"""Observe named resource bindings and original managed helper units without changing them."""

from subprocess import SubprocessError

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import PATH_SCOPE
from .lifecycle_operations import check_start_request_shape
from .operation_contract import (
    RECONFIGURE,
    RELEASE,
    RELEASE_ACTIONS,
    ROLLBACK_CODE,
    path_reference,
    version,
)
from .registry import is_timestamp
from .registry_recovery_retained_data import PRESERVED as RETAINED_DATA_VERIFIED
from .registry_recovery_stop import (
    observed_stop_receipt,
    original_runtime_identity,
    stopped_runtime_unit,
)
from .release_execution import HOLD_EXECUTOR as RELEASE_EXECUTOR
from .release_open_admission import TARGET, check_open_request_shape
from .release_reconciliation import opened_evidence
from .restore_execution import HOLD_EXECUTOR as RESTORE_EXECUTOR
from .restore_reconciliation import opened_restore
from .runtime_cancel import start_common
from .runtime_capacity import CLAIM_KIND, CLAIM_SCOPE, DIMENSIONS, MAXIMUM, MINIMUM
from .runtime_observation import load_policy, unit_facts
from .runtime_start import RUNTIME_POLICY, original_record, preparation_group_empty

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_EFFECT_UNVERIFIED'
START_STEP = 'RUNTIME_STARTED'
STOP_STEP = 'RUNTIME_STOPPED'
ORDINARY_EXECUTOR = 'SYSTEMD_ORDINARY_RUNTIME'
CANCEL_STEPS = ('RUNTIME_PREPARATION_CANCELLED', 'RUNTIME_START_CANCELLED')
DEPLOYMENT_STEPS = {
    'RELEASE_DEPLOYMENT': (RELEASE, RELEASE_EXECUTOR),
    'RESTORE_ENVIRONMENT': ('RESTORE', RESTORE_EXECUTOR),
}
OBSERVATION_FAILURE = (
    EnvironmentFailure,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    SubprocessError,
)


def resource_observation(row, observed_environment):
    subject = {
        'kind': 'RESOURCE_CLAIM',
        'resource_id': row['resource_id'],
        'resource_kind': row['kind'],
        'environment_id': row['environment_id'],
        'operation_id': row['operation_id'],
    }
    if row['kind'] == CLAIM_KIND:
        if (
            row.get('scope_ref') == CLAIM_SCOPE
            and row.get('original_action') == 'START'
            and row.get('original_operation_status') == 'CANCELLED'
        ):
            return {**subject, 'state': 'CHANGED', 'reason_code': 'RETIRED_START_CAPACITY_RETAINED'}
        return {**subject, 'state': 'PRESERVED', 'reason_code': 'CAPACITY_NOT_RELEASED'}
    actual = observed_environment.get('assignment_claims', {}).get(row['kind'])
    if actual is None:
        actual = observed_environment.get('paths', {}).get(row['kind'])
    if actual is None:
        return {**subject, 'state': 'UNKNOWN', 'reason_code': UNVERIFIED}
    reason = UNVERIFIED
    try:
        pinned = (
            None
            if row['identity_json'] is None
            else decode(row['identity_json'].encode('utf-8'), UNVERIFIED)
        )
        state = 'CHANGED'
        unpinned_socket = (
            row['kind'] == 'UPSTREAM_SOCKET'
            and pinned is None
            and observed_environment['state'] == 'RUNNING_OBSERVED'
            and actual['object_identity'] is not None
        )
        if (
            row['scope_ref'] == actual['scope']
            and row['locator'] == actual['locator']
            and (pinned == actual['object_identity'] or unpinned_socket)
        ):
            state, reason = 'BOUND', None
        elif row['scope_ref'] == PATH_SCOPE and any(
            resource['kind'] == row['kind']
            and resource['locator'] == row['locator']
            and pinned == resource['object_identity']
            for resource in observed_environment.get('retained_paths', ())
        ):
            state, reason = 'PRESERVED', RETAINED_DATA_VERIFIED
    except OBSERVATION_FAILURE:
        state = 'UNKNOWN'
    return {**subject, 'state': state, 'reason_code': reason}


