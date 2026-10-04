"""I12 real ASGI completion and durable success after response projection failure."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch
from backend.app.documents import commands
from backend.tests.shared import test_http_commands as fixtures
from backend.tests.shared.test_http_commands import BASE, KEY, OTHER


class HttpCompleteDraftTests(unittest.TestCase):
    facts=fixtures.HttpCommandTests.facts
    envelope=fixtures.HttpCommandTests.envelope
    command=fixtures.HttpCommandTests.command
    draft=fixtures.HttpCommandTests.draft
    save_body=fixtures.HttpCommandTests.save_body

    def setUp(self):
        fixtures.HttpCommandTests.setUp(self)
        self.addCleanup(fixtures.HttpCommandTests.tearDown,self)

    def test_expected_version_is_saved_draft_and_result_is_same_current(self):
        draft=self.draft()
        saved=self.command('PUT',BASE+'/manual-draft',self.save_body())['data']
        before=self.facts()
        failed=self.command('POST',BASE+'/manual-draft/complete',{'expected_version':draft['content_version']},status=409)
        self.assertEqual(failed['error']['code'],'CONTENT_VERSION_CONFLICT');self.assertEqual(self.facts(),before)
        with patch('backend.app.documents.commands.complete_manual_draft',wraps=commands.complete_manual_draft) as invoked:
            complete=self.command('POST',BASE+'/manual-draft/complete',{'expected_version':saved['content_version']})
        self.assertEqual(invoked.call_count,1)
        self.assertEqual((complete['data']['id'],complete['data']['document_type'],complete['data']['content_version']),(201,'CURRENT',8))
        self.assertEqual(complete['data']['markdown_content'],saved['markdown_content'])
        self.envelope(self.client.get(BASE+'/manual-draft'),404)
        before=self.facts();replayed=self.command('POST',BASE+'/manual-draft/complete',{'expected_version':saved['content_version']})
        self.assertEqual(replayed['data'],complete['data']);self.assertNotEqual(replayed['meta']['request_id'],complete['meta']['request_id']);self.assertEqual(self.facts(),before)

    def test_boundary_rejects_before_app_and_absent_activity_is_conflict(self):
        before=self.facts()
        for body in ({},{'expected_version':True},{'expected_version':1,'reason':'user input'},{'expected_content_version':1}):
            with patch('backend.app.documents.commands.complete_manual_draft',wraps=commands.complete_manual_draft) as invoked:
                self.command('POST',BASE+'/manual-draft/complete',body,status=422)
            invoked.assert_not_called();self.assertEqual(self.facts(),before)
        with patch('backend.app.documents.commands.complete_manual_draft',wraps=commands.complete_manual_draft) as invoked:
            self.envelope(self.client.post(BASE+'/manual-draft/complete',json={'expected_version':1}),422)
        invoked.assert_not_called();self.assertEqual(self.facts(),before)
        self.command('POST',BASE+'/manual-draft/complete',{'expected_version':1})
        failed=self.command('POST',BASE+'/manual-draft/complete',{'expected_version':1},key=OTHER,status=409)
        self.assertEqual(failed['error']['code'],'WORK_STATE_CONFLICT')

    def test_real_commit_projection_failure_replays_without_second_adoption(self):
        with patch('backend.app.documents.http_models.CompleteManualDraftResponse.project',side_effect=ValueError('projection after real commit')):
            self.command('POST',BASE+'/manual-draft/complete',{'expected_version':1},status=500)
        before=self.facts();result=self.command('POST',BASE+'/manual-draft/complete',{'expected_version':1})
        self.assertEqual(result['data']['content_version'],8);self.assertEqual(self.facts(),before)
        new=self.command('POST',BASE+'/manual-draft',{'expected_version':8},key=OTHER,status=201)['data']['manual_draft']
        before=self.facts();self.command('POST',BASE+'/manual-draft/complete',{'expected_version':1})
        self.assertEqual(self.facts(),before);self.assertEqual(self.draft()['id'],new['id'])

    def test_sql_failure_returns_safe_503_and_preserves_draft_and_current(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER i12_fault AFTER UPDATE ON requirement_documents WHEN NEW.document_type='CURRENT' BEGIN SELECT RAISE(ABORT,'private diagnostic SQL'); END");connection.commit()
        before=self.facts();result=self.command('POST',BASE+'/manual-draft/complete',{'expected_version':1},status=503)
        self.assertEqual(result['error']['code'],'STORAGE_UNAVAILABLE');self.assertNotIn('private diagnostic',str(result));self.assertEqual(self.facts(),before)


if __name__=='__main__': unittest.main()
