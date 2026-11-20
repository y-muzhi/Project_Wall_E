"""V2.1 hostile command, forward-reference and full-graph boundary regressions."""

from copy import deepcopy

import pytest

from backend.app.formation.graph import acyclic, validate_graph
from backend.app.formation.native_contracts import native_command
from backend.app.formation.path_contracts import route_batch
from backend.app.formation.path_scope import path_scope
from backend.app.formation.types import reference, target_selection
from backend.app.shared.validation import InvalidInput, MAX_SAFE_INTEGER


def add_step(number=1, dependencies=()):
    return {
        'type': 'ADD_STEP',
        'temp_step_ref': f'new_step_{number}',
        'title': '讨论路线',
        'expected_results': [
            {
                'temp_result_ref': f'new_result_{number}',
                'description': '形成依据',
                'kind': 'CONTENT',
            }
        ],
        'dependencies': list(dependencies),
        'replaces_step_refs': [],
        'before_step_ref': None,
    }


def scope(changes, routes=(), **overrides):
    parsed, routes = route_batch(changes, list(routes))
    graph = dict(
        step_refs={'s1'}, result_owners={'s1.o1': 's1'}, branch_refs={'b1'}, issue_refs={'i1'}
    )
    graph.update(overrides)
    return path_scope(parsed, routes, **graph), parsed, routes


@pytest.mark.parametrize(
    'kind,value',
    [
        ('STEP', True),
        ('STEP', 's0'),
        ('STEP', 's01'),
        ('STEP', 'b1'),
        ('STEP', f's{MAX_SAFE_INTEGER + 1}'),
        ('STEP', 's' + '9' * 5000),
        ('RESULT', 's1.o0'),
        ('RESULT', 's1.o1.1'),
        ('TEMP_RESULT', 'new_step_1'),
    ],
)
def test_local_refs_do_not_coerce_or_cross_symbol_kinds(kind, value):
    with pytest.raises(InvalidInput):
        reference(value, 'ref', kind)


def test_forward_declarations_and_result_allocation_preserve_confirmed_text():
    first = add_step(1, ['new_step_2'])
    first['title'] = 'new_step_2'
    second = add_step(2)
    second['before_step_ref'] = 'new_step_1'
    plan, changes, routes = scope(
        [
            first,
            second,
            {
                'type': 'LINK_CONTENT',
                'step_ref': 'new_step_1',
                'result_refs': ['new_result_1'],
                'revision_id': 7,
                'block_ids': [8],
            },
        ]
    )
    original = deepcopy(changes)
    resolved, _ = plan.resolve(
        changes,
        routes,
        {
            'new_step_1': 's2',
            'new_step_2': 's3',
            'new_result_1': 's2.o1',
            'new_result_2': 's3.o1',
        },
    )
    assert resolved[0]['dependencies'] == ['s3']
    assert resolved[0]['title'] == 'new_step_2'
    assert resolved[2]['result_refs'] == ['s2.o1']
    assert changes == original
    with pytest.raises(ValueError):
        plan.resolve(changes, routes, {'new_step_1': 's2'})


def test_route_cannot_capture_symbols_from_another_card_or_missing_document():
    with pytest.raises(InvalidInput):
        scope([add_step(1, ['new_step_2'])])
    with pytest.raises(InvalidInput):
        scope([{'type': 'RENAME_STEP', 'step_ref': 's2', 'title': '其他文档'}])
    with pytest.raises(InvalidInput):
        scope([{'type': 'MOVE_ISSUE', 'issue_ref': 'i2', 'to_step_ref': 's1'}])


def test_duplicate_declarations_and_conflicting_writes_reject_entire_batch():
    with pytest.raises(InvalidInput):
        scope([add_step(), add_step()])
    first, second = add_step(1), add_step(2)
    second['expected_results'][0]['temp_result_ref'] = 'new_result_1'
    with pytest.raises(InvalidInput):
        scope([first, second])
    with pytest.raises(InvalidInput):
        scope(
            [
                {
                    'type': 'DISPOSE_ISSUE',
                    'issue_ref': 'i1',
                    'disposition': 'DEFERRED',
                    'reason': '待核实',
                },
                {'type': 'RESUME_ISSUE', 'issue_ref': 'i1'},
            ]
        )


