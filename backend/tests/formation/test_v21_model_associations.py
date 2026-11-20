"""Ordinary actual AI returns record program-verified association reviews and lineage."""

from copy import deepcopy
import json

import pytest

from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.formation.relation_queries import read_lineage
from backend.tests.formation.test_v21_discuss_acceptance import (
    database,
    released,
    base_workspace,
    workspace,
    request,
    accepted,
)
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_content_maintenance import edit, change_first
from backend.tests.formation.test_v21_model_contracts import examples
from backend.tests.formation.test_v21_model_results import progress
from backend.tests.formation.test_v21_proposal_adjustment import run_round
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, output

__all__ = ['database', 'released', 'base_workspace', 'workspace']


@pytest.mark.parametrize('mode', ('MATCHED', 'UNVERIFIED', 'REASSOCIATED'))
def test_actual_review_keeps_original_or_creates_real_successor_with_exact_sources(
    workspace, monkeypatch, mode
):
    offline_gate(monkeypatch)
    doc = associated(workspace)
    if mode == 'REASSOCIATED':
        result, _ = edit(workspace, doc, change_first)
        assert result['code'] == 'DRAFT_COMPLETED', result
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, doc)
        before = dict(
            connection.execute(
                'SELECT * FROM formation_artifacts WHERE document_id=?', (doc,)
            ).fetchone()
        )
    body = request(
        workspace, document_id=doc, expected_discussion_version=root['discussion_version']
    )
    body['target']['discussion_step_ref'] = 's1'
    received = accepted(workspace, body)

    def returned(context):
        change = deepcopy(examples()[11])
        change.update(
            review_of='a1',
            source_refs=[context.input['current_request']['message_ref']],
            document_refs=[
                block['ref']
                for block in context.input['documents'][0]['blocks'][
                    : 1 if mode == 'UNVERIFIED' else 2
                ]
            ],
        )
        return output(context, progress_delta=progress(context, [change]))

    run_round(workspace, received['data']['guide_run_id'], Gateway(returned))
    with workspace[0].transaction() as connection:
        final = json.loads(
            connection.execute(
                'SELECT final_result_json FROM guide_runs WHERE id=?',
                (received['data']['guide_run_id'],),
            ).fetchone()[0]
        )
        assert final['effect_state'] == 'APPLIED', final
        review = dict(connection.execute('SELECT * FROM formation_artifact_reviews').fetchone())
        assert review['result'] == mode
        assert review['reviewed_artifact_ref'] == 'a1'
        assert review['assistant_message_id'] == final['assistant_message_id']
        assert json.loads(review['source_refs_json']) == [
            {'kind': 'MESSAGE', 'message_id': received['data']['user_message_id']}
        ]
        after = dict(
            connection.execute(
                "SELECT * FROM formation_artifacts WHERE document_id=? AND artifact_ref='a1'",
                (doc,),
            ).fetchone()
        )
        assert after == before
        count = connection.execute(
            'SELECT count(*) FROM formation_artifacts WHERE document_id=?', (doc,)
        ).fetchone()[0]
        assert count == (2 if mode == 'REASSOCIATED' else 1)
        assert review['replacement_artifact_ref'] == ('a2' if mode == 'REASSOCIATED' else None)
    lineage = read_lineage(workspace[0], 1, doc, 'a1', {}, catalog=workspace[2])
    assert lineage['code'] == 'READ_OK', lineage
    assert lineage['data']['value']['total'] == (2 if mode == 'REASSOCIATED' else 1)
