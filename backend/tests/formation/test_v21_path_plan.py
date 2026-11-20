"""Whole-batch route semantics use all current entities without allocating real identities."""

from copy import deepcopy

import pytest

from backend.app.formation.path_plan import prepare_route
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import InvalidInput
from backend.tests.formation.test_v21_contracts import add_step


def graph():
    head = {
        'document_id': 1,
        'version': 7,
        'goal_version': 2,
        'goal_text': '形成设计',
        'goal_sources_json': '[]',
        'current_step_ref': 's1',
        'active_branch_ref': 'b1',
        'next_step_no': 3,
        'next_branch_no': 2,
        'next_issue_no': 2,
        'next_artifact_no': 1,
    }
    steps = {
        f's{i}': {
            'document_id': 1,
            'step_ref': f's{i}',
            'definition_version': 3,
            'next_result_no': 2,
            'position': i,
            'title': f'第{i}步',
            'status': 'IN_PROGRESS',
            'closure_event_id': None,
        }
        for i in (1, 2)
    }
    results = {
        f's{i}.o1': {
            'document_id': 1,
            'step_ref': f's{i}',
            'result_ref': f's{i}.o1',
            'description': '完整方案',
            'kind': 'CONTENT',
        }
        for i in (1, 2)
    }
    branches = {
        'b1': {
            'document_id': 1,
            'branch_ref': 'b1',
            'origin_step_ref': 's1',
            'return_step_ref': 's1',
            'status': 'OPEN',
            'state_event_id': 4,
            'disposition_event_id': None,
        }
    }
    issues = {
        'i1': {
            'document_id': 1,
            'issue_ref': 'i1',
            'step_ref': 's1',
            'branch_ref': 'b1',
            'disposition': 'OPEN',
            'disposition_reason': None,
            'disposition_event_id': None,
        }
    }
    return head, steps, results, branches, issues, {('s2', 's1')}, set()


def plan(changes, routes=(), original=None):
    return prepare_route(*(graph() if original is None else original), changes, list(routes))


def replacement():
    return {
        'from_result_ref': 's1.o1',
        'disposition': 'REPLACED',
        'target_result_refs': ['new_result_1'],
        'reason': '按完整成果范围承接',
    }


def test_cancel_is_complete_atomic_reroute_and_changes_no_existing_input_or_counter():
    original = graph()
    unchanged = deepcopy(original)
    calculated = plan(
        [
            add_step(),
            {'type': 'CANCEL_STEP', 'step_ref': 's1', 'replacement_step_refs': ['new_step_1']},
            {'type': 'MOVE_ISSUE', 'issue_ref': 'i1', 'to_step_ref': 'new_step_1'},
            {'type': 'SET_BRANCH_RETURN', 'branch_ref': 'b1', 'return_step_ref': 'new_step_1'},
            {'type': 'SET_DEPENDENCIES', 'step_ref': 's2', 'dependencies': ['new_step_1']},
        ],
        [replacement()],
        original,
    )
    assert calculated.changed
    assert calculated.steps['s1']['status'] == 'CANCELLED'
    assert calculated.steps['new_step_1']['status'] == 'PLANNED'
    assert (
        calculated.issues['i1']['step_ref']
        == calculated.branches['b1']['return_step_ref']
        == 'new_step_1'
    )
    assert calculated.head['current_step_ref'] is calculated.head['active_branch_ref'] is None
    assert calculated.branches['b1']['origin_step_ref'] == 's1'
    assert calculated.steps['s2']['definition_version'] == 4
    assert calculated.steps['new_step_1']['definition_version'] == 1
    assert calculated.head['next_step_no'] == 3
    assert original == unchanged
    assert ('new_step_1', 's1') in calculated.replacements


@pytest.mark.parametrize('missing', ['MOVE_ISSUE', 'SET_BRANCH_RETURN', 'SET_DEPENDENCIES'])
def test_cancel_cannot_hide_missing_open_work_or_dependencies(missing):
    changes = [
        add_step(),
        {'type': 'CANCEL_STEP', 'step_ref': 's1', 'replacement_step_refs': ['new_step_1']},
        {'type': 'MOVE_ISSUE', 'issue_ref': 'i1', 'to_step_ref': 'new_step_1'},
        {'type': 'SET_BRANCH_RETURN', 'branch_ref': 'b1', 'return_step_ref': 'new_step_1'},
        {'type': 'SET_DEPENDENCIES', 'step_ref': 's2', 'dependencies': ['new_step_1']},
    ]
    with pytest.raises(InvalidInput):
        plan([change for change in changes if change['type'] != missing], [replacement()])


