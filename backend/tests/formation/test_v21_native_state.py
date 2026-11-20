"""Native state transitions preserve independent focus and immutable recovery intent."""

from copy import deepcopy

import pytest

from backend.app.formation.native_contracts import native_command
from backend.app.formation.native_state import apply_state_command
from backend.app.shared.command_execution import Rejected


def state():
    head = {'current_step_ref': 's2', 'active_branch_ref': 'b2'}
    steps = {
        's1': {'status': 'IN_PROGRESS', 'position': 1, 'closure_event_id': None},
        's2': {'status': 'IN_PROGRESS', 'position': 2, 'closure_event_id': None},
        's3': {'status': 'COMPLETED', 'position': 3, 'closure_event_id': 10},
    }
    branches = {
        'b1': {
            'origin_step_ref': 's1',
            'return_step_ref': 's1',
            'status': 'RESOLVED',
            'state_event_id': 11,
            'result_summary': '已有结果',
            'result_sources_json': '[{"kind":"old"}]',
            'disposition_event_id': None,
        },
        'b2': {
            'origin_step_ref': 's2',
            'return_step_ref': 's2',
            'status': 'OPEN',
            'state_event_id': 12,
            'result_summary': None,
            'result_sources_json': '[]',
            'disposition_event_id': None,
        },
    }
    issues = {
        'i1': {
            'step_ref': 's1',
            'branch_ref': 'b1',
            'disposition': 'OPEN',
            'disposition_reason': None,
            'disposition_event_id': None,
        },
    }
    return head, steps, branches, issues


def apply(original, action, event_id=20, **fields):
    command = native_command({'type': 'FORMATION', 'action': action, **fields})
    return apply_state_command(
        *original, command, lambda: event_id, dependencies=[], replacements=[]
    )


def test_pausing_noncurrent_step_preserves_both_current_focus_parts_and_input_graph():
    original = state()
    snapshot = deepcopy(original)
    changed = apply(original, 'PAUSE_STEP', step_ref='s1')
    assert changed.steps['s1']['status'] == 'PAUSED'
    assert changed.head == {'current_step_ref': 's2', 'active_branch_ref': 'b2'}
    assert original == snapshot
    changed = apply(original, 'PAUSE_STEP', step_ref='s2')
    assert changed.head == {'current_step_ref': None, 'active_branch_ref': None}
    assert changed.branches['b2']['status'] == 'OPEN'


def test_switching_to_completed_or_whole_document_changes_no_lifecycle():
    original = state()
    changed = apply(original, 'SWITCH_STEP', step_ref='s3')
    assert changed.head == {'current_step_ref': 's3', 'active_branch_ref': None}
    assert changed.steps == original[1]
    changed = apply(original, 'SWITCH_STEP', step_ref=None)
    assert changed.head == {'current_step_ref': None, 'active_branch_ref': None}


def test_start_and_reopen_do_not_pause_another_running_step_or_erase_old_input():
    original = state()
    original[1]['s1']['status'] = 'PLANNED'
    changed = apply(original, 'START_STEP', step_ref='s1')
    assert changed.steps['s1']['status'] == changed.steps['s2']['status'] == 'IN_PROGRESS'
    assert changed.head == {'current_step_ref': 's1', 'active_branch_ref': None}
    changed = apply(original, 'REOPEN_STEP', step_ref='s3')
    assert changed.steps['s3']['status'] == 'IN_PROGRESS'
    assert changed.steps['s3']['closure_event_id'] is None
    assert original[1]['s3']['closure_event_id'] == 10


@pytest.mark.parametrize(
    'action,ref',
    [
        ('START_STEP', 's2'),
        ('PAUSE_STEP', 's3'),
        ('RESUME_STEP', 's1'),
        ('REOPEN_STEP', 's1'),
    ],
)
def test_invalid_transitions_reject_without_partial_mutation(action, ref):
    original = state()
    saved = deepcopy(original)
    with pytest.raises(Rejected) as rejected:
        apply(original, action, step_ref=ref)
    assert rejected.value.code == 'STATE_CONFLICT'
    assert rejected.value.details['reason'] == 'INVALID_TRANSITION'
    assert original == saved