def original_cancel_control(row):
    require(row['control_count'] == 1, UNVERIFIED)
    receipt = exact(
        decode(row['control_receipt_json'].encode('utf-8'), UNVERIFIED),
        (
            'control_key',
            'operation_id',
            'command',
            'revision',
            'operation_revision',
            'result',
            'recorded_at',
        ),
        UNVERIFIED,
    )
    revision = receipt['operation_revision']
    require(
        receipt['operation_id'] == row['operation_id']
        and receipt['control_key'] == row['control_key']
        and uuid_value(receipt['control_key'])
        and receipt['command'] == 'CANCEL'
        and type(receipt['revision']) is int
        and receipt['revision'] == 1
        and type(revision) is int
        and 2 <= revision < row['original_revision']
        and receipt['result'] == 'CANCELLATION_REQUESTED'
        and is_timestamp(receipt['recorded_at']),
        UNVERIFIED,
    )
    request = {
        'action': 'CONTROL',
        'command': 'CANCEL',
        'operation_id': row['operation_id'],
        'expected_revision': revision - 1,
    }
    require(digest(canonical(request)) == row['control_intent_sha256'], UNVERIFIED)
    return receipt['control_key']


def original_start_dispatch(row, external):
    fields = ('dispatch', 'run_id', 'policy_sha256') if 'run_id' in external else ('dispatch',)
    exact(external, fields, UNVERIFIED)
    grant = external['dispatch']
    check_start_request_shape(grant)
    require(
        grant['operation_id'] == row['operation_id']
        and grant['environment_id'] == row['environment_id']
        and all(MINIMUM[field] <= grant['limits'][field] <= MAXIMUM[field] for field in DIMENSIONS)
        and (
            'run_id' not in external
            or (
                uuid_value(external['run_id'])
                and external['policy_sha256'] == grant['start_policy_sha256']
            )
        ),
        UNVERIFIED,
    )
    return grant


def cancelled_units(row, external):
    require(
        row['original_action'] == 'START'
        and row['original_operation_status'] == 'CANCELLED'
        and row['cancel_requested'] == 1
        and row['ordinal'] == 2
        and row['status'] == 'SUCCEEDED'
        and row['executor_ref'] == ORDINARY_EXECUTOR,
        UNVERIFIED,
    )
    original = decode(row['original_start_identity_json'].encode('utf-8'), UNVERIFIED)
    original_start_dispatch(row, original)
    control = original_cancel_control(row)
    result = decode(row['result_json'].encode('utf-8'), UNVERIFIED)
    require(
        external.get('control_key') == control
        and result.get('environment_id') == row['environment_id']
        and uuid_value(result.get('proof_id'))
        and is_timestamp(result.get('observed_at')),
        UNVERIFIED,
    )
    operation = row['operation_id']
    environment = row['environment_id']
    runtime = stopped_runtime_unit(environment, operation)
    if row['step_kind'] == 'RUNTIME_PREPARATION_CANCELLED':
        exact(external, ('control_key',), UNVERIFIED)
        exact(
            result,
            ('environment_id', 'observed_at', 'proof_id', 'control_revision', 'outcome'),
            UNVERIFIED,
        )
        require(
            row['original_start_status'] == 'SKIPPED'
            and result['outcome'] in ('UNCHANGED', 'RETIRED')
            and type(result['control_revision']) is int
            and result['control_revision'] > 0,
            UNVERIFIED,
        )
        return (f'walle-prep-{environment}-{operation}.service', runtime)
    exact(external, ('control_key', 'run_id'), UNVERIFIED)
    exact(
        result, ('environment_id', 'run_id', 'runtime_state', 'observed_at', 'proof_id'), UNVERIFIED
    )
    require(
        row['original_start_status'] in ('FAILED', 'SUCCEEDED')
        and uuid_value(external['run_id'])
        and external['run_id'] == result['run_id'] == original.get('run_id')
        and result['runtime_state'] == 'STOPPED',
        UNVERIFIED,
    )
    return (runtime,)


