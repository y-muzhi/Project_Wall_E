"""Pure discussion transitions against an actual frozen SQLite context."""
from copy import deepcopy
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_context import compiled
from backend.app.guide.collaboration_context import compile_context
from backend.app.guide.progress_application import apply_progress, ProgressInvalid


def topic(ref, **changes):
    return {'change': 'ADD', 'ref': ref, 'mainline_ref': 'value', 'title': '目标', 'purpose': '明确目标',
        'expected_outcomes': [{'outcome_ref': 'new_o1', 'text': '目标明确', 'criterion': '有来源'}],
        'assessment': 'DISCUSSING', 'evidence_refs': ['new_e1'], 'dependencies': [], 'unresolved_impacts': [], **changes}


def evidence(**changes):
    return {'change': 'ADD', 'ref': 'new_e1', 'assertion': '用户本轮原话', 'origin': 'USER_STATEMENT', 'nature': 'FACT',
        'applies_to': ['new_t1'], 'source_refs': ['m2'], 'supersedes': [], 'topic_refs': ['new_t1'], **changes}


def delta(**changes):
    return {'topic_changes': [topic('new_t1')], 'evidence_changes': [evidence()], 'focus_topic_ref': 'new_t1',
        'next_step': {'action': 'PRESENT_DESIGN', 'topic_ref': 'new_t1', 'reason': '形成方案', 'unresolved_impacts': []},
        'processed_user_message_ids': [2], **changes}


def test_temporary_refs_outcomes_focus_and_next_step_remap_together_and_input_value_is_immutable(workspace):
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED';context = compiled(workspace)
    state = context.canonical['discussion'];before = deepcopy(state)
    result = apply_progress(state, delta(), context, 3, workspace[2].collaboration)
    assert state == before
    assert result['topics'][0]['topic_ref'] == 't1' and result['topics'][0]['expected_outcomes'][0]['outcome_ref'] == 't1:o1'
    assert result['topics'][0]['evidence_refs'] == ['e1'] and result['evidence'][0]['topic_refs'] == ['t1']
    assert result['focus_topic_ref'] == result['last_step']['value']['topic_ref'] == 't1'
    assert result['pending_user_message_ids'] == []
    assert result['counters'] == {'phase': 2, 'topic': 2, 'evidence': 2}


@pytest.mark.parametrize('change', [
    {'topic_changes': [topic('new_t1', dependencies=['new_t2']), topic('new_t2', dependencies=['new_t1'])]},
    {'evidence_changes': [evidence(source_refs=['authorization'])]},
    {'evidence_changes': [evidence(origin='USER_DECISION')]},
    {'processed_user_message_ids': [2, 2]}, {'processed_user_message_ids': [999]},
    {'topic_changes': [topic('t1')]}, {'topic_changes': [topic('new_t1', mainline_ref='unknown')]},
    # Real observation: arbitrary topic IDs and raw message aliases used as
    # evidence IDs must remain rejected; prompt repair cannot relax provenance.
    {'topic_changes': [topic('t-value')]},
    {'topic_changes': [topic('new_t1', evidence_refs=['m2'])]},
    {'topic_changes': [topic('new_t1', evidence_refs=['new_e2'])]},
])
def test_invalid_delta_cannot_partially_consume_pending_or_change_counters(workspace, change):
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED';context = compiled(workspace);state = context.canonical['discussion'];before = deepcopy(state)
    with pytest.raises(ProgressInvalid):
        apply_progress(state, delta(**change), context, 3, workspace[2].collaboration)
    assert state == before


def test_processed_claim_without_index_destination_keeps_pending(workspace):
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED';context = compiled(workspace);state = context.canonical['discussion']
    result = apply_progress(state, delta(topic_changes=[], evidence_changes=[], focus_topic_ref=None, next_step=None), context, 3, workspace[2].collaboration)
    assert result['pending_user_message_ids'] == [2]


def test_section_sources_resolve_only_carried_members_without_changing_frozen_context(workspace):
    from backend.tests.documents.test_v15_documents import document
    from backend.app.guide.progress_application import carried_aliases, resolve_sources
    created = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    heading = created['block_state_json']['blocks'][3]['block_id']
    assert accept(workspace, operation='REVIEW',
        target={'kind': 'EXISTING', 'document_id': created['id'], 'expected_content_version': 1},
        scope={'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': heading}})['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace, omit_background=True)
    before = (context.input_json, context.basis_json)
    doc = context.input['documents'][0]
    section = next(item for item in doc['sections'] if item['heading_block_id'] == heading)
    source = resolve_sources([section['section_ref']], context)
    assert source == [{'kind': 'REVISION', 'document_id': doc['document_id'],
        'revision_id': doc['revision_id'], 'block_ids': [block['block_id'] for block in doc['blocks']]}]
    assert doc['coverage'] == 'PARTIAL'
    assert before == (context.input_json, context.basis_json)
    assert doc['ref']+'s999' not in carried_aliases(context)
    with pytest.raises(ProgressInvalid):resolve_sources([doc['ref']+'s999'], context)


def test_navigation_only_section_does_not_authorize_unread_body(workspace):
    from backend.tests.documents.test_v15_documents import document
    from backend.tests.documents.test_v15_editing import start, candidate, save, finish
    from backend.app.documents.queries import get_current_document
    from backend.app.guide.progress_application import carried_aliases
    created = document(workspace)['data']['document']
    draft = start(workspace)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, '# 章节\n\n实际段落。\n'))
    assert saved['code'] == 'DRAFT_SAVED'
    assert finish(workspace, {**draft, 'content_version': saved['data']['content_version']})['code'] == 'DRAFT_COMPLETED'
    created = get_current_document(workspace[0], 1, created['id'], catalog=workspace[2])['data']
    block = created['block_state_json']['blocks'][1]['block_id']
    assert accept(workspace, operation='REVIEW',
        target={'kind': 'EXISTING', 'document_id': created['id'], 'expected_content_version': created['content_version']},
        scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': block}})['code'] == 'GUIDE_ACCEPTED'
    context = compiled(workspace, omit_background=True);doc = context.input['documents'][0]
    assert len(doc['blocks']) == 1 and doc['sections']
    assert all(section['section_ref'] not in carried_aliases(context) for section in doc['sections'])
