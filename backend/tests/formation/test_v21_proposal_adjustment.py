"""Real adjustment acceptance/cancel/replacement never rewrites original proposal authority."""

import asyncio
from copy import deepcopy
import json
from uuid import uuid4

from backend.app.guide.commands import cancel_guide_run, submit_card_responses
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.formation.commands import update_proposal
from backend.app.formation.proposal_sources import read_reference
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
from backend.tests.formation.test_v21_card_apply import answer
from backend.tests.guide.test_v15_execution import Gateway, output, PROFILE
from backend.tests.guide.test_v15_counting import Counter

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def adjust(workspace, message):
    body = request(workspace)
    body['proposal_ref'] = {'message_id': message['id'], 'card_key': 'c1'}
    body['proposal_intent'] = 'ADJUST_WRITE'
    return accepted(workspace, body)


def run_round(workspace, run_id, gateway):
    result = asyncio.run(
        execute_guide_run(
            workspace[0],
            {'guide_run_id': run_id},
            process_lock=workspace[1].process_lock,
            catalog=workspace[2],
            profile=PROFILE,
            gateway=gateway,
            counting_counter=Counter(['OK']),
        )
    )
    assert result['code'] == 'AI_FINISHED', result
    return result


def old_value(workspace, message):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
        return read_reference(
            connection,
            root,
            {'message_id': message['id'], 'card_key': 'c1'},
            purpose='STAGED_WRITE',
        )


def test_cancel_keeps_adjustment_and_withdraw_adds_proof_without_rebinding(workspace, monkeypatch):
    message, _ = publish(workspace, monkeypatch)
    original = old_value(workspace, message)
    result = adjust(workspace, message)
    marked = old_value(workspace, message)
    assert marked.needs_revision and marked.binding == original.binding
    cancelled = cancel_guide_run(
        workspace[1],
        {'guide_run_id': result['data']['guide_run_id'], 'idempotency_key': str(uuid4())},
    )
    assert cancelled['code'] == 'GUIDE_CANCELLED', cancelled
    assert old_value(workspace, message).needs_revision
    rejected = submit_card_responses(workspace[1], answer(workspace, message), catalog=workspace[2])
    assert rejected['code'] == 'STATE_CONFLICT', rejected
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    command = {
        'requirement_id': 1,
        'document_id': 1,
        'expected_discussion_version': root['discussion_version'],
        'discussion_command': {
            'type': 'FORMATION',
            'action': 'WITHDRAW_PROPOSAL_ADJUSTMENT',
            'proposal': original.reference,
        },
        'idempotency_key': str(uuid4()),
    }
    withdrawn = update_proposal(workspace[1], command, catalog=workspace[2])
    assert withdrawn['code'] == 'UPDATED', withdrawn
    assert update_proposal(workspace[1], command, catalog=workspace[2]) == withdrawn
    after = old_value(workspace, message)
    assert not after.needs_revision and after.binding == original.binding
    with workspace[0].transaction() as connection:
        proof = connection.execute(
            "SELECT after_json FROM formation_event_changes WHERE entity_kind='PROPOSAL_CHECK'"
        ).fetchone()
        assert proof is not None
        assert (
            json.loads(proof[0])['expected_semantic_digest']
            == original.binding['protected_semantic_digest']
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'"
            ).fetchone()[0]
            == 0
        )


def test_successful_new_card_supersedes_original_only_after_new_card_saved(workspace, monkeypatch):
    message, _ = publish(workspace, monkeypatch)
    before = old_value(workspace, message)
    accepted_round = adjust(workspace, message)

    def replacement(context):
        value = write_group(context)
        value['action_payload']['markdown_content'] = '# 调整后的精确正文\n\n新内容。\n'
        return output(context, cards=value)

    run_round(workspace, accepted_round['data']['guide_run_id'], Gateway(replacement))
    with workspace[0].transaction() as connection:
        rows = connection.execute(
            'SELECT * FROM formation_proposal_index ORDER BY message_id'
        ).fetchall()
        assert (
            len(rows) == 2
            and rows[0]['disposition'] == 'SUPERSEDED'
            and rows[1]['disposition'] == 'PENDING'
        )
        assert json.loads(rows[0]['binding_json']) == before.binding
        root = RequirementRepository(connection).get_for_document(1, 1)
        assert root['discussion_version'] == 5
        assert connection.execute('SELECT version FROM formation_heads').fetchone()[0] == 5
        final = json.loads(
            connection.execute(
                'SELECT final_result_json FROM guide_runs WHERE id=?',
                (accepted_round['data']['guide_run_id'],),
            ).fetchone()[0]
        )
        assert final['effect_state'] == 'APPLIED' and final['proposal_result'] == 'APPLIED'
        assert (
            connection.execute(
                'SELECT markdown_content FROM requirement_documents WHERE id=1'
            ).fetchone()[0]
            == ''
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'"
            ).fetchone()[0]
            == 0
        )


def test_rejected_replacement_preserves_original_pending_and_adjustment(workspace, monkeypatch):
    message, _ = publish(workspace, monkeypatch)
    old = old_value(workspace, message)
    result = adjust(workspace, message)

    def invalid(context):
        value = write_group(context)
        value['action_payload']['source_refs'] = ['m999999']
        return output(context, cards=value)

    run_round(workspace, result['data']['guide_run_id'], Gateway(invalid))
    after = old_value(workspace, message)
    assert after.needs_revision and after.disposition == 'PENDING' and after.binding == old.binding
    with workspace[0].transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM formation_proposal_index').fetchone()[0] == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM document_change_audits WHERE reason_code='PROPOSAL_SUPERSEDED'"
            ).fetchone()[0]
            == 0
        )
        assert RequirementRepository(connection).get_for_document(1, 1)['discussion_state_json'][
            'pending_user_message_ids'
        ]
