"""I17 real cancellation through ASGI; strict no-body input and replay."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.guide.api import guide_router
from backend.app.guide import commands
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.guide import test_cancel as fixtures
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.shared import test_http_commands as http_fixtures


class HttpGuideCancelTests(unittest.TestCase):
    facts=fixtures.CancelTests.facts
    payload=fixtures.CancelTests.payload
    create=fixtures.CancelTests.create
    row=fixtures.CancelTests.row
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.CancelTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(guide_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/guide-runs/'+str(self.run)+'/cancel'
        self.headers={'Idempotency-Key':creation.OTHER}

    def test_real_cancellation_and_replay_project_four_fields_with_fresh_request_ids(self):
        with patch('backend.app.guide.commands.cancel_guide_run',wraps=commands.cancel_guide_run) as invoked:
            first=self.envelope(self.client.post(self.url,headers=self.headers))
        invoked.assert_called_once();self.assertEqual(first['data'],{'id':self.run,'requirement_id':self.req,'status':'CANCELLED','current_step':'FINISHED'})
        before=self.facts();again=self.envelope(self.client.post(self.url,headers=self.headers))
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)
        self.assertEqual(self.row('requirements',self.req)['document_work_state'],'IDLE')

    def test_invalid_path_query_key_and_nonempty_body_reject_before_app(self):
        before=self.facts()
        inputs=[(self.url+'?reason=USER_REQUESTED',self.headers,None),('/api/v1/guide-runs/01/cancel',self.headers,None),(self.url,{},None),(self.url,{'Idempotency-Key':'invalid'},None),(self.url,[('Idempotency-Key',creation.KEY),('Idempotency-Key',creation.OTHER)],None),(self.url,self.headers,'{}')]
        for url,headers,body in inputs:
            with patch('backend.app.guide.commands.cancel_guide_run',wraps=commands.cancel_guide_run) as invoked:
                self.envelope(self.client.post(url,headers=headers,content=body),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        self.envelope(self.client.post('/api/v1/guide-runs/999/cancel',headers=self.headers),404);self.assertEqual(self.facts(),before)

    def test_persisting_conflict_and_actual_sql_failure_are_safe_no_mutation(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET current_step='PERSISTING' WHERE id=?",(self.run,))
        before=self.facts();self.envelope(self.client.post(self.url,headers=self.headers),409);self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET current_step='PREPARING' WHERE id=?",(self.run,))
            connection.execute("CREATE TRIGGER cancel_http_fault AFTER UPDATE ON requirements BEGIN SELECT RAISE(ABORT,'private database failure'); END")
        before=self.facts();value=self.envelope(self.client.post(self.url,headers=self.headers),503)
        self.assertNotIn('private database failure',str(value));self.assertEqual(self.facts(),before)

    def test_postcommit_projection_failure_keeps_fact_and_same_key_replays(self):
        with patch('backend.app.guide.http_models.CancelGuideRunResponse.project',side_effect=ValueError('private map exception')):
            value=self.envelope(self.client.post(self.url,headers=self.headers),500)
        self.assertNotIn('private map exception',str(value));self.assertEqual(self.row('guide_runs',self.run)['status'],'CANCELLED')
        before=self.facts();self.assertEqual(self.envelope(self.client.post(self.url,headers=self.headers))['data']['status'],'CANCELLED');self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
