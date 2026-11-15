"""Publish the original eligible Integration candidate for independent Testing."""

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
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
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
from .task_candidate_reads import _available
from .task_candidate_reads import _saved as saved_candidate
from .task_capture_quiescence import current_capture_owner
from .task_role_chain import ROLES, RoleChainUnavailable, current_role_chain
from .task_start import start_conflict
from .task_verification_reads import _saved as saved_verification

PATH = '/api/v1/code-tasks/{task_id}/testing-publication'
CAPABILITY = 'APP-CODE-CMD-C68'
TYPE = 'SUBMIT_FOR_TESTING'
STEPS = operation_steps('CODING', TYPE)
publication_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class PublicationRequest:
    task_id: int
    expected_state_version: int
    candidate_id: int
    verification_id: int
    command: RegisteredCommand
    admissions: tuple

    body_fields = ('expected_state_version', 'candidate_id', 'verification_id')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {field: getattr(self, field) for field in self.body_fields}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task_id = decimal_integer(request.path_params['task_id'], 'task_id')
        fixed = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        worker = getattr(request.app.state, 'walle_repository_registration', None)
        return cls(
            task_id,
            *(strict_integer(fixed[field], field) for field in cls.body_fields),
            registered_command(
                'POST', PATH.format(task_id=task_id), idempotency_header(request, lowercase=True)
            ),
            () if worker is None else worker.project_check_admissions,
        )


def publication_qualification(connection, catalog, task, candidate, verification, admissions):
    if task['status'] != 'VERIFYING' or task['stop_requested_at'] is not None:
        return 'INVALID_STATE', None
    if (
        candidate['id'] != task['current_candidate_id']
        or verification['id'] != task['current_verification_id']
    ):
        return 'TEST_SOURCE_MISMATCH', None
    if candidate['publication_operation_id'] is not None:
        return 'INVALID_STATE', None
    if (
        connection.execute(
            """SELECT 1 FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')
           UNION ALL SELECT 1 FROM code_waiting_items WHERE task_id=? AND status='OPEN' LIMIT 1""",
            (task['id'], task['id']),
        ).fetchone()
        is not None
    ):
        return 'OPERATION_CONFLICT', None
    try:
        chain = current_role_chain(connection, task)
        session, _, window, _ = current_capture_owner(connection, task)
    except RoleChainUnavailable:
        return 'VERIFICATION_STAGE_NOT_READY', None
    except TaskExecutionError:
        return 'OPERATION_CONFLICT', None
    if (
        chain.stages != ROLES
        or candidate['role'] != 'INTEGRATION'
        or candidate['control_generation'] != task['control_generation']
        or session['id'] != chain.session_id
        or window['state'] != 'CLOSED'
    ):
        return 'VERIFICATION_STAGE_NOT_READY', None
    result = saved_verification(connection, catalog, admissions, task, verification)
    if not result['eligible']:
        return (
            'CONFIG_NOT_READY'
            if 'RESOURCE_NOT_READY' in result['ineligibility_reason_codes']
            else 'CHECK_CONFIGURATION_INVALID'
        ), None
    return None, chain


def _persist(connection, task, candidate, verification, chain, request):
    at = max(operation_time(None), task['updated_at'], verification['ended_at'])
    version = increment(task['state_version'])
    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input(request.business_input())
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at,ended_at)
           VALUES(?,?,'TASK',?,?,?,?,?,?,?,'SUCCEEDED',?,?,?)""",
        (
            identity,
            task['id'],
            task['id'],
            chain.session_id,
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
    results = (
        {
            'candidate_id': candidate['id'],
            'verification_id': verification['id'],
            'backend_handoff_operation_id': chain.backend_handoff,
            'frontend_handoff_operation_id': chain.frontend_handoff,
        },
        {'candidate_id': candidate['id']},
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,
           result_ref,started_at,ended_at,last_observed_at)
           VALUES(?,?,?,'SUCCEEDED',?,?,?,?,?)""",
        [
            (identity, number, step, fixed, canonical_input(result), at, at, at)
            for number, (step, result) in enumerate(zip(STEPS, results, strict=True), 1)
        ],
    )
    saved = connection.execute(
        """UPDATE code_candidates SET published_for_testing_at=?,publication_operation_id=?
           WHERE id=? AND task_id=? AND published_for_testing_at IS NULL AND publication_operation_id IS NULL""",
        (at, identity, candidate['id'], task['id']),
    )
    changed = connection.execute(
        """UPDATE code_tasks SET status='AWAITING_TESTING',phase='TESTING',state_version=?,
           updated_at=?,last_observed_at=? WHERE id=? AND status='VERIFYING' AND phase='INTEGRATION'
           AND state_version=? AND current_candidate_id=? AND current_verification_id=?
           AND control_generation=? AND stop_requested_at IS NULL""",
        (
            version,
            at,
            at,
            task['id'],
            task['state_version'],
            candidate['id'],
            verification['id'],
            task['control_generation'],
        ),
    )
    if saved.rowcount != 1 or changed.rowcount != 1:
        raise StorageUnavailable('Original Coding publication changed before commit')
    return Success(
        {
            'code': 'UPDATED',
            'data': {
                'task_id': task['id'],
                'candidate_id': candidate['id'],
                'test_report_id': None,
                'state_version': version,
            },
            'details': None,
        },
        200,
    )


