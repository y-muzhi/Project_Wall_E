"""I16 canonical status input and the complete public status model."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer
from .contracts import guide_run_read_model
from backend.app.shared.http_boundary import idempotency_header
from .contracts import cancel_guide_run_input, guide_run_accepted
from .contracts import list_guide_runs_input, guide_run_summary, GUIDE_STATUSES
from backend.app.shared.http_projection import page
from backend.app.shared.http_commands import CommandRequest
from backend.app.shared.validation import object_fields
from backend.app.messages.contracts import message_read_model
from .contracts import create_guide_run_input, continue_guide_run_input
from .contracts import modify_from_comment_input
from .contracts import retry_guide_run_input


@dataclass(frozen=True)
class GetGuideRunRequest:
    guide_run_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        return cls(decimal_integer(request.path_params['guide_run_id'], 'guide_run_id'))


class GetGuideRunResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        value = guide_run_read_model(data)
        if value['id'] != request.guide_run_id:
            raise ValueError('Run status response belongs to another request')
        return value, None


@dataclass(frozen=True)
class CancelGuideRunRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        request_query(request)
        payload = {'guide_run_id': decimal_integer(request.path_params['guide_run_id'], 'guide_run_id'), 'idempotency_key': idempotency_header(request)}
        cancel_guide_run_input(payload)
        return cls(payload)


class CancelGuideRunResponse:
    success_code = 'GUIDE_CANCELLED'
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        value = guide_run_accepted(data)
        if value['id'] != request.payload['guide_run_id'] or value['status'] != 'CANCELLED' or value['current_step'] != 'FINISHED':
            raise ValueError('Cancellation response must reference the actual cancelled run')
        return value, None


@dataclass(frozen=True)
class ListGuideRunsRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        payload = request_query(request, singles=('page',), arrays={'status': GUIDE_STATUSES, 'action_type': ('INITIALIZE', 'ASK', 'REVIEW', 'MODIFY')})
        payload['requirement_id'] = decimal_integer(request.path_params['requirement_id'], 'requirement_id')
        if 'page' in payload:
            payload['page'] = decimal_integer(payload['page'], 'page', maximum=100000)
        validated = list_guide_runs_input(payload)
        return cls({'requirement_id': validated.requirement_id, 'page': validated.page, 'status': list(validated.status), 'action_type': list(validated.action_type)})


class ListGuideRunsResponse:
    errors = GetGuideRunResponse.errors

    @staticmethod
    def project(data, request):
        def project_item(item):
            value = guide_run_summary(item)
            if value['requirement_id'] != request.payload['requirement_id']:
                raise ValueError('History response contains another requirement')
            return value
        return page(data, project_item, request.payload['page'])


class CreateGuideRunRequest(CommandRequest):
    body_fields = ('expected_version', 'action_type', 'instruction', 'scope_type', 'scope_ref', 'source_type', 'source_id')
    mandatory = ('expected_version', 'action_type', 'instruction', 'scope_type', 'source_type')
    rename = {'expected_version': 'expected_content_version'}
    validate = staticmethod(create_guide_run_input)
    normalize = staticmethod(lambda payload, validated: validated.business_input() | {'idempotency_key': validated.idempotency_key})


class CreateGuideRunResponse:
    success_code = 'GUIDE_ACCEPTED'
    status = 202
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'SOURCE_INVALID', 'SCOPE_INVALID', 'CONFIG_INVALID', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'CAPACITY_EXHAUSTED', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        value = object_fields(data, 'data', ('guide_run', 'user_message'), ('guide_run', 'user_message'))
        run, message = guide_run_accepted(value['guide_run']), message_read_model(value['user_message'])
        if run['requirement_id'] != request.payload['requirement_id'] or run['status'] != 'RUNNING' or run['current_step'] != 'PREPARING' or message['guide_run_id'] != run['id'] or message['requirement_id'] != run['requirement_id'] or message['role'] != 'USER' or message['message_type'] != 'TEXT' or message['content'] != request.payload['instruction']:
            raise ValueError('Accepted response contradicts the submitted instruction/run')
        return {'guide_run': run, 'user_message': message}, None


class ContinueGuideRunRequest(CommandRequest):
    body_fields = ('instruction',)
    mandatory = body_fields
    uses_requirement_path = False

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        value = object_fields(body, 'body', cls.body_fields, cls.mandatory)
        validated = continue_guide_run_input({**value, 'guide_run_id': decimal_integer(request.path_params['guide_run_id'], 'guide_run_id'), 'idempotency_key': idempotency_header(request)})
        return cls(validated.business_input() | {'idempotency_key': validated.idempotency_key})


class ContinueGuideRunResponse:
    success_code = 'GUIDE_CONTINUED'
    status = 202
    errors = CreateGuideRunResponse.errors - {'CONTENT_VERSION_CONFLICT', 'SOURCE_INVALID', 'SCOPE_INVALID'}

    @staticmethod
    def project(data, request):
        value = guide_run_accepted(data)
        if value['id'] != request.payload['guide_run_id'] or value['status'] != 'RUNNING' or value['current_step'] != 'PREPARING':
            raise ValueError('Continuation must reference the accepted original run')
        return value, None


class ModifyFromCommentRequest(CommandRequest):
    body_fields = ('expected_content_version',)
    mandatory = body_fields
    uses_requirement_path = False

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        value = object_fields(body, 'body', cls.body_fields, cls.mandatory)
        parsed = modify_from_comment_input({**value, 'comment_id': decimal_integer(request.path_params['comment_id'], 'comment_id'), 'idempotency_key': idempotency_header(request)})
        return cls(parsed.business_input() | {'idempotency_key': parsed.idempotency_key})


class ModifyFromCommentResponse:
    success_code = 'GUIDE_ACCEPTED'
    status = 202
    errors = CreateGuideRunResponse.errors - {'SOURCE_INVALID', 'SCOPE_INVALID'} | {'COMMENT_ORPHANED'}

    @staticmethod
    def project(data, request):
        value = guide_run_read_model(data)
        if value['status'] != 'RUNNING' or value['current_step'] != 'PREPARING' or value['action_type'] != 'MODIFY' or value['function_type'] != 'MODIFY_FROM_COMMENT' or value['source_type'] != 'COMMENT' or value['source_id'] != request.payload['comment_id'] or value['scope']['scope_type'] not in ('BLOCK', 'SELECTION'):
            raise ValueError('Accepted comment run must preserve its source and derived authority')
        return value, None


@dataclass(frozen=True)
class RetryGuideRunRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        request_query(request)
        value = retry_guide_run_input({'guide_run_id': decimal_integer(request.path_params['guide_run_id'], 'guide_run_id'), 'idempotency_key': idempotency_header(request)})
        return cls(value.business_input() | {'idempotency_key': value.idempotency_key})


class RetryGuideRunResponse:
    success_code = 'GUIDE_RETRY_ACCEPTED'
    status = 202
    errors = CreateGuideRunResponse.errors - {'CONTENT_VERSION_CONFLICT'}

    @staticmethod
    def project(data, request):
        value = guide_run_read_model(data)
        if value['id'] == request.payload['guide_run_id'] or value['retry_of_guide_run_id'] != request.payload['guide_run_id'] or value['status'] != 'RUNNING' or value['current_step'] != 'PREPARING':
            raise ValueError('Retry response must reference a new accepted run and actual predecessor')
        return value, None
