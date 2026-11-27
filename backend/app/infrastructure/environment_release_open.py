"""Promote the independently verified ordinary program under its original maintenance lock."""

import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from backend.app.management.attachment_observation import now
from backend.app.management.registry import is_timestamp

from .environment_admission import OrdinaryScope
from .environment_backup_package import read_policy
from .environment_control import (
    CONTROL_NAME,
    initial_control,
    read_control,
    read_release_transition,
    require_release_not_reverting,
)
from .environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    read_entry,
    read_protected,
    require,
)
from .environment_initialize import database_has_sidecars
from .environment_installation import read_access_policy, sha_value, uuid_value
from .environment_ordinary import check_external_effects
from .environment_release_gateway_check import (
    VERIFIED as GATEWAY_PROOF,
)
from .environment_release_gateway_check import (
    listener_inodes,
    process_epoch,
)
from .environment_release_preflight import read_reference
from .environment_release_verify import verified_release_receipt
from .environment_restore import reopen_archive

POLICY = 'release-open-policy.v1.json'
UNVERIFIED = 'RELEASE_OPEN_UNVERIFIED'
INVALID = 'RELEASE_OPEN_INTENT_MISMATCH'
GATEWAY_PROOF_MAX_SECONDS = 120


def open_inputs(installation, operation, path, expected):
    plan = read_policy(
        path,
        expected,
        POLICY,
        (
            'operation_id',
            'run_id',
            'installation_sha256',
            'transition_sha256',
            'control_sha256',
            'release_verification',
            'gateway_verification',
        ),
    )
    require(
        'deployment_slot' in installation.description
        and 'recovery_replica' not in installation.description
        and plan['operation_id'] == operation
        and uuid_value(operation)
        and uuid_value(plan['run_id'])
        and operation != plan['run_id']
        and plan['installation_sha256'] == installation.anchor_sha256
        and all(sha_value(plan[key]) for key in ('transition_sha256', 'control_sha256')),
        INVALID,
    )
    return plan


def observed_transition(fd, installation, plan):
    transition = read_release_transition(fd, installation, plan['operation_id'])
    require_release_not_reverting(fd, transition, UNVERIFIED)
    require(
        digest(canonical(transition)) == plan['transition_sha256']
        and transition['after_sha256'] == plan['control_sha256'],
        UNVERIFIED,
    )
    return transition


def expected_open_receipt(installation, plan, transition, plan_sha):
    return {
        'format_version': 1,
        'operation_id': plan['operation_id'],
        'run_id': plan['run_id'],
        'environment_id': installation.environment_id,
        'data_generation': installation.data_generation,
        'deployment_id': installation.deployment_id,
        'configuration_sha256': installation.configuration_sha256,
        'control_revision': transition['after']['control_revision'],
        'start_sha256': plan_sha,
        'transition_sha256': plan['transition_sha256'],
        'gateway_verification_sha256': plan['gateway_verification']['sha256'],
        'release_verification_sha256': plan['release_verification']['sha256'],
    }


def exact_open_time(actual, expected):
    timestamp = decode(actual, UNVERIFIED).get('opened_at')
    require(
        is_timestamp(timestamp) and actual == canonical({**expected, 'opened_at': timestamp}),
        UNVERIFIED,
    )
    return timestamp


def assert_gateway(proof, port):
    require(is_timestamp(proof['verified_at']), UNVERIFIED)
    stamp = datetime.fromisoformat(proof['verified_at'])
    require(
        0 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= GATEWAY_PROOF_MAX_SECONDS,
        UNVERIFIED,
    )
    process = exact(
        proof['gateway_process'],
        ('pid', 'uid', 'start_ticks', 'boot_id', 'listener_inode'),
        UNVERIFIED,
    )
    require(
        type(process['pid']) is int
        and 1 < process['pid'] < 2**31
        and type(process['uid']) is int
        and 0 < process['uid'] < 2**31
        and type(process['listener_inode']) is str
        and process['listener_inode'].isdigit(),
        UNVERIFIED,
    )
    expected_epoch = (process['start_ticks'], process['boot_id'])
    expected_listener = {process['listener_inode']}
    try:
        same_process = process_epoch(process['pid']) == expected_epoch
        matches = same_process and listener_inodes(os.getpid(), port) == expected_listener
    except OSError as error:
        raise EnvironmentFailure(UNVERIFIED) from error
    require(matches, UNVERIFIED)


