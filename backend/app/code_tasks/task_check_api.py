"""Accept an original Coding candidate capture under the persisted activity fence."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import CapacityExhausted, EntityKind, entity_id
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.resources import ConfigInvalid
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
    strict_enum,
    strict_integer,
)

from .coding_check_plan import CodingCheckPlanError, read_coding_check_selection
from .coding_project_check_scope import require_project_check_admissions
from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .repository_reads import ERRORS
from .task_basis import TaskBasisUnavailable
from .task_candidate_commit import reserve_candidate_identity
from .task_capture_quiescence import current_capture_owner
from .task_initial_configuration import current_effective_configuration
from .task_role_chain import RoleChainUnavailable, current_role_chain
from .task_start import start_conflict
from .task_testing_publication import published_check_task
from .task_verify_candidate import TYPE as VERIFY_TYPE
from .task_verify_candidate import VERIFY

CAPTURE = '/api/v1/code-tasks/{task_id}/candidates'
CAPTURE_TYPE = 'CAPTURE_AND_CHECK'
check_write_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class CaptureCheckRequest:
    task_id: int
    expected_state_version: int
    purpose: str
    command: RegisteredCommand
    candidate_id: int | None

    body_fields = ('expected_state_version', 'purpose')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        value = {'expected_state_version': self.expected_state_version, 'purpose': self.purpose}
        if self.candidate_id is not None:
            value['candidate_id'] = self.candidate_id
        return value

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task_id = decimal_integer(request.path_params['task_id'], 'task_id')
        fixed = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        candidate = request.path_params.get('candidate_id')
        candidate_id = None if candidate is None else decimal_integer(candidate, 'candidate_id')
        path = CAPTURE if candidate_id is None else VERIFY
        return cls(
            task_id,
            strict_integer(fixed['expected_state_version'], 'expected_state_version'),
            strict_enum(fixed['purpose'], 'purpose', ('HANDOFF',)),
            registered_command(
                'POST',
                path.format(task_id=task_id, candidate_id=candidate_id),
                idempotency_header(request, lowercase=True),
            ),
            candidate_id,
        )


def _capture_inputs(connection, catalog, task, admissions):
    if (
        task['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
        or task['active_session_id'] is None
    ):
        return 'VERIFICATION_STAGE_NOT_READY', None
    try:
        session, scope, _, _ = current_capture_owner(connection, task)
    except TaskExecutionError:
        return 'WRITER_ACTIVE', None
    configuration = current_effective_configuration(connection, task, start_scope=scope)
    if configuration is None or not admissions:
        raise ConfigurationNotReady('Q20-CHECKS')
    try:
        _, _, selection, definitions, _ = read_coding_check_selection(connection, catalog, task)
        require_project_check_admissions(selection, admissions, definitions=definitions)
    except TaskBasisUnavailable:
        return 'CONTENT_NOT_READY', None
    except ConfigInvalid as error:
        raise ConfigurationNotReady('Q20-CHECKS') from error
    except CodingCheckPlanError as error:
        return (
            'VERIFICATION_STAGE_NOT_READY'
            if error.code == 'VERIFICATION_STAGE_NOT_READY'
            else 'CHECK_CONFIGURATION_INVALID'
        ), None
    return None, session


def _accept_candidate_check(connection, task, session, request, *, previous_status):
    version = task['state_version']
    if version >= MAX_SAFE_INTEGER - 1:
        return start_conflict('INVALID_STATE', task)
    at = max(operation_time(None), task['updated_at'])
    kind = CAPTURE_TYPE if request.candidate_id is None else VERIFY_TYPE
    prepared = None
    try:
        operation_id = entity_id(connection, EntityKind.OPERATION_RECORD)
        if kind == CAPTURE_TYPE:
            prepared = reserve_candidate_identity(
                connection, task, operation_id, session, state_version=version + 1
            )
    except CapacityExhausted:
        return start_conflict('INVALID_STATE', task)
    fixed = canonical_input(request.business_input())
    if (
        connection.execute(
            """UPDATE code_tasks SET state_version=?,updated_at=?,status=?,phase=?,
           current_verification_id=CASE WHEN ? THEN NULL ELSE current_verification_id END WHERE id=?
           AND state_version=? AND control_generation=? AND stop_requested_at IS NULL
           AND active_session_id=? AND status=?""",
            (
                version + 1,
                at,
                task['status'],
                task['phase'],
                int(kind == VERIFY_TYPE),
                task['id'],
                version,
                task['control_generation'],
                session['id'],
                previous_status,
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original capture intake fence differs')
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,?,?,?,?,?,'PENDING',?)""",
        (
            operation_id,
            task['id'],
            task['id'],
            session['id'],
            kind,
            request.command.key,
            version,
            fixed,
            task['control_generation'],
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [
            (operation_id, index, name, prepared.fixed() if name == 'CAPTURE' else fixed)
            for index, name in enumerate(operation_steps('CODING', kind), 1)
        ],
    )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': operation_id,
                'operation_status': 'PENDING',
                'task_status': task['status'],
                'state_version': version + 1,
            },
            'details': None,
        },
        202,
    )


