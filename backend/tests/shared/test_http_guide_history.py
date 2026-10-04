"""I19 ASGI real history projection, filtering and safe page failures."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.guide.api import guide_router
from backend.app.guide import queries
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.guide import test_history as fixtures
from backend.tests.shared import test_http_reads as http_fixtures


class HttpGuideHistoryTests(unittest.TestCase):
    facts=fixtures.GuideHistoryTests.facts
    payload=fixtures.GuideHistoryTests.payload
    create=fixtures.GuideHistoryTests.create
    row=fixtures.GuideHistoryTests.row
    protocol_run_fixture=fixtures.GuideHistoryTests.protocol_run_fixture
    envelope=http_fixtures.HttpReadTests.envelope

    def setUp(self):
        fixtures.GuideHistoryTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(guide_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/requirements/'+str(self.req)+'/guide-runs'

    def test_actual_summary_page_and_repeated_or_and_filters_with_fresh_request_ids(self):
        self.protocol_run_fixture(10,action='ASK');before=self.facts()
        with patch('backend.app.guide.queries.list_guide_runs',wraps=queries.list_guide_runs) as invoked:
            first=self.envelope(self.client.get(self.url))
        invoked.assert_called_once();self.assertEqual(first['meta']['pagination'],{'page':1,'page_size':20,'total':2,'total_pages':1})
        self.assertEqual(set(first['data']),{'items'});self.assertEqual([item['id'] for item in first['data']['items']],[10,1]);self.assertNotIn('final_result',first['data']['items'][0])
        filtered=self.envelope(self.client.get(self.url+'?status=RUNNING&status=RUNNING&action_type=ASK'))
        self.assertEqual([item['id'] for item in filtered['data']['items']],[10]);self.assertNotEqual(first['meta']['request_id'],filtered['meta']['request_id']);self.assertEqual(self.facts(),before)

    def test_noncanonical_paths_queries_and_body_are_rejected_before_app(self):
        before=self.facts()
        urls=['/api/v1/requirements/01/guide-runs']+[self.url+'?'+query for query in ('status=','status=null','status=RUNNING,FAILED','action_type=ask','page=01','page=1&page=2','page=100001','scope_type=DOCUMENT')]
        for url in urls:
            with patch('backend.app.guide.queries.list_guide_runs',wraps=queries.list_guide_runs) as invoked:
                self.envelope(self.client.get(url),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.guide.queries.list_guide_runs',wraps=queries.list_guide_runs) as invoked:
            self.envelope(self.client.request('GET',self.url,content='{}'),422)
        invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_missing_requirement_is_404_and_out_of_range_page_stays_requested(self):
        before=self.facts();self.envelope(self.client.get('/api/v1/requirements/999/guide-runs'),404)
        value=self.envelope(self.client.get(self.url+'?page=100000'))
        self.assertEqual(value['data'],{'items':[]});self.assertEqual(value['meta']['pagination'],{'page':100000,'page_size':20,'total':1,'total_pages':1});self.assertEqual(self.facts(),before)

    def test_projection_failure_and_malformed_persistent_scope_are_safe_no_writes(self):
        before=self.facts()
        with patch('backend.app.guide.http_models.ListGuideRunsResponse.project',side_effect=ValueError('private history exception')):
            value=self.envelope(self.client.get(self.url),500)
        self.assertNotIn('private history exception',str(value));self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET scope_type='BLOCK',scope_ref_json='{}' WHERE id=?",(self.run,))
        before=self.facts();self.envelope(self.client.get(self.url),500);self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
