"""Actual CheckSetVersion HTTP commands and reads on the shared boundary."""

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

from .check_set_content import CheckSetContent, parse_check_set_content
from .check_set_versions import (
    VERSION_FIELDS,
    list_check_set_versions,
    publish_check_set_version,
    read_check_set_version,
)
from .command_registry import RegisteredCommand, registered_command
from .configuration_api import CreatedIdentityResponse, IdentityListResponse

check_set_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


@dataclass(frozen=True)
class PublishCheckSetRequest:
    check_set_id: int
    content: CheckSetContent
    command: RegisteredCommand
    body_fields = ('protocol_version', 'items', 'coverage_plan')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'check_set_id': self.check_set_id, **self.content.value()}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        identity = decimal_integer(request.path_params['check_set_id'], 'check_set_id')
        content = parse_check_set_content(
            body, owner_module='CODING', max_input_bytes=HTTP_REQUEST_BYTES
        )
        command = registered_command(
            'POST',
            f'/api/v1/code-check-sets/{identity}/versions',
            idempotency_header(request, lowercase=True),
        )
        return cls(identity, content, command)


def read_query(request, *, paginated=False):
    if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
        reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取检查版本不接收幂等请求头')
    return request_query(request, singles=('page',) if paginated else ())


@dataclass(frozen=True)
class ReadCheckSetVersionRequest:
    version_id: int

    @classmethod
    def parse(cls, request):
        read_query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


@dataclass(frozen=True)
class ListCheckSetVersionsRequest:
    check_set_id: int
    page: int

    @classmethod
    def parse(cls, request):
        query = read_query(request, paginated=True)
        return cls(
            decimal_integer(request.path_params['check_set_id'], 'check_set_id'),
            decimal_integer(query.get('page', '1'), 'page', 100000),
        )


def project_version(value):
    data = exact(value, VERSION_FIELDS)
    for field in ('id', 'check_set_id', 'version'):
        strict_integer(data[field], field)
    content = parse_check_set_content(
        {field: data[field] for field in ('protocol_version', 'items', 'coverage_plan')},
        owner_module=data['owner_module'],
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
        raise ValueError('Invalid check readiness facts')
    return data


class CheckSetVersionResponse(IdentityListResponse):
    @staticmethod
    def project(data, request):
        result = project_version(data)
        if result['id'] != request.version_id:
            raise ValueError('Version identity differs')
        return result, None


class CheckSetVersionsResponse(IdentityListResponse):
    @staticmethod
    def project(data, request):
        result, pagination = page(data, project_version, request.page)
        order = [(item['version'], item['id']) for item in result['items']]
        if order != sorted(set(order), reverse=True) or any(
            item['check_set_id'] != request.check_set_id for item in result['items']
        ):
            raise ValueError('Version scope or ordering differs')
        return result, pagination


@check_set_router.post('/code-check-sets/{check_set_id}/versions')
async def publish_http(request: Request):
    return await handle_http(
        request, PublishCheckSetRequest, CreatedIdentityResponse, publish_check_set_version
    )


@check_set_router.get('/code-check-sets/{check_set_id}/versions')
async def versions_http(request: Request):
    return await handle_http(
        request, ListCheckSetVersionsRequest, CheckSetVersionsResponse, list_check_set_versions
    )


@check_set_router.get('/code-check-set-versions/{id}')
async def version_http(request: Request):
    return await handle_http(
        request, ReadCheckSetVersionRequest, CheckSetVersionResponse, read_check_set_version
    )
