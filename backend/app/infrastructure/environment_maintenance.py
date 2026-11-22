"""Apply or release the original maintenance hold on a stopped ordinary installation."""

from contextlib import ExitStack
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from .environment_admission import read_start
from .environment_command import admission_inputs
from .environment_control import (
    CONTROL_NAME,
    maintained_control,
    maintenance_cancel_name,
    maintenance_name,
    normal_stop,
    read_control,
    read_maintenance_intent,
)
from .environment_files import (
    EnvironmentFailure,
    MAX_REVISION,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    read_entry,
    read_protected,
    require,
)
from .environment_installation import database_identity, sha_value, uuid_value
from .environment_ordinary import OrdinaryDatabase

POLICY = 'environment-maintenance.v1.json'
INVALID = 'MAINTENANCE_INTENT_MISMATCH'
UNKNOWN = 'MAINTENANCE_CONTROL_UNVERIFIED'
STALE = 'MAINTENANCE_SOURCE_CHANGED'
ACTIVE = 'MAINTENANCE_CLOSED'
CANCELLED = 'MAINTENANCE_CANCELLED'
PENDING = 'PENDING_RECONCILIATION'
SCOPE = ('environment_id', 'data_generation', 'deployment_id')


def load_policy(path, expected):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    record = decode(raw, INVALID)
    restore_reference = ('restore_plan',) if 'restore_plan' in record else ()
    identity_pin = (
        ('expected_database_identity_sha256',)
        if 'expected_database_identity_sha256' in record
        else ()
    )
    exact(
        record,
        (
            'format_version',
            'operation_id',
            *SCOPE,
            'installation_sha256',
            'program',
            'program_sha256',
            'expected_control_revision',
            'expected_control_sha256',
            *identity_pin,
            *restore_reference,
        ),
        INVALID,
    )
    require(
        type(record['format_version']) is int
        and record['format_version'] == 1
        and all(uuid_value(record[key]) for key in ('operation_id', *SCOPE))
        and all(
            sha_value(record[key])
            for key in (
                'installation_sha256',
                'program_sha256',
                'expected_control_sha256',
                *identity_pin,
            )
        )
        and type(record['expected_control_revision']) is int
        and 1 <= record['expected_control_revision'] < MAX_REVISION - 2,
        INVALID,
    )
    absolute(record['program'], INVALID)
    return record


def before_matches(control, plan):
    return (
        normal_stop(control)
        and control['operation_id'] != plan['operation_id']
        and control['control_revision'] == plan['expected_control_revision']
        and digest(canonical(control)) == plan['expected_control_sha256']
    )


def maybe_intent(fd, installation, plan, plan_sha):
    try:
        value = read_maintenance_intent(fd, installation, plan['operation_id'])
    except FileNotFoundError:
        return None
    require(value['plan_sha256'] == plan_sha and before_matches(value['before'], plan), INVALID)
    return value


def write_fact(fd, installation, name, expected, *, create=False):
    raw = canonical(expected)
    try:
        existing = read_entry(
            fd,
            name,
            owner=installation.maintenance_uid,
            group=installation.group,
            reject_writers=0o227,
        )
    except FileNotFoundError:
        if create:
            persisted_write(fd, name, raw, mode=0o440)
            return True
        return False
    require(existing == raw, UNKNOWN)
    return True


def released_control(before):
    return {**before, 'control_revision': before['control_revision'] + 2}


def cancellation_facts(intent):
    operation = intent['operation_id']
    before = intent['before']
    active = maintained_control(before, operation, intent['plan_sha256'])
    released = released_control(before)
    record = {
        'format_version': 1,
        'operation_id': operation,
        'plan_sha256': intent['plan_sha256'],
        'active_sha256': digest(canonical(active)),
        'released_sha256': digest(canonical(released)),
        'released_control_revision': released['control_revision'],
    }
    return (
        maintenance_cancel_name(operation),
        f'maintenance-cancel-confirmed-{operation}.v1.json',
        record,
    )


def observe(fd, installation, control, plan, intent):
    if intent is None:
        return 'MAINTENANCE_NOT_PREPARED' if before_matches(control, plan) else PENDING
    before = intent['before']
    active = maintained_control(before, intent['operation_id'], intent['plan_sha256'])
    released = released_control(before)
    request_name, proof_name, record = cancellation_facts(intent)
    authorized = write_fact(fd, installation, request_name, record)
    confirmed = write_fact(fd, installation, proof_name, record)
    require(not confirmed or authorized, UNKNOWN)
    if control == active and not confirmed:
        return ACTIVE
    if authorized and control == released:
        return CANCELLED
    if confirmed and control['control_revision'] > released['control_revision']:
        return CANCELLED
    return PENDING


def verify_stopped(native, installation, release, resources, fd, control, lock):
    require(not os.path.lexists(installation.path('runtime') / 'walle.sock'), STALE)
    try:
        raw = read_start(fd, installation, control['operation_id'])
    except FileNotFoundError:
        pass
    else:
        receipt = decode(raw, UNKNOWN)
        original_revision = receipt.get('control_revision')
        require(
            type(original_revision) is int
            and 1 <= original_revision < control['control_revision']
            and receipt.get('format_version') == 1
            and receipt.get('operation_id') == control['operation_id']
            and uuid_value(receipt.get('run_id'))
            and all(
                receipt.get(key) == getattr(installation, key)
                for key in (*SCOPE, 'configuration_sha256')
            ),
            STALE,
        )
    data = resources.enter_context(installation.directory(native, 'data'))
    database = OrdinaryDatabase(installation, release, data, lock)
    database.preflight()
    database.check_recovery()