def accept_candidate_check(runtime, request, *, admissions):
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
        if task['stop_requested_at'] is not None or task['status'] not in (
            'RUNNING',
            'VERIFYING',
            'AWAITING_TESTING',
        ):
            return start_conflict('INVALID_STATE', task)
        previous_status = task['status']
        task = published_check_task(connection, task)
        if request.candidate_id is not None:
            candidate = connection.execute(
                'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
                (request.candidate_id, task['id']),
            ).fetchone()
            if candidate is None:
                return Rejection('NOT_FOUND', None)
            if (
                task['status'] != 'VERIFYING'
                or task['current_candidate_id'] != candidate['id']
                or candidate['role'] != task['phase']
                or candidate['control_generation'] != task['control_generation']
            ):
                return start_conflict('VERIFICATION_STAGE_NOT_READY', task)
            from .task_candidate_commit import read_stored_candidate_package

            read_stored_candidate_package(connection, candidate)
        pending = connection.execute(
            """SELECT id FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')
               ORDER BY id LIMIT 1""",
            (task['id'],),
        ).fetchone()
        if pending is not None:
            return start_conflict('OPERATION_CONFLICT', task, pending['id'])
        rejection, session = _capture_inputs(connection, runtime.catalog, task, admissions)
        if rejection == 'CHECK_CONFIGURATION_INVALID':
            return Rejection(
                rejection,
                {'field_errors': [{'field': 'check_set_version_id', 'reason': 'RELATION'}]},
            )
        if rejection is not None:
            return start_conflict(rejection, task)
        return _accept_candidate_check(
            connection, task, session, request, previous_status=previous_status
        )

    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        accept,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def validate_candidate_check_receipt(command, data, status):
    row = exact(
        data, ('task_id', 'operation_id', 'operation_status', 'task_status', 'state_version')
    )
    for key in ('task_id', 'operation_id', 'state_version'):
        strict_integer(row[key], key)
    if (
        status != 202
        or row['operation_status'] != 'PENDING'
        or row['task_status']
        not in (
            ('VERIFYING',)
            if command.route.capability_id == 'APP-CODE-CMD-C51'
            else ('RUNNING', 'VERIFYING')
        )
        or row['task_id'] != command.route.match(command.path)['task_id']
    ):
        raise ValueError('Original candidate check receipt differs')
    return row['task_id']


class CaptureCheckResponse:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    errors = ERRORS | frozenset(
        {
            'INVALID_STATE',
            'TASK_ENDED',
            'VERSION_CONFLICT',
            'OPERATION_CONFLICT',
            'WRITER_ACTIVE',
            'VERIFICATION_STAGE_NOT_READY',
            'CHECK_CONFIGURATION_INVALID',
            'COMMAND_CLOSED',
            'IDEMPOTENCY_CONFLICT',
            'EXTERNAL_RESULT_UNKNOWN',
        }
    )
    status = 202

    @staticmethod
    def project(data, request):
        validate_candidate_check_receipt(request.command, data, 202)
        if data['state_version'] != request.expected_state_version + 1:
            raise ValueError('Original candidate check receipt version differs')
        return data, None


def candidate_check_admissions(request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    if not getattr(worker, 'accepts_candidate_capture', False):
        return ()
    return worker.project_check_admissions


def candidate_check_actions(connection, catalog, task, admissions):
    """Project the same prerequisites used by the write boundary."""
    reasons = {}
    task = published_check_task(connection, task)
    status = task['status']
    if status not in ('RUNNING', 'VERIFYING') or task['stop_requested_at'] is not None:
        return {CAPTURE_TYPE: 'TASK_STATE', VERIFY_TYPE: 'TASK_STATE'}
    try:
        current_role_chain(connection, task)
    except RoleChainUnavailable as error:
        return {CAPTURE_TYPE: error.reason, VERIFY_TYPE: error.reason}
    if not admissions:
        base = 'RESOURCE_NOT_READY'
    else:
        try:
            rejection, _ = _capture_inputs(connection, catalog, task, admissions)
        except ConfigurationNotReady:
            rejection = 'CHECK_CONFIGURATION_INVALID'
        base = {
            None: None,
            'CHECK_CONFIGURATION_INVALID': 'RESOURCE_NOT_READY',
            'CONTENT_NOT_READY': 'RESOURCE_NOT_READY',
            'WRITER_ACTIVE': 'WRITER_ACTIVE',
            'VERIFICATION_STAGE_NOT_READY': 'SESSION_NOT_CURRENT',
        }[rejection]
    reasons[CAPTURE_TYPE] = base
    reasons[VERIFY_TYPE] = (
        base
        if status == 'VERIFYING' and task['current_candidate_id'] is not None
        else 'CANDIDATE_NOT_CURRENT'
        if status == 'VERIFYING'
        else 'TASK_STATE'
    )
    return reasons


@check_write_router.post(CAPTURE)
@check_write_router.post(VERIFY)
async def candidate_check_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    admissions = candidate_check_admissions(request)
    response = await handle_http(
        request,
        CaptureCheckRequest,
        CaptureCheckResponse,
        lambda runtime, parsed: accept_candidate_check(runtime, parsed, admissions=admissions),
    )
    if response.status_code == 202 and worker is not None:
        worker.wake()
    return response
