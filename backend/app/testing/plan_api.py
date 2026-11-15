"""Native Testing plan HTTP boundaries and original response projection."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.code_tasks.authorization_api import authorization_query
from backend.app.code_tasks.command_registry import RegisteredCommand, registered_command
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    ordinary_text,
    strict_integer,
)

from .asset_api import TEST_ASSET_ROUTER
from .plan_content import parse_plan_content
from .plans import (
    create_plan,
    create_version,
    list_plans,
    list_versions,
    plan_name,
    project_plan,
    project_version,
    publish_plan,
    read_plan,
    read_version,
    revoke_plan,
    save_draft,
)
from .policy_api import PolicyRead
from .report_api import TEST_REPORT_ROUTER
from .task_api import TEST_TASK_ROUTER
from .usage_api import TEST_USAGE_ROUTER

PLAN_PATH = '/test-plans'
VERSION_PATH = '/test-plan-versions'
TEST_PLAN_ROUTER = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_testing_plan_path(path):
    return (
        re.fullmatch(
            r'/api/v1/(?:test-plans(?:/[^/]+(?:/versions)?)?|test-plan-versions/[^/]+(?:/(?:draft|publish|revoke|packs))?|test-pack-versions/[^/]+(?:/(?:seal|revoke|validations|publish))?|test-pack-validations/[^/]+|testing-operations/[^/]+|testing-reference-sets|test-reports/[^/]+(?:/findings)?|testing-findings/[^/]+/review|testing-tasks(?:/[^/]+(?:/(?:terminate|assets|run|budget|report|model-calls(?:/[^/]+)?|operations(?:/[^/]+)?|verifications/[^/]+(?:/items/[^/]+/cases)?))?)?)',
            path,
        )
        is not None
    )


@dataclass(frozen=True)
class CreatePlanRequest:
    name: str
    command: RegisteredCommand
    body_fields = ('name',)

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'name': self.name}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        return cls(
            plan_name(fields['name']),
            registered_command(
                'POST', '/api/v1' + PLAN_PATH, idempotency_header(request, lowercase=True)
            ),
        )


@dataclass(frozen=True)
class VersionWriteRequest:
    identity: int
    command: RegisteredCommand
    content: dict | None
    expected: int | None
    reason: str | None
    path = PLAN_PATH + '/{id}/versions'
    body_fields = ('plan_content',)

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        fields = {
            'plan_content': self.content,
            'expected_state_version': self.expected,
            'reason': self.reason,
        }
        return {field: fields[field] for field in self.body_fields}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        identity = decimal_integer(request.path_params['id'], 'id')
        body = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        content = parse_plan_content(body['plan_content']) if 'plan_content' in body else None
        expected = (
            strict_integer(body['expected_state_version'], 'expected_state_version')
            if 'expected_state_version' in body
            else None
        )
        reason = ordinary_text(body['reason'], 'reason', 1, 2000) if 'reason' in body else None
        return cls(
            identity,
            registered_command(
                'POST',
                '/api/v1' + cls.path.format(id=identity),
                idempotency_header(request, lowercase=True),
            ),
            content,
            expected,
            reason,
        )


class SaveDraftRequest(VersionWriteRequest):
    path = VERSION_PATH + '/{id}/draft'
    body_fields = ('expected_state_version', 'plan_content')


class PublishRequest(VersionWriteRequest):
    path = VERSION_PATH + '/{id}/publish'
    body_fields = ('expected_state_version',)


class RevokeRequest(VersionWriteRequest):
    path = VERSION_PATH + '/{id}/revoke'
    body_fields = ('expected_state_version', 'reason')


@dataclass(frozen=True)
class PlanReadRequest:
    identity: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


@dataclass(frozen=True)
class PlansRequest:
    page: int
    requirement_id: int | None

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page', 'requirement_id'))
        return cls(
            decimal_integer(query.get('page', '1'), 'page', 100000),
            decimal_integer(query['requirement_id'], 'requirement_id')
            if 'requirement_id' in query
            else None,
        )


@dataclass(frozen=True)
class VersionsRequest:
    identity: int
    page: int

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['id'], 'id'),
            decimal_integer(query.get('page', '1'), 'page', 100000),
        )


def _scoped(data, request, project):
    result = project(data)
    if result['id'] != request.identity:
        raise ValueError('Original Testing plan identity differs')
    return result, None


class PlanRead(PolicyRead):
    @staticmethod
    def project(data, request):
        return _scoped(data, request, project_plan)


class VersionRead(PolicyRead):
    @staticmethod
    def project(data, request):
        return _scoped(data, request, project_version)


def _ordered(data, request, project):
    value, meta = page(data, project, request.page)
    ids = [row['id'] for row in value['items']]
    if ids != sorted(set(ids)):
        raise ValueError('Original Testing plan page is unordered')
    return value, meta


class PlansRead(PolicyRead):
    @staticmethod
    def project(data, request):
        return _ordered(data, request, project_plan)


class VersionsRead(PolicyRead):
    @staticmethod
    def project(data, request):
        value, meta = _ordered(data, request, project_version)
        if any(row['plan_id'] != request.identity for row in value['items']):
            raise ValueError('Original Testing versions cross plan scope')
        return value, meta


_MUTATION_ERRORS = PolicyRead.errors | {'OPERATION_CONFLICT', 'COMMAND_CLOSED'}
_CAS_ERRORS = _MUTATION_ERRORS | {'VERSION_CONFLICT', 'INVALID_STATE'}
_BASIS_ERRORS = {'BASIS_REF_INVALID'}


class PlanCreated(PolicyRead):
    errors = _MUTATION_ERRORS
    status = 201
    success_code = 'CREATED'

    @staticmethod
    def project(data, request):
        return project_plan_receipt(request.command, data, 201), None


class VersionCreated(PlanCreated):
    errors = _MUTATION_ERRORS | _BASIS_ERRORS

    @staticmethod
    def project(data, request):
        value = project_plan_receipt(request.command, data, 201)
        if any(value[field] != item for field, item in request.content.items()):
            raise ValueError('Original Testing draft content differs')
        return value, None


class VersionUpdated(PolicyRead):
    status = 200
    success_code = 'UPDATED'
    errors = _CAS_ERRORS | _BASIS_ERRORS

    @staticmethod
    def project(data, request):
        value = project_plan_receipt(request.command, data, 200)
        if (
            value['state_version'] != request.expected + 1
            or (
                request.content is not None
                and any(value[field] != item for field, item in request.content.items())
            )
            or (request.reason is not None and request.reason != value['revocation_reason'])
        ):
            raise ValueError('Original Testing plan control differs')
        return value, None


class PlanPublished(VersionUpdated):
    errors = VersionUpdated.errors | {'CHECK_CONFIGURATION_INVALID'}


class PlanRevoked(VersionUpdated):
    errors = _CAS_ERRORS


_COMMANDS = {
    'APP-TEST-CMD-C06': (PlanCreated, None),
    'APP-TEST-CMD-C09': (VersionCreated, 'DRAFT'),
    'APP-TEST-CMD-C12': (VersionUpdated, 'DRAFT'),
    'APP-TEST-CMD-C13': (PlanPublished, 'PUBLISHED'),
    'APP-TEST-CMD-C14': (PlanRevoked, 'REVOKED'),
}


def plan_command_errors(command):
    response, _ = _COMMANDS[command.route.capability_id]
    return response.errors


def project_plan_receipt(command, data, status):
    response, state = _COMMANDS[command.route.capability_id]
    if status != response.status:
        raise ValueError('Original Testing plan status differs')
    scope = command.route.match(command.path)
    if state is None:
        result = exact(data, ('plan_id',))
        strict_integer(result['plan_id'], 'plan_id')
        return result
    result = project_version(data)
    if result['status'] != state:
        raise ValueError('Original Testing plan state differs')
    if command.route.capability_id == 'APP-TEST-CMD-C09':
        if result['plan_id'] != scope['plan_id'] or result['state_version'] != 1:
            raise ValueError('Original Testing plan parent differs')
    elif result['id'] != scope['id']:
        raise ValueError('Original Testing plan version differs')
    return result


@TEST_PLAN_ROUTER.post(PLAN_PATH)
async def create_plan_http(request: Request):
    return await handle_http(request, CreatePlanRequest, PlanCreated, create_plan)


@TEST_PLAN_ROUTER.get(PLAN_PATH)
async def list_plans_http(request: Request):
    return await handle_http(request, PlansRequest, PlansRead, list_plans)


@TEST_PLAN_ROUTER.get(PLAN_PATH + '/{id}')
async def read_plan_http(request: Request):
    return await handle_http(request, PlanReadRequest, PlanRead, read_plan)


@TEST_PLAN_ROUTER.post(PLAN_PATH + '/{id}/versions')
async def create_version_http(request: Request):
    return await handle_http(request, VersionWriteRequest, VersionCreated, create_version)


@TEST_PLAN_ROUTER.get(PLAN_PATH + '/{id}/versions')
async def list_versions_http(request: Request):
    return await handle_http(request, VersionsRequest, VersionsRead, list_versions)


@TEST_PLAN_ROUTER.get(VERSION_PATH + '/{id}')
async def read_version_http(request: Request):
    return await handle_http(request, PlanReadRequest, VersionRead, read_version)


@TEST_PLAN_ROUTER.post(VERSION_PATH + '/{id}/draft')
async def save_draft_http(request: Request):
    return await handle_http(request, SaveDraftRequest, VersionUpdated, save_draft)


@TEST_PLAN_ROUTER.post(VERSION_PATH + '/{id}/publish')
async def publish_http(request: Request):
    return await handle_http(request, PublishRequest, PlanPublished, publish_plan)


@TEST_PLAN_ROUTER.post(VERSION_PATH + '/{id}/revoke')
async def revoke_http(request: Request):
    return await handle_http(request, RevokeRequest, PlanRevoked, revoke_plan)


TEST_PLAN_ROUTER.include_router(TEST_ASSET_ROUTER)
TEST_PLAN_ROUTER.include_router(TEST_TASK_ROUTER)
TEST_PLAN_ROUTER.include_router(TEST_REPORT_ROUTER)
TEST_PLAN_ROUTER.include_router(TEST_USAGE_ROUTER)
