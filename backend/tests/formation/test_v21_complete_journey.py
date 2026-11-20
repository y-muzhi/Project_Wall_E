"""One complete V2.1 journey uses original C01/C07/C06, manual edits and immutable closures."""

import json
from copy import deepcopy

from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.formation.commands import complete_step, update_path, update_state
from backend.app.formation.relation_queries import read_lineage
from backend.app.messages.queries import list_messages
from backend.tests.documents.test_patch_validation import patch
from backend.tests.formation.test_v21_card_apply import answer, submit
from backend.tests.formation.test_v21_completion_commands import request as complete_request
from backend.tests.formation.test_v21_content_maintenance import edit
from backend.tests.formation.test_v21_contracts import add_step
from backend.tests.formation.test_v21_discuss_acceptance import (
    accepted,
    base_workspace,
    database,
    released,
    request,
    workspace,
)
from backend.tests.formation.test_v21_model_contracts import examples
from backend.tests.formation.test_v21_model_publication import publish, write_group
from backend.tests.formation.test_v21_model_results import progress
from backend.tests.formation.test_v21_path_commands import request as path_request
from backend.tests.formation.test_v21_proposal_adjustment import run_round
from backend.tests.formation.test_v21_state_commands import payload
from backend.tests.guide.test_v15_execution import Gateway, output

__all__ = ['base_workspace', 'database', 'released', 'workspace']


def frozen_closure(workspace, event):
    with workspace[0].transaction() as connection:
        return {
            table: [
                tuple(row)
                for row in connection.execute(
                    'SELECT * FROM ' + table + ' WHERE event_id=?', (event,)
                )
            ]
            for table in (
                'formation_closures',
                'formation_closure_items',
                'formation_closure_evidence',
            )
        }


def test_complete_journey_preserves_closed_history_and_accepts_valid_late_write(
    workspace, monkeypatch
):
    original, gateway = publish(workspace, monkeypatch, initial=True)
    # Unrelated append changes D/F, but cannot expire an exact still-valid write.
    added = update_path(workspace[1], path_request(workspace, [add_step()]), catalog=workspace[2])
    assert added['code'] == 'UPDATED', added
    adopted = submit(workspace, answer(workspace, original))
    assert adopted['code'] == 'PROGRAM_PROCESSED', adopted
    finished = complete_step(
        workspace[1],
        complete_request(
            workspace,
            expected_content_version=2,
            next_step_ref='s2',
            result_dispositions=[
                {
                    'result_ref': 's1.o1',
                    'status': 'LANDED',
                    'artifact_refs': ['a1'],
                    'source_refs': [],
                }
            ],
        ),
        catalog=workspace[2],
    )
    assert finished['code'] == 'UPDATED', finished
    event = finished['data']['event_ids'][0]
    closure = frozen_closure(workspace, event)
    assert closure['formation_closures'] and closure['formation_closure_items']
    edited, _ = edit(
        workspace,
        1,
        lambda blocks, ids: (
            '\n\n'.join(
                [
                    blocks[0].markdown.replace('原文', '已明确范围', 1),
                    *[block.markdown for block in blocks[1:]],
                ]
            ),
            ids,
        ),
    )
    assert edited['code'] == 'DRAFT_COMPLETED', edited
    assert frozen_closure(workspace, event) == closure
    discussion = request(workspace)
    discussion['target']['discussion_step_ref'] = 's1'
    reviewed = accepted(workspace, discussion)

    def reassociated(context):
        change = deepcopy(examples()[11])
        change.update(
            review_of='a1',
            source_refs=[context.input['current_request']['message_ref']],
            document_refs=[block['ref'] for block in context.input['documents'][0]['blocks']],
        )
        return output(context, progress_delta=progress(context, [change]))

    second_gateway = Gateway(reassociated)
    assert (
        run_round(workspace, reviewed['data']['guide_run_id'], second_gateway)['code']
        == 'AI_FINISHED'
    )
    lineage = read_lineage(workspace[0], 1, 1, 'a1', {}, catalog=workspace[2])
    assert lineage['code'] == 'READ_OK', lineage
    assert [row['artifact_ref'] for row in lineage['data']['value']['items']] == ['a1', 'a2']
    assert frozen_closure(workspace, event) == closure
    with workspace[0].transaction() as connection:
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        assert current['content_version'] == 3
        snapshot = validate_snapshot(
            current['markdown_content'],
            json.loads(current['block_state_json']),
            DocumentSources(connection, 1, workspace[2], document_id=1),
        )
        identity = list(snapshot.by_id)[-1]
        precise = patch(snapshot, identity, proposed='明确补充已结束步骤的正文。\n')
        assert (
            connection.execute("SELECT status FROM formation_steps WHERE step_ref='s1'").fetchone()[
                0
            ]
            == 'COMPLETED'
        )
    next_request = request(workspace)
    next_request['target']['discussion_step_ref'] = 's1'
    next_accepted = accepted(workspace, next_request)

    def staged(context):
        cards = write_group(context)
        cards['action_payload'].update(
            write_mode='PATCH_EXISTING',
            markdown_content=None,
            patches=[precise],
            change_summary='明确写入已结束步骤',
        )
        return output(context, cards=cards)

    third_gateway = Gateway(staged)
    assert (
        run_round(workspace, next_accepted['data']['guide_run_id'], third_gateway)['code']
        == 'AI_FINISHED'
    )
    messages = list_messages(
        workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2]
    )
    assert messages['code'] == 'READ_OK', messages
    latest = messages['data']['items'][-1]
    assert latest['card_state'] == 'AVAILABLE', latest
    # Pure focus movement must not invalidate the already counted exact proposal.
    assert (
        update_state(workspace[1], payload(workspace, 'SWITCH_STEP', step_ref='s2'))['code']
        == 'UPDATED'
    )
    last_command = answer(workspace, latest)
    late_write = submit(workspace, last_command)
    assert late_write['code'] == 'PROGRAM_PROCESSED', late_write
    assert submit(workspace, last_command) == late_write
    assert frozen_closure(workspace, event) == closure
    completed = complete_step(
        workspace[1],
        complete_request(workspace, step_ref='s2', expected_content_version=4),
        catalog=workspace[2],
    )
    assert completed['code'] == 'UPDATED', completed
    assert frozen_closure(workspace, event) == closure
    with workspace[0].transaction() as connection:
        assert [
            row[0]
            for row in connection.execute('SELECT status FROM formation_steps ORDER BY step_ref')
        ] == ['COMPLETED', 'COMPLETED']
        current = connection.execute('SELECT * FROM requirement_documents WHERE id=1').fetchone()
        assert current['content_version'] == 4 and current['confirmed_revision_id'] is None
        assert '明确补充已结束步骤的正文' in current['markdown_content']
        assert (
            connection.execute('SELECT status FROM requirements WHERE id=1').fetchone()[0]
            == 'PLANNING'
        )
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 3
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 3
        assert connection.execute('SELECT count(*) FROM formation_closures').fetchone()[0] == 2
    assert len(gateway.calls) == len(second_gateway.calls) == len(third_gateway.calls) == 1
