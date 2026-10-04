"""Actual immutable revision reads and same-snapshot pagination."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from backend.app.documents.snapshot import Provenance, assign_identities
from backend.app.documents.sources import DocumentSources, close_edit_session, register_edit_session
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.revisions.contracts import SUMMARY_FIELDS
from backend.app.revisions.queries import get_revision, list_revisions
from backend.tests.documents.test_snapshot import T0, T1
from backend.tests.documents.test_sources import remove_draft_and_release, seed_documents
from backend.tests.infrastructure.test_database import insert_requirement


def seed_revision(connection, identity, version, pair, *, requirement=101, description=None, source_version=7, at=T0):
    connection.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?)',
                       (identity, requirement, version, 'BASELINE' if version == 1 else 'MANUAL', pair.parsed.markdown,
                        pair.state_json, description, source_version, at))


class RevisionQueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-revision-query-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.database = Database(self.path)
        self.database.initialize()
        self.catalog = ResourceCatalog()
        with self.database.transaction(write=True) as connection:
            self.original = seed_documents(connection)
            register_edit_session(connection, 202, T0)
            insert_requirement(connection, 102, 'REQ000002')

    def tearDown(self):
        self.directory.cleanup()

    def listing(self, page=1, identity=101):
        return list_revisions(self.database, {'requirement_id': identity, 'page': page})

    def reading(self, identity):
        return get_revision(self.database, identity, catalog=self.catalog)

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def test_empty_existing_root_and_missing_root_have_distinct_results(self):
        self.assertEqual(self.listing(12), {'code': 'READ_OK', 'details': None, 'data': {
            'items': [], 'page': 12, 'page_size': 20, 'total': 0, 'total_pages': 0}})
        self.assertEqual(self.listing(identity=999), {'code': 'NOT_FOUND', 'data': None, 'details': None})
        self.assertEqual(self.reading(999), {'code': 'NOT_FOUND', 'data': None, 'details': None})

    def test_list_order_is_version_desc_not_id_or_time_and_fixed_twenty(self):
        with self.database.transaction(write=True) as connection:
            for version in range(1, 44):
                seed_revision(connection, 500 - version, version, self.original, description='初始化基线' if version == 1 else None, at=T1 if version == 1 else T0)
            seed_revision(connection, 800, 1, self.original, requirement=102)
        for page in (1, 2, 3, 4):
            result = self.listing(page)
            self.assertEqual(result['code'], 'READ_OK')
            expected = list(range(43, 0, -1))[(page - 1) * 20:page * 20]
            self.assertEqual([item['version_no'] for item in result['data']['items']], expected)
            self.assertEqual(result['data']['total'], 43)
            self.assertEqual(result['data']['total_pages'], 3)
            self.assertEqual(result['data']['page'], page)
            self.assertTrue(all(tuple(item) == SUMMARY_FIELDS for item in result['data']['items']))
        self.assertEqual(self.listing(identity=102)['data']['total'], 1)

    def test_snapshot_returns_nine_fields_from_history_and_not_current_body(self):
        with self.database.transaction(write=True) as connection:
            seed_revision(connection, 301, 1, self.original, description='初始化基线', source_version=7)
            connection.execute("UPDATE requirement_documents SET markdown_content='different current body',block_state_json='{}',content_version=99 WHERE id=201")
        result = self.reading(301)
        self.assertEqual(result['code'], 'READ_OK')
        self.assertEqual(tuple(result['data']), (*SUMMARY_FIELDS, 'markdown_content', 'block_state_json'))
        self.assertEqual(result['data']['markdown_content'], '原文\n')
        self.assertEqual(result['data']['block_state_json'], self.original.state)
        self.assertEqual(result['data']['source_content_version'], 7)
        self.assertNotIn('document_type', result['data'])
        self.assertNotIn('comments', result['data'])
        result['data']['block_state_json']['blocks'].clear()
        self.assertEqual(self.reading(301)['data']['block_state_json'], self.original.state)
        self.assertEqual(get_revision(self.database, 301)['code'], 'READ_OK')

    def test_history_uses_real_closed_manual_source_after_draft_deleted(self):
        with self.database.transaction(write=True) as connection:
            pair = assign_identities('原文\n\n人工😀\n', [1, 2], 3, self.original, Provenance('USER', 'MANUAL_EDIT', 202), T1, DocumentSources(connection, 101, self.catalog))
            seed_revision(connection, 301, 1, self.original)
            seed_revision(connection, 302, 2, pair, at=T1)
            remove_draft_and_release(connection)
            close_edit_session(connection, 202, 'COMPLETED', T1)
        self.assertEqual(self.reading(302)['code'], 'READ_OK')
        self.assertEqual(self.reading(302)['data']['block_state_json']['blocks'][1]['created_source_id'], 202)

    def test_malformed_history_pair_is_not_replaced_by_valid_current(self):
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO revisions VALUES (301,101,1,'BASELINE','historical', '{}',NULL,1,?)", (T0,))
        before = self.facts()
        self.assertEqual(self.reading(301), {'code': 'INTERNAL_ERROR', 'data': None, 'details': None})
        # Summary intentionally does not materialize a body or pair.
        self.assertEqual(self.listing()['code'], 'READ_OK')
        self.assertEqual(self.facts(), before)

    def test_bad_source_wrong_root_or_role_fails_without_current_substitution(self):
        state = self.original.state
        state['blocks'][0]['created_by_type'] = 'USER'
        state['blocks'][0]['created_source_type'] = 'MANUAL_EDIT'
        state['blocks'][0]['created_source_id'] = 202
        import json
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO revisions VALUES (301,102,1,'BASELINE','原文\n',?,NULL,1,?)", (json.dumps(state), T0))
        self.assertEqual(self.reading(301), {'code': 'INTERNAL_ERROR', 'data': None, 'details': None})
        with self.database.transaction(write=True) as connection:
            state['blocks'][0]['created_source_id'] = 999
            connection.execute("INSERT INTO revisions VALUES (302,101,1,'BASELINE','原文\n',?,NULL,1,?)", (json.dumps(state), T0))
        self.assertEqual(self.reading(302)['code'], 'INTERNAL_ERROR')

    def test_invalid_persisted_summary_is_conversion_failure_and_preserved(self):
        with self.database.transaction(write=True) as connection:
            seed_revision(connection, 301, 1, self.original, description=' 未标准化 ')
            seed_revision(connection, 302, 2, self.original, requirement=102, at='2026-99-04T00:00:00.000Z')
        before = self.facts()
        for identity in (101, 102):
            self.assertEqual(self.listing(identity=identity), {'code': 'INTERNAL_ERROR', 'data': None, 'details': None})
        for identity in (301, 302):
            self.assertEqual(self.reading(identity)['code'], 'INTERNAL_ERROR')
        self.assertEqual(self.facts(), before)

    def test_input_validation_rejects_extra_filters_and_unparsed_ids_and_pages(self):
        for payload in (None, [], {}, {'requirement_id': 101, 'keyword': 'foo'}, {'requirement_id': None}, {'requirement_id': True}, {'requirement_id': '101'}, {'requirement_id': 101, 'page': None}, {'requirement_id': 101, 'page': '1'}, {'requirement_id': 101, 'page': 100001}, {'requirement_id': 101, 'page': True}):
            self.assertEqual(list_revisions(self.database, payload)['code'], 'INVALID_INPUT')
        self.assertEqual(list_revisions(self.database)['code'], 'INVALID_INPUT')
        self.assertEqual(list_revisions(self.database, {'requirement_id': 101})['data']['page'], 1)
        for identity in (None, True, '301', 1.0, 0, 9007199254740992, {'revision_id': 301}):
            result = get_revision(self.database, identity)
            self.assertEqual(result['code'], 'INVALID_INPUT')
            self.assertEqual(result['details']['field_errors'][0]['field'], 'revision_id')
        self.assertEqual(get_revision(self.database)['code'], 'INVALID_INPUT')

    def test_missing_storage_and_read_paths_have_no_fake_success_or_writes(self):
        with self.database.transaction(write=True) as connection:
            seed_revision(connection, 301, 1, self.original)
        before = self.facts()
        self.listing()
        self.reading(301)
        self.reading(999)
        self.assertEqual(self.facts(), before)
        path = Path(self.directory.name) / 'absent.sqlite'
        database = Database(path)
        for result in (list_revisions(database, {'requirement_id': 101}), get_revision(database, 301)):
            self.assertEqual(result, {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None})
        self.assertFalse(path.exists())

    def test_list_and_count_share_actual_snapshot_while_new_revision_commits(self):
        with self.database.transaction(write=True) as connection:
            for version in range(1, 22):
                seed_revision(connection, 300 + version, version, self.original)
        counted, committed = Event(), Event()
        original_count = RevisionRepository._count
        def pause_after_count(repository, identity):
            total = original_count(repository, identity)
            counted.set()
            if not committed.wait(10):
                raise RuntimeError('Writer did not commit')
            return total
        def writer():
            try:
                if not counted.wait(10):
                    raise RuntimeError('Reader did not count')
                with self.database.transaction(write=True) as connection:
                    seed_revision(connection, 322, 22, self.original)
            finally:
                committed.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            with patch.object(RevisionRepository, '_count', pause_after_count):
                result = self.listing()
            future.result(timeout=12)
        self.assertEqual(result['code'], 'READ_OK', result)
        self.assertEqual(result['data']['total'], 21)
        self.assertEqual([item['version_no'] for item in result['data']['items']], list(range(21, 1, -1)))
        fresh = self.listing()
        self.assertEqual(fresh['data']['total'], 22)
        self.assertEqual(fresh['data']['items'][0]['version_no'], 22)


if __name__ == '__main__':
    unittest.main()
