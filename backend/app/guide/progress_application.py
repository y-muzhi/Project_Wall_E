"""Apply one bounded AI discussion delta against actual carried provenance.

This pure value transition neither commits nor releases the running operation.
A rejected delta leaves all pending inputs and the complete old value intact.
"""
from copy import deepcopy
import json
import re

from backend.app.infrastructure.identifiers import increment
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.requirements.discussion import validate_discussion


class ProgressInvalid(ValueError):
    pass


def carried_aliases(context):
    basis, wire = context.basis, context.input
    refs = {item['ref'] for item in basis['selected']}
    refs.update(item['ref'] for item in wire['goal_and_decisions'])
    refs.update(block['ref'] for document in wire['documents'] for block in document['blocks'])
    refs.update(item['ref'] for item in wire['recent_history'])
    refs.add(wire['current_request']['message_ref'])
    messages = [wire['current_request'], *wire['recent_history']]
    for message in messages:
        if message['formal_answers']:
            ref = message.get('message_ref', message.get('ref'))
            refs.update(ref+':'+answer['card_key'] for answer in message['formal_answers'])
    # Formal answers in long-term selected text have their exact card alias.
    refs.update(item['ref'] for item in basis['selected'] if item['kind'] == 'CARD_ANSWER')
    aliases = {item['ref']: item for item in basis['aliases'] if item['ref'] in refs}
    # Section references are public Wire identities too. Resolve them only to
    # the actually transmitted blocks, never to an unread remainder or to the
    # private Canonical document. Navigation-only ancestor titles are excluded.
    # Deriving this view preserves historic counted request/basis bytes.
    for document in wire['documents']:
        sections = {item['section_ref']: item for item in document['sections']}
        visible = {block['block_id'] for block in document['blocks']}
        for ref, section in sections.items():
            if section['heading_block_id'] not in visible:
                continue
            members = []
            for block in document['blocks']:
                parent = block['section_ref'];visited = set()
                while parent in sections and parent not in visited:
                    if parent == ref:
                        members.append(block['block_id']);break
                    visited.add(parent);parent = sections[parent]['parent_ref']
            aliases[ref] = {'ref': ref, 'source_refs': [{'kind': 'REVISION',
                'document_id': document['document_id'], 'revision_id': document['revision_id'],
                'block_ids': members}]}
    return aliases


def resolve_sources(refs, context):
    aliases = carried_aliases(context)
    result = {}
    if len(refs) != len(set(refs)):
        raise ProgressInvalid('Duplicate source alias')
    for ref in refs:
        if ref not in aliases:
            raise ProgressInvalid('Source was not actually carried')
        for source in aliases[ref]['source_refs']:
            result.setdefault(canonical_input(source), source)
    return list(result.values())


