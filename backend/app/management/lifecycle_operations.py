"""Bind accepted local runtime operations to protected physical receipts."""

from backend.app.infrastructure.environment_control import normal_stop
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    exact,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import machine_clock, now
from .operation_contract import (
    DENIED,
    INVALID,
    MISSING,
    RESOURCE,
    UNAVAILABLE,
    VERSION,
    installed_record,
    version,
)
from .operation_store import (
    decoded,
    environment_row,
    insert_operation,
    insert_step,
    may_read_operation,
    mutation,
    operation_by_key,
    operation_result,
    require_no_conflicting_action,
    stored,
)
from .registry import is_timestamp
from .runtime_capacity import (
    DIMENSIONS,
    check_capacity,
    load_capacity,
    release_capacity,
    release_rows,
    reservations_for,
    reserve_capacity,
    verify_reservation,
)
from .runtime_observation import project_runtime

STEPS = {'START': 'RUNTIME_STARTED', 'STOP': 'RUNTIME_STOPPED'}


def lifecycle_intent(raw):
    action = raw['action']
    extra = 'expected_configuration_sha256' if action == 'START' else 'target'
    exact(
        raw,
        (
            'action',
            'environment_id',
            'expected_record_version',
            'expected_assignment_generation',
            extra,
        ),
        INVALID,
    )
    require(
        uuid_value(raw['environment_id'])
        and version(raw['expected_record_version'])
        and version(raw['expected_assignment_generation']),
        INVALID,
    )
    if action == 'START':
        require(sha_value(raw[extra]), INVALID)
    else:
        target = exact(raw[extra], ('kind', 'run_id'), INVALID)
        require(target['kind'] == 'RUN' and uuid_value(target['run_id']), INVALID)
    return raw


def authorized(connection, principal, environment):
    row = environment_row(connection, environment)
    require(
        row is not None
        and (
            principal.role == 'MANAGER'
            or principal.role == 'DEVELOPER'
            and row['writer_principal'] == principal.id
        ),
        DENIED,
    )
    require(
        row['registration_state'] == 'ACTIVE'
        and row['preparation_state'] == 'PREPARED'
        and row['assignment_control_state'] == 'OPEN'
        and row['purpose'] in ('DEVELOPMENT', 'INTEGRATION'),
        UNAVAILABLE,
    )
    return row


def expected_versions(row, intent):
    require(
        row['record_version'] == intent['expected_record_version']
        and row['assignment_generation'] == intent['expected_assignment_generation'],
        VERSION,
    )


def startup_capacity(connection, catalog, row, intent, projected):
    from .release_maintenance_view import confirmed_current_control

    require(row['configuration_sha256'] == intent['expected_configuration_sha256'], VERSION)
    physical = confirmed_current_control(catalog, row)
    require(physical is not None, RESOURCE)
    require(
        normal_stop(physical),
        UNAVAILABLE,
    )
    require(
        not (
            projected
            and projected['freshness'] == 'FRESH'
            and projected['runtime_state'] == 'RUNNING'
        ),
        RESOURCE,
    )
    policy = load_capacity(catalog)
    return policy, check_capacity(connection, policy, row)


def accept_runtime(connection, lock, catalog, generation, principal, key, intent):
    with mutation(connection, lock):
        row = authorized(connection, principal, intent['environment_id'])
        expected_versions(row, intent)
        require_no_conflicting_action(connection, row['environment_id'])
        projected = project_runtime(catalog, row, decoded(row['work_package_json']))
        policy = None
        waiting = None
        if intent['action'] == 'START':
            policy, waiting = startup_capacity(connection, catalog, row, intent, projected)
        else:
            require(
                projected is not None
                and projected['freshness'] == 'FRESH'
                and projected['run_id'] == intent['target']['run_id']
                and projected['reason_code']
                in ('MANAGED_APPLICATION_READY', 'MANAGED_STOP_CONFIRMED'),
                RESOURCE,
            )
        operation = insert_operation(
            connection,
            generation,
            key,
            principal,
            intent,
            row['environment_id'],
            now(),
            status='WAITING_CAPACITY' if waiting else 'ACCEPTED',
        )
        insert_step(connection, operation, STEPS[intent['action']], waiting, status='PLANNED')
        if policy is not None and waiting is None:
            reserve_capacity(connection, operation, policy, row, stored)
        return operation_result(connection, operation_by_key(connection, generation, key))


