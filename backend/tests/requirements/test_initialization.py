"""Real baseline transactions with persistent command claims and fault points."""
from contextlib import closing, contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.app.documents.snapshot import create_snapshot
from backend.app.documents.sources import DocumentSources, register_edit_session
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.commands import complete_initialization
from backend.app.requirements.queries import get_requirement
from backend.tests.documents.test_snapshot import TEMPLATE, T0, T1
from backend.tests.infrastructure.test_database import insert_requirement
from backend.tests.documents.test_sources import insert_guide
from backend.app.shared.validation import MAX_SAFE_INTEGER

KEY = '00000000-0000-4000-8000-00000000000a'
SECOND_KEY = '00000000-0000-4000-8000-00000000000b'
INSTANT = datetime.fromisoformat(T1[:-1] + '+00:00')


class InitializationCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-baseline-command-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.database = Database(self.path)
        self.database.initialize()
        self.lock = ProcessLock.for_database(self.path).acquire()
        self.executor = Idempotency(self.database, self.lock, clock=lambda: INSTANT)
        self.catalog = ResourceCatalog()
        self.template = self.catalog.template('NEW', 'new-requirement', 'v1')
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection)
            self.original = create_snapshot(self.template.markdown, TEMPLATE, T0, DocumentSources(connection, 101, self.catalog))
            connection.execute("INSERT INTO requirement_documents VALUES (201,101,'CURRENT',?,?,7,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))

    def tearDown(self):
        self.lock.release()
        self.directory.cleanup()

    def payload(self, **changes):
        return {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': KEY, **changes}

    def complete(self, **changes):
        return complete_initialization(self.executor, self.payload(**changes), catalog=self.catalog, clock=lambda: INSTANT)

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def test_baseline_copies_exact_pair_and_keeps_original_current_identity_version(self):
        result = self.complete()
        self.assertEqual(result['code'], 'INITIALIZATION_COMPLETED', result)
        self.assertEqual(result['data']['current_document'], {'id': 201, 'content_version': 7})
        self.assertEqual(result['data']['requirement']['status'], 'ACTIVE')
        self.assertEqual(result['data']['requirement']['updated_at'], T1)
        baseline = result['data']['baseline_revision']
        self.assertEqual((baseline['version_no'], baseline['revision_type'], baseline['description'], baseline['source_content_version'], baseline['created_at']), (1, 'BASELINE', '初始化基线', 7, T1))
        with self.database.transaction() as connection:
            row = connection.execute('SELECT * FROM revisions').fetchone()
            self.assertEqual((row['markdown_snapshot'], row['block_state_snapshot_json']), (self.original.parsed.markdown, self.original.state_json))
            current = connection.execute('SELECT * FROM requirement_documents').fetchone()
            self.assertEqual((current['id'], current['content_version'], current['updated_at']), (201, 7, T0))
            saved = connection.execute('SELECT status,success_result_json,http_status FROM idempotency_records').fetchone()
            self.assertEqual((saved['status'], saved['http_status']), ('SUCCEEDED', 200))
            self.assertEqual(json.loads(saved['success_result_json']), result)

    def test_replay_freezes_original_result_even_after_requirement_changed(self):
        result = self.complete()
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET title='后来改名',updated_at=?", (T1,))
        before = self.facts()
        replay = complete_initialization(self.executor, self.payload(idempotency_key=KEY.upper()), clock=lambda: None)
        self.assertEqual(replay, result)
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.complete(expected_content_version=8)['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.complete(idempotency_key=SECOND_KEY)['code'], 'STATE_CONFLICT')

    def test_persistent_processing_claim_returns_in_progress_without_writes(self):
        request = self.payload()
        scope = Scope('APP-REQ-CMD-C03', 'Requirement:101', KEY)
        claim = self.executor.claim(scope, {'requirement_id': 101, 'expected_content_version': 7})
        before = self.facts()
        self.assertEqual(self.complete(), {'code': 'REQUEST_IN_PROGRESS', 'data': None, 'details': None})
        self.assertEqual(self.facts(), before)
        self.executor.abandon(claim)
        self.assertEqual(self.complete()['code'], 'INITIALIZATION_COMPLETED')

    def test_invalid_inputs_never_claim_and_missing_state_and_version_rejections_release_claim(self):
        before = self.facts()
        for payload in (None, {}, self.payload(expected_content_version=True), self.payload(requirement_id='101'), self.payload(idempotency_key='not UUID'), self.payload(unknown=1)):
            self.assertEqual(complete_initialization(self.executor, payload)['code'], 'INVALID_INPUT')
        self.assertEqual(self.facts(), before)
        for changes, expected in (({'requirement_id': 999}, 'NOT_FOUND'), ({'expected_content_version': 8}, 'CONTENT_VERSION_CONFLICT')):
            self.assertEqual(self.complete(**changes)['code'], expected)
            self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='ACTIVE'")
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_existing_baseline_rejected_even_when_root_is_still_initializing(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO revisions VALUES (301,101,1,'BASELINE',?,?,?,7,?)", (self.original.parsed.markdown, self.original.state_json, '初始化基线', T0))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_missing_current_dangling_occupancy_and_remaining_draft_fail_safely(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=999,state_started_at=?", (T0,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL")
            connection.execute("INSERT INTO requirement_documents VALUES (202,101,'MANUAL_DRAFT',?,?,1,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute('DELETE FROM requirement_documents')
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_actual_registered_manual_occupancy_is_busy_and_broken_context_is_inconsistent(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO requirement_documents VALUES (202,101,'MANUAL_DRAFT',?,?,1,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
            connection.execute('INSERT INTO manual_draft_context VALUES (202,201,7,?,?)', (self.original.state_json, T0))
            register_edit_session(connection, 202, T0)
            connection.execute("UPDATE requirements SET document_work_state='MANUAL_EDITING',active_operation_type='MANUAL_DRAFT',active_operation_id=202,state_started_at=?", (T0,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute('DELETE FROM manual_draft_context WHERE draft_id=202')
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_running_and_terminal_actual_guide_occupancy_and_remaining_run(self):
        with self.database.transaction(write=True) as connection:
            insert_guide(connection, self.catalog, 501, 'INITIALIZE')
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=501,state_started_at=?", (T0,))
        self.assertEqual(self.complete()['code'], 'WORK_STATE_CONFLICT')
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE guide_runs SET status='COMPLETED',ended_at=?,current_step='FINISHED' WHERE id=501", (T1,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_pending_batch_occupancy_checks_actual_parent_run_requirement(self):
        with self.database.transaction(write=True) as connection:
            insert_guide(connection, self.catalog, 501, 'MODIFY')
            connection.execute("UPDATE guide_runs SET status='COMPLETED',ended_at=?,current_step='FINISHED' WHERE id=501", (T1,))
            connection.execute("INSERT INTO suggestion_batches(id,requirement_id,guide_run_id,source_type,title,summary,status,base_content_version,created_at,updated_at) VALUES (601,101,501,'USER_INSTRUCTION','建议','测试','PENDING',7,?,?)", (T0, T0))
            connection.execute("UPDATE requirements SET document_work_state='SUGGESTION_REVIEWING',active_operation_type='SUGGESTION_BATCH',active_operation_id=601,state_started_at=?", (T0,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)
        # Separate fixtures cannot authorize a cross-requirement batch relation.
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
            insert_guide(connection, self.catalog, 502, 'MODIFY', 102)
            connection.execute("UPDATE guide_runs SET status='COMPLETED',ended_at=?,current_step='FINISHED' WHERE id=502", (T1,))
            connection.execute("UPDATE requirements SET active_operation_id=602 WHERE id=101")
            connection.execute("INSERT INTO suggestion_batches(id,requirement_id,guide_run_id,source_type,title,summary,status,base_content_version,created_at,updated_at) VALUES (602,101,502,'USER_INSTRUCTION','跨需求','测试','PENDING',7,?,?)", (T0, T0))
            connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=? WHERE id=601", (T1,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_document_and_template_failures_are_distinct_and_do_not_allocate(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirement_documents SET block_state_json='{}'")
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'DOCUMENT_INVALID')
        self.assertEqual(self.facts(), before)
        for markdown in (self.template.markdown.replace('## 背景与目标', '### 背景与目标'), self.template.markdown.replace('## 背景与目标', '## 已改标题')):
            with self.database.transaction(write=True) as connection:
                snapshot = create_snapshot(markdown, TEMPLATE, T0, DocumentSources(connection, 101, self.catalog))
                connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=?', (markdown, snapshot.state_json))
            before = self.facts()
            self.assertEqual(self.complete()['code'], 'TEMPLATE_INVALID')
            self.assertEqual(self.facts(), before)

    def test_template_lock_checks_original_identity_not_matching_heading_text(self):
        state = self.original.state
        for metadata in state['blocks']:
            metadata['block_id'] += 100
        state['next_block_id'] += 100
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET block_state_json=?', (json.dumps(state),))
        self.assertEqual(self.complete()['code'], 'TEMPLATE_INVALID')

    def test_failure_at_each_real_write_rolls_back_revision_root_sequence_and_success(self):
        for name, target, timing, predicate in (
            ('test_revision_fail', 'revisions', 'AFTER INSERT', ''),
            ('test_root_fail', 'requirements', 'AFTER UPDATE', ''),
            ('test_success_fail', 'idempotency_records', 'BEFORE UPDATE', "WHEN NEW.status='SUCCEEDED'"),
        ):
            with self.subTest(target=target):
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute(f"CREATE TRIGGER {name} {timing} ON {target} {predicate} BEGIN SELECT RAISE(ABORT,'injected fault'); END")
                    connection.commit()
                before = self.facts()
                self.assertEqual(self.complete()['code'], 'STORAGE_UNAVAILABLE')
                self.assertEqual(self.facts(), before)
                with closing(sqlite3.connect(self.path)) as connection:
                    connection.execute('DROP TRIGGER ' + name)
                    connection.commit()
        self.assertEqual(self.complete()['code'], 'INITIALIZATION_COMPLETED')

    def test_result_conversion_failure_after_real_business_writes_rolls_back(self):
        before = self.facts()
        with patch('backend.app.requirements.commands.complete_initialization_result', side_effect=ValueError('injected mapping failure')):
            self.assertEqual(self.complete()['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)
        self.assertEqual(get_requirement(self.database, 101)['data']['status'], 'INITIALIZING')

    def test_capacity_exhaustion_preserves_all_facts_and_releases_processing(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO sequences VALUES ('Revision',?)", (MAX_SAFE_INTEGER,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'CAPACITY_EXHAUSTED')
        self.assertEqual(self.facts(), before)

    def test_actual_success_commit_with_lost_ack_is_recovered_by_persisted_replay(self):
        class LostAckDatabase(Database):
            writes = 0
            @contextmanager
            def transaction(self, *, write=False):
                with super().transaction(write=write) as connection:
                    yield connection
                if write:
                    self.writes += 1
                    if self.writes == 2:
                        raise CommitOutcomeUnknown('Injected loss after business and success actually committed')
        executor = Idempotency(LostAckDatabase(self.path), self.lock, clock=lambda: INSTANT)
        result = complete_initialization(executor, self.payload(), catalog=self.catalog, clock=lambda: INSTANT)
        self.assertEqual(result['code'], 'STORAGE_UNAVAILABLE')
        before = self.facts()
        replay = self.complete()
        self.assertEqual(replay['code'], 'INITIALIZATION_COMPLETED')
        self.assertEqual(self.facts(), before)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT status FROM idempotency_records').fetchone()[0], 'SUCCEEDED')


if __name__ == '__main__':
    unittest.main()
