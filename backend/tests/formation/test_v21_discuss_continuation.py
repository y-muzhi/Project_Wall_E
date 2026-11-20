"""Original continuation/retry adapters preserve the formation protocol and actual inputs."""

import json
from uuid import uuid4
import pytest

from backend.app.guide.commands import continue_guide_run, retry_guide_run
from backend.app.guide.collaboration_context import read_canonical, compile_context
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_model_publication import publish
from backend.tests.formation.test_v21_card_apply import answer, submit
from backend.tests.formation.test_v21_proposal_adjustment import run_round
from backend.tests.guide.test_v15_execution import Gateway, execute, output
from backend.tests.guide.test_v15_counting import offline_gate

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def test_continue_after_real_card_adoption_reads_new_provenance_and_creates_only_new_user_input(
    workspace, monkeypatch
):
    message, _ = publish(workspace, monkeypatch, initial=True)
    adopted = submit(workspace, answer(workspace, message))
    assert adopted['code'] == 'PROGRAM_PROCESSED', adopted
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    body = {
        'guide_run_id': 1,
        'expected_discussion_version': root['discussion_version'],
        'instruction': '继续核对刚采用的正文',
        'idempotency_key': str(uuid4()),
    }
    from backend.app.formation.discuss_continuation import derive_discussion

    with workspace[0].transaction() as connection:
        previous = connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone()
        derived = derive_discussion(
            connection,
            previous,
            root,
            body['instruction'],
            body['idempotency_key'],
            body['expected_discussion_version'],
        )
        assert derived.operation == 'DISCUSS'
    from backend.app.guide import commands as guide_commands

    original_accept = guide_commands._accept_collaboration
    failures = []

    def observed(*args, **kwargs):
        try:
            return original_accept(*args, **kwargs)
        except Exception as error:
            import traceback

            failures.append(traceback.format_exc())
            raise

    monkeypatch.setattr(guide_commands, '_accept_collaboration', observed)
    result = continue_guide_run(workspace[1], body, catalog=workspace[2])
    assert result['code'] == 'GUIDE_CONTINUED', (result, failures)
    assert 'accepted_target' in result['data']
    assert continue_guide_run(workspace[1], body, catalog=workspace[2]) == result
    with workspace[0].transaction() as connection:
        canonical = read_canonical(connection, result['data']['guide_run_id'], workspace[2])
        context = compile_context(canonical, workspace[2])
        assert context.input['documents'][0]['blocks']
        assert 'CARD_RESPONSE' in json.dumps(canonical)
        assert canonical['formation']['basis']['content_version'] == 2
    run_round(workspace, result['data']['guide_run_id'], Gateway(output))


@pytest.mark.parametrize('returned_raw', (False, True))
def test_explicit_retry_reuses_failed_actual_user_message_and_keeps_new_frozen_protocol(
    workspace, monkeypatch, returned_raw
):
    offline_gate(monkeypatch)
    first = accepted(workspace, request(workspace))
    failed = execute(
        workspace, Gateway(output if returned_raw else lambda context: None, failed=True)
    )
    assert failed['code'] == 'AI_FAILED', failed
    body = {'guide_run_id': first['data']['guide_run_id'], 'idempotency_key': str(uuid4())}
    with workspace[0].transaction() as connection:
        count_before = connection.execute(
            "SELECT count(*) FROM conversation_messages WHERE role='USER' AND message_type='TEXT'"
        ).fetchone()[0]
    retried = retry_guide_run(workspace[1], body, catalog=workspace[2])
    assert retried['code'] == 'GUIDE_RETRY_ACCEPTED', retried
    assert retried['data']['user_message_id'] == first['data']['user_message_id']
    assert retried['data']['accepted_target'] == first['data']['accepted_target']
    assert retry_guide_run(workspace[1], body, catalog=workspace[2]) == retried
    with workspace[0].transaction() as connection:
        rows = connection.execute('SELECT * FROM guide_runs ORDER BY id').fetchall()
        assert len(rows) == 2 and rows[0]['status'] == 'FAILED'
        basis = json.loads(rows[1]['execution_basis_json'])
        assert 'formation' in basis and 'formation_request' in basis
        assert rows[1]['context_template_key'] == 'formation_context_v21_1'
        assert (
            connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE role='USER' AND message_type='TEXT'"
            ).fetchone()[0]
            == count_before
        )
    run_round(workspace, retried['data']['guide_run_id'], Gateway(output))