def check_start_request_shape(request):
    exact(
        request,
        (
            'operation_id',
            'environment_id',
            'configuration_sha256',
            'data_generation',
            'deployment_id',
            'capacity_sha256',
            'limits',
            'start_policy_sha256',
            'boot_id',
        ),
        INVALID,
    )
    require(
        all(
            uuid_value(request[key])
            for key in (
                'operation_id',
                'environment_id',
                'data_generation',
                'deployment_id',
                'boot_id',
            )
        )
        and all(
            sha_value(request[key])
            for key in ('configuration_sha256', 'capacity_sha256', 'start_policy_sha256')
        ),
        INVALID,
    )
    usage = exact(request['limits'], DIMENSIONS, INVALID)
    require(all(type(value) is int for value in usage.values()), INVALID)


def dispatch_start(connection, lock, catalog, request):
    check_start_request_shape(request)
    require(request['boot_id'] == machine_clock()[0], INVALID)
    with mutation(connection, lock):
        operation = connection.execute(
            'SELECT * FROM management_operations WHERE operation_id=? AND registry_generation=?',
            (request['operation_id'], catalog.scope['registry_generation']),
        ).fetchone()
        require(
            operation is not None
            and operation['action'] == 'START'
            and operation['environment_id'] == request['environment_id'],
            RESOURCE,
        )
        principal = catalog.access(operation['principal'])
        row = authorized(connection, principal, operation['environment_id'])
        expected_versions(row, decoded(operation['intent_json']))
        profile = load_capacity(catalog)
        work = decoded(row['work_package_json'])
        require(
            request['configuration_sha256'] == row['configuration_sha256']
            and request['deployment_id'] == work['deployment_id']
            and request['data_generation'] == work['data_generation']
            and request['capacity_sha256'] == profile.sha256
            and request['limits'] == profile.profile(row),
            RESOURCE,
        )
        verify_reservation(connection, operation['operation_id'], profile, row, stored)
        step = connection.execute(
            'SELECT status, external_identity_json FROM management_steps WHERE operation_id=? '
            "AND ordinal=1 AND step_kind='RUNTIME_STARTED'",
            (operation['operation_id'],),
        ).fetchone()
        require(step is not None, RESOURCE)
        if operation['status'] in ('RUNNING', 'UNKNOWN'):
            require(
                step['status'] in ('DISPATCHING', 'UNKNOWN')
                and decoded(step['external_identity_json']).get('dispatch') == request,
                RESOURCE,
            )
            return {'admission': request, 'dispatch_allowed': not operation['cancel_requested']}
        require(
            operation['status'] == 'ACCEPTED'
            and step['status'] == 'PLANNED'
            and not operation['cancel_requested'],
            UNAVAILABLE,
        )
        require(operation['revision'] < MAX_REVISION, VERSION)
        advanced = connection.execute(
            "UPDATE management_operations SET status='RUNNING', revision=revision+1 "
            'WHERE operation_id=? AND revision=?',
            (operation['operation_id'], operation['revision']),
        )
        stepped = connection.execute(
            "UPDATE management_steps SET status='DISPATCHING', executor_ref=?, external_identity_json=? "
            "WHERE operation_id=? AND ordinal=1 AND step_kind='RUNTIME_STARTED' AND status='PLANNED'",
            ('SYSTEMD_ORDINARY_RUNTIME', stored({'dispatch': request}), operation['operation_id']),
        )
        require(advanced.rowcount == stepped.rowcount == 1, RESOURCE)
        return {'admission': request, 'dispatch_allowed': True}


