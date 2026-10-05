"""I14/I15 actual SQLite through FastAPI; no model dispatch or fixture success."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.guide.api import guide_router
from backend.app.guide import commands
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.guide import test_acceptance as fixtures
from backend.tests.shared import test_http_commands as http_fixtures


class HttpGuideAcceptanceTests(unittest.TestCase):
    facts=fixtures.AcceptanceTests.facts
    payload=fixtures.AcceptanceTests.payload
    create=fixtures.AcceptanceTests.create
    row=fixtures.AcceptanceTests.row
    guide_payload=fixtures.AcceptanceTests.guide_payload
    accept=fixtures.AcceptanceTests.accept
    activate=fixtures.AcceptanceTests.activate
    waiting=fixtures.AcceptanceTests.waiting
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.AcceptanceTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(guide_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url=f'/api/v1/requirements/{self.req}/guide-runs'
        self.headers={'Idempotency-Key':fixtures.KEY}
        self.body={'expected_version':1,'action_type':'INITIALIZE','instruction':' first\r\nsecond ','scope_type':'DOCUMENT','source_type':'USER_INSTRUCTION'}

    def test_real_create_202_exact_message_and_run_once_replay_fresh_request_id(self):
        with patch('backend.app.guide.commands.create_guide_run',wraps=commands.create_guide_run) as invoked:
            first=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202)
        invoked.assert_called_once();self.assertEqual(set(first['data']),{'guide_run','user_message'})
        self.assertEqual(first['data']['user_message']['content'],'first\nsecond')
        self.assertEqual(first['data']['guide_run']['status'],'RUNNING')
        before=self.facts();again=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202)
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)
        self.assertNotIn('pagination',first['meta'])

    def test_create_strict_path_body_query_key_and_nested_input_zero_app(self):
        before=self.facts()
        cases=[(self.url+'?page=1',self.headers,self.body),('/api/v1/requirements/01/guide-runs',self.headers,self.body),
            (self.url,{},self.body),(self.url,self.headers,{**self.body,'expected_content_version':1}),(self.url,self.headers,{**self.body,'function_type':'INITIALIZE_REQUIREMENT'}),
            (self.url,self.headers,{**self.body,'scope_type':'BLOCK','scope_ref':{'block_id':1,'write':True}}),
            (self.url,self.headers,{**self.body,'expected_version':True}),(self.url,self.headers,{**self.body,'instruction':'\ud800'})]
        for url,headers,body in cases:
            import json
            with patch('backend.app.guide.commands.create_guide_run',wraps=commands.create_guide_run) as invoked:
                self.envelope(self.client.post(url,headers={**headers,'Content-Type':'application/json'},content=json.dumps(body,ensure_ascii=True)),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        value=self.envelope(self.client.post(self.url,headers=self.headers,json={**self.body,'expected_version':2}),409)
        self.assertEqual(value['error']['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)

    def test_real_continue_202_same_run_and_plain_text_and_replay(self):
        identity=self.waiting('REVIEW');url=f'/api/v1/guide-runs/{identity}/continue';headers={'Idempotency-Key':fixtures.NEXT}
        with patch('backend.app.guide.commands.continue_guide_run',wraps=commands.continue_guide_run) as invoked:
            first=self.envelope(self.client.post(url,headers=headers,json={'instruction':'more'}),202)
        invoked.assert_called_once();self.assertEqual(first['data'],{'id':identity,'requirement_id':self.req,'status':'RUNNING','current_step':'PREPARING'})
        message=self.row('conversation_messages',self.row('guide_runs',identity)['trigger_message_id']);self.assertEqual(message['message_type'],'TEXT');self.assertIsNone(message['reply_to_message_id'])
        before=self.facts();again=self.envelope(self.client.post(url,headers=headers,json={'instruction':'more'}),202)
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)

    def test_continue_invalid_body_and_duplicate_json_never_invoke_app(self):
        identity=self.waiting();url=f'/api/v1/guide-runs/{identity}/continue';headers={'Idempotency-Key':fixtures.NEXT,'Content-Type':'application/json'};before=self.facts()
        for body in ('{}','{"instruction":null}','{"instruction":"a","instruction":"b"}','{"instruction":"a","responses":[]}', '"more"'):
            with patch('backend.app.guide.commands.continue_guide_run',wraps=commands.continue_guide_run) as invoked:
                self.envelope(self.client.post(url,headers=headers,content=body),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_create_postcommit_projection_failure_retains_acceptance_and_replays(self):
        with patch('backend.app.guide.http_models.CreateGuideRunResponse.project',side_effect=ValueError('private map failure')):
            value=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),500)
        self.assertNotIn('private map failure',str(value));before=self.facts()
        self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202);self.assertEqual(self.facts(),before)

    def test_continue_postcommit_projection_failure_retains_acceptance_and_replays(self):
        identity=self.waiting()
        url=f'/api/v1/guide-runs/{identity}/continue';headers={'Idempotency-Key':'00000000-0000-4000-8000-00000000000f'}
        with patch('backend.app.guide.http_models.ContinueGuideRunResponse.project',side_effect=ValueError('private continue map')): self.envelope(self.client.post(url,headers=headers,json={'instruction':'more'}),500)
        before=self.facts();self.envelope(self.client.post(url,headers=headers,json={'instruction':'more'}),202);self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
