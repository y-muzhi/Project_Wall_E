"""Task-scoped read-only views of original Coding operations (API42 and API43)."""

from dataclasses import dataclass
from itertools import pairwise

from fastapi import APIRouter, Request

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.command_execution import ConfigurationNotReady
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import decimal_integer

from .configuration_identities import require_schema
from .repository_reads import ERRORS
from .task_read_query import read_task_query

LIST = '/api/v1/code-tasks/{task_id}/operations'
DETAIL = LIST + '/{operation_id}'
task_operation_router = APIRouter(redirect_slashes=False)
TASK_OPERATION_TYPES = (
    'START',
    'RESUME',
    'TERMINATE',
    'ANSWER_QUESTION',
    'DECIDE_PERMISSION',
    'PREPARE_HANDOFF',
    'APPLY_CONFIGURATION',
    'CAPTURE_AND_CHECK',
    'VERIFY_CANDIDATE',
    'HANDOFF_ROLE',
    'SUBMIT_FOR_TESTING',
    'LINK_TEST_REPORT',
    'REPAIR',
    'PREPARE_DELIVERY',
    'DELIVER',
    'RECONCILE',
)
_NOT_FOUND = {'code': 'NOT_FOUND', 'data': None, 'details': None}


def public_task_operation(connection, row):
    if row['operation_type'] == 'APPLY_CONFIGURATION':
        from .task_configuration_progress import public_configuration_operation

        return public_configuration_operation(connection, row)
    if row['operation_type'] == 'START':
        from .task_start_view import public_start_operation

        return public_start_operation(connection, row)
    if row['operation_type'] == 'RESUME':
        from .task_resume_view import public_resume_operation

        return public_resume_operation(connection, row)
    if row['operation_type'] == 'ANSWER_QUESTION':
        from .task_question_response import public_question_response

        return public_question_response(connection, row)
    if row['operation_type'] == 'DECIDE_PERMISSION':
        from .task_permission_response import public_permission_response

        return public_permission_response(connection, row)
    if row['operation_type'] == 'PREPARE_HANDOFF':
        from .task_question_handoff import public_handoff_operation

        return public_handoff_operation(connection, row)
    if row['operation_type'] == 'CAPTURE_AND_CHECK':
        from .task_capture_operation_view import public_capture_operation

        return public_capture_operation(connection, row)
    if row['operation_type'] == 'VERIFY_CANDIDATE':
        from .task_verify_candidate import public_verify_candidate

        return public_verify_candidate(connection, row)
    if row['operation_type'] == 'HANDOFF_ROLE':
        from .task_role_view import public_role_operation

        return public_role_operation(connection, row)
    if row['operation_type'] == 'RECONCILE':
        from .task_role_reconciliation import public_reconciliation_operation

        return public_reconciliation_operation(connection, row)
    if row['operation_type'] == 'SUBMIT_FOR_TESTING':
        from .task_testing_publication import public_publication_operation

        return public_publication_operation(connection, row)
    if row['operation_type'] == 'LINK_TEST_REPORT':
        from .task_report_link import read_link_operation

        return read_link_operation(connection, row)
    if row['operation_type'] in ('PREPARE_DELIVERY', 'DELIVER'):
        from .task_delivery_api import public_delivery_operation

        return public_delivery_operation(connection, row)
    if row['operation_type'] == 'REPAIR':
        from .task_repairs import public_repair_operation

        return public_repair_operation(connection, row)
    if row['operation_type'] == 'TERMINATE':
        from .task_stop import public_stop_operation

        return public_stop_operation(connection, row)
    raise ConfigurationNotReady('RUNTIME')


