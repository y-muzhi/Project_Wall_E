"""I21 actual file decisions and strict public projection."""
import unittest
import json
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.suggestions import commands
from backend.app.suggestions.api import batch_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.suggestions import test_decision as fixtures
from backend.tests.shared import test_http_reads as http_fixtures
from backend.tests.requirements import test_create_requirement as creation


class HttpDecisionTests(unittest.TestCase):
    facts=fixtures.DecisionTests.facts
    payload=fixtures.DecisionTests.payload
    create=fixtures.DecisionTests.create
    row=fixtures.DecisionTests.row
    terminal=fixtures.DecisionTests.terminal
    batch_fixture=fixtures.DecisionTests.batch_fixture
    envelope=http_fixtures.HttpReadTests.envelope

    def setUp(self):
        fixtures.DecisionTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(batch_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/suggestions/10/decision';self.headers={'Idempotency-Key':creation.KEY}

    def test_actual_decision_and_original_replay_with_new_request_id(self):
        with patch('backend.app.suggestions.commands.decide_suggestion',wraps=commands.decide_suggestion) as invoked:
            first=self.envelope(self.client.put(self.url,headers=self.headers,json={'decision':'EDITED','edited_content':'# 用户😀'}))
        invoked.assert_called_once();self.assertEqual(first['data']['suggestion']['status'],'EDITED');self.assertEqual(first['data']['counts']['edited'],1)
        self.assertNotIn('pagination',first['meta']);before=self.facts()
        again=self.envelope(self.client.put(self.url,headers=self.headers,json={'decision':'EDITED','edited_content':'# 用户😀'}))
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)
        self.envelope(self.client.put(self.url,headers=self.headers,json={'decision':'REJECTED'}),409);self.assertEqual(self.facts(),before)

    def test_strict_path_query_json_header_body_and_unicode_are_zero_app(self):
        before=self.facts()
        variants=[('/api/v1/suggestions/010/decision',self.headers,{'decision':'ACCEPTED'}),(self.url+'?page=1',self.headers,{'decision':'ACCEPTED'}),(self.url,{}, {'decision':'ACCEPTED'}),(self.url,self.headers,{'decision':'PENDING'}),(self.url,self.headers,{'decision':'EDITED'}),(self.url,self.headers,{'decision':'ACCEPTED','target_ref':{'block_id':1}}),(self.url,self.headers,{'decision':'EDITED','edited_content':'\ud800'})]
        for url,headers,body in variants:
            with patch('backend.app.suggestions.commands.decide_suggestion',wraps=commands.decide_suggestion) as invoked:
                self.envelope(self.client.put(url,headers={**headers,'Content-Type':'application/json'},content=json.dumps(body)),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.suggestions.commands.decide_suggestion',wraps=commands.decide_suggestion) as invoked:
            self.envelope(self.client.put(self.url,headers={**self.headers,'Content-Type':'application/json'},content='{"decision":"ACCEPTED","decision":"REJECTED"}'),422)
        invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_native_patch_invalid_is_safe_422_and_missing_resource_404(self):
        before=self.facts();value=self.envelope(self.client.put(self.url,headers=self.headers,json={'decision':'EDITED','edited_content':'first\n\nsecond'}),422)
        self.assertIsNone(value['data']);self.assertEqual(self.facts(),before)
        self.envelope(self.client.put('/api/v1/suggestions/999/decision',headers=self.headers,json={'decision':'ACCEPTED'}),404);self.assertEqual(self.facts(),before)

    def test_actual_commit_survives_projection_failure_and_strong_result_guard(self):
        with patch('backend.app.suggestions.http_models.DecideSuggestionResponse.project',side_effect=ValueError('private postcommit failure')):
            value=self.envelope(self.client.put(self.url,headers=self.headers,json={'decision':'ACCEPTED'}),500)
        self.assertNotIn('private postcommit failure',str(value));self.assertEqual(self.row('suggestions',10)['status'],'ACCEPTED')
        before=self.facts();self.envelope(self.client.put(self.url,headers=self.headers,json={'decision':'ACCEPTED'}));self.assertEqual(self.facts(),before)
        original=commands.decide_suggestion
        def damaged(*args,**kwargs):
            result=original(*args,**kwargs);result['data']['suggestion']['status']='REJECTED';return result
        with patch('backend.app.suggestions.commands.decide_suggestion',side_effect=damaged): self.envelope(self.client.put(self.url,headers=self.headers,json={'decision':'ACCEPTED'}),500)
        self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
