"""Read persisted Coding verification facts without executing a check."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    strict_enum,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .coding_check_plan import CodingCheckPlanError, read_coding_handoff_plan
from .coding_project_check_scope import require_project_check_admissions
from .configuration_identities import require_schema
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_candidate_reads import NOT_FOUND, PATH
from .task_initial_configuration import current_effective_configuration
from .task_read_query import read_task_query
from .task_start_session import original_active_session_scope
from .verification_case_reads import verification_case_router

DETAIL = '/api/v1/code-tasks/{task_id}/verifications/{verification_id}'
LIST = PATH + '/{candidate_id}/verifications'
VERIFICATION_FIELDS = (
    'id',
    'task_id',
    'owner_kind',
    'testing_task_id',
    'candidate_id',
    'snapshot_id',
    'purpose',
    'role',
    'check_set_version_id',
    'profile_version_id',
    'testing_profile_version_id',
    'environment_record_id',
    'operation_id',
    'scope_stages',
    'selected_check_ids',
    'status',
    'stop_status',
    'cleanup_status',
    'source_integrity_status',
    'created_at',
    'ended_at',
    'backend_handoff_operation_id',
    'frontend_handoff_operation_id',
)
ITEM_FIELDS = (
    'id',
    'verification_id',
    'check_id',
    'required',
    'check_kind',
    'evidence_kind',
    'command_execution_id',
    'result',
    'reason_code',
    'expected_case_count',
    'executed_case_count',
    'passed_case_count',
    'failed_case_count',
    'reused_from_item_id',
    'evidence_summary',
    'started_at',
    'ended_at',
)
ENVIRONMENT_FIELDS = (
    'id',
    'task_id',
    'testing_task_id',
    'runtime_refs',
    'dependency_refs',
    'runner_refs',
    'effective_config_application_id',
    'testing_profile_version_id',
    'check_resource_refs',
    'scope_key',
    'observed_at',
)
REASONS = (
    'REQUIRED_NOT_PASSED',
    'VERIFICATION_STAGE_NOT_READY',
    'RESOURCE_NOT_READY',
    'COVERAGE_NOT_READY',
    'NO_CONTROLLED_CASES',
    'CANDIDATE_MISMATCH',
    'CONFIGURATION_MISMATCH',
    'ENVIRONMENT_MISMATCH',
    'RESULT_INCOMPLETE',
    'ACTIVITY_NOT_STOPPED',
    'CLEANUP_NOT_VERIFIED',
    'INPUT_CHANGED',
)
RESULTS = ('NOT_RUN', 'RUNNING', 'PASSED', 'FAILED', 'UNAVAILABLE', 'UNKNOWN', 'CANCELLED')
DIGEST = re.compile('[0-9a-f]{64}')
verification_read_router = APIRouter(redirect_slashes=False)
verification_read_router.include_router(verification_case_router)


def _admissions(request):
    registration = getattr(request.app.state, 'walle_repository_registration', None)
    return () if registration is None else registration.project_check_admissions


@dataclass(frozen=True)
class ListVerificationRequest:
    task_id: int
    candidate_id: int
    purpose: str | None
    page: int
    admissions: tuple

    @classmethod
    def parse(cls, request):
        query = read_task_query(request, singles=('purpose', 'page'))
        purpose = query.get('purpose')
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['candidate_id'], 'candidate_id'),
            None if purpose is None else strict_enum(purpose, 'purpose', ('HANDOFF',)),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
            _admissions(request),
        )


@dataclass(frozen=True)
class ReadVerificationRequest:
    task_id: int
    verification_id: int
    admissions: tuple

    @classmethod
    def parse(cls, request):
        read_task_query(request)
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['verification_id'], 'verification_id'),
            _admissions(request),
        )


def _list(value, *, nonempty=False):
    if (
        type(value) is not list
        or (nonempty and not value)
        or any(type(item) is not str or not item or len(item) > 512 for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError('Original verification reference list differs')
    return value


def _project(data, task_id):
    value = exact(
        data,
        (
            *VERIFICATION_FIELDS,
            'items',
            'environment_record',
            'eligible',
            'ineligibility_reason_codes',
        ),
    )
    for key in (
        'id',
        'candidate_id',
        'check_set_version_id',
        'profile_version_id',
        'environment_record_id',
        'operation_id',
    ):
        strict_integer(value[key], key)
    if (
        value['task_id'] != task_id
        or value['owner_kind'] != 'CODING'
        or value['purpose'] != 'HANDOFF'
        or any(
            value[key] is not None
            for key in ('testing_task_id', 'testing_profile_version_id', 'snapshot_id')
        )
    ):
        raise ValueError('Original Coding verification owner differs')
    _time(value['created_at'], nullable=False)
    _time(value['ended_at'])
    stages = ('BACKEND', 'FRONTEND', 'INTEGRATION')
    role = strict_enum(value['role'], 'role', stages)
    if value['scope_stages'] != list(stages[: stages.index(role) + 1]):
        raise ValueError('Original verification scope differs')
    if (
        type(value['eligible']) is not bool
        or value['eligible'] != (not _list(value['ineligibility_reason_codes']))
        or any(reason not in REASONS for reason in value['ineligibility_reason_codes'])
    ):
        raise ValueError('Original verification eligibility differs')
    selected = _list(value['selected_check_ids'], nonempty=True)
    if (
        type(value['items']) is not list
        or [item['check_id'] for item in value['items']] != selected
    ):
        raise ValueError('Original verification item set differs')
    for item in value['items']:
        exact(item, ITEM_FIELDS)
        strict_integer(item['id'], 'item_id')
        strict_enum(item['result'], 'result', RESULTS)
        if item['verification_id'] != value['id'] or type(item['required']) is not bool:
            raise ValueError('Original verification item owner differs')
        _time(item['started_at'])
        _time(item['ended_at'])
    environment = exact(value['environment_record'], ENVIRONMENT_FIELDS)
    if (
        environment['id'] != value['environment_record_id']
        or environment['task_id'] != task_id
        or environment['testing_task_id'] is not None
        or environment['testing_profile_version_id'] is not None
        or not DIGEST.fullmatch(environment['scope_key'])
    ):
        raise ValueError('Original verification environment differs')
    for key in ('runtime_refs', 'dependency_refs', 'runner_refs', 'check_resource_refs'):
        _list(environment[key])
    _time(environment['observed_at'], nullable=False)
    return value


def _safe_summary(row):
    summary = row['evidence_summary']
    if summary is None:
        return None
    if row['evidence_kind'] != 'PROCESS_EXIT':
        raise StorageUnavailable('Unregistered public verification summary')
    source = strict_json_object(summary)
    integrity = source.pop('source_integrity_status', 'NOT_CHECKED')
    if integrity not in ('NOT_CHECKED', 'VERIFIED', 'CHANGED', 'UNKNOWN'):
        raise StorageUnavailable('Original verification input evidence differs')
    value = exact(source, ('exit_code', 'stdout', 'stderr'))
    if value['exit_code'] is not None:
        strict_integer(value['exit_code'], 'exit_code', minimum=0, maximum=(1 << 32) - 1)
    for field in ('stdout', 'stderr'):
        if value[field] is None:
            continue
        stream = exact(value[field], ('byte_count', 'sha256'))
        strict_integer(stream['byte_count'], 'byte_count', minimum=0)
        if not DIGEST.fullmatch(stream['sha256']):
            raise StorageUnavailable('Original verification output digest differs')
    return canonical_input(value)


def _current_environment(connection, catalog, admissions, task, value, environment):
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (task['active_session_id'], task['id']),
    ).fetchone()
    if session is None or environment['effective_config_application_id'] is None:
        return 'ENVIRONMENT_MISMATCH'
    try:
        scope = original_active_session_scope(connection, task, session)
        applied = current_effective_configuration(connection, task, start_scope=scope)
    except StorageUnavailable:
        return 'ENVIRONMENT_MISMATCH'
    if applied is None or applied['id'] != environment['effective_config_application_id']:
        return 'ENVIRONMENT_MISMATCH'
    try:
        plan = read_coding_handoff_plan(
            connection, catalog, task['id'], value['candidate_id'], comparison_task=task
        )
    except (ConfigInvalid, CodingCheckPlanError):
        return 'RESOURCE_NOT_READY'
    if (
        plan.check_set_version_id != value['check_set_version_id']
        or list(plan.selected_check_ids) != value['selected_check_ids']
        or list(plan.scope_stages) != value['scope_stages']
        or value['backend_handoff_operation_id'] != plan.role_chain.backend_handoff
        or value['frontend_handoff_operation_id'] != plan.role_chain.frontend_handoff
    ):
        return 'CONFIGURATION_MISMATCH'
    try:
        selected = require_project_check_admissions(plan.selection(), admissions)
    except CodingCheckPlanError:
        return 'RESOURCE_NOT_READY'
    runners = [row.admission for row in selected]
    if (
        environment['runtime_refs']
        != list(dict.fromkeys(ref for row in runners for ref in row.runtime_refs))
        or environment['runner_refs'] != list(dict.fromkeys(row.runner_ref for row in runners))
        or environment['check_resource_refs']
        != list(
            dict.fromkeys(
                row.runner_ref + ':sha256:' + row.runner_manifest_sha256 for row in runners
            )
        )
    ):
        return 'RESOURCE_NOT_READY'

    return None


def _eligibility(connection, catalog, admissions, task, value):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=? AND task_id=?',
        (value['operation_id'], task['id']),
    ).fetchone()
    step = connection.execute(
        "SELECT status,result_ref FROM code_operation_steps WHERE operation_id=? AND step_type='CHECK'",
        (value['operation_id'],),
    ).fetchone()
    if (
        operation is None
        or operation['operation_type'] not in ('CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE')
        or step is None
    ):
        raise StorageUnavailable('Original Coding verification operation differs')
    reasons = set()
    if any(item['required'] and item['result'] != 'PASSED' for item in value['items']):
        reasons.add('REQUIRED_NOT_PASSED')
    if task['current_candidate_id'] != value['candidate_id']:
        reasons.add('CANDIDATE_MISMATCH')
    if task['execution_profile_version_id'] != value['profile_version_id']:
        reasons.add('CONFIGURATION_MISMATCH')
    if (
        value['role'] != task['phase']
        or task['status'] != 'VERIFYING'
        or task['stop_requested_at'] is not None
        or task['control_generation'] != operation['control_generation']
    ):
        reasons.add('VERIFICATION_STAGE_NOT_READY')
    if (
        value['status'] != 'FINISHED'
        or operation['status'] != 'SUCCEEDED'
        or step['status'] != 'SUCCEEDED'
        or strict_json_object(step['result_ref']) != {'verification_id': value['id']}
    ):
        reasons.add('RESULT_INCOMPLETE')
    if value['stop_status'] != 'VERIFIED':
        reasons.add('ACTIVITY_NOT_STOPPED')
    if value['cleanup_status'] != 'VERIFIED':
        reasons.add('CLEANUP_NOT_VERIFIED')
    if value['source_integrity_status'] == 'CHANGED':
        reasons.add('INPUT_CHANGED')
    elif value['source_integrity_status'] != 'VERIFIED':
        reasons.add('RESULT_INCOMPLETE')
    if not reasons.intersection(
        {'VERIFICATION_STAGE_NOT_READY', 'CANDIDATE_MISMATCH', 'CONFIGURATION_MISMATCH'}
    ):
        reason = _current_environment(
            connection, catalog, admissions, task, value, value['environment_record']
        )
        if reason is not None:
            reasons.add(reason)
    return [reason for reason in REASONS if reason in reasons]


def _saved(connection, catalog, admissions, task, row):
    data = {key: row[key] for key in VERIFICATION_FIELDS}
    for key in ('scope_stages', 'selected_check_ids'):
        data[key] = strict_json_loads(data[key])
    environment = connection.execute(
        'SELECT * FROM code_environment_records WHERE id=? AND task_id=?',
        (row['environment_record_id'], task['id']),
    ).fetchone()
    if environment is None:
        raise StorageUnavailable('Original Coding verification environment is missing')
    record = {key: environment[key] for key in ENVIRONMENT_FIELDS}
    for key in ('runtime_refs', 'dependency_refs', 'runner_refs', 'check_resource_refs'):
        record[key] = strict_json_loads(record[key])
    rows = connection.execute(
        'SELECT * FROM code_verification_items WHERE verification_id=? ORDER BY id',
        (row['id'],),
    ).fetchall()
    items = []
    for item in rows:
        if item['required'] not in (0, 1):
            raise StorageUnavailable('Original verification item required flag differs')
        items.append(
            {
                **{key: item[key] for key in ITEM_FIELDS},
                'required': bool(item['required']),
                'evidence_summary': _safe_summary(item),
            }
        )
    data.update(items=items, environment_record=record)
    comparison_task = task
    if (
        task['status'] in ('AWAITING_TESTING', 'AWAITING_ACCEPTANCE')
        and task['current_candidate_id'] == row['candidate_id']
    ):
        from .task_testing_publication import published_check_task

        comparison_task = published_check_task(connection, task, for_read=True)
    reasons = _eligibility(connection, catalog, admissions, comparison_task, data)
    data.update(eligible=not reasons, ineligibility_reason_codes=reasons)
    return _project(data, task['id'])


def list_verifications(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if (
            task is None
            or connection.execute(
                'SELECT 1 FROM code_candidates WHERE id=? AND task_id=?',
                (request.candidate_id, request.task_id),
            ).fetchone()
            is None
        ):
            return NOT_FOUND
        scope = (request.task_id, request.candidate_id, request.purpose, request.purpose)
        predicate = (
            "task_id=? AND candidate_id=? AND owner_kind='CODING' AND (? IS NULL OR purpose=?)"
        )
        total = connection.execute(
            f'SELECT count(*) FROM code_verifications WHERE {predicate}', scope
        ).fetchone()[0]
        rows = connection.execute(
            f"""SELECT * FROM code_verifications WHERE {predicate}
                ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?""",
            (*scope, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        data = {
            **page_metadata(request.page, total),
            'items': [
                _saved(connection, runtime.catalog, request.admissions, task, row) for row in rows
            ],
        }
    return {'code': 'READ_OK', 'data': data, 'details': None}


def read_verification(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        row = connection.execute(
            "SELECT * FROM code_verifications WHERE id=? AND task_id=? AND owner_kind='CODING'",
            (request.verification_id, request.task_id),
        ).fetchone()
        if task is None or row is None:
            return NOT_FOUND
        data = _saved(connection, runtime.catalog, request.admissions, task, row)
    return {'code': 'READ_OK', 'data': data, 'details': None}


class VerificationListResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        return page(data, lambda item: _project(item, request.task_id), request.page)


class VerificationResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        value = _project(data, request.task_id)
        if value['id'] != request.verification_id:
            raise ValueError('Original verification identity differs')
        return value, None


@verification_read_router.get(LIST)
async def list_verifications_http(request: Request):
    return await handle_http(
        request, ListVerificationRequest, VerificationListResponse, list_verifications
    )


@verification_read_router.get(DETAIL)
async def read_verification_http(request: Request):
    return await handle_http(
        request, ReadVerificationRequest, VerificationResponse, read_verification
    )