def opening_evidence(plan, installation, transition):
    release = verified_release_receipt(plan['release_verification'], installation, transition)
    gateway = read_reference(plan['gateway_verification'], name=GATEWAY_PROOF)
    expected = {
        'format_version': 1,
        'status': 'RELEASE_GATEWAY_VERIFIED_CLOSED',
        'operation_id': plan['operation_id'],
        'target_installation_sha256': installation.anchor_sha256,
        'target_environment_id': installation.environment_id,
        'target_data_generation': installation.data_generation,
        'target_deployment_id': installation.deployment_id,
        'target_configuration_sha256': installation.configuration_sha256,
        'target_frontend_index_sha256': installation.description['deployment_slot'][
            'frontend_index_sha256'
        ],
        'target_verification_sha256': plan['release_verification']['sha256'],
        'transition_sha256': plan['transition_sha256'],
        'control_sha256': plan['control_sha256'],
    }
    more = (
        'policy_sha256',
        'gateway_stage_sha256',
        'gateway_configuration_sha256',
        'current_asset_sha256',
        'previous_asset_sha256',
    )
    access = read_access_policy(installation)
    origin = access['public_origin']
    require(
        set(gateway) == {*expected, *more, 'origin', 'gateway_process', 'verified_at'}
        and all(canonical(gateway[key]) == canonical(value) for key, value in expected.items())
        and all(sha_value(gateway[key]) for key in more)
        and gateway['origin'] == origin
        and plan['run_id'] != release['run_id']
        and is_timestamp(gateway['verified_at'])
        and gateway['verified_at'] >= release['verified_at'],
        UNVERIFIED,
    )
    assert_gateway(gateway, urlsplit(origin).port or 443)


