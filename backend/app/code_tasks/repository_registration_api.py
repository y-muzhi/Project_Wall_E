"""Original repository operations on the public V2 HTTP boundary."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.windows_local_paths import PathBoundaryError, local_absolute_path
from backend.app.shared.http_boundary import (
    HTTP_REQUEST_BYTES,
    handle_http,
    idempotency_header,
    request_query,
)
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    ordinary_text,
    reject,
    strict_integer,
    text_value,
)

from .command_registry import RegisteredCommand, registered_command, validate_registered_success
from .repository_acceptance import accept_repository_operation
from .repository_registration_worker import RepositoryRegistrationWorker

PATH = '/api/v1/code-repositories'
repository_registration_router = APIRouter(redirect_slashes=False)


def is_repository_write_path(path):
    return (
        path == PATH
        or re.fullmatch(r'/api/v1/code-repositories/[^/]+/(?:refresh|snapshots)', path) is not None
    )


@dataclass(frozen=True)
class RegisterRepositoryRequest:
    name: str
    root_path: str
    command: RegisteredCommand
    body_fields = ('name', 'root_path')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'name': self.name, 'root_path': self.root_path}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        name = ordinary_text(fields['name'], 'name', 1, HTTP_REQUEST_BYTES)
        if '\0' in name:
            reject('name', 'INVALID_FORMAT', '名称不能包含空字符')
        root_path = text_value(fields['root_path'], 'root_path')
        try:
            local_absolute_path(root_path)
        except PathBoundaryError:
            reject('root_path', 'INVALID_FORMAT', '必须提供本机绝对目录路径')
        key = idempotency_header(request, lowercase=True)
        return cls(name, root_path, registered_command('POST', PATH, key))


@dataclass(frozen=True)
class RefreshRepositoryRequest:
    repository_id: int
    command: RegisteredCommand
    body_fields = ()

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'repository_id': self.repository_id}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        repository_id = decimal_integer(request.path_params['id'], 'id')
        object_fields(body, 'body', cls.body_fields, cls.body_fields)
        key = idempotency_header(request, lowercase=True)
        command = registered_command('POST', f'{PATH}/{repository_id}/refresh', key)
        return cls(repository_id, command)


@dataclass(frozen=True)
class RegisterBaselineRequest:
    repository_id: int
    commit_oid: str
    execution_profile_version_id: int
    command: RegisteredCommand
    body_fields = ('commit_oid', 'execution_profile_version_id')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {
            'repository_id': self.repository_id,
            'commit_oid': self.commit_oid,
            'execution_profile_version_id': self.execution_profile_version_id,
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        repository_id = decimal_integer(request.path_params['id'], 'id')
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        commit_oid = text_value(fields['commit_oid'], 'commit_oid')
        if re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit_oid) is None or set(
            commit_oid
        ) == {'0'}:
            reject('commit_oid', 'INVALID_FORMAT', '必须提供完整的小写 Git 提交编号')
        profile = strict_integer(
            fields['execution_profile_version_id'], 'execution_profile_version_id'
        )
        key = idempotency_header(request, lowercase=True)
        command = registered_command('POST', f'{PATH}/{repository_id}/snapshots', key)
        return cls(repository_id, commit_oid, profile, command)


class RepositoryAcceptedResponse:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    status = 202
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'CONFIG_NOT_READY',
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
        validate_registered_success(request.command, data, 'OPERATION_ACCEPTED', 202)
        return data, None


async def _accept_http(request, request_type):
    worker = getattr(request.app.state, 'walle_repository_registration', None)

    def accept(runtime, original):
        new_acceptance = False

        def queue_available():
            nonlocal new_acceptance
            new_acceptance = True
            return type(worker) is RepositoryRegistrationWorker and worker.accepting

        result = accept_repository_operation(runtime, original, queue_available=queue_available)
        if result['code'] == 'OPERATION_ACCEPTED' and type(worker) is RepositoryRegistrationWorker:
            if not new_acceptance and request_type is RegisterBaselineRequest and worker.accepting:
                worker.hint_pin_observation(result['data']['operation_id'])
            worker.wake()
        return result

    return await handle_http(request, request_type, RepositoryAcceptedResponse, accept)


@repository_registration_router.post(PATH)
async def register_repository_http(request: Request):
    return await _accept_http(request, RegisterRepositoryRequest)


@repository_registration_router.post(PATH + '/{id}/refresh')
async def refresh_repository_http(request: Request):
    return await _accept_http(request, RefreshRepositoryRequest)


@repository_registration_router.post(PATH + '/{id}/snapshots')
async def register_baseline_http(request: Request):
    return await _accept_http(request, RegisterBaselineRequest)
