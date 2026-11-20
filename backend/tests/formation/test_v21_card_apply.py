"""Publish through actual audited execution, then adopt through original C06 without Chat."""

from copy import deepcopy
import json
from uuid import uuid4
import pytest

from backend.app.guide.commands import submit_card_responses
from backend.app.messages.queries import list_messages
from backend.app.documents.queries import get_current_document
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.formation.card_source import card_source
from backend.app.formation.proposal_binding import digest
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
)
from backend.tests.formation.test_v21_model_publication import publish
from backend.tests.formation.test_v21_path_commands import snapshot

__all__ = ['database', 'released', 'base_workspace', 'workspace']


def answer(workspace, message):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    return {
        'message_id': message['id'],
        'schema_version': 1,
        'expected_discussion_version': root['discussion_version'],
        'responses': [
            {
                'card_key': 'c1',
                'selected_option_keys': ['apply'],
                'custom_answer': None,
                'skipped': False,
            }
        ],
        'execution_selection': None,
        'idempotency_key': str(uuid4()),
    }


def submit(workspace, body):
    return submit_card_responses(workspace[1], body, catalog=workspace[2])


def test_exact_empty_write_records_real_response_block_revision_audit_and_artifact(
    workspace, monkeypatch
):
    message, gateway = publish(workspace, monkeypatch, initial=True)
    before = deepcopy(message['structured_content']['action_payload'])
    body = answer(workspace, message)
    result = submit(workspace, body)
    assert result['code'] == 'PROGRAM_PROCESSED', result
    data = result['data']
    assert data['schema'] == 'formation_program_receipt_v21_1'
    assert data['operation'] == 'STAGED_WRITE' and data['content_version'] == 2
    assert data['discussion_version'] == 4 and data['formation_version'] == 2
    assert (
        data['effects']['content_changed'] and data['effects']['proposal_disposition'] == 'APPLIED'
    )
    assert submit(workspace, body) == result
    assert len(gateway.calls) == 1
    with workspace[0].transaction() as connection:
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        assert current['markdown_content'] == before['markdown_content']
        state = json.loads(current['block_state_json'])
        assert state['blocks']
        assert all(
            row['created_source_type'] == 'CARD_RESPONSE' and row['created_by_type'] == 'USER'
            for row in state['blocks']
        )
        assert all(row['created_source_id'] == data['user_message_id'] for row in state['blocks'])
        descriptor, payload = card_source(connection, 1, 1, data['user_message_id'], workspace[2])
        assert (
            descriptor['conversation_message_id'] == message['id']
            and descriptor['card_key'] == 'c1'
        )
        assert payload == before
        audit = connection.execute(
            "SELECT * FROM document_change_audits WHERE source_type='CARD_RESPONSE'"
        ).fetchone()
        assert (
            audit['source_id'] == data['user_message_id']
            and audit['revision_id'] == data['effects']['revision_id']
        )
        assert json.loads(audit['payload_json'])['card_response_source'] == descriptor
        assert connection.execute('SELECT count(*) FROM formation_artifacts').fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1
        indexed = connection.execute('SELECT * FROM formation_proposal_index').fetchone()
        assert indexed['disposition'] == 'APPLIED' and indexed['payload_digest'] == digest(before)
        assert (
            json.loads(
                connection.execute(
                    'SELECT structured_content_json FROM conversation_messages WHERE id=?',
                    (message['id'],),
                ).fetchone()[0]
            )['action_payload']
            == before
        )
        refs = json.loads(
            connection.execute(
                'SELECT source_refs_json FROM revisions WHERE id=?',
                (data['effects']['revision_id'],),
            ).fetchone()[0]
        )
        assert {
            'kind': 'CARD_ANSWER',
            'message_id': data['user_message_id'],
            'card_key': 'c1',
        } in refs
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    assert messages['data']['items'][-1]['program_receipt'] == data
    assert (
        next(row for row in messages['data']['items'] if row['id'] == message['id'])['card_state']
        == 'ANSWERED'
    )


def test_exact_path_adoption_allocates_only_now_and_preserves_original_symbols(
    workspace, monkeypatch
):
    message, _ = publish(workspace, monkeypatch, purpose='FORMATION_PATH_CHANGE')
    original = deepcopy(message['structured_content']['action_payload'])
    body = answer(workspace, message)
    result = submit(workspace, body)
    assert result['code'] == 'PROGRAM_PROCESSED', result
    data = result['data']
    assert data['operation'] == 'FORMATION_PATH_CHANGE' and data['content_version'] == 1
    assert data['reference_map'] == [
        {'temp_ref': 'new_step_1', 'resolved_ref': 's2'},
        {'temp_ref': 'new_result_1', 'resolved_ref': 's2.o1'},
    ]
    assert data['formation_version'] == 4 and data['effects']['proposal_disposition'] == 'APPLIED'
    assert submit(workspace, body) == result
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM formation_steps').fetchone()[0] == 2
        assert connection.execute('SELECT next_step_no FROM formation_heads').fetchone()[0] == 3
        stored = json.loads(
            connection.execute(
                'SELECT structured_content_json FROM conversation_messages WHERE id=?',
                (message['id'],),
            ).fetchone()[0]
        )
        assert stored['action_payload'] == original
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1


