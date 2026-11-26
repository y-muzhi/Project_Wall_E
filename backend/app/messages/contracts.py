"""Exact message projections and fixed exclusive cursor result."""

from dataclasses import dataclass
from functools import lru_cache
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import (
    object_fields,
    strict_integer,
    strict_enum,
    strict_boolean,
    raw_text,
)
from backend.app.documents.snapshot import _time

MESSAGE_FIELDS = (
    'id',
    'requirement_id',
    'document_id',
    'guide_run_id',
    'sequence_no',
    'role',
    'content',
    'message_type',
    'structured_content',
    'reply_to_message_id',
    'created_at',
    'card_state',
    'phase_ref',
    'topic_refs',
    'document_ids',
    'program_receipt',
)


@lru_cache(maxsize=1)
def _structure_protocol():
    return ResourceCatalog().collaboration


def program_receipt(data):
    if type(data) is dict and data.get('schema') == 'formation_program_receipt_v21_1':
        from backend.app.formation.http_projection import program_receipt as formation_receipt

        return formation_receipt(data)
    fields = (
        'processing',
        'user_message_id',
        'requirement_id',
        'discussion_version',
        'purpose',
        'result',
        'document_effect',
    )
    value = object_fields(data, 'program_receipt', fields, fields)
    strict_enum(value['processing'], 'processing', ('PROGRAM',))
    for field in ('user_message_id', 'requirement_id', 'discussion_version'):
        strict_integer(value[field], field)
    strict_enum(
        value['purpose'], 'purpose', ('DOCUMENT_ACTION', 'PHASE_CHANGE', 'FACT_CONFIRMATION')
    )
    strict_enum(value['result'], 'result', ('APPLIED', 'DEFERRED', 'NO_CHANGE'))
    if value['purpose'] == 'DOCUMENT_ACTION' and value['result'] != 'DEFERRED':
        raise ValueError('Accepted document actions require a real model round')
    if value['document_effect'] is not None:
        from backend.app.documents.contracts import document_effect

        document_effect(value['document_effect'])
        if value['purpose'] != 'FACT_CONFIRMATION' or value['result'] == 'DEFERRED':
            raise ValueError('Only applied fact confirmation has a document effect')
    if (
        value['purpose'] == 'FACT_CONFIRMATION'
        and value['result'] != 'DEFERRED'
        and value['document_effect'] is None
    ):
        raise ValueError('Confirmed facts require the actual formal content outcome')
    return dict(value)


@dataclass(frozen=True)
class MessageQuery:
    requirement_id: int
    document_id: int
    before_sequence_no: int | None


def list_messages_input(payload):
    value = object_fields(
        payload,
        'query',
        ('requirement_id', 'document_id', 'before_sequence_no'),
        ('requirement_id', 'document_id'),
    )
    cursor = value.get('before_sequence_no')
    return MessageQuery(
        strict_integer(value['requirement_id'], 'requirement_id'),
        strict_integer(value['document_id'], 'document_id'),
        None if cursor is None else strict_integer(cursor, 'before_sequence_no'),
    )