def test_resume_branch_is_one_time_event_bound_and_does_not_resume_parent():
    original = state()
    original[1]['s1']['status'] = 'COMPLETED'
    changed = apply(
        original,
        'RESUME_BRANCH',
        step_ref='s1',
        branch_ref='b1',
        expected_branch_status='RESOLVED',
        expected_branch_event_id=11,
        enter_after_resume=True,
    )
    assert changed.action == 'BRANCH_REOPENED'
    assert changed.head == {'current_step_ref': 's1', 'active_branch_ref': 'b1'}
    assert changed.branches['b1']['status'] == 'OPEN'
    assert changed.branches['b1']['result_summary'] is None
    assert changed.branches['b1']['result_sources_json'] == '[]'
    assert changed.steps['s1']['status'] == 'COMPLETED'
    assert original[2]['b1']['result_summary'] == '已有结果'
    with pytest.raises(Rejected) as rejected:
        apply(
            (changed.head, changed.steps, changed.branches, changed.issues),
            'RESUME_BRANCH',
            step_ref='s1',
            branch_ref='b1',
            expected_branch_status='RESOLVED',
            expected_branch_event_id=11,
            enter_after_resume=True,
        )
    assert rejected.value.details['reason'] == 'BRANCH_STATE_CHANGED'
    entered = apply(
        (changed.head, changed.steps, changed.branches, changed.issues),
        'ENTER_BRANCH',
        step_ref='s1',
        branch_ref='b1',
    )
    assert entered.changed is False


def test_resuming_without_entering_preserves_current_step_and_active_branch():
    changed = apply(
        state(),
        'RESUME_BRANCH',
        step_ref='s1',
        branch_ref='b1',
        expected_branch_status='RESOLVED',
        expected_branch_event_id=11,
        enter_after_resume=False,
    )
    assert changed.head == {'current_step_ref': 's2', 'active_branch_ref': 'b2'}


def test_old_recovery_basis_cannot_clear_a_newer_result():
    original = state()
    original[2]['b1']['state_event_id'] = 19
    with pytest.raises(Rejected) as rejected:
        apply(
            original,
            'RESUME_BRANCH',
            step_ref='s1',
            branch_ref='b1',
            expected_branch_status='RESOLVED',
            expected_branch_event_id=11,
            enter_after_resume=True,
        )
    assert rejected.value.details['reason'] == 'BRANCH_STATE_CHANGED'
    assert original[2]['b1']['result_summary'] == '已有结果'


def test_branch_enter_needs_complete_real_return_and_return_keeps_branch_open():
    with pytest.raises(Rejected) as rejected:
        apply(state(), 'ENTER_BRANCH', step_ref='s1', branch_ref='b2')
    assert rejected.value.details['reason'] == 'BRANCH_RETURN_MISMATCH'
    changed = apply(state(), 'RETURN_FROM_BRANCH', branch_ref='b2')
    assert changed.head == {'current_step_ref': 's2', 'active_branch_ref': None}
    assert changed.branches['b2']['status'] == 'OPEN'


def test_resuming_branch_checks_open_issues_before_any_change_becomes_visible():
    original = state()
    original[3]['i1']['step_ref'] = 's2'
    with pytest.raises(Rejected):
        apply(
            original,
            'RESUME_BRANCH',
            step_ref='s1',
            branch_ref='b1',
            expected_branch_status='RESOLVED',
            expected_branch_event_id=11,
            enter_after_resume=True,
        )
    assert original[2]['b1']['status'] == 'RESOLVED'
    assert original[0]['active_branch_ref'] == 'b2'


def test_resuming_issue_does_not_reopen_closed_branch_or_parent_step():
    original = state()
    original[1]['s1']['status'] = 'COMPLETED'
    original[3]['i1']['disposition'] = 'DEFERRED'
    original[3]['i1']['disposition_reason'] = '稍后处理'
    changed = apply(original, 'RESUME_ISSUE', issue_ref='i1')
    assert changed.issues['i1']['disposition'] == 'OPEN'
    assert changed.issues['i1']['disposition_event_id'] is None
    assert changed.branches['b1']['status'] == 'RESOLVED'
    assert changed.steps['s1']['status'] == 'COMPLETED'
    current = (changed.head, changed.steps, changed.branches, changed.issues)
    assert apply(current, 'RESUME_ISSUE', issue_ref='i1').changed is False
    current[3]['i1']['disposition'] = 'DROPPED'
    with pytest.raises(Rejected):
        apply(current, 'RESUME_ISSUE', issue_ref='i1')


def test_branch_disposition_only_clears_its_matching_active_focus():
    original = state()
    changed = apply(
        original, 'DISPOSE_BRANCH', branch_ref='b2', disposition='DEFERRED', reason='稍后处理'
    )
    assert changed.head == {'current_step_ref': 's2', 'active_branch_ref': None}
    assert changed.branches['b2']['status'] == 'DEFERRED'
    assert changed.branches['b2']['state_event_id'] == 20
    assert changed.steps == original[1]
