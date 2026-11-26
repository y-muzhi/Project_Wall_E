"""Prepare, start and reconcile one ordinary Linux service through its fixed host unit."""

import fcntl
import grp
import os
import pwd
import re
import stat
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from backend.app.infrastructure.environment_admission import read_start
from backend.app.infrastructure.environment_control import normal_stop, read_control
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles
from backend.app.infrastructure.environment_retained_data import retained_data_unit_properties

from .attachment_observation import candidate_environment, machine_clock, now
from .host_capacity import available_memory_bytes
from .operation_contract import (
    CONFLICT,
    INVALID,
    RESOURCE,
    SCOPE,
    installed_record,
    path_reference,
    version,
)
from .registry import is_timestamp
from .runtime_capacity import load_capacity
from .runtime_observation import (
    CGROUP_ROOT,
    SYSTEM_PYTHON,
    SYSTEMCTL,
    capture_runtime,
    cgroup_processes,
    expected_command,
    launch_wrapper,
    trusted_executable,
    unit_facts,
)
from .runtime_observation import (
    NOT_READY as APPLICATION_UNREADY,
)
from .runtime_observation import (
    POLICY as RUNTIME_POLICY,
)
from .runtime_observation import (
    READY as APPLICATION_READY,
)

START_POLICY = 'managed-start.v1.json'
SYSTEMD_RUN = Path('/usr/bin/systemd-run')
SETPRIV = Path('/usr/bin/setpriv')
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'TZ': 'UTC', 'SYSTEMD_COLORS': '0'}
UNVERIFIED = 'MANAGEMENT_START_EFFECT_UNVERIFIED'
NOT_READY = 'MANAGEMENT_NOT_READY'
OBSERVED_STARTED = ('READY', 'RUNNING_UNREADY')


def load_start(catalog, path, expected):
    require(path.is_absolute() and path.name == START_POLICY and sha_value(expected), INVALID)
    record = installed_record(path, expected)
    cancellation = (
        ('previous_cancel_control_key',) if 'previous_cancel_control_key' in record else ()
    )
    adoption = ('previous_registry_adoption',) if 'previous_registry_adoption' in record else ()
    plan = exact(
        record,
        (
            'format_version',
            *catalog.scope,
            'candidate_ref',
            'candidate_sha256',
            'start_operation_id',
            'previous_stop_operation_id',
            *cancellation,
            *adoption,
            'launcher',
            'home',
            'temporary',
            'maintenance_home',
            'maintenance_temporary',
            'systemctl_sha256',
            'systemd_run_sha256',
            'setpriv_sha256',
            'memory_bytes',
            'tasks',
            'cpu_percent',
        ),
        INVALID,
    )
    require(type(plan['format_version']) is int and plan['format_version'] == 1, INVALID)
    require(all(plan[key] == value for key, value in catalog.scope.items()), SCOPE)
    require(
        all(uuid_value(plan[key]) for key in ('candidate_ref', 'start_operation_id'))
        and (
            plan['previous_stop_operation_id'] is None
            or uuid_value(plan['previous_stop_operation_id'])
        )
        and (
            not cancellation
            or (
                plan['previous_stop_operation_id'] is None
                and uuid_value(plan['previous_cancel_control_key'])
            )
        )
        and all(
            sha_value(plan[key])
            for key in (
                'candidate_sha256',
                'systemctl_sha256',
                'systemd_run_sha256',
                'setpriv_sha256',
            )
        )
        and type(plan['memory_bytes']) is int
        and 128 * 1024**2 <= plan['memory_bytes'] <= 2 * 1024**3
        and type(plan['tasks']) is int
        and 16 <= plan['tasks'] <= 512
        and type(plan['cpu_percent']) is int
        and 25 <= plan['cpu_percent'] <= 200,
        INVALID,
    )
    if adoption:
        from .registry_recovery_restart import recovery_predecessor

        recovery_predecessor(plan)
    return plan


def verify_application_groups(environment):
    try:
        user = pwd.getpwuid(environment.application_uid)
    except KeyError as error:
        raise EnvironmentFailure(RESOURCE) from error
    require(
        user.pw_gid == environment.group
        and set(os.getgrouplist(user.pw_name, user.pw_gid)) == {environment.group},
        RESOURCE,
    )


