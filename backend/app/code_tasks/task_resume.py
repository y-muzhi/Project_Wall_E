"""Accept a single explicit continuation for an original Coding model wait."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    decimal_integer,
    object_fields,
    reject,
    strict_integer,
    strict_json_object,
)

from .coding_model_wait import read_task_waits
from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .task_model_ingress import ModelWindow, read_original_window_state
from .task_start import start_conflict

RESUME_PATH = '/api/v1/code-tasks/{task_id}/resume'
RESUME_CAPABILITY = 'APP-CODE-CMD-C36'
RESUME_STEPS = operation_steps('CODING', 'RESUME')
ACTIVE = ('PENDING', 'RUNNING', 'UNKNOWN')
resume_write_router = APIRouter(redirect_slashes=False)


def _waiting_ids(value):
    if type(value) is not list:
        reject('waiting_item_ids', 'INVALID_TYPE', '等待事项必须为列表')
    ids = [strict_integer(item, 'waiting_item_ids') for item in value]
    if len(set(ids)) != len(ids):
        reject('waiting_item_ids', 'DUPLICATE_PARAMETER', '等待事项不得重复')
    return ids


@dataclass(frozen=True)
class ResumeRequest:
    task_id: int
    expected_state_version: int
    operation_id: int
    waiting_item_ids: tuple[int, ...]
    delivery_confirmed: bool
    command: RegisteredCommand

    required = ('expected_state_version', 'operation_id', 'waiting_item_ids')
    body_fields = (*required, 'repository_quiescent_confirmed')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        data = {
            'task_id': self.task_id,
            'expected_state_version': self.expected_state_version,
            'operation_id': self.operation_id,
            'waiting_item_ids': list(self.waiting_item_ids),
        }
        if self.delivery_confirmed:
            data['repository_quiescent_confirmed'] = True
        return data

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task_id = decimal_integer(request.path_params['task_id'], 'task_id')
        fields = object_fields(body, 'body', cls.body_fields, cls.required)
        confirmed = 'repository_quiescent_confirmed' in fields
        if confirmed and fields['repository_quiescent_confirmed'] is not True:
            reject('repository_quiescent_confirmed', 'INVALID_TYPE', '交付窗口确认必须为 true')
        return cls(
            task_id,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            strict_integer(fields['operation_id'], 'operation_id'),
            tuple(_waiting_ids(fields['waiting_item_ids'])),
            confirmed,
            registered_command(
                'POST',
                RESUME_PATH.format(task_id=task_id),
                idempotency_header(request, lowercase=True),
            ),
        )


def active_resume(connection, task_id):
    rows = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type='RESUME'
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
        (task_id,),
    ).fetchall()
    if len(rows) > 1:
        raise StorageUnavailable('Multiple active Coding continuations')
    return rows[0] if rows else None


def model_resume_window(connection, task):
    if (
        task['status'] != 'WAITING'
        or task['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
        or task['resume_phase'] != task['phase']
        or task['stop_requested_at'] is not None
        or task['active_session_id'] is None
    ):
        return None
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (task['active_session_id'], task['id']),
    ).fetchone()
    if session is None or session['role'] != task['phase'] or session['model_window'] is None:
        return None
    saved = strict_json_object(session['model_window'])
    if saved.get('state') != 'HELD':
        return None
    window = ModelWindow(
        task['id'],
        session['instance_id'],
        task['control_generation'],
        session['id'],
        session['native_session_id'],
        saved['operation_id'],
        saved['native_trigger_message_id'],
    )
    credential = session['gateway_credential_ref']
    if read_original_window_state(connection, window, credential) != 'HELD':
        return None
    original = connection.execute(
        """SELECT operation_type,status FROM code_operations o WHERE id=? AND task_id=?
           AND ((o.operation_type IN ('START','RESUME') AND o.session_id=? AND o.control_generation=?)
                OR (o.operation_type='HANDOFF_ROLE' AND o.control_generation+1=? AND EXISTS(
                    SELECT 1 FROM code_operation_steps s WHERE s.operation_id=o.id AND s.step_no=4
                    AND s.status='SUCCEEDED' AND json_extract(s.result_ref,'$.session_id')=?)))""",
        (
            window.operation_id,
            task['id'],
            session['id'],
            window.generation,
            window.generation,
            session['id'],
        ),
    ).fetchone()
    if (
        original is None
        or original['operation_type'] not in ('START', 'RESUME', 'HANDOFF_ROLE')
        or original['status'] != 'SUCCEEDED'
    ):
        return None
    return window, credential


def model_waits_cleared(connection, window, waits):
    if (
        not waits
        or connection.execute(
            """SELECT 1 FROM code_task_reservations WHERE task_id=?
           AND status IN ('RESERVED','UNKNOWN','DISPUTED') LIMIT 1""",
            (window.task_id,),
        ).fetchone()
    ):
        return False
    for wait in waits:
        if wait['kind'] not in ('BUDGET', 'MODEL_RESULT'):
            return False
        if wait['source_kind'] == 'OPERATION':
            if wait['source_id'] != window.operation_id:
                return False
            continue
        row = connection.execute(
            """SELECT r.status AS reservation_status,u.ended_at FROM llm_uses u
               JOIN code_task_reservations r ON r.llm_use_id=u.id AND r.task_id=?
               WHERE u.id=? AND u.execution_session_id=? AND u.operation_id=?""",
            (window.task_id, wait['source_id'], window.execution_session_id, window.operation_id),
        ).fetchone()
        if (
            row is None
            or row['ended_at'] is None
            or row['reservation_status'] not in ('SETTLED', 'RELEASED_UNSENT')
        ):
            return False
    return True


def _new_resume(connection, task, request, *, controller_epoch=None):
    version = task['state_version']
    if version >= MAX_SAFE_INTEGER - 2:
        return start_conflict('INVALID_STATE', task)
    now = max(operation_time(None), task['updated_at'])
    operation_id = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input(request.business_input())
    if (
        connection.execute(
            """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
           AND control_generation=? AND status='WAITING' AND stop_requested_at IS NULL""",
            (version + 1, now, task['id'], version, task['control_generation']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original continuation acceptance fence differs')
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,'RESUME',?,?,?,?,'PENDING',?)""",
        (
            operation_id,
            task['id'],
            task['id'],
            task['active_session_id'],
            request.idempotency_key,
            version,
            fixed,
            task['control_generation'],
            now,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,external_identity)
           VALUES(?,?,?,'PENDING',?,?)""",
        [
            (
                operation_id,
                number,
                kind,
                fixed,
                canonical_input({'controller_epoch': controller_epoch})
                if number == 1 and controller_epoch
                else None,
            )
            for number, kind in enumerate(RESUME_STEPS, 1)
        ],
    )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': operation_id,
                'operation_status': 'PENDING',
                'task_status': 'WAITING',
                'state_version': version + 1,
            },
            'details': None,
        },
        202,
    )


def accept_resume(runtime, request, *, available, delivery_epoch=None, cleanup_available=False):
    require_schema(runtime)

    def accept(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return Rejection('NOT_FOUND', None)
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return start_conflict('TASK_ENDED', task)
        if task['stop_requested_at'] is not None or task['status'] != 'WAITING':
            return start_conflict('INVALID_STATE', task)
        if task['state_version'] != request.expected_state_version:
            return start_conflict('VERSION_CONFLICT', task)
        pending = active_resume(connection, task['id'])
        if pending is not None:
            code = (
                'EXTERNAL_RESULT_UNKNOWN'
                if pending['status'] == 'UNKNOWN'
                else 'OPERATION_IN_PROGRESS'
            )
            return start_conflict(code, task, pending['id'])
        if request.delivery_confirmed:
            original = connection.execute(
                "SELECT 1 FROM code_operations WHERE id=? AND task_id=? AND operation_type='DELIVER'",
                (request.operation_id, task['id']),
            ).fetchone()
            if original is None:
                return Rejection(
                    'INVALID_INPUT',
                    {
                        'field_errors': [
                            {'field': 'repository_quiescent_confirmed', 'reason': 'UNKNOWN_FIELD'},
                        ]
                    },
                )
            from .task_delivery_window import renewable_delivery

            ready = renewable_delivery(connection, task, request.operation_id)
            if ready is None:
                return start_conflict('EXTERNAL_RESULT_UNKNOWN', task, request.operation_id)
            if list(request.waiting_item_ids) != [ready[1]['id']]:
                return start_conflict('OPERATION_CONFLICT', task)
            if delivery_epoch is None:
                raise ConfigurationNotReady('Q20-GIT')
            return _new_resume(connection, task, request, controller_epoch=delivery_epoch)
        if task['phase'] == 'DELIVERY':
            from .task_delivery_finalize import resumable_finalization

            original = connection.execute(
                "SELECT 1 FROM code_operations WHERE id=? AND task_id=? AND operation_type='DELIVER'",
                (request.operation_id, task['id']),
            ).fetchone()
            if original is None:
                return start_conflict('OPERATION_CONFLICT', task)
            ready = resumable_finalization(connection, task, request.operation_id)
            if ready is None:
                return start_conflict('EXTERNAL_RESULT_UNKNOWN', task, request.operation_id)
            if list(request.waiting_item_ids) != [ready[1]['id']]:
                return start_conflict('OPERATION_CONFLICT', task)
            if not cleanup_available:
                raise ConfigurationNotReady('RUNTIME')
            return _new_resume(connection, task, request)
        original = model_resume_window(connection, task)
        if original is None or original[0].operation_id != request.operation_id:
            return start_conflict('OPERATION_CONFLICT', task)
        window, _ = original
        waits = read_task_waits(connection, task['id'])
        if set(request.waiting_item_ids) != {wait['id'] for wait in waits}:
            return start_conflict('OPERATION_CONFLICT', task)
        if not model_waits_cleared(connection, window, waits):
            return start_conflict('EXTERNAL_RESULT_UNKNOWN', task, window.operation_id)
        if not available:
            raise ConfigurationNotReady('Q20-OC', 'Q20-MODEL')
        return _new_resume(connection, task, request)

    return execute_idempotent(
        runtime.commands(),
        RESUME_CAPABILITY,
        request,
        accept,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def validate_resume_receipt(command, data, http_status):
    value = exact(
        data, ('task_id', 'operation_id', 'operation_status', 'task_status', 'state_version')
    )
    for name in ('task_id', 'operation_id', 'state_version'):
        strict_integer(value[name], name)
    if (
        http_status != 202
        or value['operation_status'] != 'PENDING'
        or value['task_status'] != 'WAITING'
        or value['task_id'] != command.route.match(command.path)['task_id']
    ):
        raise ValueError('Original continuation receipt differs')
    return value['task_id']


def original_resume_steps(connection, operation):
    task_id = operation['task_id']
    command = registered_command(
        'POST', RESUME_PATH.format(task_id=task_id), operation['idempotency_key']
    )
    receipt = connection.execute(
        """SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    if (
        operation['operation_type'] != 'RESUME'
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != task_id
        or operation['testing_task_id'] is not None
        or operation['session_id'] is None
        or receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['business_input_json'] != operation['fixed_input']
    ):
        raise StorageUnavailable('Original continuation acceptance differs')
    fixed = strict_json_object(operation['fixed_input'])
    fields = ('task_id', 'expected_state_version', 'operation_id', 'waiting_item_ids')
    if 'repository_quiescent_confirmed' in fixed:
        if fixed['repository_quiescent_confirmed'] is not True:
            raise StorageUnavailable('Original delivery confirmation differs')
        fields = (*fields, 'repository_quiescent_confirmed')
    exact(fixed, fields)
    strict_integer(fixed['operation_id'], 'operation_id')
    _waiting_ids(fixed['waiting_item_ids'])
    saved = strict_json_object(receipt['success_result_json'])
    Success(saved, receipt['http_status']).encoded()
    validate_resume_receipt(command, saved['data'], receipt['http_status'])
    if (
        fixed['task_id'] != task_id
        or fixed['expected_state_version'] != operation['expected_state_version']
        or saved['code'] != 'OPERATION_ACCEPTED'
        or saved['data']['operation_id'] != operation['id']
        or saved['data']['state_version'] != operation['expected_state_version'] + 1
    ):
        raise StorageUnavailable('Original continuation receipt differs')
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(RESUME_STEPS) or any(
        step['step_no'] != index
        or step['step_type'] != kind
        or step['fixed_input'] != operation['fixed_input']
        for index, (step, kind) in enumerate(zip(steps, RESUME_STEPS), 1)
    ):
        raise StorageUnavailable('Original continuation steps differ')
    return fixed, steps


