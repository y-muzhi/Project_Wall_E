"""Prepare a P1 startup and drive the admitted lifecycle on the stable lock."""

from contextlib import ExitStack
import os
from uuid import uuid4

from .environment_control import CONTROL_NAME, CONTROL_ERROR, normal_stop, read_control
from .environment_files import (
    MAX_REVISION,
    canonical,
    decode,
    digest,
    persisted_write,
    read_entry,
    require,
)
from .environment_binding import EnvironmentBinding
from .environment_initialize import confirm_initialized, inspect_database, now
from .environment_installation import database_identity, sha_value, uuid_value
from .environment_ordinary import OrdinaryDatabase


def start_name(operation):
    return f'start-{operation}.v1.json'


def read_start(fd, installation, operation):
    return read_entry(
        fd, start_name(operation), owner=installation.maintenance_uid, group=installation.group
    )


def prepared_start(installation, native, release, operation, expected_control_sha256=None):
    require(uuid_value(operation), CONTROL_ERROR)
    require('recovery_replica' not in installation.description, 'RECOVERY_REPLICA_READ_ONLY')
    installation.check_identity(maintenance=True)
    with ExitStack() as resources:
        resources.enter_context(installation.lock(native))
        installation.check_hold()
        fd = resources.enter_context(installation.directory(native, 'control'))
        control = read_control(fd, installation)
        require(normal_stop(control), CONTROL_ERROR)
        if expected_control_sha256 is not None:
            require(
                sha_value(expected_control_sha256)
                and digest(canonical(control)) == expected_control_sha256,
                CONTROL_ERROR,
            )
        try:
            pending = decode(read_start(fd, installation, control['operation_id']), CONTROL_ERROR)
        except FileNotFoundError:
            pending = None
        require(
            pending is None or pending.get('control_revision') != control['control_revision'],
            'START_RESULT_UNVERIFIED',
        )
        data_fd = resources.enter_context(installation.directory(native, 'data'))
        file_identity = database_identity(installation, data_fd)
        require(file_identity is not None, 'INITIALIZATION_NOT_CONFIRMED')
        binding = EnvironmentBinding(installation.environment_id, installation.data_generation)
        timestamp = inspect_database(installation, data_fd, file_identity, release, binding)
        require(timestamp is not None, 'INITIALIZATION_NOT_CONFIRMED')
        if control['last_opened_deployment_id'] is None:
            maintenance_fd = resources.enter_context(installation.directory(native, 'maintenance'))
            confirm_initialized(
                native,
                installation,
                maintenance_fd,
                control['operation_id'],
                file_identity,
                timestamp,
            )
        revision = control['control_revision'] + 1
        run = str(uuid4())
        receipt = {
            'format_version': 1,
            'operation_id': operation,
            'run_id': run,
            'environment_id': installation.environment_id,
            'data_generation': installation.data_generation,
            'deployment_id': installation.deployment_id,
            'configuration_sha256': installation.configuration_sha256,
            'control_revision': revision,
        }
        raw = canonical(receipt)
        persisted_write(fd, start_name(operation), raw, mode=0o440)
        new = {**control, 'operation_id': operation, 'control_revision': revision}
        persisted_write(fd, CONTROL_NAME, canonical(new), mode=0o640, replace=True)
        return {**receipt, 'start_sha256': digest(raw)}


def preparation_retirement(installation, fd, operation, before_id, before_revision, before_sha):
    require(
        uuid_value(operation)
        and uuid_value(before_id)
        and operation != before_id
        and type(before_revision) is int
        and 1 <= before_revision < MAX_REVISION - 2
        and sha_value(before_sha),
        CONTROL_ERROR,
    )
    current = read_control(fd, installation)
    before = {**current, 'operation_id': before_id, 'control_revision': before_revision}
    require(normal_stop(current) and digest(canonical(before)) == before_sha, CONTROL_ERROR)
    if current == before:
        return current, before, 'UNCHANGED'
    raw = read_start(fd, installation, operation)
    receipt = decode(raw, CONTROL_ERROR)
    prepared = {**before, 'operation_id': operation, 'control_revision': before_revision + 1}
    expected = {
        'format_version': 1,
        'operation_id': operation,
        'run_id': receipt.get('run_id'),
        'environment_id': installation.environment_id,
        'data_generation': installation.data_generation,
        'deployment_id': installation.deployment_id,
        'configuration_sha256': installation.configuration_sha256,
        'control_revision': prepared['control_revision'],
    }
    require(uuid_value(expected['run_id']) and raw == canonical(expected), CONTROL_ERROR)
    retired = {**before, 'control_revision': before_revision + 2}
    require(current in (prepared, retired), CONTROL_ERROR)
    return current, retired, 'RETIRED'


