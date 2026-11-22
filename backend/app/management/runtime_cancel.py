"""Close an already identified managed start using its original cancellation."""

import fcntl
import os
from types import SimpleNamespace
from uuid import uuid4

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_control import read_control
from backend.app.infrastructure.environment_installation import uuid_value
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles

from .attachment_observation import candidate_environment, machine_clock, now
from .host_capacity import NOT_READY
from .operation_contract import INVALID, RESOURCE, SCOPE, installed_record, path_reference, version
from .registry import is_timestamp
from .runtime_capacity import load_capacity
from .runtime_early_cancel import close_early_application, early_effect
from .runtime_observation import CGROUP_ROOT, STOPPED, SYSTEMCTL, trusted_executable, unit_facts
from .runtime_preparation_cancel import RETIRED, cancel_preparation, matches_preparation_cancel
from .runtime_start import (
    OBSERVED_STARTED,
    SETPRIV,
    control_directory,
    host_registry_call,
    load_start,
    original_record,
    record_at,
    write_record,
)
from .runtime_stop import stop_record, stop_runtime

POLICY = 'managed-cancel.v1.json'
UNVERIFIED = 'MANAGEMENT_CANCEL_EFFECT_UNVERIFIED'


def start_common(catalog, operation_id, environment_id, policy_sha):
    return {
        'format_version': 1,
        **catalog.scope,
        'environment_id': environment_id,
        'start_operation_id': operation_id,
        'start_policy_sha256': policy_sha,
    }


def cancel_binding(catalog, start, control_key):
    return {
        'format_version': 1,
        **catalog.scope,
        'environment_id': start['environment_id'],
        'run_id': start['prepared']['run_id'],
        'control_key': control_key,
        'start_operation_id': start['start_operation_id'],
        'start_policy_sha256': start['start_policy_sha256'],
        'runtime_policy_sha256': start['runtime']['sha256'],
    }


def stop_intent(catalog, start, control_key):
    return {
        'format_version': 1,
        **catalog.scope,
        'stop_operation_id': control_key,
        'environment_id': start['environment_id'],
        'run_id': start['prepared']['run_id'],
        'runtime_policy_ref': start['runtime'],
    }


def cancellation_effect(catalog, operation, policy_sha, control_key):
    start_id = operation['operation_id']
    environment_id = operation['environment_id']
    common = start_common(catalog, start_id, environment_id, policy_sha)
    with protected_directory(catalog.directory / 'observations') as observed:
        binding = record_at(observed, 'cancel-' + start_id + '.v1.json')
        if binding is None:
            return None
        start = original_record(observed, 'start-' + start_id + '.v1.json', common)
        require(
            start is not None
            and start['state'] in OBSERVED_STARTED
            and binding == cancel_binding(catalog, start, control_key),
            RESOURCE,
        )
        expected = {
            **{
                key: binding[key]
                for key in (
                    'format_version',
                    *catalog.scope,
                    'environment_id',
                    'start_operation_id',
                    'run_id',
                    'runtime_policy_sha256',
                )
            },
            'stop_operation_id': control_key,
            'stop_policy_sha256': digest(canonical(stop_intent(catalog, start, control_key))),
        }
        stopped = stop_record(observed, 'stop-' + control_key + '.v1.json', expected)
    if stopped is None or stopped['state'] != 'STOPPED':
        return None
    observation = stopped['observation']
    require(
        observation['state'] == 'STOPPED'
        and observation['reason_code'] == STOPPED
        and observation['environment_id'] == environment_id
        and uuid_value(observation['proof_id'])
        and is_timestamp(observation['observed_at']),
        RESOURCE,
    )
    return binding, observation


def retirement_proof(observed, common, control_key):
    record = record_at(observed, 'cancel-unissued-' + common['start_operation_id'] + '.v1.json')
    if record is None:
        return None
    preparing = record.get('cutoff') == 'PREPARING'
    retirement_fields = ('retirement_state', 'retirement_sha256') if preparing else ()
    exact(
        record,
        (
            *common,
            'control_key',
            'boot_id',
            'observed_at',
            'proof_id',
            'cutoff',
            'control_revision',
            'reason_code',
            *retirement_fields,
        ),
        RESOURCE,
    )
    require(
        all(record[key] == value for key, value in common.items())
        and record['control_key'] == control_key
        and uuid_value(record['boot_id'])
        and uuid_value(record['proof_id'])
        and is_timestamp(record['observed_at'])
        and version(record['control_revision']),
        RESOURCE,
    )
    if preparing:
        require(
            record['reason_code'] == RETIRED
            and record['retirement_state'] in ('UNCHANGED', 'RETIRED')
            and matches_preparation_cancel(observed, common, control_key, record),
            RESOURCE,
        )
    else:
        require(
            record['cutoff'] in ('ABSENT', 'RESERVED')
            and record['reason_code'] == 'MANAGED_START_NOT_DISPATCHED',
            RESOURCE,
        )
    return record


