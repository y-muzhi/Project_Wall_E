"""I36 real file SQLite and 202 acceptance, guarded response error details."""
import json
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.messages.api import message_router
from backend.app.guide import commands
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.guide import test_cards as fixtures
from backend.tests.shared import test_http_commands as http_fixtures


class HttpCardTests(unittest.TestCase):
    facts=fixtures.CardSubmissionTests.facts
    payload=fixtures.CardSubmissionTests.payload
    create=fixtures.CardSubmissionTests.create
    row=fixtures.CardSubmissionTests.row
    read=fixtures.CardSubmissionTests.read
    message_fixture=fixtures.CardSubmissionTests.message_fixture
    initialize_cards_fixture=fixtures.CardSubmissionTests.initialize_cards_fixture
    waiting_cards_fixture=fixtures.CardSubmissionTests.waiting_cards_fixture
    answers=fixtures.CardSubmissionTests.answers
    envelope=http_fixtures.HttpCommandTests.envelope

    def setUp(self):
        fixtures.CardSubmissionTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(message_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog,self.executor)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/conversation-messages/11/responses';self.headers={'Idempotency-Key':fixtures.KEY}
        self.body={key:value for key,value in self.answers().items() if key not in ('message_id','idempotency_key')}

    def test_real_formal_response_202_replay_and_new_key_safe_existing_reference(self):
        self.initialize_cards_fixture()
        with patch('backend.app.guide.commands.submit_card_responses',wraps=commands.submit_card_responses) as invoked:
            first=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202)
        invoked.assert_called_once();self.assertEqual(first['data']['card_state'],'ANSWERED');self.assertEqual(set(first['data']),{'response_message','guide_run','card_state'})
        before=self.facts();again=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202)
        self.assertEqual(first['data'],again['data']);self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)
        conflict=self.envelope(self.client.post(self.url,headers={'Idempotency-Key':fixtures.OTHER},json=self.body),409)
        self.assertEqual(conflict['error']['code'],'CARD_ALREADY_ANSWERED');self.assertEqual(conflict['error']['details'],{'response_message_id':first['data']['response_message']['id']});self.assertEqual(self.facts(),before)

    def test_invalid_nested_unknown_duplicate_keys_version_path_and_query_zero_app(self):
        self.initialize_cards_fixture();before=self.facts()
        cases=[(self.url+'?page=1',self.headers,self.body),('/api/v1/conversation-messages/01/responses',self.headers,self.body),
            (self.url,{},self.body),(self.url,self.headers,{**self.body,'schema_version':True}),(self.url,self.headers,{**self.body,'instruction':'bad'}),
            (self.url,self.headers,{**self.body,'responses':[{**self.body['responses'][0],'source_id':1}]}),
            (self.url,self.headers,{**self.body,'responses':[{**self.body['responses'][0],'custom_answer':'\ud800'}]})]
        for url,headers,body in cases:
            with patch('backend.app.guide.commands.submit_card_responses',wraps=commands.submit_card_responses) as invoked:
                self.envelope(self.client.post(url,headers={**headers,'Content-Type':'application/json'},content=json.dumps(body,ensure_ascii=True)),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        duplicate='{"schema_version":1,"responses":[{"card_key":"first","card_key":"first","selected_option_keys":["b"],"custom_answer":null,"skipped":false}]}'
        with patch('backend.app.guide.commands.submit_card_responses',wraps=commands.submit_card_responses) as invoked:
            self.envelope(self.client.post(self.url,headers={**self.headers,'Content-Type':'application/json'},content=duplicate),422)
        invoked.assert_not_called();self.assertEqual(self.facts(),before)

    def test_real_whole_group_semantic_rejection_returns_fields_without_partial_answer(self):
        self.initialize_cards_fixture();before=self.facts()
        body={**self.body,'responses':[{**self.body['responses'][0],'selected_option_keys':['foreign']}]}
        value=self.envelope(self.client.post(self.url,headers=self.headers,json=body),422)
        self.assertEqual(value['error']['code'],'VALIDATION_FAILED');self.assertEqual(value['error']['details']['field_errors'][0]['field'],'responses');self.assertEqual(self.facts(),before)
        value=self.envelope(self.client.post('/api/v1/conversation-messages/1/responses',headers=self.headers,json=self.body),422)
        self.assertEqual(value['error']['code'],'SOURCE_INVALID');self.assertEqual(self.facts(),before)

    def test_real_waiting_answer_same_run_and_postcommit_mapping_failure_replays(self):
        self.waiting_cards_fixture()
        with patch('backend.app.messages.http_models.SubmitCardResponsesResponse.project',side_effect=ValueError('private map failure')):
            value=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),500)
        self.assertNotIn('private map failure',str(value));self.assertEqual(self.row('guide_runs',2)['status'],'RUNNING')
        before=self.facts();value=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),202)
        self.assertEqual(value['data']['guide_run']['id'],2);self.assertEqual(self.facts(),before)

    def test_malformed_actual_source_and_sql_failure_keep_storage_unchanged_and_hide_details(self):
        self.initialize_cards_fixture()
        with self.database.transaction(write=True) as connection: connection.execute("CREATE TRIGGER http_cards_fault AFTER INSERT ON conversation_messages BEGIN SELECT RAISE(ABORT,'private formal failure'); END")
        before=self.facts();value=self.envelope(self.client.post(self.url,headers=self.headers,json=self.body),503);self.assertNotIn('private formal failure',str(value));self.assertEqual(self.facts(),before)
        with self.database.transaction(write=True) as connection: connection.execute('DROP TRIGGER http_cards_fault')
        self.message_fixture(12,structured='{"schema_version":1,"private":"bad raw"}')
        before=self.facts();value=self.envelope(self.client.post('/api/v1/conversation-messages/12/responses',headers=self.headers,json=self.body),422)
        self.assertEqual(value['error']['code'],'SOURCE_INVALID');self.assertNotIn('bad raw',str(value));self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