def message_read_model(data):
    value = object_fields(
        data,
        'message',
        (
            *MESSAGE_FIELDS,
            'formation_operations',
            'initial_route_suggestion',
            'guide_operations',
            'audited_document_output',
        ),
        MESSAGE_FIELDS,
    )
    if 'guide_operations' in value:
        from .operation_receipts import guide_operation

        rows = value['guide_operations']
        if value['role'] != 'USER' or type(rows) is not list or not rows:
            raise ValueError('Operations must belong to the original user message')
        projected = [guide_operation(item) for item in rows]
        identities = [item['run_id'] for item in projected]
        if identities != sorted(set(identities)):
            raise ValueError('Operations must be distinct and ordered')
    if 'audited_document_output' in value and (
        value['audited_document_output'] is not True
        or value['role'] != 'ASSISTANT'
        or value['guide_run_id'] is None
        or value['message_type'] != 'TEXT'
    ):
        raise ValueError('Audited document output must belong to its original assistant text')
    if 'initial_route_suggestion' in value:
        if (
            value['role'] != 'ASSISTANT'
            or value['message_type'] != 'TEXT'
            or value['guide_run_id'] is None
            or 'formation_operations' in value
        ):
            raise ValueError('An initial suggestion requires its original assistant message')
        proposal = object_fields(
            value['initial_route_suggestion'],
            'initial_route_suggestion',
            ('goal', 'steps'),
            ('goal', 'steps'),
        )
        raw_text(proposal['goal'], 'goal', 1)
        if not isinstance(proposal['steps'], list) or not proposal['steps']:
            raise ValueError('An initial suggestion needs steps')
        for item in proposal['steps']:
            step = object_fields(
                item, 'step', ('title', 'expected_results'), ('title', 'expected_results')
            )
            raw_text(step['title'], 'title', 1)
            if not isinstance(step['expected_results'], list):
                raise ValueError('Expected results must be a list')
            for result in step['expected_results']:
                raw_text(result, 'expected_result', 1)
    if 'formation_operations' in value:
        operations = value['formation_operations']
        if not isinstance(operations, list) or not operations:
            raise ValueError('Missing formation operations')
        for item in operations:
            fields = (
                'batch_id',
                'kind',
                'goal',
                'steps',
                'moves',
                'focus_title',
                'previous_focus_title',
                'actions',
            )
            operation = object_fields(item, 'formation_operation', fields, fields)
            strict_integer(operation['batch_id'], 'batch_id')
            strict_enum(operation['kind'], 'kind', ('CREATED', 'UPDATED', 'FOCUSED'))
            if operation['goal'] is not None:
                raw_text(operation['goal'], 'goal', 1, 1000)
            if not isinstance(operation['steps'], list):
                raise ValueError('Invalid historical step list')
            if operation['focus_title'] is not None:
                raw_text(operation['focus_title'], 'focus_title', 1, 1000)
            if operation['previous_focus_title'] is not None:
                raw_text(operation['previous_focus_title'], 'previous_focus_title', 1, 1000)
            if not isinstance(operation['actions'], list):
                raise ValueError('Invalid lifecycle actions')
            for label in operation['actions']:
                raw_text(label, 'action_label', 1, 120)
            if not isinstance(operation['moves'], list):
                raise ValueError('Invalid historical step moves')
            for move in operation['moves']:
                fields = ('title', 'before', 'after')
                object_fields(move, 'move', fields, fields)
                raw_text(move['title'], 'title', 1, 1000)
                strict_integer(move['before'], 'before')
                strict_integer(move['after'], 'after')
            for title in operation['steps']:
                raw_text(title, 'step_title', 1, 1000)
    for field in ('id', 'requirement_id', 'sequence_no'):
        strict_integer(value[field], field)
    for field in ('guide_run_id', 'reply_to_message_id', 'document_id'):
        if value[field] is not None:
            strict_integer(value[field], field)
    strict_enum(value['role'], 'role', ('USER', 'ASSISTANT'))
    strict_enum(
        value['message_type'], 'message_type', ('TEXT', 'INTERACTION_CARDS', 'CARD_RESPONSE')
    )
    raw_text(value['content'], 'content', 0)
    _time(value['created_at'])
    if value['phase_ref'] is not None:
        raw_text(value['phase_ref'], 'phase_ref', 1, 100)
    for field in ('topic_refs', 'document_ids'):
        if type(value[field]) is not list or len(value[field]) != len(set(value[field])):
            raise ValueError('Message associations must be unique arrays')
        for item in value[field]:
            strict_integer(item, field) if field == 'document_ids' else raw_text(
                item, field, 1, 100
            )
    if value['program_receipt'] is not None:
        receipt = program_receipt(value['program_receipt'])
        if (
            (receipt['user_message_id'], receipt['requirement_id'])
            != (value['id'], value['requirement_id'])
            or value['guide_run_id'] is not None
            or value['message_type'] != 'CARD_RESPONSE'
        ):
            raise ValueError(
                'Program receipt must belong to its actual formal user answer without a model run'
            )
    kind = value['message_type']
    if kind == 'TEXT' and (
        value['structured_content'] is not None
        or value['reply_to_message_id'] is not None
        or value['card_state'] is not None
    ):
        raise ValueError('Text has no structure or card state')
    if kind == 'INTERACTION_CARDS':
        if value['role'] != 'ASSISTANT' or value['reply_to_message_id'] is not None:
            raise ValueError('Cards require an assistant without a reply')
        if value['structured_content'] is None:
            if value['card_state'] is not None:
                raise ValueError('Damaged structure has no card state')
        else:
            from .cards import validate_cards

            from .queries import reading_protocol
            import json

            validate_cards(
                value['structured_content'],
                reading_protocol(json.dumps(value['structured_content']), _structure_protocol()),
            )
            strict_enum(value['card_state'], 'card_state', ('AVAILABLE', 'ANSWERED', 'EXPIRED'))
    if kind == 'CARD_RESPONSE' and (
        value['role'] != 'USER'
        or value['reply_to_message_id'] is None
        or value['card_state'] is not None
    ):
        raise ValueError('Formal responses require a user and original card identity')
    if kind == 'CARD_RESPONSE' and value['structured_content'] is not None:
        _structure_protocol().validate_responses(value['structured_content'])
    canonical_input(value)
    return dict(value)


def list_messages_result(items, request, has_more):
    strict_boolean(has_more, 'has_more')
    if type(items) is not list or len(items) > 20:
        raise ValueError('Message windows have at most 20 items')
    rows = [message_read_model(item) for item in items]
    sequences = [item['sequence_no'] for item in rows]
    if (
        sequences != sorted(set(sequences))
        or any(
            item['requirement_id'] != request.requirement_id
            or item['document_id'] != request.document_id
            for item in rows
        )
        or request.before_sequence_no is not None
        and any(sequence >= request.before_sequence_no for sequence in sequences)
    ):
        raise ValueError('Message window must match its exclusive cursor and root')
    if has_more and not rows:
        raise ValueError('Empty windows have no continuation')
    return {
        'items': rows,
        'page_size': 20,
        'has_more': has_more,
        'next_cursor': sequences[0] if has_more else None,
    }
