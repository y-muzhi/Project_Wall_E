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