def host_effect(catalog, operation, intent, environment):
    action = operation['action']
    identity = operation['operation_id']
    location = catalog.directory / 'observations' / (action.lower() + '-' + identity + '.v1.json')
    try:
        record = installed_record(location)
    except FileNotFoundError:
        return None
    require(
        record.get('format_version') == 1
        and all(record.get(key) == value for key, value in catalog.scope.items())
        and record.get('environment_id') == operation['environment_id']
        and record.get(action.lower() + '_operation_id') == identity,
        RESOURCE,
    )
    source_start = None
    if action == 'START':
        state = record.get('state')
        require(
            state in ('RESERVED', 'PREPARING', 'STARTING', 'READY', 'RUNNING_UNREADY'), RESOURCE
        )
        if state in ('RESERVED', 'PREPARING'):
            return None
        prepared = record.get('prepared')
        work = decoded(environment['work_package_json'])
        require(
            type(prepared) is dict
            and prepared.get('environment_id') == operation['environment_id']
            and prepared.get('configuration_sha256') == intent['expected_configuration_sha256']
            and prepared.get('operation_id') == identity
            and prepared.get('deployment_id') == work['deployment_id']
            and prepared.get('data_generation') == work['data_generation']
            and uuid_value(prepared.get('run_id'))
            and sha_value(record.get('start_policy_sha256')),
            RESOURCE,
        )
        run_id = prepared['run_id']
        source_sha = record['start_policy_sha256']
        success_state, reason = 'RUNNING', 'MANAGED_APPLICATION_READY'
        if state == 'RUNNING_UNREADY':
            reason = 'MANAGED_APPLICATION_UNVERIFIED'
        if state == 'STARTING':
            return run_id, source_sha, source_start, None
    else:
        state = record.get('state')
        require(state in ('PREPARED', 'DISPATCHING', 'STOPPED'), RESOURCE)
        run_id = intent['target']['run_id']
        source_sha = record.get('stop_policy_sha256')
        source_start = record.get('start_operation_id')
        require(
            record.get('run_id') == run_id
            and sha_value(source_sha)
            and uuid_value(source_start)
            and source_start != identity,
            RESOURCE,
        )
        if state == 'PREPARED':
            return None
        if state == 'DISPATCHING':
            return run_id, source_sha, source_start, None
        success_state, reason = 'STOPPED', 'MANAGED_STOP_CONFIRMED'

    observation = exact(
        record.get('observation'),
        (
            'proof_id',
            'environment_id',
            'observed_at',
            'state',
            'reason_code',
        ),
        RESOURCE,
    )
    require(
        observation['environment_id'] == operation['environment_id']
        and uuid_value(observation['proof_id'])
        and is_timestamp(observation['observed_at'])
        and observation['state'] == success_state
        and observation['reason_code'] == reason,
        RESOURCE,
    )
    return (
        run_id,
        source_sha,
        source_start,
        {
            'environment_id': observation['environment_id'],
            'run_id': run_id,
            'runtime_state': 'STARTED_UNREADY' if state == 'RUNNING_UNREADY' else success_state,
            'observed_at': observation['observed_at'],
            'proof_id': observation['proof_id'],
        },
    )


def reconcile_runtime(connection, lock, catalog, generation, principal, key):
    with mutation(connection, lock):
        operation = operation_by_key(connection, generation, key)
        require(operation is not None, MISSING)
        require(may_read_operation(connection, principal, operation), DENIED)
        return reconcile_original(connection, catalog, principal, operation)


