"""Explicit Coding adoption of an existing qualifying independent Testing report."""

from contextlib import ExitStack
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    decimal_integer,
    object_fields,
    strict_integer,
    strict_json_object,
)

from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .repository_reads import ERRORS
from .task_capture_quiescence import current_capture_owner
from .task_start import start_conflict
from .task_testing_publication import read_candidate_publication
from .task_verification_reads import _admissions

PATH = '/api/v1/code-tasks/{task_id}/test-reports'
TYPE = 'LINK_TEST_REPORT'
PHASES = {
    'AWAITING_TESTING': 'TESTING',
    'AWAITING_ACCEPTANCE': 'ACCEPTANCE',
    'VERIFYING': 'INTEGRATION',
}
STEPS = operation_steps('CODING', TYPE)
INPUT = ('expected_state_version', 'candidate_id', 'test_report_id')
OUTPUT = ('task_id', 'candidate_id', 'test_report_id', 'state_version')
report_link_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class LinkReportRequest:
    task_id: int
    expected_state_version: int
    candidate_id: int
    test_report_id: int
    command: RegisteredCommand
    admissions: tuple
    body_fields = INPUT

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {key: getattr(self, key) for key in INPUT}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        data = object_fields(body, 'body', INPUT, INPUT)
        return cls(
            task,
            *(strict_integer(data[key], key) for key in INPUT),
            registered_command(
                'POST', PATH.format(task_id=task), idempotency_header(request, lowercase=True)
            ),
            _admissions(request),
        )


def _selection(connection, task, candidate):
    phase = PHASES.get(task['status'])
    if (
        phase is None
        or task['phase'] != phase
        or task['stop_requested_at'] is not None
        or task['current_delivery_id'] is not None
        or task['state_version'] == MAX_SAFE_INTEGER
    ):
        return 'INVALID_STATE', None
    if (
        candidate is None
        or candidate['id'] != task['current_candidate_id']
        or candidate['task_id'] != task['id']
        or candidate['role'] != 'INTEGRATION'
        or candidate['control_generation'] != task['control_generation']
        or candidate['publication_operation_id'] is None
    ):
        return 'TEST_SOURCE_MISMATCH', None
    if connection.execute(
        """SELECT 1 FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')
           UNION ALL SELECT 1 FROM code_waiting_items WHERE task_id=? AND status='OPEN' LIMIT 1""",
        (task['id'], task['id']),
    ).fetchone():
        return 'OPERATION_CONFLICT', None
    publication = read_candidate_publication(connection, candidate)
    checking_task = {**dict(task), 'status': 'VERIFYING', 'phase': 'INTEGRATION'}
    try:
        session, _, window, _ = current_capture_owner(connection, checking_task)
    except TaskExecutionError:
        return 'OPERATION_CONFLICT', None
    if session['id'] != publication['session_id'] or window['state'] != 'CLOSED':
        return 'OPERATION_CONFLICT', None
    return None, session['id']


def link_action_reason(connection, task):
    if task['status'] not in PHASES:
        return 'INVALID_STATE'
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (task['current_candidate_id'], task['id']),
    ).fetchone()
    return _selection(connection, task, candidate)[0]


