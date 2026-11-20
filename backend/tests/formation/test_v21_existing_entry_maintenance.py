"""Existing fact-card and suggestion commits maintain only actual affected formation ranges."""

from uuid import uuid4

import pytest

from backend.app.documents.markdown import parse_markdown
from backend.app.messages.queries import list_messages
from backend.app.suggestions.commands import complete_batch, decide_suggestion
from backend.app.suggestions.queries import get_batch
from backend.tests.formation.test_v21_content_maintenance import state
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_cards import body, group, submit
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, execute, output

__all__ = ['database', 'released', 'workspace']


@pytest.mark.parametrize('entry', ['FACT_CONFIRMATION', 'SUGGESTION_BATCH'])
@pytest.mark.parametrize('related', [True, False])
def test_actual_existing_commit_entry_has_precise_maintenance_and_original_replay(
    workspace, monkeypatch, entry, related
):
    offline_gate(monkeypatch)
    doc = associated(workspace)
    before = state(workspace, doc)
    blocks = parse_markdown(before[4]['markdown_content']).blocks
    import json

    ids = [row['block_id'] for row in json.loads(before[4]['block_state_json'])['blocks']]
    index = 0 if related else len(blocks) - 1
    assert index == 0 or index >= 2
    patch = {
        'title': '核实范围',
        'explanation': '仅修改所选区块',
        'impact': None,
        'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': ids[index]},
        'selector_json': None,
        'original_content': blocks[index].markdown,
        'proposed_markdown': blocks[index].markdown.rstrip() + ' 新增内容',
        'proposed_data_json': None,
    }
    result = accept(
        workspace,
        operation='DISCUSS' if entry == 'FACT_CONFIRMATION' else 'PROPOSE_CHANGES',
        document_id=doc,
        expected_discussion_version=before[0]['discussion_version'],
        target={'kind': 'EXISTING', 'document_id': doc, 'expected_content_version': 1},
        scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': ids[index]}},
    )
    assert result['code'] == 'GUIDE_ACCEPTED', result

    def returned(context):
        if entry == 'FACT_CONFIRMATION':
            action = {
                'confirmed_fact_patches': [
                    {
                        'patch': patch,
                        'evidence': [
                            {
                                'message_id': context.input['current_request']['message_id'],
                                'quoted_text': '用户原话',
                            }
                        ],
                    }
                ]
            }
            return output(context, cards=group('FACT_CONFIRMATION', action))
        return output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch])

    gateway = Gateway(returned)
    assert execute(workspace, gateway)['code'] == 'AI_FINISHED'
    assert len(gateway.calls) == 1
    prior_commit = state(workspace, doc)
    assert prior_commit[2] == before[2] and prior_commit[4]['content_version'] == 1
    if entry == 'FACT_CONFIRMATION':
        messages = list_messages(
            workspace[0], {'requirement_id': 1, 'document_id': doc}, catalog=workspace[2]
        )
        assert messages['code'] == 'READ_OK', messages
        message = messages['data']['items'][-1]
        command = body(message, 'confirm')
        result = submit(workspace, command)
        assert result['code'] == 'PROGRAM_PROCESSED', result

        def replay():
            return submit(workspace, command)
    else:
        batch = get_batch(workspace[0], 1, catalog=workspace[2])
        assert batch['code'] == 'READ_OK', batch
        items = batch['data']['suggestions']
        assert len(items) == 1
        decided = decide_suggestion(
            workspace[1],
            {
                'suggestion_id': items[0]['id'],
                'decision': 'ACCEPTED',
                'idempotency_key': str(uuid4()),
            },
            catalog=workspace[2],
        )
        assert decided['code'] == 'SUGGESTION_DECIDED', decided
        command = {'batch_id': 1, 'expected_content_version': 1, 'idempotency_key': str(uuid4())}
        result = complete_batch(workspace[1], command, catalog=workspace[2])
        assert result['code'] == 'BATCH_APPLIED', result

        def replay():
            return complete_batch(workspace[1], command, catalog=workspace[2])

    after = state(workspace, doc)
    assert after[4]['content_version'] == 2
    assert after[1]['version'] == before[1]['version'] + int(related)
    if related:
        assert after[2]['freshness'] == 'NEEDS_REVIEW' and after[2]['review_reason'] == 'CHANGED'
        assert after[2]['origin_revision_id'] == before[2]['origin_revision_id']
    else:
        assert after[2] == before[2] and after[3] == before[3]
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1
        events = [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM document_change_audits WHERE reason_code='ARTIFACT_CHECKED'"
            )
        ]
        assert len(events) == int(related)
    assert replay() == result
    assert state(workspace, doc) == after