def select_maintenance(native, installation, release, plan, plan_sha, action):
    operation = plan['operation_id']
    with ExitStack() as resources:
        lock = resources.enter_context(installation.lock(native))
        fd = resources.enter_context(installation.directory(native, 'control'))
        control = read_control(fd, installation)
        intent = maybe_intent(fd, installation, plan, plan_sha)
        status = observe(fd, installation, control, plan, intent)
        effective_revision = None

        if action == 'enter' and status not in (ACTIVE, CANCELLED):
            require(before_matches(control, plan), STALE)
            if intent is not None:
                request_name, _, record = cancellation_facts(intent)
                require(not write_fact(fd, installation, request_name, record), UNKNOWN)
            verify_stopped(native, installation, release, resources, fd, control, lock)
            expected_data = plan.get('expected_database_identity_sha256')
            if expected_data is not None:
                with installation.directory(native, 'data') as data_fd:
                    current_database = database_identity(installation, data_fd)
                require(
                    current_database is not None
                    and digest(canonical(current_database)) == expected_data,
                    STALE,
                )
            installation.check_hold()
            lock.assert_owned()
            require(read_control(fd, installation) == control, STALE)
            if intent is None:
                intent = {
                    'format_version': 1,
                    'operation_id': operation,
                    'plan_sha256': plan_sha,
                    'before_sha256': plan['expected_control_sha256'],
                    'before': control,
                }
                persisted_write(fd, maintenance_name(operation), canonical(intent), mode=0o440)
            desired = maintained_control(control, operation, plan_sha)
            persisted_write(fd, CONTROL_NAME, canonical(desired), mode=0o640, replace=True)
            control = read_control(fd, installation)
            require(control == desired, UNKNOWN)
            status = ACTIVE
        elif action == 'cancel':
            require(status in (ACTIVE, CANCELLED), UNKNOWN)
            if status == ACTIVE:
                require(not os.path.lexists(installation.path('runtime') / 'walle.sock'), STALE)
                installation.check_hold()
                request_name, _, record = cancellation_facts(intent)
                write_fact(fd, installation, request_name, record, create=True)
                lock.assert_owned()
                require(read_control(fd, installation) == control, STALE)
                desired = released_control(intent['before'])
                persisted_write(fd, CONTROL_NAME, canonical(desired), mode=0o640, replace=True)
                control = read_control(fd, installation)
                require(control == desired, UNKNOWN)
                status = CANCELLED
            if control == released_control(intent['before']):
                _, proof_name, record = cancellation_facts(intent)
                write_fact(fd, installation, proof_name, record, create=True)

        if status == ACTIVE:
            effective_revision = intent['before']['control_revision'] + 1
        if status == CANCELLED:
            effective_revision = intent['before']['control_revision'] + 2
        return {
            'status': status,
            'operation_id': operation,
            **{key: plan[key] for key in SCOPE},
            'plan_sha256': plan_sha,
            'control_revision': effective_revision,
        }


def maintenance_authorization(plan, policy_sha, installation):
    if 'restore_plan' not in plan:
        return policy_sha
    from .environment_restore_preflight import POLICY as RESTORE_PLAN
    from .environment_restore_preflight import restore_authorization, restore_plan

    reference = exact(plan['restore_plan'], ('path', 'sha256'), INVALID)
    path = absolute(reference['path'], INVALID)
    require(
        path.name == RESTORE_PLAN
        and sha_value(reference['sha256'])
        and 'expected_database_identity_sha256' in plan,
        INVALID,
    )
    restore = restore_plan(path, reference['sha256'])
    require(
        restore['operation_id'] == plan['operation_id']
        and restore['installation_sha256'] == installation.anchor_sha256
        and restore['source_data_generation'] == installation.data_generation
        and restore['source_deployment_id'] == installation.deployment_id
        and restore['source_configuration_sha256'] == installation.configuration_sha256
        and restore['source_control_revision'] == plan['expected_control_revision'] + 1,
        INVALID,
    )
    return restore_authorization(restore)


def run_maintenance(native, active, args, entry):
    plan = load_policy(args.maintenance_policy, args.maintenance_policy_sha256)
    require(plan['installation_sha256'] == args.anchor_sha256, INVALID)
    program = Path(plan['program'])
    program_sha = entry['verify_program'](program)
    require(program_sha == plan['program_sha256'], INVALID)
    installation, release = admission_inputs(
        SimpleNamespace(anchor=args.anchor, anchor_sha256=args.anchor_sha256, project=program),
        active,
        program_sha,
    )
    require('recovery_replica' not in installation.description, 'RECOVERY_REPLICA_READ_ONLY')
    installation.check_identity(maintenance=True)
    require(all(plan[key] == getattr(installation, key) for key in SCOPE), INVALID)
    try:
        return select_maintenance(
            native,
            installation,
            release,
            plan,
            maintenance_authorization(plan, args.maintenance_policy_sha256, installation),
            args.maintenance_action,
        )
    except sqlite3.Error as error:
        raise EnvironmentFailure(UNKNOWN) from error
