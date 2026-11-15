"""Public original Coding termination boundary."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    reject,
    strict_integer,
    text_value,
)

from .command_registry import RegisteredCommand, registered_command, validate_registered_success
from .task_stop import STOP_PATH, accept_task_stop

task_stop_router = APIRouter(redirect_slashes=False)


def is_task_stop_path(path):
    return re.fullmatch(r'/api/v1/code-tasks/[^/]+/terminate', path) is not None


@dataclass(frozen=True)
class StopTaskRequest:
    task_id: int
    expected_state_version: int
    reason: str | None
    command: RegisteredCommand
    body_fields = ('expected_state_version', 'reason')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        result = {'task_id': self.task_id, 'expected_state_version': self.expected_state_version}
        if self.reason is not None:
            result['reason'] = self.reason
        return result

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task_id = decimal_integer(request.path_params['task_id'], 'task_id')
        fields = object_fields(body, 'body', cls.body_fields, ('expected_state_version',))
        reason = None
        if 'reason' in fields:
            reason = text_value(fields['reason'], 'reason')
            if not reason.strip():
                reject('reason', 'TOO_SHORT', '停止说明必须为非空文本')
        key = idempotency_header(request, lowercase=True)
        return cls(
            task_id,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            reason,
            registered_command('POST', STOP_PATH.format(task_id=task_id), key),
        )


class StopTaskResponse:
    error_contract = 'code'
    success_codes = ('OPERATION_ACCEPTED', 'TASK_ALREADY_ENDED')
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
    def status_for(data):
        return 202 if 'operation_id' in data else 200

    @staticmethod
    def project(data, request):
        status = StopTaskResponse.status_for(data)
        code = 'OPERATION_ACCEPTED' if status == 202 else 'TASK_ALREADY_ENDED'
        validate_registered_success(request.command, data, code, status)
        return data, None


@task_stop_router.post(STOP_PATH)
async def stop_task_http(request: Request):
    result = await handle_http(request, StopTaskRequest, StopTaskResponse, accept_task_stop)
    wake = getattr(request.app.state, 'walle_stop_wake', None)
    if result.status_code == 202 and wake is not None:
        wake.set()
    return result