def _save_link(connection, request, task, report, session):
    at = max(operation_time(None), task['updated_at'], report['created_at'])
    version = increment(task['state_version'])
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input(request.business_input())
    result = {
        'task_id': task['id'],
        'candidate_id': request.candidate_id,
        'test_report_id': request.test_report_id,
        'state_version': version,
    }
    encoded = canonical_input(result)
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at,ended_at)
           VALUES(?,?,'TASK',?,?,?,?,?,?,?,'SUCCEEDED',?,?,?)""",
        (
            operation,
            task['id'],
            task['id'],
            session,
            TYPE,
            request.idempotency_key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
            at,
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,result_ref,
           started_at,ended_at,last_observed_at) VALUES(?,?,?,'SUCCEEDED',?,?,?,?,?)""",
        [
            (operation, number, step, fixed, encoded, at, at, at)
            for number, step in enumerate(STEPS, 1)
        ],
    )
    saved = connection.execute(
        """UPDATE code_tasks SET status='AWAITING_ACCEPTANCE',phase='ACCEPTANCE',state_version=?,
           current_delivery_plan_id=CASE WHEN current_test_report_id=? THEN current_delivery_plan_id ELSE NULL END,
           current_test_report_id=?,updated_at=?,last_observed_at=?
           WHERE id=? AND state_version=? AND current_candidate_id=? AND control_generation=?
           AND status=? AND phase=? AND stop_requested_at IS NULL""",
        (
            version,
            report['id'],
            report['id'],
            at,
            at,
            task['id'],
            task['state_version'],
            request.candidate_id,
            task['control_generation'],
            task['status'],
            task['phase'],
        ),
    )
    if saved.rowcount != 1:
        raise StorageUnavailable('Original Coding task changed before report link commit')
    return Success({'code': 'UPDATED', 'data': result, 'details': None}, 200)


def qualify_report(connection, catalog, admissions, task, candidate, report, held):
    from backend.app.testing.reports import _view, original_report

    testing, _, _ = original_report(connection, report)
    if testing['candidate_id'] != candidate['id'] or testing['target_kind'] != 'CANDIDATE':
        return 'TEST_SOURCE_MISMATCH', None
    try:
        view = _view(connection, catalog, admissions, report, held=held)
    except (KeyError, TypeError, ValueError) as error:
        raise StorageUnavailable('Original report is unreadable') from error
    reasons = view['delivery_ineligibility_reason_codes']
    if 'TEST_ASSET_REVOKED' in reasons:
        return 'TEST_ASSET_REVOKED', None
    if (
        'DESIGN_MISMATCH' in reasons
        or 'TARGET_NOT_CURRENT' in reasons
        or candidate['task_id'] != task['id']
    ):
        return 'TEST_SOURCE_MISMATCH', None
    return (None, view) if view['delivery_eligible'] else ('TEST_REPORT_NOT_ELIGIBLE', None)


def accept_link(runtime, request):
    require_schema(runtime)

    def save(connection, held):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        candidate = connection.execute(
            'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
            (request.candidate_id, request.task_id),
        ).fetchone()
        report = connection.execute(
            'SELECT * FROM testing_reports WHERE id=?', (request.test_report_id,)
        ).fetchone()
        if task is None or candidate is None or report is None:
            return Rejection('NOT_FOUND', None)
        if task['state_version'] != request.expected_state_version:
            return start_conflict('VERSION_CONFLICT', task)
        reason, session = _selection(connection, task, candidate)
        if reason is not None:
            return start_conflict(reason, task)
        reason, _ = qualify_report(
            connection, runtime.catalog, request.admissions, task, candidate, report, held
        )
        if reason is not None:
            return start_conflict(reason, task)
        return _save_link(connection, request, task, report, session)

    with ExitStack() as held:
        return execute_idempotent(
            runtime.commands(),
            request.command.route.capability_id,
            request,
            lambda connection: save(connection, held),
            target_identity=request.command.scope.target_identity,
            allowed_failures=frozenset(),
        )


def project_link_receipt(command, value, status):
    data = exact(value, OUTPUT)
    for key in OUTPUT:
        strict_integer(data[key], key)
    if status != 200 or data['task_id'] != command.route.match(command.path)['task_id']:
        raise ValueError('Original Coding report link crosses scope')
    return data


class LinkReportResponse:
    error_contract = 'code'
    success_code = 'UPDATED'
    errors = ERRORS | {
        'COMMAND_CLOSED',
        'INVALID_STATE',
        'VERSION_CONFLICT',
        'OPERATION_CONFLICT',
        'BASIS_REF_INVALID',
        'CHECK_CONFIGURATION_INVALID',
        'TEST_REPORT_NOT_ELIGIBLE',
        'TEST_SOURCE_MISMATCH',
        'TEST_ASSET_REVOKED',
    }

    @staticmethod
    def project(value, request):
        data = project_link_receipt(request.command, value, 200)
        if (
            data['candidate_id'] != request.candidate_id
            or data['test_report_id'] != request.test_report_id
            or data['state_version'] != request.expected_state_version + 1
        ):
            raise ValueError('Original Coding report link differs from its fixed input')
        return data, None


