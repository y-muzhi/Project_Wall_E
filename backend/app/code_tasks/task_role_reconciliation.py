"""Explicit read-only reconciliation of the original Coding role delivery."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .repository_reads import ERRORS
from .task_role_handoff import (
    _finish_delivery,
    original_role_result_for_reconciliation,
    record_reconciled_role_creation,
)
from .task_start import start_conflict

PATH = '/api/v1/code-tasks/{task_id}/reconcile'
CAPABILITY = 'APP-CODE-CMD-C38'
TYPE = 'RECONCILE'
STEPS = operation_steps('CODING', TYPE)
ACTIVE = ('PENDING', 'RUNNING', 'UNKNOWN')
reconciliation_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class ReconciliationRequest:
    task_id: int
    expected_state_version: int
    operation_id: int
    command: RegisteredCommand
    ready: bool
    delivery_ready: bool = False
    body_fields = ('expected_state_version', 'operation_id')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {field: getattr(self, field) for field in self.body_fields}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fixed = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        worker = getattr(request.app.state, 'walle_repository_registration', None)
        return cls(
            task,
            *(strict_integer(fixed[field], field) for field in cls.body_fields),
            registered_command(
                'POST', PATH.format(task_id=task), idempotency_header(request, lowercase=True)
            ),
            bool(worker is not None and getattr(worker, 'accepts_native_responses', False)),
            bool(worker is not None and getattr(worker, 'delivery_writes_ready', False)),
        )


def active_role_reconciliation(connection, task_id):
    rows = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type=?
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id LIMIT 2""",
        (task_id, TYPE),
    ).fetchall()
    if len(rows) > 1:
        raise StorageUnavailable('Original role observation is not unique')
    return rows[0] if rows else None


