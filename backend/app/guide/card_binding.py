"""Validate suggestions, then bind their program-only version identities."""
from copy import deepcopy

from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.messages.cards import validate_cards, CardsInvalid
from backend.app.requirements.source_refs import verify_source_refs
from .progress_application import resolve_sources


def bind_cards(connection, root, run, context, value, catalog, *, reference_map=None):
    resources = catalog.collaboration
    cards = deepcopy(validate_cards(value, resources))
    purpose = cards['purpose'];payload = cards['action_payload']
    if purpose in ('DOCUMENT_ACTION', 'PHASE_CHANGE', 'FACT_CONFIRMATION'):
        card = cards['cards'][0]
        keys = ['confirm', 'defer'] if purpose == 'FACT_CONFIRMATION' else ['accept', 'defer']
        if len(cards['cards']) != 1 or card['card_type'] != 'CONFIRM' or not card['required'] or [option['option_key'] for option in card['options']] != keys or card['selection_rule'] != {'min': 1, 'max': 1} or card['custom_answer'] != {'enabled': False, 'max_length': 0}:
            raise CardsInvalid('Action cards require their fixed explicit confirmation options')
    target_version = None;sources = []
    if purpose in ('DOCUMENT_ACTION', 'PHASE_CHANGE') and payload['basis_discussion_version'] != context.input['current_request']['basis_ref']['discussion_version']:
        raise CardsInvalid('Action suggestion refers to another discussion basis')
    if purpose == 'DOCUMENT_ACTION':
        payload['source_refs'] = resolve_sources(payload['source_refs'], context)
        sources = payload['source_refs']
        verify_source_refs(connection, root['id'], sources, resources=resources)
        target = payload['target']
        if target['kind'] == 'EXISTING':
            frozen = next((document for document in context.canonical['documents'] if document['document_id'] == target['document_id'] and document['content_version'] == target['expected_content_version']), None)
            if frozen is None:
                raise CardsInvalid('Suggestion cannot address an unread target')
            current = DocumentRepository(connection).get_current(root['id'], target['document_id'])
            if current is None or current['content_version'] != target['expected_content_version'] or current['archived_at'] is not None:
                raise CardsInvalid('Suggestion target is no longer maintainable at that version')
            target_version = target['expected_content_version']
        elif payload['operation'] != 'GENERATE':
            raise CardsInvalid('Only generation can allocate a new target')
        if payload['operation'] == 'REVISE' and (target['kind'] != 'EXISTING' or payload['scope'] is None) or payload['operation'] == 'GENERATE' and (target['kind'] != 'NEW' or payload['scope'] is not None):
            raise CardsInvalid('Suggested operation and target/scope differ')
        if target['kind'] == 'NEW':
            from backend.app.shared.validation import ordinary_text
            if ordinary_text(target['name'], 'name', 1, 80, multiline=False) != target['name']:
                raise CardsInvalid('Suggested name must already satisfy the document name rules')
            if target['template_ref'] is not None:
                fixed = resources.reference('structure.'+target['document_kind'])
                if target['template_ref'] != {key: fixed[key] for key in ('key', 'version')}:
                    raise CardsInvalid('Suggested structure differs from its actual document kind')
    elif purpose == 'PHASE_CHANGE':
        from backend.app.requirements.discussion import discussion_references
        mapping = reference_map or {}
        refs = [mapping.get(ref, ref) for ref in payload['unresolved_refs']]
        if any(ref is None for ref in refs) or len(set(refs)) != len(refs) or not set(refs) <= discussion_references(connection, root['id'], root['discussion_state_json']):
            raise CardsInvalid('Phase suggestion refers to missing or ambiguous outcomes')
        payload['unresolved_refs'] = refs
    elif purpose == 'FACT_CONFIRMATION':
        # Exact fact authority/evidence uses the existing patch proof; the
        # confirmation path must bind the same actual accepted target.
        from .fact_confirmation import validate_fact_action
        validate_fact_action(connection, root, run, context, payload, catalog)
        if [(option['option_key'], option['label']) for option in cards['cards'][0]['options']] != [('confirm', '确认以上事实和变更'), ('defer', '尚未确认')]:
            raise CardsInvalid('Fact confirmation labels must describe the exact adoption')
        target_version = context.canonical['authorization']['expected_content_version']
    heads = {}
    for source in sources:
        if source['kind'] == 'REVISION':
            current = DocumentRepository(connection).get_current(root['id'], source['document_id'])
            if current is None:
                raise CardsInvalid('Suggestion source is unavailable')
            heads[current['id']] = {'document_id': current['id'], 'content_version': current['content_version']}
    cards['program_binding'] = {'discussion_version': root['discussion_version'], 'target_content_version': target_version, 'source_heads': list(heads.values())}
    return resources.validate('StoredCardGroup', cards)
