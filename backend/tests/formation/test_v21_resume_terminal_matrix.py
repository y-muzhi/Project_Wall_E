"""Real C01/C07 branch resume cross-product, including failed and cancelled returns."""

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from backend.app.formation.commands import complete_step, update_state
from backend.app.guide.commands import cancel_guide_run, create_guide_run
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.queries import get_guide_run
from backend.tests.formation.test_v21_completion_commands import request as completion_request
from backend.tests.formation.test_v21_completion_commands import seed
from backend.tests.formation.test_v21_discuss_acceptance import (
    accepted,
    base_workspace,
    database,
    released,
    request,
    workspace,
)
from backend.tests.formation.test_v21_model_contracts import examples
from backend.tests.formation.test_v21_model_results import progress
from backend.tests.formation.test_v21_state_commands import payload
from backend.tests.guide.test_v15_counting import Counter, offline_gate
from backend.tests.guide.test_v15_execution import PROFILE, Gateway, output

__all__ = ['base_workspace', 'database', 'released', 'workspace']


def run_round(workspace, identity, gateway):
    return asyncio.run(
        execute_guide_run(
            workspace[0],
            {'guide_run_id': identity},
            process_lock=workspace[1].process_lock,
            catalog=workspace[2],
            profile=PROFILE,
            gateway=gateway,
            counting_counter=Counter(['OK']),
        )
    )


def branch(workspace):
    with workspace[0].transaction() as connection:
        return dict(
            connection.execute("SELECT * FROM formation_branches WHERE branch_ref='b1'").fetchone()
        )


def result_output(context, *, invalid=False, summary='已核实风险'):
    change = deepcopy(examples()[7])
    change['result']['summary'] = summary
    change['result']['source_refs'] = [
        'm99999999' if invalid else context.input['current_request']['message_ref']
    ]
    return output(context, progress_delta=progress(context, [change]))


def cancel(workspace, identity):
    result = cancel_guide_run(
        workspace[1], {'guide_run_id': identity, 'idempotency_key': str(uuid4())}
    )
    assert result['code'] in ('GUIDE_CANCELLED', 'CANCELLED'), result


@pytest.mark.parametrize('status', ['RESOLVED', 'DEFERRED'])
@pytest.mark.parametrize('parent', ['IN_PROGRESS', 'PAUSED', 'COMPLETED'])
@pytest.mark.parametrize('outcome', ['valid', 'invalid', 'failed', 'cancelled'])
def test_real_resume_terminal_matrix_preserves_old_result_and_consumes_only_once(
    workspace, monkeypatch, status, parent, outcome
):
    offline_gate(monkeypatch)
    seed(workspace, related=True)
    first = accepted(
        workspace,
        request(
            workspace,
            target={
                'discussion_step_ref': 's1',
                'discussion_branch_ref': 'b1',
                'branch_intent': 'ENTER',
                'branch_resume_basis': None,
            },
        ),
    )
    assert (
        run_round(workspace, first['data']['guide_run_id'], Gateway(result_output))['code']
        == 'AI_FINISHED'
    )
    original = branch(workspace)
    assert original['status'] == 'RESOLVED' and original['result_summary'] == '已核实风险'
    with workspace[0].transaction() as connection:
        original_event = dict(
            connection.execute(
                'SELECT * FROM document_change_audits WHERE id=?', (original['state_event_id'],)
            ).fetchone()
        )
    if status == 'DEFERRED':
        # Reopen through the actual program command before deferring again.
        command = payload(
            workspace,
            'RESUME_BRANCH',
            step_ref='s1',
            branch_ref='b1',
            expected_branch_status='RESOLVED',
            expected_branch_event_id=original['state_event_id'],
            enter_after_resume=False,
        )
        assert update_state(workspace[1], command)['code'] == 'UPDATED'
        assert (
            update_state(
                workspace[1],
                payload(
                    workspace,
                    'DISPOSE_BRANCH',
                    branch_ref='b1',
                    disposition='DEFERRED',
                    reason='稍后核实',
                ),
            )['code']
            == 'UPDATED'
        )
    if parent == 'PAUSED':
        assert (
            update_state(workspace[1], payload(workspace, 'PAUSE_STEP', step_ref='s1'))['code']
            == 'UPDATED'
        )
    elif parent == 'COMPLETED':
        assert (
            complete_step(workspace[1], completion_request(workspace), catalog=workspace[2])['code']
            == 'UPDATED'
        )
    current = branch(workspace)
    target = {
        'discussion_step_ref': 's1',
        'discussion_branch_ref': 'b1',
        'branch_intent': 'RESUME',
        'branch_resume_basis': {
            'expected_branch_status': status,
            'expected_branch_event_id': current['state_event_id'],
        },
    }
    body = request(workspace, target=target)
    resumed = accepted(workspace, body)
    identity = resumed['data']['guide_run_id']
    assert resumed['data']['accepted_target'] == {
        **target,
        'branch_intent': 'ENTER',
        'branch_resume_basis': None,
    }
    resumed_event = branch(workspace)['state_event_id']
    assert branch(workspace)['status'] == 'OPEN' and branch(workspace)['result_summary'] is None
    if outcome == 'cancelled':
        cancel(workspace, identity)
    else:
        gateway = Gateway(
            lambda ctx: result_output(ctx, invalid=outcome == 'invalid', summary='新结果'),
            failed=outcome == 'failed',
        )
        result = run_round(workspace, identity, gateway)
        assert result['code'] == ('AI_FAILED' if outcome == 'failed' else 'AI_FINISHED'), result
        assert len(gateway.calls) == 1
    after = branch(workspace)
    assert after['status'] == ('RESOLVED' if outcome == 'valid' else 'OPEN')
    assert after['result_summary'] == ('新结果' if outcome == 'valid' else None)
    if outcome != 'valid':
        assert after['state_event_id'] == resumed_event
    if outcome == 'invalid':
        assert (
            get_guide_run(workspace[0], identity, catalog=workspace[2])['data']['effect_state']
            == 'STRUCTURED_REJECTED'
        )
    with workspace[0].transaction() as connection:
        assert (
            dict(
                connection.execute(
                    'SELECT * FROM document_change_audits WHERE id=?', (original['state_event_id'],)
                ).fetchone()
            )
            == original_event
        )
        assert connection.execute('SELECT count(*) FROM formation_branches').fetchone()[0] == 1
        assert connection.execute(
            "SELECT status FROM formation_steps WHERE step_ref='s1'"
        ).fetchone()[0] == ('IN_PROGRESS' if parent == 'PAUSED' else parent)
        assert (
            connection.execute(
                'SELECT content_version FROM requirement_documents WHERE id=1'
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute('SELECT count(*) FROM revisions WHERE document_id=1').fetchone()[0]
            == 1
        )
    assert accepted(workspace, body) == resumed
    assert branch(workspace) == after
    stale = request(workspace, target=target)
    rejected = create_guide_run(workspace[1], stale, catalog=workspace[2])
    assert rejected['code'] == 'STATE_CONFLICT', rejected
    assert branch(workspace) == after
    if outcome != 'valid':
        enter = {**target, 'branch_intent': 'ENTER', 'branch_resume_basis': None}
        following = accepted(workspace, request(workspace, target=enter))
        assert branch(workspace) == after
        cancel(workspace, following['data']['guide_run_id'])
        assert branch(workspace) == after
