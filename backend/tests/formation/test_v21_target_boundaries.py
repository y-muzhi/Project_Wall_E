"""Actual C01 validates complete cross-node targets before any partial start or resume."""

from uuid import uuid4

import pytest

from backend.app.formation.commands import update_path, update_state
from backend.app.guide.commands import cancel_guide_run, create_guide_run
from backend.tests.formation.test_v21_completion_commands import seed
from backend.tests.formation.test_v21_discuss_acceptance import (
    accepted,
    base_workspace,
    database,
    released,
    request,
    workspace,
)
from backend.tests.formation.test_v21_path_commands import request as path_request
from backend.tests.formation.test_v21_path_commands import snapshot
from backend.tests.formation.test_v21_state_commands import payload

__all__ = ['base_workspace', 'database', 'released', 'workspace']


def all_facts(workspace):
    facts = snapshot(workspace[0])
    with workspace[0].transaction() as connection:
        for table in (
            'guide_runs',
            'formation_branches',
            'formation_issues',
            'idempotency_records',
        ):
            facts[table] = [tuple(row) for row in connection.execute('SELECT * FROM ' + table)]
    return facts


def state(workspace):
    with workspace[0].transaction() as connection:
        return dict(
            connection.execute("SELECT * FROM formation_branches WHERE branch_ref='b1'").fetchone()
        )


def dispose(workspace, status='DEFERRED'):
    result = update_state(
        workspace[1],
        payload(
            workspace,
            'DISPOSE_BRANCH',
            branch_ref='b1',
            disposition=status,
            reason='明确暂缓或放弃',
        ),
    )
    assert result['code'] == 'UPDATED', result
    return state(workspace)


def target(branch, intent='ENTER', step='s1'):
    return {
        'discussion_step_ref': step,
        'discussion_branch_ref': 'b1',
        'branch_intent': intent,
        'branch_resume_basis': None
        if intent == 'ENTER'
        else {
            'expected_branch_status': branch['status'],
            'expected_branch_event_id': branch['state_event_id'],
        },
    }


def focus_other(workspace):
    assert (
        update_state(workspace[1], payload(workspace, 'SWITCH_STEP', step_ref='s2'))['code']
        == 'UPDATED'
    )


def cancel(workspace, identity):
    result = cancel_guide_run(
        workspace[1], {'guide_run_id': identity, 'idempotency_key': str(uuid4())}
    )
    assert result['code'] in ('GUIDE_CANCELLED', 'CANCELLED'), result


@pytest.mark.parametrize('status', ['OPEN', 'DEFERRED'])
def test_cross_node_target_is_one_real_acceptance_with_normalized_frozen_target(workspace, status):
    seed(workspace, related=True)
    if status == 'DEFERRED':
        dispose(workspace)
    focus_other(workspace)
    before = all_facts(workspace)
    body = request(
        workspace, target=target(state(workspace), 'ENTER' if status == 'OPEN' else 'RESUME')
    )
    result = accepted(workspace, body)
    after = all_facts(workspace)
    assert result['data']['accepted_target'] == target(state(workspace))
    with workspace[0].transaction() as connection:
        current = dict(connection.execute('SELECT * FROM formation_heads').fetchone())
        assert current['current_step_ref'] == 's1' and current['active_branch_ref'] == 'b1'
        assert (
            current['version']
            == dict(
                zip(
                    [r[1] for r in connection.execute('PRAGMA table_info(formation_heads)')],
                    before['formation_heads'][0],
                    strict=True,
                )
            )['version']
            + 1
        )
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s1'").fetchone()[
                0
            ]
            == 'IN_PROGRESS'
        )
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s2'").fetchone()[
                0
            ]
            == 'PLANNED'
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
    assert accepted(workspace, body) == result
    assert all_facts(workspace) == after
    cancel(workspace, result['data']['guide_run_id'])


@pytest.mark.parametrize('status', ['DEFERRED', 'DROPPED', 'RESOLVED'])
def test_old_enter_cannot_implicitly_resume_and_cannot_half_start_parent(
    workspace, monkeypatch, status
):
    seed(workspace, related=True)
    if status == 'RESOLVED':
        from backend.tests.formation.test_v21_resume_terminal_matrix import result_output, run_round
        from backend.tests.guide.test_v15_counting import offline_gate
        from backend.tests.guide.test_v15_execution import Gateway

        offline_gate(monkeypatch)
        first = accepted(workspace, request(workspace, target=target(state(workspace))))
        assert (
            run_round(workspace, first['data']['guide_run_id'], Gateway(result_output))['code']
            == 'AI_FINISHED'
        )
    else:
        dispose(workspace, status)
    focus_other(workspace)
    before = all_facts(workspace)
    result = create_guide_run(
        workspace[1], request(workspace, target=target(state(workspace))), catalog=workspace[2]
    )
    assert result['code'] == 'STATE_CONFLICT', result
    assert all_facts(workspace) == before


def test_same_status_with_new_resume_event_rejects_old_basis_without_partial_start(workspace):
    seed(workspace, related=True)
    first = dispose(workspace)
    old = target(first, 'RESUME')
    resumed = update_state(
        workspace[1],
        payload(
            workspace,
            'RESUME_BRANCH',
            step_ref='s1',
            branch_ref='b1',
            expected_branch_status='DEFERRED',
            expected_branch_event_id=first['state_event_id'],
            enter_after_resume=False,
        ),
    )
    assert resumed['code'] == 'UPDATED'
    newer = dispose(workspace)
    assert newer['status'] == first['status'] and newer['state_event_id'] != first['state_event_id']
    focus_other(workspace)
    before = all_facts(workspace)
    result = create_guide_run(workspace[1], request(workspace, target=old), catalog=workspace[2])
    assert (
        result['code'] == 'STATE_CONFLICT' and result['details']['reason'] == 'BRANCH_STATE_CHANGED'
    ), result
    assert all_facts(workspace) == before


@pytest.mark.parametrize('intent', ['ENTER', 'RESUME'])
def test_changed_return_point_rejects_entire_target_before_planned_parent_starts(workspace, intent):
    seed(workspace, related=True)
    if intent == 'RESUME':
        dispose(workspace)
    old = target(state(workspace), intent)
    focus_other(workspace)
    moved = update_path(
        workspace[1],
        path_request(
            workspace,
            [
                {'type': 'MOVE_ISSUE', 'issue_ref': 'i1', 'to_step_ref': 's2'},
                {'type': 'SET_BRANCH_RETURN', 'branch_ref': 'b1', 'return_step_ref': 's2'},
            ],
        ),
        catalog=workspace[2],
    )
    assert moved['code'] == 'UPDATED', moved
    before = all_facts(workspace)
    result = create_guide_run(workspace[1], request(workspace, target=old), catalog=workspace[2])
    assert (
        result['code'] == 'STATE_CONFLICT'
        and result['details']['reason'] == 'BRANCH_RETURN_MISMATCH'
    ), result
    assert all_facts(workspace) == before
