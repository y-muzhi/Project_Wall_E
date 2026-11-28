"""Observe actual release control and project only safe maintenance facts."""

import os
from uuid import uuid4

from backend.app.infrastructure.environment_control import (
    CONTROL_ERROR,
    control_bytes,
    read_control,
    read_release_transition,
)
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    decode,
    exact,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)

from .attachment_observation import (
    candidate_environment,
    machine_clock,
    now,
    observation_path,
    publish_observation,
    require_fresh,
)
from .operation_contract import DENIED, INVALID, MISSING, RESOURCE, installed_record, version
from .operation_store import decoded, environment_row, may_read_environment
from .registry import is_timestamp
from .release_configuration import read_configuration
from .release_observation import admitted_pair
from .release_operations import confirmed_preview, raw_plan
from .runtime_start import control_directory

BINDING = ('data_generation', 'deployment_id', 'configuration_sha256', 'program_sha256')
CONTROL = (
    *BINDING,
    'control_revision',
    'operation_id',
    'admission',
    'closed_reason',
    'outbound_hold',
    'last_open',
)
UNKNOWN = 'OBSERVATION_UNAVAILABLE'


def observation_ref(environment_id):
    return 'maintenance-' + environment_id


def confirmed_control(installations):
    source = installations[0]
    with control_directory(source) as fd:
        _, raw = control_bytes(fd, source)
        selected = decode(raw, CONTROL_ERROR)
        participants = [
            item
            for item in installations
            if (item.deployment_id, item.configuration_sha256)
            == (selected.get('deployment_id'), selected.get('configuration_sha256'))
        ]
        require(len(participants) == 1, CONTROL_ERROR)
        deployment = participants[0]
        deployment.check_hold()
        record = read_control(fd, deployment)
        last_open = None
        if record['open_receipt_ref'] is not None:
            generation = record['data_generation']
            if record['closed_reason'] == 'RECOVERY_REQUIRED':
                transition = read_release_transition(fd, deployment, record['operation_id'])
                generation = transition['before']['data_generation']
            opened = decode(
                read_entry(
                    fd,
                    record['open_receipt_ref'],
                    owner=deployment.application_uid,
                    group=deployment.group,
                ),
                CONTROL_ERROR,
            )
            require(
                opened['deployment_id'] == record['last_opened_deployment_id']
                and opened['data_generation'] == generation
                and uuid_value(opened['run_id'])
                and is_timestamp(opened['opened_at']),
                CONTROL_ERROR,
            )
            last_open = {key: opened[key] for key in ('deployment_id', 'run_id', 'opened_at')}
        _, confirmed = control_bytes(fd, source)
        require(confirmed == raw, CONTROL_ERROR)
    return {
        **{key: record[key] for key in CONTROL if key not in ('program_sha256', 'last_open')},
        'program_sha256': deployment.description['program_source']['sha256'],
        'last_open': last_open,
    }


def capture_maintenance(catalog, args, entry):
    require(os.geteuid() == 0, DENIED)
    configuration = read_configuration(catalog, args.release_configuration_ref)
    pair = admitted_pair(configuration, args.sha256, entry)
    return publish_control(catalog, (pair.source, pair.target))


def capture_environment_control(catalog, args):
    require(os.geteuid() == 0, DENIED)
    require(uuid_value(args.candidate_ref), INVALID)
    candidate = catalog.candidate(
        args.candidate_ref, catalog.installed_candidate_pin(args.candidate_ref)
    )
    installation = candidate_environment(candidate, args.sha256)
    return publish_control(catalog, (installation,))


def publish_control(catalog, installations):
    identifier = installations[0].environment_id
    boot, _ = machine_clock()
    observed = confirmed_control(installations)
    repeated_boot, elapsed = machine_clock()
    require(repeated_boot == boot, RESOURCE)
    proof = {
        'format_version': 1,
        **catalog.scope,
        'proof_id': str(uuid4()),
        'environment_id': identifier,
        'boot_id': boot,
        'observed_monotonic_ms': elapsed,
        'observed_at': now(),
        'control': observed,
    }
    publish_observation(catalog, observation_ref(identifier), proof)
    return {'environment_id': identifier, 'proof_id': proof['proof_id']}


def checked_status(catalog, identifier):
    try:
        proof = installed_record(observation_path(catalog, observation_ref(identifier)))
        version_record(
            proof,
            (
                *catalog.scope,
                'proof_id',
                'environment_id',
                'boot_id',
                'observed_monotonic_ms',
                'observed_at',
                'control',
            ),
            RESOURCE,
        )
        require(
            all(proof[key] == value for key, value in catalog.scope.items())
            and proof['environment_id'] == identifier
            and all(uuid_value(proof[key]) for key in ('proof_id', 'boot_id'))
            and version(proof['observed_monotonic_ms'])
            and is_timestamp(proof['observed_at']),
            RESOURCE,
        )
        control = exact(proof['control'], CONTROL, RESOURCE)
        require(
            all(
                uuid_value(control[key])
                for key in ('data_generation', 'deployment_id', 'operation_id')
            )
            and all(sha_value(control[key]) for key in ('configuration_sha256', 'program_sha256'))
            and version(control['control_revision'])
            and type(control['outbound_hold']) is bool
            and (control['admission'], control['closed_reason'])
            in (
                ('OPEN', 'NONE'),
                ('DRAINING', 'NORMAL_STOP'),
                ('CLOSED', 'NORMAL_STOP'),
                ('CLOSED', 'MAINTENANCE'),
                ('CLOSED', 'RECOVERY_REQUIRED'),
            ),
            RESOURCE,
        )
        if control['last_open'] is not None:
            opened = exact(control['last_open'], ('deployment_id', 'run_id', 'opened_at'), RESOURCE)
            require(
                uuid_value(opened['deployment_id'])
                and uuid_value(opened['run_id'])
                and is_timestamp(opened['opened_at']),
                RESOURCE,
            )
        if control['admission'] == 'OPEN':
            require(
                control['last_open'] is not None
                and control['last_open']['deployment_id'] == control['deployment_id'],
                RESOURCE,
            )
    except (OSError, KeyError, TypeError, ValueError, EnvironmentFailure):
        return 'UNAVAILABLE', None
    try:
        require_fresh(proof)
        freshness = 'FRESH'
    except (OSError, EnvironmentFailure):
        freshness = 'STALE'
    return freshness, {'observed_at': proof['observed_at'], 'control': control}