def verify_accounts_and_paths(plan, environment):
    user = pwd.getpwuid(environment.application_uid)
    group = grp.getgrgid(environment.group)
    require(
        user.pw_gid == group.gr_gid
        and user.pw_shell in ('/usr/sbin/nologin', '/sbin/nologin', '/bin/false'),
        RESOURCE,
    )
    areas = {}
    for key in ('home', 'temporary', 'maintenance_home', 'maintenance_temporary'):
        path = absolute(plan[key], INVALID)
        expected = (
            environment.maintenance_uid
            if key.startswith('maintenance_')
            else environment.application_uid
        )
        with protected_directory(path.parent) as parent:
            fd = os.open(
                path.name,
                os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC | os.O_RDONLY,
                dir_fd=parent,
            )
            try:
                props = os.fstat(fd)
                require(
                    props.st_uid == expected
                    and props.st_gid == environment.group
                    and stat.S_IMODE(props.st_mode) == 0o700
                    and identity(props) == identity(path.lstat()),
                    RESOURCE,
                )
                no_acl(fd)
            finally:
                os.close(fd)
        areas[key] = path
    require(
        all(not a.is_relative_to(b) for a in areas.values() for b in areas.values() if a != b)
        and len(set(areas.values())) == len(areas),
        INVALID,
    )


@contextmanager
def control_directory(environment):
    with protected_directory(environment.environment_root) as parent:
        fd = os.open(
            'control', os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=parent
        )
        try:
            require(identity(os.fstat(fd)) == environment.roots['control'], RESOURCE)
            yield fd
        finally:
            os.close(fd)


def prepared(environment, operation, *, require_closed=False):
    with control_directory(environment) as fd:
        control = read_control(fd, environment)
        try:
            raw = read_start(fd, environment, operation)
        except FileNotFoundError:
            return None
        result = exact(
            decode(raw, UNVERIFIED),
            (
                'format_version',
                'operation_id',
                'run_id',
                'environment_id',
                'data_generation',
                'deployment_id',
                'configuration_sha256',
                'control_revision',
            ),
            UNVERIFIED,
        )
        require(
            type(result['format_version']) is int
            and result['format_version'] == 1
            and result['operation_id'] == operation == control['operation_id']
            and uuid_value(result['run_id'])
            and all(
                result[key] == getattr(environment, key)
                for key in (
                    'environment_id',
                    'data_generation',
                    'deployment_id',
                    'configuration_sha256',
                )
            )
            and version(result['control_revision'])
            and result['control_revision'] <= control['control_revision']
            and (
                not require_closed
                or (
                    normal_stop(control)
                    and result['control_revision'] == control['control_revision']
                )
            ),
            UNVERIFIED,
        )
        return {**result, 'start_sha256': digest(raw)}


def record_at(fd, name):
    try:
        return decode(read_entry(fd, name, owner=0), UNVERIFIED)
    except FileNotFoundError:
        return None


def write_record(fd, name, record, *, replace=False):
    persisted_write(fd, name, canonical(record), mode=0o444, replace=replace)


def original_record(fd, name, common):
    found = record_at(fd, name)
    if found is None:
        return None
    exact(
        found,
        (*common, 'state', 'recorded_at', 'boot_id', 'prepared', 'runtime', 'observation'),
        UNVERIFIED,
    )
    require(all(found[key] == value for key, value in common.items()), CONFLICT)
    state = found['state']
    require(
        state in ('RESERVED', 'PREPARING', 'STARTING', *OBSERVED_STARTED)
        and is_timestamp(found['recorded_at'])
        and uuid_value(found['boot_id'])
        and (
            type(found['prepared']) is dict
            if state in ('STARTING', *OBSERVED_STARTED)
            else found['prepared'] is None
        )
        and (
            type(found['runtime']) is dict
            if state in OBSERVED_STARTED
            else found['runtime'] is None
        )
        and (
            type(found['observation']) is dict
            if state in OBSERVED_STARTED
            else found['observation'] is None
        ),
        UNVERIFIED,
    )
    return found


