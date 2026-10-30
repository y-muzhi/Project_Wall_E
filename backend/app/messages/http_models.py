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
        cursor = (
            None
            if 'before_sequence_no' not in query
            else decimal_integer(query['before_sequence_no'], 'before_sequence_no')
        )
        payload = {
            'requirement_id': decimal_integer(
                request.path_params['requirement_id'], 'requirement_id'
            ),
            'before_sequence_no': cursor,
        }
        list_messages_input(payload)
        return cls(payload)


class ListMessagesResponse:
    errors = frozenset({'INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'})

    @staticmethod
    def project(data, request):
        fields = ('items', 'page_size', 'has_more', 'next_cursor')
        value = object_fields(data, 'data', fields, fields)
        validated = list_messages_result(
            value['items'], list_messages_input(request.payload), value['has_more']
        )
        if (
            value['page_size'] != 20
            or type(value['page_size']) is not int
            or value['next_cursor'] != validated['next_cursor']
            or value['next_cursor'] is not None
            and type(value['next_cursor']) is not int
        ):
            raise ValueError('Message continuation must reflect its actual window')
        return {'items': validated['items']}, {field: validated[field] for field in fields[1:]}


class SubmitCardResponsesRequest:
    body_fields = (
        'schema_version',
        'responses',
        'expected_discussion_version',
        'execution_selection',
    )

    def __init__(self, payload):
        self.payload = payload

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        value = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        parsed = submit_card_responses_input(
            {
                **value,
                'message_id': decimal_integer(request.path_params['message_id'], 'message_id'),
                'idempotency_key': idempotency_header(request),
            }
        )
        return cls(parsed.business_input() | {'idempotency_key': parsed.idempotency_key})


class SubmitCardResponsesResponse:
    success_codes = ('CARDS_ACCEPTED', 'PROGRAM_PROCESSED')
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'STATE_CONFLICT',
            'SOURCE_INVALID',
            'SCOPE_INVALID',
            'SOURCE_VERSION_CONFLICT',
            'CARD_ALREADY_ANSWERED',
            'CARD_EXPIRED',
            'WORK_STATE_CONFLICT',
            'WORK_STATE_INCONSISTENT',
            'DISCUSSION_VERSION_CONFLICT',
            'CONTENT_VERSION_CONFLICT',
            'TARGET_STALE',
            'CONFIG_INVALID',
            'IDEMPOTENCY_CONFLICT',
            'REQUEST_IN_PROGRESS',
            'CAPACITY_EXHAUSTED',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def status_for(data):
        return 202 if data['processing'] == 'MODEL' else 200

    @staticmethod
    def project(data, request):
        if data.get('processing') == 'MODEL':
            from backend.app.guide.http_models import CreateGuideRunResponse

            value, _ = CreateGuideRunResponse.project(data, request)
        else:
            from .contracts import program_receipt

            value = program_receipt(data)
        return value, None