def retire_preparation(installation, native, operation, before_id, before_revision, before_sha):
    require('recovery_replica' not in installation.description, 'RECOVERY_REPLICA_READ_ONLY')
    installation.check_identity(maintenance=True)
    with installation.lock(native) as lock, installation.directory(native, 'control') as fd:
        current, target, state = preparation_retirement(
            installation, fd, operation, before_id, before_revision, before_sha
        )
        require(not os.path.lexists(installation.path('runtime') / 'walle.sock'), CONTROL_ERROR)
        lock.assert_owned()
        if current != target:
            persisted_write(fd, CONTROL_NAME, canonical(target), mode=0o640, replace=True)
        require(read_control(fd, installation) == target, CONTROL_ERROR)
        return {'state': state, 'control_revision': target['control_revision']}


class OrdinaryScope:
    recover_local_commands = True

    @property
    def recover_on_start(self):
        return not self.control['outbound_hold']

    def __init__(self, installation, native, release, resources, operation, start_sha):
        require('recovery_replica' not in installation.description, 'RECOVERY_REPLICA_READ_ONLY')
        installation.check_identity(maintenance=False)
        installation.check_hold()
        self.installation = installation
        self.lock = installation.lock(native)
        self._control_fd = resources.enter_context(installation.directory(native, 'control'))
        self._data_fd = resources.enter_context(installation.directory(native, 'data'))
        for kind in ('runtime', 'log', 'temporary', 'frontend'):
            resources.enter_context(installation.directory(native, kind))
        self.database = OrdinaryDatabase(installation, release, self._data_fd, self.lock)
        self.operation = operation
        self.start_sha = start_sha
        self.control, self.receipt = self.read_start()
        self.run_id = self.receipt['run_id']
        self.observed_at = None
        self.active = False

    def read_start(self):
        require(uuid_value(self.operation), CONTROL_ERROR)
        raw = read_start(self._control_fd, self.installation, self.operation)
        require(digest(raw) == self.start_sha, CONTROL_ERROR)
        receipt = decode(raw, CONTROL_ERROR)
        control = read_control(self._control_fd, self.installation)
        expected = {
            'format_version': 1,
            'operation_id': control['operation_id'],
            'run_id': receipt.get('run_id'),
            'environment_id': self.installation.environment_id,
            'data_generation': self.installation.data_generation,
            'deployment_id': self.installation.deployment_id,
            'configuration_sha256': self.installation.configuration_sha256,
            'control_revision': control['control_revision'],
        }
        require(
            uuid_value(receipt.get('run_id'))
            and normal_stop(control)
            and self.operation == control['operation_id']
            and raw == canonical(expected),
            CONTROL_ERROR,
        )
        return control, receipt

    def before_recovery(self):
        self.lock.assert_owned()
        self.installation.check_hold()
        control, receipt = self.read_start()
        require(control == self.control and receipt == self.receipt, CONTROL_ERROR)
        self.database.check_recovery()

    def set_control(self, admission, reason, **facts):
        self.lock.assert_owned()
        require(read_control(self._control_fd, self.installation) == self.control, CONTROL_ERROR)
        new = {
            **self.control,
            **facts,
            'control_revision': self.control['control_revision'] + 1,
            'admission': admission,
            'closed_reason': reason,
        }
        persisted_write(self._control_fd, CONTROL_NAME, canonical(new), mode=0o640, replace=True)
        self.control = new

    def start(self):
        with self.installation.host_admission():
            self.open_control()

    def open_control(self):
        self.before_recovery()
        observed_at = now()
        name = f'open-{self.run_id}.v1.json'
        record = {**self.receipt, 'start_sha256': self.start_sha, 'opened_at': observed_at}
        persisted_write(self._control_fd, name, canonical(record), mode=0o440)
        self.set_control(
            'OPEN',
            'NONE',
            open_receipt_ref=name,
            last_opened_deployment_id=self.installation.deployment_id,
        )
        self.observed_at = observed_at
        self.active = True

    def drain(self):
        if self.active:
            self.active = False
            self.set_control('DRAINING', 'NORMAL_STOP')

    def close(self):
        if self.control['admission'] == 'DRAINING':
            self.set_control('CLOSED', 'NORMAL_STOP')
