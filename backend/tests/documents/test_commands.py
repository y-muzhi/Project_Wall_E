"""Actual draft creation/cancellation, contexts and retained edit sessions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.app.documents.commands import start_manual_draft, cancel_manual_draft
from backend.app.documents.queries import get_current_document, get_manual_draft
from backend.app.documents.snapshot import Provenance, create_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.commands import complete_initialization
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.documents.test_snapshot import TEMPLATE, T0, T1
from backend.tests.infrastructure.test_database import insert_requirement

KEY = '00000000-0000-4000-8000-00000000000a'
SECOND_KEY = '00000000-0000-4000-8000-00000000000b'
BASE_KEY = '00000000-0000-4000-8000-000000000001'
INSTANT = datetime.fromisoformat(T1[:-1] + '+00:00')
LATER = INSTANT + timedelta(seconds=1)


class DraftCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-draft-command-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.database = Database(self.path)
        self.database.initialize()
        self.lock = ProcessLock.for_database(self.path).acquire()
        self.executor = Idempotency(self.database, self.lock, clock=lambda: INSTANT)
        self.catalog = ResourceCatalog()
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection)
            template = self.catalog.template('NEW', 'new-requirement', 'v1')
            self.original = create_snapshot(template.markdown, TEMPLATE, T0, DocumentSources(connection, 101, self.catalog))
            connection.execute("INSERT INTO requirement_documents VALUES (201,101,'CURRENT',?,?,7,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
            # Fixture IDs must have corresponding durable allocation facts.
            connection.execute("INSERT INTO sequences VALUES ('RequirementDocument',201)")

    def tearDown(self):
        self.lock.release()
        self.directory.cleanup()

    def start_payload(self, **changes):
        return {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': KEY, **changes}

    def cancel_payload(self, **changes):
        return {'requirement_id': 101, 'expected_version': 1, 'idempotency_key': KEY, **changes}

    def start(self, **changes):
        return start_manual_draft(self.executor, self.start_payload(**changes), catalog=self.catalog, clock=lambda: INSTANT)

    def cancel(self, **changes):
        return cancel_manual_draft(self.executor, self.cancel_payload(**changes), clock=lambda: LATER)

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def current_facts(self):
        with self.database.transaction() as connection:
            return tuple(connection.execute("SELECT * FROM requirement_documents WHERE document_type='CURRENT'").fetchone())

    def test_start_copies_exact_pair_with_independent_version_and_atomic_session_context(self):
        current = self.current_facts()
        result = self.start()
        self.assertEqual(result['code'], 'DRAFT_STARTED', result)
        draft, root = result['data']['manual_draft'], result['data']['requirement']
        self.assertEqual((draft['id'], draft['document_type'], draft['content_version']), (202, 'MANUAL_DRAFT', 1))
        self.assertEqual(draft['block_state_json'], self.original.state)
        self.assertEqual(draft['markdown_content'], self.original.parsed.markdown)
        self.assertEqual(root['document_work_state'], 'MANUAL_EDITING')
        self.assertEqual(root['active_operation_id'], 202)
        self.assertEqual(root['state_started_at'], T1)
        self.assertEqual(root['updated_at'], T1)
        self.assertEqual(self.current_facts(), current)
        self.assertEqual(get_manual_draft(self.database, 101, catalog=self.catalog)['data'], draft)
        with self.database.transaction() as connection:
            context = connection.execute('SELECT * FROM manual_draft_context').fetchone()
            self.assertEqual(tuple(context), (202, 201, 7, self.original.state_json, T1))
            self.assertEqual(tuple(connection.execute('SELECT * FROM manual_edit_sessions').fetchone()), (202, 101, 201, 'EDITING', T1, None))
            saved = connection.execute('SELECT status,success_result_json,http_status FROM idempotency_records').fetchone()
            self.assertEqual((saved['status'], saved['http_status']), ('SUCCEEDED', 201))
            self.assertEqual(json.loads(saved['success_result_json']), result)
            self.assertEqual(connection.execute('SELECT count(*) FROM document_change_audits').fetchone()[0], 0)

    def test_start_allowed_after_real_initialization_and_completed_is_rejected(self):
        self.assertEqual(complete_initialization(self.executor, self.start_payload(idempotency_key=BASE_KEY), catalog=self.catalog, clock=lambda: INSTANT)['code'], 'INITIALIZATION_COMPLETED')
        result = self.start()
        self.assertEqual(result['code'], 'DRAFT_STARTED')
        self.assertEqual(result['data']['requirement']['status'], 'ACTIVE')
        self.assertEqual(self.cancel()['code'], 'DRAFT_CANCELLED')
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=?", (T1,))
        before = self.facts()
        self.assertEqual(self.start(idempotency_key=SECOND_KEY)['code'], 'STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_cancel_retains_minimal_source_and_current_while_removing_draft_and_context(self):
        current = self.current_facts()
        self.assertEqual(self.start()['code'], 'DRAFT_STARTED')
        result = self.cancel()
        self.assertEqual(result, {'code': 'DRAFT_CANCELLED', 'details': None, 'data': {'requirement_id': 101, 'manual_draft_id': 202, 'cancelled': True}})
        self.assertEqual(self.current_facts(), current)
        self.assertEqual(get_manual_draft(self.database, 101)['code'], 'MANUAL_DRAFT_NOT_FOUND')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_draft_context').fetchone()[0], 0)
            self.assertEqual(tuple(connection.execute('SELECT status,closed_at FROM manual_edit_sessions').fetchone()), ('CANCELLED', LATER.isoformat(timespec='milliseconds').replace('+00:00', 'Z')))
            self.assertEqual(tuple(connection.execute('SELECT document_work_state,active_operation_type,active_operation_id,state_started_at FROM requirements').fetchone()), ('IDLE', None, None, None))
            self.assertTrue(DocumentSources(connection, 101, self.catalog)(Provenance('USER', 'MANUAL_EDIT', 202)))
            self.assertEqual(connection.execute('SELECT count(*) FROM document_change_audits').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 0)

    def test_start_replay_is_original_pair_and_new_key_cannot_create_second_draft(self):
        result = self.start()
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirement_documents SET content_version=2 WHERE id=202")
        before = self.facts()
        self.assertEqual(start_manual_draft(self.executor, self.start_payload(idempotency_key=KEY.upper()), clock=lambda: None), result)
        self.assertEqual(self.start(idempotency_key=SECOND_KEY)['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.start(expected_content_version=8)['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_cancel_compares_draft_version_and_old_replay_never_deletes_new_draft(self):
        self.assertEqual(self.start()['code'], 'DRAFT_STARTED')
        before = self.facts()
        self.assertEqual(self.cancel(expected_version=7)['code'], 'CONTENT_VERSION_CONFLICT')
        self.assertEqual(self.facts(), before)
        original = self.cancel()
        new = self.start(idempotency_key=SECOND_KEY)
        self.assertEqual(new['data']['manual_draft']['id'], 203)
        before = self.facts()
        self.assertEqual(self.cancel(), original)
        self.assertEqual(self.cancel(expected_version=2)['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.facts(), before)
        self.assertEqual(get_manual_draft(self.database, 101, catalog=self.catalog)['data']['id'], 203)

    def test_cancel_new_key_after_prior_cancel_has_no_active_draft(self):
        self.start()
        self.cancel()
        before = self.facts()
        self.assertEqual(self.cancel(idempotency_key=SECOND_KEY)['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_invalid_inputs_do_not_claim_and_version_names_are_distinct(self):
        before = self.facts()
        for payload in (None, {}, self.start_payload(expected_content_version=True), self.start_payload(expected_version=7), self.start_payload(requirement_id='101'), self.start_payload(idempotency_key='bad')):
            self.assertEqual(start_manual_draft(self.executor, payload)['code'], 'INVALID_INPUT')
        for payload in (None, {}, self.cancel_payload(expected_version=None), self.cancel_payload(expected_version=True), self.cancel_payload(expected_content_version=1), self.cancel_payload(unknown=1), self.cancel_payload(idempotency_key='bad')):
            self.assertEqual(cancel_manual_draft(self.executor, payload)['code'], 'INVALID_INPUT')
        self.assertEqual(self.facts(), before)

    def test_not_found_missing_current_wrong_version_and_dangling_occupancy_preserve_facts(self):
        before = self.facts()
        self.assertEqual(self.start(requirement_id=999)['code'], 'NOT_FOUND')
        self.assertEqual(self.cancel(requirement_id=999)['code'], 'NOT_FOUND')
        self.assertEqual(self.start(expected_content_version=8)['code'], 'CONTENT_VERSION_CONFLICT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=999,state_started_at=?", (T0,))
        before = self.facts()
        self.assertEqual(self.start()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.cancel()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL")
            connection.execute('DELETE FROM requirement_documents')
        before = self.facts()
        self.assertEqual(self.start()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_cancel_dangling_and_mismatched_context_are_not_silently_cleaned_up(self):
        self.start()
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirements SET active_operation_id=999')
        before = self.facts()
        self.assertEqual(self.cancel()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirements SET active_operation_id=202')
            connection.execute('DELETE FROM manual_draft_context')
        before = self.facts()
        self.assertEqual(self.cancel()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_bad_current_pair_cannot_start_but_cancel_does_not_adopt_bad_draft_body(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirement_documents SET block_state_json='{}' WHERE id=201")
        before = self.facts()
        self.assertEqual(self.start()['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET block_state_json=? WHERE id=201', (self.original.state_json,))
        self.assertEqual(self.start()['code'], 'DRAFT_STARTED')
        current = self.current_facts()
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirement_documents SET markdown_content='discarded invalid body',block_state_json='{}' WHERE id=202")
        self.assertEqual(self.cancel()['code'], 'DRAFT_CANCELLED')
        self.assertEqual(self.current_facts(), current)

    def test_each_start_write_failure_rolls_back_document_context_session_occupancy_and_sequence(self):
        for name, table, event, predicate in (
            ('test_fail_doc', 'requirement_documents', 'AFTER INSERT', ''),
            ('test_fail_context', 'manual_draft_context', 'AFTER INSERT', ''),
            ('test_fail_session', 'manual_edit_sessions', 'AFTER INSERT', ''),
            ('test_fail_root', 'requirements', 'AFTER UPDATE', ''),
            ('test_fail_success', 'idempotency_records', 'BEFORE UPDATE', "WHEN NEW.status='SUCCEEDED'"),
        ):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER {name} {event} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'injected start failure'); END")
                    connection.commit()
                before = self.facts()
                self.assertEqual(self.start()['code'], 'STORAGE_UNAVAILABLE')
                self.assertEqual(self.facts(), before)
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute('DROP TRIGGER ' + name)
                    connection.commit()

    def test_each_cancel_write_failure_keeps_draft_context_editing_session_and_occupancy(self):
        self.start()
        for name, table, event, predicate in (
            ('test_fail_context', 'manual_draft_context', 'AFTER DELETE', ''),
            ('test_fail_doc', 'requirement_documents', 'AFTER DELETE', ''),
            ('test_fail_root', 'requirements', 'AFTER UPDATE', ''),
            ('test_fail_session', 'manual_edit_sessions', 'AFTER UPDATE', ''),
            ('test_fail_success', 'idempotency_records', 'BEFORE UPDATE', "WHEN NEW.status='SUCCEEDED'"),
        ):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER {name} {event} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'injected cancel failure'); END")
                    connection.commit()
                before = self.facts()
                self.assertEqual(self.cancel()['code'], 'STORAGE_UNAVAILABLE')
                self.assertEqual(self.facts(), before)
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute('DROP TRIGGER ' + name)
                    connection.commit()

    def test_result_mapping_failures_for_both_actions_rollback_all_business_writes(self):
        before = self.facts()
        with patch('backend.app.documents.commands.start_manual_draft_result', side_effect=ValueError('injected result conversion')):
            self.assertEqual(self.start()['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)
        self.start()
        before = self.facts()
        with patch('backend.app.documents.commands.cancel_manual_draft_result', side_effect=ValueError('injected result conversion')):
            self.assertEqual(self.cancel()['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)

    def test_capacity_exhaustion_does_not_create_partial_draft_or_session(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE sequences SET last_value=? WHERE entity_kind='RequirementDocument'", (MAX_SAFE_INTEGER,))
        before = self.facts()
        self.assertEqual(self.start()['code'], 'CAPACITY_EXHAUSTED')
        self.assertEqual(self.facts(), before)

    def test_real_competing_starts_create_one_draft_and_one_edit_session(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: self.start(idempotency_key=key), (KEY, SECOND_KEY)))
        self.assertEqual(sorted(result['code'] for result in results), ['DRAFT_STARTED', 'WORK_STATE_CONFLICT'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM requirement_documents WHERE document_type='MANUAL_DRAFT'").fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_edit_sessions').fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT last_value FROM sequences WHERE entity_kind='RequirementDocument'").fetchone()[0], 202)

    def test_real_competing_cancels_close_one_session_once(self):
        self.start()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: self.cancel(idempotency_key=key), (KEY, SECOND_KEY)))
        self.assertEqual(sorted(result['code'] for result in results), ['DRAFT_CANCELLED', 'WORK_STATE_CONFLICT'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_edit_sessions').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT status FROM manual_edit_sessions').fetchone()[0], 'CANCELLED')

    def test_persistent_processing_claims_do_not_duplicate_either_action(self):
        for capability, business, action in (('APP-DOC-CMD-C01', {'requirement_id': 101, 'expected_content_version': 7}, self.start), ('APP-DOC-CMD-C04', {'requirement_id': 101, 'expected_version': 1}, self.cancel)):
            claim = self.executor.claim(Scope(capability, 'Requirement:101', KEY), business)
            before = self.facts()
            self.assertEqual(action()['code'], 'REQUEST_IN_PROGRESS')
            self.assertEqual(self.facts(), before)
            self.executor.abandon(claim)

    def test_actual_start_and_cancel_commits_with_lost_ack_replay_original_results(self):
        for function, payload, expected in ((start_manual_draft, self.start_payload(), 'DRAFT_STARTED'), (cancel_manual_draft, self.cancel_payload(), 'DRAFT_CANCELLED')):
            with self.subTest(function=function.__name__):
                class LostAckDatabase(Database):
                    writes = 0
                    @contextmanager
                    def transaction(self, *, write=False):
                        with super().transaction(write=write) as connection:
                            yield connection
                        if write:
                            self.writes += 1
                            if self.writes == 2:
                                raise CommitOutcomeUnknown('Injected loss after actual atomic draft/session/success commit')
                executor = Idempotency(LostAckDatabase(self.path), self.lock, clock=lambda: INSTANT)
                if function is start_manual_draft:
                    result = function(executor, payload, catalog=self.catalog, clock=lambda: INSTANT)
                else:
                    result = function(executor, payload, clock=lambda: LATER)
                self.assertEqual(result['code'], 'STORAGE_UNAVAILABLE')
                before = self.facts()
                replay = function(self.executor, payload, clock=lambda: None)
                self.assertEqual(replay['code'], expected)
                self.assertEqual(self.facts(), before)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_edit_sessions').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT status FROM manual_edit_sessions').fetchone()[0], 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