def reconcile_original(connection, catalog, principal, operation):
    require(operation['action'] in STEPS, UNAVAILABLE)
    if operation['status'] in ('SUCCEEDED', 'CANCELLED'):
        return operation_result(connection, operation)
    require(
        operation['status'] in ('ACCEPTED', 'RUNNING', 'UNKNOWN', 'WAITING_CAPACITY'), UNAVAILABLE
    )
    row = authorized(connection, principal, operation['environment_id'])
    intent = decoded(operation['intent_json'])
    expected_versions(row, intent)
    if operation['status'] == 'WAITING_CAPACITY':
        return operation_result(connection, operation)
    step = connection.execute(
        'SELECT external_identity_json FROM management_steps WHERE operation_id=? AND ordinal=1',
        (operation['operation_id'],),
    ).fetchone()
    require(step is not None, RESOURCE)
    previous = decoded(step[0]) if step[0] is not None else {}
    grant = previous.get('dispatch')
    cancelled = operation['action'] == 'START' and operation['cancel_requested']
    key = cancel_control_key(connection, operation) if cancelled and grant is not None else None
    if key is not None and operation['status'] == 'RUNNING':
        closed = close_unissued_start(connection, catalog, operation, grant, key)
        if closed is not None:
            return closed
    effect = host_effect(catalog, operation, intent, row)
    if effect is None:
        return operation_result(connection, operation)
    run_id, source_sha, source_start, outcome = effect
    external = {'run_id': run_id, 'policy_sha256': source_sha}
    if source_start is not None:
        external['start_operation_id'] = source_start

    if grant is not None:
        require(grant['start_policy_sha256'] == source_sha, RESOURCE)
        external['dispatch'] = grant
    if operation['status'] == 'UNKNOWN':
        require(
            previous and all(external.get(key) == value for key, value in previous.items()),
            RESOURCE,
        )
    if cancelled:
        if key is not None:
            finished = close_cancelled_start(
                connection, catalog, operation, source_sha, external, outcome, key
            )
            if finished is not None:
                return finished
        outcome = None
    if outcome is not None and outcome['runtime_state'] == 'STARTED_UNREADY':
        outcome = None
    if operation['status'] == 'UNKNOWN' and outcome is None:
        return operation_result(connection, operation)
    terminal = outcome is not None
    if terminal and source_start is not None:
        release_capacity(
            connection,
            source_start,
            operation['operation_id'],
            operation['environment_id'],
            outcome,
            stored,
            decoded,
        )
    require(operation['revision'] < MAX_REVISION, VERSION)
    updated = connection.execute(
        'UPDATE management_operations SET status=?, revision=revision+1 WHERE operation_id=? AND revision=?',
        (
            'SUCCEEDED' if terminal else 'UNKNOWN',
            operation['operation_id'],
            operation['revision'],
        ),
    )
    require(updated.rowcount == 1, VERSION)
    changed = connection.execute(
        'UPDATE management_steps SET status=?,executor_ref=?,external_identity_json=?,result_json=? '
        'WHERE operation_id=? AND ordinal=1 AND step_kind=?',
        (
            'SUCCEEDED' if terminal else 'UNKNOWN',
            'SYSTEMD_ORDINARY_RUNTIME',
            stored(external),
            stored(outcome) if terminal else None,
            operation['operation_id'],
            STEPS[operation['action']],
        ),
    )
    require(changed.rowcount == 1, RESOURCE)
    return operation_result(
        connection,
        operation_by_key(connection, operation['registry_generation'], operation['request_key']),
    )


def cancel_control_key(connection, operation):
    controls = connection.execute(
        "SELECT control_key FROM management_controls WHERE operation_id=? AND command='CANCEL'",
        (operation['operation_id'],),
    ).fetchall()
    require(len(controls) == 1, RESOURCE)
    return controls[0]['control_key']


