"""I35 exact cursor and message projection, without totals."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer, object_fields
from .contracts import list_messages_input, list_messages_result
from backend.app.guide.contracts import submit_card_responses_input, guide_run_accepted
from backend.app.shared.http_boundary import idempotency_header
from .contracts import message_read_model


@dataclass(frozen=True)
class ListMessagesRequest:
    payload: dict

    @classmethod
    def parse(cls, request):
        query = request_query(request, singles=('before_sequence_no',))
        cursor = None if 'before_sequence_no' not in query else decimal_integer(query['before_sequence_no'], 'before_sequence_no')
        payload = {'requirement_id': decimal_integer(request.path_params['requirement_id'], 'requirement_id'), 'before_sequence_no': cursor}
        list_messages_input(payload)
        return cls(payload)


class ListMessagesResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        fields = ('items', 'page_size', 'has_more', 'next_cursor')
        value = object_fields(data, 'data', fields, fields)
        validated = list_messages_result(value['items'], list_messages_input(request.payload), value['has_more'])
        if value['page_size'] != 20 or type(value['page_size']) is not int or value['next_cursor'] != validated['next_cursor'] or value['next_cursor'] is not None and type(value['next_cursor']) is not int:
            raise ValueError('Message continuation must reflect its actual window')
        return {'items': validated['items']}, {field: validated[field] for field in fields[1:]}


class SubmitCardResponsesRequest:
    body_fields = ('schema_version', 'responses')

    def __init__(self, payload):
        self.payload = payload

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        value = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        parsed = submit_card_responses_input({**value, 'message_id': decimal_integer(request.path_params['message_id'], 'message_id'), 'idempotency_key': idempotency_header(request)})
        return cls(parsed.business_input() | {'idempotency_key': parsed.idempotency_key})


class SubmitCardResponsesResponse:
    success_code = 'CARDS_ACCEPTED'
    status = 202
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'SOURCE_INVALID', 'CARD_ALREADY_ANSWERED', 'CARD_EXPIRED', 'WORK_STATE_INCONSISTENT', 'CONFIG_INVALID', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'CAPACITY_EXHAUSTED', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        fields = ('response_message', 'guide_run', 'card_state')
        value = object_fields(data, 'data', fields, fields)
        message, run = message_read_model(value['response_message']), guide_run_accepted(value['guide_run'])
        if value['card_state'] != 'ANSWERED' or run['status'] != 'RUNNING' or run['current_step'] != 'PREPARING' or message['reply_to_message_id'] != request.payload['message_id'] or message['message_type'] != 'CARD_RESPONSE' or message['guide_run_id'] != run['id'] or message['requirement_id'] != run['requirement_id'] or message['structured_content'] != {'schema_version': request.payload['schema_version'], 'responses': request.payload['responses']}:
            raise ValueError('Formal answer result contradicts its accepted request')
        return {'response_message': message, 'guide_run': run, 'card_state': 'ANSWERED'}, None
