"""Initial proposals live on their audited assistant message until a subsequent user adopts one."""

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_loads
from hashlib import sha256


def audited_initials(connection, requirement_id, document_id, message_ids):
    if document_id is None or not message_ids:
        return {}
    if not connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='formation_heads'"
    ).fetchone():
        return {}
    slots = ','.join('?' for _ in message_ids)
    rows = connection.execute(
        "SELECT m.id, json_extract(l.trusted_output_json,'$.progress_delta.formation_delta') AS proposal "
        'FROM conversation_messages m JOIN guide_runs r ON r.id=m.guide_run_id '
        "JOIN llm_uses l ON l.id=(SELECT MAX(a.id) FROM llm_uses a WHERE a.guide_run_id=r.id AND a.validation_status='SUCCEEDED') "
        'WHERE m.requirement_id=? AND m.document_id=? AND r.requirement_id=m.requirement_id AND r.document_id=m.document_id '
        "AND m.role='ASSISTANT' AND m.message_type='TEXT' AND r.status='COMPLETED' AND r.operation='DISCUSS' "
        "AND json_extract(r.final_result_json,'$.effect_state')='APPLIED' "
        "AND json_extract(r.final_result_json,'$.assistant_message_id')=m.id "
        "AND json_extract(l.trusted_output_json,'$.progress_delta.formation_delta.intent')='SUGGEST_INITIAL' "
        "AND json_extract(l.trusted_output_json,'$.cards') IS NULL AND m.id IN (" + slots + ')',
        (requirement_id, document_id, *message_ids),
    )
    return {row['id']: strict_json_loads(row['proposal']) for row in rows}


def public_initial(proposal):
    return {
        'goal': proposal['goal'],
        'steps': [
            {
                'title': step['title'],
                'expected_results': [item['description'] for item in step['expected_results']],
            }
            for step in proposal['steps']
        ],
    }


def preceding_initial(connection, root, trigger_id):
    row = connection.execute(
        'SELECT m.role,m.id,m.guide_run_id FROM conversation_messages m JOIN conversation_messages t '
        'ON t.id=? AND t.document_id=m.document_id AND t.requirement_id=m.requirement_id '
        'WHERE m.requirement_id=? AND m.document_id=? AND m.sequence_no<t.sequence_no ORDER BY m.sequence_no DESC LIMIT 1',
        (trigger_id, root['id'], root['assistant_document_id']),
    ).fetchone()
    if row is None or row['role'] != 'ASSISTANT' or row['guide_run_id'] is None:
        return None
    delta = audited_initials(
        connection, root['id'], root['assistant_document_id'], [row['id']]
    ).get(row['id'])
    if delta is None:
        return None
    return {
        'message_id': row['id'],
        'payload_digest': sha256(canonical_input(delta).encode('utf-8')).hexdigest(),
        'goal': delta['goal'],
        'steps': delta['steps'],
        'basis': delta['basis'],
    }


def initial_plan(connection, root, context, delta, catalog):
    from .model_plan import prepare_model
    from .discussion_route import user_directive

    current = context.input['current_request']
    if delta['intent'] in ('CREATE_INITIAL', 'ADOPT_INITIAL'):
        user_directive(context, delta['directive'])
    if delta['intent'] == 'ADOPT_INITIAL':
        proposal = preceding_initial(connection, root, current['message_id'])
        candidate = context.canonical['formation']['route_context']['initial_proposal']
        if (
            not candidate
            or not proposal
            or candidate['message_id'] != proposal['message_id']
            or (delta['message_id'], delta['payload_digest'])
            != (proposal['message_id'], proposal['payload_digest'])
        ):
            raise ValueError('Initial proposal is absent, changed or ambiguous')
    else:
        proposal = delta
    if (
        proposal['basis'] != context.canonical['formation']['basis']
        or delta['basis'] != proposal['basis']
    ):
        raise ValueError('The document changed since the initial suggestion')
    return prepare_model(
        connection,
        root,
        context,
        {
            'basis': delta['basis'],
            'changes': [
                {
                    'type': 'INITIALIZE_PATH',
                    'goal': {'text': proposal['goal'], 'source_refs': [current['message_ref']]},
                    'steps': proposal['steps'],
                }
            ],
        },
        catalog,
        initial_position=delta.get('focus_position', 1),
    )
