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


class ListModelCallsResponse:
    errors = GetGuideRunResponse.errors

    @staticmethod
    def project(data, request):
        fields = ('id', 'requirement_id', 'action_type', 'operation', 'status', 'current_step', 'trigger_message_id', 'program_processed', 'items')
        value = object_fields(data, 'model_calls', fields, fields)
        if value['id'] != request.guide_run_id or any(item['guide_run_id'] != value['id'] for item in value['items']):
            raise ValueError('Calls must belong to the requested run')
        return value, None


@dataclass(frozen=True)
class GetModelCallRequest:
    llm_use_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        return cls(decimal_integer(request.path_params['llm_use_id'], 'llm_use_id'))


class GetModelCallResponse:
    errors = GetGuideRunResponse.errors

    @staticmethod
    def project(data, request):
        fields = ('call', 'requirement_id', 'action_type', 'operation', 'prompt_reference', 'context_reference', 'sections',
            'included_history_ids', 'budget_removed_history_ids', 'raw_request_json', 'preflight', 'context_strategy', 'selection_summary')
        value = object_fields(data, 'model_call', fields, fields)
        if value['call']['id'] != request.llm_use_id:
            raise ValueError('Snapshot must belong to the requested call')
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
    success_codes = ('GUIDE_CANCELLED', 'GUIDE_ALREADY_COMPLETED')
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        if data.get('status') == 'COMPLETED':
            value = guide_run_read_model(data)
            if value['id'] != request.payload['guide_run_id']:
                raise ValueError('Completion belongs to another run')
            return value, None
        value = guide_run_accepted(data)
        if value['id'] != request.payload['guide_run_id'] or value['status'] != 'CANCELLED' or value['current_step'] != 'FINISHED':
            raise ValueError('Cancellation response must reference the actual cancelled run')
        return value, None


@dataclass(frozen=True)
class ListGuideRunsRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        payload = request_query(request, singles=('page',), arrays={'status': GUIDE_STATUSES, 'action_type': ('ASK', 'GENERATE', 'REVIEW', 'MODIFY')})
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
    body_fields = ('expected_discussion_version', 'operation', 'instruction', 'target', 'scope', 'source_refs', 'proposal_ref', 'acknowledge_source_changes')
    mandatory = body_fields
    validate = staticmethod(create_guide_run_input)
    normalize = staticmethod(lambda payload, validated: validated.business_input() | {'idempotency_key': validated.idempotency_key})


class CreateGuideRunResponse:
    success_code = 'GUIDE_ACCEPTED'
    status = 202
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'DISCUSSION_VERSION_CONFLICT', 'CONTENT_VERSION_CONFLICT', 'SOURCE_VERSION_CONFLICT', 'SOURCE_INVALID', 'SCOPE_INVALID', 'CONFIG_INVALID', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'CAPACITY_EXHAUSTED', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        from backend.app.shared.validation import strict_enum, strict_integer
        fields = ('processing', 'guide_run_id', 'user_message_id')
        value = object_fields(data, 'data', fields, fields)
        strict_enum(value['processing'], 'processing', ('MODEL',))
        strict_integer(value['guide_run_id'], 'guide_run_id');strict_integer(value['user_message_id'], 'user_message_id')
        return value, None


class ContinueGuideRunRequest(CommandRequest):
    body_fields = ('instruction', 'expected_discussion_version')
    mandatory = body_fields
    uses_requirement_path = False

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        value = object_fields(body, 'body', cls.body_fields, cls.mandatory)
        validated = continue_guide_run_input({**value, 'guide_run_id': decimal_integer(request.path_params['guide_run_id'], 'guide_run_id'), 'idempotency_key': idempotency_header(request)})
        return cls(validated.business_input() | {'idempotency_key': validated.idempotency_key})


class ContinueGuideRunResponse(CreateGuideRunResponse):
    success_code = 'GUIDE_CONTINUED'
    status = 202
    errors = CreateGuideRunResponse.errors - {'CONTENT_VERSION_CONFLICT', 'SOURCE_INVALID', 'SCOPE_INVALID'}

    @staticmethod
    def project(data, request):
        value, _ = CreateGuideRunResponse.project(data, request)
        if value['guide_run_id'] == request.payload['guide_run_id']:
            raise ValueError('Continuation must accept a new linked run')
        return value, None


class ModifyFromCommentRequest(CommandRequest):
    body_fields = ('expected_content_version', 'expected_discussion_version')
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
    errors = CreateGuideRunResponse.errors | {'COMMENT_ORPHANED'}

    @staticmethod
    def project(data, request):
        return CreateGuideRunResponse.project(data, request)


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
    errors = CreateGuideRunResponse.errors

    @staticmethod
    def project(data, request):
        value, _ = CreateGuideRunResponse.project(data, request)
        if value['guide_run_id'] == request.payload['guide_run_id']:
            raise ValueError('Retry response must reference a new accepted run and actual predecessor')
        return value, None
