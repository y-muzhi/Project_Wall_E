"""I22 actual batch application/no-change and postcommit HTTP failure replay."""
import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.suggestions import commands
from backend.app.suggestions.api import batch_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.suggestions import test_complete as fixtures
from backend.tests.shared import test_http_reads as http_fixtures
from backend.tests.requirements import test_create_requirement as creation


class HttpCompleteTests(unittest.TestCase):
    facts=fixtures.CompleteTests.facts
    payload=fixtures.CompleteTests.payload
    create=fixtures.CompleteTests.create
    row=fixtures.CompleteTests.row
    terminal=fixtures.CompleteTests.terminal
    batch_fixture=fixtures.CompleteTests.batch_fixture
    add_suggestion=fixtures.CompleteTests.add_suggestion
    decide=fixtures.CompleteTests.decide
    envelope=http_fixtures.HttpReadTests.envelope

    def setUp(self):
        fixtures.CompleteTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(batch_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/suggestion-batches/10/complete';self.headers={'Idempotency-Key':creation.KEY}

    def test_real_applied_full_document_strong_result_and_original_replay(self):
        self.decide()
        with patch('backend.app.suggestions.commands.complete_batch',wraps=commands.complete_batch) as invoked:
            first=self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}))
        invoked.assert_called_once();self.assertEqual(set(first['data']),{'batch','counts','current_document'})
        self.assertEqual(first['data']['current_document']['content_version'],2);self.assertEqual(first['data']['batch']['completion_result'],'CHANGES_APPLIED')
        self.assertNotIn('pagination',first['meta']);before=self.facts()
        again=self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}))
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)
        self.envelope(self.client.post(self.url,headers={'Idempotency-Key':creation.OTHER},json={'expected_content_version':1}),409);self.assertEqual(self.facts(),before)

    def test_no_change_is_registered_success_same_payload_without_version_increment(self):
        self.decide('REJECTED');current=self.row('requirement_documents',self.created['current_document_id'])
        value=self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}))
        self.assertEqual(value['data']['batch']['completion_result'],'NO_CHANGE');self.assertIsNone(value['data']['batch']['applied_content_version'])
        self.assertEqual(value['data']['current_document']['content_version'],1);self.assertEqual(self.row('requirement_documents',current['id']),current)

    def test_strict_path_query_json_headers_version_unknown_keys_zero_app(self):
        before=self.facts()
        variants=[('/api/v1/suggestion-batches/010/complete',self.headers,{'expected_content_version':1}),(self.url+'?page=1',self.headers,{'expected_content_version':1}),(self.url,{}, {'expected_content_version':1}),(self.url,self.headers,{}),(self.url,self.headers,{'expected_content_version':True}),(self.url,self.headers,{'expected_version':1}),(self.url,self.headers,{'expected_content_version':1,'counts':{}})]
        for url,headers,body in variants:
            with patch('backend.app.suggestions.commands.complete_batch',wraps=commands.complete_batch) as invoked:
                self.envelope(self.client.post(url,headers=headers,json=body),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        self.envelope(self.client.post('/api/v1/suggestion-batches/999/complete',headers=self.headers,json={'expected_content_version':1}),404);self.assertEqual(self.facts(),before)

    def test_pending_version_stale_detail_errors_preserve_all_and_never_echo_original_text(self):
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}),422);self.assertEqual(self.facts(),before)
        self.add_suggestion(11,2,target_ref_json='{"block_id":999}',original_content='private original content');self.decide();self.decide(suggestion_id=11)
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':2}),409);self.assertEqual(self.facts(),before)
        value=self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}),409)
        self.assertEqual(value['error']['code'],'TARGET_STALE');self.assertEqual(value['error']['details']['suggestion_errors'][0]['suggestion_id'],11)
        self.assertNotIn('private original content',str(value));self.assertEqual(self.facts(),before)

    def test_actual_commit_survives_projection_failure_and_guard_rejects_false_document_version(self):
        self.decide()
        with patch('backend.app.suggestions.http_models.CompleteBatchResponse.project',side_effect=ValueError('private aftercommit failure')):
            value=self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}),500)
        self.assertNotIn('private aftercommit failure',str(value));self.assertEqual(self.row('requirement_documents',self.created['current_document_id'])['content_version'],2)
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}));self.assertEqual(self.facts(),before)
        original=commands.complete_batch
        def damaged(*args,**kwargs):
            result=original(*args,**kwargs);result['data']['current_document']['content_version']+=1;return result
        with patch('backend.app.suggestions.commands.complete_batch',side_effect=damaged): self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':1}),500)
        self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
