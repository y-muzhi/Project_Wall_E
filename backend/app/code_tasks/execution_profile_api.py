"""Actual ExecutionProfileVersion HTTP commands and reads on the shared boundary."""

from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Request

from backend.app.shared.code_errors import CAPABILITIES
from backend.app.shared.http_boundary import (
    HTTP_REQUEST_BYTES,
    handle_http,
    idempotency_header,
    request_query,
)
from backend.app.shared.http_projection import exact, page
from backend.app.shared.validation import decimal_integer, reject, strict_boolean, strict_integer

from .command_registry import RegisteredCommand, registered_command
from .configuration_api import CreatedIdentityResponse, IdentityListResponse
from .execution_profile_content import (
    FIELDS,
    ExecutionProfileContent,
    parse_execution_profile_content,
)
from .execution_profile_versions import (
    VERSION_FIELDS,
    list_execution_profile_versions,
    publish_execution_profile_version,
    read_execution_profile_version,
)

execution_profile_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@dataclass(frozen=True)
class PublishExecutionProfileRequest:
    profile_id: int
    content: ExecutionProfileContent
    command: RegisteredCommand
    body_fields = FIELDS

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'profile_id': self.profile_id, **self.content.value()}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        identity = decimal_integer(request.path_params['profile_id'], 'profile_id')
        content = parse_execution_profile_content(body, max_input_bytes=HTTP_REQUEST_BYTES)
        command = registered_command(
            'POST',
            f'/api/v1/code-execution-profiles/{identity}/versions',
            idempotency_header(request, lowercase=True),
        )
        return cls(identity, content, command)


def read_query(request, *, paginated=False):
    if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
        reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取执行配置版本不接收幂等请求头')
    return request_query(request, singles=('page',) if paginated else ())


@dataclass(frozen=True)
class ReadExecutionProfileVersionRequest:
    version_id: int

    @classmethod
    def parse(cls, request):
        read_query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


@dataclass(frozen=True)
class ListExecutionProfileVersionsRequest:
    profile_id: int
    page: int

    @classmethod
    def parse(cls, request):
        query = read_query(request, paginated=True)
        return cls(
            decimal_integer(request.path_params['profile_id'], 'profile_id'),
            decimal_integer(query.get('page', '1'), 'page', 100000),
        )


def project_version(value):
    data = exact(value, VERSION_FIELDS)
    for field in ('id', 'profile_id', 'version'):
        strict_integer(data[field], field)
    content = parse_execution_profile_content(
        {field: data[field] for field in FIELDS},
        max_input_bytes=HTTP_REQUEST_BYTES,
    ).value()
    if any(content[field] != data[field] for field in content):
        raise ValueError('Version content must already be canonical')
    time = data['created_at']
    if (
        type(time) is not str
        or datetime.fromisoformat(time).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        != time
    ):
        raise ValueError('Invalid version timestamp')
    ready = strict_boolean(data['ready'], 'ready')
    codes = data['unresolved_capability_codes']
    if (
        type(codes) is not list
        or any(type(code) is not str or code not in CAPABILITIES for code in codes)
        or len(set(codes)) != len(codes)
        or ready != (not codes)
    ):
        raise ValueError('Invalid execution readiness facts')
    return data


class ExecutionProfileVersionResponse(IdentityListResponse):
    @staticmethod
    def project(data, request):
        result = project_version(data)
        if result['id'] != request.version_id:
            raise ValueError('Version identity differs')
        return result, None


class ExecutionProfileVersionsResponse(IdentityListResponse):
    @staticmethod
    def project(data, request):
        result, pagination = page(data, project_version, request.page)
        order = [(item['version'], item['id']) for item in result['items']]
        if order != sorted(set(order), reverse=True) or any(
            item['profile_id'] != request.profile_id for item in result['items']
        ):
            raise ValueError('Version scope or ordering differs')
        return result, pagination


@execution_profile_router.post('/code-execution-profiles/{profile_id}/versions')
async def publish_http(request: Request):
    return await handle_http(
        request,
        PublishExecutionProfileRequest,
        CreatedIdentityResponse,
        publish_execution_profile_version,
    )


@execution_profile_router.get('/code-execution-profiles/{profile_id}/versions')
async def versions_http(request: Request):
    return await handle_http(
        request,
        ListExecutionProfileVersionsRequest,
        ExecutionProfileVersionsResponse,
        list_execution_profile_versions,
    )


@execution_profile_router.get('/code-execution-profile-versions/{id}')
async def version_http(request: Request):
    return await handle_http(
        request,
        ReadExecutionProfileVersionRequest,
        ExecutionProfileVersionResponse,
        read_execution_profile_version,
    )
