"""Withdraw revalidation uses original authority and cannot authorize later changed content."""

import asyncio
import json
from uuid import uuid4

from backend.app.formation.commands import update_path, update_proposal
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.documents.test_v15_editing import candidate, finish, save, start
from backend.tests.formation.test_v21_card_apply import answer, submit
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_discuss_acceptance import (
    base_workspace,
    database,
    released,
    workspace,
)
from backend.tests.formation.test_v21_model_publication import publish
from backend.tests.formation.test_v21_path_commands import request as path_request
from backend.tests.formation.test_v21_proposal_adjustment import adjust, old_value
from backend.tests.formation.test_v21_target_boundaries import all_facts
from backend.tests.guide.test_v15_counting import Counter
from backend.tests.guide.test_v15_execution import PROFILE, Gateway

__all__ = ['base_workspace', 'database', 'released', 'workspace']


def failed_adjustment(workspace, monkeypatch):
    message, original_gateway = publish(workspace, monkeypatch)
    original = old_value(workspace, message)
    accepted = adjust(workspace, message)
    gateway = Gateway(failed=True)
    result = asyncio.run(
        execute_guide_run(
            workspace[0],
            {'guide_run_id': accepted['data']['guide_run_id']},
            process_lock=workspace[1].process_lock,
            catalog=workspace[2],
            profile=PROFILE,
            gateway=gateway,
            counting_counter=Counter(['OK']),
        )
    )
    assert result['code'] == 'AI_FAILED' and result['details']['error_code'] == 'MODEL_ERROR'
    assert len(original_gateway.calls) == len(gateway.calls) == 1
    assert old_value(workspace, message).needs_revision
    return message, original


def withdraw_command(workspace, reference):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    return {
        'requirement_id': 1,
        'document_id': 1,
        'expected_discussion_version': root['discussion_version'],
        'discussion_command': {
            'type': 'FORMATION',
            'action': 'WITHDRAW_PROPOSAL_ADJUSTMENT',
            'proposal': reference,
        },
        'idempotency_key': str(uuid4()),
    }


def proof_rows(workspace):
    with workspace[0].transaction() as connection:
        return [
            json.loads(row[0])
            for row in connection.execute(
                'SELECT after_json FROM formation_event_changes '
                "WHERE entity_kind='PROPOSAL_CHECK' ORDER BY event_id"
            )
        ]


def test_failed_adjustment_related_change_refuses_withdraw_without_rebinding_or_any_effect(
    workspace, monkeypatch
):
    message, original = failed_adjustment(workspace, monkeypatch)
    changed = update_path(
        workspace[1],
        path_request(
            workspace, [{'type': 'SET_GOAL', 'text': '后来的明确新目标', 'source_refs': []}]
        ),
        catalog=workspace[2],
    )
    assert changed['code'] == 'UPDATED', changed
    command = withdraw_command(workspace, original.reference)
    before = all_facts(workspace)
    rejected = update_proposal(workspace[1], command, catalog=workspace[2])
    assert rejected['code'] == 'STATE_CONFLICT', rejected
    assert rejected['details']['reason'] == 'PROPOSAL_BASIS_CHANGED', rejected
    assert all_facts(workspace) == before
    current = old_value(workspace, message)
    assert current.needs_revision and current.binding == original.binding
    assert current.payload == original.payload and proof_rows(workspace) == []


def test_unrelated_f_allows_withdraw_but_old_success_replay_cannot_authorize_later_content(
    workspace, monkeypatch
):
    message, original = failed_adjustment(workspace, monkeypatch)
    changed = update_path(workspace[1], path_request(workspace, [add_step()]), catalog=workspace[2])
    assert changed['code'] == 'UPDATED', changed
    command = withdraw_command(workspace, original.reference)
    withdrawn = update_proposal(workspace[1], command, catalog=workspace[2])
    assert withdrawn['code'] == 'UPDATED', withdrawn
    proofs = proof_rows(workspace)
    assert len(proofs) == 1
    assert proofs[0]['publication_binding_digest'] == original.binding_digest
    assert proofs[0]['expected_semantic_digest'] == proofs[0]['observed_semantic_digest']
    draft = start(workspace, identity=1, version=1)
    assert draft['code'] == 'DRAFT_STARTED', draft
    prepared = candidate(
        workspace, draft['data']['manual_draft'], '# 已经明确写入的正文\n\n用户的新内容。\n'
    )
    saved = save(workspace, draft['data']['manual_draft'], prepared)
    assert saved['code'] == 'DRAFT_SAVED', saved
    completed = finish(workspace, saved['data'])
    assert completed['code'] == 'DRAFT_COMPLETED', completed
    before = all_facts(workspace)
    assert update_proposal(workspace[1], command, catalog=workspace[2]) == withdrawn
    assert all_facts(workspace) == before
    blocked = submit(workspace, answer(workspace, message))
    assert blocked['code'] == 'STATE_CONFLICT', blocked
    assert blocked['details']['reason'] == 'PROPOSAL_BASIS_CHANGED', blocked
    assert all_facts(workspace) == before
    assert proof_rows(workspace) == proofs
    current = old_value(workspace, message)
    assert not current.needs_revision and current.binding == original.binding
    assert current.payload == original.payload
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'"
            ).fetchone()[0]
            == 0
        )
