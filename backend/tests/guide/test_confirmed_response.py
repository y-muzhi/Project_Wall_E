"""Offline C06 confirmation transactions against temporary SQLite only."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch as mock_patch

from backend.app.guide.confirmed_response import confirmation_patch, QUESTION_END
from backend.app.guide.output_evidence import fact_declaration
from backend.app.guide.queries import get_guide_run
from backend.app.documents.patch_validation import validate_patch
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.documents.tables import table_model
from backend.app.infrastructure.resources import ResourceCatalog
from backend.tests.guide import test_cards as submissions
from backend.tests.documents.test_patch_validation import patch
from backend.tests.messages.test_queries import cards_fixture


class ConfirmedResponseTests(unittest.TestCase):
    def setUp(self):
        self.f = submissions.CardSubmissionTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.catalog = ResourceCatalog()

    def snapshot(self):
        with self.f.database.transaction() as connection:
            current = self.f.row('requirement_documents', self.f.created['current_document_id'])
            snapshot = validate_snapshot(current['markdown_content'], json.loads(current['block_state_json']), DocumentSources(connection, self.f.req, self.f.catalog))
        return snapshot, resolve_scope(snapshot, 'INITIALIZE', 'DOCUMENT')

    def card(self, identity=3, operation='REPLACE_BLOCK'):
        snapshot, scope = self.snapshot()
        value = patch(snapshot, identity, operation, None if operation == 'DELETE_BLOCK' else '已确认的新正文。\n')
        card = cards_fixture()['cards'][0]
        card.update(card_type='CONFIRM', question=fact_declaration(snapshot, validate_patch(snapshot, value, scope)) + QUESTION_END,
            options=[{'option_key': key, 'label': label, 'description': '', 'impact': '', 'risks': ''} for key, label in [('confirm', '确认以上事实和变更'), ('defer', '尚未确认')]],
            custom_answer={'enabled': False, 'max_length': 0}, recommendation=None,
            related_spec_context=[{'block_id': identity, 'content_snapshot': snapshot.by_id[identity][0].markdown}])
        return card

    def submit(self, cards=None, choice='confirm'):
        if cards is None: cards = [self.card()]
        self.f.initialize_cards_fixture(structured={'schema_version': 1, 'intro': '确认', 'cards': cards})
        with mock_patch('socket.socket.connect', side_effect=AssertionError('No model call')):
            return self.f.submit(responses=[{'card_key': c['card_key'], 'selected_option_keys': [choice], 'custom_answer': None, 'skipped': False} for c in cards])

    def test_confirm_applies_once_finishes_and_releases_without_llm(self):
        result = self.submit(); self.assertEqual(result['code'], 'CARDS_ACCEPTED', result)
        run = result['data']['guide_run']; self.assertEqual((run['status'], run['current_step']), ('COMPLETED', 'FINISHED'))
        from types import SimpleNamespace
        from backend.app.messages.http_models import SubmitCardResponsesResponse
        projected, _ = SubmitCardResponsesResponse.project(result['data'], SimpleNamespace(payload={'message_id': 11, **result['data']['response_message']['structured_content']}))
        self.assertEqual(projected['guide_run']['status'], 'COMPLETED')
        current = self.f.row('requirement_documents', self.f.created['current_document_id'])
        self.assertEqual(current['content_version'], 2); self.assertIn('已确认的新正文。', current['markdown_content'])
        self.assertEqual(self.f.row('requirements', self.f.req)['document_work_state'], 'IDLE')
        self.assertEqual(get_guide_run(self.f.database, run['id'], catalog=self.f.catalog)['code'], 'READ_OK')
        answers = result['data']['response_message']['structured_content']['responses']
        before = self.f.facts(); self.assertEqual(self.f.submit(responses=answers), result); self.assertEqual(self.f.facts(), before)
        self.assertEqual(self.f.submit(responses=answers, idempotency_key=submissions.OTHER)['code'], 'CARD_ALREADY_ANSWERED')
        with self.f.database.transaction() as connection: self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0], 0)

    def test_defer_preserves_document_and_finishes_without_call(self):
        result = self.submit(choice='defer'); self.assertEqual(result['data']['guide_run']['status'], 'COMPLETED')
        self.assertEqual(self.f.row('requirement_documents', self.f.created['current_document_id'])['content_version'], 1)

    def test_bad_original_is_saved_and_explained_without_write_or_call(self):
        card = self.card(); card['related_spec_context'][0]['content_snapshot'] = '错误原文'
        result = self.submit([card]); self.assertEqual(result['code'], 'CARDS_ACCEPTED', result)
        run = get_guide_run(self.f.database, result['data']['guide_run']['id'], catalog=self.f.catalog)['data']
        self.assertIn('未写入文档', self.f.row('conversation_messages', run['latest_assistant_message_id'])['content'])
        self.assertEqual(self.f.row('requirement_documents', self.f.created['current_document_id'])['content_version'], 1)

    def test_conflicting_bundle_and_locked_heading_never_partial_apply(self):
        for cards in ([self.card(), {**self.card(), 'card_key': 'second'}], [self.card(identity=1)]):
            with self.subTest(cards=len(cards)):
                f = submissions.CardSubmissionTests(); f.setUp(); self.addCleanup(f.doCleanups); f.catalog = ResourceCatalog()
                old = self.f; self.f = f
                try:
                    result = self.submit(cards); self.assertEqual(result['data']['guide_run']['status'], 'COMPLETED', result)
                    self.assertEqual(self.f.row('requirement_documents', self.f.created['current_document_id'])['content_version'], 1)
                finally: self.f = old

    def test_all_block_operations_roundtrip_complete_declaration(self):
        for operation in ('REPLACE_BLOCK', 'INSERT_BEFORE', 'INSERT_AFTER', 'DELETE_BLOCK'):
            snapshot, scope = self.snapshot(); value = confirmation_patch(self.card(operation=operation), snapshot, scope)
            self.assertEqual(value['patch_operation'], operation)

    def test_real_full_template_table_row_canonical_and_compact_are_applied(self):
        for compact in (False, True):
            f = submissions.CardSubmissionTests()
            submissions.creation.CreateRequirementTests.setUp(f); self.addCleanup(f.doCleanups)
            f.catalog = ResourceCatalog(); f.created = f.create(template_version='v2')['data']
            f.req = f.created['requirement']['id']; f.run = f.created['guide_run_id']; f.at = '2026-10-04T08:00:00.000Z'
            old = self.f; self.f = f
            try:
                snapshot, scope = self.snapshot(); block = snapshot.by_id[8][0]
                table = table_model(block); row = next(row for row in table.rows if row.cells[0] == '本版本包含')
                value = patch(snapshot, 8, 'REPLACE_TABLE_ROW', None, {'key_column_index': 0, 'key_value': '本版本包含'}, {'cells': ['本版本包含', '多轮问答产出规格草稿与澄清记录。']}, row.markdown)
                card = self.card(); card['related_spec_context'] = [{'block_id': 8, 'content_snapshot': block.markdown}]
                card['question'] = fact_declaration(snapshot, validate_patch(snapshot, value, scope)) + QUESTION_END
                if compact:
                    card['question'] = card['question'].replace('原表格：\n', '原表格：').replace(block.markdown + '\n行选择：', block.markdown + '行选择：').replace('\n原文：\n' + row.markdown, '').replace('确认的新正文：\n', '确认的新正文：')
                    # Provider misquoted an unrelated placeholder in the actual incident.
                    card['question'] = card['question'].replace('用户或数据隔离', '用户数据隔离')
                    card['related_spec_context'][0]['content_snapshot'] = block.markdown.replace('用户或数据隔离', '用户数据隔离')
                result = self.submit([card]); self.assertEqual(result['data']['guide_run']['status'], 'COMPLETED', result)
                current = self.f.row('requirement_documents', f.created['current_document_id'])
                self.assertEqual(current['content_version'], 2)
                self.assertIn('多轮问答产出规格草稿与澄清记录。', current['markdown_content'])
                self.assertIn('用户或数据隔离', current['markdown_content'])
            finally: self.f = old

    def test_completed_confirmation_is_not_dispatched(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import Mock
        from backend.app.guide.worker import GuideWorker
        dispatcher = SimpleNamespace(dispatch=Mock(), events=[])
        result = self.submit()
        asyncio.run(GuideWorker.after_commit(dispatcher, result))
        dispatcher.dispatch.assert_not_called()

    def test_document_write_fault_rolls_back_answer_run_and_document(self):
        self.f.initialize_cards_fixture(structured={'schema_version': 1, 'intro': '确认', 'cards': [self.card()]})
        with self.f.database.transaction(write=True) as connection:
            connection.execute("CREATE TRIGGER reject_confirm AFTER UPDATE ON requirement_documents BEGIN SELECT RAISE(ABORT,'write fault'); END")
        before = self.f.facts()
        result = self.f.submit(responses=[{'card_key': 'first', 'selected_option_keys': ['confirm'], 'custom_answer': None, 'skipped': False}])
        self.assertEqual(result['code'], 'STORAGE_UNAVAILABLE', result)
        self.assertEqual(self.f.facts(), before)
