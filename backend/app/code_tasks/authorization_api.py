"""Approval and exact authorization reads on the existing native HTTP boundary."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.http_boundary import (
    HTTP_REQUEST_BYTES,
    handle_http,
    idempotency_header,
    request_query,
)
from backend.app.shared.http_projection import exact, page
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    reject,
    strict_enum,
    strict_integer,
)

from .authorization_scope import STATUSES, AuthorizationScope, parse_authorization_scope
from .authorizations import (
    FIELDS,
    approve_authorization,
    list_authorizations,
    project_grant,
    read_authorization,
)
from .command_registry import RegisteredCommand, registered_command
from .configuration_api import CreatedIdentityResponse, IdentityListResponse

authorization_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def authorization_query(request, *, singles=()):
    if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
        reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取授权不接收幂等请求头')
    return request_query(request, singles=singles)


@dataclass(frozen=True)
class ApproveAuthorizationRequest:
    profile_version_id: int
    scope: AuthorizationScope
    command: RegisteredCommand
    body_fields = ('profile_version_id', 'scope')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'profile_version_id': self.profile_version_id, 'scope': self.scope.value()}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        body = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = strict_integer(body['profile_version_id'], 'profile_version_id')
        scope = parse_authorization_scope(body['scope'], max_input_bytes=HTTP_REQUEST_BYTES)
        command = registered_command(
            'POST', '/api/v1/code-authorizations', idempotency_header(request, lowercase=True)
        )
        return cls(identity, scope, command)


@dataclass(frozen=True)
class ReadAuthorizationRequest:
    authorization_id: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


@dataclass(frozen=True)
class ListAuthorizationsRequest:
    page: int
    task_id: int | None
    status: str | None

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page', 'task_id', 'status'))
        return cls(
            decimal_integer(query.get('page', '1'), 'page', 100000),
            decimal_integer(query['task_id'], 'task_id') if 'task_id' in query else None,
            strict_enum(query['status'], 'status', STATUSES) if 'status' in query else None,
        )


def public_grant(value):
    data = exact(value, FIELDS)
    result = project_grant({**data, 'scope': compact(data['scope'])})
    if result != data:
        raise ValueError('Authorization projection differs')
    return result


class AuthorizationResponse(IdentityListResponse):
    @staticmethod
    def project(data, request):
        result = public_grant(data)
        if result['id'] != request.authorization_id:
            raise ValueError('Authorization identity differs')
        return result, None


class AuthorizationsResponse(IdentityListResponse):
    @staticmethod
    def project(data, request):
        result, pagination = page(data, public_grant, request.page)
        order = [(item['approved_at'], item['id']) for item in result['items']]
        if order != sorted(set(order), reverse=True):
            raise ValueError('Authorization ordering differs')
        for item in result['items']:
            if (request.task_id is not None and item['task_id'] != request.task_id) or (
                request.status is not None and item['status'] != request.status
            ):
                raise ValueError('Authorization filter differs')
        return result, pagination


@authorization_router.post('/code-authorizations')
async def approve_http(request: Request):
    return await handle_http(
        request, ApproveAuthorizationRequest, CreatedIdentityResponse, approve_authorization
    )


@authorization_router.get('/code-authorizations')
async def authorizations_http(request: Request):
    return await handle_http(
        request, ListAuthorizationsRequest, AuthorizationsResponse, list_authorizations
    )


@authorization_router.get('/code-authorizations/{id}')
async def authorization_http(request: Request):
    return await handle_http(
        request, ReadAuthorizationRequest, AuthorizationResponse, read_authorization
    )
