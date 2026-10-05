"""I35 exact cursor and message projection, without totals."""
from dataclasses import dataclass
from backend.app.shared.http_boundary import request_query
from backend.app.shared.validation import decimal_integer, object_fields
from .contracts import list_messages_input, list_messages_result


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
