"""Ordinary model maintenance cannot impersonate manual decisions or program evidence."""

from copy import deepcopy

import pytest

from backend.app.formation.model_contracts import change, formation_delta
from backend.app.shared.validation import InvalidInput


def examples():
    expected = [{'temp_ref': 'new_result_1', 'description': '成果', 'kind': 'CONTENT'}]
    step = {
        'temp_ref': 'new_step_1',
        'title': '明确范围',
        'expected_results': expected,
        'dependencies': [],
        'topic_refs': [],
    }
    source = ['m1']
    return [
        {
            'type': 'INITIALIZE_PATH',
            'goal': {'text': '形成完整设计', 'source_refs': source},
            'steps': [step],
        },
        {'type': 'ADD_STEP', **step, 'before_step_ref': None},
        {
            'type': 'UPDATE_STEP',
            'step_ref': 's1',
            'title': '完善范围',
            'add_results': [],
            'dependencies': None,
            'topic_refs': None,
        },
        {'type': 'MOVE_STEP', 'step_ref': 's1', 'before_step_ref': None},
        {
            'type': 'ADD_ISSUE',
            'temp_ref': 'new_issue_1',
            'step_ref': 's1',
            'branch_ref': None,
            'description': '范围待明确',
            'blocking': False,
            'source_refs': source,
        },
        {
            'type': 'UPDATE_ISSUE',
            'issue_ref': 'i1',
            'description': None,
            'blocking': None,
            'resolution': {'summary': '已确认范围', 'source_refs': source},
        },
        {
            'type': 'ADD_BRANCH',
            'temp_ref': 'new_branch_1',
            'origin_step_ref': 's1',
            'return_step_ref': 's1',
            'question': '相关风险',
            'relevance': '影响当前方案',
            'topic_refs': [],
            'source_refs': source,
        },
        {
            'type': 'UPDATE_BRANCH',
            'branch_ref': 'b1',
            'topic_refs': None,
            'result': {'summary': '风险已核实', 'source_refs': source},
        },
        {'type': 'SET_BRANCH_FOCUS', 'branch_ref': None, 'reason': '继续主线'},
        {
            'type': 'ASSESS_STEP',
            'step_ref': 's1',
            'definition_version': 1,
            'verdict': 'UNCERTAIN',
            'reason': '材料不完整',
            'document_refs': [],
            'source_refs': source,
        },
        {
            'type': 'RECOMMEND',
            'step_ref': 's1',
            'action': 'NEED_MATERIAL',
            'reason': '补充依据',
            'target_step_ref': None,
            'source_refs': source,
        },
        {
            'type': 'ASSOCIATE_CONTENT',
            'step_ref': 's1',
            'result_refs': ['s1.o1'],
            'document_refs': ['d1v1b1'],
            'source_refs': source,
            'review_of': None,
        },
    ]


@pytest.mark.parametrize('value', examples())
def test_all_twelve_exact_alternatives_remain_detached(value):
    expected = deepcopy(value)
    assert change(value, 'change') == expected
    value['private_basis'] = {}
    with pytest.raises(InvalidInput):
        change(value, 'change')


@pytest.mark.parametrize(
    'name',
    ['CANCEL_STEP', 'COMPLETE_STEP', 'REOPEN_STEP', 'DISPOSE_BRANCH', 'RESUME_BRANCH', 'SET_GOAL'],
)
def test_user_only_decisions_are_never_model_delta_authority(name):
    with pytest.raises(InvalidInput):
        change({'type': name}, 'change')


def test_private_basis_and_source_objects_are_not_model_aliases():
    values = examples()
    for value in values:
        if 'source_refs' in value:
            value['source_refs'] = [{'kind': 'MESSAGE', 'message_id': 1}]
            with pytest.raises(InvalidInput):
                change(value, 'change')
    recommendation = examples()[10]
    recommendation['basis'] = {}
    with pytest.raises(InvalidInput):
        change(recommendation, 'change')


def test_initialization_freeze_uses_null_not_a_fake_zero_version_and_can_recommend_same_round():
    initial, recommendation = examples()[0], examples()[10]
    recommendation['step_ref'] = 'new_step_1'
    value = {
        'basis': {
            'formation_version': None,
            'goal_version': None,
            'document_revision_id': 1,
            'content_version': 1,
        },
        'changes': [initial, recommendation],
    }
    assert formation_delta(value) == value
    for version in (0, True, '1'):
        bad = deepcopy(value)
        bad['basis']['formation_version'] = version
        with pytest.raises(InvalidInput):
            formation_delta(bad)
    bad = deepcopy(value)
    bad['changes'].append(deepcopy(initial))
    with pytest.raises(InvalidInput):
        formation_delta(bad)