def test_result_cannot_be_linked_under_another_owner_or_allocated_to_wrong_step():
    first = add_step()
    with pytest.raises(InvalidInput):
        scope(
            [
                first,
                {
                    'type': 'LINK_CONTENT',
                    'step_ref': 's1',
                    'result_refs': ['new_result_1'],
                    'revision_id': 1,
                    'block_ids': [1],
                },
            ]
        )
    plan, changes, routes = scope([first])
    with pytest.raises(ValueError):
        plan.resolve(changes, routes, {'new_step_1': 's2', 'new_result_1': 's1.o2'})
    with pytest.raises(ValueError):
        plan.resolve(changes, routes, {'new_step_1': 's1', 'new_result_1': 's1.o2'})


def test_cancel_requires_complete_result_routes_without_landing_any_content():
    changes = [
        add_step(),
        {'type': 'CANCEL_STEP', 'step_ref': 's1', 'replacement_step_refs': ['new_step_1']},
    ]
    with pytest.raises(InvalidInput):
        scope(changes)
    route = {
        'from_result_ref': 's1.o1',
        'disposition': 'REPLACED',
        'target_result_refs': ['new_result_1'],
        'reason': '后续步骤承接原成果要求',
    }
    plan, parsed, routes = scope(changes, [route])
    assert plan.result_owners['new_result_1'] == 'new_step_1'
    assert routes[0]['target_result_refs'] == ['new_result_1']
    route['target_result_refs'] = ['s1.o1']
    with pytest.raises(InvalidInput):
        scope(changes, [route])


def test_strict_path_shape_rejects_exploratory_schema_names_and_unknown_authority():
    item = add_step()
    item['temp_ref'] = item.pop('temp_step_ref')
    with pytest.raises(InvalidInput):
        scope([item])
    item = add_step()
    item['actor'] = 'PROGRAM'
    with pytest.raises(InvalidInput):
        scope([item])


def test_batch_budget_counts_utf8_and_rejects_whole_batch():
    with pytest.raises(InvalidInput):
        route_batch([{'type': 'RENAME_STEP', 'step_ref': 's1', 'title': '修改'}] * 21, [])
    # 20 legal text fields can collectively exceed 64KiB in UTF-8.
    changes = [{'type': 'SET_GOAL', 'text': '内容' * 500, 'source_refs': []} for _ in range(20)]
    # Add route reasons so the canonical batch exceeds 64KiB without oversized fields.
    routes = [
        {
            'from_result_ref': f's1.o{i}',
            'disposition': 'NOT_REQUIRED',
            'target_result_refs': [],
            'reason': '内容' * 500,
        }
        for i in range(1, 21)
    ]
    with pytest.raises(InvalidInput):
        route_batch(changes, routes)


def test_native_completion_allows_omissions_but_not_null_or_fabricated_resolution():
    command = {
        'type': 'FORMATION',
        'action': 'COMPLETE_STEP',
        'step_ref': 's1',
        'expected_definition_version': 1,
        'expected_goal_version': 1,
        'expected_content_version': 1,
        'result_dispositions': [],
        'issue_dispositions': [],
        'branch_dispositions': [],
        'next_step_ref': None,
    }
    assert native_command(command) == command
    invalid = deepcopy(command)
    invalid['result_dispositions'] = None
    with pytest.raises(InvalidInput):
        native_command(invalid)
    invalid = deepcopy(command)
    invalid['issue_dispositions'] = [
        {'ref': 'i1', 'disposition': 'RESOLVED', 'to_step_ref': None, 'reason': None}
    ]
    with pytest.raises(InvalidInput):
        native_command(invalid)


def test_native_resume_requires_immutable_basis_and_real_boolean():
    command = {
        'type': 'FORMATION',
        'action': 'RESUME_BRANCH',
        'step_ref': 's1',
        'branch_ref': 'b1',
        'expected_branch_status': 'RESOLVED',
        'expected_branch_event_id': 9,
        'enter_after_resume': False,
    }
    assert native_command(command) == command
    for key, value in [
        ('expected_branch_event_id', True),
        ('enter_after_resume', 1),
        ('expected_branch_status', 'DROPPED'),
    ]:
        invalid = {**command, key: value}
        with pytest.raises(InvalidInput):
            native_command(invalid)


