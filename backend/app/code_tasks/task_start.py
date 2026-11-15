"""Original Coding START intake and immutable receipt verification."""

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import CapacityExhausted, EntityKind, entity_id
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .authorization_scope import profile_scope_error, resource_scope_error
from .authorizations import project_grant
from .command_registry import registered_command, validate_registered_success
from .configuration_identities import require_schema
from .costs import format_money, parse_money
from .execution_profile_versions import _project as project_profile
from .operation_protocol import operation_steps
from .task_configuration_progress import pending_configuration
from .task_stop import EXECUTION_TABLES

START_CAPABILITY = 'APP-CODE-CMD-C35'
START_PATH = '/api/v1/code-tasks/{task_id}/start'
START_STEPS = operation_steps('CODING', 'START')


def start_conflict(code, task, operation_id=None):
    return Rejection(
        code,
        {
            **empty_conflict(),
            'task_id': task['id'],
            'current_state_version': task['state_version'],
            'related_operation_id': operation_id,
        },
    )


def _check_start_readiness(connection, catalog, task, workspace_available):
    profile_row = connection.execute(
        'SELECT * FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    grant_row = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?', (task['authorization_id'],)
    ).fetchone()
    if profile_row is None or grant_row is None:
        raise StorageUnavailable('Fixed START configuration is missing')
    grant = project_grant(grant_row)
    if (
        grant['task_id'] != task['id']
        or grant['profile_version_id'] != profile_row['id']
        or grant['status'] not in ('BOUND_PENDING_APPLY', 'EFFECTIVE')
    ):
        raise ConfigurationNotReady('Q20-CONFIG')
    try:
        snapshots = {}
        profile = project_profile(profile_row, connection, catalog, snapshots)
        if profile_scope_error(grant['scope'], profile) or resource_scope_error(
            grant['scope'], snapshots['execution']
        ):
            raise ConfigurationNotReady('Q20-CONFIG')
    except ConfigInvalid as error:
        raise ConfigurationNotReady('Q20-CONFIG') from error
    codes = set(profile['unresolved_capability_codes'])
    if not workspace_available:
        codes.add('Q20-WINDOWS')
    if not profile['ready'] and not codes:
        codes.add('Q20-CONFIG')
    if codes:
        raise ConfigurationNotReady(*sorted(codes))


def _new_start(connection, task, request):
    version = task['state_version']
    if version >= MAX_SAFE_INTEGER - 2:
        return start_conflict('PRECONDITION_FAILED', task)
    try:
        operation_id = entity_id(connection, EntityKind.OPERATION_RECORD)
    except CapacityExhausted:
        return start_conflict('PRECONDITION_FAILED', task)
    now = operation_time(None)
    if now < task['updated_at']:
        raise StorageUnavailable('START clock is behind the task')
    if (
        connection.execute(
            """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
           AND control_generation=? AND stop_requested_at IS NULL AND status='PENDING'""",
            (version + 1, now, task['id'], version, task['control_generation']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Task changed inside the START transaction')
    fixed = canonical_input(request.business_input())
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,'START',?,?,?,?,'PENDING',?)""",
        (
            operation_id,
            task['id'],
            task['id'],
            request.idempotency_key,
            version,
            fixed,
            task['control_generation'],
            now,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [(operation_id, number, step, fixed) for number, step in enumerate(START_STEPS, 1)],
    )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': operation_id,
                'operation_status': 'PENDING',
                'task_status': 'PENDING',
                'state_version': version + 1,
            },
            'details': None,
        },
        202,
    )


def accept_task_start(runtime, request, *, workspace_available):
    require_schema(runtime)

    def accept(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return Rejection('NOT_FOUND', None)
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return start_conflict('TASK_ENDED', task)
        if task['state_version'] != request.expected_state_version:
            return start_conflict('VERSION_CONFLICT', task)
        if (
            task['status'] != 'PENDING'
            or task['phase'] != 'PREPARING'
            or task['stop_requested_at'] is not None
        ):
            return start_conflict('INVALID_STATE', task)
        configuration = pending_configuration(connection, task)
        configuration_id = None if configuration is None else configuration['id']
        previous = connection.execute(
            """SELECT id,status,operation_type FROM code_operations WHERE task_id=?
               AND id IS NOT ? AND (operation_type='START' OR status IN ('PENDING','RUNNING','UNKNOWN'))
               ORDER BY (status='UNKNOWN') DESC,id DESC LIMIT 1""",
            (task['id'], configuration_id),
        ).fetchone()
        if previous is not None:
            code = {
                'PENDING': 'OPERATION_IN_PROGRESS',
                'RUNNING': 'OPERATION_IN_PROGRESS',
                'UNKNOWN': 'EXTERNAL_RESULT_UNKNOWN',
            }.get(previous['status'], 'OPERATION_CONFLICT')
            return start_conflict(code, task, previous['id'])
        if (
            task['workspace_id'] is not None
            or task['active_session_id'] is not None
            or task['started_at'] is not None
        ):
            return start_conflict('EXECUTION_NOT_STOPPED', task)
        for table in EXECUTION_TABLES:
            if table == 'code_configuration_applications' and configuration is not None:
                continue
            if connection.execute(
                f'SELECT 1 FROM {table} WHERE task_id=? LIMIT 1', (task['id'],)
            ).fetchone():
                return start_conflict('EXECUTION_NOT_STOPPED', task)
        budget = parse_money(task['budget_limit_cny'], 'budget_limit_cny')
        if budget <= 0 or format_money(budget) != task['budget_limit_cny']:
            raise StorageUnavailable('Invalid stored START budget')
        _check_start_readiness(connection, runtime.catalog, task, workspace_available)
        return _new_start(connection, task, request)

    return execute_idempotent(
        runtime.commands(),
        START_CAPABILITY,
        request,
        accept,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def original_start_steps(connection, operation):
    """Verify the original committed acceptance before advancing any allocation."""
    task_id = operation['task_id']
    version = operation['expected_state_version']
    if (
        operation['operation_type'] != 'START'
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != task_id
        or operation['testing_task_id'] is not None
    ):
        raise StorageUnavailable('Original START operation owner differs')
    command = registered_command(
        'POST', START_PATH.format(task_id=task_id), operation['idempotency_key']
    )
    receipt = connection.execute(
        """SELECT status,business_input_json,success_result_json,http_status FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    fixed = {'task_id': task_id, 'expected_state_version': version}
    encoded = canonical_input(fixed)
    if (
        receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['business_input_json'] != encoded
        or operation['fixed_input'] != encoded
    ):
        raise StorageUnavailable('Original START acceptance is missing')
    saved = strict_json_object(receipt['success_result_json'])
    Success(saved, receipt['http_status']).encoded()
    data = saved['data']
    validate_registered_success(command, data, saved['code'], receipt['http_status'])
    if data['operation_id'] != operation['id'] or data['state_version'] != version + 1:
        raise StorageUnavailable('Original START receipt differs')
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(START_STEPS) or any(
        step['step_no'] != number or step['step_type'] != kind or step['fixed_input'] != encoded
        for number, (step, kind) in enumerate(zip(steps, START_STEPS), 1)
    ):
        raise StorageUnavailable('Original START steps differ')
    return fixed, steps