def accept_publication(runtime, request):
    require_schema(runtime)

    def save(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        candidate = connection.execute(
            'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
            (request.candidate_id, request.task_id),
        ).fetchone()
        verification = connection.execute(
            """SELECT * FROM code_verifications WHERE id=? AND task_id=? AND candidate_id=? AND owner_kind='CODING'""",
            (request.verification_id, request.task_id, request.candidate_id),
        ).fetchone()
        if task is None or candidate is None or verification is None:
            return Rejection('NOT_FOUND', None)
        if task['state_version'] != request.expected_state_version:
            return start_conflict('VERSION_CONFLICT', task)
        reason, chain = publication_qualification(
            connection, runtime.catalog, task, candidate, verification, request.admissions
        )
        if reason == 'CONFIG_NOT_READY':
            raise ConfigurationNotReady('Q20-CHECKS')
        if reason is not None:
            return start_conflict(reason, task)
        _, package = saved_candidate(connection, candidate)
        if not _available(package):
            return start_conflict('CONTENT_NOT_READY', task)
        return _persist(connection, task, candidate, verification, chain, request)

    return execute_idempotent(
        runtime.commands(),
        CAPABILITY,
        request,
        save,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
        target_identity=request.command.scope.target_identity,
    )


def validate_publication_receipt(command, value, status):
    data = exact(value, ('task_id', 'candidate_id', 'test_report_id', 'state_version'))
    for field in ('task_id', 'candidate_id', 'state_version'):
        strict_integer(data[field], field)
    if (
        status != 200
        or data['test_report_id'] is not None
        or data['task_id'] != command.route.match(command.path)['task_id']
    ):
        raise ValueError('Original Coding publication receipt differs')
    return data['task_id']


class PublicationResponse:
    error_contract = 'code'
    success_code = 'UPDATED'
    errors = ERRORS | {
        'INVALID_STATE',
        'VERSION_CONFLICT',
        'OPERATION_CONFLICT',
        'BASIS_REF_INVALID',
        'CHECK_CONFIGURATION_INVALID',
        'TEST_REPORT_NOT_ELIGIBLE',
        'TEST_SOURCE_MISMATCH',
        'TEST_ASSET_REVOKED',
        'VERIFICATION_STAGE_NOT_READY',
        'COMMAND_CLOSED',
        'EXTERNAL_RESULT_UNKNOWN',
    }

    @staticmethod
    def project(data, request):
        validate_publication_receipt(request.command, data, 200)
        if data['candidate_id'] != request.candidate_id or data['state_version'] != increment(
            request.expected_state_version
        ):
            raise ValueError('Original publication input differs')
        return data, None


@publication_router.post(PATH)
async def publication_http(request: Request):
    return await handle_http(request, PublicationRequest, PublicationResponse, accept_publication)


def _fixed_publication(value):
    fixed = exact(value, PublicationRequest.body_fields)
    for field in PublicationRequest.body_fields:
        strict_integer(fixed[field], field)
    return fixed


def project_publication_operation(value, operation_id):
    row = exact(value, OPERATION_FIELDS)
    fixed = _fixed_publication(row['fixed_input'])
    for field in ('task_id', 'session_id', 'control_generation'):
        strict_integer(row[field], field)
    registered_command('POST', PATH.format(task_id=row['task_id']), row['idempotency_key'])
    if (
        row['id'] != operation_id
        or row['operation_type'] != TYPE
        or row['status'] != 'SUCCEEDED'
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != row['task_id']
        or row['testing_task_id'] is not None
        or row['failure_code'] is not None
        or row['content_capture'] is not None
        or row['expected_state_version'] != fixed['expected_state_version']
        or type(row['steps']) is not list
        or len(row['steps']) != len(STEPS)
    ):
        raise ValueError('Original Testing publication operation differs')
    at = row['ended_at']
    _time(at, nullable=False)
    if not row['created_at'] == row['started_at'] == at:
        raise ValueError('Original Testing publication chronology differs')
    for index, (source, kind) in enumerate(zip(row['steps'], STEPS, strict=True), 1):
        step = exact(source, STEP_FIELDS)
        fields = (
            (
                'candidate_id',
                'verification_id',
                'backend_handoff_operation_id',
                'frontend_handoff_operation_id',
            )
            if index == 1
            else ('candidate_id',)
        )
        result = exact(step['result_ref'], fields)
        for field in fields:
            strict_integer(result[field], field)
        if (
            step['operation_id'] != row['id']
            or step['step_no'] != index
            or step['step_type'] != kind
            or step['status'] != 'SUCCEEDED'
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
            or not step['started_at'] == step['ended_at'] == step['last_observed_at'] == at
            or result['candidate_id'] != fixed['candidate_id']
            or index == 1
            and (
                result['verification_id'] != fixed['verification_id']
                or result['backend_handoff_operation_id'] >= result['frontend_handoff_operation_id']
            )
        ):
            raise ValueError('Original Testing publication step differs')
    return row


def public_publication_operation(connection, operation):
    fixed = _fixed_publication(strict_json_object(operation['fixed_input']))
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if any(step['fixed_input'] != operation['fixed_input'] for step in steps):
        raise StorageUnavailable('Original Testing publication input differs')
    data = project_publication_operation(
        {
            **dict(operation),
            'fixed_input': fixed,
            'content_capture': None,
            'steps': [
                {
                    **dict(step),
                    'fixed_input': fixed,
                    'result_ref': strict_json_object(step['result_ref']),
                }
                for step in steps
            ],
        },
        operation['id'],
    )
    return data


def read_current_publication(connection, task):
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (task['current_candidate_id'], task['id']),
    ).fetchone()
    if candidate is None or candidate['publication_operation_id'] is None:
        raise StorageUnavailable('Current Coding publication is missing')
    return read_candidate_publication(connection, candidate)


