"""Same-snapshot SourceRef lookup shared by discussion and context selection.

A reference proves an owned immutable source, never write permission. Material
references select only an actually saved selected item, not a run's private basis.
"""
import json

from backend.app.shared.command_execution import Rejected
from .discussion import discussion_resources


def verify_source_refs(connection, requirement_id, refs, *, resources=None):
    resources = resources or discussion_resources()
    seen = set()
    for source in refs:
        resources.validate('SourceRef', source)
        key = json.dumps(source, sort_keys=True, ensure_ascii=False)
        if key in seen:
            raise Rejected('SOURCE_INVALID')
        seen.add(key)
        kind = source['kind']
        if kind in ('MESSAGE', 'CARD_ANSWER'):
            row = connection.execute('SELECT * FROM conversation_messages WHERE id=? AND requirement_id=?',
                (source['message_id'], requirement_id)).fetchone()
            if row is None:
                raise Rejected('SOURCE_INVALID')
            if kind == 'CARD_ANSWER':
                if row['role'] != 'USER' or row['message_type'] != 'CARD_RESPONSE':
                    raise Rejected('SOURCE_INVALID')
                original = connection.execute("SELECT * FROM conversation_messages WHERE id=? AND requirement_id=? AND role='ASSISTANT' AND message_type='INTERACTION_CARDS'",
                    (row['reply_to_message_id'], requirement_id)).fetchone()
                if original is None:
                    raise Rejected('SOURCE_INVALID')
                answers = resources.validate('StoredResponses', json.loads(row['structured_content_json']))
                cards = resources.validate('StoredCardGroup', json.loads(original['structured_content_json']))
                if not any(answer['card_key'] == source['card_key'] and not answer['skipped'] for answer in answers['responses']) or not any(card['card_key'] == source['card_key'] for card in cards['cards']):
                    raise Rejected('SOURCE_INVALID')
        elif kind == 'REVISION':
            row = connection.execute("SELECT r.block_state_snapshot_json FROM revisions r JOIN requirement_documents d ON d.id=r.document_id WHERE r.id=? AND r.document_id=? AND r.requirement_id=? AND d.document_type='CURRENT'",
                (source['revision_id'], source['document_id'], requirement_id)).fetchone()
            if row is None:
                raise Rejected('SOURCE_INVALID')
            ids = source['block_ids']
            if ids is not None and (len(set(ids)) != len(ids) or not set(ids) <= {block['block_id'] for block in json.loads(row['block_state_snapshot_json'])['blocks']}):
                raise Rejected('SOURCE_INVALID')
        else:
            run = connection.execute('SELECT * FROM guide_runs WHERE id=? AND requirement_id=?', (source['guide_run_id'], requirement_id)).fetchone()
            if run is None:
                raise Rejected('SOURCE_INVALID')
            if kind == 'RUN_RESULT':
                output = None if run['final_result_json'] is None else json.loads(run['final_result_json'])
                if run['status'] != 'COMPLETED' or type(output) is not dict or output.get('analysis') is None:
                    raise Rejected('SOURCE_INVALID')
                resources.validate('Analysis', output['analysis'])
            else:
                found = False
                for row in connection.execute('SELECT request_snapshot_json FROM llm_uses WHERE guide_run_id=?', (run['id'],)):
                    snapshot = json.loads(row['request_snapshot_json'])
                    basis = snapshot.get('context_basis')
                    if basis is None:
                        continue
                    basis = resources.validate('ContextBasis', basis)
                    matches = [item for item in basis['selected'] if item['ref'] == source['material_ref']]
                    if len(matches) == 1:
                        found = True
                if not found:
                    raise Rejected('SOURCE_INVALID')
    return refs
