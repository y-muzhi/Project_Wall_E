"""C01 same-transaction immutable input capture, before any provider work.

This is the existing GuideRun's private execution basis, not a model prompt.
Canonical selection and Wire compilation consume these captured source values.
"""
import json

from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.documents.queries import current_document_view
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.documents.scopes import resolve_scope, ScopeInvalid
from backend.app.requirements.source_refs import verify_source_refs, saved_run_material
from backend.app.shared.command_execution import Rejected


def check_proposal(connection, root, request, resources):
    reference = request.proposal_ref
    if reference is None:
        return
    row = connection.execute("SELECT * FROM conversation_messages WHERE id=? AND requirement_id=? AND role='ASSISTANT' AND message_type='INTERACTION_CARDS'",
        (reference['message_id'], root['id'])).fetchone()
    if row is None:
        raise Rejected('SOURCE_INVALID')
    cards = resources.validate('StoredCardGroup', json.loads(row['structured_content_json']))
    if cards['purpose'] != 'DOCUMENT_ACTION' or not any(card['card_key'] == reference['card_key'] for card in cards['cards']):
        raise Rejected('SOURCE_INVALID')
    if connection.execute("SELECT 1 FROM conversation_messages WHERE reply_to_message_id=? AND message_type='CARD_RESPONSE'", (row['id'],)).fetchone():
        raise Rejected('SOURCE_INVALID')
    payload, binding = cards['action_payload'], cards['program_binding']
    if payload['operation'] != request.operation:
        raise Rejected('SOURCE_INVALID')
    if binding['discussion_version'] != root['discussion_version']:
        raise Rejected('DISCUSSION_VERSION_CONFLICT', details={'expected_version': binding['discussion_version'],
            'actual_version': root['discussion_version'], 'resource_kind': 'Requirement', 'resource_id': root['id']})
    for field in ('target', 'scope', 'source_refs'):
        if field not in payload['selectable_fields'] and canonical_input({'value': payload[field]}) != canonical_input({'value': getattr(request, field)}):
            raise Rejected('SOURCE_INVALID')
    for head in binding['source_heads']:
        current = DocumentRepository(connection).get_current(root['id'], head['document_id'])
        if current is None:
            raise Rejected('SOURCE_INVALID')
        if current['content_version'] != head['content_version'] and not request.acknowledge_source_changes:
            raise Rejected('SOURCE_VERSION_CONFLICT', details={'expected_version': head['content_version'],
                'actual_version': current['content_version'], 'resource_kind': 'RequirementDocument', 'resource_id': current['id']})


def capture_source(connection, root_id, source, resources):
    """Capture only the addressed record/material, never another run's authority."""
    kind = source['kind']
    if kind in ('MESSAGE', 'CARD_ANSWER'):
        row = dict(connection.execute('SELECT * FROM conversation_messages WHERE id=?', (source['message_id'],)).fetchone())
        row.pop('idempotency_key')
        result = {'message': row}
        if kind == 'CARD_ANSWER':
            original = dict(connection.execute('SELECT * FROM conversation_messages WHERE id=?', (row['reply_to_message_id'],)).fetchone())
            original.pop('idempotency_key');result['original_card'] = original
        return {'source_ref': source, 'value': result}
    if kind == 'REVISION':
        row = dict(connection.execute('SELECT * FROM revisions WHERE id=? AND requirement_id=?', (source['revision_id'], root_id)).fetchone())
        document = connection.execute('SELECT name,document_kind,template_ref FROM requirement_documents WHERE id=?', (row['document_id'],)).fetchone()
        return {'source_ref': source, 'value': {**row, **dict(document)}}
    run = connection.execute('SELECT * FROM guide_runs WHERE id=? AND requirement_id=?', (source['guide_run_id'], root_id)).fetchone()
    if kind == 'RUN_RESULT':
        return {'source_ref': source, 'value': {'analysis': json.loads(run['final_result_json'])['analysis']}}
    snapshot, basis, selected = saved_run_material(connection, root_id, source, resources)
    from backend.app.infrastructure.collaboration_resources import sha256
    wire_text = snapshot['request']['messages'][1]['content']
    if sha256(wire_text) != basis['wire_sha256']:
        raise Rejected('SOURCE_INVALID')
    wire = resources.validate('Wire', json.loads(wire_text))
    documents = []
    for document in wire['documents']:
        if document['document_id'] == selected['document_id'] and document['revision_id'] == selected['revision_id']:
            documents.append({'document_id': document['document_id'], 'revision_id': document['revision_id'],
                'content_version': document['content_version'], 'name': document['name'],
                'blocks': [{key: block[key] for key in ('block_id', 'block_type', 'section_ref', 'markdown_content')}
                    for block in document['blocks'] if block['block_id'] in selected['block_ids']]})
    aliases = {item['ref']: item for item in basis['aliases']}
    message_refs = {'m'+str(identity) for identity in selected['message_ids']}
    messages = []
    for message in [wire['current_request'], *wire['recent_history']]:
        ref = message.get('message_ref', message.get('ref'))
        if ref not in message_refs:
            continue
        answers = message['formal_answers']
        card_keys = {item['card_key'] for item in selected['source_refs'] if item['kind'] == 'CARD_ANSWER'}
        if answers is not None and card_keys:
            answers = [answer for answer in answers if answer['card_key'] in card_keys]
        messages.append({'ref': ref, 'content': message['content'], 'formal_answers': answers})
    texts = [{key: item[key] for key in ('ref', 'origin', 'text', 'nature', 'applies_to')}
        for item in wire['goal_and_decisions'] if item['ref'] == selected['ref'] or item['ref'] in message_refs]
    if selected['ref'] not in aliases:
        raise Rejected('SOURCE_INVALID')
    return {'source_ref': source, 'value': {'material_ref': selected['ref'], 'documents': documents, 'messages': messages, 'texts': texts}}


