"""Exact message projections and fixed exclusive cursor result."""
from dataclasses import dataclass
from functools import lru_cache
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import object_fields, strict_integer, strict_enum, strict_boolean, raw_text
from backend.app.documents.snapshot import _time

MESSAGE_FIELDS = ('id', 'requirement_id', 'guide_run_id', 'sequence_no', 'role', 'content', 'message_type', 'structured_content', 'reply_to_message_id', 'created_at', 'card_state')


@lru_cache(maxsize=1)
def _structure_protocol():
    return ResourceCatalog().freeze('ASK', 'USER_INSTRUCTION')


@dataclass(frozen=True)
class MessageQuery:
    requirement_id: int
    before_sequence_no: int | None


def list_messages_input(payload):
    value = object_fields(payload, 'query', ('requirement_id', 'before_sequence_no'), ('requirement_id',))
    cursor = value.get('before_sequence_no')
    return MessageQuery(strict_integer(value['requirement_id'], 'requirement_id'), None if cursor is None else strict_integer(cursor, 'before_sequence_no'))


def message_read_model(data):
    value = object_fields(data, 'message', MESSAGE_FIELDS, MESSAGE_FIELDS)
    for field in ('id', 'requirement_id', 'sequence_no'): strict_integer(value[field], field)
    for field in ('guide_run_id', 'reply_to_message_id'):
        if value[field] is not None: strict_integer(value[field], field)
    strict_enum(value['role'], 'role', ('USER', 'ASSISTANT'))
    strict_enum(value['message_type'], 'message_type', ('TEXT', 'INTERACTION_CARDS', 'CARD_RESPONSE'))
    raw_text(value['content'], 'content', 0);_time(value['created_at'])
    kind = value['message_type']
    if kind == 'TEXT' and (value['structured_content'] is not None or value['reply_to_message_id'] is not None or value['card_state'] is not None): raise ValueError('Text has no structure or card state')
    if kind == 'INTERACTION_CARDS':
        if value['role'] != 'ASSISTANT' or value['reply_to_message_id'] is not None: raise ValueError('Cards require an assistant without a reply')
        if value['structured_content'] is None:
            if value['card_state'] is not None: raise ValueError('Damaged structure has no card state')
        else:
            from .cards import validate_cards
            validate_cards(value['structured_content'], _structure_protocol())
            strict_enum(value['card_state'], 'card_state', ('AVAILABLE', 'ANSWERED', 'EXPIRED'))
    if kind == 'CARD_RESPONSE' and (value['role'] != 'USER' or value['reply_to_message_id'] is None or value['card_state'] is not None): raise ValueError('Formal responses require a user and original card identity')
    if kind == 'CARD_RESPONSE' and value['structured_content'] is not None: _structure_protocol().validate_responses(value['structured_content'])
    canonical_input(value)
    return dict(value)


def list_messages_result(items, request, has_more):
    strict_boolean(has_more, 'has_more')
    if type(items) is not list or len(items) > 20: raise ValueError('Message windows have at most 20 items')
    rows = [message_read_model(item) for item in items]
    sequences = [item['sequence_no'] for item in rows]
    if sequences != sorted(set(sequences)) or any(item['requirement_id'] != request.requirement_id for item in rows) or request.before_sequence_no is not None and any(sequence >= request.before_sequence_no for sequence in sequences):
        raise ValueError('Message window must match its exclusive cursor and root')
    if has_more and not rows: raise ValueError('Empty windows have no continuation')
    return {'items': rows, 'page_size': 20, 'has_more': has_more, 'next_cursor': sequences[0] if has_more else None}
