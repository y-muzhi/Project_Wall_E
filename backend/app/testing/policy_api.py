"""Strict HTTP boundary for immutable Testing policy and approval records."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.code_tasks.authorization_api import authorization_query
from backend.app.code_tasks.command_registry import RegisteredCommand, registered_command
from backend.app.code_tasks.costs import format_money, parse_money
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import page
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    strict_enum,
    strict_integer,
)

from .policies import (
    create_authorization,
    create_profile,
    list_profiles,
    project_authorization_view,
    project_profile_view,
    read_authorization,
    read_profile,
)
from .policy_content import parse_profile, profile_name

PROFILE_PATH = '/testing-profile-versions'
AUTHORIZATION_PATH = '/testing-authorizations'
testing_policy_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_testing_policy_path(path):
    return (
        re.fullmatch(r'/api/v1/testing-(?:profile-versions|authorizations)(?:/[^/]+)?', path)
        is not None
    )


def _command(request, path):
    return registered_command('POST', '/api/v1' + path, idempotency_header(request, lowercase=True))


@dataclass(frozen=True)
class CreateProfileRequest:
    content: dict
    command: RegisteredCommand
    body_fields = ('profile_content',)

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'profile_content': self.content}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        body = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        return cls(parse_profile(body['profile_content']), _command(request, PROFILE_PATH))


@dataclass(frozen=True)
class CreateAuthorizationRequest:
    profile_version_id: int
    scope_kind: str
    budget_limit_cny: str
    command: RegisteredCommand
    body_fields = ('profile_version_id', 'scope_kind', 'budget_limit_cny')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {field: getattr(self, field) for field in self.body_fields}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        body = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        return cls(
            strict_integer(body['profile_version_id'], 'profile_version_id'),
            strict_enum(body['scope_kind'], 'scope_kind', ('TASK', 'PACK_VALIDATION')),
            format_money(parse_money(body['budget_limit_cny'], 'budget_limit_cny')),
            _command(request, AUTHORIZATION_PATH),
        )


@dataclass(frozen=True)
class ReadPolicyRequest:
    identity: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


@dataclass(frozen=True)
class ListProfilesRequest:
    page: int
    name: str | None

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page', 'name'))
        name = profile_name(query['name']) if 'name' in query else None
        return cls(decimal_integer(query.get('page', '1'), 'page', 100000), name)


class PolicyRead:
    error_contract = 'code'
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'PERMISSION_NOT_GRANTED',
        }
    )


class ProfileRead(PolicyRead):
    @staticmethod
    def project(data, request):
        result = project_profile_view(data)
        if result['id'] != request.identity:
            raise ValueError('Testing profile identity differs')
        return result, None


class ProfilesRead(PolicyRead):
    @staticmethod
    def project(data, request):
        result, pagination = page(data, project_profile_view, request.page)
        order = [item['id'] for item in result['items']]
        if order != sorted(set(order)) or (
            request.name is not None
            and any(item['name'] != request.name for item in result['items'])
        ):
            raise ValueError('Testing profile scope or ordering differs')
        return result, pagination


class AuthorizationRead(PolicyRead):
    @staticmethod
    def project(data, request):
        result = project_authorization_view(data)
        if result['id'] != request.identity:
            raise ValueError('Testing authorization identity differs')
        return result, None


class ProfileCreated(PolicyRead):
    status = 201
    success_code = 'CREATED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'CHECK_CONFIGURATION_INVALID',
    }

    @staticmethod
    def project(data, request):
        result = project_profile_view(data)
        if any(result[field] != value for field, value in request.content.items()):
            raise ValueError('Original Testing profile input differs')
        return result, None


class AuthorizationCreated(ProfileCreated):
    errors = ProfileCreated.errors | {'AUTHORIZATION_NOT_APPLICABLE'}

    @staticmethod
    def project(data, request):
        result = project_authorization_view(data)
        if result['status'] != 'APPROVED_UNBOUND' or any(
            result[field] != value for field, value in request.business_input().items()
        ):
            raise ValueError('Original Testing authorization input differs')
        return result, None


@testing_policy_router.post(PROFILE_PATH)
async def create_profile_http(request: Request):
    return await handle_http(request, CreateProfileRequest, ProfileCreated, create_profile)


@testing_policy_router.get(PROFILE_PATH)
async def list_profiles_http(request: Request):
    return await handle_http(request, ListProfilesRequest, ProfilesRead, list_profiles)


@testing_policy_router.get(PROFILE_PATH + '/{id}')
async def read_profile_http(request: Request):
    return await handle_http(request, ReadPolicyRequest, ProfileRead, read_profile)


@testing_policy_router.post(AUTHORIZATION_PATH)
async def create_authorization_http(request: Request):
    return await handle_http(
        request, CreateAuthorizationRequest, AuthorizationCreated, create_authorization
    )


@testing_policy_router.get(AUTHORIZATION_PATH + '/{id}')
async def read_authorization_http(request: Request):
    return await handle_http(request, ReadPolicyRequest, AuthorizationRead, read_authorization)
