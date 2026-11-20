"""Real C01 transactions freeze V2.1 targets without a fabricated model round."""

import json
from uuid import uuid4
import pytest

from backend.app.guide.commands import create_guide_run, cancel_guide_run
from backend.app.formation.commands import update_state
from backend.app.formation.discuss_contracts import formation_discuss_input
from backend.app.infrastructure.model_profile import DEFAULT_PROFILE
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.validation import InvalidInput
from backend.tests.formation.test_v21_schema import (
    database,
    released,
    workspace as base_workspace,
    head,
)
from backend.tests.formation.test_v21_state_commands import payload as state_payload
from backend.tests.formation.test_v21_path_commands import snapshot
from backend.tests.formation.test_v21_completion_commands import seed

__all__ = ['database', 'released', 'base_workspace']


@pytest.fixture
def workspace(base_workspace):
    db, executor, catalog = base_workspace
    return db, executor, catalog.for_formation_profile(DEFAULT_PROFILE)


def request(workspace, target=None, **extra):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    return {
        'requirement_id': 1,
        'document_id': 1,
        'expected_discussion_version': root['discussion_version'],
        'operation': 'DISCUSS',
        'instruction': '  继续形成当前设计  ',
        'target': {
            'discussion_step_ref': None,
            'discussion_branch_ref': None,
            'branch_intent': None,
            'branch_resume_basis': None,
        }
        if target is None
        else target,
        'scope': None,
        'source_refs': [],
        'proposal_ref': None,
        'proposal_intent': None,
        'acknowledge_source_changes': False,
        'idempotency_key': str(uuid4()),
        **extra,
    }


def accepted(workspace, body):
    result = create_guide_run(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'GUIDE_ACCEPTED', result
    return result


def test_whole_document_acceptance_freezes_real_null_head_and_original_input_then_replays(
    workspace,
):
    body = request(workspace)
    result = accepted(workspace, body)
    current = snapshot(workspace[0])
    assert create_guide_run(workspace[1], body, catalog=workspace[2]) == result
    assert snapshot(workspace[0]) == current
    with workspace[0].transaction() as connection:
        run = connection.execute(
            'SELECT * FROM guide_runs WHERE id=?', (result['data']['guide_run_id'],)
        ).fetchone()
        basis = json.loads(run['execution_basis_json'])
        assert run['context_template_key'] == 'formation_context_v21_1'
        assert basis['formation']['basis']['formation_version'] is None
        assert basis['formation']['basis']['goal_version'] is None
        assert basis['formation_selection'] == result['data']['accepted_target'] == body['target']
        assert basis['user_message']['content'] == body['instruction']
        assert basis['authorization']['allowed_targets'] == []
        assert basis['discussion_version'] == body['expected_discussion_version'] + 1
        assert connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_accepting_planned_step_reuses_real_user_source_and_advances_d_f_once(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)
    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1'
    result = accepted(workspace, body)
    with workspace[0].transaction() as connection:
        step = connection.execute('SELECT * FROM formation_steps WHERE document_id=1').fetchone()
        formed = connection.execute('SELECT * FROM formation_heads WHERE document_id=1').fetchone()
        assert (
            step['status'] == 'IN_PROGRESS'
            and formed['current_step_ref'] == 's1'
            and formed['version'] == 2
        )
        run = connection.execute(
            'SELECT * FROM guide_runs WHERE id=?', (result['data']['guide_run_id'],)
        ).fetchone()
        basis = json.loads(run['execution_basis_json'])
        assert basis['discussion_version'] == body['expected_discussion_version'] + 1
        assert basis['formation']['basis']['formation_version'] == 2
        assert basis['formation']['selected_step']['status'] == 'IN_PROGRESS'
        event = connection.execute(
            "SELECT * FROM document_change_audits WHERE reason_code='STEP_STARTED' ORDER BY id DESC"
        ).fetchone()
        assert event['source_type'] == 'USER_ACTION'
        assert event['source_id'] == result['data']['user_message_id']
        assert event['guide_run_id'] == run['id']
        assert json.loads(event['payload_json'])['event']['actor'] == 'USER'


def test_branch_resume_is_consumed_by_acceptance_and_never_replayed_after_cancel(workspace):
    seed(workspace, related=True)
    deferred = update_state(
        workspace[1],
        state_payload(
            workspace, 'DISPOSE_BRANCH', branch_ref='b1', disposition='DEFERRED', reason='稍后继续'
        ),
    )
    assert deferred['code'] == 'UPDATED', deferred
    event_id = deferred['data']['event_ids'][0]
    target = {
        'discussion_step_ref': 's1',
        'discussion_branch_ref': 'b1',
        'branch_intent': 'RESUME',
        'branch_resume_basis': {
            'expected_branch_status': 'DEFERRED',
            'expected_branch_event_id': event_id,
        },
    }
    body = request(workspace, target=target)
    result = accepted(workspace, body)
    assert result['data']['accepted_target']['branch_intent'] == 'ENTER'
    assert result['data']['accepted_target']['branch_resume_basis'] is None
    cancelled = cancel_guide_run(
        workspace[1],
        {'guide_run_id': result['data']['guide_run_id'], 'idempotency_key': str(uuid4())},
    )
    assert cancelled['code'] in ('GUIDE_CANCELLED', 'CANCELLED'), cancelled
    old = request(workspace, target=target)
    before = snapshot(workspace[0])
    rejected = create_guide_run(workspace[1], old, catalog=workspace[2])
    assert rejected['code'] == 'STATE_CONFLICT', rejected
    assert rejected['details']['reason'] == 'BRANCH_STATE_CHANGED'
    assert snapshot(workspace[0]) == before


@pytest.mark.parametrize(
    'mutation',
    [
        lambda value: value['target'].update(discussion_branch_ref='b1'),
        lambda value: value['target'].update(private_basis={}),
        lambda value: value.update(proposal_intent='ADJUST_WRITE'),
        lambda value: value.update(operation='GENERATE'),
        lambda value: value.update(scope={'scope_type': 'DOCUMENT', 'private_scope': True}),
    ],
)
def test_strict_target_scope_and_operation_are_rejected_before_acceptance(workspace, mutation):
    value = request(workspace)
    mutation(value)
    with pytest.raises(InvalidInput):
        formation_discuss_input(value)


def test_old_release_cannot_accept_new_input_and_does_not_consume_a_success(workspace):
    from backend.app.infrastructure.resources import ResourceCatalog

    body = request(workspace)
    before = snapshot(workspace[0])
    result = create_guide_run(workspace[1], body, catalog=ResourceCatalog())
    assert result['code'] == 'CONFIG_INVALID', result
    assert snapshot(workspace[0]) == before


def test_frozen_material_failure_rolls_back_message_run_focus_and_same_key_can_retry(
    workspace, monkeypatch
):
    from backend.app.formation import discuss_acceptance

    with workspace[0].transaction(write=True) as connection:
        head(connection)
    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1'
    before = snapshot(workspace[0])
    original = discuss_acceptance.capture_material

    def unavailable(*args, **kwargs):
        raise StorageUnavailable('isolated failure')

    monkeypatch.setattr(discuss_acceptance, 'capture_material', unavailable)
    assert (
        create_guide_run(workspace[1], body, catalog=workspace[2])['code'] == 'STORAGE_UNAVAILABLE'
    )
    assert snapshot(workspace[0]) == before
    monkeypatch.setattr(discuss_acceptance, 'capture_material', original)
    accepted(workspace, body)
