"""I34 actual accepted run and anchor-only rejection through ASGI."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.guide.api import guide_router
from backend.app.guide import commands
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.guide import test_comment_acceptance as fixtures
from backend.tests.shared import test_http_commands as http_fixtures


class HttpCommentAcceptanceTests(unittest.TestCase):
    facts=fixtures.CommentAcceptanceTests.facts
    write_body=fixtures.CommentAcceptanceTests.write_body
    row=fixtures.CommentAcceptanceTests.row
    create_payload=fixtures.CommentAcceptanceTests.create_payload
    make_comment=fixtures.CommentAcceptanceTests.make_comment
    stale_selection=fixtures.CommentAcceptanceTests.stale_selection
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.CommentAcceptanceTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(guide_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/comments/1/guide-runs';self.headers={'Idempotency-Key':fixtures.KEY};self.body={'expected_content_version':7}

    def test_real_202_full_status_safe_source_and_frozen_replay(self):
        self.make_comment()
        with patch('backend.app.guide.commands.modify_from_comment',wraps=commands.modify_from_comment) as invoked:
            first=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202)
        invoked.assert_called_once();self.assertEqual(first['data']['source_type'],'COMMENT');self.assertEqual(first['data']['source_id'],1);self.assertEqual(first['data']['scope'],{'scope_type':'BLOCK','scope_ref':{'block_id':1}})
        self.assertNotIn('prompt_version',first['data']);self.assertNotIn('allowed_targets_json',first['data'])
        before=self.facts();again=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202)
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)

    def test_unknown_overrides_wrong_version_name_and_invalid_path_query_key_zero_app(self):
        self.make_comment();before=self.facts()
        cases=[(self.url+'?page=1',self.headers,self.body),('/api/v1/comments/01/guide-runs',self.headers,self.body),(self.url,{},self.body),
            (self.url,self.headers,{'expected_version':7}),(self.url,self.headers,{**self.body,'content':'override'}),(self.url,self.headers,{**self.body,'source_type':'USER_INSTRUCTION'}),
            (self.url,self.headers,{**self.body,'scope':{'scope_type':'DOCUMENT'}}),(self.url,self.headers,{'expected_content_version':True})]
        for url,headers,body in cases:
            with patch('backend.app.guide.commands.modify_from_comment',wraps=commands.modify_from_comment) as invoked:
                self.envelope(self.client.post(url,headers=headers,json=body),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_actual_relocation_refusal_returns_409_after_only_anchor_correction(self):
        self.stale_selection();old=self.row('comments',1);value=self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':9}),409)
        self.assertEqual(value['error']['code'],'COMMENT_ORPHANED');self.assertIsNone(value['error']['details']);self.assertEqual(self.row('comments',1),{**old,'anchor_status':'ORPHANED'})
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers,json={'expected_content_version':9}),409);self.assertEqual(self.facts(),before)
        with self.database.transaction() as connection: self.assertEqual(connection.execute("SELECT count(*) FROM idempotency_records WHERE capability_id='APP-GUIDE-CMD-C05'").fetchone()[0],0)

    def test_postcommit_response_mapping_failure_replays_persisted_run(self):
        self.make_comment()
        with patch('backend.app.guide.http_models.ModifyFromCommentResponse.project',side_effect=ValueError('private response map')):
            value=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),500)
        self.assertNotIn('private response map',str(value));self.assertEqual(self.row('requirements',101)['document_work_state'],'GUIDE_ACTIVE')
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202);self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
