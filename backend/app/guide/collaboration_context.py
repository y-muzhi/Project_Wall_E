"""V1.5 fixed execution basis -> Canonical -> private basis and exact Wire.

Selection uses explicit identities and topic dependencies. It never queries a
model, guesses relevance from text, or changes the accepted write authority.
"""
from dataclasses import dataclass
import json

from backend.app.documents.markdown import parse_markdown
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.collaboration_resources import sha256
from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES, AuditCapacityExceeded
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.schema_transport import compact
from backend.app.requirements.discussion import validate_discussion
from backend.app.shared.command_execution import Rejected


KINDS = {'REQUIREMENT_BRIEF': 'brief', 'DESIGN': 'design', 'SPECIFICATION': 'specification'}
RAW_FIELDS = ('sequence_no', 'role', 'message_type', 'content', 'structured_content_json', 'reply_to_message_id')


def raw_message(row):
    value = {'message_id': row['id'], **{key: row[key] for key in RAW_FIELDS}}
    if row['message_type'] == 'CARD_RESPONSE':
        # A persistence summary is not a second copy of the formal answer.
        value['content'] = ''
    return value


def message_ref(identity):
    return 'm' + str(identity)


def document_ref(identity, version):
    return 'd' + str(identity) + 'v' + str(version)


def source_key(source):
    return compact({key: source[key] for key in sorted(source)})


