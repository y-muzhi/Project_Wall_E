"""Configuration identity commands and nonsecret reads on the existing HTTP boundary."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.code_configuration_catalog import KINDS, option
from backend.app.shared.http_boundary import (
    HTTP_REQUEST_BYTES,
    handle_http,
    idempotency_header,
    request_query,
)
from backend.app.shared.http_projection import page
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    MISSING,
    decimal_integer,
    object_fields,
    ordinary_text,
    reject,
    strict_enum,
)

from .command_registry import RegisteredCommand, registered_command, validate_registered_success
from .configuration_identities import (
    CHECK_SETS,
    EXECUTION_PROFILES,
    IdentityCollection,
    create_identity,
    list_identities,
)
from .configuration_options import list_options

CONFIGURATION_PATHS = frozenset(
    (
        EXECUTION_PROFILES.path,
        CHECK_SETS.path,
        '/api/v1/code-configuration-options',
        '/api/v1/code-authorizations',
    )
)
configuration_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_configuration_path(path):
    return (
        path in CONFIGURATION_PATHS
        or re.fullmatch(
            r'/api/v1/code-(?:check-sets|execution-profiles)/[^/]+/versions|/api/v1/code-(?:check-set|execution-profile)-versions/[^/]+|/api/v1/code-authorizations/[^/]+',
            path,
        )
        is not None
    )


@dataclass(frozen=True)
class CreateIdentityRequest:
    name: str
    command: RegisteredCommand
    collection: IdentityCollection
    body_fields = ('name',)
    target = EXECUTION_PROFILES

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'name': self.name}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        name = ordinary_text(fields['name'], 'name', 1, HTTP_REQUEST_BYTES)
        if '\0' in name:
            reject('name', 'INVALID_FORMAT', '名称不能包含空字符')
        key = idempotency_header(request, lowercase=True)
        command = registered_command('POST', cls.target.path, key)
        return cls(name, command, cls.target)


class CreateCheckSetRequest(CreateIdentityRequest):
    target = CHECK_SETS


@dataclass(frozen=True)
class ListIdentityRequest:
    page: int
    collection: IdentityCollection
    target = EXECUTION_PROFILES

    @classmethod
    def parse(cls, request):
        if any(key.lower() == b'idempotency-key' for key, _ in request.scope.get('headers', [])):
            reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取配置列表不接收幂等请求头')
        query = request_query(request, singles=('page',))
        return cls(decimal_integer(query.get('page', '1'), 'page', 100000), cls.target)


class ListCheckSetRequest(ListIdentityRequest):
    target = CHECK_SETS


def _identity(value, *, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise ValueError('Configuration identity must be a positive safe integer')


class CreatedIdentityResponse:
    error_contract = 'code'
    success_code = 'CREATED'
    status = 201
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'RESOURCE_CONFLICT',
            'SOURCE_CHANGED',
            'SOURCE_BUSY',
            'SOURCE_UNSUPPORTED',
            'REPOSITORY_UNSUPPORTED',
            'CONTENT_NOT_READY',
            'PRECONDITION_FAILED',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'OPERATION_CONFLICT',
            'OPERATION_IN_PROGRESS',
            'COMMAND_CLOSED',
        }
    )

    @staticmethod
    def project(data, request):
        validate_registered_success(request.command, data, 'CREATED', 201)
        return data, None


class IdentityListResponse:
    error_contract = 'code'
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'CONTENT_NOT_READY',
            'CONFIG_NOT_READY',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        if (
            type(data) is not dict
            or set(data) != {'items', 'page', 'page_size', 'total', 'total_pages'}
            or type(data['items']) is not list
            or len(data['items']) > 20
            or data['page'] != request.page
            or data['page_size'] != 20
            or type(data['total']) is not int
            or not 0 <= data['total'] <= MAX_SAFE_INTEGER
            or data['total_pages'] != (data['total'] + 19) // 20
        ):
            raise ValueError('Incomplete configuration identity page')
        seen = set()
        for item in data['items']:
            if type(item) is not dict or set(item) != {'id', 'name', 'latest_version_id'}:
                raise ValueError('Configuration identity projection differs')
            _identity(item['id'])
            _identity(item['latest_version_id'], nullable=True)
            if item['id'] in seen or type(item['name']) is not str or not item['name']:
                raise ValueError('Invalid or duplicate configuration identity row')
            seen.add(item['id'])
        return {'items': data['items']}, {
            key: data[key] for key in ('page', 'page_size', 'total', 'total_pages')
        }


@configuration_router.post('/code-execution-profiles')
async def create_profile_http(request: Request):
    return await handle_http(
        request, CreateIdentityRequest, CreatedIdentityResponse, create_identity
    )


@configuration_router.post('/code-check-sets')
async def create_check_set_http(request: Request):
    return await handle_http(
        request, CreateCheckSetRequest, CreatedIdentityResponse, create_identity
    )


@configuration_router.get('/code-execution-profiles')
async def profiles_http(request: Request):
    return await handle_http(request, ListIdentityRequest, IdentityListResponse, list_identities)


@configuration_router.get('/code-check-sets')
async def check_sets_http(request: Request):
    return await handle_http(request, ListCheckSetRequest, IdentityListResponse, list_identities)


@dataclass(frozen=True)
class ListOptionsRequest:
    kind: str
    page: int

    @classmethod
    def parse(cls, request):
        if any(key.lower() == b'idempotency-key' for key, _ in request.scope.get('headers', [])):
            reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取配置目录不接收幂等请求头')
        query = request_query(request, singles=('kind', 'page'))
        kind = strict_enum(query.get('kind', MISSING), 'kind', KINDS)
        return cls(kind, decimal_integer(query.get('page', '1'), 'page', 100000))


class OptionsResponse(IdentityListResponse):
    @staticmethod
    def project(data, request):
        result, pagination = page(data, option, request.page)
        ids = [entry['option_id'] for entry in result['items']]
        if ids != sorted(set(ids)) or any(
            entry['kind'] != request.kind for entry in result['items']
        ):
            raise ValueError('Configuration options differ from the requested kind or ordering')
        return result, pagination


@configuration_router.get('/code-configuration-options')
async def options_http(request: Request):
    return await handle_http(request, ListOptionsRequest, OptionsResponse, list_options)
