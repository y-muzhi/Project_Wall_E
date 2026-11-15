"""HTTP boundary for fixed independent Testing tasks."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.code_tasks.authorization_api import authorization_query
from backend.app.code_tasks.command_registry import RegisteredCommand, registered_command
from backend.app.code_tasks.costs import format_money, parse_money
from backend.app.code_tasks.verification_case_reads import _project as project_case
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    strict_enum,
    strict_integer,
)

from .planning import DRAFT_PATH, accept_draft
from .policy_api import PolicyRead
from .task_controls import attach_assets, increase_budget
from .task_operations import list_task_operations, project_task_operation, read_task_operation
from .task_recovery import RECONCILE_PATH, RESUME_PATH, accept_recovery
from .task_run import run_testing_task
from .task_stop import STOP_PATH, project_accepted, terminate_task
from .task_views import list_tasks, project_task_summary, project_task_view, read_task
from .tasks import CREATE_FIELDS, PURPOSES, STATUSES, create_task, parse_create_task
from .verification_reads import project_verification, read_cases, read_verification

TASKS = '/testing-tasks'
TASK = TASKS + '/{testing_task_id}'
ASSETS = TASK + '/assets'
RUN = TASK + '/run'
BUDGET = TASK + '/budget'
TASK_OPERATIONS = TASK + '/operations'
VERIFICATION = TASK + '/verifications/{verification_id}'
CASES = VERIFICATION + '/items/{item_id}/cases'
TEST_TASK_ROUTER = APIRouter(redirect_slashes=False)
FILTERS = ('requirement_id', 'document_id', 'status', 'purpose', 'candidate_id', 'snapshot_id')


@dataclass(frozen=True)
class CreateTaskRequest:
    data: dict
    command: RegisteredCommand
    body_fields = CREATE_FIELDS

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return self.data

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        return cls(
            parse_create_task(body),
            registered_command(
                'POST', '/api/v1' + TASKS, idempotency_header(request, lowercase=True)
            ),
        )


@dataclass(frozen=True)
class TaskVersionRequest:
    identity: int
    expected: int
    command: RegisteredCommand
    body_fields = ('expected_state_version',)

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'expected_state_version': self.expected}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = decimal_integer(request.path_params['testing_task_id'], 'testing_task_id')
        return cls(
            identity,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            registered_command(
                'POST',
                '/api/v1' + cls.path.format(testing_task_id=identity),
                idempotency_header(request, lowercase=True),
            ),
        )


class TaskStopRequest(TaskVersionRequest):
    path = STOP_PATH


class DraftTaskRequest(TaskVersionRequest):
    path = DRAFT_PATH


class RunTaskRequest(TaskVersionRequest):
    path = RUN


class RunAccepted(PolicyRead):
    status = 202
    success_code = 'OPERATION_ACCEPTED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'VERSION_CONFLICT',
        'INVALID_STATE',
        'TASK_ENDED',
        'CONFIG_NOT_READY',
        'CONTENT_NOT_READY',
        'TEST_SOURCE_MISMATCH',
        'TEST_ASSET_REVOKED',
        'AUTHORIZATION_NOT_APPLICABLE',
    }

    @staticmethod
    def project(value, request):
        data = project_accepted(value, request.identity)
        if data['state_version'] != request.expected + 1:
            raise ValueError('Original Testing run receipt version differs')
        return data, None


@TEST_TASK_ROUTER.post(DRAFT_PATH)
async def draft_task_http(request: Request):
    response = await handle_http(request, DraftTaskRequest, RunAccepted, accept_draft)
    if response.status_code == 202:
        wake = getattr(request.app.state, 'walle_planning_wake', None)
        if wake is not None:
            wake.set()
    return response


@TEST_TASK_ROUTER.post(RUN)
async def run_task_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    resources = getattr(worker, 'testing_cli_resources', None)
    response = await handle_http(
        request,
        RunTaskRequest,
        RunAccepted,
        lambda runtime, parsed: run_testing_task(runtime, parsed, runtime_resources=resources),
    )
    if response.status_code == 202 and worker is not None:
        worker.wake()
    return response


@dataclass(frozen=True)
class RecoverTaskRequest:
    identity: int
    expected: int
    original_operation: int
    command: RegisteredCommand
    body_fields = ('expected_state_version', 'operation_id')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'expected_state_version': self.expected, 'operation_id': self.original_operation}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = decimal_integer(request.path_params['testing_task_id'], 'testing_task_id')
        return cls(
            identity,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            strict_integer(fields['operation_id'], 'operation_id'),
            registered_command(
                'POST', request.url.path, idempotency_header(request, lowercase=True)
            ),
        )


class RecoveryAccepted(RunAccepted):
    errors = RunAccepted.errors | {'OPERATION_IN_PROGRESS'}

    @staticmethod
    def project(value, request):
        data = project_accepted(value, request.identity)
        if data['state_version'] != request.expected:
            raise ValueError('Original Testing recovery receipt version differs')
        return data, None


@TEST_TASK_ROUTER.post(RESUME_PATH)
@TEST_TASK_ROUTER.post(RECONCILE_PATH)
async def recover_task_http(request: Request):
    action = 'RESUME' if request.url.path.endswith('/resume') else 'RECONCILE'
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    resources = getattr(worker, 'testing_cli_resources', None)
    response = await handle_http(
        request,
        RecoverTaskRequest,
        RecoveryAccepted,
        lambda runtime, parsed: accept_recovery(
            runtime, parsed, action, runtime_resources=resources
        ),
    )
    if response.status_code == 202:
        if worker is not None:
            worker.wake()
        wake = getattr(request.app.state, 'walle_stop_wake', None)
        if wake is not None:
            wake.set()
    return response


@dataclass(frozen=True)
class TaskMutationRequest:
    identity: int
    expected: int
    data: dict
    command: RegisteredCommand

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'expected_state_version': self.expected, **self.data}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = decimal_integer(request.path_params['testing_task_id'], 'testing_task_id')
        return cls(
            identity,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            cls.controls(fields),
            registered_command(
                'POST',
                '/api/v1' + cls.path.format(testing_task_id=identity),
                idempotency_header(request, lowercase=True),
            ),
        )


class AttachTaskRequest(TaskMutationRequest):
    path = ASSETS
    body_fields = ('expected_state_version', 'plan_version_id', 'test_pack_version_id')

    @staticmethod
    def controls(fields):
        return {
            key: strict_integer(fields[key], key)
            for key in ('plan_version_id', 'test_pack_version_id')
        }


class IncreaseBudgetRequest(TaskMutationRequest):
    path = BUDGET
    body_fields = ('expected_state_version', 'new_budget_limit_cny', 'authorization_id')

    @staticmethod
    def controls(fields):
        return {
            'new_budget_limit_cny': format_money(
                parse_money(fields['new_budget_limit_cny'], 'new_budget_limit_cny')
            ),
            'authorization_id': strict_integer(fields['authorization_id'], 'authorization_id'),
        }


@dataclass(frozen=True)
class ReadTaskRequest:
    identity: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(decimal_integer(request.path_params['testing_task_id'], 'testing_task_id'))


@dataclass(frozen=True)
class ListTasksRequest:
    page: int
    filters: dict

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page', *FILTERS))
        selected = {}
        for field in FILTERS:
            if field not in query:
                continue
            if field == 'status':
                selected[field] = strict_enum(query[field], field, STATUSES)
            elif field == 'purpose':
                selected[field] = strict_enum(query[field], field, PURPOSES)
            else:
                selected[field] = decimal_integer(query[field], field)
        return cls(decimal_integer(query.get('page', '1'), 'page', MAX_PAGE), selected)


def project_task_created(value):
    data = exact(value, ('testing_task_id', 'state_version'))
    strict_integer(data['testing_task_id'], 'testing_task_id')
    if strict_integer(data['state_version'], 'state_version') != 1:
        raise ValueError('Original Testing task must start at state version one')
    return data


class TaskCreated(PolicyRead):
    status = 201
    success_code = 'CREATED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'BASIS_REF_INVALID',
        'CONTENT_NOT_READY',
        'AUTHORIZATION_NOT_APPLICABLE',
        'TEST_SOURCE_MISMATCH',
        'TEST_ASSET_REVOKED',
        'INVALID_STATE',
    }

    @staticmethod
    def project(value, request):
        return project_task_created(value), None


class TaskRead(PolicyRead):
    @staticmethod
    def project(value, request):
        return project_task_view(value, request.identity), None


class TaskList(PolicyRead):
    @staticmethod
    def project(value, request):
        data, meta = page(value, project_task_summary, request.page)
        ids = [row['id'] for row in data['items']]
        if ids != sorted(set(ids)) or any(
            row[field] != expected
            for row in data['items']
            for field, expected in request.filters.items()
        ):
            raise ValueError('Original Testing list crosses the fixed query')
        return data, meta


@TEST_TASK_ROUTER.post(TASKS)
async def create_task_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    resources = getattr(worker, 'testing_cli_resources', None)
    return await handle_http(
        request,
        CreateTaskRequest,
        TaskCreated,
        lambda runtime, parsed: create_task(runtime, parsed, runtime_resources=resources),
    )


@TEST_TASK_ROUTER.get(TASKS)
async def list_tasks_http(request: Request):
    return await handle_http(request, ListTasksRequest, TaskList, list_tasks)


@TEST_TASK_ROUTER.get(TASK)
async def read_task_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    resources = getattr(worker, 'testing_cli_resources', None)
    return await handle_http(
        request,
        ReadTaskRequest,
        TaskRead,
        lambda runtime, parsed: read_task(runtime, parsed, runtime_resources=resources),
    )


class TaskTerminated(PolicyRead):
    success_codes = ('OPERATION_ACCEPTED', 'TASK_ALREADY_ENDED')
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'VERSION_CONFLICT',
        'INVALID_STATE',
    }

    @staticmethod
    def project(value, request):
        if 'operation_id' in value:
            return project_accepted(value, request.identity), None
        row = project_task_view(value, request.identity)
        if row['status'] not in ('COMPLETED', 'TERMINATED'):
            raise ValueError('Original Testing task is still active')
        return row, None

    @staticmethod
    def status_for(value):
        return 202 if 'operation_id' in value else 200


@TEST_TASK_ROUTER.post(STOP_PATH)
async def terminate_task_http(request: Request):
    return await handle_http(request, TaskStopRequest, TaskTerminated, terminate_task)


class TaskUpdated(TaskRead):
    success_code = 'UPDATED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'VERSION_CONFLICT',
        'INVALID_STATE',
        'TASK_ENDED',
        'AUTHORIZATION_NOT_APPLICABLE',
        'TEST_SOURCE_MISMATCH',
        'TEST_ASSET_REVOKED',
        'CONTENT_NOT_READY',
        'BUDGET_NOT_INCREASED',
    }


@TEST_TASK_ROUTER.post(ASSETS)
async def attach_assets_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    resources = getattr(worker, 'testing_cli_resources', None)
    return await handle_http(
        request,
        AttachTaskRequest,
        TaskUpdated,
        lambda runtime, parsed: attach_assets(runtime, parsed, runtime_resources=resources),
    )


@TEST_TASK_ROUTER.post(BUDGET)
async def increase_budget_http(request: Request):
    return await handle_http(request, IncreaseBudgetRequest, TaskUpdated, increase_budget)


@dataclass(frozen=True)
class TaskOperationRequest:
    identity: int
    owner: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(
            decimal_integer(request.path_params['operation_id'], 'operation_id'),
            decimal_integer(request.path_params['testing_task_id'], 'testing_task_id'),
        )


@dataclass(frozen=True)
class TaskOperationListRequest:
    owner: int
    page: int

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['testing_task_id'], 'testing_task_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
        )


class TaskOperationRead(PolicyRead):
    @staticmethod
    def project(value, request):
        return project_task_operation(value, request.identity, owner=request.owner), None


class TaskOperationsRead(PolicyRead):
    @staticmethod
    def project(value, request):
        data, meta = page(
            value,
            lambda row: project_task_operation(row, row['id'], owner=request.owner),
            request.page,
        )
        ids = [row['id'] for row in data['items']]
        if ids != sorted(set(ids)):
            raise ValueError('Original Testing operation order differs')
        return data, meta


@TEST_TASK_ROUTER.get(TASK_OPERATIONS)
async def list_task_operations_http(request: Request):
    return await handle_http(
        request,
        TaskOperationListRequest,
        TaskOperationsRead,
        lambda runtime, parsed: list_task_operations(runtime, parsed.owner, parsed.page),
    )


@TEST_TASK_ROUTER.get(TASK_OPERATIONS + '/{operation_id}')
async def read_task_operation_http(request: Request):
    return await handle_http(
        request,
        TaskOperationRequest,
        TaskOperationRead,
        lambda runtime, parsed: read_task_operation(runtime, parsed.identity, owner=parsed.owner),
    )


@dataclass(frozen=True)
class VerificationRequest:
    task: int
    verification: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(
            decimal_integer(request.path_params['testing_task_id'], 'testing_task_id'),
            decimal_integer(request.path_params['verification_id'], 'verification_id'),
        )


@dataclass(frozen=True)
class CasesRequest:
    task: int
    verification: int
    item: int
    page: int

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['testing_task_id'], 'testing_task_id'),
            decimal_integer(request.path_params['verification_id'], 'verification_id'),
            decimal_integer(request.path_params['item_id'], 'item_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
        )


class VerificationRead(PolicyRead):
    @staticmethod
    def project(value, request):
        return project_verification(value, request.task, request.verification), None


class CasesRead(PolicyRead):
    @staticmethod
    def project(value, request):
        data, meta = page(value, project_case, request.page)
        identities = [row['case_id'] for row in data['items']]
        if identities != sorted(set(identities)):
            raise ValueError('Original Testing case ordering differs')
        return data, meta


@TEST_TASK_ROUTER.get(VERIFICATION)
async def read_verification_http(request: Request):
    return await handle_http(request, VerificationRequest, VerificationRead, read_verification)


@TEST_TASK_ROUTER.get(CASES)
async def read_cases_http(request: Request):
    return await handle_http(request, CasesRequest, CasesRead, read_cases)