def project_link_operation(value, identity):
    row = exact(value, OPERATION_FIELDS)
    task = strict_integer(row['task_id'], 'task_id')
    if (
        strict_integer(row['id'], 'operation_id') != identity
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != task
        or row['operation_type'] != TYPE
        or row['status'] != 'SUCCEEDED'
        or any(
            row[key] is not None for key in ('testing_task_id', 'failure_code', 'content_capture')
        )
    ):
        raise ValueError('Original Coding report operation differs')
    strict_integer(row['session_id'], 'session_id')
    strict_integer(row['control_generation'], 'control_generation')
    fixed = exact(row['fixed_input'], INPUT)
    for key in INPUT:
        strict_integer(fixed[key], key)
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    if version != fixed['expected_state_version']:
        raise ValueError('Original Coding report operation version differs')
    registered_command('POST', PATH.format(task_id=task), row['idempotency_key'])
    for field in ('created_at', 'started_at', 'ended_at'):
        _time(row[field], nullable=False)
    if not row['created_at'] <= row['started_at'] <= row['ended_at']:
        raise ValueError('Original Coding report operation time differs')
    result = {
        'task_id': task,
        'candidate_id': fixed['candidate_id'],
        'test_report_id': fixed['test_report_id'],
        'state_version': version + 1,
    }
    if type(row['steps']) is not list or len(row['steps']) != len(STEPS):
        raise ValueError('Original Coding report operation steps differ')
    previous = row['started_at']
    for number, (entry, kind) in enumerate(zip(row['steps'], STEPS, strict=True), 1):
        step = exact(entry, STEP_FIELDS)
        for field in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[field], nullable=False)
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != kind
            or step['status'] != 'SUCCEEDED'
            or step['external_identity'] is not None
            or step['fixed_input'] != fixed
            or step['result_ref'] != result
            or not previous
            <= step['started_at']
            <= step['ended_at']
            <= step['last_observed_at']
            <= row['ended_at']
        ):
            raise ValueError('Original Coding report operation step differs')
        previous = step['ended_at']
    return row


def read_link_operation(connection, operation):
    fixed = strict_json_object(operation['fixed_input'])
    source = connection.execute(
        """SELECT 1 FROM testing_reports r JOIN testing_tasks t ON t.id=r.testing_task_id
           JOIN code_candidates c ON c.id=t.candidate_id
           WHERE r.id=? AND t.report_id=r.id AND t.target_kind='CANDIDATE' AND c.id=? AND c.task_id=?""",
        (fixed['test_report_id'], fixed['candidate_id'], operation['task_id']),
    ).fetchone()
    if source is None:
        raise StorageUnavailable('Original linked report owner differs')
    steps = [
        {
            **dict(step),
            'fixed_input': strict_json_object(step['fixed_input']),
            'result_ref': strict_json_object(step['result_ref']),
        }
        for step in connection.execute(
            'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
            (operation['id'],),
        )
    ]
    return project_link_operation(
        {**dict(operation), 'fixed_input': fixed, 'steps': steps, 'content_capture': None},
        operation['id'],
    )


def require_current_report_link(connection, task):
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type='LINK_TEST_REPORT'
           AND status='SUCCEEDED' AND json_extract(fixed_input,'$.test_report_id')=?
           AND json_extract(fixed_input,'$.candidate_id')=? ORDER BY id DESC LIMIT 1""",
        (task['id'], task['current_test_report_id'], task['current_candidate_id']),
    ).fetchone()
    if (
        operation is None
        or operation['control_generation'] != task['control_generation']
        or operation['session_id'] != task['active_session_id']
        or operation['expected_state_version'] >= task['state_version']
    ):
        raise StorageUnavailable('Current Coding report link is missing')
    read_link_operation(connection, operation)


@report_link_router.post(PATH)
async def link_report_http(request: Request):
    return await handle_http(request, LinkReportRequest, LinkReportResponse, accept_link)