def test_target_null_enter_and_resume_are_different_intents():
    empty = dict(
        discussion_step_ref=None,
        discussion_branch_ref=None,
        branch_intent=None,
        branch_resume_basis=None,
    )
    assert target_selection(empty) == empty
    enter = {
        **empty,
        'discussion_step_ref': 's1',
        'discussion_branch_ref': 'b1',
        'branch_intent': 'ENTER',
    }
    assert target_selection(enter) == enter
    with pytest.raises(InvalidInput):
        target_selection({**enter, 'branch_intent': 'RESUME'})
    resume = {
        **enter,
        'branch_intent': 'RESUME',
        'branch_resume_basis': {
            'expected_branch_status': 'DEFERRED',
            'expected_branch_event_id': 8,
        },
    }
    assert target_selection(resume) == resume
    with pytest.raises(InvalidInput):
        target_selection({**resume, 'branch_intent': 'ENTER'})
    with pytest.raises(InvalidInput):
        target_selection({**empty, 'branch_resume_basis': resume['branch_resume_basis']})


def test_depth_and_document_history_have_no_lifetime_or_recursive_cap():
    steps = {f's{i}' for i in range(1, 5001)}
    owners = {f'{ref}.o1': ref for ref in steps}
    plan, _, _ = scope(
        [{'type': 'RENAME_STEP', 'step_ref': 's5000', 'title': '后续步骤'}],
        step_refs=steps,
        result_owners=owners,
    )
    assert len(plan.step_refs) == 5000
    edges = [(f's{i}', f's{i + 1}') for i in range(1, 5000)]
    acyclic(steps, edges, 'dependencies')
    with pytest.raises(InvalidInput):
        acyclic(steps, [*edges, ('s5000', 's1')], 'dependencies')


def test_dual_open_owner_constraint_does_not_apply_to_historical_closed_branch():
    steps = {
        's1': {'status': 'IN_PROGRESS', 'position': 1},
        's2': {'status': 'COMPLETED', 'position': 2},
    }
    branches = {'b1': {'origin_step_ref': 's1', 'return_step_ref': 's2', 'status': 'RESOLVED'}}
    issues = {'i1': {'step_ref': 's1', 'branch_ref': 'b1', 'disposition': 'OPEN'}}
    arguments = dict(
        current_step_ref='s1', active_branch_ref=None, dependencies=[], replacements=[]
    )
    validate_graph(steps, branches, issues, **arguments)
    branches['b1']['status'] = 'OPEN'
    with pytest.raises(InvalidInput):
        validate_graph(steps, branches, issues, **arguments)
    issues['i1']['step_ref'] = 's2'
    validate_graph(steps, branches, issues, **arguments)
    with pytest.raises(InvalidInput):
        validate_graph(steps, branches, issues, **{**arguments, 'active_branch_ref': 'b1'})


def test_each_native_action_has_only_its_own_registered_fields():
    with pytest.raises(InvalidInput):
        native_command(
            {'type': 'FORMATION', 'action': 'SWITCH_STEP', 'step_ref': None, 'actor': 'USER'}
        )
    with pytest.raises(InvalidInput):
        native_command({'type': 'FORMATION', 'action': 'SWITCH_STEP'})
    assert (
        native_command({'type': 'FORMATION', 'action': 'SWITCH_STEP', 'step_ref': None})['step_ref']
        is None
    )


def test_route_reference_sets_use_the_batch_budget_without_model_material_caps():
    changes, _ = route_batch(
        [
            {
                'type': 'SET_DEPENDENCIES',
                'step_ref': 's1',
                'dependencies': [f's{number}' for number in range(2, 202)],
            }
        ],
        [],
    )
    assert len(changes[0]['dependencies']) == 200


def test_business_text_preserves_spaces_normalizes_line_endings_and_rejects_surrogates():
    from backend.app.formation.types import text

    assert (
        text('  第一行' + chr(13) + chr(10) + '第二行  ', 'description')
        == '  第一行' + chr(10) + '第二行  '
    )
    with pytest.raises(InvalidInput):
        text(chr(0xD800), 'description')
