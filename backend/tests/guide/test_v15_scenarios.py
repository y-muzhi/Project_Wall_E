"""Two business cases through real HTTP/SQLite; effects remain offline fixtures."""
import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.guide.test_v15_counting import offline_gate, Counter
from backend.tests.guide.test_v15_execution import PROFILE, Gateway, output
from backend.tests.guide.test_v15_cards import group
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.requirements.api import req_router
from backend.app.documents.api import doc_router
from backend.app.guide.api import guide_router
from backend.app.messages.api import message_router
from backend.app.guide.orchestrator import execute_guide_run


@pytest.mark.parametrize('title,idea,initial,revised', [
    ('电影记录推荐', '记录、评分并推荐电影，优先解决看什么的问题', '先支持个人记录和评分。', '推荐优先使用用户明确的评分偏好。'),
    ('实验耗材管理', '记录实验耗材的入库与领用，优先解决库存不足的问题', '先支持入库和领用登记。', '低于明确的安全库存时提示补货。'),
])
def test_discuss_defer_generate_local_revision_compare_and_review_are_separate_authorized_rounds(setup, monkeypatch, title, idea, initial, revised):
    offline_gate(monkeypatch);database, executor = setup;catalog = ResourceCatalog()
    app = FastAPI();app.state.walle_runtime = HttpRuntime(database, catalog, executor)
    for router in (req_router, doc_router, guide_router, message_router): app.include_router(router)
    calls = []
    with TestClient(app) as client:
        def command(method, path, body):
            response = client.request(method, '/api/v1'+path, json=body, headers={'Idempotency-Key': str(uuid4())})
            assert response.status_code in (200, 201, 202), response.text
            return response.json()['data']
        def get(path):
            response = client.get('/api/v1'+path);assert response.status_code == 200, response.text
            return response.json()['data']
        def accept(operation, instruction, target=None, scope=None, refs=()):
            root = get('/requirements/1')['requirement']
            return command('POST', '/requirements/1/guide-runs', {'expected_discussion_version': root['discussion_version'],
                'operation': operation, 'instruction': instruction, 'target': target, 'scope': scope,
                'source_refs': list(refs), 'proposal_ref': None, 'acknowledge_source_changes': False})
        def execute(receipt, returned):
            gateway = Gateway(returned);counter = Counter(['OK'])
            result = asyncio.run(execute_guide_run(database, {'guide_run_id': receipt['guide_run_id']}, process_lock=executor.process_lock,
                catalog=catalog, profile=PROFILE, gateway=gateway, counting_counter=counter))
            assert result['code'] == 'AI_FINISHED', result
            assert len(gateway.calls) == len(counter.calls) == 1;calls.extend(gateway.calls)
            return get('/guide-runs/'+str(receipt['guide_run_id']))

        created = command('POST', '/requirements', {'title': title, 'requirement_type': 'NEW', 'initial_idea': idea})
        assert created['documents'] == [] and counts(database)['llm_uses'] == counts(database)['guide_runs'] == 0
        first = accept('DISCUSS', '先讨论首版范围，暂时不写文档。')
        def recommend(context):
            assert context.input_json.count(idea) == 1
            return output(context, message='建议先明确首版闭环，用户同意后再生成说明。', cards=group('DOCUMENT_ACTION', {
                'operation': 'GENERATE', 'target': {'kind': 'NEW', 'name': title+'说明', 'document_kind': 'brief', 'template_ref': None},
                'scope': None, 'source_refs': [context.input['current_request']['message_ref']],
                'basis_discussion_version': context.input['current_request']['basis_ref']['discussion_version'],
                'unresolved_impacts': [], 'selectable_fields': []}))
        execute(first, recommend);assert counts(database)['requirement_documents'] == 0
        message = get('/requirements/1/messages')['items'][-1];binding = message['structured_content']['program_binding']
        before = counts(database)
        deferred = command('POST', '/conversation-messages/'+str(message['id'])+'/responses', {
            'schema_version': 1, 'expected_discussion_version': binding['discussion_version'],
            'responses': [{'card_key': 'c1', 'selected_option_keys': ['defer'], 'custom_answer': None, 'skipped': False}], 'execution_selection': None})
        assert deferred['processing'] == 'PROGRAM' and deferred['result'] == 'DEFERRED'
        assert counts(database)['guide_runs'] == before['guide_runs'] and counts(database)['llm_uses'] == before['llm_uses']
        assert counts(database)['requirement_documents'] == 0

        generated = accept('GENERATE', '现在明确生成说明。', {'kind': 'NEW', 'name': title+'说明', 'document_kind': 'brief', 'template_ref': None})
        saved = execute(generated, lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={
            'name': title+'说明', 'document_kind': 'brief', 'markdown_content': '# 目标\n\n'+initial+'\n\n# 边界\n\n本轮只覆盖首版。\n', 'change_summary': '明确生成'}))
        effect = saved['document_effect'];identity = effect['document_id'];revision1 = effect['revision_id']
        current = get('/requirements/1/current-document?document_id='+str(identity))
        assert effect['result'] == 'CREATED' and current['confirmed_revision_id'] is None
        block = current['block_state_json']['blocks'][1]['block_id']
        original_tail = current['markdown_content'].split('# 边界', 1)[1]
        changed = accept('REVISE', '只修订当前这一段。', {'kind': 'EXISTING', 'document_id': identity, 'expected_content_version': 1},
            {'scope_type': 'BLOCK', 'scope_ref': {'block_id': block}})
        root = get('/requirements/1')['requirement']
        command('PATCH', '/requirements/1', {'expected_metadata_version': root['metadata_version'], 'changes': {'status': 'CLOSED'}})
        saved = execute(changed, lambda context: output(context, response_type='DOCUMENT_RESULT', document_result={
            'name': title+'说明', 'document_kind': 'brief', 'markdown_content': revised, 'change_summary': '只修改绑定段落'}))
        current = get('/requirements/1/current-document?document_id='+str(identity));revision2 = saved['document_effect']['revision_id']
        assert current['content_version'] == 2 and revised in current['markdown_content']
        assert current['markdown_content'].split('# 边界', 1)[1] == original_tail
        assert get('/requirements/1')['requirement']['status'] == 'CLOSED'
        refs = [{'kind': 'REVISION', 'document_id': identity, 'revision_id': revision, 'block_ids': None} for revision in (revision1, revision2)]
        compared = accept('COMPARE', '比较说明的新旧版本，不写正文。', refs=refs)
        def analysis(context):
            covered = [item['ref'] for item in context.input['documents']]
            return output(context, response_type='ANALYSIS', analysis={'conclusion': 'RESULT', 'summary': '已按实际携带范围完成检查。',
                'findings': [], 'covered_refs': covered, 'unresolved': []})
        before = counts(database);compared_result = execute(compared, analysis)
        assert len(compared_result['final_result']['analysis']['covered_refs']) == 2
        assert counts(database)['revisions'] == before['revisions']
        reviewed = accept('REVIEW', '仅检查这一段，参考刚才的比较结果。',
            {'kind': 'EXISTING', 'document_id': identity, 'expected_content_version': 2},
            {'scope_type': 'BLOCK', 'scope_ref': {'block_id': block}}, [{'kind': 'RUN_RESULT', 'guide_run_id': compared['guide_run_id']}])
        review = execute(reviewed, analysis)
        assert review['final_result']['analysis']['conclusion'] == 'RESULT'
        assert review['application_result'] == 'NOT_REQUESTED' and counts(database)['revisions'] == 2
        assert counts(database)['llm_uses'] == counts(database)['guide_runs'] == len(calls) == 5
        assert get('/requirements/1')['requirement']['document_work_state'] == 'IDLE'
        with database.transaction() as connection:
            assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
            assert all(json.loads(row[0])['protocol']['function_type'] == 'collaboration_v1' for row in connection.execute('SELECT request_snapshot_json FROM llm_uses'))
