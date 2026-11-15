"""Original Coding termination acceptance and safe stop projections."""

import asyncio
import hashlib
import sqlite3

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .command_registry import registered_command, validate_registered_success
from .configuration_identities import require_schema
from .operation_protocol import operation_steps

STOP_CAPABILITY = 'APP-CODE-CMD-C37'
STOP_STEPS = operation_steps('CODING', 'TERMINATE')
STOP_PATH = '/api/v1/code-tasks/{task_id}/terminate'
NO_ACTIVITY_FIELDS = (
    'workspace_id',
    'active_session_id',
    'current_candidate_id',
    'current_verification_id',
    'current_test_report_id',
    'current_delivery_plan_id',
    'current_delivery_id',
    'resume_phase',
    'started_at',
)
# References in subsidiary tables (LLM uses, checkpoints, private packages,
# delivery locks) have an original owner in one of these root records.
EXECUTION_TABLES = (
    'code_workspaces',
    'code_instances',
    'code_commands',
    'code_sessions',
    'code_execution_records',
    'code_environment_records',
    'code_runtime_observations',
    'code_configuration_applications',
    'code_waiting_items',
    'code_task_reservations',
    'code_candidates',
    'code_verifications',
    'code_questions',
    'code_permissions',
    'code_question_handoffs',
    'code_defects',
    'code_repairs',
    'code_delivery_plans',
    'code_acceptances',
    'code_deliveries',
)


def stop_operation(connection, task_id):
    return connection.execute(
        "SELECT * FROM code_operations WHERE task_id=? AND operation_type='TERMINATE'",
        (task_id,),
    ).fetchone()


