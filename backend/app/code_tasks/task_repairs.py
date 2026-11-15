"""Accept one explicit repair and expose immutable task-scoped repair history."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    decimal_integer,
    object_fields,
    reject,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .error_codes import ERROR_HTTP
from .operation_protocol import operation_steps
from .repository_operations import OPERATION_FIELDS, STATES, STEP_FIELDS, _time
from .repository_reads import ERRORS
from .task_capture_quiescence import current_capture_owner
from .task_defects import DEFECT_STATES
from .task_defects import _stored as stored_defect
from .task_start import start_conflict

PATH = '/api/v1/code-tasks/{task_id}/repairs'
TYPE = 'REPAIR'
STEPS = operation_steps('CODING', TYPE)
FIELDS = (
    'id',
    'task_id',
    'defect_ids',
    'source_candidate_id',
    'operation_id',
    'status',
    'created_at',
    'result_candidate_id',
    'ended_at',
    'failure_code',
)
RECEIPT = ('task_id', 'operation_id', 'operation_status', 'task_status', 'state_version')
NOT_FOUND = Rejection('NOT_FOUND', None)
repair_router = APIRouter(redirect_slashes=False)


def _defect_ids(value):
    if type(value) is not list or not value:
        reject('defect_ids', 'INVALID_TYPE', '请选择至少一条缺陷')
    identities = [strict_integer(item, f'defect_ids[{i}]') for i, item in enumerate(value)]
    if len(set(identities)) != len(identities):
        reject('defect_ids', 'DUPLICATE_PARAMETER', '缺陷不可重复')
    return identities


def _fixed(value):
    fields = ('expected_state_version', 'candidate_id', 'defect_ids')
    body = object_fields(value, 'body', fields, fields)
    return {
        'expected_state_version': strict_integer(
            body['expected_state_version'], 'expected_state_version'
        ),
        'candidate_id': strict_integer(body['candidate_id'], 'candidate_id'),
        'defect_ids': _defect_ids(body['defect_ids']),
    }


@dataclass(frozen=True)
class RepairRequest:
    task_id: int
    data: dict
    command: RegisteredCommand

    body_fields = ('expected_state_version', 'candidate_id', 'defect_ids')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return self.data

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        return cls(
            task,
            _fixed(body),
            registered_command(
                'POST', PATH.format(task_id=task), idempotency_header(request, lowercase=True)
            ),
        )


def _pending_delivery(connection, task):
    identity = task['current_delivery_id']
    if identity is None:
        return None, None
    row = connection.execute(
        """SELECT d.*,o.status AS operation_status FROM code_deliveries d
           JOIN code_operations o ON o.id=d.operation_id AND o.task_id=d.task_id
           WHERE d.id=? AND d.task_id=? AND o.operation_type='DELIVER'""",
        (identity, task['id']),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original Coding delivery is missing')
    if row['status'] == 'UNKNOWN' or row['git_write_status'] in ('MAY_HAVE_BEEN_SENT', 'UNKNOWN'):
        return 'EXTERNAL_RESULT_UNKNOWN', row
    if (
        row['status'] != 'PENDING'
        or row['operation_status'] != 'PENDING'
        or row['git_write_status'] != 'NOT_DISPATCHED'
        or row['commit_input_ref'] is not None
        or row['planned_commit_oid'] is not None
        or connection.execute(
            """SELECT 1 FROM code_operation_steps WHERE operation_id=? AND
               (status<>'PENDING' OR external_identity IS NOT NULL OR started_at IS NOT NULL)
               UNION ALL SELECT 1 FROM code_commands WHERE operation_id=? LIMIT 1""",
            (row['operation_id'], row['operation_id']),
        ).fetchone()
    ):
        return 'OPERATION_CONFLICT', row
    return None, row


def _conflicting_operation(connection, task, delivery):
    allowed = 0 if delivery is None else delivery['operation_id']
    return connection.execute(
        """SELECT id FROM code_operations WHERE task_id=? AND id<>?
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id LIMIT 1""",
        (task['id'], allowed),
    ).fetchone()


def _repair_owner(connection, task, candidate, delivery):
    session = connection.execute(
        "SELECT * FROM code_sessions WHERE id=? AND task_id=? AND status='ACTIVE'",
        (task['active_session_id'], task['id']),
    ).fetchone()
    if session is None or candidate['role'] != session['role']:
        return None
    checking = {**dict(task), 'status': 'VERIFYING', 'phase': session['role']}
    try:
        owner, scope, window, previous = current_capture_owner(
            connection, checking, 0 if delivery is None else delivery['operation_id']
        )
    except TaskExecutionError:
        return None
    return (owner, scope, previous) if window['state'] == 'CLOSED' else None


def _defects(connection, task, candidate, identities):
    facts = []
    for identity in identities:
        row = connection.execute(
            'SELECT * FROM code_defects WHERE id=? AND task_id=? AND candidate_id=?',
            (identity, task['id'], candidate['id']),
        ).fetchone()
        if row is None:
            return None
        facts.append(stored_defect(connection, row, task['id']))
    return tuple(facts)


def _cancel_pending_delivery(connection, delivery, at):
    connection.execute(
        "UPDATE code_deliveries SET status='CANCELLED' WHERE id=?", (delivery['id'],)
    )
    connection.execute(
        """UPDATE code_operations SET status='CANCELLED',ended_at=?
           WHERE id=? AND status='PENDING'""",
        (at, delivery['operation_id']),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
           WHERE operation_id=? AND status='PENDING'""",
        (at, at, delivery['operation_id']),
    )


