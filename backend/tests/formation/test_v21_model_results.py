"""Actual C01/count/Chat fixture/C07 proves all-or-none formation storage."""

from copy import deepcopy
import json
import pytest

from backend.app.guide.queries import get_guide_run
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_model_contracts import examples
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, execute, output, delta

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def progress(context, changes):
    value = delta(context)
    value['formation_delta'] = {
        'basis': context.canonical['formation']['basis'],
        'changes': changes,
    }
    return value


def initialized(context, *, invalid=False, extras=()):
    initial = deepcopy(examples()[0])
    initial['goal']['source_refs'] = [context.input['current_request']['message_ref']]
    if invalid:
        initial['goal']['source_refs'] = ['m999999']
    return output(context, progress_delta=progress(context, [initial, *extras]))


def test_actual_audited_initialize_and_progress_advance_once_and_read_back(workspace, monkeypatch):
    offline_gate(monkeypatch)
    accepted(workspace, request(workspace))
    gateway = Gateway(initialized)
    result = execute(workspace, gateway)
    assert result['code'] == 'AI_FINISHED', result
    assert len(gateway.calls) == 1
    read = get_guide_run(workspace[0], 1, catalog=workspace[2])
    assert read['code'] == 'READ_OK', read
    data = read['data']
    assert data['effect_state'] == 'APPLIED'
    assert data['formation_result'] == data['progress_result'] == 'APPLIED'
    assert data['proposal_result'] == 'NOT_APPLICABLE'
    assert data['component_errors'] == []
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
        assert root['discussion_version'] == 3 and root['document_work_state'] == 'IDLE'
        assert not root['discussion_state_json']['pending_user_message_ids']
        head = dict(connection.execute('SELECT * FROM formation_heads').fetchone())
        assert head['version'] == head['goal_version'] == 1
        assert head['current_step_ref'] == 's1'
        assert (
            connection.execute('SELECT status FROM formation_steps').fetchone()[0] == 'IN_PROGRESS'
        )
        events = connection.execute(
            'SELECT * FROM document_change_audits WHERE guide_run_id=1'
        ).fetchall()
        assert events and all(row['source_type'] == 'AI_MESSAGE' for row in events)
        assert all(row['source_id'] == data['latest_assistant_message_id'] for row in events)
        audits = connection.execute('SELECT * FROM llm_uses').fetchall()
        assert len(audits) == 1 and audits[0]['validation_status'] == 'SUCCEEDED'
        assert json.loads(audits[0]['trusted_output_json'])['progress_delta']['formation_delta']
        assert (
            connection.execute('SELECT count(*) FROM revisions WHERE document_id=1').fetchone()[0]
            == 1
        )


@pytest.mark.parametrize('invalid_part', ['formation', 'progress', 'header', 'cards'])
def test_one_invalid_part_rejects_whole_structure_and_keeps_pending(
    workspace, monkeypatch, invalid_part
):
    offline_gate(monkeypatch)
    accepted(workspace, request(workspace))

    def returned(context):
        value = initialized(context, invalid=invalid_part == 'formation')
        if invalid_part == 'progress':
            value['progress_delta']['evidence_changes'][0]['source_refs'] = ['missing']
        elif invalid_part == 'header':
            del value['analysis']
        elif invalid_part == 'cards':
            value['cards'] = {'purpose': 'STAGED_WRITE'}
        return value

    result = execute(workspace, Gateway(returned))
    assert result['code'] == 'AI_FINISHED', result
    read = get_guide_run(workspace[0], 1, catalog=workspace[2])
    assert read['code'] == 'READ_OK', read
    data = read['data']
    assert data['effect_state'] == 'STRUCTURED_REJECTED'
    assert (
        data['progress_result'] == data['formation_result'] == data['proposal_result'] == 'REJECTED'
    )
    assert data['component_errors'] == ['OUTPUT_INVALID'] and data['returned_responses']
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
        assert root['discussion_version'] == 2 and root['document_work_state'] == 'IDLE'
        assert root['discussion_state_json']['pending_user_message_ids']
        assert connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM formation_event_changes').fetchone()[0] == 0
        row = connection.execute('SELECT * FROM llm_uses').fetchone()
        assert row['validation_status'] == 'FAILED' and row['trusted_output_json'] is None
        message = connection.execute(
            "SELECT content,structured_content_json FROM conversation_messages WHERE role='ASSISTANT'"
        ).fetchone()
        assert message['structured_content_json'] is None
        assert 'schema_version' in message['content']


def test_actual_initialize_assessment_recommendation_share_real_events(workspace, monkeypatch):
    offline_gate(monkeypatch)
    accepted(workspace, request(workspace))

    def returned(context):
        assessment = deepcopy(examples()[9])
        recommendation = deepcopy(examples()[10])
        for item in (assessment, recommendation):
            item['step_ref'] = 'new_step_1'
            item['source_refs'] = [context.input['current_request']['message_ref']]
        assessment['document_refs'] = []
        return initialized(context, extras=(assessment, recommendation))

    result = execute(workspace, Gateway(returned))
    assert result['code'] == 'AI_FINISHED', result
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_assessments').fetchone()[0] == 1
        assert (
            connection.execute('SELECT count(*) FROM formation_recommendations').fetchone()[0] == 1
        )
        assert connection.execute('SELECT version FROM formation_heads').fetchone()[0] == 1
        row = connection.execute('SELECT final_result_json FROM guide_runs').fetchone()
        assert json.loads(row[0])['effect_state'] == 'APPLIED'


def test_natural_reply_does_not_initialize_or_claim_business_change(workspace, monkeypatch):
    offline_gate(monkeypatch)
    accepted(workspace, request(workspace))
    result = execute(workspace, Gateway(output))
    assert result['code'] == 'AI_FINISHED', result
    data = get_guide_run(workspace[0], 1, catalog=workspace[2])['data']
    assert data['effect_state'] == 'APPLIED'
    assert (
        data['formation_result']
        == data['progress_result']
        == data['proposal_result']
        == 'NOT_APPLICABLE'
    )
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0
        assert RequirementRepository(connection).get_for_document(1, 1)['discussion_version'] == 2