def apply_progress(state, delta, context, assistant_id, resources, *, return_mapping=False):
    try:
        delta = resources.validate('Progress', delta)
        state = validate_discussion(state, resources)
        actual = context.canonical
        if state != actual['discussion']:
            raise ProgressInvalid('Discussion changed since acceptance')
        result = deepcopy(state)
        topics = {topic['topic_ref']: topic for topic in result['topics']}
        evidence = {item['evidence_ref']: item for item in result['evidence']}
        mapping = {};outcome_mapping = {};seen = set()
        def allocate(ref, prefix, counter):
            if ref in seen or ref in topics or ref in evidence or re.fullmatch('new_'+prefix+r'[1-9][0-9]*', ref) is None:
                raise ProgressInvalid('ADD requires a unique temporary reference')
            seen.add(ref);mapping[ref] = prefix+str(result['counters'][counter]);result['counters'][counter] = increment(result['counters'][counter])
        for change in delta['topic_changes']:
            if change['change'] == 'ADD':
                allocate(change['ref'], 't', 'topic')
            elif change['ref'] not in topics or topics[change['ref']]['phase_ref'] != state['phase']['phase_ref'] or change['ref'] in seen:
                raise ProgressInvalid('UPDATE requires an existing current-phase topic')
            else:
                seen.add(change['ref'])
        for change in delta['evidence_changes']:
            allocate(change['ref'], 'e', 'evidence')
        resolve = lambda ref: mapping.get(ref, ref)
        guide = resources.guide(state['phase']['kind'])
        mainlines = {item['ref'] for item in guide['mainlines']}
        for change in delta['topic_changes']:
            if change['mainline_ref'] not in mainlines:
                raise ProgressInvalid('Unknown phase mainline')
            ref = resolve(change['ref'])
            outcomes = deepcopy(change['expected_outcomes'])
            known_outcomes = {item['outcome_ref'] for item in topics.get(ref, {}).get('expected_outcomes', [])}
            outcome_refs = [item['outcome_ref'] for item in outcomes]
            if len(outcome_refs) != len(set(outcome_refs)):
                raise ProgressInvalid('Duplicate topic outcome')
            for index, outcome in enumerate(outcomes, 1):
                old = outcome['outcome_ref']
                if change['change'] == 'ADD' or old not in known_outcomes:
                    # New local outcome IDs are scoped to their real topic.
                    number = index
                    while ref+':o'+str(number) in known_outcomes:
                        number += 1
                    outcome['outcome_ref'] = ref+':o'+str(number)
                    known_outcomes.add(outcome['outcome_ref'])
                    if old not in outcome_mapping:
                        outcome_mapping[old] = outcome['outcome_ref']
                    elif outcome_mapping[old] != outcome['outcome_ref']:
                        outcome_mapping[old] = None
            topics[ref] = {'topic_ref': ref, 'phase_ref': state['phase']['phase_ref'], 'mainline_ref': change['mainline_ref'],
                **{key: change[key] for key in ('title', 'purpose', 'assessment', 'unresolved_impacts')}, 'expected_outcomes': outcomes,
                'evidence_refs': [resolve(item) for item in change['evidence_refs']], 'dependencies': [resolve(item) for item in change['dependencies']],
                'updated_by_message_id': assistant_id}
        raw_messages = {row['message_id']: row for row in [actual['current_message'], *actual['messages']]}
        def user_source(source, decision=False):
            if source['kind'] not in ('MESSAGE', 'CARD_ANSWER'):
                return False
            row = raw_messages.get(source['message_id'])
            if row is None or row['role'] != 'USER':
                return False
            if not decision:
                return True
            if any(item['message_id'] == row['message_id'] for item in state['dispositions']):
                return True
            if row['message_type'] != 'CARD_RESPONSE':
                return False
            answers = resources.validate('StoredResponses', json.loads(row['structured_content_json']))['responses']
            return any(not answer['skipped'] and (answer['selected_option_keys'] or answer['custom_answer'] is not None)
                and (source['kind'] == 'MESSAGE' or answer['card_key'] == source['card_key']) for answer in answers)
        for change in delta['evidence_changes']:
            sources = resolve_sources(change['source_refs'], context)
            if not sources:
                raise ProgressInvalid('Evidence needs actual carried sources')
            if change['origin'] in ('USER_STATEMENT', 'USER_DECISION') and not any(user_source(source, change['origin'] == 'USER_DECISION') for source in sources):
                raise ProgressInvalid('AI proposal cannot become a user decision')
            ref = resolve(change['ref']);supersedes = [resolve(item) for item in change['supersedes']]
            if any(item not in evidence or item == ref for item in supersedes) or len(supersedes) != len(set(supersedes)):
                raise ProgressInvalid('Unknown superseded evidence')
            if change['change'] == 'ADD' and supersedes:
                raise ProgressInvalid('ADD does not supersede a decision')
            if change['change'] == 'PROPOSE_SUPERSEDE' and not supersedes:
                raise ProgressInvalid('A dispute must name existing evidence')
            for prior in supersedes:
                evidence[prior]['state'] = 'DISPUTED'
            evidence[ref] = {key: change[key] for key in ('assertion', 'origin', 'nature')} | {
                'evidence_ref': ref, 'applies_to': 'GLOBAL' if change['applies_to'] == 'GLOBAL' else [resolve(item) for item in change['applies_to']],
                'source_refs': sources, 'state': 'DISPUTED' if supersedes else 'ACTIVE', 'supersedes': supersedes,
                'topic_refs': [resolve(item) for item in change['topic_refs']]}
        result['topics'], result['evidence'] = list(topics.values()), list(evidence.values())
        result['focus_topic_ref'] = None if delta['focus_topic_ref'] is None else resolve(delta['focus_topic_ref'])
        next_step = deepcopy(delta['next_step'])
        if next_step is not None:
            if next_step['topic_ref'] is not None:
                next_step['topic_ref'] = resolve(next_step['topic_ref'])
                if next_step['topic_ref'] not in topics or topics[next_step['topic_ref']]['phase_ref'] != state['phase']['phase_ref']:
                    raise ProgressInvalid('Next step names an unavailable topic')
            result['last_step'] = {'message_id': assistant_id, 'value': next_step}
        processed = delta['processed_user_message_ids']
        carried_ids = {identity for item in context.basis['selected'] for identity in item['message_ids']}
        if len(processed) != len(set(processed)) or not set(processed) <= set(state['pending_user_message_ids']) & carried_ids:
            raise ProgressInvalid('Processed inputs must be unique actually carried pending messages')
        indexed = {source['message_id'] for item in evidence.values() if item['state'] in ('ACTIVE', 'DISPUTED')
            for source in item['source_refs'] if source['kind'] in ('MESSAGE', 'CARD_ANSWER')}
        indexed.update(item['message_id'] for item in result['dispositions'])
        # Unsupported processing claims stay pending rather than discarding
        # the otherwise valid delta or pretending the input has a destination.
        result['pending_user_message_ids'] = [identity for identity in state['pending_user_message_ids'] if identity not in set(processed) & indexed]
        result = validate_discussion(result, resources)
        card_mapping = dict(mapping)
        for old, new in outcome_mapping.items():
            card_mapping[old] = new if old not in mapping or mapping[old] == new else None
        return (result, card_mapping) if return_mapping else result
    except ProgressInvalid:
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise ProgressInvalid('Discussion delta failed structural or reference validation') from error