def deployment_step_binding(row, catalog):
    payload = row['external_identity_json']
    if type(payload) is not str:
        return None
    external = decode(payload.encode('utf-8'), UNVERIFIED)
    request = external.get('opening')
    if request is None:
        return None
    exact(external, ('maintenance', 'opening'), UNVERIFIED)
    action, executor = DEPLOYMENT_STEPS[row['step_kind']]
    grant = external['maintenance']
    original_action = row.get('original_action')
    allowed = RELEASE_ACTIONS if action == RELEASE else (action,)
    require(
        row['ordinal'] == 1
        and original_action in allowed
        and row['executor_ref'] == executor
        and type(grant) is dict
        and type(grant.get('format_version')) is int
        and grant['format_version'] == 1
        and uuid_value(row['registry_generation'])
        and grant.get('registry_generation') == row['registry_generation']
        and all(uuid_value(grant.get(field)) for field in ('manager_id', 'host_id'))
        and catalog is not None
        and all(grant[field] == catalog.scope[field] for field in ('manager_id', 'host_id')),
        UNVERIFIED,
    )
    check_open_request_shape(request)
    if action == RELEASE:
        require(
            ('target_access_sha256' in grant) == (original_action == RECONFIGURE)
            and (original_action != RECONFIGURE or sha_value(grant['target_access_sha256'])),
            UNVERIFIED,
        )
    if original_action == ROLLBACK_CODE:
        require(
            sha_value(grant.get('rollback_source_sha256')) and 'repair_of_operation_id' in grant,
            UNVERIFIED,
        )
        repair = grant['repair_of_operation_id']
        require(
            repair is None or (uuid_value(repair) and repair != row['operation_id']), UNVERIFIED
        )
    elif action == RELEASE:
        require(
            'rollback_source_sha256' not in grant and 'repair_of_operation_id' not in grant,
            UNVERIFIED,
        )
    expected = grant if action == RELEASE else grant['confirmation']
    target = expected['target']
    limits = exact(request['limits'], DIMENSIONS, UNVERIFIED)
    require(
        all(
            request[field] == row[field] == expected[field]
            for field in ('operation_id', 'environment_id')
        )
        and all(request[field] == target[field] for field in TARGET[1:])
        and sha_value(target['program_sha256'])
        and all(
            type(limits[field]) is int and MINIMUM[field] <= limits[field] <= MAXIMUM[field]
            for field in DIMENSIONS
        ),
        UNVERIFIED,
    )
    pin = 'release_manifest_sha256'
    if row['status'] == 'SUCCEEDED':
        result_json = row['result_json']
        require(
            type(result_json) is str and row.get('original_operation_status') == 'SUCCEEDED',
            UNVERIFIED,
        )
        result = decode(result_json.encode('utf-8'), UNVERIFIED)
        reference = expected['release_ref' if action == RELEASE else 'target_release_ref']
        require(
            all(result[field] == request[field] for field in (*TARGET, 'run_id'))
            and uuid_value(reference)
            and result['release_ref'] == reference
            and sha_value(expected[pin])
            and result[pin] == expected[pin]
            and uuid_value(result['proof_id'])
            and is_timestamp(result['opened_at'])
            and all(
                version(result[field])
                for field in ('control_revision', 'record_version', 'assignment_generation')
            ),
            UNVERIFIED,
        )
    binding = {
        **{field: request[field] for field in (*TARGET, 'run_id')},
        'program_sha256': target['program_sha256'],
    }
    return binding, grant, request


def checked_deployment_opening(catalog, row, grant, request):
    require(row['registry_generation'] == catalog.scope['registry_generation'], UNVERIFIED)
    if row['original_action'] in RELEASE_ACTIONS:
        receipt = opened_evidence(catalog, grant, request)
        attachment = grant['target_attachment']
    else:
        restored = opened_restore(catalog, grant, request)
        if restored is None:
            return None
        selection, receipt = restored
        attachment = selection['target_attachment']
    if receipt is None:
        return None
    path, pin = path_reference(receipt['runtime'])
    policy = load_policy(path, pin, catalog)
    return receipt, attachment, policy


def observed_deployment_authority(catalog, row, grant, request):
    if row['registry_generation'] != catalog.scope['registry_generation']:
        from .registry_recovered_runtime import recovered_authority

        return recovered_authority(catalog, row, request['run_id'], request['limits'])
    verified = checked_deployment_opening(catalog, row, grant, request)
    require(verified is not None, UNVERIFIED)
    receipt, _, policy = verified
    return {'policy_sha256': receipt['runtime']['sha256'], 'invocation_id': policy['invocation_id']}


