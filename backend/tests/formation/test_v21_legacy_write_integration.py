"""Actual accepted/audited legacy REVISE joins formation maintenance without another call."""

import json
import pytest

from backend.app.formation.history_queries import read_history
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_schema import database, released, workspace
from backend.tests.formation.test_v21_relation_reads import associated
from backend.tests.formation.test_v21_content_maintenance import state
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_execution import execute, Gateway, output, delta
from backend.tests.guide.test_v15_counting import Counter, offline_gate
from backend.app.guide.queries import get_guide_run

__all__ = ['database', 'released', 'workspace']


@pytest.mark.parametrize('with_progress', (False, True))
def test_real_existing_write_path_has_one_count_one_offline_gateway_and_one_d_f_commit(
    workspace, monkeypatch, with_progress
):
    offline_gate(monkeypatch)
    doc = associated(workspace)
    before = state(workspace, doc)
    current = before[4]
    result = accept(
        workspace,
        document_id=doc,
        operation='REVISE',
        expected_discussion_version=before[0]['discussion_version'],
        target={'kind': 'EXISTING', 'document_id': doc, 'expected_content_version': 1},
        scope={'scope_type': 'DOCUMENT', 'scope_ref': None},
    )
    assert result['code'] == 'GUIDE_ACCEPTED', result

    def returned(context):
        return output(
            context,
            response_type='DOCUMENT_RESULT',
            document_result={
                'name': current['name'],
                'document_kind': 'brief',
                'markdown_content': current['markdown_content'].replace('# 1. ', '# 1. 明确', 1),
                'change_summary': '修订实际目标正文',
            },
            progress_delta=delta(context) if with_progress else None,
        )

    gateway, counter = Gateway(returned), Counter(['OK'])
    result = execute(workspace, gateway, counter)
    assert result['code'] == 'AI_FINISHED', result
    assert len(gateway.calls) == len(counter.calls) == 1
    after = state(workspace, doc)
    assert after[0]['discussion_version'] == before[0]['discussion_version'] + 2
    assert after[1]['version'] == before[1]['version'] + 1
    assert after[4]['content_version'] == 2
    assert after[2]['freshness'] == 'NEEDS_REVIEW'
    run = get_guide_run(workspace[0], result['data']['guide_run_id'])
    assert run['code'] == 'READ_OK', run
    assert run['data']['application_result'] == 'APPLIED'
    assert run['data']['progress_result'] == ('APPLIED' if with_progress else 'NOT_REQUESTED')
    assert run['data']['status'] == 'COMPLETED'
    with workspace[0].transaction() as connection:
        actual = RequirementRepository(connection).get_for_document(1, doc)
        assert actual['document_work_state'] == 'IDLE'
        use = connection.execute('SELECT * FROM llm_uses').fetchone()
        assert use['call_status'] == use['validation_status'] == 'SUCCEEDED'
        snapshot = json.loads(use['request_snapshot_json'])
        assert snapshot['context_basis']['canonical']['authorization']['target_document_id'] == doc
        assert connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1
    history = read_history(workspace[0], 1, doc, 'events', {})
    assert history['code'] == 'READ_OK', history
    event = history['data']['value']['items'][0]
    assert event['actor'] == 'PROGRAM'
    assert event['version_before']['discussion_version'] == before[0]['discussion_version'] + 1
    assert event['version_after']['discussion_version'] == after[0]['discussion_version']