def check_environment_lease(fd, name, common, plan, catalog, environment, *, verify_recovery=None):
    lease = record_at(fd, name)
    claim = {
        key: common[key] for key in ('environment_id', 'start_operation_id', 'start_policy_sha256')
    }
    if lease == claim:
        return lease, claim
    if 'previous_registry_adoption' in plan:
        require(lease is None and verify_recovery is not None, CONFLICT)
        verify_recovery()
        return lease, claim
    previous_id = plan['previous_stop_operation_id']
    previous_cancel = plan.get('previous_cancel_control_key')
    if lease is not None:
        exact(lease, claim, UNVERIFIED)
        require(
            uuid_value(lease['start_operation_id'])
            and sha_value(lease['start_policy_sha256'])
            and lease['environment_id'] == common['environment_id'],
            RESOURCE,
        )
    stop = record_at(fd, 'stop-' + previous_id + '.v1.json') if previous_id is not None else None
    if stop is not None:
        from .release_restart import verify_release_stop

        if verify_release_stop(catalog, fd, environment, plan, previous_id, stop):
            return lease, claim
    if lease is None:
        require(previous_id is None and previous_cancel is None, CONFLICT)
    else:
        require(uuid_value(previous_id) or uuid_value(previous_cancel), CONFLICT)
        old_operation = lease['start_operation_id']
        if previous_cancel is not None:
            from .runtime_cancel import retirement_proof
            from .runtime_early_cancel import early_effect

            expected = {
                **common,
                'start_operation_id': old_operation,
                'start_policy_sha256': lease['start_policy_sha256'],
            }
            previous = retirement_proof(fd, expected, previous_cancel)
            if previous is None:
                require(early_effect(fd, expected, previous_cancel) is not None, CONFLICT)
            else:
                require(previous['cutoff'] in ('RESERVED', 'PREPARING'), CONFLICT)
            return lease, claim
        old = record_at(fd, 'start-' + old_operation + '.v1.json')
        require(
            old is not None
            and old['state'] == 'READY'
            and stop is not None
            and stop['state'] == 'STOPPED'
            and old['start_policy_sha256'] == lease['start_policy_sha256']
            and all(
                stop[key] == common[key] == old[key]
                for key in (
                    'manager_id',
                    'host_id',
                    'registry_generation',
                    'environment_id',
                )
            )
            and stop['stop_operation_id'] == previous_id
            and stop['start_operation_id'] == old_operation
            and stop['run_id'] == old['prepared']['run_id']
            and stop['runtime_policy_sha256'] == old['runtime']['sha256']
            and stop['observation']['reason_code'] == 'MANAGED_STOP_CONFIRMED',
            CONFLICT,
        )
    return lease, claim


