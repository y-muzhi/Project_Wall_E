"""Saved request reads, isolated SQLite fixtures; no model or counting I/O."""
import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.guide.model_calls import list_model_calls, get_model_call
from backend.app.guide.api import guide_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.infrastructure.test_audit_repository import AuditRepositoryTests


class ModelCallReadTests(unittest.TestCase):
    def setUp(self):
        self.f = AuditRepositoryTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.call = self.f.prepare()['id']

    def snapshot(self, value):
        with self.f.database.transaction(write=True) as connection:
            connection.execute('UPDATE llm_uses SET request_snapshot_json=? WHERE id=?', (json.dumps(value, ensure_ascii=False), self.call))

    def saved(self):
        return json.loads(self.f.row('llm_uses', self.call)['request_snapshot_json'])

    def test_summary_is_small_unknown_is_null_and_reads_do_not_mutate_or_connect(self):
        before = self.f.facts()
        with patch('socket.socket.connect', side_effect=AssertionError('Read must stay offline')):
            result = list_model_calls(self.f.database, self.f.run)
            detail = get_model_call(self.f.database, self.call)
        self.assertEqual(result['code'], 'READ_OK', result); self.assertEqual(detail['code'], 'READ_OK', detail)
        row = result['data']['items'][0]
        self.assertEqual(row['user_message_id'], 1); self.assertEqual(row['document_version'], 1)
        for field in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'duration_ms'): self.assertIsNone(row[field])
        self.assertNotIn('sections', result['data']); self.assertNotIn('request_snapshot_json', row)
        self.assertNotIn('profile', detail['data']); self.assertNotIn('provider_request_id', row)
        self.assertEqual(self.f.facts(), before)

    def test_actual_zero_and_cache_are_preserved_without_double_counting(self):
        self.f.transport(self.call, input_tokens=0, output_tokens=12, duration_ms=44, cache_info={'cached_tokens': 0})
        row = list_model_calls(self.f.database, self.f.run)['data']['items'][0]
        self.assertEqual((row['input_tokens'], row['output_tokens'], row['total_tokens'], row['cached_tokens'], row['duration_ms']), (0, 12, 12, 0, 44))

    def test_all_attempts_ordered_and_unknown_usage_not_fabricated(self):
        self.f.transport(self.call, self.f.response(content='bad JSON'), input_tokens=100, output_tokens=12, cache_info={'cached_tokens': 50})
        self.f.parse(self.call)
        second = self.f.prepare(at='2026-10-04T08:00:03.000Z', call_no=1)['id']
        rows = list_model_calls(self.f.database, self.f.run)['data']['items']
        self.assertEqual([(row['id'], row['call_no'], row['attempt_no']) for row in rows], [(self.call, 1, 1), (second, 1, 2)])
        self.assertEqual(rows[0]['total_tokens'], 112); self.assertIsNone(rows[1]['total_tokens'])

    def test_v7_order_history_metadata_budget_and_raw_use_one_saved_snapshot(self):
        saved = self.saved()
        wire = {'template': {'markdown_content': '# Saved template'}, 'current_document': {'read_blocks': [{'markdown_content': 'Original body'}]},
            'history': [{'role': 'USER', 'content': 'Question\nChosen option\nCustom answer'}], 'user_input': {'content': 'Latest input'},
            'source': None, 'request_metadata': {'user_message_id': 123, 'current_document': {'content_version': 7}, 'history_message_refs': [{'id': 98}]}}
        saved['request']['messages'][1]['content'] = json.dumps(wire, ensure_ascii=False)
        saved['request']['future_saved_parameter'] = 'retained'
        saved['counting'] = {'input_tokens_candidate': 1100, 'count_attempts': [{'measurement': {'counts': [10, 66, 12, 2, 30, 22]}, 'removed_history_ids': [55]}]}
        self.snapshot(saved)
        with self.f.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirement_documents SET markdown_content='Later body' WHERE id=?", (self.f.created['current_document_id'],))
        before = self.f.facts(); result = get_model_call(self.f.database, self.call)
        self.assertEqual(result['code'], 'READ_OK', result); data = result['data']
        self.assertEqual([section['title'] for section in data['sections']], ['系统提示词与输出格式约束', '完整模板', '当前正文与读取区块', '历史消息', '本轮用户输入', '来源信息', '身份、范围与权限'])
        self.assertEqual(json.loads(data['raw_request_json']), saved['request'])
        self.assertEqual((data['call']['user_message_id'], data['call']['document_version']), (123, 7))
        self.assertEqual(data['included_history_ids'], [98]); self.assertEqual(data['budget_removed_history_ids'], [55])
        self.assertEqual(data['preflight']['counts'], [10, 66, 12, 2, 30, 22]); self.assertEqual(data['preflight']['input_tokens'], 1100)
        self.assertIn('Original body', data['sections'][2]['content']); self.assertNotIn('Later body', data['sections'][2]['content'])
        self.assertEqual(self.f.facts(), before)

    def test_incomplete_or_plain_text_legacy_snapshot_stays_readable(self):
        for request in (None, {'messages': None}, {'messages': [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'plain input'}]}):
            self.snapshot({'request': request})
            result = get_model_call(self.f.database, self.call); summary = list_model_calls(self.f.database, self.f.run)
            self.assertEqual((result['code'], summary['code']), ('READ_OK', 'READ_OK'))
            self.assertIsNone(result['data']['call']['document_version']); self.assertIsNone(result['data']['preflight']['budget'])
        self.assertEqual(result['data']['sections'][1]['content'], 'plain input')

    def test_program_receipt_and_failed_cancelled_preparing_no_calls(self):
        with self.f.database.transaction(write=True) as connection:
            connection.execute('DELETE FROM llm_uses WHERE id=?', (self.call,))
            connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',ended_at='2026-10-04T08:00:03.000Z' WHERE id=?", (self.f.run,))
            connection.execute("INSERT INTO conversation_messages VALUES (100,?,?,2,'ASSISTANT','程序已将确认事实写入正文','TEXT',NULL,NULL,NULL,?)", (self.f.req, self.f.run, '2026-10-04T08:00:03.000Z'))
        result = list_model_calls(self.f.database, self.f.run)['data']
        self.assertTrue(result['program_processed']); self.assertEqual(result['items'], [])
        with self.f.database.transaction(write=True) as connection: connection.execute('DELETE FROM conversation_messages WHERE id=100')
        for status, step in [('FAILED', 'FINISHED'), ('CANCELLED', 'FINISHED'), ('RUNNING', 'PREPARING')]:
            with self.f.database.transaction(write=True) as connection:
                connection.execute('UPDATE guide_runs SET status=?,current_step=?,ended_at=?,error_code=?,error_message=?,cancel_reason=? WHERE id=?', (status, step, None if status=='RUNNING' else '2026-10-04T08:00:03.000Z', 'MODEL_ERROR' if status=='FAILED' else None, 'failed' if status=='FAILED' else None, 'user cancelled' if status=='CANCELLED' else None, self.f.run))
            result = list_model_calls(self.f.database, self.f.run)['data']
            self.assertFalse(result['program_processed']); self.assertEqual(result['status'], status)

    def test_http_contract_canonical_id_empty_body_missing_and_read_only(self):
        app = FastAPI(redirect_slashes=False); app.include_router(guide_router)
        app.state.walle_runtime = HttpRuntime(self.f.database, self.f.catalog, self.f.executor)
        before = self.f.facts()
        with TestClient(app) as client:
            for url in (f'/api/v1/guide-runs/{self.f.run}/model-calls', f'/api/v1/model-calls/{self.call}'):
                self.assertEqual(client.get(url).status_code, 200)
                self.assertEqual(client.get(url+'?unexpected=1').status_code, 422)
                self.assertEqual(client.request('GET', url, content='{}').status_code, 422)
            self.assertEqual(client.get('/api/v1/model-calls/01').status_code, 422)
            self.assertEqual(client.get('/api/v1/model-calls/999').status_code, 404)
            self.assertEqual(client.get('/api/v1/guide-runs/999/model-calls').status_code, 404)
        self.assertEqual(self.f.facts(), before)