def read_canonical(connection, identity, catalog, *, require_current=True):
    """One read snapshot, frozen facts plus explicit current-owner rechecks."""
    run = GuideRepository(connection).get(identity)
    if run is None:
        raise Rejected('NOT_FOUND')
    if run['function_type'] != 'collaboration_v1' or run['execution_basis_json'] is None:
        raise Rejected('SOURCE_INVALID')
    root = RequirementRepository(connection).get(run['requirement_id'])
    if root is None:
        raise Rejected('SOURCE_INVALID')
    if run['status'] == 'RUNNING' and require_current:
        if (root['document_work_state'], root['active_operation_type'], root['active_operation_id']) != ('GUIDE_ACTIVE', 'GUIDE_RUN', identity):
            raise Rejected('WORK_STATE_CONFLICT')
        if root['discussion_version'] != run['discussion_version_snapshot']:
            raise Rejected('DISCUSSION_VERSION_CONFLICT')
    accepted = json.loads(run['execution_basis_json'])
    resources = catalog.collaboration
    discussion = validate_discussion(accepted['discussion'], resources)
    if accepted['discussion_version'] != run['discussion_version_snapshot'] or accepted['requirement']['id'] != root['id']:
        raise Rejected('SOURCE_INVALID')
    request = accepted['request']
    if request['operation'] != run['operation'] or accepted['user_message']['id'] != run['trigger_message_id']:
        raise Rejected('SOURCE_INVALID')
    actual = connection.execute('SELECT * FROM conversation_messages WHERE id=? AND requirement_id=?', (run['trigger_message_id'], root['id'])).fetchone()
    if actual is None or raw_message(actual) != raw_message(accepted['user_message']):
        raise Rejected('SOURCE_INVALID')
    documents = {}
    messages = {}
    materials = []
    def add_message(row):
        value = raw_message(row)
        previous = messages.setdefault(value['message_id'], value)
        if previous != value:
            raise Rejected('SOURCE_INVALID')
        if value['message_type'] == 'CARD_RESPONSE':
            original = connection.execute("SELECT * FROM conversation_messages WHERE id=? AND requirement_id=? AND role='ASSISTANT' AND message_type='INTERACTION_CARDS'", (value['reply_to_message_id'], root['id'])).fetchone()
            if original is None:
                raise Rejected('SOURCE_INVALID')
            messages.setdefault(original['id'], raw_message(original))
    def add_document(row, current=False):
        if not current:
            row = {**row, 'content_version': row['source_content_version'], 'markdown_content': row['markdown_snapshot'], 'block_state_json': row['block_state_snapshot_json']}
        identity = row['id'] if current else row['document_id']
        version = row['content_version']
        revision = row['current_revision_id'] if current else row['id']
        state = row['block_state_json'] if isinstance(row['block_state_json'], dict) else json.loads(row['block_state_json'])
        verifier = DocumentSources(connection, root['id'], catalog, document_id=identity)
        snapshot = validate_snapshot(row['markdown_content'], state, verifier)
        ref = document_ref(identity, version)
        sections, blocks, stack = [], [], []
        authorization = accepted['authorization']
        allowed = {item['block_id'] for item in authorization['allowed_targets']} if (authorization['target_document_id'], authorization['expected_content_version']) == (identity, version) else set()
        for block_id, (block, _) in snapshot.by_id.items():
            if block.heading_level is not None:
                while stack and stack[-1]['level'] >= block.heading_level:
                    stack.pop()
                section = {'section_ref': ref+'s'+str(block_id), 'heading_block_id': block_id, 'level': block.heading_level,
                    'title': block.plain_text, 'parent_ref': None if not stack else stack[-1]['section_ref']}
                sections.append(section);stack.append(section)
            blocks.append({'ref': ref+'b'+str(block_id), 'block_id': block_id, 'block_type': block.block_type,
                'section_ref': None if not stack else stack[-1]['section_ref'], 'markdown_content': block.markdown,
                'writable': block_id in allowed})
        value = {'document_id': identity, 'revision_id': revision, 'content_version': version, 'name': row['name'],
            'document_kind': KINDS[row['document_kind']], 'markdown_content': snapshot.parsed.markdown,
            'block_state': state, 'blocks': blocks, 'sections': sections}
        key = identity, version
        if documents.setdefault(key, value) != value:
            raise Rejected('SOURCE_INVALID')
    target = accepted['target_document']
    if target is not None:
        if run['status'] == 'RUNNING' and require_current:
            head = DocumentRepository(connection).get_current(root['id'], target['id'])
            if head is None or head['content_version'] != target['content_version']:
                raise Rejected('CONTENT_VERSION_CONFLICT')
            if request['operation'] in ('REVISE', 'PROPOSE_CHANGES') and head['archived_at'] is not None:
                raise Rejected('STATE_CONFLICT')
        add_document(target, True)
    for item in accepted['source_snapshots']:
        kind, value = item['source_ref']['kind'], item['value']
        if kind in ('MESSAGE', 'CARD_ANSWER'):
            add_message(value['message'])
        elif kind == 'REVISION':
            add_document(value)
        else:
            materials.append({'source_ref': item['source_ref'], 'content': compact(value)})
    for row in accepted['recent_messages']:
        if row['sequence_no'] < actual['sequence_no']:
            add_message(row)
    add_message(actual)
    all_refs = [item['source_ref'] for item in accepted['source_snapshots']]
    comment = accepted.get('comment_source')
    if comment is not None:
        if run['source_type'] != 'COMMENT' or run['source_id'] != comment['id'] or comment['requirement_id'] != root['id'] or accepted['authorization']['target_document_id'] != comment['document_id']:
            raise Rejected('SOURCE_INVALID')
        # A source kind is not added to SourceRef. This actual run's frozen
        # comment anchor becomes a selected RUN_MATERIAL in its saved request.
        # The original comment text is already the real current user message.
        source = {'kind': 'RUN_MATERIAL', 'guide_run_id': run['id'], 'material_ref': 'comment_anchor'}
        anchor = {'comment_id': comment['id'], **{key: comment[key] for key in ('document_id', 'anchor_type', 'block_id', 'anchor_ref', 'updated_at')}}
        materials.append({'source_ref': source, 'content': compact({'material_ref': 'comment_anchor', 'documents': [], 'messages': [], 'texts': [], 'comment_anchor': anchor})})
        all_refs.append(source)
    resource_contents = []
    for reference in accepted['resources'].values():
        if reference is not None:
            content = resources.content(reference)
            try:
                json.loads(content);media_type = 'application/json'
            except ValueError:
                media_type = 'text/plain'
            resource_contents.append({'resource_ref': reference, 'media_type': media_type, 'content_text': content})
    candidates = [row for row in accepted['recent_messages'] if row['sequence_no'] < actual['sequence_no']]
    history_candidates = [{'ref': message_ref(row['id']), 'kind': 'MESSAGE', 'document_id': None, 'revision_id': None, 'content_version': None,
        'block_ids': [], 'message_ids': [row['id']], 'source_refs': [{'kind': 'MESSAGE', 'message_id': row['id']}],
        'roles': ['HISTORY'], 'required': False, 'reason': 'RECENT_WINDOW_CANDIDATE'} for row in candidates]
    canonical = {'schema_version': 1, 'layout_version': 'collaboration_context_v1',
        'requirement': {key: accepted['requirement'][key] for key in ('id', 'title', 'requirement_type', 'status', 'metadata_version', 'discussion_version', 'initial_message_id')},
        'discussion': discussion, 'operation': request['operation'], 'target': request['target'], 'scope': request['scope'],
        'source_refs': all_refs, 'current_message': raw_message(actual),
        'messages': sorted((row for row in messages.values() if row['message_id'] != actual['id']), key=lambda row: row['sequence_no']),
        'documents': list(documents.values()), 'run_materials': materials, 'resources': resource_contents,
        'authorization': accepted['authorization'], 'selected': history_candidates, 'omitted': []}
    return resources.validate('Canonical', canonical)


