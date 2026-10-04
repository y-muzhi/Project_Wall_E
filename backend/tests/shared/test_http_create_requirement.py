"""I02 actual empty database acceptance and original result replay."""
import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.requirements.api import req_router
from backend.app.requirements import commands
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.requirements import test_create_requirement as fixtures
from backend.tests.shared import test_http_commands as http_fixtures


class HttpCreateRequirementTests(unittest.TestCase):
    payload=fixtures.CreateRequirementTests.payload
    facts=fixtures.CreateRequirementTests.facts
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.CreateRequirementTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(req_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)

    def body(self,**changes):
        return {k:v for k,v in self.payload(**changes).items() if k!='idempotency_key'}

    def post(self,body=None,*,status=201,key=fixtures.KEY):
        return self.envelope(self.client.post('/api/v1/requirements',content=json.dumps(self.body() if body is None else body,ensure_ascii=True),headers={'Idempotency-Key':key,'Content-Type':'application/json'}),status)

    def test_create_calls_app_once_projects_only_accepted_resources_and_replays_new_request_id(self):
        with patch('backend.app.requirements.commands.create_requirement',wraps=commands.create_requirement) as invoked:
            result=self.post()
        invoked.assert_called_once();self.assertEqual(set(result['data']),{'requirement','current_document_id','guide_run_id'})
        root=result['data']['requirement'];self.assertEqual(root['title'],'需求😀');self.assertNotIn('initial_idea',root)
        before=self.facts();replay=self.post(self.body(title='需求😀',initial_idea='first\nsecond'))
        self.assertEqual(replay['data'],result['data']);self.assertNotEqual(replay['meta']['request_id'],result['meta']['request_id']);self.assertEqual(self.facts(),before)
        conflict=self.post(self.body(initial_idea='different'),status=409);self.assertEqual(conflict['error']['code'],'IDEMPOTENCY_CONFLICT');self.assertEqual(self.facts(),before)

    def test_missing_fields_wrong_types_unknowns_headers_and_duplicate_keys_are_zero_app(self):
        before=self.facts()
        for body in ({},{'title':'x'},self.body(initialization_mode=None),self.body(requirement_id=1),self.body(initial_idea='\ud800')):
            with patch('backend.app.requirements.commands.create_requirement',wraps=commands.create_requirement) as invoked:
                self.post(body,status=422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.requirements.commands.create_requirement',wraps=commands.create_requirement) as invoked:
            self.envelope(self.client.post('/api/v1/requirements',json=self.body()),422)
            duplicate=json.dumps(self.body(),ensure_ascii=True)[:-1]+',"title":"duplicate"}'
            self.envelope(self.client.post('/api/v1/requirements',content=duplicate,headers={'Content-Type':'application/json','Idempotency-Key':fixtures.KEY}),422)
        invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_actual_template_mismatch_returns_422_without_accepted_resources(self):
        before=self.facts();value=self.post(self.body(requirement_type='CHANGE'),status=422)
        self.assertEqual(value['error']['code'],'TEMPLATE_INVALID');self.assertEqual(self.facts(),before)

    def test_actual_commit_before_projection_failure_still_replays_original_acceptance(self):
        with patch('backend.app.requirements.http_models.CreateRequirementResponse.project',side_effect=ValueError('after commit')):
            self.post(status=500)
        before=self.facts();result=self.post();self.assertEqual(result['data']['requirement']['id'],1);self.assertEqual(self.facts(),before)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],0)


if __name__=='__main__': unittest.main()
