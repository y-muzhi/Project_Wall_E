"""Actual manual revision allocation and immutable success replay."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.app.documents.snapshot import create_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.commands import complete_initialization
from backend.app.revisions.commands import create_manual_revision
from backend.app.shared.validation import MAX_SAFE_INTEGER
from backend.tests.documents.test_snapshot import TEMPLATE, T0, T1, T2
from backend.tests.infrastructure.test_database import insert_requirement

INSTANT = datetime.fromisoformat(T1[:-1] + '+00:00')
LATER = datetime.fromisoformat(T2[:-1] + '+00:00')
BASE_KEY = '00000000-0000-4000-8000-000000000001'
KEY = '00000000-0000-4000-8000-00000000000a'
SECOND_KEY = '00000000-0000-4000-8000-00000000000b'


class ManualRevisionCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-manual-revision-')
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
        result = complete_initialization(self.executor, {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': BASE_KEY}, catalog=self.catalog, clock=lambda: INSTANT)
        self.assertEqual(result['code'], 'INITIALIZATION_COMPLETED', result)

    def tearDown(self):
        self.lock.release()
        self.directory.cleanup()

    def payload(self, **changes):
        return {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': KEY, **changes}

    def create(self, **changes):
        return create_manual_revision(self.executor, self.payload(**changes), catalog=self.catalog, clock=lambda: LATER)

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def test_manual_revision_exact_copy_and_summary_does_not_modify_root_or_current(self):
        with self.database.transaction() as connection:
            root_before = tuple(connection.execute('SELECT * FROM requirements').fetchone())
            current_before = tuple(connection.execute('SELECT * FROM requirement_documents').fetchone())
        result = self.create(description='\u3000版本😀\r\n说明\u3000')
        self.assertEqual(result['code'], 'REVISION_CREATED')
        self.assertEqual((result['data']['version_no'], result['data']['revision_type'], result['data']['description'], result['data']['source_content_version'], result['data']['created_at']), (2, 'MANUAL', '版本😀\n说明', 7, T2))
        self.assertEqual(len(result['data']), 7)
        with self.database.transaction() as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM requirements').fetchone()), root_before)
            self.assertEqual(tuple(connection.execute('SELECT * FROM requirement_documents').fetchone()), current_before)
            row = connection.execute('SELECT * FROM revisions WHERE version_no=2').fetchone()
            self.assertEqual((row['markdown_snapshot'], row['block_state_snapshot_json']), (self.original.parsed.markdown, self.original.state_json))
            self.assertEqual(connection.execute("SELECT http_status FROM idempotency_records WHERE capability_id='APP-REV-CMD-C01'").fetchone()[0], 201)

    def test_missing_null_and_blank_descriptions_have_same_canonical_replay(self):
        result = self.create()
        self.assertIsNone(result['data']['description'])
        before = self.facts()
        self.assertEqual(self.create(description=None, idempotency_key=KEY.upper()), result)
        self.assertEqual(self.create(description='\r\n\u3000\t'), result)
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.create(description='不同输入')['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.create(expected_content_version=8)['code'], 'IDEMPOTENCY_CONFLICT')

    def test_replay_original_summary_after_new_current_and_new_versions(self):
        original = self.create(description='首个版本')
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=8 WHERE id=201')
        fresh = self.create(idempotency_key=SECOND_KEY, expected_content_version=8)
        self.assertEqual(fresh['data']['version_no'], 3)
        before = self.facts()
        self.assertEqual(self.create(description='首个版本'), original)
        self.assertEqual(self.facts(), before)

    def test_two_real_competing_commands_allocate_distinct_consecutive_versions(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.create, idempotency_key=key) for key in (KEY, SECOND_KEY)]
            results = [future.result(timeout=15) for future in futures]
        self.assertTrue(all(result['code'] == 'REVISION_CREATED' for result in results), results)
        self.assertEqual(sorted(result['data']['version_no'] for result in results), [2, 3])
        self.assertEqual(len({result['data']['id'] for result in results}), 2)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT count(*) FROM idempotency_records WHERE status='SUCCEEDED'").fetchone()[0], 3)

    def test_invalid_description_and_input_never_claim(self):
        before = self.facts()
        for payload in (None, {}, self.payload(description=True), self.payload(description='😀' * 1001), self.payload(description='\ud800'), self.payload(expected_content_version=True), self.payload(unknown=True), self.payload(idempotency_key='bad')):
            self.assertEqual(create_manual_revision(self.executor, payload)['code'], 'INVALID_INPUT')
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.create(description='😀' * 1000)['code'], 'REVISION_CREATED')

    def test_not_found_version_status_and_occupancy_rejections_preserve_facts(self):
        before = self.facts()
        for changes, expected in (({'requirement_id': 999}, 'NOT_FOUND'), ({'expected_content_version': 8}, 'CONTENT_VERSION_CONFLICT')):
            self.assertEqual(self.create(**changes)['code'], expected)
            self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=?", (T1,))
        before = self.facts()
        self.assertEqual(self.create()['code'], 'STATE_CONFLICT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='ACTIVE',completed_at=NULL")
            connection.execute("INSERT INTO requirement_documents VALUES (202,101,'MANUAL_DRAFT',?,?,1,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
        before = self.facts()
        self.assertEqual(self.create()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_missing_current_or_dangling_activity_never_creates_revision(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=999,state_started_at=?", (T1,))
        before = self.facts()
        self.assertEqual(self.create()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL")
            connection.execute('DELETE FROM requirement_documents')
        before = self.facts()
        self.assertEqual(self.create()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_bad_current_pair_is_document_invalid_and_no_state_is_repaired(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirement_documents SET block_state_json='{}'")
        before = self.facts()
        self.assertEqual(self.create(), {'code': 'DOCUMENT_INVALID', 'data': None, 'details': None})
        self.assertEqual(self.facts(), before)

    def test_active_without_actual_baseline_is_inconsistent(self):
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
            connection.execute("UPDATE requirements SET status='ACTIVE' WHERE id=102")
            connection.execute("INSERT INTO requirement_documents VALUES (202,102,'CURRENT',?,?,1,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
        before = self.facts()
        self.assertEqual(self.create(requirement_id=102, expected_content_version=1)['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_write_and_success_faults_and_result_conversion_rollback_revision_sequence(self):
        for name, table, timing, predicate in (
            ('test_fail_revision', 'revisions', 'AFTER INSERT', ''),
            ('test_fail_success', 'idempotency_records', 'BEFORE UPDATE', "WHEN NEW.status='SUCCEEDED'"),
        ):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER {name} {timing} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'injected failure'); END")
                    connection.commit()
                before = self.facts()
                self.assertEqual(self.create()['code'], 'STORAGE_UNAVAILABLE')
                self.assertEqual(self.facts(), before)
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute('DROP TRIGGER ' + name)
                    connection.commit()
        before = self.facts()
        with patch('backend.app.revisions.commands.create_manual_revision_result', side_effect=ValueError('injected conversion failure')):
            self.assertEqual(self.create()['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)

    def test_entity_and_per_requirement_version_capacity_exhaustion_roll_back(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE sequences SET last_value=? WHERE entity_kind='Revision'", (MAX_SAFE_INTEGER,))
        before = self.facts()
        self.assertEqual(self.create()['code'], 'CAPACITY_EXHAUSTED')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE sequences SET last_value=1 WHERE entity_kind='Revision'")
            connection.execute("INSERT INTO revisions VALUES (999,101,?,'MANUAL',?,?,NULL,7,?)", (MAX_SAFE_INTEGER, self.original.parsed.markdown, self.original.state_json, T0))
        before = self.facts()
        self.assertEqual(self.create()['code'], 'CAPACITY_EXHAUSTED')
        self.assertEqual(self.facts(), before)

    def test_persistent_processing_and_actual_commit_lost_ack_do_not_duplicate_snapshot(self):
        scope = Scope('APP-REV-CMD-C01', 'Requirement:101', KEY)
        claim = self.executor.claim(scope, {'requirement_id': 101, 'expected_content_version': 7, 'description': None})
        before = self.facts()
        self.assertEqual(self.create()['code'], 'REQUEST_IN_PROGRESS')
        self.assertEqual(self.facts(), before)
        self.executor.abandon(claim)
        class LostAckDatabase(Database):
            writes = 0
            @contextmanager
            def transaction(self, *, write=False):
                with super().transaction(write=write) as connection:
                    yield connection
                if write:
                    self.writes += 1
                    if self.writes == 2:
                        raise CommitOutcomeUnknown('Injected loss after actual success commit')
        executor = Idempotency(LostAckDatabase(self.path), self.lock, clock=lambda: INSTANT)
        result = create_manual_revision(executor, self.payload(), catalog=self.catalog, clock=lambda: LATER)
        self.assertEqual(result['code'], 'STORAGE_UNAVAILABLE')
        before = self.facts()
        replay = self.create()
        self.assertEqual(replay['code'], 'REVISION_CREATED')
        self.assertEqual(replay['data']['version_no'], 2)
        self.assertEqual(self.facts(), before)


if __name__ == '__main__':
    unittest.main()
