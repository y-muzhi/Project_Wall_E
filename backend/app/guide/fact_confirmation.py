"""Exact proposed fact bundle proof; proposing is separate from C06 adoption."""
import json

from backend.app.documents.patch_application import preview_patches
from backend.app.documents.patch_validation import validate_bundle
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.messages.cards import CardsInvalid


def validate_fact_action(connection, root, run, context, payload, catalog):
    canonical = context.canonical;target = canonical['target'];scope = canonical['scope']
    if target is None or target['kind'] != 'EXISTING' or scope is None:
        raise CardsInvalid('Fact confirmation requires its fixed actual target and scope')
    current = DocumentRepository(connection).get_current(root['id'], target['document_id'])
    if current is None or current['content_version'] != target['expected_content_version'] or current['archived_at'] is not None:
        raise CardsInvalid('Fact target changed or is unavailable')
    snapshot = validate_snapshot(current['markdown_content'], json.loads(current['block_state_json']), DocumentSources(connection, root['id'], catalog, document_id=current['id']))
    reference = scope['scope_ref']
    if scope['scope_type'] == 'SECTION':
        reference = {'block_id': reference['heading_block_id']}
    # This is only the ceiling for the proposed exact bundle. It grants no
    # current write permission; C06 requires a real formal confirmation.
    authority = resolve_scope(snapshot, 'MODIFY', scope['scope_type'], reference)
    facts = payload['confirmed_fact_patches']
    checked = validate_bundle(snapshot, [item['patch'] for item in facts], authority)
    read_ids = {block['block_id'] for document in context.input['documents'] if document['document_id'] == current['id'] and document['content_version'] == current['content_version'] for block in document['blocks']}
    messages = {message['message_id']: message for message in [canonical['current_message'], *canonical['messages']]}
    carried_ids = {identity for item in context.basis['selected'] for identity in item['message_ids']}
    # Only actual USER text is a source. Formal answers may quote the selected
    # label/custom value, never the synthesized persistence summary or options.
    provided = {}
    for message in [context.input['current_request'], *context.input['recent_history']]:
        ref = message.get('message_ref', message.get('ref'))
        if ref is None or not ref.startswith('m') or not ref[1:].isdigit():
            continue
        identity = int(ref[1:]);row = messages.get(identity)
        if row is None or row['role'] != 'USER':
            continue
        texts = [message['content']] if message['content'] is not None else []
        for answer in message['formal_answers'] or []:
            texts.extend(option['label'] for option in answer['selected_options'])
            if answer['custom_answer'] is not None:
                texts.append(answer['custom_answer'])
        provided[identity] = texts
    for item in context.input['goal_and_decisions']:
        if item['ref'].startswith('m') and item['ref'][1:].isdigit() and item['text'] is not None:
            identity = int(item['ref'][1:]);row = messages.get(identity)
            if row is not None and row['role'] == 'USER' and row['message_type'] == 'TEXT':
                provided.setdefault(identity, []).append(item['text'])
    for fact, patch in zip(facts, checked):
        if patch.target_id not in read_ids:
            raise CardsInvalid('Fact patch target was not actually carried')
        for evidence in fact['evidence']:
            identity = evidence['message_id']
            if identity not in carried_ids or not any(evidence['quoted_text'] in text for text in provided.get(identity, [])):
                raise CardsInvalid('Fact quotation is not exact actually carried USER evidence')
    preview = preview_patches(snapshot, [item['patch'] for item in facts], authority)
    from backend.app.documents.content import validate_structure
    validate_structure(preview, snapshot, current, catalog)
    return preview


def apply_confirmed_action(connection, root, original, response, cards, catalog, key, at):
    from .collaboration_counting import restore_counted, verify_counted
    from .collaboration_context import read_canonical
    from backend.app.infrastructure.model_profile import ModelProfile
    from backend.app.infrastructure.identifiers import EntityKind, entity_id
    from backend.app.infrastructure.requirement_repository import RequirementRepository
    from backend.app.documents.snapshot import Provenance
    from backend.app.documents.sources import register_edit_session, close_edit_session
    from backend.app.documents.patch_application import apply_confirmed_facts
    from backend.app.documents.manual_identity import ManualIdentityProofs
    from backend.app.documents.content import commit_content
    run = connection.execute('SELECT * FROM guide_runs WHERE id=? AND requirement_id=?', (original['guide_run_id'], root['id'])).fetchone()
    row = connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=? ORDER BY id DESC LIMIT 1', (run['id'],)).fetchone()
    if row is None or row['raw_response_json'] is None:
        raise CardsInvalid('Fact action has no actual frozen request')
    saved = json.loads(row['request_snapshot_json']);profile = ModelProfile.from_snapshot(saved['profile'])
    context = restore_counted(saved, catalog, profile)
    verify_counted(context, catalog, profile, expected_canonical=read_canonical(connection, run['id'], catalog, require_current=False))
    validate_fact_action(connection, root, run, context, cards['action_payload'], catalog)
    target = context.canonical['target'];scope = context.canonical['scope']
    documents = DocumentRepository(connection);roots = RequirementRepository(connection)
    current = documents.get_current(root['id'], target['document_id'])
    # Reuse the real manual session's source/identity proof and formal commit
    # mechanism. It starts and closes within this one transaction and never
    # becomes a separately visible, waiting editor or fake GuideRun.
    draft = documents.create_manual_draft(entity_id(connection, EntityKind.DOCUMENT), current, at)
    register_edit_session(connection, draft['id'], at)
    roots.occupy_manual_draft(root['id'], draft['id'], at)
    sources = DocumentSources(connection, root['id'], catalog, document_id=current['id'])
    snapshot = validate_snapshot(current['markdown_content'], json.loads(current['block_state_json']), sources)
    reference = scope['scope_ref']
    if scope['scope_type'] == 'SECTION':
        reference = {'block_id': reference['heading_block_id']}
    authority = resolve_scope(snapshot, 'MODIFY', scope['scope_type'], reference)
    candidate = apply_confirmed_facts(snapshot, [item['patch'] for item in cards['action_payload']['confirmed_fact_patches']], authority,
        None, at, sources, provenance=Provenance('USER', 'MANUAL_EDIT', draft['id']))
    proofs = ManualIdentityProofs(connection, draft['id']);baseline = proofs.baseline(sources)
    candidate = proofs.derive(candidate, snapshot, baseline, at, sources)
    refs = [{'kind': 'CARD_ANSWER', 'message_id': response['id'], 'card_key': cards['cards'][0]['card_key']}]
    quoted_ids = sorted({evidence['message_id'] for item in cards['action_payload']['confirmed_fact_patches'] for evidence in item['evidence']})
    refs.extend({'kind': 'MESSAGE', 'message_id': identity} for identity in quoted_ids)
    effect = commit_content(connection, current, candidate, resources=catalog, source_type='MANUAL_EDIT', source_id=draft['id'],
        source_refs=refs, summary='用户确认事实变更', key=key, at=at)
    documents.delete_manual_draft(draft)
    roots.release_manual_draft(root['id'], draft['id'], at)
    close_edit_session(connection, draft['id'], 'COMPLETED', at)
    return effect
