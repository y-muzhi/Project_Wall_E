"""Explicit observation and guarded continuation of one original Testing operation."""

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .assets import NOT_FOUND
from .run_ownership import read_original_run
from .run_records import accepted_run
from .tasks import grant_rejection, read_task_row, task_conflict

RESUME_PATH = '/testing-tasks/{testing_task_id}/resume'
RECONCILE_PATH = '/testing-tasks/{testing_task_id}/reconcile'
RECOVERY_TYPES = ('RESUME', 'RECONCILE')
_FINAL = ('SUCCEEDED', 'FAILED', 'CANCELLED')


def owned_operation(connection, task, operation):
    return connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND testing_task_id=? AND task_id IS NULL
           AND resource_kind='TESTING_TASK' AND resource_id=testing_task_id""",
        (operation, task),
    ).fetchone()


def _resume_problem(connection, task, original):
    if task['status'] in ('COMPLETED', 'TERMINATED'):
        return task_conflict('TASK_ENDED', task)
    if (
        task['status'] != 'WAITING'
        or task['active_operation_id'] != original['id']
        or task['stop_requested_at'] is not None
        or task['state_version'] >= MAX_SAFE_INTEGER - 1
        or original['status'] in _FINAL
        or original['control_generation'] != task['control_generation']
        or original['operation_type'] != 'RUN_TEST'
        or 'facts' not in strict_json_object(original['fixed_input'])
    ):
        return task_conflict('INVALID_STATE', task)
    run = read_original_run(connection, original['id'])
    if run is None:
        raise StorageUnavailable('Original Testing continuation is missing')
    plan = connection.execute(
        'SELECT status FROM testing_plan_versions WHERE id=?', (task['plan_version_id'],)
    ).fetchone()
    if plan is None:
        raise StorageUnavailable('Original Testing continuation plan is missing')
    if plan['status'] == 'REVOKED' or run.pack['status'] == 'REVOKED':
        return task_conflict('TEST_ASSET_REVOKED', task)
    if task['authorization_id'] != run.facts['authorization_id']:
        return grant_rejection(task['authorization_id'])
    if (
        connection.execute(
            """SELECT 1 FROM testing_authorizations WHERE id=? AND status='EFFECTIVE'
           AND profile_version_id=? AND ((scope_kind='TASK' AND testing_task_id=?)
           OR (scope_kind='PACK_VALIDATION' AND validation_id=?))""",
            (
                task['authorization_id'],
                task['profile_version_id'],
                task['id'],
                task['validation_id'],
            ),
        ).fetchone()
        is None
    ):
        return grant_rejection(task['authorization_id'])
    open_waits = connection.execute(
        "SELECT 1 FROM code_waiting_items WHERE testing_task_id=? AND status='OPEN'",
        (task['id'],),
    ).fetchone()
    if (
        open_waits is not None
        or not any(case.command['status'] == 'PENDING' for case in run.cases)
        or any(
            case.command['status'] != 'PENDING'
            and (
                case.command['ended_at'] is None
                or connection.execute(
                    'SELECT 1 FROM code_verification_case_results WHERE item_id=? AND case_id=?',
                    (case.item['id'], case.case_id),
                ).fetchone()
                is None
            )
            for case in run.cases
        )
    ):
        return task_conflict('OPERATION_IN_PROGRESS', task)
    return None


def resume_available(connection, task, runtime_resources):
    if (
        runtime_resources is None
        or task['status'] != 'WAITING'
        or task['active_operation_id'] is None
    ):
        return False
    original = owned_operation(connection, task['id'], task['active_operation_id'])
    return original is not None and _resume_problem(connection, task, original) is None


def _accept(connection, request, action, *, runtime_resources):
    task = read_task_row(connection, request.identity)
    if task is None:
        return NOT_FOUND
    original = owned_operation(connection, task['id'], request.original_operation)
    if original is None:
        return NOT_FOUND
    if task['state_version'] != request.expected:
        return task_conflict('VERSION_CONFLICT', task)
    if original['operation_type'] in RECOVERY_TYPES and original['status'] not in _FINAL:
        return task_conflict('OPERATION_IN_PROGRESS', task)
    if action == 'RESUME':
        problem = _resume_problem(connection, task, original)
        if problem is not None:
            return problem
        if runtime_resources is None:
            raise ConfigurationNotReady('Q20-CHECKS')
    if (
        connection.execute(
            """SELECT 1 FROM code_operations WHERE testing_task_id=? AND task_id IS NULL
           AND operation_type=? AND status='PENDING'
           AND json_extract(fixed_input,'$.operation_id')=?""",
            (task['id'], action, original['id']),
        ).fetchone()
        is not None
    ):
        return task_conflict('OPERATION_IN_PROGRESS', task)
    at = max(operation_time(None), task['created_at'])
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input(request.business_input())
    connection.execute(
        """INSERT INTO code_operations(id,testing_task_id,resource_kind,resource_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TESTING_TASK',?,?,?,?,?,?,'PENDING',?)""",
        (
            operation,
            task['id'],
            task['id'],
            action,
            request.idempotency_key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [
            (operation, number, step, fixed)
            for number, step in enumerate(operation_steps('TESTING', action), 1)
        ],
    )
    return accepted_run(task['id'], operation, task['state_version'])


def accept_recovery(runtime, request, action, *, runtime_resources=None):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _accept(
            connection, request, action, runtime_resources=runtime_resources
        ),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def next_recovery(connection, action):
    return connection.execute(
        """SELECT * FROM code_operations WHERE operation_type=? AND resource_kind='TESTING_TASK'
           AND testing_task_id=resource_id AND task_id IS NULL AND status='PENDING'
           ORDER BY id LIMIT 1""",
        (action,),
    ).fetchone()


def recovery_source(connection, operation):
    fixed = strict_json_object(operation['fixed_input'])
    original = owned_operation(connection, operation['testing_task_id'], fixed['operation_id'])
    if original is None or original['id'] == operation['id']:
        raise StorageUnavailable('Original Testing recovery source differs')
    return original


def _settle(connection, operation, original, *, failure=None):
    at = max(operation_time(None), operation['created_at'])
    source = canonical_input(
        {'operation_id': original['id'], 'observed_status': original['status']}
    )
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if [row['step_type'] for row in steps] != list(
        operation_steps('TESTING', operation['operation_type'])
    ) or any(
        row['status'] != 'PENDING' or row['fixed_input'] != operation['fixed_input']
        for row in steps
    ):
        raise StorageUnavailable('Original Testing recovery steps differ')
    for step in steps:
        status = 'FAILED' if failure and step['step_no'] == len(steps) else 'SUCCEEDED'
        connection.execute(
            """UPDATE code_operation_steps SET status=?,result_ref=?,started_at=?,ended_at=?,last_observed_at=?
               WHERE operation_id=? AND step_no=? AND status='PENDING'""",
            (status, source, at, at, at, operation['id'], step['step_no']),
        )
    connection.execute(
        """UPDATE code_operations SET status=?,failure_code=?,started_at=?,ended_at=?
           WHERE id=? AND status='PENDING'""",
        ('FAILED' if failure else 'SUCCEEDED', failure, at, at, operation['id']),
    )


def native_reconcile_source(connection, operation):
    original = recovery_source(connection, operation)
    if original['operation_type'] != 'RUN_TEST' or original['status'] in _FINAL:
        return None
    run = read_original_run(connection, original['id'])
    if run is None:
        return None
    return next(
        (
            case
            for case in run.cases
            if case.command['status'] in ('RUNNING', 'UNKNOWN') and case.command['ended_at'] is None
        ),
        None,
    )


def finish_pending_reconcile(connection, operation_id):
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND testing_task_id=resource_id
           AND task_id IS NULL AND operation_type='RECONCILE' AND status='PENDING'""",
        (operation_id,),
    ).fetchone()
    if operation is None:
        return False
    original = recovery_source(connection, operation)
    _settle(connection, operation, original)
    return True


def advance_pending_reconcile(runtime, native_available=False):
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        operation = next_recovery(connection, 'RECONCILE')
        if operation is None:
            return False
        if native_available and native_reconcile_source(connection, operation) is not None:
            return False
        return finish_pending_reconcile(connection, operation['id'])


def finish_pending_resume(connection, operation_id, *, proven):
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND testing_task_id IS NOT NULL
           AND task_id IS NULL AND operation_type='RESUME' AND status='PENDING'""",
        (operation_id,),
    ).fetchone()
    if operation is None:
        return False
    original = recovery_source(connection, operation)
    task = read_task_row(connection, operation['testing_task_id'])
    if task is None:
        raise StorageUnavailable('Original Testing recovery owner is missing')
    problem = _resume_problem(connection, task, original)
    failure = (
        'VERSION_CONFLICT'
        if task['state_version'] != operation['expected_state_version']
        else problem.result['code']
        if problem is not None
        else None
        if proven
        else 'CONFIG_NOT_READY'
    )
    if failure is None:
        changed = connection.execute(
            """UPDATE testing_tasks SET status='RUNNING',state_version=?
               WHERE id=? AND status='WAITING' AND active_operation_id=? AND state_version=?
               AND control_generation=? AND stop_requested_at IS NULL""",
            (
                increment(task['state_version']),
                task['id'],
                original['id'],
                task['state_version'],
                operation['control_generation'],
            ),
        )
        if changed.rowcount != 1:
            raise StorageUnavailable('Original Testing resume fence changed')
        connection.execute(
            """UPDATE code_operations SET status='RUNNING',failure_code=NULL
               WHERE id=? AND status IN ('RUNNING','UNKNOWN') AND ended_at IS NULL""",
            (original['id'],),
        )
        connection.execute(
            """UPDATE code_operation_steps SET status='RUNNING'
               WHERE operation_id=? AND step_type='EXECUTE' AND status='UNKNOWN' AND ended_at IS NULL""",
            (original['id'],),
        )
    _settle(connection, operation, original, failure=failure)
    return True
