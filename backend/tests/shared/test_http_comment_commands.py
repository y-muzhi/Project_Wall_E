"""I29-I33 actual native comment transactions through strict ASGI boundaries."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.comments.api import comment_router
from backend.app.comments import commands
from backend.app.comments.contracts import create_comment_input
from backend.app.infrastructure.idempotency import Scope
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.comments import test_commands as fixtures
from backend.tests.shared import test_http_commands as http_fixtures


class HttpCommentCommandTests(unittest.TestCase):
    facts=fixtures.CommentCommandTests.facts
    write_body=fixtures.CommentCommandTests.write_body
    create_payload=fixtures.CommentCommandTests.create_payload
    create=fixtures.CommentCommandTests.create
    row=fixtures.CommentCommandTests.row
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.CommentCommandTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(comment_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/requirements/101/comments';self.headers={'Idempotency-Key':fixtures.KEY}
        self.body={k:v for k,v in self.create_payload().items() if k not in ('requirement_id','idempotency_key')}

    def test_all_five_real_commands_correct_projection_and_replay_without_duplicate_or_late_overwrite(self):
        with patch('backend.app.comments.commands.create_comment',wraps=commands.create_comment) as invoked:
            created=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),201)
        invoked.assert_called_once();self.assertEqual(created['data']['id'],1);self.assertEqual(created['data']['content'],'说明😀\n第二行')
        for name,method,url,body in (('edit_comment','PATCH','/api/v1/comments/1',{'content':'changed'}),('resolve_comment','POST','/api/v1/comments/1/resolve',None),('reopen_comment','POST','/api/v1/comments/1/reopen',None),('delete_comment','DELETE','/api/v1/comments/1',None)):
            with patch('backend.app.comments.commands.'+name,wraps=getattr(commands,name)) as invoked:
                response=self.client.request(method,url,headers=self.headers,**({} if body is None else {'json':body}))
                value=self.envelope(response)
            invoked.assert_called_once();self.assertEqual(value['data']['id'],1);self.assertIn('anchor_ref',value['data']);self.assertNotIn('anchor_ref_json',value['data'])
            before=self.facts();replayed=self.envelope(self.client.request(method,url,headers=self.headers,**({} if body is None else {'json':body})))
            self.assertEqual(replayed['data'],value['data']);self.assertNotEqual(replayed['meta']['request_id'],value['meta']['request_id']);self.assertEqual(self.facts(),before)
        self.assertIsNotNone(self.row('comments',1)['deleted_at']);before=self.facts()
        self.assertEqual(self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),201)['data'],created['data']);self.assertEqual(self.facts(),before)

    def test_creation_and_action_input_structures_and_duplicate_json_reject_zero_app(self):
        before=self.facts()
        bodies=[{**self.body,'selection':{}},{**self.body,'expected_version':7},{**self.body,'block_id':True},{**self.body,'anchor_type':'SELECTION'},{**self.body,'content':None}]
        for body in bodies:
            with patch('backend.app.comments.commands.create_comment',wraps=commands.create_comment) as invoked:
                self.envelope(self.client.post(self.url,headers=self.headers,json=body),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.comments.commands.create_comment',wraps=commands.create_comment) as invoked:
            self.envelope(self.client.post(self.url,headers={**self.headers,'Content-Type':'application/json'},content='{"content":"a","content":"b"}'),422)
        invoked.assert_not_called()
        for method,url,body in (('PATCH','/api/v1/comments/01',{'content':'x'}),('PATCH','/api/v1/comments/1',{'content':'x','anchor_status':'ATTACHED'}),('POST','/api/v1/comments/1/resolve',{}),('DELETE','/api/v1/comments/1',{})):
            with patch('backend.app.comments.commands.edit_comment',wraps=commands.edit_comment) as edit,patch('backend.app.comments.commands.resolve_comment',wraps=commands.resolve_comment) as resolve,patch('backend.app.comments.commands.delete_comment',wraps=commands.delete_comment) as delete:
                self.envelope(self.client.request(method,url,headers=self.headers,json=body),422)
            edit.assert_not_called();resolve.assert_not_called();delete.assert_not_called();self.assertEqual(self.facts(),before)

    def test_version_and_anchor_invalid_use_registered_errors_without_new_facts(self):
        before=self.facts()
        for body,status in (({**self.body,'expected_content_version':6},409),({**self.body,'block_id':999},422)):
            self.envelope(self.client.post(self.url,headers=self.headers,json=body),status);self.assertEqual(self.facts(),before)
        self.envelope(self.client.patch('/api/v1/comments/999',headers=self.headers,json={'content':'x'}),404);self.assertEqual(self.facts(),before)

    def test_committed_creation_and_update_projection_failure_keeps_fact_and_same_key_replays(self):
        with patch('backend.app.comments.http_models.CreateCommentResponse.project',side_effect=ValueError('private comment projection')):
            self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),500)
        self.assertEqual(self.row('comments',1)['status'],'OPEN');before=self.facts()
        self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),201);self.assertEqual(self.facts(),before)
        with patch('backend.app.comments.http_models.EditCommentResponse.project',side_effect=ValueError('private update projection')):
            self.envelope(self.client.post('/api/v1/comments/1/resolve',headers=self.headers),500)
        self.assertEqual(self.row('comments',1)['status'],'RESOLVED');before=self.facts()
        self.envelope(self.client.post('/api/v1/comments/1/resolve',headers=self.headers));self.assertEqual(self.facts(),before)

    def test_sql_rollback_processing_and_mismatched_idempotency_have_safe_no_change_responses(self):
        claim=self.executor.claim(Scope('APP-COMMENT-CMD-C01','Requirement:101',fixtures.KEY),create_comment_input(self.create_payload()).business_input())
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),409);self.assertEqual(self.facts(),before);self.executor.abandon(claim)
        with self.database.transaction(write=True) as connection: connection.execute("CREATE TRIGGER comment_http_fault AFTER INSERT ON comments BEGIN SELECT RAISE(ABORT,'private storage error'); END")
        before=self.facts();value=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),503)
        self.assertNotIn('private storage error',str(value));self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DROP TRIGGER comment_http_fault')
        self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),201);before=self.facts()
        self.envelope(self.client.post(self.url,headers=self.headers,json={**self.body,'content':'changed input'}),409);self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