def read_candidate_publication(connection, candidate):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=? AND task_id=? AND operation_type=?',
        (candidate['publication_operation_id'], candidate['task_id'], TYPE),
    ).fetchone()
    if operation is None:
        raise StorageUnavailable('Original Coding publication operation is missing')
    data = public_publication_operation(connection, operation)
    fixed = data['fixed_input']
    refs = data['steps'][0]['result_ref']
    verification = connection.execute(
        """SELECT * FROM code_verifications WHERE id=? AND task_id=? AND candidate_id=?
           AND owner_kind='CODING' AND role='INTEGRATION' AND purpose='HANDOFF'""",
        (fixed['verification_id'], candidate['task_id'], candidate['id']),
    ).fetchone()
    if (
        fixed['candidate_id'] != candidate['id']
        or candidate['role'] != 'INTEGRATION'
        or candidate['published_for_testing_at'] != data['ended_at']
        or verification is None
        or refs['backend_handoff_operation_id'] != verification['backend_handoff_operation_id']
        or refs['frontend_handoff_operation_id'] != verification['frontend_handoff_operation_id']
    ):
        raise StorageUnavailable('Original Coding publication provenance differs')
    return data


def published_check_task(connection, task, *, for_read=False):
    """Use the verified Integration session behind a published task for check admission."""
    phase = {'AWAITING_TESTING': 'TESTING'}
    if for_read:
        phase['AWAITING_ACCEPTANCE'] = 'ACCEPTANCE'
    expected = phase.get(task['status'])
    if expected is None:
        return task
    if task['phase'] != expected:
        raise StorageUnavailable('Published Coding task phase differs')
    read_current_publication(connection, task)
    return {**dict(task), 'status': 'VERIFYING', 'phase': 'INTEGRATION'}


def restore_published_task_after_check(connection, catalog, admissions, claim, *, at):
    task = connection.execute(
        "SELECT * FROM code_tasks WHERE id=? AND status='VERIFYING' AND phase='INTEGRATION'",
        (claim.check.owner_id,),
    ).fetchone()
    if (
        task is None
        or task['stop_requested_at'] is not None
        or task['control_generation'] != claim.check.control_generation
        or task['current_candidate_id'] != claim.check.candidate_id
        or task['current_verification_id'] != claim.check.verification_id
    ):
        return False
    verification = connection.execute(
        """SELECT v.* FROM code_verifications v JOIN code_operations o ON o.id=v.operation_id AND o.task_id=v.task_id
           JOIN code_candidates c ON c.id=v.candidate_id AND c.task_id=v.task_id
           WHERE v.id=? AND v.task_id=? AND o.id=? AND o.operation_type='VERIFY_CANDIDATE'
             AND o.status='SUCCEEDED' AND c.publication_operation_id IS NOT NULL""",
        (claim.check.verification_id, task['id'], claim.scope.operation_id),
    ).fetchone()
    if (
        verification is None
        or not saved_verification(connection, catalog, admissions, task, verification)['eligible']
    ):
        return False
    read_current_publication(connection, task)
    version = increment(task['state_version'])
    observed = max(task['updated_at'], at)
    changed = connection.execute(
        """UPDATE code_tasks SET status='AWAITING_TESTING',phase='TESTING',state_version=?,
           updated_at=?,last_observed_at=? WHERE id=? AND state_version=? AND current_verification_id=?
           AND stop_requested_at IS NULL""",
        (version, observed, observed, task['id'], task['state_version'], verification['id']),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original published Coding check changed before restoration')
    return True