@dataclass(frozen=True)
class CollaborationContext:
    system: str
    input_json: str
    basis_json: str
    manifest_json: str

    @property
    def input(self):
        return json.loads(self.input_json)

    @property
    def basis(self):
        return json.loads(self.basis_json)

    @property
    def canonical(self):
        return self.basis['canonical']

    @property
    def texts(self):
        wire = self.input
        # Inner field order is the order restored from the actual Wire bytes.
        part = lambda name: compact(wire[name]) if wire[name] else ''
        return (self.system, self.input_json, compact(wire['current_request']), part('structure'), part('documents'),
            part('recent_history'), part('goal_and_decisions'), compact({key: wire[key] for key in ('project_position', 'current_topic')}))


def compile_context(canonical, catalog, *, omit_history=False, omit_background=False):
    resources = catalog.collaboration
    canonical = resources.validate('Canonical', canonical)
    validate_discussion(canonical['discussion'], resources)
    for content in canonical['resources']:
        if resources.content(content['resource_ref']) != content['content_text']:
            raise Rejected('CONFIG_INVALID')
    discussion = canonical['discussion'];phase = discussion['phase']
    guide = resources.guide(phase['kind'])
    messages = {row['message_id']: row for row in [*canonical['messages'], canonical['current_message']]}
    current = canonical['current_message'];current_ref = message_ref(current['message_id'])
    aliases, selected, omitted = {}, [], []
    def alias(ref, sources, evidence=None):
        row = {'ref': ref, 'source_refs': sources, 'evidence_ref': evidence}
        if ref in aliases and aliases[ref] != row:
            raise Rejected('SOURCE_INVALID')
        aliases[ref] = row
        return ref
    def material(ref, kind, sources, roles, reason, *, required=True, document=None, block_ids=(), message_ids=()):
        selected.append({'ref': ref, 'kind': kind, 'document_id': None if document is None else document['document_id'],
            'revision_id': None if document is None else document['revision_id'], 'content_version': None if document is None else document['content_version'],
            'block_ids': list(block_ids), 'message_ids': list(message_ids), 'source_refs': sources, 'roles': roles, 'required': required, 'reason': reason})
    def omit(ref, sources, reason, replacement=None):
        omitted.append({'ref': ref, 'source_refs': sources, 'reason': reason, 'replaced_by': replacement})
    def formal(row):
        if row['message_type'] != 'CARD_RESPONSE':
            return None
        stored = resources.validate('StoredResponses', json.loads(row['structured_content_json']))
        original = messages.get(row['reply_to_message_id'])
        if original is None:
            raise Rejected('SOURCE_INVALID')
        group = resources.validate('StoredCardGroup', json.loads(original['structured_content_json']))
        cards = {card['card_key']: card for card in group['cards']}
        values = []
        for answer in stored['responses']:
            card = cards.get(answer['card_key'])
            if card is None:
                raise Rejected('SOURCE_INVALID')
            options = {option['option_key']: option for option in card['options']}
            if any(key not in options for key in answer['selected_option_keys']):
                raise Rejected('SOURCE_INVALID')
            values.append({'card_key': card['card_key'], 'question': card['question'],
                'selected_options': [{'option_key': key, 'label': options[key]['label']} for key in answer['selected_option_keys']],
                'custom_answer': answer['custom_answer'], 'skipped': answer['skipped']})
        return values
    def message_alias(row):
        ref = alias(message_ref(row['message_id']), [{'kind': 'MESSAGE', 'message_id': row['message_id']}])
        answers = formal(row)
        if answers:
            for answer in answers:
                alias(ref+':'+answer['card_key'], [{'kind': 'CARD_ANSWER', 'message_id': row['message_id'], 'card_key': answer['card_key']}])
        return ref, answers
    # Alias registration is independent of where original text is emitted.
    for row in sorted(messages.values(), key=lambda row: row['sequence_no']):
        message_alias(row)
    represented = {current_ref}
    current_answers = formal(current)
    if current_answers:
        represented.update(current_ref+':'+answer['card_key'] for answer in current_answers)
        represented.add(message_ref(current['reply_to_message_id']))
    material(current_ref, 'MESSAGE' if current_answers is None else 'CARD_ANSWER', aliases[current_ref]['source_refs'], ['CURRENT'], 'CURRENT_REQUEST', message_ids=[current['message_id']])
    goal, wire_documents = [], []
    target = canonical['target'];scope = canonical['scope']
    for document in canonical['documents']:
        ref = document_ref(document['document_id'], document['content_version'])
        is_target = target is not None and target['kind'] == 'EXISTING' and target['document_id'] == document['document_id'] and target['expected_content_version'] == document['content_version']
        sources = [source for source in canonical['source_refs'] if source['kind'] == 'REVISION' and source['document_id'] == document['document_id'] and source['revision_id'] == document['revision_id']]
        required, background = set(), set()
        if is_target:
            if scope is None or scope['scope_type'] == 'DOCUMENT':
                required.update(block['block_id'] for block in document['blocks'])
            else:
                snapshot = validate_snapshot(document['markdown_content'], document['block_state'], lambda _: True)
                reference = scope['scope_ref']
                if scope['scope_type'] == 'SECTION':
                    reference = {'block_id': reference['heading_block_id']}
                resolved = resolve_scope(snapshot, 'REVIEW', scope['scope_type'], reference)
                required.update(resolved.focus_ids)
                # Ancestor titles are navigation, not duplicate read bodies.
                background.update(set(resolved.read_ids) - set(resolved.required_read_ids))
        for source in sources:
            required.update((block['block_id'] for block in document['blocks']) if source['block_ids'] is None else source['block_ids'])
        background -= required
        roles = (['TARGET'] if is_target else []) + (['REFERENCE'] if sources else [])
        if not roles:
            raise Rejected('SOURCE_INVALID')
        required_ids = [block['block_id'] for block in document['blocks'] if block['block_id'] in required]
        source = {'kind': 'REVISION', 'document_id': document['document_id'], 'revision_id': document['revision_id'], 'block_ids': required_ids}
        alias(ref, [source]);material(ref, 'REVISION', [source], roles, 'TARGET_AND_FIXED_SOURCES' if is_target else 'FIXED_SOURCE', document=document, block_ids=required_ids)
        blocks = []
        for block in document['blocks']:
            identity = block['block_id']
            if identity not in required | background:
                continue
            block_source = {**source, 'block_ids': [identity]}
            alias(block['ref'], [block_source])
            if identity in background:
                if omit_background:
                    omit(block['ref'], [block_source], 'BUDGET_OPTIONAL_BACKGROUND');continue
                material(block['ref'], 'REVISION', [block_source], roles, 'OPTIONAL_NEIGHBOR', required=False, document=document, block_ids=[identity])
            blocks.append(block)
        # Navigation ancestors of selected blocks only; no unrelated outline.
        section_index = {section['section_ref']: section for section in document['sections']}
        section_refs = set()
        for block in blocks:
            section_ref = block['section_ref']
            while section_ref is not None and section_ref not in section_refs:
                section_refs.add(section_ref);section_ref = section_index[section_ref]['parent_ref']
        wire_documents.append({key: document[key] for key in ('document_id', 'revision_id', 'content_version', 'name', 'document_kind')} |
            {'ref': ref, 'roles': roles, 'coverage': 'FULL' if len(blocks) == len(document['blocks']) else 'PARTIAL',
             'sections': [section for section in document['sections'] if section['section_ref'] in section_refs], 'blocks': blocks})
    def resolve(source):
        kind = source['kind']
        if kind in ('MESSAGE', 'CARD_ANSWER'):
            ref = message_ref(source['message_id']) + (':'+source['card_key'] if kind == 'CARD_ANSWER' else '')
        elif kind == 'REVISION':
            document = next((row for row in canonical['documents'] if row['document_id'] == source['document_id'] and row['revision_id'] == source['revision_id']), None)
            if document is None:
                raise Rejected('SOURCE_INVALID')
            ref = document_ref(document['document_id'], document['content_version'])
        else:
            ref = 'r'+str(source['guide_run_id'])+':'+('result' if kind == 'RUN_RESULT' else source['material_ref'])
            alias(ref, [source])
        if ref not in aliases:
            raise Rejected('SOURCE_INVALID')
        return ref
    for item in canonical['run_materials']:
        resolve(item['source_ref'])
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
    def goal_message(identity, reason, card_key=None):
        row = messages.get(identity)
        if row is None:
            raise Rejected('SOURCE_INVALID')
        ref, answers = message_alias(row)
        sources = [{'kind': 'MESSAGE', 'message_id': identity}]
        if card_key is not None:
            ref += ':'+card_key;sources = [{'kind': 'CARD_ANSWER', 'message_id': identity, 'card_key': card_key}]
            answers = [answer for answer in answers or [] if answer['card_key'] == card_key]
            if not answers:
                raise Rejected('SOURCE_INVALID')
        if ref in represented:
            omit(ref, sources, 'DUPLICATE', ref)
            # Keep one short goal ref for the original/current identity.
            if not any(item['ref'] == ref for item in goal):
                goal.append({'ref': ref, 'origin': 'USER_STATEMENT', 'text': None, 'source_refs': [ref], 'nature': 'FACT', 'applies_to': 'GLOBAL'})
            return
        if answers is not None:
            answers = [answer for answer in answers if message_ref(identity)+':'+answer['card_key'] not in represented]
            text = compact(answers) if answers else None
            represented.update(message_ref(identity)+':'+answer['card_key'] for answer in answers)
            represented.add(message_ref(row['reply_to_message_id']))
        else:
            text = row['content'] or None
        represented.add(ref)
        material(ref, sources[0]['kind'], sources, ['EVIDENCE'], reason, message_ids=[identity])
        goal.append({'ref': ref, 'origin': 'USER_STATEMENT' if row['role'] == 'USER' else 'AI_PROPOSAL', 'text': text, 'source_refs': [ref], 'nature': 'FACT' if row['role'] == 'USER' else 'PROPOSAL', 'applies_to': 'GLOBAL'})
    goal_message(canonical['requirement']['initial_message_id'], 'INITIAL_GOAL')
    for source in canonical['source_refs']:
        if source['kind'] in ('MESSAGE', 'CARD_ANSWER'):
            goal_message(source['message_id'], 'FIXED_OR_LONG_TERM_INPUT', source.get('card_key'))
    for identity in discussion['pending_user_message_ids']:
        goal_message(identity, 'PENDING_INPUT')
    for item in evidence:
        ref = alias(item['evidence_ref'], item['source_refs'], item['evidence_ref'])
        material(ref, 'EVIDENCE', item['source_refs'], ['EVIDENCE'], 'RELEVANT_ACTIVE_OR_DISPUTED_EVIDENCE')
        goal.append({'ref': ref, 'origin': item['origin'], 'text': item['assertion'], 'source_refs': [resolve(source) for source in item['source_refs']], 'nature': item['nature'], 'applies_to': item['applies_to']})
    for item in canonical['run_materials']:
        source = item['source_ref'];ref = resolve(source)
        value = json.loads(item['content'])
        material_document = None;material_blocks = [];material_messages = []
        if source['kind'] == 'RUN_MATERIAL':
            transmitted = {(document['document_id'], document['content_version'], block['block_id']): block
                for document in wire_documents for block in document['blocks']}
            for document in value['documents']:
                material_document = document
                for index, block in enumerate(document['blocks']):
                    material_blocks.append(block['block_id'])
                    other = transmitted.get((document['document_id'], document['content_version'], block['block_id']))
                    if other is not None and other['markdown_content'] == block['markdown_content']:
                        document['blocks'][index] = {'ref': other['ref']}
            for message in value['messages']:
                old_ref = message['ref']
                if old_ref.startswith('m') and old_ref[1:].isdigit():
                    material_messages.append(int(old_ref[1:]))
                if old_ref in represented:
                    message['content'] = None;message['formal_answers'] = None
                elif message['formal_answers']:
                    message['formal_answers'] = [answer for answer in message['formal_answers'] if old_ref+':'+answer['card_key'] not in represented] or None
                if message['content'] is not None or message['formal_answers']:
                    represented.add(old_ref)
                    represented.update(old_ref+':'+answer['card_key'] for answer in message['formal_answers'] or [])
            visible_texts = {entry['ref']: entry['text'] for entry in goal}
            for text in value['texts']:
                if text['ref'] in visible_texts and text['text'] == visible_texts[text['ref']]:
                    text['text'] = None
                elif text['text'] is not None:
                    represented.add(text['ref'])
            anchor = value.get('comment_anchor')
            if anchor is not None and anchor['anchor_type'] == 'BLOCK':
                other = next((block for document in wire_documents if document['document_id'] == anchor['document_id']
                    for block in document['blocks'] if block['block_id'] == anchor['block_id']), None)
                if other is not None and anchor['anchor_ref']['block_markdown_snapshot'] == other['markdown_content']:
                    anchor['anchor_ref'] = {'block_ref': other['ref']}
        material(ref, source['kind'], [source], ['REFERENCE'], 'EXPLICIT_RUN_SOURCE', document=material_document,
            block_ids=material_blocks, message_ids=material_messages)
        goal.append({'ref': ref, 'origin': 'USER_STATEMENT' if 'comment_anchor' in value else 'AI_PROPOSAL', 'text': compact(value), 'source_refs': [ref],
            'nature': 'FACT' if 'comment_anchor' in value else 'PROPOSAL', 'applies_to': 'GLOBAL'})
    history = []
    history_ids = {identity for item in canonical['selected'] if item['reason'] == 'RECENT_WINDOW_CANDIDATE' for identity in item['message_ids']}
    candidates = [row for row in canonical['messages'] if row['message_id'] in history_ids]
    # Original card records loaded for answer validation are not extra history.
    # Formal answers own their question/selected text; their original card
    # remains private validation evidence rather than a second question body.
    answer_parents = {row['reply_to_message_id'] for row in candidates if row['message_type'] == 'CARD_RESPONSE'}
    for row in candidates:
        ref, answers = message_alias(row)
        sources = aliases[ref]['source_refs']
        if ref in represented or row['message_id'] in answer_parents:
            omit(ref, sources, 'DUPLICATE', ref);continue
        if answers is not None:
            answers = [answer for answer in answers if ref+':'+answer['card_key'] not in represented]
            if not answers:
                omit(ref, sources, 'DUPLICATE', ref);continue
        if omit_history:
            omit(ref, sources, 'BUDGET_OPTIONAL_HISTORY');continue
        history.append({'ref': ref, 'role': row['role'], 'content': row['content'] or None if answers is None else None,
            'formal_answers': answers, 'cards_ref': ref if row['message_type'] == 'INTERACTION_CARDS' else None})
        material(ref, 'MESSAGE' if answers is None else 'CARD_ANSWER', sources, ['HISTORY'], 'RECENT_WINDOW', required=False, message_ids=[row['message_id']])
    mainlines = []
    for line in guide['mainlines']:
        current_topics = [topic for topic in topics.values() if topic['phase_ref'] == phase['phase_ref'] and topic['mainline_ref'] == line['ref']]
        assessments = {topic['assessment'] for topic in current_topics}
        assessment = 'REVIEW_REQUIRED' if 'REVIEW_REQUIRED' in assessments else 'SUPPORTED' if assessments == {'SUPPORTED'} else 'DISCUSSING' if current_topics else 'NOT_STARTED'
        mainlines.append({'ref': line['ref'], 'summary': '；'.join(topic['title'] for topic in current_topics)[:1000], 'assessment': assessment})
    focus = topics.get(discussion['focus_topic_ref'])
    topic = None if focus is None else {'topic_ref': focus['topic_ref'], 'purpose': focus['purpose'], 'expected_outcomes': focus['expected_outcomes'],
        'evidence_refs': focus['evidence_refs'], 'dependency_refs': focus['dependencies'], 'unresolved_impacts': focus['unresolved_impacts']}
    structure = _structure(canonical, catalog)
    wire = {'schema_version': 1, 'structure': structure, 'goal_and_decisions': goal,
        'project_position': {'phase_kind': phase['kind'], 'phase_ref': phase['phase_ref'], 'focus_topic_ref': discussion['focus_topic_ref'], 'mainlines': mainlines,
            'dispositions': [{key: item[key] for key in ('kind', 'scope_refs', 'summary')} | {'message_ref': message_ref(item['message_id'])} for item in discussion['dispositions']]},
        'current_topic': topic, 'documents': wire_documents, 'recent_history': history,
        'current_request': {'message_id': current['message_id'], 'message_ref': current_ref, 'content': current['content'] if current_answers is None else None,
            'formal_answers': current_answers, 'operation': canonical['operation'], 'target': target, 'scope': scope,
            'source_refs': list(dict.fromkeys(resolve(source) for source in canonical['source_refs'])),
            'basis_ref': {'discussion_version': canonical['requirement']['discussion_version'], 'phase_ref': phase['phase_ref'], 'guide_key': guide['key'], 'guide_version': guide['version']}}}
    # Canonical retains the fixed candidate set, so a saved basis can replay
    # every budget candidate without rereading an expanded history window.
    # The actual transmitted selection belongs to ContextBasis.selected.
    canonical_text = resources.serialize('Canonical', canonical)
    wire_text = resources.serialize('Wire', wire)
    system = resources.system(phase['kind'], canonical['operation'])
    basis = {'schema_version': 1, 'canonical': canonical, 'aliases': list(aliases.values()), 'canonical_sha256': sha256(canonical_text),
        'wire_sha256': sha256(wire_text), 'system_sha256': sha256(system), 'output_schema_sha256': sha256(resources.output_schema(canonical['operation'])),
        'selected': selected, 'omitted': omitted}
    basis_text = resources.serialize('ContextBasis', basis)
    # The same normal audit capacity applies before any count or Chat I/O.
    if len(compact({'context_basis': json.loads(basis_text), 'request': {'system': system, 'user': wire_text}}).encode('utf-8')) > MAX_AUDIT_BYTES:
        raise AuditCapacityExceeded('Collaboration snapshot exceeds the normal audit capacity')
    return CollaborationContext(system, wire_text, basis_text, canonical_input({'selected': selected, 'omitted': omitted}))