def accept_reconciliation(runtime, request):
    require_schema(runtime)

    def save(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        original = connection.execute(
            "SELECT * FROM code_operations WHERE id=? AND task_id=? AND resource_kind='TASK'",
            (request.operation_id, request.task_id),
        ).fetchone()
        if task is None or original is None:
            return Rejection('NOT_FOUND')
        if task['state_version'] != request.expected_state_version:
            return start_conflict('VERSION_CONFLICT', task)
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return start_conflict('TASK_ENDED', task)
        if task['stop_requested_at'] is not None:
            return start_conflict('OPERATION_CONFLICT', task)
        if original['operation_type'] == 'DELIVER':
            if not delivery_reconcile_source(connection, task, original):
                return start_conflict('INVALID_STATE', task, original['id'])
            if not request.delivery_ready:
                raise ConfigurationNotReady('RUNTIME')
            session = original['session_id']
        elif original['operation_type'] == 'HANDOFF_ROLE':
            try:
                scope, _, _ = original_role_result_for_reconciliation(
                    connection, request.operation_id
                )
            except TaskExecutionError:
                return start_conflict('INVALID_STATE', task, original['id'])
            if not request.ready:
                raise ConfigurationNotReady('RUNTIME')
            session = scope.source['id']
        elif original['operation_type'] == 'REPAIR':
            from .task_repair_runtime import (
                repair_creation_for_reconciliation,
                repair_message_for_reconciliation,
            )

            if (
                repair_message_for_reconciliation(connection, task, original['id']) is None
                and repair_creation_for_reconciliation(connection, task, original['id']) is None
            ):
                return start_conflict('INVALID_STATE', task, original['id'])
            if not request.ready:
                raise ConfigurationNotReady('RUNTIME')
            from .task_session_replacement import repair_execution

            session, _ = repair_execution(connection, original)
        else:
            raise ConfigurationNotReady('RUNTIME')
        existing = active_role_reconciliation(connection, task['id'])
        if existing is not None:
            return start_conflict('OPERATION_CONFLICT', task, existing['id'])
        identity = entity_id(connection, EntityKind.OPERATION_RECORD)
        at = max(operation_time(None), task['updated_at'])
        version = increment(task['state_version'])
        fixed = canonical_input(request.business_input())
        changed = connection.execute(
            """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
               AND status='WAITING' AND stop_requested_at IS NULL""",
            (version, at, task['id'], task['state_version']),
        )
        if changed.rowcount != 1:
            raise StorageUnavailable('Original role reconciliation acceptance was fenced')
        connection.execute(
            """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,
               operation_type,idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
               VALUES(?,?,'TASK',?,?,?,?,?,?,?,'PENDING',?)""",
            (
                identity,
                task['id'],
                task['id'],
                session,
                TYPE,
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
            [(identity, number, kind, fixed) for number, kind in enumerate(STEPS, 1)],
        )
        return Success(
            {
                'code': 'OPERATION_ACCEPTED',
                'details': None,
                'data': {
                    'task_id': task['id'],
                    'operation_id': identity,
                    'operation_status': 'PENDING',
                    'task_status': 'WAITING',
                    'state_version': version,
                },
            },
            202,
        )

    return execute_idempotent(
        runtime.commands(),
        CAPABILITY,
        request,
        save,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
        target_identity=request.command.scope.target_identity,
    )


def delivery_reconcile_source(connection, task, original):
    from .task_delivery_write import load_original_delivery

    if (
        task['status'] != 'WAITING'
        or task['phase'] != 'DELIVERY'
        or task['stop_requested_at'] is not None
        or original['operation_type'] != 'DELIVER'
        or original['status'] not in ('RUNNING', 'UNKNOWN')
    ):
        return False
    state = load_original_delivery(connection, original['id'])
    return state.delivery['id'] == task['current_delivery_id'] and state.delivery[
        'git_write_status'
    ] in ('MAY_HAVE_BEEN_SENT', 'UNKNOWN', 'CONFIRMED')


def next_delivery_reconciliation(connection):
    return connection.execute(
        """SELECT o.id,json_extract(o.fixed_input,'$.operation_id') AS original_id
           FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
           JOIN code_operations source ON source.id=json_extract(o.fixed_input,'$.operation_id')
             AND source.task_id=o.task_id AND source.operation_type='DELIVER'
           WHERE o.operation_type='RECONCILE' AND o.status='PENDING'
             AND t.status='WAITING' AND t.phase='DELIVERY' AND t.stop_requested_at IS NULL
           ORDER BY o.id LIMIT 1"""
    ).fetchone()


def finish_delivery_reconciliation(connection, identity, original_id):
    row = connection.execute(
        """SELECT r.*,o.status AS original_status,t.stop_requested_at,t.control_generation AS current_generation
           FROM code_operations r JOIN code_operations o ON o.id=? AND o.task_id=r.task_id
           JOIN code_tasks t ON t.id=r.task_id
           WHERE r.id=? AND r.operation_type='RECONCILE' AND r.status='PENDING'
             AND o.operation_type='DELIVER'""",
        (original_id, identity),
    ).fetchone()
    if row is None or row['stop_requested_at'] is not None:
        return False
    if (
        _fixed(strict_json_object(row['fixed_input']))['operation_id'] != original_id
        or row['control_generation'] != row['current_generation']
    ):
        raise StorageUnavailable('Original delivery reconciliation was fenced')
    at = max(operation_time(None), row['created_at'])
    result = canonical_input(
        {
            'operation_id': original_id,
            'original_status': 'SUCCEEDED' if row['original_status'] == 'SUCCEEDED' else 'UNKNOWN',
        }
    )
    connection.execute(
        "UPDATE code_operations SET status='SUCCEEDED',started_at=?,ended_at=? WHERE id=?",
        (at, at, identity),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,started_at=?,ended_at=?,last_observed_at=?
           WHERE operation_id=? AND status='PENDING'""",
        (result, at, at, at, identity),
    )
    return True


def _fixed(value):
    fixed = exact(value, ReconciliationRequest.body_fields)
    for field in ReconciliationRequest.body_fields:
        strict_integer(fixed[field], field)
    return fixed


def _accepted_reconciliation(connection, identity):
    operation = connection.execute(
        "SELECT * FROM code_operations WHERE id=? AND operation_type=? AND status='PENDING'",
        (identity, TYPE),
    ).fetchone()
    if operation is None:
        raise TaskExecutionError('ORIGINAL_RECONCILIATION_FENCED')
    fixed = _fixed(strict_json_object(operation['fixed_input']))
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no', (identity,)
    ).fetchall()
    if (
        operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != operation['task_id']
        or operation['expected_state_version'] != fixed['expected_state_version']
        or tuple((row['step_no'], row['step_type']) for row in steps) != tuple(enumerate(STEPS, 1))
        or any(
            row['status'] != 'PENDING'
            or row['fixed_input'] != operation['fixed_input']
            or row['external_identity'] is not None
            or row['result_ref'] is not None
            for row in steps
        )
    ):
        raise StorageUnavailable('Original reconciliation identity differs')
    return dict(operation), fixed


def _require_source(operation, task, session_id):
    if (
        task is None
        or task['id'] != operation['task_id']
        or task['status'] != 'WAITING'
        or task['stop_requested_at'] is not None
        or operation['session_id'] != session_id
        or operation['control_generation'] != task['control_generation']
        or task['state_version'] <= operation['expected_state_version']
    ):
        raise TaskExecutionError('ORIGINAL_RECONCILIATION_SOURCE_FENCED')


def _current(connection, identity):
    operation, fixed = _accepted_reconciliation(connection, identity)
    scope, owner, original = original_role_result_for_reconciliation(
        connection, fixed['operation_id']
    )
    _require_source(operation, scope.task, scope.source['id'])
    return operation, scope, owner, original


def _current_repair(connection, identity):
    from .task_repair_runtime import repair_message_for_reconciliation

    operation, fixed = _accepted_reconciliation(connection, identity)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    if task is None:
        raise TaskExecutionError('ORIGINAL_REPAIR_RECONCILIATION_FENCED')
    source = repair_message_for_reconciliation(connection, task, fixed['operation_id'])
    if source is None:
        raise TaskExecutionError('ORIGINAL_REPAIR_RECONCILIATION_FENCED')
    _require_source(operation, task, source[1].scope.session_id)
    return operation, source


def _current_repair_creation(connection, identity):
    from .task_repair_runtime import repair_creation_for_reconciliation

    operation, fixed = _accepted_reconciliation(connection, identity)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    source = (
        None
        if task is None
        else repair_creation_for_reconciliation(connection, task, fixed['operation_id'])
    )
    if source is None:
        raise TaskExecutionError('ORIGINAL_REPAIR_CREATION_RECONCILIATION_FENCED')
    _require_source(operation, task, source[1].session_id)
    return operation, source


def _observe_repair_creation(runtime, driver, identity, cancelled):
    from .task_repair_runtime import record_reconciled_repair_creation

    with runtime.database.transaction() as connection:
        operation, source = _current_repair_creation(connection, identity)

    def checkpoint():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_REPAIR_CREATION_RECONCILIATION_CANCELLED')
        with runtime.database.transaction() as connection:
            if _current_repair_creation(connection, identity) != (operation, source):
                raise TaskExecutionError('ORIGINAL_REPAIR_CREATION_RECONCILIATION_FENCED')

    try:
        native = driver.observe_created_session(source[1], checkpoint)
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError):
        native = None
    if cancelled():
        return False
    with runtime.database.transaction(write=True) as connection:
        if _current_repair_creation(connection, identity) != (operation, source):
            raise TaskExecutionError('ORIGINAL_REPAIR_CREATION_RECONCILIATION_FENCED')
        at = max(operation_time(None), operation['created_at'], source[0][0]['updated_at'])
        if native is not None:
            record_reconciled_repair_creation(connection, source, native, at)
        _finish_native_observation(
            connection,
            operation,
            source[0][1]['id'],
            'RUNNING' if native is not None else 'UNKNOWN',
            at,
        )
    return True


def _finish_native_observation(connection, operation, original_id, original_status, at):
    identity = operation['id']
    result = canonical_input({'operation_id': original_id, 'original_status': original_status})
    connection.execute(
        "UPDATE code_operations SET status='SUCCEEDED',started_at=?,ended_at=? WHERE id=? AND status='PENDING'",
        (at, at, identity),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,started_at=?,ended_at=?,last_observed_at=?
           WHERE operation_id=? AND status='PENDING'""",
        (result, at, at, at, identity),
    )


def _observe_repair(runtime, driver, identity, *, cancelled):
    from .task_repair_runtime import record_reconciled_repair_message

    with runtime.database.transaction() as connection:
        operation, source = _current_repair(connection, identity)
    _, owner, window, payload = source

    def checkpoint():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_REPAIR_RECONCILIATION_CANCELLED')
        with runtime.database.transaction() as connection:
            if _current_repair(connection, identity) != (operation, source):
                raise TaskExecutionError('ORIGINAL_REPAIR_RECONCILIATION_FENCED')

    try:
        observed = driver.observe_continuation(
            owner.scope, window, owner.credential_ref, payload, checkpoint
        )
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError):
        observed = None
    if cancelled():
        return False
    with runtime.database.transaction(write=True) as connection:
        if _current_repair(connection, identity) != (operation, source):
            raise TaskExecutionError('ORIGINAL_REPAIR_RECONCILIATION_FENCED')
        at = max(operation_time(None), operation['created_at'], source[0][0]['updated_at'])
        verified = observed is not None and observed == window.trigger_message_id
        if verified:
            record_reconciled_repair_message(connection, source, at)
        _finish_native_observation(
            connection, operation, window.operation_id, 'RUNNING' if verified else 'UNKNOWN', at
        )
    return True


def advance_role_reconciliation(runtime, driver, *, cancelled):
    if cancelled():
        return False
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction() as connection:
        row = connection.execute(
            """SELECT o.id,source.operation_type AS source_type
               FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
               JOIN code_operations source ON source.id=json_extract(o.fixed_input,'$.operation_id')
                AND source.task_id=o.task_id AND source.operation_type IN ('HANDOFF_ROLE','REPAIR')
               WHERE o.operation_type=? AND o.status='PENDING' AND t.status='WAITING'
               AND t.stop_requested_at IS NULL ORDER BY o.id LIMIT 1""",
            (TYPE,),
        ).fetchone()
        if row is None:
            return False
        identity, source_type = row['id'], row['source_type']
        if source_type == 'HANDOFF_ROLE':
            operation, scope, owner, original = _current(connection, identity)
    if source_type == 'REPAIR':
        with runtime.database.transaction() as connection:
            _, fixed = _accepted_reconciliation(connection, identity)
            from .task_repair_runtime import repair_creation_for_reconciliation

            task = connection.execute(
                'SELECT t.* FROM code_tasks t JOIN code_operations o ON o.task_id=t.id WHERE o.id=?',
                (identity,),
            ).fetchone()
            creating = (
                task is not None
                and repair_creation_for_reconciliation(connection, task, fixed['operation_id'])
                is not None
            )
        if creating:
            return _observe_repair_creation(runtime, driver, identity, cancelled)
        return _observe_repair(runtime, driver, identity, cancelled=cancelled)

    def checkpoint():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_ROLE_RECONCILIATION_CANCELLED')
        with runtime.database.transaction() as connection:
            current = _current(connection, identity)
            if (
                current[0] != operation
                or current[1].id != scope.id
                or current[2:] != (owner, original)
            ):
                raise TaskExecutionError('ORIGINAL_ROLE_RECONCILIATION_FENCED')

    creating = scope.step['step_type'] == 'CREATE_SESSION'
    try:
        message = (
            driver.observe_created_session(owner, checkpoint)
            if creating
            else driver.observe_successor_message(owner, original, checkpoint)
        )
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError):
        message = None
    if cancelled():
        return False
    with runtime.database.transaction(write=True) as connection:
        current, scope, _, still_original = _current(connection, identity)
        if current != operation or still_original != original:
            raise TaskExecutionError('ORIGINAL_ROLE_RECONCILIATION_FENCED')
        verified = message is not None and (creating or message == original['native_message_id'])
        if verified:
            if creating:
                record_reconciled_role_creation(connection, scope, message)
            else:
                _finish_delivery(connection, scope, message, reconcile=True)
        at = max(operation_time(None), operation['created_at'])
        _finish_native_observation(
            connection,
            operation,
            scope.id,
            ('RUNNING' if creating else 'SUCCEEDED') if verified else 'UNKNOWN',
            at,
        )
    return True