def current_runtime_unit(row, unit, current):
    opening = row.get('opening_binding', {})
    authority = row.get('runtime_authority', {})
    binding = current.get('binding', {})
    authority_pin = authority.get('policy_sha256')
    invocation = authority.get('invocation_id')
    pid = unit.get('main_pid')
    lock_pid = current.get('lock_pid')
    return (
        current.get('state') == 'RUNNING_OBSERVED'
        and opening.get('run_id') is not None
        and current.get('run_id') == opening['run_id']
        and all(
            opening.get(key) is not None and binding.get(key) == opening[key]
            for key in (
                'environment_id',
                'deployment_id',
                'data_generation',
                'configuration_sha256',
            )
        )
        and sha_value(authority_pin)
        and current.get('policy_sha256') == authority_pin
        and invocation is not None
        and unit.get('invocation_id') == invocation
        and unit.get('active_state') == 'active'
        and unit.get('cgroup_empty') is False
        and type(pid) is int
        and pid > 1
        and type(lock_pid) is int
        and lock_pid > 1
        and lock_pid != pid
    )


def ordinary_start_binding(row, external):
    require(
        row['original_action'] == 'START'
        and row['ordinal'] == 1
        and row['executor_ref'] == ORDINARY_EXECUTOR,
        UNVERIFIED,
    )
    grant = original_start_dispatch(row, external)
    if row['status'] != 'SUCCEEDED':
        return grant, None
    result = exact(
        decode(row['result_json'].encode('utf-8'), UNVERIFIED),
        ('environment_id', 'run_id', 'runtime_state', 'observed_at', 'proof_id'),
        UNVERIFIED,
    )
    require(
        row['original_operation_status'] in ('SUCCEEDED', 'CANCELLED')
        and result['environment_id'] == grant['environment_id']
        and result['run_id'] == external['run_id']
        and result['runtime_state'] == 'RUNNING'
        and is_timestamp(result['observed_at'])
        and uuid_value(result['proof_id']),
        UNVERIFIED,
    )
    return grant, result


def observed_start_authority(catalog, row, grant, result):
    require(
        catalog is not None
        and row['original_operation_status'] == 'SUCCEEDED'
        and result is not None,
        UNVERIFIED,
    )
    if row['registry_generation'] != catalog.scope['registry_generation']:
        from .registry_recovered_runtime import recovered_authority

        return recovered_authority(
            catalog, row, result['run_id'], grant['limits'], boot_id=grant['boot_id']
        )
    operation = row['operation_id']
    directory = catalog.directory / 'observations'
    common = start_common(catalog, operation, row['environment_id'], grant['start_policy_sha256'])
    with protected_directory(directory) as parent:
        started = original_record(parent, f'start-{operation}.v1.json', common)
    require(started is not None and started['state'] == 'READY', UNVERIFIED)
    prepared = started['prepared']
    require(
        started['boot_id'] == grant['boot_id']
        and prepared['run_id'] == result['run_id']
        and all(prepared[field] == grant[field] for field in TARGET)
        and prepared['operation_id'] == operation
        and started['observation']
        == {
            **{field: result[field] for field in ('proof_id', 'environment_id', 'observed_at')},
            'state': 'RUNNING',
            'reason_code': 'MANAGED_APPLICATION_READY',
        },
        UNVERIFIED,
    )
    path, pin = path_reference(started['runtime'])
    require(path == directory / f'start-runtime-{operation}' / RUNTIME_POLICY, UNVERIFIED)
    policy = load_policy(path, pin, catalog)
    require(
        'release_open_policy' not in policy
        and policy['operation_id'] == operation
        and policy['run_id'] == result['run_id']
        and policy['boot_id'] == grant['boot_id']
        and policy['start_sha256'] == prepared['start_sha256']
        and policy['memory_bytes'] == grant['limits']['memory_bytes']
        and policy['tasks'] == grant['limits']['tasks']
        and policy['cpu_quota_usec'] == grant['limits']['cpu_percent'] * 1000
        and policy['cpu_period_usec'] == 100_000,
        UNVERIFIED,
    )
    return {
        'policy_sha256': pin,
        'invocation_id': policy['invocation_id'],
        'configuration_attachment': {
            'candidate_ref': policy['candidate_ref'],
            'sha256': policy['candidate_sha256'],
        },
    }


