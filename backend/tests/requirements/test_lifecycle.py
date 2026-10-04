"""Real complete/reactivate transactions, old result replay and writer races."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
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
from backend.app.requirements.commands import complete_initialization, complete_requirement, reactivate_requirement
from backend.app.requirements.queries import get_requirement
from backend.app.shared.time import utc_milliseconds
from backend.tests.documents.test_snapshot import TEMPLATE, T0, T1
from backend.tests.infrastructure.test_database import insert_requirement

BASE_KEY = '00000000-0000-4000-8000-000000000001'
KEY = '00000000-0000-4000-8000-00000000000a'
SECOND_KEY = '00000000-0000-4000-8000-00000000000b'
INSTANT = datetime.fromisoformat(T1[:-1] + '+00:00') + timedelta(seconds=1)
LATER = INSTANT + timedelta(seconds=1)


class RequirementLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-lifecycle-')
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
        self.assertEqual(complete_initialization(self.executor, {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': BASE_KEY}, catalog=self.catalog, clock=lambda: INSTANT)['code'], 'INITIALIZATION_COMPLETED')

    def tearDown(self):
        self.lock.release()
        self.directory.cleanup()

    def complete_payload(self, **changes):
        return {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': KEY, **changes}

    def reactivate_payload(self, **changes):
        return {'requirement_id': 101, 'idempotency_key': KEY, **changes}

    def complete(self, **changes):
        return complete_requirement(self.executor, self.complete_payload(**changes), clock=lambda: INSTANT)

    def reactivate(self, **changes):
        return reactivate_requirement(self.executor, self.reactivate_payload(**changes), clock=lambda: LATER)

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def content_facts(self):
        with self.database.transaction() as connection:
            return {table: [tuple(row) for row in connection.execute('SELECT * FROM ' + table)]
                    for table in ('requirement_documents', 'revisions', 'comments', 'conversation_messages', 'sequences')}

    def test_complete_and_reactivate_change_only_lifecycle_fields_and_exact_event_times(self):
        before = get_requirement(self.database, 101)['data']
        content = self.content_facts()
        completed = self.complete()
        self.assertEqual(completed['code'], 'REQUIREMENT_COMPLETED')
        self.assertEqual(completed['data'], {**before, 'status': 'COMPLETED', 'completed_at': utc_milliseconds(INSTANT), 'updated_at': utc_milliseconds(INSTANT)})
        self.assertEqual(self.content_facts(), content)
        reactivated = self.reactivate()
        self.assertEqual(reactivated['code'], 'REACTIVATED')
        self.assertEqual(reactivated['data'], {**before, 'updated_at': utc_milliseconds(LATER)})
        self.assertEqual(self.content_facts(), content)
        with self.database.transaction() as connection:
            rows = connection.execute("SELECT capability_id,http_status FROM idempotency_records WHERE capability_id IN ('APP-REQ-CMD-C04','APP-REQ-CMD-C05') ORDER BY capability_id").fetchall()
            self.assertEqual([tuple(row) for row in rows], [('APP-REQ-CMD-C04', 200), ('APP-REQ-CMD-C05', 200)])

    def test_original_results_replay_across_later_lifecycle_without_changing_facts(self):
        completed = self.complete()
        self.assertEqual(self.reactivate()['code'], 'REACTIVATED')
        before = self.facts()
        replay = complete_requirement(self.executor, self.complete_payload(idempotency_key=KEY.upper()), clock=lambda: None)
        self.assertEqual(replay, completed)
        self.assertEqual(self.facts(), before)
        self.assertEqual(get_requirement(self.database, 101)['data']['status'], 'ACTIVE')
        reactivated = self.reactivate()
        self.assertEqual(self.complete(idempotency_key=SECOND_KEY)['code'], 'REQUIREMENT_COMPLETED')
        before = self.facts()
        self.assertEqual(reactivate_requirement(self.executor, self.reactivate_payload(), clock=lambda: None), reactivated)
        self.assertEqual(self.facts(), before)
        self.assertEqual(get_requirement(self.database, 101)['data']['status'], 'COMPLETED')

    def test_same_key_different_version_conflicts_and_new_key_rechecks_current_state(self):
        self.assertEqual(self.complete()['code'], 'REQUIREMENT_COMPLETED')
        self.assertEqual(self.complete(expected_content_version=8)['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.complete(idempotency_key=SECOND_KEY)['code'], 'STATE_CONFLICT')
        self.assertEqual(self.reactivate()['code'], 'REACTIVATED')
        self.assertEqual(self.reactivate(idempotency_key=SECOND_KEY)['code'], 'STATE_CONFLICT')

    def test_input_validation_never_claims_and_reactivate_does_not_accept_a_version(self):
        before = self.facts()
        for payload in (None, {}, self.complete_payload(expected_content_version=True), self.complete_payload(requirement_id='101'), self.complete_payload(idempotency_key='bad'), self.complete_payload(unknown=1)):
            self.assertEqual(complete_requirement(self.executor, payload)['code'], 'INVALID_INPUT')
        for payload in (None, {}, self.reactivate_payload(requirement_id=True), self.reactivate_payload(expected_content_version=7), self.reactivate_payload(title='extra'), self.reactivate_payload(idempotency_key=None)):
            self.assertEqual(reactivate_requirement(self.executor, payload)['code'], 'INVALID_INPUT')
        self.assertEqual(self.facts(), before)

    def test_not_found_wrong_version_and_wrong_phase_leave_all_facts_unchanged(self):
        before = self.facts()
        for result, expected in ((self.complete(requirement_id=999), 'NOT_FOUND'), (self.complete(expected_content_version=8), 'CONTENT_VERSION_CONFLICT'), (self.reactivate(), 'STATE_CONFLICT'), (self.reactivate(requirement_id=999), 'NOT_FOUND')):
            self.assertEqual(result['code'], expected)
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='INITIALIZING'")
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_completion_missing_current_and_dangling_activity_are_inconsistent(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=999,state_started_at=?", (T0,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL")
            connection.execute('DELETE FROM requirement_documents')
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_real_manual_occupancy_blocks_both_transitions_without_guessing_release(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO requirement_documents VALUES (202,101,'MANUAL_DRAFT',?,?,1,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
            connection.execute('INSERT INTO manual_draft_context VALUES (202,201,7,?,?)', (self.original.state_json, T0))
            register_edit_session(connection, 202, T0)
            connection.execute("UPDATE requirements SET document_work_state='MANUAL_EDITING',active_operation_type='MANUAL_DRAFT',active_operation_id=202,state_started_at=?", (T0,))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=?", (T1,))
        before = self.facts()
        self.assertEqual(self.reactivate()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_idle_with_remaining_draft_is_completion_conflict_and_reactivation_inconsistent(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO requirement_documents VALUES (202,101,'MANUAL_DRAFT',?,?,1,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
        before = self.facts()
        self.assertEqual(self.complete()['code'], 'WORK_STATE_CONFLICT')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=?", (T1,))
        before = self.facts()
        self.assertEqual(self.reactivate()['code'], 'WORK_STATE_INCONSISTENT')
        self.assertEqual(self.facts(), before)

    def test_two_real_completion_writers_accept_one_distinct_action(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: self.complete(idempotency_key=key), (KEY, SECOND_KEY)))
        self.assertEqual(sorted(result['code'] for result in results), ['REQUIREMENT_COMPLETED', 'STATE_CONFLICT'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM idempotency_records WHERE capability_id='APP-REQ-CMD-C04'").fetchone()[0], 1)

    def test_two_real_reactivation_writers_accept_one_distinct_action(self):
        self.assertEqual(self.complete()['code'], 'REQUIREMENT_COMPLETED')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: self.reactivate(idempotency_key=key), (KEY, SECOND_KEY)))
        self.assertEqual(sorted(result['code'] for result in results), ['REACTIVATED', 'STATE_CONFLICT'])

    def test_sql_and_result_conversion_failures_roll_back_both_transitions(self):
        for action, before_status, mapper in ((self.complete, 'ACTIVE', 'complete_requirement_result'), (self.reactivate, 'COMPLETED', 'reactivate_requirement_result')):
            with self.subTest(action=mapper):
                if before_status == 'COMPLETED':
                    self.assertEqual(self.complete()['code'], 'REQUIREMENT_COMPLETED')
                for name, table, predicate in (('test_fail_root', 'requirements', ''), ('test_fail_success', 'idempotency_records', "WHEN NEW.status='SUCCEEDED'")):
                    with closing(sqlite3.connect(self.path)) as connection:
                        connection.execute(f"CREATE TRIGGER {name} AFTER UPDATE ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'injected storage failure'); END")
                        connection.commit()
                    before = self.facts()
                    self.assertEqual(action()['code'], 'STORAGE_UNAVAILABLE')
                    self.assertEqual(self.facts(), before)
                    with closing(sqlite3.connect(self.path)) as connection:
                        connection.execute('DROP TRIGGER ' + name)
                        connection.commit()
                before = self.facts()
                with patch('backend.app.requirements.commands.' + mapper, side_effect=ValueError('injected result conversion')):
                    self.assertEqual(action()['code'], 'INTERNAL_ERROR')
                self.assertEqual(self.facts(), before)

    def test_processing_claims_return_in_progress_for_each_capability(self):
        for capability, business, action in (('APP-REQ-CMD-C04', {'requirement_id': 101, 'expected_content_version': 7}, self.complete), ('APP-REQ-CMD-C05', {'requirement_id': 101}, self.reactivate)):
            claim = self.executor.claim(Scope(capability, 'Requirement:101', KEY), business)
            before = self.facts()
            self.assertEqual(action()['code'], 'REQUEST_IN_PROGRESS')
            self.assertEqual(self.facts(), before)
            self.executor.abandon(claim)

    def test_real_lost_commit_ack_for_each_transition_replays_persisted_success(self):
        for function, payload, expected in ((complete_requirement, self.complete_payload(), 'REQUIREMENT_COMPLETED'), (reactivate_requirement, self.reactivate_payload(), 'REACTIVATED')):
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
                                raise CommitOutcomeUnknown('Injected ack loss after real atomic success')
                executor = Idempotency(LostAckDatabase(self.path), self.lock, clock=lambda: INSTANT)
                result = function(executor, payload, clock=lambda: INSTANT)
                self.assertEqual(result['code'], 'STORAGE_UNAVAILABLE')
                before = self.facts()
                replay = function(self.executor, payload, clock=lambda: None)
                self.assertEqual(replay['code'], expected)
                self.assertEqual(self.facts(), before)


if __name__ == '__main__':
    unittest.main()
