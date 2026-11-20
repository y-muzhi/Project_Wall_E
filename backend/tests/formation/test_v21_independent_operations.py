"""Actual staged adoption remains readable to independent revision and its explicit retry."""

import asyncio
import json
from uuid import uuid4
import pytest

from backend.app.guide.commands import create_guide_run, retry_guide_run, continue_guide_run
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
)
from backend.tests.formation.test_v21_model_publication import publish, write_group
from backend.tests.formation.test_v21_card_apply import answer, submit
from backend.tests.formation.test_v21_model_results import progress
from backend.tests.guide.test_v15_execution import Gateway, output, PROFILE
from backend.tests.guide.test_v15_counting import Counter

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def run(workspace, identity, gateway):
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


def accept_revision(workspace):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
        version = connection.execute(
            'SELECT content_version FROM requirement_documents WHERE id=1'
        ).fetchone()[0]
    result = create_guide_run(
        workspace[1],
        {
            'requirement_id': 1,
            'document_id': 1,
            'expected_discussion_version': root['discussion_version'],
            'operation': 'REVISE',
            'instruction': '明确更新原有正文',
            'target': {'kind': 'EXISTING', 'document_id': 1, 'expected_content_version': version},
            'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None},
            'source_refs': [],
            'proposal_ref': None,
            'acknowledge_source_changes': False,
            'idempotency_key': str(uuid4()),
        },
        catalog=workspace[2],
    )
    assert result['code'] == 'GUIDE_ACCEPTED', result
    return result


@pytest.mark.parametrize('bad_component', ['none', 'formation', 'proposal'])
def test_independent_revision_reads_real_card_sources_and_keeps_content_effect_independent(
    workspace, monkeypatch, bad_component
):
    message, _ = publish(workspace, monkeypatch, initial=True)
    assert submit(workspace, answer(workspace, message))['code'] == 'PROGRAM_PROCESSED'
    accepted = accept_revision(workspace)
    identity = accepted['data']['guide_run_id']
    with workspace[0].transaction() as connection:
        row = connection.execute('SELECT * FROM guide_runs WHERE id=?', (identity,)).fetchone()
        basis = json.loads(row['execution_basis_json'])
        assert 'formation_request' not in basis and basis['formation_selection'] is None
        assert (
            row['operation'] == 'REVISE'
            and row['context_template_key'] == 'formation_context_v21_1'
        )

    def revised(context):
        assert 'CARD_RESPONSE' in json.dumps(context.canonical)
        assert context.input['current_request']['formation_selection'] is None
        delta = None
        if bad_component == 'formation':
            delta = progress(context, [{'type': 'FINISH_STEP', 'step_ref': 's1'}])
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            document_result={
                'name': '需求',
                'document_kind': 'design',
                'markdown_content': '独立修订后的正文。\n',
                'change_summary': '明确更新',
            },
            progress_delta=delta,
            cards=write_group(context) if bad_component == 'proposal' else None,
        )

    outcome = run(workspace, identity, Gateway(revised))
    assert outcome['code'] == 'AI_FINISHED', outcome
    read = get_guide_run(workspace[0], identity, catalog=workspace[2])
    assert read['code'] == 'READ_OK', read
    assert read['data']['operation'] == 'REVISE' and 'accepted_target' not in read['data']
    with workspace[0].transaction() as connection:
        diagnostics = json.loads(
            connection.execute(
                'SELECT final_result_json FROM guide_runs WHERE id=?', (identity,)
            ).fetchone()[0]
        )
    assert read['data']['application_result'] == 'APPLIED', diagnostics
    if bad_component == 'formation':
        assert read['data']['progress_result'] == 'REJECTED', read
    with workspace[0].transaction() as connection:
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        if bad_component == 'proposal':
            assert (
                connection.execute('SELECT count(*) FROM formation_proposal_index').fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT structured_content_json FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT'",
                    (identity,),
                ).fetchone()[0]
                is None
            )
            assert diagnostics['validation_error'] is not None
        assert (
            current['content_version'] == 3
            and current['markdown_content'] == '独立修订后的正文。\n'
        )
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s1'").fetchone()[
                0
            ]
            == 'IN_PROGRESS'
        )
        root = RequirementRepository(connection).get_for_document(1, 1)
    continued = continue_guide_run(
        workspace[1],
        {
            'guide_run_id': identity,
            'expected_discussion_version': root['discussion_version'],
            'instruction': '继续核对新正文',
            'idempotency_key': str(uuid4()),
        },
        catalog=workspace[2],
    )
    assert continued['code'] == 'GUIDE_CONTINUED', continued
    assert continued['data']['accepted_target'] == {
        'discussion_step_ref': None,
        'discussion_branch_ref': None,
        'branch_intent': None,
        'branch_resume_basis': None,
    }


def test_independent_revision_retry_keeps_original_operation_and_original_user_message(
    workspace, monkeypatch
):
    message, _ = publish(workspace, monkeypatch, initial=True)
    assert submit(workspace, answer(workspace, message))['code'] == 'PROGRAM_PROCESSED'
    accepted = accept_revision(workspace)
    identity = accepted['data']['guide_run_id']
    failed = run(workspace, identity, Gateway(lambda context: None, failed=True))
    assert failed['code'] == 'AI_FAILED', failed
    retried = retry_guide_run(
        workspace[1],
        {'guide_run_id': identity, 'idempotency_key': str(uuid4())},
        catalog=workspace[2],
    )
    assert retried['code'] == 'GUIDE_RETRY_ACCEPTED', retried
    assert retried['data']['user_message_id'] == accepted['data']['user_message_id']
    assert 'accepted_target' not in retried['data']
    with workspace[0].transaction() as connection:
        actual = connection.execute(
            'SELECT * FROM guide_runs WHERE id=?', (retried['data']['guide_run_id'],)
        ).fetchone()
        assert actual['operation'] == 'REVISE' and actual['retry_of_guide_run_id'] == identity
        assert 'formation_request' not in json.loads(actual['execution_basis_json'])