def run_bounded(command, seconds):
    try:
        subprocess.run(
            command,
            env=ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


PREPARATION_UNVERIFIED = 'MANAGEMENT_PREPARATION_UNVERIFIED'


def preparation_baseline(fd, common, boot):
    baseline = record_at(fd, 'prepare-base-' + common['start_operation_id'] + '.v1.json')
    if baseline is None:
        return None
    exact(
        baseline,
        (*common, 'boot_id', 'control_operation_id', 'control_revision', 'control_sha256'),
        PREPARATION_UNVERIFIED,
    )
    require(
        all(baseline[key] == value for key, value in common.items())
        and baseline['boot_id'] == boot
        and uuid_value(baseline['control_operation_id'])
        and baseline['control_operation_id'] != common['start_operation_id']
        and version(baseline['control_revision'])
        and baseline['control_revision'] < MAX_REVISION - 2
        and sha_value(baseline['control_sha256']),
        PREPARATION_UNVERIFIED,
    )
    return baseline


def capture_preparation(fd, common, boot, environment, native):
    baseline = preparation_baseline(fd, common, boot)
    with (
        environment.lock(native) as lock,
        environment.host_admission(),
        control_directory(environment) as control,
    ):
        before = read_control(control, environment)
        require(
            normal_stop(before)
            and before['operation_id'] != common['start_operation_id']
            and before['control_revision'] < MAX_REVISION - 2
            and not os.path.lexists(environment.path('runtime') / 'walle.sock'),
            PREPARATION_UNVERIFIED,
        )
        expected = {
            **common,
            'boot_id': boot,
            'control_operation_id': before['operation_id'],
            'control_revision': before['control_revision'],
            'control_sha256': digest(canonical(before)),
        }
        lock.assert_owned()
        if baseline is None:
            write_record(fd, 'prepare-base-' + common['start_operation_id'] + '.v1.json', expected)
        else:
            require(baseline == expected, PREPARATION_UNVERIFIED)
    return expected


PREPARATION_PROPERTIES = (
    'Id',
    'LoadState',
    'ActiveState',
    'SubState',
    'MainPID',
    'ExecMainStatus',
    'ExecMainCode',
    'InvocationID',
    'ControlGroup',
    'Description',
    'Type',
    'User',
    'Group',
    'Result',
    'SendSIGKILL',
    'KillMode',
    'RemainAfterExit',
    'Restart',
    'Delegate',
    'NoNewPrivileges',
    'MemoryMax',
    'TasksMax',
    'CapabilityBoundingSet',
)


def preparation_properties(plan, checksum):
    return {
        'Description': 'WALL-E startup preparation ' + checksum,
        'Type': 'oneshot',
        'RemainAfterExit': 'yes',
        'Restart': 'no',
        'KillMode': 'control-group',
        'SendSIGKILL': 'no',
        'SendSIGHUP': 'no',
        'TimeoutStartSec': '35s',
        'TimeoutStopSec': '20s',
        'User': 'root',
        'Group': 'root',
        'CapabilityBoundingSet': 'CAP_SETUID CAP_SETGID',
        'Delegate': 'no',
        'NoNewPrivileges': 'yes',
        'MemoryMax': str(plan['memory_bytes']),
        'TasksMax': str(plan['tasks']),
        'CPUQuota': str(plan['cpu_percent']) + '%',
        'CPUQuotaPeriodSec': '100ms',
        'StandardOutput': 'null',
        'StandardError': 'null',
    }


def preparation_group_empty(unit):
    group = CGROUP_ROOT / 'system.slice' / unit
    if not os.path.lexists(group):
        return True
    try:
        return not cgroup_processes(group)
    except FileNotFoundError:
        return not os.path.lexists(group)


def preparation_unit_identity(unit, properties):
    facts = unit_facts(unit, properties=PREPARATION_PROPERTIES)
    expected = {
        'LoadState': 'loaded',
        **{
            key: properties[key]
            for key in (
                'Description',
                'Type',
                'User',
                'Group',
                'KillMode',
                'SendSIGKILL',
                'RemainAfterExit',
                'Restart',
                'Delegate',
                'NoNewPrivileges',
                'MemoryMax',
                'TasksMax',
            )
        },
    }
    invocation = facts.get('InvocationID', '')
    require(
        all(facts.get(key) == value for key, value in expected.items())
        and re.fullmatch(r'[0-9a-f]{32}', invocation) is not None
        and invocation != '0' * 32
        and set(facts.get('CapabilityBoundingSet', '').lower().split())
        == {'cap_setuid', 'cap_setgid'},
        PREPARATION_UNVERIFIED,
    )
    return facts


def observe_preparation(unit, properties):
    facts = preparation_unit_identity(unit, properties)
    require(
        all(
            facts[key] == value
            for key, value in {
                'ActiveState': 'active',
                'SubState': 'exited',
                'MainPID': '0',
                'Result': 'success',
                'ExecMainCode': '1',
                'ExecMainStatus': '0',
            }.items()
        )
        and preparation_group_empty(unit)
        and unit_facts(unit, properties=PREPARATION_PROPERTIES) == facts,
        PREPARATION_UNVERIFIED,
    )
    return facts['InvocationID']


def launch_preparation_unit(unit, properties, command):
    run_bounded(
        [
            str(SYSTEMD_RUN),
            '--system',
            '--unit',
            unit,
            *[f'--property={key}={value}' for key, value in properties.items()],
            '--',
            *command,
        ],
        45,
    )


def preparation_unit_quiet(unit, invocation=None, *, cancelled=False):
    facts = unit_facts(unit)
    inactive = ('inactive', 'failed') if cancelled else ('inactive',)
    allowed_invocations = ('', '0' * 32, invocation)
    return (
        facts['LoadState'] in ('loaded', 'not-found')
        and facts.get('ActiveState') in inactive
        and facts.get('MainPID', '0') == '0'
        and facts.get('InvocationID', '') in allowed_invocations
        and preparation_group_empty(unit)
    )


def stop_preparation_unit(unit, properties, invocation):
    require(observe_preparation(unit, properties) == invocation, PREPARATION_UNVERIFIED)
    run_bounded([str(SYSTEMCTL), '--system', '--no-pager', 'stop', unit], 25)
    require(preparation_unit_quiet(unit, invocation), PREPARATION_UNVERIFIED)


def preparation_reference(common, boot, command):
    return {
        **common,
        'unit': f'walle-prep-{common["environment_id"]}-{common["start_operation_id"]}.service',
        'command_sha256': digest(canonical({'argv': command})),
        'boot_id': boot,
    }


def preparation_record(fd, expected):
    original = expected['start_operation_id']
    record = record_at(fd, 'prepare-' + original + '.v1.json')
    if record is None:
        return None
    exact(record, (*expected, 'state', 'invocation_id', 'receipt_sha256'), PREPARATION_UNVERIFIED)
    require(all(record[key] == value for key, value in expected.items()), PREPARATION_UNVERIFIED)
    if record['state'] == 'ISSUED':
        require(
            record['invocation_id'] is None and record['receipt_sha256'] is None,
            PREPARATION_UNVERIFIED,
        )
    else:
        require(
            record['state'] in ('OBSERVED', 'RELEASED')
            and type(record['invocation_id']) is str
            and re.fullmatch(r'[0-9a-f]{32}', record['invocation_id']) is not None
            and record['invocation_id'] != '0' * 32
            and sha_value(record['receipt_sha256']),
            PREPARATION_UNVERIFIED,
        )
    return record


def finish_preparation(fd, common, plan, environment, command, *, launch):
    original = common['start_operation_id']
    expected = preparation_reference(common, machine_clock()[0], command)
    unit = expected['unit']
    properties = preparation_properties(plan, expected['command_sha256'])
    name = 'prepare-' + original + '.v1.json'
    record = preparation_record(fd, expected)
    if launch:
        with environment.host_admission():
            require(
                record is None and unit_facts(unit)['LoadState'] == 'not-found',
                PREPARATION_UNVERIFIED,
            )
            record = {**expected, 'state': 'ISSUED', 'invocation_id': None, 'receipt_sha256': None}
            write_record(fd, name, record)
        launch_preparation_unit(unit, properties, command)
    require(record is not None, PREPARATION_UNVERIFIED)
    receipt = prepared(environment, original)
    require(receipt is not None, PREPARATION_UNVERIFIED)
    if record['state'] == 'ISSUED':
        record = {
            **record,
            'state': 'OBSERVED',
            'invocation_id': observe_preparation(unit, properties),
            'receipt_sha256': receipt['start_sha256'],
        }
        write_record(fd, name, record, replace=True)
    require(record['receipt_sha256'] == receipt['start_sha256'], PREPARATION_UNVERIFIED)
    if not preparation_unit_quiet(unit, record['invocation_id']):
        require(record['state'] == 'OBSERVED', PREPARATION_UNVERIFIED)
        stop_preparation_unit(unit, properties, record['invocation_id'])
    require(prepared(environment, original) == receipt, PREPARATION_UNVERIFIED)
    if record['state'] == 'OBSERVED':
        write_record(fd, name, {**record, 'state': 'RELEASED'}, replace=True)
    return receipt


def available_memory(memory_bytes):
    require(available_memory_bytes() >= memory_bytes, NOT_READY)


def preparation_command(args, plan, environment, launcher, action):
    return [
        str(SETPRIV),
        '--reuid',
        str(environment.maintenance_uid),
        '--regid',
        str(environment.group),
        '--clear-groups',
        '--no-new-privs',
        '--',
        str(SYSTEM_PYTHON),
        '-I',
        '-B',
        '-S',
        str(launcher),
        action,
        '--root',
        str(args.root),
        '--home',
        plan['maintenance_home'],
        '--temporary',
        plan['maintenance_temporary'],
        '--project',
        str(environment.project),
        '--anchor',
        str(environment.anchor),
        '--runtime-entry',
        str(args.runtime_entry),
        '--sha256',
        args.sha256,
        '--anchor-sha256',
        environment.anchor_sha256,
        '--operation-id',
        plan['start_operation_id'],
    ]


def prepare_command(args, plan, environment, launcher, baseline=None):
    command = preparation_command(args, plan, environment, launcher, 'prepare-start')
    if baseline is not None:
        command.extend(('--before-control-sha256', baseline['control_sha256']))
    return command


def startup_command(args, plan, booted, environment, launcher, executable, unit):
    native = {
        **plan,
        'operation_id': booted['operation_id'],
        'start_sha256': booted['start_sha256'],
        '_installation_sha256': environment.anchor_sha256,
    }
    if 'release_open_policy' in booted:
        native['release_open_policy'] = booted['release_open_policy']
    child = expected_command(args, native, environment, executable, launcher)
    wrapper = launch_wrapper(child)
    properties = {
        'Type': 'exec',
        'Restart': 'no',
        'KillMode': 'control-group',
        'SendSIGKILL': 'no',
        'SendSIGHUP': 'no',
        'KillSignal': 'SIGTERM',
        'TimeoutStopSec': '20s',
        'Delegate': 'no',
        'User': str(environment.application_uid),
        'Group': str(environment.group),
        'NoNewPrivileges': 'yes',
        'MemoryMax': str(plan['memory_bytes']),
        'TasksMax': str(plan['tasks']),
        'CPUQuota': str(plan['cpu_percent']) + '%',
        'CPUQuotaPeriodSec': '100ms',
        'StandardOutput': 'null',
        'StandardError': 'null',
        **retained_data_unit_properties(environment),
    }
    return [
        str(SYSTEMD_RUN),
        '--system',
        '--collect',
        '--unit',
        unit,
        '--description',
        'WALL-E ordinary managed service',
        *(f'--property={key}={value}' for key, value in properties.items()),
        '--',
        *wrapper,
    ]


def runtime_result(
    catalog, args, entry, plan, booted, environment, unit, boot, *, wait, wait_seconds=80
):
    end = time.monotonic() + (wait_seconds if wait else 0)
    while True:
        facts = unit_facts(unit)
        if facts.get('ActiveState') == 'active':
            with control_directory(environment) as fd:
                control = read_control(fd, environment)
            if control['admission'] == 'OPEN':
                break
        if time.monotonic() >= end or facts.get('ActiveState') in ('inactive', 'failed'):
            raise EnvironmentFailure(UNVERIFIED, uncertain=True)
        time.sleep(0.25)
    require(machine_clock()[0] == boot, RESOURCE)
    directory = catalog.directory / 'observations' / ('start-runtime-' + booted['operation_id'])
    with protected_directory(directory.parent) as parent:
        try:
            os.mkdir(directory.name, 0o755, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    policy = {
        'format_version': 1,
        **catalog.scope,
        'candidate_ref': plan['candidate_ref'],
        'candidate_sha256': plan['candidate_sha256'],
        'operation_id': booted['operation_id'],
        'run_id': booted['run_id'],
        'boot_id': boot,
        'invocation_id': facts['InvocationID'],
        'start_sha256': booted['start_sha256'],
        'systemctl_sha256': plan['systemctl_sha256'],
        'launcher': plan['launcher'],
        'home': plan['home'],
        'temporary': plan['temporary'],
        'memory_bytes': plan['memory_bytes'],
        'tasks': plan['tasks'],
        'cpu_quota_usec': plan['cpu_percent'] * 1000,
        'cpu_period_usec': 100_000,
    }
    if 'release_open_policy' in booted:
        policy['release_open_policy'] = booted['release_open_policy']
    raw = canonical(policy)
    with protected_directory(directory) as target:
        current = record_at(target, RUNTIME_POLICY)
        if current is None:
            write_record(target, RUNTIME_POLICY, policy)
        else:
            require(current == policy, UNVERIFIED)
    ref = {'path': str(directory / RUNTIME_POLICY), 'sha256': digest(raw)}
    observed = capture_runtime(
        catalog,
        SimpleNamespace(
            runtime_policy=Path(ref['path']),
            runtime_policy_sha256=ref['sha256'],
            root=args.root,
            sha256=args.sha256,
            runtime_entry=args.runtime_entry,
        ),
        entry,
    )
    require(
        observed['state'] == 'RUNNING'
        and observed['reason_code'] in (APPLICATION_READY, APPLICATION_UNREADY),
        UNVERIFIED,
    )
    return ref, observed


def host_registry_call(args, entry, registry, policy, program, executable, action, request):
    environment_vars = {
        'HOME': str(policy.home),
        'TMPDIR': str(policy.temporary),
        'PATH': '/usr/bin:/bin',
        'LANG': 'C.UTF-8',
        'TZ': 'UTC',
    }
    command = [
        str(SETPRIV),
        '--reuid',
        str(registry.uid),
        '--regid',
        str(registry.gid),
        '--clear-groups',
        '--no-new-privs',
        '--',
        str(executable),
        *entry['FLAGS'],
        str(program),
        action,
        '--root',
        str(args.root),
        '--sha256',
        args.sha256,
        '--project',
        str(args.project),
        '--program-sha256',
        args.program_sha256,
        '--runtime-entry',
        str(args.runtime_entry),
        '--anchor',
        str(args.anchor),
        '--anchor-sha256',
        args.anchor_sha256,
        '--catalog',
        str(args.catalog),
        '--catalog-sha256',
        args.catalog_sha256,
        '--home',
        str(policy.home),
        '--temporary',
        str(policy.temporary),
    ]
    try:
        receipt = subprocess.run(
            command,
            env=environment_vars,
            cwd=policy.temporary,
            input=canonical(request),
            capture_output=True,
            timeout=25,
            check=False,
        )
        if receipt.returncode == 2:
            raise EnvironmentFailure(RESOURCE)
        require(receipt.returncode == 0, NOT_READY)
        return decode(receipt.stdout, NOT_READY)
    except (OSError, subprocess.SubprocessError) as error:
        raise EnvironmentFailure(NOT_READY, uncertain=True) from error


def authorize_host_start(
    args, entry, registry, policy, plan, environment, program, executable, boot
):
    request = {
        'operation_id': plan['start_operation_id'],
        'environment_id': environment.environment_id,
        'configuration_sha256': environment.configuration_sha256,
        'data_generation': environment.data_generation,
        'deployment_id': environment.deployment_id,
        'capacity_sha256': policy.sha256,
        'limits': {
            **{key: plan[key] for key in ('memory_bytes', 'cpu_percent', 'tasks')},
            'run_slots': 1,
        },
        'start_policy_sha256': args.start_policy_sha256,
        'boot_id': boot,
    }
    decision = exact(
        host_registry_call(
            args, entry, registry, policy, program, executable, '_admit-runtime', request
        ),
        ('admission', 'dispatch_allowed'),
        NOT_READY,
    )
    require(
        decision['admission'] == request and type(decision['dispatch_allowed']) is bool, NOT_READY
    )
    return decision['dispatch_allowed']


def record_application_dispatch(fd, name, record, environment, native, booted, unit):
    with environment.lock(native) as lock, environment.host_admission():
        require(
            record['boot_id'] == machine_clock()[0]
            and prepared(environment, record['start_operation_id'], require_closed=True) == booted
            and not os.path.lexists(environment.path('runtime') / 'walle.sock')
            and unit_facts(unit)['LoadState'] == 'not-found',
            UNVERIFIED,
        )
        verify_application_groups(environment)
        lock.assert_owned()
        starting = {**record, 'state': 'STARTING', 'prepared': booted}
        write_record(fd, name, starting, replace=True)
        return starting


def start_runtime(catalog, args, entry, registry, program):
    require(os.geteuid() == 0, RESOURCE)
    plan = load_start(catalog, args.start_policy, args.start_policy_sha256)
    candidate = catalog.candidate(plan['candidate_ref'], plan['candidate_sha256'])
    environment = candidate_environment(candidate, args.sha256)
    operation = plan['start_operation_id']
    common = {
        'format_version': 1,
        **catalog.scope,
        'environment_id': environment.environment_id,
        'start_operation_id': operation,
        'start_policy_sha256': args.start_policy_sha256,
    }
    name = 'start-' + operation + '.v1.json'
    claim = 'start-claim-' + environment.environment_id + '.v1.json'
    unit = f'walle-env-{environment.environment_id}-{operation}.service'
    with protected_directory(catalog.directory) as host:
        try:
            fcntl.flock(host, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnvironmentFailure(NOT_READY) from error
        with protected_directory(catalog.directory / 'observations') as fd:
            record = original_record(fd, name, common)
            if record and record['state'] == 'READY':
                return record
            launcher, launcher_pin = path_reference(plan['launcher'])
            require(
                launcher == environment.project / 'tools/linux_runtime/serve_environment.py',
                RESOURCE,
            )
            trusted_executable(launcher, launcher_pin, script=True)
            trusted_executable(SYSTEMCTL, plan['systemctl_sha256'])
            trusted_executable(SYSTEMD_RUN, plan['systemd_run_sha256'])
            trusted_executable(SETPRIV, plan['setpriv_sha256'])
            verify_accounts_and_paths(plan, environment)
            if record is None or record['state'] in ('RESERVED', 'PREPARING'):
                verify_application_groups(environment)
            environment.check_hold()
            require(
                entry['verify_program'](environment.project)
                == environment.description['program_source']['sha256'],
                RESOURCE,
            )
            manifest, _ = entry['verify_runtime'](args.root, args.sha256)
            executable = args.root / manifest['python']['executable_ref']
            boot = machine_clock()[0]
            if record is not None:
                require(record['boot_id'] == boot, UNVERIFIED)
            if record is None or record['state'] == 'RESERVED':
                available_memory(plan['memory_bytes'])
                require(unit_facts(unit)['LoadState'] == 'not-found', CONFLICT)

            def verify_recovery():
                from .registry_recovery_restart import verify_adopted_restart

                verify_adopted_restart(
                    NativeEnvironmentFiles(args.root), registry, args, catalog, environment, plan
                )

            lease, bound = check_environment_lease(
                fd, claim, common, plan, catalog, environment, verify_recovery=verify_recovery
            )
            policy = load_capacity(catalog)
            allowed = authorize_host_start(
                args, entry, registry, policy, plan, environment, program, executable, boot
            )
            require(
                allowed
                or (record is not None and record['state'] in ('STARTING', 'RUNNING_UNREADY')),
                CONFLICT,
            )
            if record is None:
                record = {
                    **common,
                    'state': 'RESERVED',
                    'recorded_at': now(),
                    'boot_id': boot,
                    'prepared': None,
                    'runtime': None,
                    'observation': None,
                }
                write_record(fd, name, record)
            if lease != bound:
                write_record(fd, claim, bound, replace=lease is not None)
            dispatched = record['state'] in ('STARTING', 'RUNNING_UNREADY')
            try:
                require(record['boot_id'] == machine_clock()[0], UNVERIFIED)
                baseline = preparation_baseline(fd, common, boot)
                if record['state'] == 'RESERVED':
                    available_memory(plan['memory_bytes'])
                    require(unit_facts(unit)['LoadState'] == 'not-found', CONFLICT)
                    baseline = capture_preparation(
                        fd, common, boot, environment, NativeEnvironmentFiles(args.root)
                    )
                    record = {**record, 'state': 'PREPARING'}
                    write_record(fd, name, record, replace=True)
                if dispatched:
                    booted = prepared(environment, operation)
                    require(booted is not None, UNVERIFIED)
                else:
                    booted = finish_preparation(
                        fd,
                        common,
                        plan,
                        environment,
                        prepare_command(args, plan, environment, launcher, baseline),
                        launch=baseline is not None
                        and record_at(fd, 'prepare-' + operation + '.v1.json') is None,
                    )
                if dispatched:
                    require(record['prepared'] == booted, UNVERIFIED)
                else:
                    require(
                        authorize_host_start(
                            args,
                            entry,
                            registry,
                            policy,
                            plan,
                            environment,
                            program,
                            executable,
                            boot,
                        ),
                        CONFLICT,
                    )
                    available_memory(plan['memory_bytes'])
                    command = startup_command(
                        args, plan, booted, environment, launcher, executable, unit
                    )
                    record = record_application_dispatch(
                        fd,
                        name,
                        record,
                        environment,
                        NativeEnvironmentFiles(args.root),
                        booted,
                        unit,
                    )
                    run_bounded(command, 15)
                ref, observation = runtime_result(
                    catalog,
                    args,
                    entry,
                    plan,
                    booted,
                    environment,
                    unit,
                    record['boot_id'],
                    wait=not dispatched,
                )
                state = (
                    'READY'
                    if observation['reason_code'] == APPLICATION_READY
                    else 'RUNNING_UNREADY'
                )
                result = {**record, 'state': state, 'runtime': ref, 'observation': observation}
                write_record(fd, name, result, replace=True)
                if state == 'RUNNING_UNREADY':
                    raise EnvironmentFailure(APPLICATION_UNREADY, uncertain=True)
                return original_record(fd, name, common)
            except (
                EnvironmentFailure,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                subprocess.SubprocessError,
            ) as error:
                if getattr(error, 'code', None) == APPLICATION_UNREADY:
                    raise
                if getattr(error, 'code', None) == PREPARATION_UNVERIFIED:
                    raise EnvironmentFailure(PREPARATION_UNVERIFIED, uncertain=True) from error
                if record['state'] in ('PREPARING', 'STARTING', 'RUNNING_UNREADY'):
                    raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
                raise
