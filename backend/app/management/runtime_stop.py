"""Execute or reconcile one original, non-forced ordinary stop on the host."""

import fcntl
import os
import subprocess
from types import SimpleNamespace

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    exact,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import candidate_environment, now
from .operation_contract import CONFLICT, INVALID, RESOURCE, SCOPE, installed_record
from .registry import is_timestamp
from .runtime_observation import SYSTEMCTL, capture_runtime, load_policy, unit_facts

STOP_POLICY = 'managed-stop.v1.json'
NOT_READY = 'MANAGEMENT_NOT_READY'
UNVERIFIED = 'MANAGEMENT_STOP_EFFECT_UNVERIFIED'
STOP_PROPERTIES = (
    'Id',
    'LoadState',
    'ActiveState',
    'InvocationID',
    'KillMode',
    'KillSignal',
    'SendSIGKILL',
    'SendSIGHUP',
    'ExecStop',
    'ExecStopPost',
    'TimeoutStopFailureMode',
)


def stop_policy(catalog, path, expected):
    require(path.is_absolute() and path.name == STOP_POLICY and sha_value(expected), INVALID)
    plan = exact(
        installed_record(path, expected),
        (
            'format_version',
            *catalog.scope,
            'stop_operation_id',
            'environment_id',
            'run_id',
            'runtime_policy_ref',
        ),
        INVALID,
    )
    require(
        type(plan['format_version']) is int
        and plan['format_version'] == 1
        and all(uuid_value(plan[key]) for key in ('stop_operation_id', 'environment_id', 'run_id')),
        INVALID,
    )
    require(all(plan[key] == value for key, value in catalog.scope.items()), SCOPE)
    ref = exact(plan['runtime_policy_ref'], ('path', 'sha256'), INVALID)
    require(sha_value(ref['sha256']), INVALID)
    return plan, absolute(ref['path'], INVALID), ref['sha256']


def stop_record(fd, name, original):
    try:
        raw = read_entry(fd, name, owner=0)
    except FileNotFoundError:
        return None
    record = exact(
        decode(raw, UNVERIFIED),
        (
            *original,
            'state',
            'dispatch',
            'recorded_at',
            'observation',
        ),
        UNVERIFIED,
    )
    require(all(record[key] == value for key, value in original.items()), CONFLICT)
    require(is_timestamp(record['recorded_at']), UNVERIFIED)
    if record['state'] in ('PREPARED', 'DISPATCHING'):
        dispatch = 'NOT_NEEDED' if record['state'] == 'PREPARED' else 'DISPATCH_RECORDED'
        require(record['dispatch'] == dispatch and record['observation'] is None, UNVERIFIED)
    else:
        require(
            record['state'] == 'STOPPED'
            and record['dispatch'] in ('DISPATCH_RECORDED', 'NOT_NEEDED'),
            UNVERIFIED,
        )
        sample = exact(
            record['observation'],
            (
                'proof_id',
                'environment_id',
                'observed_at',
                'state',
                'reason_code',
            ),
            UNVERIFIED,
        )
        require(
            uuid_value(sample['proof_id'])
            and is_timestamp(sample['observed_at'])
            and sample['environment_id'] == original['environment_id']
            and sample['state'] == 'STOPPED'
            and sample['reason_code'] == 'MANAGED_STOP_CONFIRMED',
            UNVERIFIED,
        )
    return record


def run_claim(fd, name, original, *, create):
    try:
        raw = read_entry(fd, name, owner=0)
    except FileNotFoundError:
        if create:
            persisted_write(fd, name, canonical(original), mode=0o444)
        return False
    recorded = exact(decode(raw, UNVERIFIED), original, UNVERIFIED)
    require(recorded == original, CONFLICT)
    return True


def verify_normal_stop(unit, invocation):
    facts = unit_facts(unit, properties=STOP_PROPERTIES, optional=('ExecStop', 'ExecStopPost'))
    require(
        facts.get('ActiveState') == 'active'
        and facts.get('InvocationID') == invocation
        and facts.get('KillMode') == 'control-group'
        and facts.get('KillSignal') in ('15', 'SIGTERM')
        and facts.get('SendSIGKILL') == 'no'
        and facts.get('SendSIGHUP') == 'no'
        and facts.get('TimeoutStopFailureMode') == 'terminate'
        and facts.get('ExecStop', '') == ''
        and facts.get('ExecStopPost', '') == '',
        RESOURCE,
    )


