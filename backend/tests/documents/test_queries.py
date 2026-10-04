"""Actual document/draft read snapshots and durable source relations."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from backend.app.documents.contracts import DOCUMENT_FIELDS
from backend.app.documents.queries import get_current_document, get_manual_draft
from backend.app.documents.snapshot import Provenance, assign_identities, create_snapshot
from backend.app.documents.sources import DocumentSources, close_edit_session, register_edit_session
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.tests.documents.test_snapshot import TEMPLATE, T0, T1
from backend.tests.documents.test_sources import remove_draft_and_release, seed_documents
from backend.tests.infrastructure.test_database import insert_requirement


class DocumentQueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-document-query-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.database = Database(self.path)
        self.database.initialize()
        self.catalog = ResourceCatalog()
        with self.database.transaction(write=True) as connection:
            self.original = seed_documents(connection)
            register_edit_session(connection, 202, T0)

    def tearDown(self):
        self.directory.cleanup()

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def current(self, identity=101):
        return get_current_document(self.database, identity, catalog=self.catalog)

    def draft(self, identity=101):
        return get_manual_draft(self.database, identity, catalog=self.catalog)

    def edit_draft(self):
        with self.database.transaction(write=True) as connection:
            sources = DocumentSources(connection, 101, self.catalog)
            candidate = assign_identities('原文\n\n新增😀\n', [1, 2], 3, self.original, Provenance('USER', 'MANUAL_EDIT', 202), T1, sources)
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=?,content_version=2,updated_at=? WHERE id=202', (candidate.parsed.markdown, candidate.state_json, T1))
        return candidate

    def test_current_and_draft_are_independent_exact_eight_field_pairs(self):
        candidate = self.edit_draft()
        current, draft = self.current(), self.draft()
        for result in (current, draft):
            self.assertEqual(result['code'], 'READ_OK')
            self.assertEqual(tuple(result['data']), DOCUMENT_FIELDS)
            self.assertIs(type(result['data']['block_state_json']), dict)
        self.assertEqual((current['data']['id'], current['data']['document_type'], current['data']['content_version'], current['data']['markdown_content']), (201, 'CURRENT', 1, '原文\n'))
        self.assertEqual((draft['data']['id'], draft['data']['document_type'], draft['data']['content_version']), (202, 'MANUAL_DRAFT', 2))
        self.assertEqual(draft['data']['block_state_json'], candidate.state)
        draft['data']['block_state_json']['blocks'][1]['created_source_id'] = 999
        self.assertEqual(self.draft()['data']['block_state_json']['blocks'][1]['created_source_id'], 202)

    def test_default_resource_catalog_and_exact_markdown_bytes_are_real(self):
        markdown = '# 标题\r\n\r\n正文😀  \r\n尾行\r\n'
        with self.database.transaction(write=True) as connection:
            pair = create_snapshot(markdown, TEMPLATE, T0, DocumentSources(connection, 101, self.catalog))
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=? WHERE id=201', (markdown, pair.state_json))
        result = get_current_document(self.database, 101)
        self.assertEqual(result['code'], 'READ_OK')
        self.assertEqual(result['data']['markdown_content'], markdown)
        self.assertEqual(result['data']['block_state_json'], pair.state)

    def test_empty_body_is_success_only_with_actual_empty_snapshot(self):
        with self.database.transaction(write=True) as connection:
            pair = create_snapshot('', TEMPLATE, T0, DocumentSources(connection, 101, self.catalog))
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=? WHERE id=201', ('', pair.state_json))
        self.assertEqual(self.current()['data']['block_state_json'], {'schema_version': 1, 'next_block_id': 1, 'blocks': []})
        self.assertEqual(self.current()['data']['markdown_content'], '')

    def test_not_found_requirement_and_missing_current_are_distinct(self):
        for query in (self.current, self.draft):
            self.assertEqual(query(999), {'code': 'NOT_FOUND', 'data': None, 'details': None})
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
        self.assertEqual(self.current(102), {'code': 'WORK_STATE_INCONSISTENT', 'data': None, 'details': None})
        self.assertEqual(self.draft(102), {'code': 'MANUAL_DRAFT_NOT_FOUND', 'data': None, 'details': None})

    def test_missing_draft_and_dangling_active_reference_are_distinct(self):
        with self.database.transaction(write=True) as connection:
            connection.execute('DELETE FROM manual_draft_context WHERE draft_id=202')
            connection.execute('DELETE FROM requirement_documents WHERE id=202')
        before = self.facts()
        self.assertEqual(self.draft(), {'code': 'WORK_STATE_INCONSISTENT', 'data': None, 'details': None})
        self.assertEqual(self.facts(), before)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL")
        self.assertEqual(self.draft(), {'code': 'MANUAL_DRAFT_NOT_FOUND', 'data': None, 'details': None})

    def test_existing_draft_requires_correct_occupancy_and_identity(self):
        for assignments in ("document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL", "document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=88", 'active_operation_id=999'):
            with self.subTest(assignments=assignments):
                with self.database.transaction(write=True) as connection:
                    connection.execute('UPDATE requirements SET ' + assignments)
                before = self.facts()
                self.assertEqual(self.draft()['code'], 'WORK_STATE_INCONSISTENT')
                self.assertEqual(self.facts(), before)
                with self.database.transaction(write=True) as connection:
                    connection.execute("UPDATE requirements SET document_work_state='MANUAL_EDITING',active_operation_type='MANUAL_DRAFT',active_operation_id=202,state_started_at=?", (T0,))

    def test_completed_source_stays_readable_after_actual_draft_deletion(self):
        candidate = self.edit_draft()
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=?,content_version=2,updated_at=? WHERE id=201', (candidate.parsed.markdown, candidate.state_json, T1))
            remove_draft_and_release(connection)
            close_edit_session(connection, 202, 'COMPLETED', T1)
        result = self.current()
        self.assertEqual(result['code'], 'READ_OK')
        self.assertEqual(result['data']['block_state_json']['blocks'][1]['created_source_id'], 202)
        self.assertEqual(self.draft()['code'], 'MANUAL_DRAFT_NOT_FOUND')

    def test_bad_or_cross_requirement_source_never_returns_unverified_pair(self):
        self.edit_draft()
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
            row = connection.execute('SELECT block_state_json FROM requirement_documents WHERE id=202').fetchone()
            state = json.loads(row[0])
            state['blocks'][1]['created_source_id'] = 999
            connection.execute('UPDATE requirement_documents SET block_state_json=? WHERE id=202', (json.dumps(state),))
        before = self.facts()
        self.assertEqual(self.draft(), {'code': 'INTERNAL_ERROR', 'data': None, 'details': None})
        self.assertEqual(self.facts(), before)
        # Source 202 exists, but copying that metadata to another root is invalid.
        state['blocks'][1]['created_source_id'] = 202
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO requirement_documents VALUES (203,102,'CURRENT','原文\n\n新增😀\n',?,1,?,?)", (json.dumps(state), T0, T0))
        self.assertEqual(self.current(102)['code'], 'INTERNAL_ERROR')

    def test_snapshot_structure_duplicate_json_and_bad_time_are_not_fake_empty(self):
        for body, state, at in (('原文\n', '{}', T0), ('原文\n\n多一块\n', self.original.state_json, T0), ('原文\n', self.original.state_json[:-1] + ',"schema_version":1}', T0), ('原文\n', self.original.state_json, '2026-99-04T00:00:00.000Z')):
            with self.subTest(state=state[:30], at=at):
                with self.database.transaction(write=True) as connection:
                    connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=?,updated_at=? WHERE id=201', (body, state, at))
                before = self.facts()
                self.assertEqual(self.current(), {'code': 'INTERNAL_ERROR', 'data': None, 'details': None})
                self.assertEqual(self.facts(), before)

    def test_invalid_inputs_missing_storage_and_queries_have_no_write_effects(self):
        before = self.facts()
        for query in (get_current_document, get_manual_draft):
            for identity in (None, True, '101', 1.0, 0, 9007199254740992, {'requirement_id': 101}):
                result = query(self.database, identity)
                self.assertEqual(result['code'], 'INVALID_INPUT')
                self.assertEqual(result['details']['field_errors'][0]['field'], 'requirement_id')
            self.assertEqual(query(self.database)['code'], 'INVALID_INPUT')
            query(self.database, 101)
            path = Path(self.directory.name) / 'absent.sqlite'
            self.assertEqual(query(Database(path), 101), {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None})
            self.assertFalse(path.exists())
        self.assertEqual(self.facts(), before)

    def test_root_document_and_source_relations_share_real_read_snapshot(self):
        candidate = self.edit_draft()
        rooted, committed = Event(), Event()
        original_get = RequirementRepository.get
        def pause_after_root(repository, identity):
            root = original_get(repository, identity)
            rooted.set()
            if not committed.wait(10):
                raise RuntimeError('Competing cancellation did not commit')
            return root
        def cancel_after_root_read():
            try:
                if not rooted.wait(10):
                    raise RuntimeError('Reader did not anchor root snapshot')
                with self.database.transaction(write=True) as connection:
                    remove_draft_and_release(connection)
                    close_edit_session(connection, 202, 'CANCELLED', T1)
            finally:
                committed.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(cancel_after_root_read)
            with patch.object(RequirementRepository, 'get', pause_after_root):
                result = self.draft()
            future.result(timeout=12)
        self.assertEqual(result['code'], 'READ_OK', result)
        self.assertEqual(result['data']['block_state_json'], candidate.state)
        self.assertEqual(self.draft()['code'], 'MANUAL_DRAFT_NOT_FOUND')
        self.assertEqual(self.current()['data']['markdown_content'], '原文\n')


if __name__ == '__main__':
    unittest.main()
