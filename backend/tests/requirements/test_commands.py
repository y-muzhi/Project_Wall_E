"""APP-REQ-CMD-C02 real file transactions, state competition and rollback."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from backend.app.infrastructure.database import CommitOutcomeUnknown, Database
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.commands import update_requirement
from backend.app.requirements.queries import get_requirement
from .test_queries import TIME, LATER, seed

INSTANT = datetime(2026, 10, 4, 4, 1, tzinfo=timezone.utc)


class RequirementCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-requirement-command-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.database = Database(self.path)
        self.database.initialize()
        with self.database.transaction(write=True) as connection:
            seed(connection)
            connection.execute("INSERT INTO requirement_documents VALUES (9,1,'CURRENT','unchanged body','{}',7,?,?)", (TIME, TIME))

    def tearDown(self):
        self.directory.cleanup()

    def update(self, **fields):
        return update_requirement(self.database, {'requirement_id': 1, **fields}, clock=lambda: INSTANT)

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def test_title_normalizes_unicode_and_only_changes_submitted_attributes(self):
        before = get_requirement(self.database, 1)['data']
        result = self.update(title='\u3000😀新需求\r\n\t')
        self.assertEqual(result['code'], 'UPDATED')
        self.assertEqual(result['data'], {**before, 'title': '😀新需求', 'updated_at': LATER})
        self.assertEqual(get_requirement(self.database, 1)['data'], result['data'])
        with self.database.transaction() as connection:
            self.assertEqual(tuple(connection.execute('SELECT markdown_content,content_version,updated_at FROM requirement_documents').fetchone()), ('unchanged body', 7, TIME))
            for table in ('revisions', 'idempotency_records', 'sequences', 'guide_runs', 'conversation_messages'):
                self.assertEqual(connection.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_mode_is_creation_only_and_mixed_patch_cannot_partially_change_title(self):
        for status in ('INITIALIZING', 'ACTIVE', 'COMPLETED'):
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirements SET status=?,completed_at=?", (status, TIME if status == 'COMPLETED' else None))
            before = self.facts()
            for fields in ({'initialization_mode': 'IDEATION'}, {'initialization_mode': 'DESIGN'}, {'title': '不得部分更新', 'initialization_mode': 'DESIGN'}):
                result = self.update(**fields)
                self.assertEqual(result['code'], 'INVALID_INPUT')
                self.assertIsNone(result['data'])
            self.assertEqual(self.facts(), before)

    def test_no_change_does_not_write_sql_or_consult_clock(self):
        before = self.facts()
        def forbidden_clock():
            raise AssertionError('Unchanged request must not consult event clock')
        # A real aborting trigger additionally proves no UPDATE was issued.
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER test_no_update BEFORE UPDATE ON requirements BEGIN SELECT RAISE(ABORT,'must not update'); END")
            connection.commit()
        for changes in ({'title': ' 需求甲 '}, {'title': '需求甲'}):
            result = update_requirement(self.database, {'requirement_id': 1, **changes}, clock=forbidden_clock)
            self.assertEqual(result['code'], 'UPDATED')
            self.assertEqual(result['data']['updated_at'], TIME)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('DROP TRIGGER test_no_update')
            connection.commit()
        self.assertEqual(self.facts(), before)

    def test_invalid_or_missing_inputs_leave_all_facts_unchanged(self):
        before = self.facts()
        payloads = [None, [], {}, {'requirement_id': 1}, {'requirement_id': True, 'title': '甲'},
                    {'requirement_id': 1, 'unknown': '甲'}, {'requirement_id': 1, 'idempotency_key': 'key', 'title': '甲'}]
        for value in (None, True, '', '甲\r\n乙', '😀' * 21, '\ud800'):
            payloads.append({'requirement_id': 1, 'title': value})
        for value in (None, True, 'design', '', 'NEW'):
            payloads.append({'requirement_id': 1, 'initialization_mode': value})
        for payload in payloads:
            with self.subTest(payload=repr(payload)):
                result = update_requirement(self.database, payload)
                self.assertEqual(result['code'], 'INVALID_INPUT', result)
                self.assertIsNone(result['data'])
                self.assertTrue(result['details']['field_errors'])
        self.assertEqual(self.facts(), before)

    def test_missing_requirement_is_not_found_without_clock_or_writes(self):
        before = self.facts()
        result = update_requirement(self.database, {'requirement_id': 2, 'title': '甲'}, clock=lambda: None)
        self.assertEqual(result, {'code': 'NOT_FOUND', 'data': None, 'details': None})
        self.assertEqual(self.facts(), before)

    def test_active_allows_title_but_rejects_mode_even_same_mode_and_both_atomic(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='ACTIVE'")
        self.assertEqual(self.update(title='活动标题')['code'], 'UPDATED')
        before = self.facts()
        for fields in ({'initialization_mode': 'IDEATION'}, {'initialization_mode': 'DESIGN'}, {'title': '不得部分更新', 'initialization_mode': 'DESIGN'}):
            self.assertEqual(self.update(**fields)['code'], 'INVALID_INPUT')
        self.assertEqual(self.facts(), before)

    def test_completed_rejects_title_mode_and_no_change_before_mutation(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=?", (TIME,))
        before = self.facts()
        for fields in ({'title': '需求甲'}, {'title': '新标题'}, {'initialization_mode': 'IDEATION'}, {'title': '新标题', 'initialization_mode': 'DESIGN'}):
            self.assertEqual(self.update(**fields)['code'], 'INVALID_INPUT' if 'initialization_mode' in fields else 'STATE_CONFLICT')
        self.assertEqual(self.facts(), before)

    def test_non_idle_blocks_mode_and_both_but_title_remains_permitted(self):
        for work, operation in (('MANUAL_EDITING', 'MANUAL_DRAFT'), ('GUIDE_ACTIVE', 'GUIDE_RUN'), ('SUGGESTION_REVIEWING', 'SUGGESTION_BATCH')):
            with self.subTest(work=work):
                with self.database.transaction(write=True) as connection:
                    connection.execute('UPDATE requirements SET document_work_state=?,active_operation_type=?,active_operation_id=88,state_started_at=?', (work, operation, TIME))
                before = self.facts()
                for fields in ({'initialization_mode': 'IDEATION'}, {'title': '不得部分更新', 'initialization_mode': 'DESIGN'}):
                    self.assertEqual(self.update(**fields)['code'], 'INVALID_INPUT')
                self.assertEqual(self.facts(), before)
                self.assertEqual(self.update(title='可改标题')['code'], 'UPDATED')

    def test_real_sql_constraint_failure_rolls_back_all_attributes_and_time(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER test_fail_write AFTER UPDATE ON requirements BEGIN SELECT RAISE(ABORT,'injected storage write failure'); END")
            connection.commit()
        before = self.facts()
        self.assertEqual(self.update(title='新标题'), {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None})
        self.assertEqual(self.facts(), before)

    def test_result_mapping_failure_after_actual_update_rolls_back_transaction(self):
        original = RequirementRepository.get
        reads = 0
        def fail_after_write(repository, identity):
            nonlocal reads
            result = original(repository, identity)
            reads += 1
            if reads == 2:
                self.assertEqual(result['title'], '待回滚')
                raise ValueError('Injected result conversion failure after actual SQL')
            return result
        before = self.facts()
        with patch.object(RequirementRepository, 'get', fail_after_write):
            self.assertEqual(self.update(title='待回滚')['code'], 'INTERNAL_ERROR')
        self.assertEqual(reads, 2)
        self.assertEqual(self.facts(), before)

    def test_clock_or_stored_data_failure_is_internal_and_never_partial_success(self):
        before = self.facts()
        for instant in (None, datetime(2026, 10, 4), 'fake time'):
            result = update_requirement(self.database, {'requirement_id': 1, 'title': '甲'}, clock=lambda: instant)
            self.assertEqual(result['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET updated_at='2026-99-04T04:00:00.000Z'")
        before = self.facts()
        self.assertEqual(self.update(title='甲')['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)

    def test_actual_write_lock_rechecks_state_changed_after_previous_get(self):
        self.assertEqual(get_requirement(self.database, 1)['data']['status'], 'INITIALIZING')
        held, command_begins = Event(), Event()
        command_database = Database(self.path)
        original_connect = command_database._connect
        def traced_connect(**kwargs):
            connection = original_connect(**kwargs)
            connection.set_trace_callback(lambda sql: command_begins.set() if sql == 'BEGIN IMMEDIATE' else None)
            return connection
        def competing_writer():
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirements SET status='COMPLETED',completed_at=?", (TIME,))
                held.set()
                if not command_begins.wait(10):
                    raise RuntimeError('Command never attempted shared write lock')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(competing_writer)
            self.assertTrue(held.wait(10))
            with patch.object(command_database, '_connect', traced_connect):
                result = update_requirement(command_database, {'requirement_id': 1, 'title': '不得部分更新'})
            future.result(timeout=12)
        self.assertEqual(result, {'code': 'STATE_CONFLICT', 'data': None, 'details': None})
        current = get_requirement(self.database, 1)['data']
        self.assertEqual((current['status'], current['title'], current['initialization_mode'], current['updated_at']), ('COMPLETED', '需求甲', 'IDEATION', TIME))

    def test_real_commit_with_lost_ack_keeps_fact_and_retry_is_no_change(self):
        class LostAckDatabase(Database):
            @contextmanager
            def transaction(self, *, write=False):
                with super().transaction(write=write) as connection:
                    yield connection
                if write:
                    raise CommitOutcomeUnknown('Injected acknowledgement loss after real commit')
        result = update_requirement(LostAckDatabase(self.path), {'requirement_id': 1, 'title': '已提交'}, clock=lambda: INSTANT)
        self.assertEqual(result, {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None})
        self.assertEqual(get_requirement(self.database, 1)['data']['title'], '已提交')
        retried = update_requirement(self.database, {'requirement_id': 1, 'title': '已提交'}, clock=lambda: None)
        self.assertEqual(retried['code'], 'UPDATED')
        self.assertEqual(retried['data']['updated_at'], LATER)

    def test_missing_storage_has_no_fake_update(self):
        path = Path(self.directory.name) / 'missing.sqlite'
        result = update_requirement(Database(path), {'requirement_id': 1, 'title': '甲'})
        self.assertEqual(result, {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None})
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
