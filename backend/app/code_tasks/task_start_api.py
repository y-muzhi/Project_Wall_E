"""Public START accepts a version and the original idempotency key."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.validation import decimal_integer, object_fields, strict_integer

from .command_registry import RegisteredCommand, registered_command, validate_registered_success
from .repository_registration_worker import RepositoryRegistrationWorker
from .task_start import START_PATH, accept_task_start

task_start_router = APIRouter(redirect_slashes=False)


def is_task_start_path(path):
    return re.fullmatch(r'/api/v1/code-tasks/[^/]+/start', path) is not None


@dataclass(frozen=True)
class StartTaskRequest:
    task_id: int
    expected_state_version: int
    command: RegisteredCommand
    body_fields = ('expected_state_version',)

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'task_id': self.task_id, 'expected_state_version': self.expected_state_version}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task_id = decimal_integer(request.path_params['task_id'], 'task_id')
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        return cls(
            task_id,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            registered_command(
                'POST',
                START_PATH.format(task_id=task_id),
                idempotency_header(request, lowercase=True),
            ),
        )


class StartTaskResponse:
    error_contract = 'code'
    success_code = 'OPERATION_ACCEPTED'
    status = 202
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'INVALID_STATE',
            'TASK_ENDED',
            'VERSION_CONFLICT',
            'OPERATION_CONFLICT',
            'OPERATION_IN_PROGRESS',
            'EXTERNAL_RESULT_UNKNOWN',
            'EXECUTION_NOT_STOPPED',
            'CONFIG_NOT_READY',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
            'COMMAND_CLOSED',
            'PRECONDITION_FAILED',
        }
    )

    @staticmethod
    def project(data, request):
        validate_registered_success(request.command, data, 'OPERATION_ACCEPTED', 202)
        return data, None


@task_start_router.post(START_PATH)
async def start_task_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)

    def invoke(runtime, parsed):
        return accept_task_start(
            runtime,
            parsed,
            workspace_available=(
                type(worker) is RepositoryRegistrationWorker and worker.accepts_workspace_starts
            ),
        )

    result = await handle_http(request, StartTaskRequest, StartTaskResponse, invoke)
    if result.status_code == 202 and type(worker) is RepositoryRegistrationWorker:
        worker.wake()
    return result