def _structure(canonical, catalog):
    operation, target, scope = canonical['operation'], canonical['target'], canonical['scope']
    if operation not in ('GENERATE', 'REVISE') or target is None:
        return None
    resources = catalog.collaboration
    kind = target['document_kind'] if target['kind'] == 'NEW' else next(document['document_kind'] for document in canonical['documents'] if document['document_id'] == target['document_id'] and document['content_version'] == target['expected_content_version'])
    profile = resources.structure(kind)
    template = None
    rules = list(profile['rules'])
    if kind != 'specification':
        rules.append('章节结构：'+'；'.join(profile['headings']))
    else:
        fixed = catalog.template('NEW', profile['template_ref']['key'], profile['template_ref']['version'])
        if operation == 'GENERATE':
            template = {'key': fixed.key, 'version': fixed.version, 'markdown_content': fixed.markdown}
        elif scope is not None and scope['scope_type'] != 'DOCUMENT':
            # Actual template section boundaries, retaining global invariants.
            parsed = parse_markdown(fixed.markdown)
            document = next(document for document in canonical['documents'] if document['document_id'] == target['document_id'] and document['content_version'] == target['expected_content_version'])
            ids = {entry['block_id'] for entry in canonical['authorization']['allowed_targets']}
            paths = [metadata['section_path'] for metadata in document['block_state']['blocks'] if metadata['block_id'] in ids]
            headings = {path[0] for path in paths if path}
            parts = [block.markdown for block in parsed.blocks if block.section_path and block.section_path[0] in headings]
            if parts:
                template = {'key': fixed.key, 'version': fixed.version, 'markdown_content': '\n\n'.join(parts)}
    return {'profile': kind, 'key': profile['key'], 'version': profile['version'], 'rules': rules, 'template': template}