def test_kind_mismatch_cannot_claim_a_content_requirement_was_taken_over_by_analysis():
    new_step = add_step()
    new_step['expected_results'][0]['kind'] = 'ANALYSIS'
    original = graph()
    original[3].clear()
    original[4].clear()
    original[0]['active_branch_ref'] = None
    original[5].clear()
    with pytest.raises(InvalidInput):
        plan(
            [
                new_step,
                {'type': 'CANCEL_STEP', 'step_ref': 's1', 'replacement_step_refs': ['new_step_1']},
            ],
            [replacement()],
            original,
        )


def test_display_rename_and_order_change_do_not_increment_definition_or_goal():
    calculated = plan(
        [
            {'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '完整设计'},
            {'type': 'MOVE_STEP', 'step_ref': 's2', 'before_step_ref': 's1'},
        ]
    )
    assert (
        calculated.steps['s1']['definition_version']
        == calculated.steps['s2']['definition_version']
        == 3
    )
    assert calculated.steps['s2']['position'] == 1
    assert calculated.steps['s1']['position'] == 2
    assert calculated.head['goal_version'] == 2
    assert calculated.head['current_step_ref'] == 's1'


def test_actual_definition_changes_increment_once_per_step_not_per_change():
    calculated = plan(
        [
            {'type': 'UPDATE_RESULT', 'result_ref': 's2.o1', 'description': '完整前后端设计与边界'},
            {'type': 'SET_DEPENDENCIES', 'step_ref': 's2', 'dependencies': []},
            {
                'type': 'ADD_RESULT',
                'step_ref': 's2',
                'temp_result_ref': 'new_result_1',
                'description': '验证依据',
                'kind': 'ANALYSIS',
            },
        ]
    )
    assert calculated.steps['s2']['definition_version'] == 4
    assert calculated.steps['s1']['definition_version'] == 3


def test_no_change_preserves_versions_and_has_no_allocated_reference_map():
    calculated = plan([{'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '第1步'}])
    assert not calculated.changed
    assert calculated.head['version'] == 7
    assert calculated.scope.declared_steps == calculated.scope.declared_results == ()


def test_goal_change_is_versioned_without_writing_body_or_completing_work():
    calculated = plan([{'type': 'SET_GOAL', 'text': '形成明确的接口及交互设计', 'source_refs': []}])
    assert calculated.head['goal_version'] == 3
    assert calculated.steps == graph()[1]
    assert calculated.links == ()
    assert calculated.head['version'] == 7


def test_dependency_cycle_detected_using_full_graph_after_batch_application():
    with pytest.raises(InvalidInput):
        plan([{'type': 'SET_DEPENDENCIES', 'step_ref': 's1', 'dependencies': ['s2']}])


def test_closed_step_cannot_be_cancelled_via_route_edit():
    original = graph()
    original[1]['s2']['status'] = 'COMPLETED'
    with pytest.raises(Rejected):
        plan(
            [{'type': 'CANCEL_STEP', 'step_ref': 's2', 'replacement_step_refs': []}],
            [
                {
                    'from_result_ref': 's2.o1',
                    'disposition': 'NOT_REQUIRED',
                    'target_result_refs': [],
                    'reason': '不再要求',
                }
            ],
            original,
        )


def test_related_closed_branch_keeps_history_while_independent_issue_resumes():
    original = graph()
    original[3]['b1']['status'] = 'RESOLVED'
    original[3]['b1']['return_step_ref'] = 's2'
    original[0]['active_branch_ref'] = None
    original[4]['i1']['disposition'] = 'DEFERRED'
    original[4]['i1']['disposition_reason'] = '稍后讨论'
    original[4]['i1']['disposition_event_id'] = 5
    calculated = plan([{'type': 'RESUME_ISSUE', 'issue_ref': 'i1'}], original=original)
    assert calculated.issues['i1']['disposition'] == 'OPEN'
    assert calculated.issues['i1']['disposition_event_id'] is None
    assert calculated.branches == original[3]
    assert calculated.steps == original[1]


def test_forward_link_uses_new_owner_and_declared_result_without_allocating_ids():
    calculated = plan(
        [
            {
                'type': 'LINK_CONTENT',
                'step_ref': 'new_step_1',
                'result_refs': ['new_result_1'],
                'revision_id': 1,
                'block_ids': [1],
            },
            add_step(),
        ]
    )
    assert calculated.links[0]['result_refs'] == ['new_result_1']
    assert calculated.head['next_step_no'] == 3
    assert calculated.scope.declared_steps == ('new_step_1',)