class ResumeResponse:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    status = 202
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'INVALID_STATE',
            'TASK_ENDED',
            'VERSION_CONFLICT',
            'OPERATION_CONFLICT',
            'OPERATION_IN_PROGRESS',
            'EXTERNAL_RESULT_UNKNOWN',
            'EXECUTION_NOT_STOPPED',
            'CONFIG_NOT_READY',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'COMMAND_CLOSED',
        }
    )

    @staticmethod
    def project(data, request):
        validate_resume_receipt(request.command, data, 202)
        if data['state_version'] != request.expected_state_version + 1:
            raise ValueError('Original continuation version differs')
        return data, None


@resume_write_router.post(RESUME_PATH)
async def resume_task_http(request: Request):
    from .repository_registration_worker import RepositoryRegistrationWorker

    worker = getattr(request.app.state, 'walle_repository_registration', None)
    available = type(worker) is RepositoryRegistrationWorker and worker.accepts_model_resumes
    delivery_epoch = (
        worker.delivery_epoch
        if type(worker) is RepositoryRegistrationWorker and worker.delivery_writes_ready
        else None
    )

    cleanup_available = (
        type(worker) is RepositoryRegistrationWorker and worker.delivery_finalization_ready
    )

    def invoke(runtime, parsed):
        return accept_resume(
            runtime,
            parsed,
            available=available,
            delivery_epoch=delivery_epoch,
            cleanup_available=cleanup_available,
        )

    result = await handle_http(request, ResumeRequest, ResumeResponse, invoke)
    if result.status_code == 202 and (available or delivery_epoch is not None):
        worker.wake()
    return result