def request_stop(unit):
    try:
        # Once dispatched, loss of the control response cannot establish that nothing happened.
        subprocess.run(
            [str(SYSTEMCTL), '--system', '--no-pager', 'stop', unit],
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'TZ': 'UTC', 'SYSTEMD_COLORS': '0'},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=35,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def verified_sample(catalog, runtime_args, entry):
    try:
        return capture_runtime(catalog, runtime_args, entry)
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
        raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error


def finish_stop(fd, name, original, previous, closed):
    outcome = {
        **original,
        'state': 'STOPPED',
        'recorded_at': previous['recorded_at'] if previous else now(),
        'dispatch': previous['dispatch'] if previous else 'NOT_NEEDED',
        'observation': closed,
    }
    persisted_write(fd, name, canonical(outcome), mode=0o444, replace=previous is not None)
    return stop_record(fd, name, original)


def stop_runtime(catalog, args, entry, *, allow_unready=False, admit_new_stop=None):
    require(os.geteuid() == 0, RESOURCE)
    plan, path, pin = stop_policy(catalog, args.stop_policy, args.stop_policy_sha256)
    runtime = load_policy(path, pin, catalog)
    candidate = catalog.candidate(runtime['candidate_ref'], runtime['candidate_sha256'])
    environment = candidate_environment(candidate, args.sha256)
    require(
        plan['environment_id'] == environment.environment_id
        and plan['run_id'] == runtime['run_id']
        and plan['stop_operation_id'] != runtime['operation_id'],
        INVALID,
    )
    common = {
        'format_version': 1,
        **catalog.scope,
        **{key: plan[key] for key in ('stop_operation_id', 'environment_id', 'run_id')},
        'start_operation_id': runtime['operation_id'],
        'stop_policy_sha256': args.stop_policy_sha256,
        'runtime_policy_sha256': pin,
    }
    runtime_args = SimpleNamespace(
        runtime_policy=path,
        runtime_policy_sha256=pin,
        root=args.root,
        sha256=args.sha256,
        runtime_entry=args.runtime_entry,
    )
    unit = f'walle-env-{environment.environment_id}-{runtime["operation_id"]}.service'
    name = f'stop-{plan["stop_operation_id"]}.v1.json'
    claim = f'stop-claim-{environment.environment_id}-{runtime["run_id"]}.v1.json'
    # Serialize host effects on the protected catalog parent. The separate observation
    # directory retains its existing publication lock.
    with protected_directory(catalog.directory) as host:
        try:
            fcntl.flock(host, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnvironmentFailure(NOT_READY) from error
        with protected_directory(catalog.directory / 'observations') as fd:
            previous = stop_record(fd, name, common)
            claimed = run_claim(fd, claim, common, create=False)
            if previous and previous['state'] != 'PREPARED':
                require(claimed, UNVERIFIED)
                if previous['state'] == 'STOPPED':
                    return previous
                current = verified_sample(catalog, runtime_args, entry)
                if current['state'] != 'STOPPED':
                    raise EnvironmentFailure(UNVERIFIED, uncertain=True)
                return finish_stop(fd, name, common, previous, current)

            if admit_new_stop is not None:
                admit_new_stop()
            current = capture_runtime(catalog, runtime_args, entry)
            if current['state'] != 'STOPPED':
                require(
                    current['state'] == 'RUNNING'
                    and (
                        current['reason_code'] == 'MANAGED_APPLICATION_READY'
                        or allow_unready
                        and current['reason_code'] == 'MANAGED_APPLICATION_UNVERIFIED'
                    ),
                    RESOURCE,
                )
                verify_normal_stop(unit, runtime['invocation_id'])
            if previous is None:
                previous = {
                    **common,
                    'state': 'PREPARED',
                    'dispatch': 'NOT_NEEDED',
                    'recorded_at': now(),
                    'observation': None,
                }
                persisted_write(fd, name, canonical(previous), mode=0o444)
            run_claim(fd, claim, common, create=True)
            if current['state'] == 'STOPPED':
                return finish_stop(fd, name, common, previous, current)

            attempted = {**previous, 'state': 'DISPATCHING', 'dispatch': 'DISPATCH_RECORDED'}
            persisted_write(fd, name, canonical(attempted), mode=0o444, replace=True)
            try:
                verify_normal_stop(unit, runtime['invocation_id'])
                request_stop(unit)
            except (
                EnvironmentFailure,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                subprocess.SubprocessError,
            ) as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
            closed = verified_sample(catalog, runtime_args, entry)
            if closed['state'] != 'STOPPED':
                raise EnvironmentFailure(UNVERIFIED, uncertain=True)
            return finish_stop(fd, name, common, attempted, closed)
