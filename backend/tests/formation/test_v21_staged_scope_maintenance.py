"""Actual staged patch adoption and shared maintenance agree on affected original artifacts."""

import json
from uuid import uuid4

import pytest

from backend.app.documents.markdown import parse_markdown
from backend.app.guide.commands import submit_card_responses
from backend.app.messages.queries import list_messages
from backend.tests.formation.test_v21_content_maintenance import state
from backend.tests.formation.test_v21_discuss_acceptance import (
    accepted,
    base_workspace,
    database,
    released,
    request,
    workspace,
)
from backend.tests.formation.test_v21_model_publication import write_group
from backend.tests.formation.test_v21_proposal_adjustment import run_round
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, output

__all__ = ['base_workspace', 'database', 'released', 'workspace']


@pytest.mark.parametrize('related', [True, False])
def test_real_staged_patch_rechecks_only_affected_original_artifact(
    workspace, monkeypatch, related
):
    offline_gate(monkeypatch)
    doc = associated(workspace)
    before = state(workspace, doc)
    blocks = parse_markdown(before[4]['markdown_content']).blocks
    ids = [row['block_id'] for row in json.loads(before[4]['block_state_json'])['blocks']]
    index = 0 if related else len(blocks) - 1
    patch = {
        'title': '精确替换',
        'explanation': '仅目标区块',
        'impact': None,
        'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': ids[index]},
        'selector_json': None,
        'original_content': blocks[index].markdown,
        'proposed_markdown': blocks[index].markdown.rstrip() + ' 精确补充',
        'proposed_data_json': None,
    }
    body = request(workspace)
    body.update(document_id=doc, expected_discussion_version=before[0]['discussion_version'])
    body['target']['discussion_step_ref'] = 's1'
    initial = accepted(workspace, body)

    def returned(context):
        cards = write_group(context)
        cards['action_payload'].update(
            write_mode='PATCH_EXISTING',
            markdown_content=None,
            patches=[patch],
            scope={
                'scope_type': 'BLOCK',
                'scope_ref': {'block_id': ids[index]},
            },
        )
        return output(context, cards=cards)

    outcome = run_round(workspace, initial['data']['guide_run_id'], Gateway(returned))
    assert outcome['code'] == 'AI_FINISHED'
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': doc}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    proposal = messages['data']['items'][-1]
    assert proposal['card_state'] == 'AVAILABLE', proposal
    before_adopt = state(workspace, doc)
    command = {
        'message_id': proposal['id'],
        'schema_version': 1,
        'expected_discussion_version': before_adopt[0]['discussion_version'],
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
    result = submit_card_responses(workspace[1], command, catalog=workspace[2])
    assert result['code'] == 'PROGRAM_PROCESSED', result
    after = state(workspace, doc)
    assert after[4]['content_version'] == 2
    if related:
        assert after[2]['freshness'] == 'NEEDS_REVIEW'
    else:
        assert after[2] == before[2] and after[3] == before[3]
    assert after[2]['origin_revision_id'] == before[2]['origin_revision_id']
    assert submit_card_responses(workspace[1], command, catalog=workspace[2]) == result
    assert state(workspace, doc) == after
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1