def project_task_operation(data, operation_id):
    if data['operation_type'] == 'APPLY_CONFIGURATION':
        from .task_configuration_progress import project_configuration_operation

        return project_configuration_operation(data, operation_id)
    if data['operation_type'] == 'START':
        from .task_start_view import project_start_operation

        return project_start_operation(data, operation_id)
    if data['operation_type'] == 'RESUME':
        from .task_resume_view import project_resume_operation

        return project_resume_operation(data, operation_id)
    if data['operation_type'] == 'ANSWER_QUESTION':
        from .task_question_response import project_question_response

        return project_question_response(data, operation_id)
    if data['operation_type'] == 'DECIDE_PERMISSION':
        from .task_permission_response import project_permission_response

        return project_permission_response(data, operation_id)
    if data['operation_type'] == 'PREPARE_HANDOFF':
        from .task_question_handoff import project_handoff_operation

        return project_handoff_operation(data, operation_id)
    if data['operation_type'] == 'CAPTURE_AND_CHECK':
        from .task_capture_operation_view import project_capture_operation

        return project_capture_operation(data, operation_id)
    if data['operation_type'] == 'VERIFY_CANDIDATE':
        from .task_verify_candidate import project_verify_candidate

        return project_verify_candidate(data, operation_id)
    if data['operation_type'] == 'HANDOFF_ROLE':
        from .task_role_view import project_role_operation

        return project_role_operation(data, operation_id)
    if data['operation_type'] == 'RECONCILE':
        from .task_role_reconciliation import project_reconciliation_operation

        return project_reconciliation_operation(data, operation_id)
    if data['operation_type'] == 'SUBMIT_FOR_TESTING':
        from .task_testing_publication import project_publication_operation

        return project_publication_operation(data, operation_id)
    if data['operation_type'] == 'LINK_TEST_REPORT':
        from .task_report_link import project_link_operation

        return project_link_operation(data, operation_id)
    if data['operation_type'] in ('PREPARE_DELIVERY', 'DELIVER'):
        from .task_delivery_api import project_delivery_operation

        return project_delivery_operation(data, operation_id)
    if data['operation_type'] == 'REPAIR':
        from .task_repairs import project_repair_operation

        return project_repair_operation(data, operation_id)
    if data['operation_type'] == 'TERMINATE':
        from .task_stop import project_stop_operation

        return project_stop_operation(data, operation_id)
    raise ValueError('Original Coding operation type is not implemented')


@dataclass(frozen=True)
class OperationsRequest:
    task_id: int
    page: int

    @classmethod
    def parse(cls, request):
        query = read_task_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(query.get('page', '1'), 'page', maximum=MAX_PAGE),
        )


@dataclass(frozen=True)
class OperationRequest:
    task_id: int
    operation_id: int

    @classmethod
    def parse(cls, request):
        read_task_query(request)
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['operation_id'], 'operation_id'),
        )


_SCOPE = "FROM code_operations WHERE task_id=? AND resource_kind='TASK' AND resource_id=task_id"


def _read_result(action):
    try:
        value = action()
    except ConfigurationNotReady as error:
        return {'code': error.code, 'data': None, 'details': error.details}
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise StorageUnavailable('Original Coding operation history differs') from error
    return _NOT_FOUND if value is None else {'code': 'READ_OK', 'data': value, 'details': None}


def list_operations(runtime, request):
    require_schema(runtime)

    def read():
        with runtime.database.transaction() as connection:
            if (
                connection.execute(
                    'SELECT 1 FROM code_tasks WHERE id=?', (request.task_id,)
                ).fetchone()
                is None
            ):
                return None
            total = connection.execute('SELECT count(*) ' + _SCOPE, (request.task_id,)).fetchone()[
                0
            ]
            rows = connection.execute(
                'SELECT * ' + _SCOPE + ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                (request.task_id, PAGE_SIZE, page_offset(request.page)),
            )
            return {
                **page_metadata(request.page, total),
                'items': [public_task_operation(connection, row) for row in rows],
            }

    return _read_result(read)


def read_operation(runtime, request):
    require_schema(runtime)

    def read():
        with runtime.database.transaction() as connection:
            row = connection.execute(
                'SELECT * ' + _SCOPE + ' AND id=?',
                (request.task_id, request.operation_id),
            ).fetchone()
            return None if row is None else public_task_operation(connection, row)

    return _read_result(read)


class OperationsResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        def item(row):
            if row['task_id'] != request.task_id:
                raise ValueError('History row crosses Coding task scope')
            return project_task_operation(row, row['id'])

        result, metadata = page(data, item, request.page)
        keys = [(row['created_at'], row['id']) for row in result['items']]
        if any(left <= right for left, right in pairwise(keys)):
            raise ValueError('Original Coding operation history order differs')
        return result, metadata


class OperationResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        if data['task_id'] != request.task_id:
            raise ValueError('Original operation crosses Coding task scope')
        return project_task_operation(data, request.operation_id), None


@task_operation_router.get(LIST)
async def list_task_operations_http(request: Request):
    return await handle_http(request, OperationsRequest, OperationsResponse, list_operations)


@task_operation_router.get(DETAIL)
async def read_task_operation_http(request: Request):
    return await handle_http(request, OperationRequest, OperationResponse, read_operation)
