"""I20 actual file aggregate through ASGI, no current-body or model substitute."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.suggestions.api import batch_router
from backend.app.suggestions import queries
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.suggestions import test_queries as fixtures
from backend.tests.shared import test_http_reads as http_fixtures


class HttpBatchReadTests(unittest.TestCase):
    facts=fixtures.BatchQueryTests.facts
    payload=fixtures.BatchQueryTests.payload
    create=fixtures.BatchQueryTests.create
    row=fixtures.BatchQueryTests.row
    terminal=fixtures.BatchQueryTests.terminal
    batch_fixture=fixtures.BatchQueryTests.batch_fixture
    add_suggestion=fixtures.BatchQueryTests.add_suggestion
    envelope=http_fixtures.HttpReadTests.envelope

    def setUp(self):
        fixtures.BatchQueryTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(batch_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/suggestion-batches/10'

    def test_complete_actual_aggregate_no_pagination_fresh_request_identity_no_writes(self):
        for identity in range(11,35): self.add_suggestion(identity,identity-9)
        before=self.facts()
        with patch('backend.app.suggestions.queries.get_batch',wraps=queries.get_batch) as invoked:
            first=self.envelope(self.client.get(self.url))
        invoked.assert_called_once();self.assertEqual(first['data']['counts']['total'],25);self.assertEqual(len(first['data']['suggestions']),25)
        self.assertNotIn('pagination',first['meta']);item=first['data']['suggestions'][0]
        self.assertEqual(item['target_ref'],{'block_id':1});self.assertNotIn('target_ref_json',item);self.assertNotIn('prompt',first['data']);self.assertEqual(self.facts(),before)
        again=self.envelope(self.client.get(self.url));self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)

    def test_paths_query_body_reject_before_app_missing_batch_is_404(self):
        before=self.facts()
        for url in ('/api/v1/suggestion-batches/010',self.url+'?page=1',self.url+'?status=PENDING'):
            with patch('backend.app.suggestions.queries.get_batch',wraps=queries.get_batch) as invoked:
                self.envelope(self.client.get(url),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.suggestions.queries.get_batch',wraps=queries.get_batch) as invoked:
            self.envelope(self.client.request('GET',self.url,content='{}'),422)
        invoked.assert_not_called();self.envelope(self.client.get('/api/v1/suggestion-batches/999'),404);self.assertEqual(self.facts(),before)

    def test_projection_guard_rejects_false_counts_and_private_mapping_errors_without_mutation(self):
        before=self.facts();original=queries.get_batch
        def damaged(*args,**kwargs):
            result=original(*args,**kwargs);result['data']['counts']['total']+=1
            return result
        with patch('backend.app.suggestions.queries.get_batch',side_effect=damaged): self.envelope(self.client.get(self.url),500)
        self.assertEqual(self.facts(),before)
        with patch('backend.app.suggestions.http_models.GetBatchResponse.project',side_effect=ValueError('private batch exception')):
            value=self.envelope(self.client.get(self.url),500)
        self.assertNotIn('private batch exception',str(value));self.assertEqual(self.facts(),before)

    def test_empty_persistent_batch_is_safe_failure_instead_of_empty_success(self):
        with self.database.transaction(write=True) as connection: connection.execute('DELETE FROM suggestions')
        before=self.facts();value=self.envelope(self.client.get(self.url),500)
        self.assertIsNone(value['data']);self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
