"""SHR-DISCUSSION value validation; no new aggregate or autonomous work queue."""

from functools import lru_cache
import re

from backend.app.infrastructure.collaboration_resources import CollaborationResources


@lru_cache(maxsize=1)
def discussion_resources():
    return CollaborationResources.load()


def empty_discussion(resources=None):
    state = {
        'schema_version': 2,
        'focus_topic_ref': None,
        'topics': [],
        'evidence': [],
        'pending_user_message_ids': [],
        'binding': {
            'target_document_id': None,
            'source_refs': [],
            'scope': None,
            'document_kind': None,
        },
        'dispositions': [],
        'last_step': None,
        'counters': {'topic': 1, 'evidence': 1},
    }
    return resources.validate('Discussion', state) if resources is not None else state


def validate_discussion(value, resources=None):
    resources = resources if resources is not None else discussion_resources()
    if value.get('schema_version') == 1 and resources.document_driven:
        from copy import deepcopy
        from backend.app.infrastructure.collaboration_resources import ROOT

        # Read-only projection of stored V1 data. No migration or phase command.
        historical = CollaborationResources.load(ROOT.parent / 'v15')
        value = deepcopy(historical.validate('Discussion', value))
        value['schema_version'] = 2
        value.pop('phase')
        value['counters'].pop('phase')
        for topic in value['topics']:
            topic.pop('phase_ref')
        if value['last_step'] and value['last_step']['value']['action'] == 'PROPOSE_PHASE_CHANGE':
            value['last_step'] = None
    state = resources.validate('Discussion', value)
    topics = {topic['topic_ref']: topic for topic in state['topics']}
    evidence = {item['evidence_ref']: item for item in state['evidence']}
    if len(topics) != len(state['topics']) or len(evidence) != len(state['evidence']):
        raise ValueError('Discussion references must be unique')
    if len(set(state['pending_user_message_ids'])) != len(state['pending_user_message_ids']):
        raise ValueError('Pending inputs must be unique')

    def local(ref, prefix):
        if re.fullmatch(prefix + r'[1-9][0-9]*', ref) is None:
            raise ValueError('Invalid local discussion identity')
        value = int(ref[1:])
        if value >= state['counters'][{'t': 'topic', 'e': 'evidence'}[prefix]]:
            raise ValueError('Discussion counter must exceed all allocated references')

    for topic in state['topics']:
        local(topic['topic_ref'], 't')
    for item in state['evidence']:
        local(item['evidence_ref'], 'e')
    focus = state['focus_topic_ref']
    if focus is not None and focus not in topics:
        raise ValueError('Focus must name an actual document topic')
    visited, active = set(), set()

    def visit(ref):
        if ref in active or ref not in topics:
            raise ValueError('Missing topic dependency or dependency cycle')
        if ref in visited:
            return
        active.add(ref)
        for dependency in topics[ref]['dependencies']:
            visit(dependency)
        active.remove(ref)
        visited.add(ref)

    for ref, topic in topics.items():
        visit(ref)
        if any(item not in evidence for item in topic['evidence_refs']):
            raise ValueError('Topic evidence is missing')
        outcomes = [item['outcome_ref'] for item in topic['expected_outcomes']]
        if len(set(outcomes)) != len(outcomes):
            raise ValueError('Topic outcomes must be unique')
    for item in evidence.values():
        if any(ref not in topics for ref in item['topic_refs']):
            raise ValueError('Evidence topic is missing')
        if any(ref not in evidence or ref == item['evidence_ref'] for ref in item['supersedes']):
            raise ValueError('Superseded evidence is missing or self-referencing')
        if item['applies_to'] != 'GLOBAL' and any(ref not in topics for ref in item['applies_to']):
            raise ValueError('Evidence applicability must reference actual topics')
    # Existence, ownership and user-decision provenance are checked by the
    # command's actual shared DB snapshot, not inferred from JSON shape.
    return state


def apply_user_command(connection, root, command, catalog):
    """Build a complete new value before writing any message or index."""
    from copy import deepcopy
    from backend.app.documents.drawing import is_drawing
    from backend.app.documents.scopes import resolve_scope, ScopeInvalid
    from backend.app.documents.snapshot import validate_snapshot
    from backend.app.documents.sources import DocumentSources
    from backend.app.infrastructure.document_repository import DocumentRepository
    from backend.app.shared.command_execution import Rejected
    from backend.app.shared.validation import strict_json_object
    from .source_refs import verify_source_refs

    resources = catalog.collaboration
    state = deepcopy(root['discussion_state_json'])
    kind = command['type']
    if kind == 'SET_BINDING':
        verify_source_refs(
            connection, root['id'], command['source_refs'], resources=resources, text_only=True
        )
        target = command['target_document_id']
        document_kind = None
        if target is None:
            if command['scope'] is not None:
                raise Rejected('SCOPE_INVALID')
        else:
            if target != root['assistant_document_id']:
                raise Rejected('SOURCE_INVALID')
            current = DocumentRepository(connection).get_current(root['id'], target)
            if current is None:
                raise Rejected('SOURCE_INVALID')
            if current['archived_at'] is not None:
                raise Rejected('STATE_CONFLICT')
            document_kind = {
                'REQUIREMENT_BRIEF': 'brief',
                'DESIGN': 'design',
                'SPECIFICATION': 'specification',
            }[current['document_kind']]
            if command['scope'] is not None:
                if is_drawing(current):
                    raise Rejected('SCOPE_INVALID')
                scope = command['scope']
                ref = scope['scope_ref']
                # Stored SECTION uses heading_block_id; the reused resolver's
                # input uses block_id and emits the same canonical scope.
                if scope['scope_type'] == 'SECTION':
                    ref = {'block_id': ref['heading_block_id']}
                snapshot = validate_snapshot(
                    current['markdown_content'],
                    strict_json_object(current['block_state_json']),
                    DocumentSources(connection, root['id'], catalog, document_id=target),
                )
                try:
                    resolve_scope(snapshot, 'ASK', scope['scope_type'], ref)
                except ScopeInvalid:
                    raise Rejected('SCOPE_INVALID') from None
        binding = {
            'target_document_id': target,
            'source_refs': command['source_refs'],
            'scope': command['scope'],
            'document_kind': document_kind,
        }
        if state['binding'] == binding:
            return state
        state['binding'] = binding
    elif kind == 'SET_FOCUS':
        if not any(topic['topic_ref'] == command['topic_ref'] for topic in state['topics']):
            raise Rejected('SOURCE_INVALID')
        if state['focus_topic_ref'] == command['topic_ref']:
            return state
        state['focus_topic_ref'] = command['topic_ref']
    else:
        raise ValueError('Unsupported discussion command')
    state['last_step'] = None
    return validate_discussion(state, resources)
