"""Bounded proposals derive exact availability from actual publications and immutable protection."""

from uuid import uuid4
import pytest

from backend.app.formation.commands import update_proposal
from backend.app.formation.read_queries import read_entities
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_model_publication import publish, write_group
from backend.tests.formation.test_v21_proposal_adjustment import run_round
from backend.tests.formation.test_v21_card_apply import answer, submit
from backend.tests.formation.test_v21_path_commands import snapshot
from backend.tests.guide.test_v15_execution import Gateway, output

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def page(workspace, query=None):
    result = read_entities(workspace[0], 1, 1, 'proposals', query or {}, catalog=workspace[2])
    assert result['code'] == 'READ_OK', result
    return result['data']


def test_paging_has_complete_total_and_old_pending_remains_applicable_then_content_expiry(
    workspace, monkeypatch
):
    first, _ = publish(workspace, monkeypatch, initial=True)
    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1'
    received = accepted(workspace, body)
    run_round(
        workspace,
        received['data']['guide_run_id'],
        Gateway(lambda context: output(context, cards=write_group(context))),
    )
    before = snapshot(workspace[0])
    front = page(workspace, {'limit': 1})
    assert front['value']['total'] == 2 and front['pagination']['has_more']
    assert front['value']['items'][0]['message_id'] == first['id']
    assert front['value']['items'][0]['can_apply']
    following = page(
        workspace,
        {
            'limit': 1,
            'known_f': front['value']['formation_version'],
            'cursor': front['pagination']['next_cursor'],
        },
    )
    assert following['value']['total'] == 2 and not following['pagination']['has_more']
    assert following['value']['items'][0]['message_id'] != first['id']
    assert snapshot(workspace[0]) == before
    adopted = submit(workspace, answer(workspace, first))
    assert adopted['code'] == 'PROGRAM_PROCESSED', adopted
    stale = read_entities(
        workspace[0],
        1,
        1,
        'proposals',
        {'limit': 1, 'cursor': front['pagination']['next_cursor']},
        catalog=workspace[2],
    )
    assert stale['code'] == 'STATE_CONFLICT' and stale['details']['reason'] == 'PATH_CHANGED'
    values = page(workspace)['value']['items']
    assert (
        values[0]['disposition'] == 'APPLIED' and values[0]['expiry_reason'] == 'ALREADY_ANSWERED'
    )
    assert (
        values[1]['disposition'] == 'PENDING'
        and values[1]['expiry_reason'] == 'CONTENT_CHANGED'
        and not values[1]['can_apply']
    )
    assert not any(
        key in str(values)
        for key in ('protected_semantic_digest', 'binding_json', 'origin_frozen_formation_version')
    )
    assert page(workspace, {'state': 'APPLIED'})['value']['total'] == 1
    assert (
        read_entities(workspace[0], 1, 1, 'proposals', {'step_ref': 's1'}, catalog=workspace[2])[
            'code'
        ]
        == 'INVALID_INPUT'
    )


def test_deferred_and_resume_availability_do_not_rebind_or_consume_formal_answer(
    workspace, monkeypatch
):
    message, _ = publish(workspace, monkeypatch)
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    command = {
        'requirement_id': 1,
        'document_id': 1,
        'expected_discussion_version': root['discussion_version'],
        'discussion_command': {
            'type': 'FORMATION',
            'action': 'DEFER_WRITE_PROPOSAL',
            'proposal': {'message_id': message['id'], 'card_key': 'c1'},
            'reason': '稍后处理',
        },
        'idempotency_key': str(uuid4()),
    }
    result = update_proposal(workspace[1], command, catalog=workspace[2])
    assert result['code'] == 'UPDATED', result
    value = page(workspace)['value']['items'][0]
    assert value['disposition'] == 'DEFERRED' and not value['can_apply']
    assert value['expiry_reason'] is None and value['reasons'] == ['DEFERRED']
    available = {item['action']: item for item in value['availability']}
    assert available['RESUME_WRITE_PROPOSAL']['available'] and available['preview']['available']
    assert not available['apply']['available']


@pytest.mark.parametrize('purpose', ['STAGED_WRITE', 'FORMATION_PATH_CHANGE'])
def test_temporary_ai_occupancy_keeps_valid_proposal_and_cancel_restores_actions(
    workspace, monkeypatch, purpose
):
    from backend.app.guide.commands import cancel_guide_run
    from backend.app.messages.queries import list_messages

    message, _ = publish(workspace, monkeypatch, purpose=purpose)
    running = accepted(workspace, request(workspace))
    read = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2]
    )
    assert read['code'] == 'READ_OK', read
    assert (
        next(row for row in read['data']['items'] if row['id'] == message['id'])['card_state']
        == 'AVAILABLE'
    )
    proposal = page(workspace)['value']['items'][0]
    assert not proposal['can_apply'] and proposal['reasons'] == ['WORK_STATE_CONFLICT']
    assert proposal['expiry_reason'] is None
    before = snapshot(workspace[0])
    rejected = submit(workspace, answer(workspace, message))
    assert rejected['code'] == 'WORK_STATE_CONFLICT', rejected
    assert snapshot(workspace[0]) == before
    cancelled = cancel_guide_run(
        workspace[1],
        {'guide_run_id': running['data']['guide_run_id'], 'idempotency_key': str(uuid4())},
    )
    assert cancelled['code'] == 'GUIDE_CANCELLED', cancelled
    assert page(workspace)['value']['items'][0]['can_apply']
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'"
            ).fetchone()[0]
            == 0
        )