def original_stop_result(connection, operation):
    """Aliases and the worker rely on the one primary, already committed 202."""
    command = registered_command(
        'POST', STOP_PATH.format(task_id=operation['task_id']), operation['idempotency_key']
    )
    receipt = connection.execute(
        """SELECT status,business_input_json,success_result_json,http_status
           FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    if (
        operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != operation['task_id']
        or operation['testing_task_id'] is not None
        or operation['operation_type'] != 'TERMINATE'
        or receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['business_input_json'] != operation['fixed_input']
    ):
        raise StorageUnavailable(
            'Original termination receipt is missing or belongs to another owner'
        )
    try:
        fixed = strict_json_object(operation['fixed_input'])
        required = {'task_id', 'expected_state_version'}
        if set(fixed) not in (required, required | {'reason'}) or (
            type(fixed['task_id']) is not int
            or fixed['task_id'] != operation['task_id']
            or type(fixed['expected_state_version']) is not int
            or fixed['expected_state_version'] != operation['expected_state_version']
            or (
                'reason' in fixed
                and (type(fixed['reason']) is not str or not fixed['reason'].strip())
            )
        ):
            raise ValueError('Original termination input differs from its task')
        stored = strict_json_object(receipt['success_result_json'])
        result = Success(stored, receipt['http_status'])
        result.encoded()
        data = stored['data']
        validate_registered_success(command, data, stored['code'], result.http_status)
    except (ValueError, KeyError, TypeError) as error:
        raise StorageUnavailable('Original termination acceptance is invalid') from error
    if (
        result.http_status != 202
        or data['operation_id'] != operation['id']
        or data['state_version'] != operation['expected_state_version'] + 1
    ):
        raise StorageUnavailable('Original termination acceptance differs')
    return result


def _close_task_model_windows(connection, task, at):
    sessions = connection.execute(
        """SELECT id,status,model_window FROM code_sessions WHERE task_id=?
           AND control_generation<=? AND model_window IS NOT NULL""",
        (task['id'], task['control_generation']),
    ).fetchall()
    for session in sessions:
        window = strict_json_object(session['model_window'])
        if window.get('state') in ('CLOSED', 'RETIRED'):
            continue
        if window.get('state') not in ('QUEUED', 'OPEN', 'HELD'):
            raise StorageUnavailable('Original model window status differs')
        window.update(state='CLOSED', closed_at=at)
        connection.execute(
            """UPDATE code_sessions SET model_window=?,status=? WHERE id=?""",
            (
                canonical_input(window),
                'QUIESCING' if session['status'] == 'ACTIVE' else session['status'],
                session['id'],
            ),
        )


def _new_stop(connection, task, request, now):
    # The persisted generation changes in the same transaction as the unique
    # intent. Every supported task launch must first have an original operation.
    require_write_transaction(connection)
    version = task['state_version']
    generation = task['control_generation']
    if version >= MAX_SAFE_INTEGER - 1 or generation == MAX_SAFE_INTEGER:
        return Rejection('PRECONDITION_FAILED', empty_conflict())
    high_water = connection.execute(
        'SELECT last_value FROM sequences WHERE entity_kind=?', (EntityKind.OPERATION_RECORD.value,)
    ).fetchone()
    if high_water is not None and high_water[0] == MAX_SAFE_INTEGER:
        return Rejection('PRECONDITION_FAILED', empty_conflict())
    operation_id = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input(request.business_input())
    advanced = connection.execute(
        """UPDATE code_tasks SET status='STOPPING',state_version=?,control_generation=?,
           stop_requested_at=?,updated_at=?,resume_phase=NULL WHERE id=? AND state_version=? AND control_generation=?
           AND status NOT IN ('STOPPING','COMPLETED','TERMINATED') AND stop_requested_at IS NULL""",
        (version + 1, generation + 1, now, now, task['id'], version, generation),
    )
    if advanced.rowcount != 1:
        raise StorageUnavailable('Original task changed inside control transaction')
    _close_task_model_windows(connection, task, now)
    connection.execute(
        """INSERT INTO code_operations(
           id,task_id,resource_kind,resource_id,session_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,'TERMINATE',?,?,?,?,'PENDING',?)""",
        (
            operation_id,
            task['id'],
            task['id'],
            task['active_session_id'],
            request.idempotency_key,
            version,
            fixed,
            generation + 1,
            now,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [(operation_id, number, step, fixed) for number, step in enumerate(STOP_STEPS, 1)],
    )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': operation_id,
                'operation_status': 'PENDING',
                'task_status': 'STOPPING',
                'state_version': version + 1,
            },
            'details': None,
        },
        202,
    )


def accept_task_stop(runtime, request):
    require_schema(runtime)

    def accept(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return Rejection('NOT_FOUND', None)
        if task['status'] in ('TERMINATED', 'COMPLETED'):
            from .task_read_api import project_saved_task

            data = project_saved_task(connection, runtime.catalog, task)
            return Success({'code': 'TASK_ALREADY_ENDED', 'data': data, 'details': None}, 200)
        previous = stop_operation(connection, task['id'])
        if previous is not None:
            if (
                task['status'] != 'STOPPING'
                or task['control_generation'] != previous['control_generation']
            ):
                raise StorageUnavailable('Original stop intent differs from its task')
            return original_stop_result(connection, previous)
        if task['status'] == 'STOPPING' or task['stop_requested_at'] is not None:
            raise StorageUnavailable('Stopping task has no original stop intent')
        if task['state_version'] != request.expected_state_version:
            return Rejection(
                'VERSION_CONFLICT',
                {
                    **empty_conflict(),
                    'task_id': task['id'],
                    'current_state_version': task['state_version'],
                },
            )
        now = operation_time(None)
        if now < task['updated_at']:
            raise StorageUnavailable('Task control clock is behind its durable state')
        return _new_stop(connection, task, request, now)

    return execute_idempotent(
        runtime.commands(),
        STOP_CAPABILITY,
        request,
        accept,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def _stop_steps(connection, operation):
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(STOP_STEPS) or any(
        row['step_no'] != number
        or row['step_type'] != kind
        or row['fixed_input'] != operation['fixed_input']
        for number, (kind, row) in enumerate(zip(STOP_STEPS, steps), 1)
    ):
        raise StorageUnavailable('Original stop step registration is invalid')
    return steps


def _queued_start_before_stop(connection, task, stop, *, cancelled_at=None, configuration_id=None):
    from .task_budget import budget_only_versions, start_budget_versions
    from .task_start import original_start_steps

    rows = connection.execute(
        'SELECT * FROM code_operations WHERE task_id=? AND id<>? AND id IS NOT ? LIMIT 2',
        (task['id'], stop['id'], configuration_id),
    ).fetchall()
    if len(rows) != 1:
        return None
    (start,) = rows
    status = 'PENDING' if cancelled_at is None else 'CANCELLED'
    if (
        start['operation_type'] != 'START'
        or start['status'] != status
        or start['control_generation'] != stop['control_generation'] - 1
        or not start_budget_versions(
            connection,
            task,
            start,
            offset=1,
            version=stop['expected_state_version'],
            through=stop['created_at'],
        )
        or not budget_only_versions(
            connection,
            task,
            start['expected_state_version'],
            through=start['created_at'],
            match_current=False,
        )
        or start['created_at'] > stop['created_at']
        or start['started_at'] is not None
        or start['ended_at'] != cancelled_at
        or start['session_id'] is not None
        or start['failure_code'] is not None
    ):
        return None
    try:
        _, steps = original_start_steps(connection, start)
    except (StorageUnavailable, ValueError, TypeError, KeyError):
        return None
    if any(
        step['status'] != status
        or any(step[key] is not None for key in ('external_identity', 'result_ref', 'started_at'))
        or step['ended_at'] != cancelled_at
        or step['last_observed_at'] != cancelled_at
        for step in steps
    ):
        return None
    return start['id']


def _empty_configuration_before_stop(connection, task, stop, cancelled_at):
    from .task_configuration_progress import public_configuration_operation, staged_configuration

    original = staged_configuration(connection, task['id'])
    if original is None:
        return True, None
    public = public_configuration_operation(connection, original)
    if (
        original['status'] != ('RUNNING' if cancelled_at is None else 'CANCELLED')
        or original['ended_at'] != cancelled_at
        or original['control_generation'] != stop['control_generation'] - 1
        or original['created_at'] > stop['created_at']
        or original['expected_state_version'] >= stop['expected_state_version']
        or public['fixed_input']['authorization_id'] != task['authorization_id']
        or public['fixed_input']['execution_profile_version_id']
        != task['execution_profile_version_id']
    ):
        return False, None
    return True, original['id']


def _empty_start_proof(connection, task, operation, *, cancelled_at=None):
    from .task_budget import budget_only_versions

    safe, configuration = _empty_configuration_before_stop(
        connection, task, operation, cancelled_at
    )
    if not safe:
        return False, None, None
    prior = connection.execute(
        'SELECT 1 FROM code_operations WHERE task_id=? AND id<>? AND id IS NOT ? LIMIT 1',
        (task['id'], operation['id'], configuration),
    ).fetchone()
    if prior is None:
        return (
            budget_only_versions(
                connection,
                task,
                operation['expected_state_version'],
                through=operation['created_at'],
            ),
            None,
            configuration,
        )
    cancelled = _queued_start_before_stop(
        connection, task, operation, cancelled_at=cancelled_at, configuration_id=configuration
    )
    return cancelled is not None, cancelled, configuration


def _zero_scope(connection, task, operation):
    """Observe a pristine task or one original START fenced before allocation."""
    if (
        operation['session_id'] is not None
        or task['control_generation'] != 2
        or task['stop_requested_at'] != operation['created_at']
        or any(task[field] is not None for field in NO_ACTIVITY_FIELDS)
    ):
        return None
    owned = (task['id'],)
    unstarted, queued_start, configuration = _empty_start_proof(connection, task, operation)
    if not unstarted:
        return None
    approvals = connection.execute(
        'SELECT id,profile_version_id,status FROM code_authorizations WHERE task_id=?', owned
    ).fetchall()
    active = [tuple(row) for row in approvals if row['status'] != 'RETIRED']
    if active != [
        (task['authorization_id'], task['execution_profile_version_id'], 'BOUND_PENDING_APPLY')
    ]:
        return None
    if len(approvals) != 1 + int(configuration is not None):
        return None
    # Each catalogue root is searched across every original generation.
    counts = {
        table: connection.execute(
            'SELECT count(*) FROM ' + table + ' WHERE task_id=?', owned
        ).fetchone()[0]
        for table in EXECUTION_TABLES
    }
    if any(
        count != int(table == 'code_configuration_applications' and configuration is not None)
        for table, count in counts.items()
    ):
        return None
    return _empty_stop_evidence(task, operation, counts, queued_start, configuration)


def _pending_scope(connection, operation_id):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
    ).fetchone()
    if operation is None or operation['status'] != 'PENDING':
        return None
    if (
        connection.execute(
            'SELECT 1 FROM code_instances WHERE task_id=? LIMIT 1', (operation['task_id'],)
        ).fetchone()
        is not None
    ):
        return None
    original_stop_result(connection, operation)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    if (
        task is None
        or task['status'] != 'STOPPING'
        or task['state_version'] != operation['expected_state_version'] + 1
        or task['control_generation'] != operation['control_generation']
    ):
        raise StorageUnavailable('Original stop is not fenced')
    steps = _stop_steps(connection, operation)
    if any(
        row['status'] != 'PENDING'
        or any(
            row[field] is not None
            for field in (
                'external_identity',
                'result_ref',
                'started_at',
                'ended_at',
                'last_observed_at',
            )
        )
        for row in steps
    ):
        raise StorageUnavailable('Original stop already has another work owner')
    if task['phase'] != 'PREPARING' or any(
        task[field] is not None for field in ('stopped_at', 'ended_at', 'last_observed_at')
    ):
        return task, operation, None
    return task, operation, _zero_scope(connection, task, operation)


def _evidence_ref(operation_id, evidence):
    digest = hashlib.sha256(canonical_input(evidence).encode('utf-8')).hexdigest()
    return f'sqlite:code_operation_steps/{operation_id}/1#sha256={digest}'


def _save_empty_stop(connection, task, operation, evidence, observed_at):
    operation_id = operation['id']
    cancelled_start = evidence.get('cancelled_start_operation_id')
    if cancelled_start is not None:
        if (
            connection.execute(
                "UPDATE code_operations SET status='CANCELLED',ended_at=? WHERE id=? AND status='PENDING'",
                (observed_at, cancelled_start),
            ).rowcount
            != 1
        ):
            raise StorageUnavailable('Original undispatched START changed')
        cancelled = connection.execute(
            """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
               WHERE operation_id=? AND status='PENDING'""",
            (observed_at, observed_at, cancelled_start),
        )
        if cancelled.rowcount != len(operation_steps('CODING', 'START')):
            raise StorageUnavailable('Original undispatched START steps changed')
    if evidence.get('cancelled_configuration_operation_id') is not None:
        from .task_configuration_progress import interrupt_staged_configuration

        interrupt_staged_configuration(connection, task['id'], observed_at, uncertain=False)
    refs = {}
    evidence_ref = _evidence_ref(operation_id, evidence)
    for kind in ('STOP', 'CLEANUP'):
        observation_id = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
        connection.execute(
            """INSERT INTO code_runtime_observations(
               id,task_id,operation_id,control_generation,kind,result,reason_codes,
               active_process_count,observed_at,evidence_ref)
               VALUES(?,?,?,?,?,'VERIFIED','[]',0,?,?)""",
            (
                observation_id,
                task['id'],
                operation_id,
                task['control_generation'],
                kind,
                observed_at,
                evidence_ref,
            ),
        )
        refs[kind.lower() + '_observation_id'] = observation_id
    for number, kind in enumerate(STOP_STEPS, 1):
        result = (
            evidence if kind == 'BLOCK_NEW' else refs if kind == 'STOP_OWNED_ACTIVITY' else None
        )
        connection.execute(
            """UPDATE code_operation_steps SET status='SUCCEEDED',started_at=?,ended_at=?,
               last_observed_at=?,result_ref=? WHERE operation_id=? AND step_no=?""",
            (
                observed_at,
                observed_at,
                observed_at,
                None if result is None else canonical_input(result),
                operation_id,
                number,
            ),
        )
    connection.execute(
        "UPDATE code_operations SET status='SUCCEEDED',started_at=?,ended_at=? WHERE id=?",
        (observed_at, observed_at, operation_id),
    )
    updated = connection.execute(
        """UPDATE code_tasks SET status='TERMINATED',phase='FINISHED',state_version=?,
           stopped_at=?,ended_at=?,updated_at=?,last_observed_at=? WHERE id=? AND status='STOPPING'
           AND state_version=? AND control_generation=?""",
        (
            task['state_version'] + 1,
            observed_at,
            observed_at,
            observed_at,
            observed_at,
            task['id'],
            task['state_version'],
            task['control_generation'],
        ),
    )
    if updated.rowcount != 1:
        raise StorageUnavailable('Original stop changed before completion')


def advance_pending_stops(runtime):
    # The process lock remains held for both transactions. A restart reopens
    # only committed original intentions, without relying on a wake signal.
    owner = runtime.commands().process_lock
    owner.assert_owned()
    with runtime.database.transaction() as connection:
        row = connection.execute(
            """SELECT id FROM code_operations WHERE resource_kind='TASK'
               AND operation_type='TERMINATE' AND status='PENDING'
               AND NOT EXISTS(SELECT 1 FROM code_instances i WHERE i.task_id=code_operations.task_id)
               ORDER BY id LIMIT 1"""
        ).fetchone()
        if row is None:
            return False
        operation_id = row['id']
        observed = _pending_scope(connection, operation_id)
    if observed is None:
        return False
    with runtime.database.transaction(write=True) as connection:
        owner.assert_owned()
        current = _pending_scope(connection, operation_id)
        if current is None:
            return False
        task, operation, evidence = current
        now = operation_time(None)
        if now < task['updated_at']:
            return False
        if evidence is None or observed[2] != evidence:
            # Any history or changed proof awaits the real runtime recovery path.
            connection.execute(
                """UPDATE code_operations SET status='UNKNOWN',failure_code='EXECUTION_NOT_STOPPED'
                   WHERE id=? AND status='PENDING'""",
                (operation_id,),
            )
        else:
            _save_empty_stop(connection, task, operation, evidence, now)
    return True


async def serve_task_stops(runtime, wake, closing, *, testing_native=None):
    """Drive local stops and original resource seals under the lifespan owner."""
    from backend.app.testing.pack_seal import advance_pending_pack_seals
    from backend.app.testing.pack_validation import advance_pending_validation_results
    from backend.app.testing.task_recovery import advance_pending_reconcile
    from backend.app.testing.task_stop import advance_pending_testing_stop

    while not closing.is_set():
        wake.clear()
        try:
            if await asyncio.to_thread(advance_pending_stops, runtime):
                continue
            if await asyncio.to_thread(advance_pending_testing_stop, runtime):
                continue
            native_available = testing_native is not None and testing_native()
            if await asyncio.to_thread(advance_pending_reconcile, runtime, native_available):
                continue
            if await asyncio.to_thread(advance_pending_validation_results, runtime):
                continue
            if await asyncio.to_thread(advance_pending_pack_seals, runtime, closing.is_set):
                continue
        except (StorageUnavailable, sqlite3.Error):
            # Original rows remain durable; retry storage on the next tick.
            pass
        if not closing.is_set():
            try:
                await asyncio.wait_for(wake.wait(), timeout=1)
            except TimeoutError:
                pass


def _empty_stop_evidence(task, operation, counts, queued_start, configuration=None):
    evidence = {
        'policy': 'CODE20-EMPTY-STOP-1',
        'task_id': task['id'],
        'operation_id': operation['id'],
        'fenced_generation': task['control_generation'],
        'authorization_id': task['authorization_id'],
        'authorization_state': 'BOUND_PENDING_APPLY',
        'checked_prior_operations': 0,
        'owned_records': counts,
    }
    if queued_start is not None:
        evidence.update(
            policy='CODE20-QUEUED-START-STOP-1',
            checked_prior_operations=1,
            cancelled_start_operation_id=queued_start,
        )
    if configuration is not None:
        evidence['policy'] = 'CODE20-PREPARED-CONFIGURATION-STOP-1'
        evidence['checked_prior_operations'] += 1
        evidence['cancelled_configuration_operation_id'] = configuration
    return evidence


def _empty_evidence(connection, task, operation, evidence):
    unstarted, cancelled, configuration = _empty_start_proof(
        connection, task, operation, cancelled_at=operation['ended_at']
    )
    if not unstarted:
        return False
    counts = dict.fromkeys(EXECUTION_TABLES, 0)
    counts['code_configuration_applications'] = int(configuration is not None)
    return evidence == _empty_stop_evidence(task, operation, counts, cancelled, configuration)


def read_stop_progress(connection, task, operation):
    original_stop_result(connection, operation)
    if (
        operation['task_id'] != task['id']
        or operation['control_generation'] != task['control_generation']
        or operation['created_at'] != task['stop_requested_at']
        or task['status'] not in ('STOPPING', 'TERMINATED')
        or (task['status'] == 'TERMINATED') != (operation['status'] == 'SUCCEEDED')
    ):
        raise StorageUnavailable('Original stop and current task differ')
    steps = _stop_steps(connection, operation)
    if is_owned_progress(steps):
        from .task_runtime_stop import read_owned_progress

        return steps, read_owned_progress(connection, task, operation, steps)
    if operation['status'] != 'SUCCEEDED':
        return steps, None
    if (
        operation['started_at'] != operation['ended_at']
        or task['state_version'] != operation['expected_state_version'] + 2
        or operation['ended_at'] != task['stopped_at']
        or task['stopped_at'] != task['ended_at']
        or any(
            step['status'] != 'SUCCEEDED'
            or step['external_identity'] is not None
            or any(
                step[field] != operation['ended_at']
                for field in ('started_at', 'ended_at', 'last_observed_at')
            )
            for step in steps
        )
    ):
        raise StorageUnavailable('Original empty-scope stop chronology differs')
    evidence = strict_json_object(steps[0]['result_ref'])
    if not _empty_evidence(connection, task, operation, evidence):
        raise StorageUnavailable('Original empty-scope fence evidence is invalid')
    results = strict_json_object(steps[3]['result_ref'])
    if set(results) != {'stop_observation_id', 'cleanup_observation_id'}:
        raise StorageUnavailable('Original stop and cleanup observations are required')
    expected_ref = _evidence_ref(operation['id'], evidence)
    for kind in ('STOP', 'CLEANUP'):
        identity = results[kind.lower() + '_observation_id']
        record = connection.execute(
            'SELECT * FROM code_runtime_observations WHERE id=?', (identity,)
        ).fetchone()
        expected = {
            'id': identity,
            'task_id': task['id'],
            'testing_task_id': None,
            'instance_id': None,
            'command_id': None,
            'operation_id': operation['id'],
            'control_generation': operation['control_generation'],
            'runtime_binding_ref': None,
            'kind': kind,
            'result': 'VERIFIED',
            'reason_codes': '[]',
            'active_process_count': 0,
            'observed_at': task['stopped_at'],
            'evidence_ref': expected_ref,
        }
        if type(identity) is not int or record is None or dict(record) != expected:
            raise StorageUnavailable('Original stop observation differs from its empty scope')
    return steps, results


def is_owned_progress(steps):
    if steps[0]['result_ref'] is None:
        return False
    from .task_runtime_stop import POLICY

    return strict_json_object(steps[0]['result_ref']).get('policy') == POLICY


def public_stop_operation(connection, operation):
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    if task is None:
        raise StorageUnavailable('Original stop task is missing')
    steps, results = read_stop_progress(connection, task, operation)
    fixed = strict_json_object(operation['fixed_input'])
    public = {key: fixed[key] for key in ('task_id', 'expected_state_version')}
    return {
        **dict(operation),
        'fixed_input': public,
        'steps': [
            {
                **dict(step),
                'fixed_input': public,
                'external_identity': None if step['external_identity'] is None else {},
                'result_ref': (
                    results
                    if operation['status'] == 'SUCCEEDED'
                    and step['step_type'] == 'STOP_OWNED_ACTIVITY'
                    else None
                ),
            }
            for step in steps
        ],
        'content_capture': None,
    }


def project_stop_operation(data, operation_id):
    from backend.app.shared.http_projection import exact
    from backend.app.shared.validation import strict_integer

    from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time

    row = exact(data, OPERATION_FIELDS)
    task = strict_integer(row['task_id'], 'task_id')
    if (
        strict_integer(row['id'], 'operation_id') != operation_id
        or row['operation_type'] != 'TERMINATE'
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != task
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or row['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN', 'SUCCEEDED')
        or row['failure_code'] != ('EXECUTION_NOT_STOPPED' if row['status'] == 'UNKNOWN' else None)
    ):
        raise ValueError('Original stop operation projection differs')
    registered_command('POST', STOP_PATH.format(task_id=task), row['idempotency_key'])
    if row['session_id'] is not None:
        strict_integer(row['session_id'], 'session_id')
    strict_integer(row['control_generation'], 'control_generation')
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    if row['fixed_input'] != {'task_id': task, 'expected_state_version': version}:
        raise ValueError('Original stop projection input differs')
    _time(row['created_at'], nullable=False)
    completed = row['status'] == 'SUCCEEDED'
    began, ended = row['started_at'], row['ended_at']
    _time(began, nullable=True)
    _time(ended, nullable=not completed)
    if (
        (completed != (ended is not None))
        or (completed and began is None)
        or (row['status'] == 'RUNNING' and began is None)
        or (row['status'] == 'PENDING' and began is not None)
        or (began is not None and began < row['created_at'])
        or (ended is not None and ended < began)
    ):
        raise ValueError('Original stop projection time differs')
    if type(row['steps']) is not list or len(row['steps']) != len(STOP_STEPS):
        raise ValueError('Original stop projection step list differs')
    previous_end = began
    for number, step in enumerate(row['steps'], 1):
        exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != operation_id
            or step['step_no'] != number
            or step['step_type'] != STOP_STEPS[number - 1]
            or step['fixed_input'] != row['fixed_input']
            or step['external_identity'] is not None
            or step['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN', 'SUCCEEDED')
            or (completed and step['status'] != 'SUCCEEDED')
        ):
            raise ValueError('Original stop projection step differs')
        times = tuple(step[key] for key in ('started_at', 'last_observed_at', 'ended_at'))
        for instant in times:
            _time(instant, nullable=True)
        if step['status'] == 'PENDING':
            valid = times == (None, None, None)
        elif step['status'] == 'SUCCEEDED':
            valid = (
                previous_end is not None
                and all(instant is not None for instant in times)
                and previous_end <= times[0] <= times[2] <= times[1]
                and (ended is None or times[1] <= ended)
            )
        else:
            valid = (
                previous_end is not None
                and times[0] is not None
                and times[1] is not None
                and previous_end <= times[0] <= times[1]
                and times[2] is None
            )
        if not valid:
            raise ValueError('Original stop projection step chronology differs')
        previous_end = times[2]
        if completed and step['step_type'] == 'STOP_OWNED_ACTIVITY':
            refs = exact(step['result_ref'], ('stop_observation_id', 'cleanup_observation_id'))
            for key, value in refs.items():
                strict_integer(value, key)
            if refs['stop_observation_id'] == refs['cleanup_observation_id']:
                raise ValueError('Original stop and cleanup identities must be distinct')
        elif step['result_ref'] is not None:
            raise ValueError('Private stop proof must not appear in projection')
    return row
