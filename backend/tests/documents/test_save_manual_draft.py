"""Actual SQLite saves and successful-allocation proofs; no simulated save API."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
import unittest
from unittest.mock import patch

from backend.app.documents.commands import save_manual_draft, cancel_manual_draft
from backend.app.documents.commands import start_manual_draft
from backend.app.documents.queries import get_manual_draft
from backend.app.documents.snapshot import Provenance, assign_identities, validate_snapshot, create_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import CommitOutcomeUnknown
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.documents import test_commands as draft_fixtures
from backend.tests.documents.test_commands import INSTANT, LATER, KEY
from backend.tests.infrastructure.test_database import insert_requirement


class SaveManualDraftTests(unittest.TestCase):
    start_payload = draft_fixtures.DraftCommandTests.start_payload
    start = draft_fixtures.DraftCommandTests.start
    facts = draft_fixtures.DraftCommandTests.facts
    current_facts = draft_fixtures.DraftCommandTests.current_facts

    def setUp(self):
        draft_fixtures.DraftCommandTests.setUp(self)
        self.draft = self.start()['data']['manual_draft']

    def tearDown(self):
        draft_fixtures.DraftCommandTests.tearDown(self)

    def payload(self, draft=None):
        draft = draft or self.draft
        return {'requirement_id': 101, 'expected_version': draft['content_version'],
            'markdown_content': draft['markdown_content'], 'block_state_json': deepcopy(draft['block_state_json'])}

    def appended(self, draft=None):
        draft = draft or self.draft
        with self.database.transaction() as connection:
            sources = DocumentSources(connection, 101, self.catalog)
            prior = validate_snapshot(draft['markdown_content'], draft['block_state_json'], sources)
            ids = list(prior.by_id) + [prior.next_block_id]
            snapshot = assign_identities(prior.parsed.markdown + '\n\nnew body\n', ids, prior.next_block_id+1, prior,
                Provenance('USER', 'MANUAL_EDIT', draft['id']), utc_milliseconds(INSTANT), sources)
        return {'requirement_id': 101, 'expected_version': draft['content_version'], 'markdown_content': snapshot.parsed.markdown, 'block_state_json': snapshot.state}

    def save(self, payload, instant=LATER):
        return save_manual_draft(self.database, payload, catalog=self.catalog, clock=lambda: instant)

    def read(self):
        return get_manual_draft(self.database, 101, catalog=self.catalog)['data']

    def test_same_pair_increments_only_draft_version_and_timestamp(self):
        current = self.current_facts()
        with self.database.transaction() as connection:
            root = tuple(connection.execute('SELECT * FROM requirements').fetchone())
        result = self.save(self.payload())
        self.assertEqual(result['code'], 'DRAFT_SAVED', result)
        self.assertEqual(result['data']['content_version'], 2)
        self.assertEqual(result['data']['block_state_json'], self.draft['block_state_json'])
        self.assertEqual(result['data']['updated_at'], utc_milliseconds(LATER))
        self.assertEqual(self.current_facts(), current)
        with self.database.transaction() as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM requirements').fetchone()), root)
            for table in ('revisions', 'comments', 'document_change_audits', 'manual_block_origins', 'manual_block_allocation_ranges'):
                self.assertEqual(connection.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0], 1)

    def test_new_birth_uses_first_server_allocation_time_and_deleted_saved_id_restores(self):
        submitted = self.appended()
        saved = self.save(submitted)['data']
        born = saved['block_state_json']['blocks'][-1]
        self.assertEqual(born['created_at'], utc_milliseconds(LATER))
        self.assertNotEqual(born['created_at'], submitted['block_state_json']['blocks'][-1]['created_at'])
        delete = self.payload(saved)
        delete['markdown_content'] = self.draft['markdown_content']
        delete['block_state_json']['blocks'].pop()
        deleted = self.save(delete, LATER+timedelta(seconds=1))['data']
        restore = self.payload(saved)
        restore['expected_version'] = deleted['content_version']
        restored = self.save(restore, LATER+timedelta(seconds=2))
        self.assertEqual(restored['code'], 'DRAFT_SAVED', restored)
        block = restored['data']['block_state_json']['blocks'][-1]
        self.assertEqual(block['block_id'], born['block_id'])
        self.assertEqual(block['created_at'], born['created_at'])
        self.assertEqual(block['last_modified_at'], utc_milliseconds(LATER+timedelta(seconds=2)))
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_block_origins').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_block_allocation_ranges').fetchone()[0], 1)

    def test_allocation_without_visible_block_later_restores_with_original_receipt_time(self):
        born_input = self.appended()
        invisible = self.payload()
        invisible['block_state_json']['next_block_id'] += 1
        accepted = self.save(invisible)['data']
        born_input['expected_version'] = accepted['content_version']
        result = self.save(born_input, LATER+timedelta(seconds=2))
        self.assertEqual(result['code'], 'DRAFT_SAVED', result)
        block = result['data']['block_state_json']['blocks'][-1]
        self.assertEqual(block['created_at'], utc_milliseconds(LATER))
        self.assertEqual(block['last_modified_at'], utc_milliseconds(LATER+timedelta(seconds=2)))

    def test_unallocated_deleted_identity_foreign_source_and_changed_birth_reject_atomically(self):
        saved = self.save(self.appended())['data']
        for field, value in (('created_at', utc_milliseconds(INSTANT)), ('created_source_id', 201), ('created_by_type', 'SYSTEM')):
            with self.subTest(field=field):
                payload = self.payload(saved)
                payload['block_state_json']['blocks'][-1][field] = value
                before = self.facts()
                self.assertEqual(self.save(payload, LATER+timedelta(seconds=1))['code'], 'DOCUMENT_INVALID')
                self.assertEqual(self.facts(), before)
        payload = self.appended(saved)
        payload['block_state_json']['blocks'][-1].update(created_by_type='SYSTEM', created_source_type='TEMPLATE', created_source_id=None)
        before = self.facts()
        self.assertEqual(self.save(payload, LATER+timedelta(seconds=1))['code'], 'DOCUMENT_INVALID')
        self.assertEqual(self.facts(), before)
        # A lower ID absent from both original baseline and allocation ranges cannot return.
        with self.database.transaction(write=True) as connection:
            connection.execute('DELETE FROM manual_block_origins')
        before = self.facts()
        self.assertEqual(self.save(self.payload(saved), LATER+timedelta(seconds=1))['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)

    def test_baseline_deleted_identity_can_return_without_new_allocation(self):
        deleted = self.payload()
        deleted['markdown_content'] = ''
        deleted['block_state_json']['blocks'] = []
        saved = self.save(deleted)['data']
        restore = self.payload()
        restore['expected_version'] = saved['content_version']
        result = self.save(restore, LATER+timedelta(seconds=1))
        self.assertEqual(result['code'], 'DRAFT_SAVED', result)
        self.assertEqual([x['block_id'] for x in result['data']['block_state_json']['blocks']], [x['block_id'] for x in self.draft['block_state_json']['blocks']])
        self.assertTrue(all(x['last_modified_source_id'] == self.draft['id'] for x in result['data']['block_state_json']['blocks']))

    def test_gap_below_initial_watermark_cannot_be_claimed_as_undo_identity(self):
        # Seed a legitimate sparse CURRENT, then use the real start command.
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
            sources = DocumentSources(connection, 102, self.catalog)
            original = create_snapshot('body\n', Provenance('SYSTEM', 'TEMPLATE', None), self.draft['created_at'], sources)
            state = original.state
            state['blocks'][0]['block_id'] = 10
            state['next_block_id'] = 50
            sparse = validate_snapshot(original.parsed.markdown, state, sources)
            connection.execute("INSERT INTO requirement_documents VALUES (301,102,'CURRENT',?,?,1,?,?)", (sparse.parsed.markdown, sparse.state_json, self.draft['created_at'], self.draft['created_at']))
            connection.execute("UPDATE sequences SET last_value=301 WHERE entity_kind='RequirementDocument'")
        started = start_manual_draft(self.executor, {'requirement_id': 102, 'expected_content_version': 1, 'idempotency_key': KEY}, catalog=self.catalog, clock=lambda: INSTANT)['data']['manual_draft']
        payload = self.payload(started)
        payload['requirement_id'] = 102
        payload['block_state_json']['blocks'][0].update(block_id=20, created_by_type='USER', created_source_type='MANUAL_EDIT', created_source_id=started['id'])
        before = self.facts()
        self.assertEqual(self.save(payload)['code'], 'DOCUMENT_INVALID')
        self.assertEqual(self.facts(), before)

    def test_large_high_watermark_stores_one_interval_without_expansion_and_never_rewinds(self):
        payload = self.payload()
        payload['block_state_json']['next_block_id'] = MAX_SAFE_INTEGER
        saved = self.save(payload)['data']
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_block_allocation_ranges').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_block_origins').fetchone()[0], 0)
        before = self.facts()
        payload = self.payload(saved)
        payload['block_state_json']['next_block_id'] -= 1
        self.assertEqual(self.save(payload, LATER+timedelta(seconds=1))['code'], 'DOCUMENT_INVALID')
        self.assertEqual(self.facts(), before)

    def test_client_modified_fields_recomputed_from_actual_changes(self):
        payload = self.appended()
        payload['block_state_json']['blocks'][-1].update(last_modified_by_type='SYSTEM', last_modified_source_type='TEMPLATE', last_modified_source_id=None)
        saved = self.save(payload)['data']
        block = saved['block_state_json']['blocks'][-1]
        self.assertEqual((block['last_modified_by_type'], block['last_modified_source_type'], block['last_modified_source_id']), ('USER', 'MANUAL_EDIT', self.draft['id']))
        self.assertEqual(block['last_modified_at'], utc_milliseconds(LATER))

    def test_every_sql_fault_and_result_conversion_roll_back_proofs_and_pair(self):
        for table, event in (('manual_block_allocation_ranges', 'AFTER INSERT'), ('manual_block_origins', 'AFTER INSERT'), ('requirement_documents', 'AFTER UPDATE')):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER test_save_fault {event} ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
                    connection.commit()
                before = self.facts()
                self.assertEqual(self.save(self.appended())['code'], 'STORAGE_UNAVAILABLE')
                self.assertEqual(self.facts(), before)
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute('DROP TRIGGER test_save_fault')
                    connection.commit()
        before = self.facts()
        with patch('backend.app.documents.commands.save_manual_draft_result', side_effect=ValueError('injected mapping failure')):
            self.assertEqual(self.save(self.appended())['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)

    def test_actual_committed_save_with_lost_ack_get_confirms_and_old_version_conflicts(self):
        original = self.database.transaction
        @contextmanager
        def lose_ack(*, write=False):
            with original(write=write) as connection:
                yield connection
            if write:
                raise CommitOutcomeUnknown('Real commit followed by lost acknowledgment')
        payload = self.appended()
        self.database.transaction = lose_ack
        try:
            self.assertEqual(self.save(payload)['code'], 'STORAGE_UNAVAILABLE')
        finally:
            self.database.transaction = original
        saved = self.read()
        self.assertEqual(saved['content_version'], 2)
        before = self.facts()
        self.assertEqual(self.save(payload)['code'], 'CONTENT_VERSION_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_two_actual_writers_accept_only_one_same_version(self):
        payload = self.appended()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.save(payload), range(2)))
        self.assertCountEqual([r['code'] for r in results], ['DRAFT_SAVED', 'CONTENT_VERSION_CONFLICT'])
        self.assertEqual(self.read()['content_version'], 2)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_block_origins').fetchone()[0], 1)

    def test_cancel_cleans_temporary_proofs_and_keeps_permanent_source(self):
        saved = self.save(self.appended())['data']
        result = cancel_manual_draft(self.executor, {'requirement_id': 101, 'expected_version': saved['content_version'], 'idempotency_key': KEY}, clock=lambda: LATER+timedelta(seconds=1))
        self.assertEqual(result['code'], 'DRAFT_CANCELLED', result)
        with self.database.transaction() as connection:
            for table in ('manual_block_origins', 'manual_block_allocation_ranges', 'manual_draft_context'):
                self.assertEqual(connection.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT status FROM manual_edit_sessions').fetchone()[0], 'CANCELLED')

    def test_cancel_proof_cleanup_failure_rolls_back_all_state(self):
        saved = self.save(self.appended())['data']
        for table in ('manual_block_origins', 'manual_block_allocation_ranges'):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER test_delete_fault AFTER DELETE ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
                    connection.commit()
                before = self.facts()
                result = cancel_manual_draft(self.executor, {'requirement_id': 101, 'expected_version': saved['content_version'], 'idempotency_key': KEY}, clock=lambda: LATER+timedelta(seconds=1))
                self.assertEqual(result['code'], 'STORAGE_UNAVAILABLE')
                self.assertEqual(self.facts(), before)
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute('DROP TRIGGER test_delete_fault')
                    connection.commit()

    def test_strict_inputs_document_pair_failures_and_missing_requirement(self):
        for changes in ({'expected_version': True}, {'requirement_id': '101'}, {'block_state_json': '{}'}, {'markdown_content': None}, {'idempotency_key': KEY}):
            with self.subTest(changes=changes):
                self.assertEqual(self.save({**self.payload(), **changes})['code'], 'INVALID_INPUT')
        payload = self.payload()
        payload['markdown_content'] = 'different block count'
        self.assertEqual(self.save(payload)['code'], 'DOCUMENT_INVALID')
        self.assertEqual(self.save({**self.payload(), 'requirement_id': 999})['code'], 'NOT_FOUND')

    def test_version_capacity_and_clock_regression_leave_facts_unchanged(self):
        before = self.facts()
        self.assertEqual(self.save(self.payload(), INSTANT-timedelta(seconds=1))['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=? WHERE id=?', (MAX_SAFE_INTEGER, self.draft['id']))
        payload = self.appended(self.read())
        before = self.facts()
        self.assertEqual(self.save(payload)['code'], 'CAPACITY_EXHAUSTED')
        self.assertEqual(self.facts(), before)


if __name__ == '__main__':
    unittest.main()
