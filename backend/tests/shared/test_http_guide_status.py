"""I16 actual accepted/recovered run reads through ASGI with no query writes."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.guide.api import guide_router
from backend.app.guide import queries
from backend.app.guide.commands import recover_runs
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.guide import test_queries as fixtures
from backend.tests.shared import test_http_commands as http_fixtures


class HttpGuideStatusTests(unittest.TestCase):
    facts=fixtures.GuideQueryTests.facts
    payload=fixtures.GuideQueryTests.payload
    create=fixtures.GuideQueryTests.create
    completed_fixture=fixtures.GuideQueryTests.completed_fixture
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.GuideQueryTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(guide_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/guide-runs/'+str(self.run)

    def test_accepted_running_and_recovered_failed_are_read_success_with_fresh_request_ids(self):
        before=self.facts()
        with patch('backend.app.guide.queries.get_guide_run',wraps=queries.get_guide_run) as invoked:
            first=self.envelope(self.client.get(self.url))
        invoked.assert_called_once();self.assertEqual(first['data']['status'],'RUNNING');self.assertEqual(self.facts(),before)
        second=self.envelope(self.client.get(self.url));self.assertNotEqual(first['meta']['request_id'],second['meta']['request_id'])
        recovered=recover_runs(self.database,{'recovery_reason':'STARTUP','live_run_ids':set(),'operation_time':self.at},process_lock=self.lock)
        self.assertEqual(recovered['code'],'RECOVERED',recovered);before=self.facts()
        failed=self.envelope(self.client.get(self.url));self.assertEqual(failed['data']['status'],'FAILED');self.assertEqual(failed['data']['error_code'],'INTERRUPTED');self.assertEqual(self.facts(),before)

    def test_complete_safe_projection_has_resource_references_without_audit_or_full_message(self):
        effects=self.completed_fixture();before=self.facts();value=self.envelope(self.client.get(self.url))
        self.assertEqual(value['data']['final_result']['assistant_message_id'],effects['assistant_message_id'])
        self.assertNotIn('full visible answer',str(value));self.assertNotIn('prompt_version',value['data']);self.assertNotIn('llm_uses',value['data']);self.assertEqual(self.facts(),before)

    def test_invalid_path_query_and_body_are_zero_app_not_found_is_404(self):
        before=self.facts()
        for url in ('/api/v1/guide-runs/01','/api/v1/guide-runs/+1',self.url+'?page=1',self.url+'?guide_run_id=1'):
            with patch('backend.app.guide.queries.get_guide_run',wraps=queries.get_guide_run) as invoked:
                self.envelope(self.client.get(url),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.guide.queries.get_guide_run',wraps=queries.get_guide_run) as invoked:
            self.envelope(self.client.request('GET',self.url,content='{}',headers={'Content-Type':'application/json'}),422)
        invoked.assert_not_called()
        self.envelope(self.client.get('/api/v1/guide-runs/999'),404);self.assertEqual(self.facts(),before)

    def test_core_corruption_and_response_mapping_exception_are_safe_500(self):
        self.completed_fixture()
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE guide_runs SET final_result_json=? WHERE id=?',('{"prompt":"private raw prompt"}',self.run))
        before=self.facts();value=self.envelope(self.client.get(self.url),500);self.assertNotIn('private raw prompt',str(value));self.assertEqual(self.facts(),before)
        with patch('backend.app.guide.http_models.GetGuideRunResponse.project',side_effect=ValueError('private response error')):
            self.envelope(self.client.get(self.url),500)
        self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
