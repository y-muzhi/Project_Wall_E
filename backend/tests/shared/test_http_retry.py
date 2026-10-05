"""I18 real failure/retry ASGI with empty body and safe complete status."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.guide.api import guide_router
from backend.app.guide import commands
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.guide import test_retry as fixtures
from backend.tests.shared import test_http_commands as http_fixtures


class HttpRetryTests(unittest.TestCase):
    facts=fixtures.RetryTests.facts
    payload=fixtures.RetryTests.payload
    create=fixtures.RetryTests.create
    row=fixtures.RetryTests.row
    fail_run=fixtures.RetryTests.fail_run
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.RetryTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(guide_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url=f'/api/v1/guide-runs/{self.failed}/retry';self.headers={'Idempotency-Key':fixtures.KEY}

    def test_real_202_new_run_full_status_old_failed_and_message_preserved_replay(self):
        old=self.row('guide_runs',self.failed);message=self.row('conversation_messages',old['trigger_message_id'])
        with patch('backend.app.guide.commands.retry_guide_run',wraps=commands.retry_guide_run) as invoked:
            first=self.envelope(self.client.post(self.url,headers=self.headers),202)
        invoked.assert_called_once();self.assertNotEqual(first['data']['id'],self.failed);self.assertEqual(first['data']['retry_of_guide_run_id'],self.failed);self.assertIsNone(first['data']['final_result'])
        self.assertEqual(self.row('guide_runs',self.failed),old);self.assertEqual(self.row('conversation_messages',message['id']),message)
        before=self.facts();again=self.envelope(self.client.post(self.url,headers=self.headers),202)
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)

    def test_body_query_duplicate_key_and_invalid_path_rejected_zero_app(self):
        before=self.facts()
        inputs=[(self.url+'?expected_version=1',self.headers,None),('/api/v1/guide-runs/01/retry',self.headers,None),(self.url,{},None),(self.url,self.headers,'{}'),
            (self.url,[('Idempotency-Key',fixtures.KEY),('Idempotency-Key',fixtures.OTHER)],None)]
        for url,headers,body in inputs:
            with patch('backend.app.guide.commands.retry_guide_run',wraps=commands.retry_guide_run) as invoked:
                self.envelope(self.client.post(url,headers=headers,content=body),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_nonfailed_state_and_actual_sql_error_are_safe_no_partial_retry(self):
        with self.database.transaction(write=True) as connection: connection.execute("UPDATE guide_runs SET status='RUNNING',current_step='PREPARING',ended_at=NULL,error_code=NULL,error_message=NULL WHERE id=?",(self.failed,))
        before=self.facts();value=self.envelope(self.client.post(self.url,headers=self.headers),409);self.assertEqual(value['error']['code'],'STATE_CONFLICT');self.assertEqual(self.facts(),before)
        self.fail_run(self.failed)
        with self.database.transaction(write=True) as connection: connection.execute("CREATE TRIGGER http_retry_fault AFTER INSERT ON guide_runs BEGIN SELECT RAISE(ABORT,'private SQL retry'); END")
        before=self.facts();value=self.envelope(self.client.post(self.url,headers=self.headers),503);self.assertNotIn('private SQL retry',str(value));self.assertEqual(self.facts(),before)

    def test_postcommit_status_projection_failure_keeps_new_run_and_replays(self):
        with patch('backend.app.guide.http_models.RetryGuideRunResponse.project',side_effect=ValueError('private map')):
            value=self.envelope(self.client.post(self.url,headers=self.headers),500)
        self.assertNotIn('private map',str(value));self.assertEqual(self.row('requirements',self.req)['document_work_state'],'GUIDE_ACTIVE')
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers),202);self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