def test_failed_artifact_storage_rolls_back_answer_content_versions_and_adoption_then_retry(
    workspace, monkeypatch
):
    message, _ = publish(workspace, monkeypatch, initial=True)
    body = answer(workspace, message)
    before = snapshot(workspace[0])
    from backend.app.formation import artifact_links

    real = artifact_links.create_links

    def fail(*args, **kwargs):
        raise RuntimeError('isolated storage fault after content commit before association')

    monkeypatch.setattr(artifact_links, 'create_links', fail)
    result = submit(workspace, body)
    assert result['code'] == 'INTERNAL_ERROR', result
    assert snapshot(workspace[0]) == before
    monkeypatch.setattr(artifact_links, 'create_links', real)
    result = submit(workspace, body)
    assert result['code'] == 'PROGRAM_PROCESSED', result


def test_client_payload_or_unbound_snapshot_cannot_replace_original_adoption(
    workspace, monkeypatch
):
    message, _ = publish(workspace, monkeypatch)
    body = answer(workspace, message)
    before = snapshot(workspace[0])
    body['action_payload'] = {'markdown_content': '替换正文'}
    assert submit(workspace, body)['code'] == 'INVALID_INPUT'
    assert snapshot(workspace[0]) == before
    del body['action_payload']
    body['responses'][0]['selected_option_keys'] = ['other']
    result = submit(workspace, body)
    assert result['code'] == 'INVALID_INPUT', result
    assert snapshot(workspace[0]) == before


@pytest.mark.parametrize('same_content', [False, True])
def test_existing_patch_adopts_actual_payload_and_same_text_keeps_revision(
    workspace, monkeypatch, same_content
):
    from backend.app.documents.snapshot import validate_snapshot
    from backend.app.documents.sources import DocumentSources
    from backend.tests.documents.test_patch_validation import patch
    from backend.tests.formation.test_v21_discuss_acceptance import request, accepted
    from backend.tests.formation.test_v21_model_publication import write_group
    from backend.tests.guide.test_v15_execution import Gateway, output

    initial, _ = publish(workspace, monkeypatch, initial=True)
    adopted = submit(workspace, answer(workspace, initial))
    assert adopted['code'] == 'PROGRAM_PROCESSED', adopted
    with workspace[0].transaction() as connection:
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        original = validate_snapshot(
            current['markdown_content'],
            json.loads(current['block_state_json']),
            DocumentSources(connection, 1, workspace[2], document_id=1),
        )
        identity = list(original.by_id)[-1]
        original_text = original.by_id[identity][0].markdown
        desired = original_text if same_content else '精确修改后的正文。\n'
        exact_patch = patch(original, identity, proposed=desired)
        previous_version = current['content_version']
        previous_revision_count = connection.execute(
            'SELECT count(*) FROM revisions WHERE document_id=1'
        ).fetchone()[0]
    body = request(workspace)
    body['target']['discussion_step_ref'] = 's1'
    accepted_result = accepted(workspace, body)

    def returned(context):
        group = write_group(context)
        group['action_payload'].update(
            write_mode='PATCH_EXISTING',
            markdown_content=None,
            patches=[exact_patch],
            change_summary='精确替换原有区块',
        )
        return output(context, cards=group)

    gateway = Gateway(returned)
    from backend.tests.formation.test_v21_proposal_adjustment import run_round

    finished = run_round(workspace, accepted_result['data']['guide_run_id'], gateway)
    assert finished['code'] == 'AI_FINISHED', finished
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    proposal = messages['data']['items'][-1]
    assert proposal['card_state'] == 'AVAILABLE', proposal
    assert proposal['structured_content']['action_payload']['patches'] == [exact_patch]
    command = answer(workspace, proposal)
    result = submit(workspace, command)
    assert result['code'] == 'PROGRAM_PROCESSED', result
    receipt = result['data']
    assert receipt['effects']['content_changed'] is not same_content
    assert receipt['content_version'] == previous_version + int(not same_content)
    assert submit(workspace, command) == result
    assert len(gateway.calls) == 1
    with workspace[0].transaction() as connection:
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        saved = validate_snapshot(
            current['markdown_content'],
            json.loads(current['block_state_json']),
            DocumentSources(connection, 1, workspace[2], document_id=1),
        )
        assert saved.by_id[identity][0].markdown == desired
        assert list(saved.by_id) == list(original.by_id)
        assert saved.next_block_id == original.next_block_id
        assert connection.execute('SELECT count(*) FROM revisions WHERE document_id=1').fetchone()[
            0
        ] == previous_revision_count + int(not same_content)
        assert connection.execute('SELECT count(*) FROM formation_artifacts').fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT count(*) FROM formation_proposal_index WHERE disposition='APPLIED'"
            ).fetchone()[0]
            == 2
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 2
        if not same_content:
            provenance = next(row for row in saved.state['blocks'] if row['block_id'] == identity)
            assert provenance['last_modified_source_type'] == 'CARD_RESPONSE'
            assert provenance['last_modified_source_id'] == receipt['user_message_id']