def capture_inputs(connection, root, request, catalog):
    resources = catalog.collaboration
    check_proposal(connection, root, request, resources)
    target, scope = request.target, request.scope
    document = None;authorization = {'operation': request.operation, 'target_document_id': None,
        'expected_content_version': None, 'scope': scope, 'allowed_targets': [], 'confirmed_fact_patches': []}
    if target is not None and target['kind'] == 'EXISTING':
        current = DocumentRepository(connection).get_current(root['id'], target['document_id'])
        if current is None:
            raise Rejected('SOURCE_INVALID')
        if current['content_version'] != target['expected_content_version']:
            raise Rejected('CONTENT_VERSION_CONFLICT')
        if request.operation in ('REVISE', 'PROPOSE_CHANGES') and current['archived_at'] is not None:
            raise Rejected('STATE_CONFLICT')
        document = current_document_view(connection, current, catalog)
        authorization.update(target_document_id=current['id'], expected_content_version=current['content_version'])
        if scope is not None:
            ref = scope['scope_ref']
            if scope['scope_type'] == 'SECTION':
                ref = {'block_id': ref['heading_block_id']}
            snapshot = validate_snapshot(document['markdown_content'], document['block_state_json'], DocumentSources(connection, root['id'], catalog, document_id=current['id']))
            try:
                resolved = resolve_scope(snapshot, 'MODIFY' if request.operation in ('REVISE', 'PROPOSE_CHANGES') else 'REVIEW', scope['scope_type'], ref)
            except ScopeInvalid:
                raise Rejected('SCOPE_INVALID') from None
            if request.operation in ('REVISE', 'PROPOSE_CHANGES'):
                authorization['allowed_targets'] = resolved.targets_json
    elif target is not None:
        if target['template_ref'] is not None:
            reference = resources.reference('structure.' + target['document_kind'])
            if target['template_ref'] != {key: reference[key] for key in ('key', 'version')}:
                raise Rejected('SOURCE_INVALID')
        resources.structure(target['document_kind'])
    discussion = root['discussion_state_json']
    topics = {topic['topic_ref']: topic for topic in discussion['topics']}
    relevant = set()
    def include(ref):
        if ref in relevant:
            return
        relevant.add(ref)
        for dependency in topics[ref]['dependencies']:
            include(dependency)
    if discussion['focus_topic_ref'] is not None:
        include(discussion['focus_topic_ref'])
    evidence_refs = {ref for topic_ref in relevant for ref in topics[topic_ref]['evidence_refs']}
    evidence = [item for item in discussion['evidence'] if item['state'] in ('ACTIVE', 'DISPUTED') and
        (item['evidence_ref'] in evidence_refs or item['applies_to'] == 'GLOBAL' or isinstance(item['applies_to'], list) and relevant.intersection(item['applies_to']))]
    refs = [*request.source_refs, *discussion['binding']['source_refs'], {'kind': 'MESSAGE', 'message_id': root['initial_message_id']},
        *({'kind': 'MESSAGE', 'message_id': identity} for identity in discussion['pending_user_message_ids']),
        *(source for item in evidence for source in item['source_refs'])]
    unique = {}
    for ref in refs:
        unique.setdefault(canonical_input(ref), ref)
    refs = list(unique.values());verify_source_refs(connection, root['id'], refs, resources=resources)
    history = [dict(row) for row in connection.execute("SELECT * FROM conversation_messages WHERE requirement_id=? AND role IN ('USER','ASSISTANT') ORDER BY sequence_no DESC LIMIT 10", (root['id'],))]
    for message in history:
        message.pop('idempotency_key')
    structure = None
    if target is not None and (request.operation == 'GENERATE' or request.operation == 'REVISE'):
        profile = target['document_kind'] if target['kind'] == 'NEW' else {'REQUIREMENT_BRIEF': 'brief', 'DESIGN': 'design', 'SPECIFICATION': 'specification'}[document['document_kind']]
        structure = resources.reference('structure.' + profile)
    # Capture disposition provenance too. A short project-position reference
    # must resolve to its actual user action, even outside the recent window.
    for disposition in discussion['dispositions']:
        source = {'kind': 'MESSAGE', 'message_id': disposition['message_id']}
        if canonical_input(source) not in unique:
            refs.append(source);unique[canonical_input(source)] = source
    return {'target_document': document, 'authorization': authorization, 'source_snapshots': [capture_source(connection, root['id'], source, resources) for source in refs],
        'recent_messages': list(reversed(history)),
        'relevant_topic_refs': [ref for ref in topics if ref in relevant], 'relevant_evidence_refs': [item['evidence_ref'] for item in evidence],
        'resources': {'release': resources.reference('collaboration.release'), 'guide': discussion['phase']['guide_ref'],
            'prompt': resources.release['prompt'], 'output_schema': resources.reference('collaboration.output.' + request.operation.lower()), 'counting': resources.release['counting'], 'structure': structure}}