def original_units(row, catalog=None):
    require(
        all(
            uuid_value(row[field])
            for field in ('environment_id', 'operation_id', 'registry_generation')
        ),
        UNVERIFIED,
    )
    payload = row['external_identity_json']
    if (
        catalog is not None
        and row['step_kind'] == STOP_STEP
        and row['status'] == 'PLANNED'
        and row['ordinal'] == 1
        and row['registry_generation'] == catalog.scope['registry_generation']
        and row['executor_ref'] is None
        and payload is None
    ):
        receipt = observed_stop_receipt(
            catalog, row['operation_id'], row['environment_id'], row.get('stop_run_id')
        )
        return (stopped_runtime_unit(row['environment_id'], receipt['start_operation_id']),)
    if type(payload) is not str:
        return ()
    identity = decode(payload.encode('utf-8'), UNVERIFIED)
    if row['step_kind'] in CANCEL_STEPS:
        require(
            all(
                type(row.get(key)) is str
                for key in ('original_start_identity_json', 'control_receipt_json', 'result_json')
            ),
            UNVERIFIED,
        )
        return cancelled_units(row, identity)
    if row['step_kind'] == STOP_STEP and row['executor_ref'] == ORDINARY_EXECUTOR:
        original = original_runtime_identity(identity, row['operation_id'])
        return (stopped_runtime_unit(row['environment_id'], original['start_operation_id']),)
    return ()


def unit_observation(unit):
    before = unit_facts(unit)
    empty = preparation_group_empty(unit)
    require(before == unit_facts(unit) and empty == preparation_group_empty(unit), UNVERIFIED)
    load = before['LoadState']
    active = before.get('ActiveState')
    main = before.get('MainPID', '0')
    require(main.isascii() and main.isdecimal(), UNVERIFIED)
    if load == 'not-found' and empty and main == '0':
        state = 'ABSENT_OBSERVED'
    elif load == 'loaded' and empty and main == '0' and active in ('inactive', 'failed'):
        state = 'QUIET_OBSERVED'
    elif load == 'loaded' and active in ('active', 'activating', 'deactivating'):
        state = 'PRESENT_OBSERVED'
    else:
        state = 'UNKNOWN'
    return {
        'unit': unit,
        'load_state': load,
        'active_state': active,
        'invocation_id': before.get('InvocationID') or None,
        'main_pid': int(main),
        'cgroup_empty': empty,
        'state': state,
    }


def helper_observation(row, catalog=None):
    subject = {
        'kind': 'ORIGINAL_HELPER_STEP',
        'environment_id': row['environment_id'],
        'operation_id': row['operation_id'],
        'ordinal': row['ordinal'],
        'step_kind': row['step_kind'],
        'original_status': row['status'],
    }
    measured = []
    try:
        if row['step_kind'] in DEPLOYMENT_STEPS:
            opening = deployment_step_binding(row, catalog)
            units = ()
            if opening is not None:
                subject['opening_binding'], grant, request = opening
                units = (stopped_runtime_unit(row['environment_id'], row['operation_id']),)
        elif row['step_kind'] == START_STEP and type(row['external_identity_json']) is str:
            require(
                uuid_value(row['environment_id'])
                and uuid_value(row['operation_id'])
                and uuid_value(row['registry_generation']),
                UNVERIFIED,
            )
            start = decode(row['external_identity_json'].encode('utf-8'), UNVERIFIED)
            grant, outcome = ordinary_start_binding(row, start)
            units = (
                f'walle-prep-{row["environment_id"]}-{row["operation_id"]}.service',
                stopped_runtime_unit(row['environment_id'], row['operation_id']),
            )
            if outcome is not None:
                subject['opening_binding'] = {
                    **{field: grant[field] for field in TARGET},
                    'run_id': outcome['run_id'],
                }
        else:
            units = original_units(row, catalog)
        for unit in units:
            try:
                result = unit_observation(unit)
            except OBSERVATION_FAILURE:
                result = {'unit': unit, 'state': 'UNKNOWN'}
            measured.append(result)
            if not (result['state'] == 'PRESENT_OBSERVED' and unit.startswith('walle-env-')):
                continue
            if row['step_kind'] in DEPLOYMENT_STEPS:
                subject['runtime_authority'] = observed_deployment_authority(
                    catalog, row, grant, request
                )
            elif row['step_kind'] == START_STEP:
                subject['runtime_authority'] = observed_start_authority(
                    catalog, row, grant, outcome
                )
    except OBSERVATION_FAILURE:
        pass
    state = (
        'OBSERVED'
        if measured and all(item['state'] != 'UNKNOWN' for item in measured)
        else 'UNKNOWN'
    )
    if (
        row.get('original_action') == 'START'
        and row.get('original_operation_status') == 'CANCELLED'
    ):
        subject['original_operation_status'] = 'CANCELLED'
    return {**subject, 'state': state, 'units': measured}