def repair_resources_ready(worker):
    return bool(
        getattr(worker, 'accepts_model_resumes', False)
        and getattr(worker, 'accepts_candidate_capture', False)
    )


def repair_action_reason(connection, task, available):
    if task['status'] not in DEFECT_STATES or task['stop_requested_at'] is not None:
        return 'INVALID_STATE'
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (task['current_candidate_id'], task['id']),
    ).fetchone()
    if candidate is None:
        return 'CANDIDATE_NOT_CURRENT'
    reason, delivery = _pending_delivery(connection, task)
    if reason is not None:
        return reason
    if _conflicting_operation(connection, task, delivery) is not None:
        return 'OPERATION_CONFLICT'
    if not available:
        return 'CONFIG_NOT_READY'
    return None if _repair_owner(connection, task, candidate, delivery) else 'EXECUTION_NOT_STOPPED'


def _save(connection, request, available):
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (request.task_id,)).fetchone()
    if task is None:
        return NOT_FOUND
    if task['status'] in ('COMPLETED', 'TERMINATED'):
        return start_conflict('TASK_ENDED', task)
    data = request.data
    if task['state_version'] != data['expected_state_version']:
        return start_conflict('VERSION_CONFLICT', task)
    if (
        task['status'] not in DEFECT_STATES
        or task['stop_requested_at'] is not None
        or (task['state_version'] >= MAX_SAFE_INTEGER - 4)
    ):
        return start_conflict('INVALID_STATE', task)
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (data['candidate_id'], request.task_id),
    ).fetchone()
    if candidate is None or candidate['id'] != task['current_candidate_id']:
        return start_conflict('CANDIDATE_NOT_CURRENT', task)
    if _defects(connection, task, candidate, data['defect_ids']) is None:
        return Rejection(
            'DEFECT_SOURCE_MISMATCH',
            {
                'field_errors': [{'field': 'defect_ids', 'reason': 'RANGE'}],
            },
        )
    reason, delivery = _pending_delivery(connection, task)
    if reason is not None:
        return start_conflict(reason, task, delivery['operation_id'])
    conflict = _conflicting_operation(connection, task, delivery)
    if conflict is not None:
        return start_conflict('OPERATION_CONFLICT', task, conflict['id'])
    if not available:
        raise ConfigurationNotReady('RUNTIME')
    owner = _repair_owner(connection, task, candidate, delivery)
    if owner is None:
        return start_conflict('EXECUTION_NOT_STOPPED', task)
    session, _, _ = owner
    at = max(operation_time(None), task['updated_at'])
    version = increment(task['state_version'])
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    repair = entity_id(connection, EntityKind.CODE_REPAIR)
    fixed = canonical_input(data)
    if delivery is not None:
        _cancel_pending_delivery(connection, delivery, at)
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,?,?,?,?,?,'PENDING',?)""",
        (
            operation,
            task['id'],
            task['id'],
            session['id'],
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
        [(operation, number, name, fixed) for number, name in enumerate(STEPS, 1)],
    )
    connection.execute(
        """INSERT INTO code_repairs(id,task_id,source_candidate_id,operation_id,status,created_at)
           VALUES(?,?,?,?,'PENDING',?)""",
        (repair, task['id'], candidate['id'], operation, at),
    )
    connection.executemany(
        'INSERT INTO code_repair_defects(repair_id,defect_id) VALUES(?,?)',
        [(repair, identity) for identity in data['defect_ids']],
    )
    connection.execute(
        """INSERT INTO code_waiting_items(id,task_id,kind,source_kind,source_id,resume_phase,status,created_at)
           VALUES(?,?,'OPERATION_RESULT','OPERATION',?,?,'OPEN',?)""",
        (
            entity_id(connection, EntityKind.WAITING_ITEM),
            task['id'],
            operation,
            session['role'],
            at,
        ),
    )
    changed = connection.execute(
        """UPDATE code_tasks SET status='WAITING',phase=?,resume_phase=?,state_version=?,updated_at=?,
           current_test_report_id=NULL,current_delivery_plan_id=NULL,current_delivery_id=NULL
           WHERE id=? AND state_version=? AND stop_requested_at IS NULL
           AND control_generation=? AND active_session_id=? AND current_candidate_id=?""",
        (
            session['role'],
            session['role'],
            version,
            at,
            task['id'],
            task['state_version'],
            task['control_generation'],
            session['id'],
            candidate['id'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Coding repair acceptance was fenced')
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': operation,
                'operation_status': 'PENDING',
                'task_status': 'WAITING',
                'state_version': version,
            },
            'details': None,
        },
        202,
    )


def accept_repair(runtime, request, *, available):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _save(connection, request, available),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def read_repair_operation(connection, operation):
    fixed = _fixed(strict_json_object(operation['fixed_input']))
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    repair = connection.execute(
        'SELECT * FROM code_repairs WHERE operation_id=? AND task_id=?',
        (operation['id'], operation['task_id']),
    ).fetchone()
    if (
        operation['operation_type'] != TYPE
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != operation['task_id']
        or operation['testing_task_id'] is not None
        or operation['fixed_input'] != canonical_input(fixed)
        or operation['expected_state_version'] != fixed['expected_state_version']
        or [(row['step_no'], row['step_type']) for row in steps] != list(enumerate(STEPS, 1))
        or any(row['fixed_input'] != operation['fixed_input'] for row in steps)
        or repair is None
        or repair['status'] != operation['status']
        or repair['source_candidate_id'] != fixed['candidate_id']
        or repair['created_at'] != operation['created_at']
        or repair['ended_at'] != operation['ended_at']
        or repair['failure_code'] != operation['failure_code']
    ):
        raise StorageUnavailable('Original repair operation differs')
    rows = connection.execute(
        """SELECT d.id,d.task_id,d.candidate_id FROM code_repair_defects rd
           JOIN code_defects d ON d.id=rd.defect_id WHERE rd.repair_id=?""",
        (repair['id'],),
    ).fetchall()
    if {row['id'] for row in rows} != set(fixed['defect_ids']) or any(
        (row['task_id'], row['candidate_id']) != (repair['task_id'], repair['source_candidate_id'])
        for row in rows
    ):
        raise StorageUnavailable('Original repair defect sources differ')
    return repair, fixed, steps


def _project_repair(value, task_id):
    data = exact(value, FIELDS)
    for key in ('id', 'task_id', 'source_candidate_id', 'operation_id'):
        strict_integer(data[key], key)
    _defect_ids(data['defect_ids'])
    state = strict_enum(data['status'], 'status', STATES)
    _time(data['created_at'], nullable=False)
    _time(data['ended_at'])
    if (
        data['task_id'] != task_id
        or (state in ('SUCCEEDED', 'FAILED', 'CANCELLED')) != (data['ended_at'] is not None)
        or data['ended_at'] is not None
        and data['ended_at'] < data['created_at']
        or (state == 'SUCCEEDED') != (data['result_candidate_id'] is not None)
        or data['failure_code'] is not None
        and data['failure_code'] not in ERROR_HTTP
    ):
        raise ValueError('Original repair projection differs')
    if data['result_candidate_id'] is not None:
        strict_integer(data['result_candidate_id'], 'result_candidate_id')
        if data['result_candidate_id'] == data['source_candidate_id']:
            raise ValueError('Repair did not produce an independent candidate')
    return data


def _saved(connection, row, task):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=? AND task_id=?', (row['operation_id'], task)
    ).fetchone()
    if operation is None:
        raise StorageUnavailable('Original repair operation is missing')
    repair, fixed, _ = read_repair_operation(connection, operation)
    if repair['id'] != row['id']:
        raise StorageUnavailable('Original repair identity differs')
    return _project_repair({**dict(repair), 'defect_ids': fixed['defect_ids']}, task)


@dataclass(frozen=True)
class ReadRepairRequest:
    task_id: int
    identity: int | None
    page: int

    @classmethod
    def parse(cls, request):
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        if 'repair_id' in request.path_params:
            request_query(request)
            return cls(task, decimal_integer(request.path_params['repair_id'], 'repair_id'), 1)
        query = request_query(request, singles=('page',))
        return cls(task, None, decimal_integer(query.get('page', '1'), 'page', maximum=MAX_PAGE))


def read_repairs(runtime, request):
    require_schema(runtime)
    task = request.task_id
    with runtime.database.transaction() as connection:
        if connection.execute('SELECT 1 FROM code_tasks WHERE id=?', (task,)).fetchone() is None:
            return NOT_FOUND.result
        if request.identity is not None:
            row = connection.execute(
                'SELECT * FROM code_repairs WHERE id=? AND task_id=?',
                (request.identity, task),
            ).fetchone()
            if row is None:
                return NOT_FOUND.result
            data = _saved(connection, row, task)
        else:
            total = connection.execute(
                'SELECT count(*) FROM code_repairs WHERE task_id=?', (task,)
            ).fetchone()[0]
            rows = connection.execute(
                'SELECT * FROM code_repairs WHERE task_id=? ORDER BY id LIMIT ? OFFSET ?',
                (task, PAGE_SIZE, page_offset(request.page)),
            ).fetchall()
            data = {
                **page_metadata(request.page, total),
                'items': [_saved(connection, row, task) for row in rows],
            }
    return {'code': 'READ_OK', 'data': data, 'details': None}


class ReadRepair:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        if request.identity is None:
            return page(value, lambda row: _project_repair(row, request.task_id), request.page)
        data = _project_repair(value, request.task_id)
        if data['id'] != request.identity:
            raise ValueError('Original repair identity differs')
        return data, None


def project_repair_receipt(command, value, status):
    data = exact(value, RECEIPT)
    for key in ('task_id', 'operation_id', 'state_version'):
        strict_integer(data[key], key)
    if (
        status != 202
        or data['operation_status'] != 'PENDING'
        or data['task_status'] != 'WAITING'
        or data['task_id'] != command.route.match(command.path)['task_id']
    ):
        raise ValueError('Original repair receipt crosses scope')
    return data


class RepairAccepted:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    status = 202
    errors = ERRORS | {
        'TASK_ENDED',
        'VERSION_CONFLICT',
        'INVALID_STATE',
        'CANDIDATE_NOT_CURRENT',
        'DEFECT_SOURCE_MISMATCH',
        'OPERATION_CONFLICT',
        'EXTERNAL_RESULT_UNKNOWN',
        'EXECUTION_NOT_STOPPED',
        'COMMAND_CLOSED',
        'IDEMPOTENCY_CONFLICT',
    }

    @staticmethod
    def project(value, request):
        data = project_repair_receipt(request.command, value, 202)
        if data['state_version'] != request.data['expected_state_version'] + 1:
            raise ValueError('Original repair acceptance version differs')
        return data, None


def project_repair_operation(value, identity):
    data = exact(value, OPERATION_FIELDS)
    fixed = _fixed(data['fixed_input'])
    for key in (
        'id',
        'task_id',
        'resource_id',
        'session_id',
        'control_generation',
        'expected_state_version',
    ):
        strict_integer(data[key], key)
    registered_command('POST', PATH.format(task_id=data['task_id']), data['idempotency_key'])
    if (
        data['id'] != identity
        or data['resource_kind'] != 'TASK'
        or data['resource_id'] != data['task_id']
        or data['testing_task_id'] is not None
        or data['operation_type'] != TYPE
        or data['content_capture'] is not None
        or data['expected_state_version'] != fixed['expected_state_version']
        or type(data['steps']) is not list
        or len(data['steps']) != len(STEPS)
    ):
        raise ValueError('Original repair operation crosses scope')
    strict_enum(data['status'], 'status', STATES)
    for key in ('created_at', 'started_at', 'ended_at'):
        _time(data[key], nullable=key != 'created_at')
    for number, (step, name) in enumerate(zip(data['steps'], STEPS, strict=True), 1):
        exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != name
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
            or step['result_ref'] is not None
        ):
            raise ValueError('Original repair step crosses scope')
        strict_enum(step['status'], 'step.status', STATES)
        for key in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[key])
    return data


def public_repair_operation(connection, operation):
    _, fixed, steps = read_repair_operation(connection, operation)
    return project_repair_operation(
        {
            **dict(operation),
            'fixed_input': fixed,
            'content_capture': None,
            'steps': [
                {**dict(step), 'fixed_input': fixed, 'external_identity': None, 'result_ref': None}
                for step in steps
            ],
        },
        operation['id'],
    )


@repair_router.post(PATH)
async def request_repair_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    available = repair_resources_ready(worker)
    response = await handle_http(
        request,
        RepairRequest,
        RepairAccepted,
        lambda runtime, parsed: accept_repair(runtime, parsed, available=available),
    )
    if response.status_code == 202 and available:
        worker.wake()
    return response


@repair_router.get(PATH)
@repair_router.get(PATH + '/{repair_id}')
async def read_repairs_http(request: Request):
    return await handle_http(request, ReadRepairRequest, ReadRepair, read_repairs)
