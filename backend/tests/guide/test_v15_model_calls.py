"""Saved collaboration request projections; no reassembly or external calls."""
import json
import socket

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import execute, Gateway, output
from backend.app.guide.model_calls import get_model_call, list_model_calls
from backend.app.guide.api import guide_router
from backend.app.shared.http_boundary import HttpRuntime


def test_eight_saved_wire_sections_actual_count_measurements_and_read_only_http(workspace, monkeypatch):
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    assert execute(workspace, Gateway())['code'] == 'AI_FINISHED'
    with workspace[0].transaction() as connection:
        saved = json.loads(connection.execute('SELECT request_snapshot_json FROM llm_uses WHERE id=1').fetchone()[0])
    def forbidden(*args, **kwargs): raise AssertionError('GET must not connect or compile/count')
    original_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr('backend.app.guide.collaboration_context.compile_context', forbidden)
    before = counts(workspace[0]);result = get_model_call(workspace[0], 1);assert result['code'] == 'READ_OK', result
    detail = result['data'];wire = json.loads(saved['request']['messages'][1]['content'])
    assert detail['context_strategy'] == 'collaboration_context_v1'
    assert detail['operation'] == 'DISCUSS'
    assert [item['key'] for item in detail['sections']] == ['system', *(key for key in wire if key != 'schema_version')]
    assert detail['sections'][0]['content'] == saved['request']['messages'][0]['content']
    for item in detail['sections'][1:]:
        assert json.loads(item['content']) == wire[item['key']] and item['characters'] == len(item['content'])
    assert detail['sections'][1]['item_count'] == 0 and detail['sections'][1]['content'] == 'null'
    assert json.loads(detail['raw_request_json']) == saved['request']
    assert 'authorization' not in wire and 'context_basis' not in json.loads(detail['raw_request_json'])
    assert detail['preflight']['counts'] == saved['counting']['count_attempts'][-1]['measurement']['counts']
    assert len(detail['preflight']['counts']) == 8 and detail['preflight']['budget']['input_tokens'] == 131072
    assert detail['selection_summary']['selected_materials'] == saved['context_basis']['selected']
    assert detail['call']['user_message_id'] == wire['current_request']['message_id']
    listing = list_model_calls(workspace[0], 1);assert listing['code'] == 'READ_OK', listing
    assert listing['data']['items'][0] == detail['call'] and 'request_snapshot_json' not in listing['data']['items'][0]
    assert listing['data']['operation'] == 'DISCUSS'
    # Windows' TestClient event loop needs its own local self-pipe sockets.
    # The direct reads above prove no socket use; HTTP retains compile guard.
    monkeypatch.setattr(socket.socket, 'connect', original_connect)
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(guide_router)
    with TestClient(app) as client:
        response = client.get('/api/v1/model-calls/1');assert response.status_code == 200, response.text
        assert response.json()['data'] == detail
    assert counts(workspace[0]) == before


def test_unknown_saved_count_is_null_and_new_generation_summary_remains_readable(workspace, monkeypatch):
    offline_gate(monkeypatch)
    accepted = accept(workspace, operation='GENERATE', target={'kind': 'NEW', 'name': '离线新稿', 'document_kind': 'brief', 'template_ref': None})
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    assert execute(workspace, Gateway(lambda context: output(context, response_type='ANALYSIS', analysis={
        'conclusion': 'NEED_EVIDENCE', 'summary': '需要更多信息', 'findings': [], 'covered_refs': [], 'unresolved': []})))['code'] == 'AI_FINISHED'
    with workspace[0].transaction(write=True) as connection:
        saved = json.loads(connection.execute('SELECT request_snapshot_json FROM llm_uses WHERE id=1').fetchone()[0])
        saved['counting']['count_attempts'][-1]['measurement'].pop('counts')
        connection.execute('UPDATE llm_uses SET request_snapshot_json=? WHERE id=1', (json.dumps(saved),))
    result = get_model_call(workspace[0], 1);assert result['code'] == 'READ_OK', result
    assert result['data']['action_type'] == 'GENERATE' and result['data']['call']['document_version'] is None
    assert result['data']['preflight']['counts'] == [None]*8


def test_read_only_run_exposes_saved_analysis_without_reconstructing_or_sending(workspace, monkeypatch):
    from backend.app.guide.queries import get_guide_run
    from backend.app.requirements.source_refs import verify_source_refs
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    analysis = {'conclusion': 'RESULT', 'summary': '实际保存的完整分析',
        'findings': [{'ref': 'f1', 'severity': 'WARNING', 'message': '首版范围需保留', 'source_refs': ['m2']}],
        'covered_refs': ['m2'], 'unresolved': []}
    assert execute(workspace, Gateway(lambda context: output(context, response_type='ANALYSIS', analysis=analysis)))['code'] == 'AI_FINISHED'
    def forbidden(*args, **kwargs): raise AssertionError('Reading analysis cannot dispatch or compile')
    monkeypatch.setattr('backend.app.guide.collaboration_context.compile_context', forbidden)
    before = counts(workspace[0]);result = get_guide_run(workspace[0], 1, catalog=workspace[2])
    assert result['code'] == 'READ_OK', result
    assert result['data']['final_result']['analysis'] == analysis
    with workspace[0].transaction() as connection:
        verify_source_refs(connection, 1, [{'kind': 'RUN_RESULT', 'guide_run_id': 1}], resources=workspace[2].collaboration)
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(guide_router)
    with TestClient(app) as client:
        response = client.get('/api/v1/guide-runs/1');assert response.status_code == 200, response.text
        assert response.json()['data']['final_result']['analysis'] == analysis
    assert counts(workspace[0]) == before
