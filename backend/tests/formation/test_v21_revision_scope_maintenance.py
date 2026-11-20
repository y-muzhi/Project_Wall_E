"""Frozen REVISE scopes keep unrelated formation ranges intact through the actual C07 commit."""

import json

import pytest

from backend.app.documents.markdown import parse_markdown
from backend.tests.formation.test_v21_content_maintenance import state
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import Gateway, execute, output

__all__ = ['database', 'released', 'workspace']


@pytest.mark.parametrize('scope', ['DOCUMENT', 'BLOCK'])
@pytest.mark.parametrize('related', [True, False])
def test_real_revision_scope_maintains_only_affected_artifacts(
    workspace, monkeypatch, scope, related
):
    offline_gate(monkeypatch)
    doc = associated(workspace)
    before = state(workspace, doc)
    blocks = parse_markdown(before[4]['markdown_content']).blocks
    ids = [row['block_id'] for row in json.loads(before[4]['block_state_json'])['blocks']]
    index = 0 if related else len(blocks) - 1
    desired = [block.markdown for block in blocks]
    desired[index] = desired[index].rstrip() + ' 新增范围说明'
    target = {'kind': 'EXISTING', 'document_id': doc, 'expected_content_version': 1}
    accepted = accept(
        workspace,
        document_id=doc,
        expected_discussion_version=before[0]['discussion_version'],
        operation='REVISE',
        target=target,
        scope={
            'scope_type': scope,
            'scope_ref': None if scope == 'DOCUMENT' else {'block_id': ids[index]},
        },
    )
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted

    def returned(context):
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            document_result={
                'name': before[4]['name'],
                'document_kind': 'brief',
                'markdown_content': '\n\n'.join(desired) if scope == 'DOCUMENT' else desired[index],
                'change_summary': '只修改目标范围',
            },
        )

    gateway = Gateway(returned)
    result = execute(workspace, gateway)
    assert result['code'] == 'AI_FINISHED', result
    assert len(gateway.calls) == 1
    after = state(workspace, doc)
    assert after[4]['content_version'] == 2
    assert after[1]['version'] == before[1]['version'] + int(related)
    if related:
        assert after[2]['freshness'] == 'NEEDS_REVIEW'
        assert after[2]['origin_revision_id'] == before[2]['origin_revision_id']
    else:
        assert after[2] == before[2] and after[3] == before[3]
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM document_change_audits WHERE reason_code='ARTIFACT_CHECKED'"
        ).fetchone()[0] == int(related)