def check_cancel_permit(args, entry, registry, capacity, program, executable, request):
    decision = exact(
        host_registry_call(
            args, entry, registry, capacity, program, executable, '_authorize-cancel', request
        ),
        ('admission', 'dispatch_allowed'),
        UNVERIFIED,
    )
    require(
        decision['admission'] == request and type(decision['dispatch_allowed']) is bool, RESOURCE
    )
    return decision['dispatch_allowed']


def cancel_before_application(
    catalog,
    args,
    entry,
    registry,
    program,
    executable,
    capacity,
    environment,
    common,
    control_key,
    startup,
):
    operation = common['start_operation_id']
    unit = f'walle-env-{environment.environment_id}-{operation}.service'
    with protected_directory(catalog.directory) as host:
        try:
            fcntl.flock(host, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnvironmentFailure(NOT_READY) from error
        with protected_directory(catalog.directory / 'observations') as observed:
            original = original_record(observed, 'start-' + operation + '.v1.json', common)
            if original is not None and original['state'] == 'STARTING':
                return cancel_early_runtime(
                    observed,
                    args,
                    entry,
                    registry,
                    program,
                    executable,
                    capacity,
                    environment,
                    common,
                    control_key,
                    startup,
                    original,
                )
            require(original is None or original['state'] in ('RESERVED', 'PREPARING'), UNVERIFIED)
            recorded = retirement_proof(observed, common, control_key)
            boot = recorded['boot_id'] if recorded is not None else machine_clock()[0]
            permit = {
                'start_operation_id': operation,
                'environment_id': environment.environment_id,
                'start_policy_sha256': common['start_policy_sha256'],
                'control_key': control_key,
                'run_id': None,
                'boot_id': boot,
            }
            to_close = check_cancel_permit(
                args, entry, registry, capacity, program, executable, permit
            )
            if recorded is None:
                require(to_close and (original is None or original['boot_id'] == boot), UNVERIFIED)
                cutoff = original['state'] if original is not None else 'ABSENT'
                if cutoff == 'PREPARING':
                    effect = cancel_preparation(
                        observed, args, entry, startup, environment, common, boot, control_key
                    )
                else:
                    effect = observe_unissued(args, environment, unit, boot)
                recorded = {
                    **common,
                    **effect,
                    'control_key': control_key,
                    'boot_id': boot,
                    'observed_at': now(),
                    'proof_id': str(uuid4()),
                    'cutoff': cutoff,
                }
                write_record(observed, 'cancel-unissued-' + operation + '.v1.json', recorded)
            state = 'PREPARATION_RETIRED' if recorded['cutoff'] == 'PREPARING' else 'NOT_DISPATCHED'
            return {
                'state': state,
                'control_key': control_key,
                'observation': {
                    key: recorded[key] for key in ('proof_id', 'observed_at', 'reason_code')
                },
            }


def cancel_early_runtime(
    observed,
    args,
    entry,
    registry,
    program,
    executable,
    capacity,
    environment,
    common,
    key,
    startup,
    original,
):
    actual = early_effect(observed, common, key)
    request = {
        'start_operation_id': common['start_operation_id'],
        'environment_id': environment.environment_id,
        'start_policy_sha256': common['start_policy_sha256'],
        'control_key': key,
        'run_id': original['prepared']['run_id'],
        'boot_id': original['boot_id'],
    }
    allowed = check_cancel_permit(args, entry, registry, capacity, program, executable, request)
    if actual is None:
        require(allowed, UNVERIFIED)
        proof = close_early_application(
            observed, args, entry, startup, environment, common, original, key, executable
        )
    else:
        proof = actual[1]
    return {
        'state': 'STOPPED',
        'control_key': key,
        'observation': {name: proof[name] for name in ('proof_id', 'observed_at', 'reason_code')},
    }


def observe_unissued(args, environment, unit, boot):
    native = NativeEnvironmentFiles(args.root)
    group = CGROUP_ROOT / 'system.slice' / unit
    with environment.lock(native) as lock, control_directory(environment) as control:
        first = read_control(control, environment)
        facts = unit_facts(unit)
        require(
            first['admission'] == 'CLOSED'
            and facts['LoadState'] == 'not-found'
            and facts.get('MainPID', '0') == '0'
            and not os.path.lexists(group)
            and not os.path.lexists(environment.path('runtime') / 'walle.sock'),
            UNVERIFIED,
        )
        lock.assert_owned()
        require(
            machine_clock()[0] == boot
            and unit_facts(unit) == facts
            and read_control(control, environment) == first,
            UNVERIFIED,
        )
    return {
        'control_revision': first['control_revision'],
        'reason_code': 'MANAGED_START_NOT_DISPATCHED',
    }


def cancel_runtime(catalog, args, entry, registry, program):
    require(os.geteuid() == 0 and args.cancel_policy.name == POLICY, RESOURCE)
    plan = exact(
        installed_record(args.cancel_policy, args.cancel_policy_sha256),
        ('format_version', *catalog.scope, 'control_key', 'start_policy_ref'),
        INVALID,
    )
    require(
        type(plan['format_version']) is int
        and plan['format_version'] == 1
        and uuid_value(plan['control_key']),
        INVALID,
    )
    require(all(plan[key] == value for key, value in catalog.scope.items()), SCOPE)
    policy_path, policy_sha = path_reference(plan['start_policy_ref'])
    startup = load_start(catalog, policy_path, policy_sha)
    candidate = catalog.candidate(startup['candidate_ref'], startup['candidate_sha256'])
    environment = candidate_environment(candidate, args.sha256)
    original_id = startup['start_operation_id']
    control_key = plan['control_key']
    require(control_key != original_id, INVALID)
    common = start_common(catalog, original_id, environment.environment_id, policy_sha)
    observations = catalog.directory / 'observations'
    with protected_directory(observations) as observed:
        start = original_record(observed, 'start-' + original_id + '.v1.json', common)
    capacity = load_capacity(catalog)
    trusted_executable(SETPRIV, startup['setpriv_sha256'])
    manifest, _ = entry['verify_runtime'](args.root, args.sha256)
    executable = args.root / manifest['python']['executable_ref']
    if start is None or start['state'] not in OBSERVED_STARTED:
        trusted_executable(SYSTEMCTL, startup['systemctl_sha256'])
        return cancel_before_application(
            catalog,
            args,
            entry,
            registry,
            program,
            executable,
            capacity,
            environment,
            common,
            control_key,
            startup,
        )
    require(start['boot_id'] == machine_clock()[0], UNVERIFIED)
    request = {
        'start_operation_id': original_id,
        'environment_id': environment.environment_id,
        'start_policy_sha256': policy_sha,
        'control_key': control_key,
        'run_id': start['prepared']['run_id'],
        'boot_id': start['boot_id'],
    }
    if not check_cancel_permit(args, entry, registry, capacity, program, executable, request):
        effect = cancellation_effect(
            catalog,
            {'operation_id': original_id, 'environment_id': environment.environment_id},
            policy_sha,
            control_key,
        )
        require(effect is not None, UNVERIFIED)
        return {'state': 'STOPPED', 'control_key': control_key, 'observation': effect[1]}

    binding = cancel_binding(catalog, start, control_key)
    stop_policy = stop_intent(catalog, start, control_key)
    dirname = 'cancel-stop-' + original_id
    with protected_directory(observations) as observed:
        binding_name = 'cancel-' + original_id + '.v1.json'
        frozen = record_at(observed, binding_name)
        if frozen is None:
            write_record(observed, binding_name, binding)
        else:
            require(frozen == binding, RESOURCE)
        try:
            os.mkdir(dirname, 0o755, dir_fd=observed)
            os.fsync(observed)
        except FileExistsError:
            pass
    directory = observations / dirname
    with protected_directory(directory) as fd:
        name = 'managed-stop.v1.json'
        fixed = record_at(fd, name)
        if fixed is None:
            write_record(fd, name, stop_policy)
        else:
            require(fixed == stop_policy, RESOURCE)
    stopped = stop_runtime(
        catalog,
        SimpleNamespace(
            **{
                **vars(args),
                'stop_policy': directory / name,
                'stop_policy_sha256': digest(canonical(stop_policy)),
            }
        ),
        entry,
        allow_unready=True,
    )
    return {
        'state': stopped['state'],
        'control_key': control_key,
        'observation': stopped['observation'],
    }