def close_unissued_start(connection, catalog, operation, grant, key):
    from .runtime_cancel import retirement_proof, start_common

    identity = operation['operation_id']
    common = start_common(
        catalog, identity, operation['environment_id'], grant['start_policy_sha256']
    )
    with protected_directory(catalog.directory / 'observations') as observed:
        proof = retirement_proof(observed, common, key)
    if proof is None:
        return None
    require(proof['boot_id'] == grant['boot_id'] and operation['status'] == 'RUNNING', RESOURCE)
    require(operation['revision'] < MAX_REVISION, VERSION)
    claims = reservations_for(connection, identity)
    release_rows(connection, identity, operation['environment_id'], claims, proof, stored)
    finished = connection.execute(
        "UPDATE management_operations SET status='CANCELLED',revision=revision+1 "
        'WHERE operation_id=? AND revision=? AND cancel_requested=1',
        (identity, operation['revision']),
    )
    step = connection.execute(
        "UPDATE management_steps SET status='SKIPPED',result_json=NULL "
        "WHERE operation_id=? AND ordinal=1 AND step_kind='RUNTIME_STARTED' AND status='DISPATCHING'",
        (identity,),
    )
    require(finished.rowcount == step.rowcount == 1, RESOURCE)
    if proof['cutoff'] == 'PREPARING':
        result = {
            'environment_id': operation['environment_id'],
            'observed_at': proof['observed_at'],
            'proof_id': proof['proof_id'],
            'control_revision': proof['control_revision'],
            'outcome': proof['retirement_state'],
        }
        connection.execute(
            'INSERT INTO management_steps '
            '(operation_id,ordinal,step_kind,status,executor_ref,external_identity_json,result_json) '
            "VALUES (?,2,'RUNTIME_PREPARATION_CANCELLED','SUCCEEDED','SYSTEMD_ORDINARY_RUNTIME',?,?)",
            (identity, stored({'control_key': key}), stored(result)),
        )
    return operation_result(
        connection,
        operation_by_key(connection, operation['registry_generation'], operation['request_key']),
    )


def close_cancelled_start(connection, catalog, operation, source_sha, external, launched, key):
    from .runtime_cancel import cancellation_effect, start_common
    from .runtime_early_cancel import early_effect

    if launched is None:
        common = start_common(
            catalog, operation['operation_id'], operation['environment_id'], source_sha
        )
        with protected_directory(catalog.directory / 'observations') as observed:
            actual = early_effect(observed, common, key)
        if actual is None:
            return None
        binding, proof = actual
        launched = {
            'environment_id': operation['environment_id'],
            'run_id': binding['run_id'],
            'runtime_state': 'STARTED_UNREADY',
            'observed_at': binding['observed_at'],
            'proof_id': binding['proof_id'],
        }
    else:
        actual = cancellation_effect(catalog, operation, source_sha, key)
        if actual is None:
            return None
        binding, proof = actual
    require(launched['run_id'] == binding['run_id'] == external['run_id'], RESOURCE)
    stopped = {
        'environment_id': proof['environment_id'],
        'run_id': binding['run_id'],
        'runtime_state': 'STOPPED',
        'observed_at': proof['observed_at'],
        'proof_id': proof['proof_id'],
    }
    identity = operation['operation_id']
    claims = reservations_for(connection, identity)
    release_rows(
        connection,
        identity,
        operation['environment_id'],
        claims,
        {'control_key': key, **stopped},
        stored,
    )
    require(operation['revision'] < MAX_REVISION, VERSION)
    closed = connection.execute(
        "UPDATE management_operations SET status='CANCELLED',revision=revision+1 "
        'WHERE operation_id=? AND revision=? AND cancel_requested=1',
        (identity, operation['revision']),
    )
    completed = connection.execute(
        'UPDATE management_steps SET status=?,external_identity_json=?,result_json=? '
        "WHERE operation_id=? AND ordinal=1 AND step_kind='RUNTIME_STARTED'",
        (
            'FAILED' if launched['runtime_state'] == 'STARTED_UNREADY' else 'SUCCEEDED',
            stored(external),
            stored(launched),
            identity,
        ),
    )
    require(closed.rowcount == completed.rowcount == 1, RESOURCE)
    connection.execute(
        'INSERT INTO management_steps '
        '(operation_id,ordinal,step_kind,status,executor_ref,external_identity_json,result_json) '
        "VALUES (?,2,'RUNTIME_START_CANCELLED','SUCCEEDED','SYSTEMD_ORDINARY_RUNTIME',?,?)",
        (identity, stored({'control_key': key, 'run_id': binding['run_id']}), stored(stopped)),
    )
    return operation_result(
        connection,
        operation_by_key(connection, operation['registry_generation'], operation['request_key']),
    )
