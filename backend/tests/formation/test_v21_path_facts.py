"""Route history stores each final fact once with real identities and member rows."""

from backend.app.formation.path_facts import event_keys, route_facts
from backend.app.formation.path_plan import prepare_route
from backend.app.formation.route_storage import resolve_route
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_path_plan import graph


def complete_graph():
    before = graph()
    before[3]['b1'].update(
        {
            'question': '待讨论事项',
            'relevance': '影响方案形成',
            'origin_event_id': 3,
            'result_summary': None,
            'result_sources_json': '[]',
        }
    )
    before[4]['i1'].update(
        {
            'description': '待明确事项',
            'blocking': 1,
            'source_refs_json': '[]',
            'resolution_sources_json': '[]',
        }
    )
    return before


def test_multiple_definition_changes_have_one_scalar_fact_and_separate_member_delta():
    before = complete_graph()
    plan = prepare_route(
        *before,
        [
            {'type': 'RENAME_STEP', 'step_ref': 's2', 'title': '完整设计'},
            {'type': 'SET_DEPENDENCIES', 'step_ref': 's2', 'dependencies': []},
            {'type': 'UPDATE_RESULT', 'result_ref': 's2.o1', 'description': '完整前后端设计'},
        ],
        [],
    )
    keys = event_keys(before, plan)
    assert keys == (('STEP_UPDATED', 's2'),)
    facts = route_facts(before, plan, keys)
    step = [fact for fact in facts if fact.kind == 'STEP']
    assert len(step) == 1
    assert step[0].before['definition_version'] == 3
    assert step[0].after['definition_version'] == 4
    assert step[0].after['title'] == '完整设计'
    assert list(step[0].members()) == [
        {
            'ordinal': 1,
            'collection': 'DEPENDENCY',
            'member_key': 's1',
            'before': {'kind': 'REF', 'ref': 's1'},
            'after': None,
        }
    ]
    assert len([fact for fact in facts if fact.kind == 'RESULT']) == 1


def test_move_freezes_each_affected_order_without_putting_the_whole_route_in_json():
    before = complete_graph()
    plan = prepare_route(
        *before, [{'type': 'MOVE_STEP', 'step_ref': 's2', 'before_step_ref': 's1'}], []
    )
    facts = route_facts(before, plan, event_keys(before, plan))
    order = [fact for fact in facts if fact.kind == 'ORDER']
    assert len(order) == 2
    assert all(set(fact.after) == {'step_ref', 'position'} for fact in order)
    assert {fact.ref: fact.after['position'] for fact in order} == {'s1': 2, 's2': 1}
    assert all('step_refs' not in fact.after for fact in facts)
    assert all(fact.owner == ('STEP_MOVED', 's2') for fact in facts)


def test_cancel_records_real_result_route_old_display_position_and_original_branch_origin():
    before = complete_graph()
    plan = prepare_route(
        *before,
        [
            add_step(),
            {'type': 'CANCEL_STEP', 'step_ref': 's1', 'replacement_step_refs': ['new_step_1']},
            {'type': 'MOVE_ISSUE', 'issue_ref': 'i1', 'to_step_ref': 'new_step_1'},
            {'type': 'SET_BRANCH_RETURN', 'branch_ref': 'b1', 'return_step_ref': 'new_step_1'},
            {'type': 'SET_DEPENDENCIES', 'step_ref': 's2', 'dependencies': ['new_step_1']},
        ],
        [
            {
                'from_result_ref': 's1.o1',
                'disposition': 'REPLACED',
                'target_result_refs': ['new_result_1'],
                'reason': '完整承接成果要求',
            }
        ],
    )
    resolved = resolve_route(plan, {'new_step_1': 's3', 'new_result_1': 's3.o1'}, {'new_step_1': 2})
    facts = route_facts(before, resolved, event_keys(before, resolved))
    route = next(fact for fact in facts if fact.kind == 'RESULT_ROUTE')
    assert route.after['target_result_refs'] == ['s3.o1']
    cancelled = next(fact for fact in facts if fact.kind == 'STEP' and fact.ref == 's1')
    assert cancelled.before['position'] == cancelled.after['position'] == 1
    assert cancelled.after['status'] == 'CANCELLED'
    branch = next(fact for fact in facts if fact.kind == 'BRANCH')
    assert branch.after['origin_step_ref'] == 's1'
    assert branch.after['return_step_ref'] == 's3'
    assert len({(fact.kind, fact.ref) for fact in facts}) == len(facts)


def test_full_history_graph_requires_no_per_step_rescan_of_all_results_or_edges():
    size = 5000
    head = {
        'document_id': 1,
        'version': 1,
        'goal_version': 1,
        'goal_text': '长期形成同一文档',
        'goal_sources_json': '[]',
        'current_step_ref': None,
        'active_branch_ref': None,
        'next_step_no': size + 1,
        'next_issue_no': 1,
        'next_branch_no': 1,
        'next_artifact_no': 1,
    }
    steps = {
        f's{i}': {
            'document_id': 1,
            'step_ref': f's{i}',
            'definition_version': 1,
            'next_result_no': 2,
            'position': i,
            'title': '历史步骤',
            'status': 'PLANNED',
            'closure_event_id': None,
        }
        for i in range(1, size + 1)
    }
    results = {
        f's{i}.o1': {
            'document_id': 1,
            'step_ref': f's{i}',
            'result_ref': f's{i}.o1',
            'description': '完整成果',
            'kind': 'CONTENT',
        }
        for i in range(1, size + 1)
    }
    dependencies = {(f's{i + 1}', f's{i}') for i in range(1, size)}
    before = head, steps, results, {}, {}, dependencies, set()
    plan = prepare_route(
        *before, [{'type': 'RENAME_STEP', 'step_ref': 's5000', 'title': '继续形成设计'}], []
    )
    facts = route_facts(before, plan, event_keys(before, plan))
    assert len(facts) == 1
    assert facts[0].ref == 's5000'
    assert list(facts[0].members()) == []
