"""I35 exact ASGI window/cursor and degraded historical card presentation."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.messages.api import message_router
from backend.app.messages import queries
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.messages import test_queries as fixtures
from backend.tests.shared import test_http_reads as http_fixtures


class HttpMessagesTests(unittest.TestCase):
    facts=fixtures.MessageQueryTests.facts
    payload=fixtures.MessageQueryTests.payload
    create=fixtures.MessageQueryTests.create
    row=fixtures.MessageQueryTests.row
    text_fixture=fixtures.MessageQueryTests.text_fixture
    message_fixture=fixtures.MessageQueryTests.message_fixture
    initialize_cards_fixture=fixtures.MessageQueryTests.initialize_cards_fixture
    envelope=http_fixtures.HttpReadTests.envelope

    def setUp(self):
        fixtures.MessageQueryTests.setUp(self)
        self.app=FastAPI(redirect_slashes=False);self.app.include_router(message_router)
        self.app.state.walle_runtime=HttpRuntime(self.database,self.catalog)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.url='/api/v1/requirements/'+str(self.req)+'/messages'

    def test_latest_twenty_cursor_meta_only_items_data_and_fresh_request_identity(self):
        for identity in range(101,125): self.text_fixture(identity)
        before=self.facts()
        with patch('backend.app.messages.queries.list_messages',wraps=queries.list_messages) as invoked: first=self.envelope(self.client.get(self.url))
        invoked.assert_called_once();self.assertEqual(set(first['data']),{'items'});self.assertEqual(first['meta']['pagination'],{'page_size':20,'has_more':True,'next_cursor':6})
        self.assertEqual([item['sequence_no'] for item in first['data']['items']],list(range(6,26)))
        tail=self.envelope(self.client.get(self.url+'?before_sequence_no=6'));self.assertEqual(tail['meta']['pagination'],{'page_size':20,'has_more':False,'next_cursor':None})
        self.assertNotIn('total',str(first['meta']));self.assertEqual(self.facts(),before)
        again=self.envelope(self.client.get(self.url));self.assertNotEqual(first['meta']['request_id'],again['meta']['request_id']);self.assertEqual(self.facts(),before)

    def test_strict_paths_duplicate_cursor_bounds_queries_body_zero_app_and_missing_root(self):
        before=self.facts()
        for url in ('/api/v1/requirements/01/messages',self.url+'?before_sequence_no=0',self.url+'?before_sequence_no=null',self.url+'?before_sequence_no=01',self.url+'?before_sequence_no=1&before_sequence_no=2',self.url+'?before_sequence_no=9007199254740992',self.url+'?page=1'):
            with patch('backend.app.messages.queries.list_messages',wraps=queries.list_messages) as invoked: self.envelope(self.client.get(url),422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.messages.queries.list_messages',wraps=queries.list_messages) as invoked: self.envelope(self.client.request('GET',self.url,content='{}'),422)
        invoked.assert_not_called();self.envelope(self.client.get('/api/v1/requirements/999/messages'),404);self.assertEqual(self.facts(),before)

    def test_card_state_structure_and_damaged_history_degrade_without_original_json_or_mutation(self):
        self.initialize_cards_fixture();self.message_fixture(12,structured={'private':'sensitive raw marker'})
        before=self.facts();value=self.envelope(self.client.get(self.url));card,bad=value['data']['items'][-2:]
        self.assertEqual(card['card_state'],'EXPIRED');self.assertEqual(card['structured_content']['schema_version'],1)
        self.assertIsNone(bad['structured_content']);self.assertIsNone(bad['card_state']);self.assertEqual(bad['content'],'Readable historical content 😀')
        self.assertNotIn('sensitive raw marker',str(value));self.assertNotIn('structured_content_json',str(value));self.assertEqual(self.facts(),before)

    def test_public_projection_rejects_invented_cursor_or_malformed_card_schema_after_actual_read(self):
        self.initialize_cards_fixture();before=self.facts();original=queries.list_messages
        def damaged_cursor(*args,**kwargs):
            result=original(*args,**kwargs);result['data']['next_cursor']=1;return result
        with patch('backend.app.messages.queries.list_messages',side_effect=damaged_cursor): self.envelope(self.client.get(self.url),500)
        def damaged_cards(*args,**kwargs):
            result=original(*args,**kwargs);result['data']['items'][-1]['structured_content']['private']='sensitive marker';return result
        with patch('backend.app.messages.queries.list_messages',side_effect=damaged_cards): value=self.envelope(self.client.get(self.url),500)
        self.assertNotIn('sensitive marker',str(value));self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
