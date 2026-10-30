"""SHR-DISCUSSION value validation; no new aggregate or autonomous work queue."""

from functools import lru_cache
import re

from backend.app.infrastructure.collaboration_resources import CollaborationResources


@lru_cache(maxsize=1)
def discussion_resources():
    return CollaborationResources.load()


def empty_discussion(resources=None):
    resources = resources if resources is not None else discussion_resources()
    return {
        'schema_version': 1,
        'phase': {
            'phase_ref': 'p1',
            'kind': 'DISCOVERY',
            'guide_ref': resources.reference('collaboration.discovery'),
            'closure': None,
        },
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
        'counters': {'phase': 2, 'topic': 1, 'evidence': 1},
    }


def validate_discussion(value, resources=None):
    resources = resources if resources is not None else discussion_resources()
    state = resources.validate('Discussion', value)
    phase = state['phase']
    guide = resources.guide(phase['kind'])
    if phase['guide_ref'] != resources.reference(guide['key'], guide['version']):
        raise ValueError('Discussion phase resource identity differs')
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
        if value >= state['counters'][{'p': 'phase', 't': 'topic', 'e': 'evidence'}[prefix]]:
            raise ValueError('Discussion counter must exceed all allocated references')

    local(phase['phase_ref'], 'p')
    for topic in state['topics']:
        local(topic['topic_ref'], 't')
        local(topic['phase_ref'], 'p')
    for item in state['evidence']:
        local(item['evidence_ref'], 'e')
    focus = state['focus_topic_ref']
    if focus is not None and (
        focus not in topics or topics[focus]['phase_ref'] != phase['phase_ref']
    ):
        raise ValueError('Focus must belong to the current phase')
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


def discussion_references(connection, requirement_id, state):
    """Stable references established by state or real user phase events."""
    import json

    known = {
        state['phase']['phase_ref'],
        *(topic['topic_ref'] for topic in state['topics']),
        *(item['evidence_ref'] for item in state['evidence']),
        *(
            outcome['outcome_ref']
            for topic in state['topics']
            for outcome in topic['expected_outcomes']
        ),
    }
    for row in connection.execute(
        "SELECT payload_json FROM document_change_audits WHERE requirement_id=? AND event_type='PHASE_CHANGED'",
        (requirement_id,),
    ):
        event = json.loads(row['payload_json'])
        for field in ('phase_before', 'phase_after'):
            phase = event.get(field)
            if isinstance(phase, dict) and isinstance(phase.get('phase_ref'), str):
                known.add(phase['phase_ref'])
    return known


def apply_user_command(connection, root, command, message_id, catalog):
    """Build a complete new value before writing any message or index."""
    from copy import deepcopy
    from backend.app.documents.scopes import resolve_scope, ScopeInvalid
    from backend.app.documents.snapshot import validate_snapshot
    from backend.app.documents.sources import DocumentSources
    from backend.app.infrastructure.document_repository import DocumentRepository
    from backend.app.infrastructure.identifiers import increment
    from backend.app.shared.command_execution import Rejected
    from backend.app.shared.validation import strict_json_object
    from .source_refs import verify_source_refs

    resources = catalog.collaboration
    state = deepcopy(root['discussion_state_json'])
    kind = command['type']
    known = discussion_references(connection, root['id'], state)
    closed_phase = None
    if kind == 'SET_BINDING':
        verify_source_refs(connection, root['id'], command['source_refs'], resources=resources)
        target = command['target_document_id']
        document_kind = None
        if target is None:
            if command['scope'] is not None:
                raise Rejected('SCOPE_INVALID')
        else:
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
            return state, None
        state['binding'] = binding
        state['dispositions'].append(
            {
                'kind': 'REDIRECT',
                'scope_refs': [state['phase']['phase_ref']],
                'message_id': message_id,
                'summary': '用户调整讨论目标与参考来源',
            }
        )
    elif kind == 'SET_FOCUS':
        if not any(
            topic['topic_ref'] == command['topic_ref']
            and topic['phase_ref'] == state['phase']['phase_ref']
            for topic in state['topics']
        ):
            raise Rejected('SOURCE_INVALID')
        if state['focus_topic_ref'] == command['topic_ref']:
            return state, None
        state['focus_topic_ref'] = command['topic_ref']
    elif kind == 'CHANGE_PHASE':
        if not set(command['unresolved_refs']) <= known:
            raise Rejected('SOURCE_INVALID')
        if state['phase']['kind'] == command['phase_kind']:
            return state, None
        closed_phase = deepcopy(state['phase'])
        closed_phase['closure'] = {
            'message_id': message_id,
            'summary': command['closure_message'] or '用户确认阶段收束',
            'unresolved_refs': command['unresolved_refs'],
        }
        guide = resources.guide(command['phase_kind'])
        state['phase'] = {
            'phase_ref': 'p' + str(state['counters']['phase']),
            'kind': command['phase_kind'],
            'guide_ref': resources.reference(guide['key'], guide['version']),
            'closure': None,
        }
        state['counters']['phase'] = increment(state['counters']['phase'])
        state['focus_topic_ref'] = None
    else:
        if command['subject_ref'] not in known:
            raise Rejected('SOURCE_INVALID')
        decision = {
            'kind': {
                'DEFER': 'DEFER',
                'NOT_APPLICABLE': 'NOT_APPLICABLE',
                'DECLINE_DRAFT': 'REJECT_DRAFT',
            }[command['decision']],
            'scope_refs': [command['subject_ref']],
            'message_id': message_id,
            'summary': command['description'],
        }
        if any(
            all(item[key] == decision[key] for key in ('kind', 'scope_refs', 'summary'))
            for item in state['dispositions']
        ):
            return state, None
        state['dispositions'].append(decision)
    state['last_step'] = None
    return validate_discussion(state, resources), closed_phase