def confirmed_current_control(catalog, row):
    freshness, observed = checked_status(catalog, row['environment_id'])
    expected = registered_tuple(row)
    if freshness != 'FRESH' or observed is None or expected is None:
        return None
    control = observed['control']
    if any(control[key] != value for key, value in expected.items()):
        return None
    return control


def release_progress(connection, catalog, identifier):
    operation = connection.execute(
        'SELECT * FROM management_operations WHERE registry_generation=? AND environment_id=? '
        "AND action IN ('RELEASE','ROLLBACK_CODE','RECONFIGURE','RESTORE') "
        "AND status IN ('ACCEPTED','RUNNING','UNKNOWN') "
        'ORDER BY created_at DESC,operation_id DESC LIMIT 1',
        (catalog.scope['registry_generation'], identifier),
    ).fetchone()
    if operation is None:
        return None, None
    intent = decoded(operation['intent_json'])
    record = raw_plan(connection, intent['plan_id'])
    if operation['action'] == 'RESTORE':
        from .restore_operations import confirmed_restore

        preview = confirmed_restore(record, operation['principal'], intent)
    else:
        preview = confirmed_preview(record, operation['principal'], intent)
    require(record['execution_operation_id'] == operation['operation_id'], RESOURCE)
    return (
        {key: operation[key] for key in ('operation_id', 'status', 'revision')},
        {key: preview['target'][key] for key in BINDING},
    )


def registered_tuple(row):
    if row['configuration_ref'] is None:
        return None
    work = decoded(row['work_package_json'])
    return {
        'data_generation': work['data_generation'],
        'deployment_id': work['deployment_id'],
        'configuration_sha256': row['configuration_sha256'],
        'program_sha256': row['program_source'],
    }


def release_phase(operation, actual, desired):
    if actual is None:
        return 'OBSERVATION_UNAVAILABLE'
    if operation is None:
        return (
            'IDLE'
            if actual['closed_reason'] not in ('MAINTENANCE', 'RECOVERY_REQUIRED')
            else 'MAINTENANCE_UNTRACKED'
        )
    if actual['operation_id'] != operation['operation_id']:
        return (
            'WAITING_FOR_MAINTENANCE'
            if operation['status'] == 'ACCEPTED'
            else 'OBSERVATION_UNAVAILABLE'
        )
    if actual['closed_reason'] == 'MAINTENANCE':
        return 'MAINTENANCE_CLOSED'
    if (
        actual['closed_reason'] == 'RECOVERY_REQUIRED'
        and operation['status'] in ('RUNNING', 'UNKNOWN')
        and all(actual[key] == desired[key] for key in BINDING)
    ):
        return 'TARGET_SELECTED'
    if actual['admission'] == 'OPEN' and all(actual[key] == desired[key] for key in BINDING):
        return 'OPENED_AWAITING_REGISTRY'
    return 'OBSERVATION_UNAVAILABLE'


def recovery_read_status(actual, observed_at, expected, *, release_selected):
    blocked = []
    if actual is None:
        blocked.append(UNKNOWN)
    elif actual['closed_reason'] == 'RECOVERY_REQUIRED' and not release_selected:
        if expected is None or any(actual[key] != expected[key] for key in BINDING):
            blocked.append('BINDING_UNVERIFIED')
        if not actual['outbound_hold']:
            blocked.append('EXECUTION_NOT_FENCED')
        blocked.append('ASSET_UNVERIFIED')
    return {
        'status': 'BLOCKED' if blocked else 'NOT_APPLICABLE',
        'observed_at': observed_at if actual is not None else None,
        **{
            key: actual[key] if actual is not None else None
            for key in ('data_generation', 'deployment_id', 'control_revision')
        },
        'verification_ref': None,
        'verified_scopes': [],
        'blockers': [{'code': code} for code in blocked],
    }


def environment_maintenance(connection, catalog, principal, identifier):
    require(uuid_value(identifier), INVALID)
    row = environment_row(connection, identifier)
    require(row is not None, MISSING)
    require(may_read_environment(principal, row), DENIED)
    operation, target = release_progress(connection, catalog, identifier)
    registered = registered_tuple(row)
    desired = target if target is not None else registered
    freshness, last = checked_status(catalog, identifier)
    actual = last['control'] if freshness == 'FRESH' else None
    stamps = last['observed_at'] if last is not None else None
    phase = release_phase(operation, actual, desired)
    recovery = recovery_read_status(
        actual, stamps, desired, release_selected=phase == 'TARGET_SELECTED'
    )
    from .backup_reconciliation import managed_backup_history

    summary, _ = managed_backup_history(connection, catalog, identifier, now())
    return {
        'environment_id': identifier,
        'registered': registered,
        'desired': desired,
        'phase': phase,
        'freshness': freshness,
        'actual': actual,
        'last_observation': last,
        'operation': operation,
        'recovery_read': recovery,
        'backup_status': summary,
    }