class ReleaseOpenScope(OrdinaryScope):
    recover_local_commands = False

    @property
    def recover_on_start(self):
        return self.installation.restore_generation_sha256 is None

    def __init__(self, installation, native, release, resources, operation, path, expected):
        self.open_path = path
        self.open_sha = expected
        self.open_plan = open_inputs(installation, operation, path, expected)
        self.verified_initial_data = False
        super().__init__(installation, native, release, resources, operation, expected)

    def read_start(self):
        installation = self.installation
        require(digest(read_protected(self.open_path)) == self.open_sha, UNVERIFIED)
        control = read_control(self._control_fd, installation)
        transition = observed_transition(self._control_fd, installation, self.open_plan)
        require(control == transition['after'], UNVERIFIED)
        opening_evidence(self.open_plan, installation, transition)
        self.transition = transition
        return control, {
            'format_version': 1,
            'operation_id': self.operation,
            'run_id': self.open_plan['run_id'],
            'environment_id': installation.environment_id,
            'data_generation': installation.data_generation,
            'deployment_id': installation.deployment_id,
            'configuration_sha256': installation.configuration_sha256,
            'control_revision': control['control_revision'],
        }

    def preflight(self):
        self.lock.assert_owned()
        require(not database_has_sidecars(self.database.path), UNVERIFIED)
        super().preflight()

    def before_recovery(self):
        self.lock.assert_owned()
        self.installation.check_hold()
        if not self.recover_on_start:
            self.check_frozen_restore()
            return
        if not self.verified_initial_data:
            database = self.database
            database._check_file()
            require(database.identity == self.transition['database_identity'], UNVERIFIED)
            require(not database_has_sidecars(database.path), UNVERIFIED)
            _, facts = reopen_archive(database.path, database.schema_release, database.binding)
            require(facts.sha256 == self.transition['logical_content_sha256'], UNVERIFIED)
            database._check_file()
        super().before_recovery()
        self.verified_initial_data = True

    def check_frozen_restore(self):
        control, receipt = self.read_start()
        require(control == self.control and receipt == self.receipt, UNVERIFIED)
        database = self.database
        database._check_file()
        require(database.identity == self.transition['database_identity'], UNVERIFIED)
        require(not database_has_sidecars(database.path), UNVERIFIED)
        _, facts = reopen_archive(
            database.path, database.schema_release, database.binding, inspect=check_external_effects
        )
        require(
            facts.sha256 == self.transition['logical_content_sha256']
            and not database_has_sidecars(database.path),
            UNVERIFIED,
        )
        database._check_file()

    def open_control(self):
        self.before_recovery()
        installation = self.installation
        name = f'open-{self.run_id}.v1.json'
        receipt = expected_open_receipt(
            installation, self.open_plan, self.transition, self.open_sha
        )
        try:
            actual = read_entry(
                self._control_fd, name, owner=installation.application_uid, group=installation.group
            )
        except FileNotFoundError:
            raw = canonical({**receipt, 'opened_at': now()})
            persisted_write(self._control_fd, name, raw, mode=0o440)
            actual = read_entry(
                self._control_fd, name, owner=installation.application_uid, group=installation.group
            )
        exact_open_time(actual, receipt)
        self.lock.assert_owned()
        before, prior_receipt = self.read_start()
        require(before == self.control and prior_receipt == self.receipt, UNVERIFIED)
        desired = {
            **initial_control(installation, self.operation),
            'control_revision': before['control_revision'] + 1,
            'admission': 'OPEN',
            'closed_reason': 'NONE',
            'last_opened_deployment_id': installation.deployment_id,
            'open_receipt_ref': name,
        }
        persisted_write(
            self._control_fd, CONTROL_NAME, canonical(desired), mode=0o640, replace=True
        )
        try:
            require(read_control(self._control_fd, installation) == desired, UNVERIFIED)
        except (OSError, RuntimeError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        self.control = desired
        self.observed_at = now()
        self.active = True


def observe_release_open(native, installation, plan, plan_sha):
    installation.check_identity(maintenance=True)
    installation.check_hold(offline=True)
    with installation.directory(native, 'control') as fd:
        transition = observed_transition(fd, installation, plan)
        first = read_control(fd, installation)
        name = f'open-{plan["run_id"]}.v1.json'
        reference = {
            'operation_id': plan['operation_id'],
            'run_id': plan['run_id'],
            'environment_id': installation.environment_id,
            'data_generation': installation.data_generation,
            'deployment_id': installation.deployment_id,
            'configuration_sha256': installation.configuration_sha256,
            'control_revision': first['control_revision'],
            'admission': first['admission'],
        }
        try:
            raw = read_entry(fd, name, owner=installation.application_uid, group=installation.group)
        except FileNotFoundError:
            raw = None
        require(read_control(fd, installation) == first, UNVERIFIED)
        if first == transition['after']:
            if raw is None:
                return {'status': 'RELEASE_OPEN_NOT_PREPARED', **reference}
            exact_open_time(raw, expected_open_receipt(installation, plan, transition, plan_sha))
            return {'status': 'PENDING_RECONCILIATION', **reference}
        require(
            raw is not None
            and first['last_opened_deployment_id'] == installation.deployment_id
            and first['open_receipt_ref'] == name
            and first['control_revision'] > transition['after']['control_revision'],
            UNVERIFIED,
        )
        opened_at = exact_open_time(
            raw, expected_open_receipt(installation, plan, transition, plan_sha)
        )
        return {
            'status': 'RELEASE_OPEN_CONFIRMED',
            **reference,
            'opened_at': opened_at,
            'open_receipt_sha256': digest(raw),
        }