def validate_reconciliation_receipt(command, value, status):
    data = exact(
        value, ('task_id', 'operation_id', 'operation_status', 'task_status', 'state_version')
    )
    for field in ('task_id', 'operation_id', 'state_version'):
        strict_integer(data[field], field)
    if (
        status != 202
        or data['operation_status'] != 'PENDING'
        or data['task_status'] != 'WAITING'
        or data['task_id'] != command.route.match(command.path)['task_id']
    ):
        raise ValueError('Original role reconciliation receipt differs')
    return data['task_id']


class ReconciliationResponse:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    errors = ERRORS | {
        'INVALID_STATE',
        'TASK_ENDED',
        'VERSION_CONFLICT',
        'OPERATION_CONFLICT',
        'OPERATION_IN_PROGRESS',
        'EXTERNAL_RESULT_UNKNOWN',
        'EXECUTION_NOT_STOPPED',
        'COMMAND_CLOSED',
    }

    @staticmethod
    def project(data, request):
        validate_reconciliation_receipt(request.command, data, 202)
        if data['state_version'] != increment(request.expected_state_version):
            raise ValueError('Original role reconciliation version differs')
        return data, None

    @staticmethod
    def status_for(_):
        return 202


@reconciliation_router.post(PATH)
async def reconciliation_http(request: Request):
    result = await handle_http(
        request, ReconciliationRequest, ReconciliationResponse, accept_reconciliation
    )
    if result.status_code == 202:
        worker = getattr(request.app.state, 'walle_repository_registration', None)
        if worker is not None:
            worker.wake()
    return result


