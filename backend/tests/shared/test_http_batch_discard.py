"""I23 native commit and transport projection, no model output substitute."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.suggestions.api import batch_router
from backend.app.suggestions import commands
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.suggestions import test_discard as fixtures
from backend.tests.shared import test_http_reads as http_fixtures
from backend.tests.requirements import test_create_requirement as creation


class HttpDiscardTests(unittest.TestCase):
    facts=fixtures.DiscardTests.facts
    payload=fixtures.DiscardTests.payload
    create=fixtures.DiscardTests.create
    row=fixtures.DiscardTests.row
    terminal=fixtures.DiscardTests.terminal
    batch_fixture=fixtures.DiscardTests.batch_fixture
    envelope=http_fixtures.HttpReadTests.envelope

    def setUp(self):
        fixtures.DiscardTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(batch_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/suggestion-batches/10/discard';self.headers={'Idempotency-Key':creation.KEY}

    def test_native_success_exact_response_replay_new_request_identity_and_new_key_conflict(self):
        with patch('backend.app.suggestions.commands.discard_batch',wraps=commands.discard_batch) as invoked:
            first=self.envelope(self.client.post(self.url,headers=self.headers))
        invoked.assert_called_once();self.assertTrue(first['success'])
        self.assertEqual(set(first['data']),{'batch','counts'});self.assertEqual(first['data']['batch']['status'],'DISCARDED')
        self.assertNotIn('pagination',first['meta']);before=self.facts()
        again=self.envelope(self.client.post(self.url,headers=self.headers));self.assertEqual(again['data'],first['data'])
        self.assertNotEqual(again['meta']['request_id'],first['meta']['request_id']);self.assertEqual(self.facts(),before)
        self.envelope(self.client.post(self.url,headers={'Idempotency-Key':creation.OTHER}),409);self.assertEqual(self.facts(),before)

    def test_invalid_paths_queries_headers_body_are_zero_app(self):
        before=self.facts()
        variants=[('/api/v1/suggestion-batches/010/discard',self.headers,None),(self.url+'?page=1',self.headers,None),(self.url,{},None),(self.url,{'Idempotency-Key':'bad'},None),(self.url,[('Idempotency-Key',creation.KEY),('Idempotency-Key',creation.KEY)],None),(self.url,self.headers,'{}')]
        for url,headers,content in variants:
            with patch('backend.app.suggestions.commands.discard_batch',wraps=commands.discard_batch) as invoked:
                self.envelope(self.client.post(url,headers=headers,content=content),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        self.envelope(self.client.post('/api/v1/suggestion-batches/999/discard',headers=self.headers),404);self.assertEqual(self.facts(),before)

    def test_projection_failure_after_actual_commit_is_recoverable_by_same_key(self):
        with patch('backend.app.suggestions.http_models.DiscardBatchResponse.project',side_effect=ValueError('private projection failure')):
            value=self.envelope(self.client.post(self.url,headers=self.headers),500)
        self.assertNotIn('private projection failure',str(value));self.assertEqual(self.row('suggestion_batches',10)['status'],'DISCARDED')
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers));self.assertEqual(self.facts(),before)

    def test_public_guard_rejects_invented_counts_after_actual_native_commit(self):
        original=commands.discard_batch
        def damaged(*args,**kwargs):
            result=original(*args,**kwargs);result['data']['counts']['total']+=1;return result
        with patch('backend.app.suggestions.commands.discard_batch',side_effect=damaged): self.envelope(self.client.post(self.url,headers=self.headers),500)
        before=self.facts();value=self.envelope(self.client.post(self.url,headers=self.headers))
        self.assertEqual(value['data']['counts']['total'],1);self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
