"""Approved initialization locks also protect intermediate draft saves."""
import unittest
from backend.tests.documents import test_commands as fixtures
from backend.tests.documents import test_save_manual_draft as save_fixtures
from backend.app.documents.snapshot import Provenance, assign_identities, validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.shared.time import utc_milliseconds


class SaveTemplateLockTests(unittest.TestCase):
    start_payload = fixtures.DraftCommandTests.start_payload
    start = fixtures.DraftCommandTests.start
    facts = fixtures.DraftCommandTests.facts
    payload = save_fixtures.SaveManualDraftTests.payload
    save = save_fixtures.SaveManualDraftTests.save

    def setUp(self):
        fixtures.DraftCommandTests.setUp(self)
        self.draft = self.start()['data']['manual_draft']
        self.assertEqual(self.start()['data']['requirement']['status'], 'INITIALIZING')

    def tearDown(self):
        fixtures.DraftCommandTests.tearDown(self)

    def candidate(self, markdown, ids=None, next_id=None):
        with self.database.transaction() as connection:
            sources = DocumentSources(connection, 101, self.catalog)
            prior = validate_snapshot(self.draft['markdown_content'], self.draft['block_state_json'], sources)
            candidate = assign_identities(markdown, list(prior.by_id) if ids is None else ids, prior.next_block_id if next_id is None else next_id, prior, Provenance('USER', 'MANUAL_EDIT', self.draft['id']), utc_milliseconds(fixtures.INSTANT), sources)
        return {**self.payload(), 'markdown_content': candidate.parsed.markdown, 'block_state_json': candidate.state}

    def test_renaming_or_changing_level_of_locked_heading_rejects_without_any_write(self):
        for replacement in ('# 错误标题', '## 需求新增规格'):
            with self.subTest(replacement=replacement):
                payload = self.candidate(self.draft['markdown_content'].replace('# 需求新增规格', replacement, 1))
                before = self.facts()
                self.assertEqual(self.save(payload)['code'], 'DOCUMENT_INVALID')
                self.assertEqual(self.facts(), before)

    def test_deleting_locked_heading_and_allocating_new_body_rolls_back_allocation_proofs(self):
        state = self.draft['block_state_json']
        ids = [block['block_id'] for block in state['blocks']][1:] + [state['next_block_id']]
        markdown = self.draft['markdown_content'].replace('# 需求新增规格\n\n', '', 1)+'\n\n新正文\n'
        payload = self.candidate(markdown, ids, state['next_block_id']+1)
        before = self.facts()
        self.assertEqual(self.save(payload)['code'], 'DOCUMENT_INVALID')
        self.assertEqual(self.facts(), before)

    def test_editing_body_under_locked_headings_is_accepted(self):
        payload = self.candidate(self.draft['markdown_content'].replace('待确认', '补充真实用户内容', 1))
        result = self.save(payload)
        self.assertEqual(result['code'], 'DRAFT_SAVED', result)
        self.assertEqual(result['data']['content_version'], 2)
        self.assertIn('补充真实用户内容', result['data']['markdown_content'])


if __name__ == '__main__':
    unittest.main()