def project_reconciliation_operation(value, operation_id):
    row = exact(value, OPERATION_FIELDS)
    fixed = _fixed(row['fixed_input'])
    for field in ('task_id', 'session_id', 'control_generation'):
        strict_integer(row[field], field)
    registered_command('POST', PATH.format(task_id=row['task_id']), row['idempotency_key'])
    if (
        row['id'] != operation_id
        or row['operation_type'] != TYPE
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != row['task_id']
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or row['expected_state_version'] != fixed['expected_state_version']
        or type(row['steps']) is not list
        or len(row['steps']) != len(STEPS)
    ):
        raise ValueError('Original reconciliation projection differs')
    status = strict_enum(row['status'], 'status', ('PENDING', 'SUCCEEDED', 'CANCELLED'))
    _time(row['created_at'], nullable=False)
    _time(row['started_at'])
    _time(row['ended_at'])
    for index, (step, kind) in enumerate(zip(row['steps'], STEPS, strict=True), 1):
        step = exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != operation_id
            or step['step_no'] != index
            or step['step_type'] != kind
            or step['status'] != status
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
        ):
            raise ValueError('Original reconciliation step differs')
        for key in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[key])
        if status == 'SUCCEEDED':
            result = exact(step['result_ref'], ('operation_id', 'original_status'))
            if result['operation_id'] != fixed['operation_id']:
                raise ValueError('Original reconciliation result scope differs')
            strict_enum(
                result['original_status'], 'original_status', ('SUCCEEDED', 'RUNNING', 'UNKNOWN')
            )
        elif step['result_ref'] is not None:
            raise ValueError('Original reconciliation has a premature result')
    return row


def public_reconciliation_operation(connection, operation):
    fixed = _fixed(strict_json_object(operation['fixed_input']))
    rows = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if any(row['fixed_input'] != operation['fixed_input'] for row in rows):
        raise StorageUnavailable('Original reconciliation input differs')
    steps = [
        {
            **dict(row),
            'fixed_input': fixed,
            'result_ref': None
            if row['result_ref'] is None
            else strict_json_object(row['result_ref']),
        }
        for row in rows
    ]
    return project_reconciliation_operation(
        {**dict(operation), 'fixed_input': fixed, 'content_capture': None, 'steps': steps},
        operation['id'],
    )
