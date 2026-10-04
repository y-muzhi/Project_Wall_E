"""Real v3 file/WAL queries; seeds are test fixtures, not application defaults."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.contracts import LIST_FIELDS, READ_FIELDS
from backend.app.requirements.queries import get_requirement, list_requirements
from backend.app.shared.validation import MAX_SAFE_INTEGER

TIME = '2026-10-04T04:00:00.000Z'
LATER = '2026-10-04T04:01:00.000Z'


def seed(connection, identity=1, *, title='需求甲', kind='NEW', status='INITIALIZING', updated=TIME, **fields):
    data = dict(id=identity, requirement_no=f'REQ{identity:06}', requirement_type=kind,
                initialization_mode='IDEATION', title=title, template_key='new-requirement',
                template_version='v1', status=status, document_work_state='IDLE',
                active_operation_type=None, active_operation_id=None, created_at=TIME,
                updated_at=updated, completed_at=TIME if status == 'COMPLETED' else None,
                state_started_at=None)
    data.update(fields)
    connection.execute('INSERT INTO requirements (' + ','.join(READ_FIELDS) + ') VALUES (' +
                       ','.join('?' for _ in READ_FIELDS) + ')', tuple(data[field] for field in READ_FIELDS))


class RequirementQueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-requirement-query-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.database = Database(self.path)
        self.database.initialize()

    def tearDown(self):
        self.directory.cleanup()

    def ids(self, payload=None):
        result = list_requirements(self.database, {} if payload is None else payload)
        self.assertEqual(result['code'], 'READ_OK', result)
        return [item['id'] for item in result['data']['items']]

    def test_empty_and_out_of_range_pages_preserve_requested_page(self):
        for page in (1, 9, 100000):
            result = list_requirements(self.database, {'page': page})
            self.assertEqual(result, {'code': 'READ_OK', 'details': None, 'data': {
                'items': [], 'page': page, 'page_size': 20, 'total': 0, 'total_pages': 0}})
        with self.database.transaction(write=True) as connection:
            seed(connection)
        result = list_requirements(self.database, {'page': 2})
        self.assertEqual(result['data'], {'items': [], 'page': 2, 'page_size': 20, 'total': 1, 'total_pages': 1})

    def test_stable_twenty_item_pages_order_time_then_id_descending(self):
        with self.database.transaction(write=True) as connection:
            for identity in range(1, 44):
                seed(connection, identity, updated=LATER if identity in (3, 5) else TIME)
        expected = [5, 3] + [identity for identity in range(43, 0, -1) if identity not in (3, 5)]
        for page in range(1, 4):
            result = list_requirements(self.database, {'page': page})
            self.assertEqual([item['id'] for item in result['data']['items']], expected[(page - 1) * 20:page * 20])
            self.assertEqual(result['data']['total'], 43)
            self.assertEqual(result['data']['total_pages'], 3)
            self.assertTrue(all(tuple(item) == LIST_FIELDS for item in result['data']['items']))

    def test_complete_number_is_case_insensitive_and_never_falls_back(self):
        with self.database.transaction(write=True) as connection:
            seed(connection, 1, title='REQ000099')
            seed(connection, 2, title='REQ 的标题')
        self.assertEqual(self.ids({'keyword': ' reQ000001 '}), [1])
        self.assertEqual(self.ids({'keyword': 'REQ000099'}), [])
        self.assertEqual(self.ids({'keyword': 'REQ'}), [2, 1])

    def test_title_search_is_literal_case_sensitive_and_sql_bound(self):
        with self.database.transaction(write=True) as connection:
            seed(connection, 1, title='Alpha_%工具')
            seed(connection, 2, title='alpha其他')
            seed(connection, 3, title="x' OR 1=1 --")
        for term, ids in [('Alpha', [1]), ('alpha', [2]), ('_', [1]), ('%', [1]), ("' OR 1=1 --", [3]), ('%alpha%', [])]:
            with self.subTest(term=term):
                self.assertEqual(self.ids({'keyword': term}), ids)

    def test_optional_keyword_unicode_trim_and_codepoint_limit(self):
        with self.database.transaction(write=True) as connection:
            seed(connection, 1, title='😀需求')
        for request in ({}, {'keyword': None}, {'keyword': ''}, {'keyword': '\u3000\r\n\t\u00a0'}, {'keyword': '\u3000😀\u3000'}, {'keyword': '😀' * 100}):
            with self.subTest(request=request):
                result = list_requirements(self.database, request)
                self.assertEqual(result['code'], 'READ_OK')
        for value in ('😀' * 101, '甲\r\n乙', '\ud800', 1, True, []):
            with self.subTest(value=repr(value)):
                result = list_requirements(self.database, {'keyword': value})
                self.assertEqual(result['code'], 'INVALID_INPUT')
                self.assertIsNone(result['data'])
                self.assertEqual(result['details']['field_errors'][0]['field'], 'keyword')

    def test_same_field_or_cross_field_and_duplicate_and_all_selected_rules(self):
        with self.database.transaction(write=True) as connection:
            seed(connection, 1, title='筛选甲')
            seed(connection, 2, title='筛选乙', status='ACTIVE')
            seed(connection, 3, title='筛选丙', kind='CHANGE', status='COMPLETED')
            seed(connection, 4, title='其他', kind='CHANGE', status='ACTIVE')
        self.assertEqual(self.ids({'status': ['INITIALIZING', 'ACTIVE', 'ACTIVE']}), [4, 2, 1])
        self.assertEqual(self.ids({'status': ['ACTIVE', 'COMPLETED'], 'requirement_type': ['CHANGE'], 'keyword': '筛选'}), [3])
        self.assertEqual(self.ids({'status': ['COMPLETED', 'ACTIVE', 'INITIALIZING', 'ACTIVE'], 'requirement_type': ['CHANGE', 'NEW']}), [4, 3, 2, 1])
        self.assertEqual(self.ids({'status': [], 'requirement_type': []}), [4, 3, 2, 1])

    def test_array_filters_reject_null_csv_empty_unknown_and_nonarrays(self):
        for field in ('status', 'requirement_type'):
            for value in (None, '', 'ACTIVE,COMPLETED', {}, True, [''], ['unknown'], [1], ['ACTIVE', None]):
                with self.subTest(field=field, value=value):
                    result = list_requirements(self.database, {field: value})
                    self.assertEqual(result['code'], 'INVALID_INPUT')
                    self.assertIsNone(result['data'])
                    self.assertTrue(result['details']['field_errors'][0]['field'].startswith(field))

    def test_application_page_is_strict_parsed_integer_and_unknown_fields_rejected(self):
        for value in (None, True, False, '1', '01', 1.0, 0, -1, 100001, [], {}):
            with self.subTest(value=value):
                result = list_requirements(self.database, {'page': value})
                self.assertEqual(result['code'], 'INVALID_INPUT')
                self.assertEqual(result['details']['field_errors'][0]['field'], 'page')
        for payload in (None, [], {'size': 1}, {'scope_type': 'DOCUMENT'}):
            self.assertEqual(list_requirements(self.database, payload)['code'], 'INVALID_INPUT')

    def test_detail_projects_fifteen_fields_and_never_reads_document_body(self):
        with self.database.transaction(write=True) as connection:
            seed(connection, status='COMPLETED', initialization_mode='DESIGN')
            connection.execute("INSERT INTO requirement_documents VALUES (9,1,'CURRENT','body must stay separate','{}',1,?,?)", (TIME, TIME))
        result = get_requirement(self.database, 1)
        self.assertEqual(result['code'], 'READ_OK')
        self.assertEqual(tuple(result['data']), READ_FIELDS)
        self.assertEqual(result['data']['completed_at'], TIME)
        self.assertEqual(result['data']['initialization_mode'], 'DESIGN')
        self.assertIsNone(result['data']['active_operation_id'])
        result['data']['title'] = 'caller mutation'
        self.assertEqual(get_requirement(self.database, 1)['data']['title'], '需求甲')

    def test_detail_projects_all_explicit_occupancy_variants_without_repair(self):
        with self.database.transaction(write=True) as connection:
            for identity, work, operation in ((1, 'MANUAL_EDITING', 'MANUAL_DRAFT'), (2, 'GUIDE_ACTIVE', 'GUIDE_RUN'), (3, 'SUGGESTION_REVIEWING', 'SUGGESTION_BATCH')):
                seed(connection, identity, document_work_state=work, active_operation_type=operation, active_operation_id=101, state_started_at=TIME)
        for identity in (1, 2, 3):
            result = get_requirement(self.database, identity)
            self.assertEqual(result['code'], 'READ_OK')
            self.assertEqual(result['data']['active_operation_id'], 101)
            self.assertEqual(result['data']['state_started_at'], TIME)
        # This unit projects the root, not cross-aggregate consistency/adoption.

    def test_detail_missing_and_safe_integer_validation(self):
        self.assertEqual(get_requirement(self.database, MAX_SAFE_INTEGER), {'code': 'NOT_FOUND', 'data': None, 'details': None})
        self.assertEqual(get_requirement(self.database)['code'], 'INVALID_INPUT')
        for value in (None, True, '1', 1.0, 0, -1, MAX_SAFE_INTEGER + 1, {'requirement_id': 1}):
            with self.subTest(value=value):
                result = get_requirement(self.database, value)
                self.assertEqual(result['code'], 'INVALID_INPUT')
                self.assertEqual(result['details']['field_errors'][0]['field'], 'requirement_id')

    def test_queries_do_not_change_rows_clocks_sequences_or_idempotency(self):
        with self.database.transaction(write=True) as connection:
            seed(connection)
        def facts():
            with closing(sqlite3.connect(self.path)) as connection:
                return list(connection.iterdump())
        before = facts()
        self.ids()
        self.ids({'keyword': 'missing'})
        get_requirement(self.database, 1)
        get_requirement(self.database, 2)
        self.assertEqual(facts(), before)

    def test_uninitialized_storage_does_not_return_fake_empty_or_create_database(self):
        path = Path(self.directory.name) / 'missing.sqlite'
        database = Database(path)
        for result in (list_requirements(database), get_requirement(database, 1)):
            self.assertEqual(result, {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None})
        self.assertFalse(path.exists())
        self.assertEqual(list_requirements(database, {'page': False})['code'], 'INVALID_INPUT')

    def test_invalid_persisted_values_fail_conversion_without_repair_or_input_blame(self):
        with self.database.transaction(write=True) as connection:
            seed(connection, title=' 未标准化 ', updated='2026-99-04T04:00:00.000Z')
        for result in (list_requirements(self.database), get_requirement(self.database, 1)):
            self.assertEqual(result, {'code': 'INTERNAL_ERROR', 'data': None, 'details': None})
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT title,updated_at FROM requirements').fetchone()[:], (' 未标准化 ', '2026-99-04T04:00:00.000Z'))
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET title='需求甲'")
        self.assertEqual(get_requirement(self.database, 1)['code'], 'INTERNAL_ERROR')

    def test_schema_mismatch_is_not_not_found_or_empty_success(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=3")
            connection.commit()
        for result in (list_requirements(self.database), get_requirement(self.database, 1)):
            self.assertEqual(result, {'code': 'INTERNAL_ERROR', 'data': None, 'details': None})

    def test_actual_wal_writer_commits_between_count_and_items_but_reader_keeps_snapshot(self):
        with self.database.transaction(write=True) as connection:
            for identity in range(1, 22):
                seed(connection, identity)
        counted, committed = Event(), Event()
        original_count = RequirementRepository._count
        def pause_after_real_count(repository, where, bindings):
            total = original_count(repository, where, bindings)
            counted.set()
            if not committed.wait(10):
                raise RuntimeError('Writer did not commit')
            return total
        def writer():
            try:
                if not counted.wait(10):
                    raise RuntimeError('Reader did not count')
                with self.database.transaction(write=True) as connection:
                    seed(connection, 22, updated=LATER)
            finally:
                committed.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            with patch.object(RequirementRepository, '_count', pause_after_real_count):
                result = list_requirements(self.database)
            future.result(timeout=12)
        self.assertEqual(result['code'], 'READ_OK', result)
        self.assertEqual(result['data']['total'], 21)
        self.assertEqual([item['id'] for item in result['data']['items']], list(range(21, 1, -1)))
        fresh = list_requirements(self.database)
        self.assertEqual(fresh['data']['total'], 22)
        self.assertEqual(fresh['data']['items'][0]['id'], 22)


if __name__ == '__main__':
    unittest.main()
