"""Resolve a real formal card answer; source objects from callers grant no authority."""

import json

from backend.app.shared.command_execution import Rejected

from .proposal_binding import digest
from .proposal_contracts import proposal_group


def card_source(connection, requirement_id, document_id, response_id, catalog):
    row = connection.execute(
        'SELECT r.*,m.structured_content_json AS original_json,m.role AS original_role,'
        'm.message_type AS original_type,m.requirement_id AS original_requirement,'
        'm.document_id AS original_document,m.guide_run_id AS original_run,p.card_key AS indexed_card_key,p.purpose AS indexed_purpose,p.binding_json,p.payload_digest,p.disposition '
        'FROM conversation_messages r JOIN conversation_messages m ON m.id=r.reply_to_message_id '
        'JOIN formation_proposal_index p ON p.message_id=m.id AND p.document_id=m.document_id '
        'WHERE r.id=? AND r.requirement_id=? AND r.document_id=?',
        (response_id, requirement_id, document_id),
    ).fetchone()
    if (
        row is None
        or row['role'] != 'USER'
        or row['message_type'] != 'CARD_RESPONSE'
        or row['guide_run_id'] is not None
    ):
        raise Rejected('SOURCE_INVALID')
    if (
        (
            row['original_role'],
            row['original_type'],
            row['original_requirement'],
            row['original_document'],
        )
        != ('ASSISTANT', 'INTERACTION_CARDS', requirement_id, document_id)
        or row['original_run'] is None
        or row['disposition'] not in ('PENDING', 'APPLIED')
    ):
        raise Rejected('SOURCE_INVALID')
    group = proposal_group(json.loads(row['original_json']), catalog.collaboration, stored=True)
    if (
        group['purpose'] != 'STAGED_WRITE'
        or digest(group['action_payload']) != row['payload_digest']
    ):
        raise Rejected('SOURCE_INVALID')
    if (
        row['indexed_card_key'] != group['cards'][0]['card_key']
        or row['indexed_purpose'] != group['purpose']
    ):
        raise Rejected('SOURCE_INVALID')
    answers = json.loads(row['structured_content_json'])
    card_key = group['cards'][0]['card_key']
    if answers != {
        'schema_version': 1,
        'responses': [
            {
                'card_key': card_key,
                'selected_option_keys': ['apply'],
                'custom_answer': None,
                'skipped': False,
            }
        ],
        'execution_selection': None,
    }:
        raise Rejected('SOURCE_INVALID')
    source_run = connection.execute(
        "SELECT 1 FROM guide_runs WHERE id=? AND requirement_id=? AND document_id=? AND status='COMPLETED'",
        (row['original_run'], requirement_id, document_id),
    ).fetchone()
    if source_run is None:
        raise Rejected('SOURCE_INVALID')
    return {
        'source_type': 'CARD_RESPONSE',
        'actor': 'USER',
        'conversation_message_id': row['reply_to_message_id'],
        'card_key': card_key,
        'response_message_id': response_id,
    }, group['action_payload']
