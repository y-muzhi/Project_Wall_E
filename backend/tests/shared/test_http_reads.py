"""Real ASGI requests and actual SQLite query bindings, not mock endpoints."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.documents.api import doc_router
from backend.app.documents.commands import start_manual_draft
from backend.app.documents.snapshot import Provenance, create_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.api import req_router
from backend.app.requirements.commands import complete_initialization
from backend.app.revisions.api import rev_router
from backend.app.shared.http_boundary import HttpRuntime, HTTP_REQUEST_BYTES
from backend.tests.infrastructure.test_database import insert_requirement

T0 = '2026-10-03T00:00:00.000Z'
NOW = datetime.fromisoformat('2026-10-03T00:00:01.000+00:00')
KEY = '00000000-0000-4000-8000-000000000001'


class HttpReadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-real-http-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.database = Database(self.path)
        self.database.initialize()
        self.lock = ProcessLock.for_database(self.path).acquire()
        self.catalog = ResourceCatalog()
        executor = Idempotency(self.database, self.lock, clock=lambda: NOW)
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection)
            template = self.catalog.template('NEW', 'new-requirement', 'v1')
            self.original = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), T0, DocumentSources(connection, 101, self.catalog))
            connection.execute("INSERT INTO requirement_documents VALUES (201,101,'CURRENT',?,?,7,?,?)", (self.original.parsed.markdown, self.original.state_json, T0, T0))
            connection.execute("INSERT INTO sequences VALUES ('RequirementDocument',201)")
        initialized = complete_initialization(executor, {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': KEY}, catalog=self.catalog, clock=lambda: NOW)
        self.assertEqual(initialized['code'], 'INITIALIZATION_COMPLETED')
        self.revision_id = initialized['data']['baseline_revision']['id']
        started = start_manual_draft(executor, {'requirement_id': 101, 'expected_content_version': 7, 'idempotency_key': KEY}, catalog=self.catalog, clock=lambda: NOW)
        self.assertEqual(started['code'], 'DRAFT_STARTED')
        self.draft_id = started['data']['manual_draft']['id']
        self.app = FastAPI(redirect_slashes=False)
        self.app.state.walle_runtime = HttpRuntime(self.database, self.catalog)
        for router in (req_router, doc_router, rev_router):
            self.app.include_router(router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.lock.release()
        self.directory.cleanup()

    def facts(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return list(connection.iterdump())

    def envelope(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        body = response.json()
        self.assertEqual(set(body), {'success', 'data', 'error', 'meta'})
        identity = body['meta']['request_id']
        self.assertEqual(UUID(identity).version, 4)
        self.assertEqual(str(UUID(identity)), identity)
        self.assertEqual(body['success'], status == 200)
        if status == 200:
            self.assertIsNone(body['error'])
        else:
            self.assertIsNone(body['data'])
            self.assertNotIn('pagination', body['meta'])
        return body

    def test_all_six_actual_queries_exact_projection_and_no_persistent_side_effect(self):
        before = self.facts()
        listed = self.envelope(self.client.get('/api/v1/requirements'))
        self.assertEqual(set(listed['data']), {'items'})
        self.assertEqual(listed['meta']['pagination'], {'page': 1, 'page_size': 20, 'total': 1, 'total_pages': 1})
        self.assertEqual(set(listed['data']['items'][0]), {'id', 'requirement_no', 'title', 'requirement_type', 'status', 'updated_at'})
        root = self.envelope(self.client.get('/api/v1/requirements/101'))['data']
        self.assertEqual(root['active_operation_id'], self.draft_id)
        current = self.envelope(self.client.get('/api/v1/requirements/101/current-document'))['data']
        draft = self.envelope(self.client.get('/api/v1/requirements/101/manual-draft'))['data']
        self.assertEqual((current['id'], current['content_version'], current['document_type']), (201, 7, 'CURRENT'))
        self.assertEqual((draft['id'], draft['content_version'], draft['document_type']), (self.draft_id, 1, 'MANUAL_DRAFT'))
        self.assertEqual(current['block_state_json'], self.original.state)
        self.assertIsInstance(draft['block_state_json'], dict)
        revisions = self.envelope(self.client.get('/api/v1/requirements/101/revisions'))
        self.assertEqual(revisions['data']['items'][0]['id'], self.revision_id)
        self.assertNotIn('markdown_content', revisions['data']['items'][0])
        historical = self.envelope(self.client.get(f'/api/v1/revisions/{self.revision_id}'))['data']
        self.assertEqual(historical['markdown_content'], self.original.parsed.markdown)
        self.assertEqual(historical['source_content_version'], 7)
        self.assertEqual(self.facts(), before)

    def test_query_arrays_repeats_literal_keyword_null_and_outside_actual_page(self):
        result = self.envelope(self.client.get('/api/v1/requirements?status=ACTIVE&status=ACTIVE&requirement_type=NEW&keyword=REQ000001'))
        self.assertEqual(len(result['data']['items']), 1)
        for url in ('/api/v1/requirements?keyword=null', '/api/v1/requirements?keyword=%25', '/api/v1/requirements?status=COMPLETED'):
            body = self.envelope(self.client.get(url))
            self.assertEqual(body['meta']['pagination']['total'], 0)
        for url in ('/api/v1/requirements?page=100000', '/api/v1/requirements/101/revisions?page=2'):
            body = self.envelope(self.client.get(url))
            self.assertEqual(body['data'], {'items': []})
            self.assertEqual(body['meta']['pagination']['total'], 1)

    def test_path_and_query_are_canonical_and_invalid_requests_never_invoke_application(self):
        urls = ['/api/v1/requirements/'+part for part in ('0', '01', '+1', '1.0', '1e2', 'REQ000001', '9007199254740992')]
        urls += ['/api/v1/requirements?'+query for query in ('page=0', 'page=01', 'page=%2B1', 'page=1.0', 'page=1e2', 'page=', 'page=%201', 'page=100001', 'page=1&page=1', 'keyword=x&keyword=x', 'status=', 'status=ACTIVE,COMPLETED', 'status=%5B%22ACTIVE%22%5D', 'status=active', 'status=%20ACTIVE', 'unknown=1', 'keyword=%FF')]
        urls += ['/api/v1/requirements/101?unknown=1', '/api/v1/requirements/101/revisions?page=01', '/api/v1/revisions/01']
        with patch('backend.app.requirements.api.queries.list_requirements') as listing, patch('backend.app.requirements.api.queries.get_requirement') as detail, patch('backend.app.revisions.api.queries.list_revisions') as revisions, patch('backend.app.revisions.api.queries.get_revision') as historical:
            for url in urls:
                with self.subTest(url=url):
                    body = self.envelope(self.client.get(url), 422)
                    self.assertEqual(body['error']['code'], 'VALIDATION_FAILED')
                    self.assertTrue(body['error']['details']['field_errors'])
            for application in (listing, detail, revisions, historical):
                application.assert_not_called()

    def test_get_body_is_rejected_and_ordinary_headers_are_tolerated(self):
        with patch('backend.app.documents.api.queries.get_current_document') as application:
            body = self.envelope(self.client.request('GET', '/api/v1/requirements/101/current-document', content='{}', headers={'Content-Type': 'application/json'}), 422)
            self.assertEqual(body['error']['details']['field_errors'][0]['field'], 'body')
            application.assert_not_called()
        self.envelope(self.client.get('/api/v1/requirements/101/current-document', headers={'Accept': 'application/json', 'Content-Type': 'text/plain', 'X-Custom': 'ordinary', 'Idempotency-Key': 'not-required-on-read'}))

    def test_actual_not_found_absent_draft_and_missing_current_are_distinct(self):
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
        for url in ('/api/v1/requirements/999', '/api/v1/requirements/999/current-document', '/api/v1/requirements/999/manual-draft', '/api/v1/requirements/999/revisions', '/api/v1/revisions/999'):
            self.assertEqual(self.envelope(self.client.get(url), 404)['error']['code'], 'NOT_FOUND')
        self.assertEqual(self.envelope(self.client.get('/api/v1/requirements/102/manual-draft'), 404)['error']['code'], 'MANUAL_DRAFT_NOT_FOUND')
        self.assertEqual(self.envelope(self.client.get('/api/v1/requirements/102/current-document'), 409)['error']['code'], 'WORK_STATE_INCONSISTENT')

    def test_real_application_is_called_once_with_parsed_defaults_and_each_request_gets_new_id(self):
        from backend.app.requirements.queries import list_requirements
        with patch('backend.app.requirements.api.queries.list_requirements', wraps=list_requirements) as application:
            one = self.envelope(self.client.get('/api/v1/requirements?status=ACTIVE&status=ACTIVE'))
            self.assertEqual(application.call_count, 1)
            self.assertEqual(application.call_args.args[1], {'keyword': None, 'status': ['ACTIVE'], 'requirement_type': [], 'page': 1})
        two = self.envelope(self.client.get('/api/v1/requirements'))
        self.assertNotEqual(one['meta']['request_id'], two['meta']['request_id'])

    def test_unregistered_malformed_and_leaky_application_results_become_safe_internal_error(self):
        valid = self.client.get('/api/v1/requirements/101').json()['data']
        for result in (
            {'code': 'NO_SUCH_CODE', 'data': None, 'details': {'secret': 'sensitive-provider-diagnostic'}},
            {'code': 'READ_OK', 'data': {**valid, 'prompt': 'sensitive-provider-diagnostic'}, 'details': None},
            {'code': 'READ_OK', 'data': {**valid, 'id': 102}, 'details': None},
            {'code': 'READ_OK', 'data': valid, 'details': {'secret': 'sensitive-provider-diagnostic'}},
            {'code': 'NOT_FOUND', 'data': valid, 'details': None},
            {'code': 'CONFIG_INVALID', 'data': None, 'details': None},
            {'code': 'READ_OK', 'data': valid},
        ):
            with self.subTest(code=result['code']), patch('backend.app.requirements.api.queries.get_requirement', return_value=result):
                response = self.client.get('/api/v1/requirements/101')
                self.assertEqual(self.envelope(response, 500)['error']['code'], 'INTERNAL_ERROR')
                self.assertNotIn('sensitive-provider-diagnostic', response.text)
        with patch('backend.app.requirements.api.queries.get_requirement', side_effect=RuntimeError('sensitive-provider-diagnostic')):
            response = self.client.get('/api/v1/requirements/101')
            self.envelope(response, 500)
            self.assertNotIn('sensitive-provider-diagnostic', response.text)

    def test_bad_page_or_document_projection_is_not_returned_as_empty_success(self):
        for data in (
            {'items': [], 'page': 1, 'page_size': 20, 'total': 1, 'total_pages': 1},
            {'items': [], 'page': 1, 'page_size': 20, 'total': 0, 'total_pages': 1},
            {'items': [], 'page': 2, 'page_size': 20, 'total': 0, 'total_pages': 0},
        ):
            with patch('backend.app.requirements.api.queries.list_requirements', return_value={'code': 'READ_OK', 'data': data, 'details': None}):
                self.envelope(self.client.get('/api/v1/requirements'), 500)
        valid = self.client.get('/api/v1/requirements/101/current-document').json()['data']
        for data in ({**valid, 'block_state_json': json.dumps(valid['block_state_json'])}, {**valid, 'document_type': 'MANUAL_DRAFT'}, {**valid, 'requirement_id': 102}, {**valid, 'markdown_content': 'wrong pair'}):
            with patch('backend.app.documents.api.queries.get_current_document', return_value={'code': 'READ_OK', 'data': data, 'details': None}):
                self.envelope(self.client.get('/api/v1/requirements/101/current-document'), 500)

    def test_storage_missing_and_runtime_missing_are_safe_without_initialization(self):
        missing = Path(self.directory.name) / 'never-created.sqlite'
        self.app.state.walle_runtime = HttpRuntime(Database(missing), self.catalog)
        self.assertEqual(self.envelope(self.client.get('/api/v1/requirements'), 503)['error']['code'], 'STORAGE_UNAVAILABLE')
        self.assertFalse(missing.exists())
        del self.app.state.walle_runtime
        self.envelope(self.client.get('/api/v1/requirements'), 500)
        self.assertFalse(missing.exists())

    def test_route_misses_and_unsupported_methods_stay_in_http_router(self):
        for method, url, status in (('GET', '/api/v1/requirements/', 404), ('POST', '/api/v1/requirements/101', 405), ('GET', '/api/v1/no-such-route', 404)):
            response = self.client.request(method, url)
            self.assertEqual(response.status_code, status)
            self.assertNotIn('VALIDATION_FAILED', response.text)

    def test_whole_visible_request_limit_counts_query_and_headers_before_application(self):
        with patch('backend.app.requirements.api.queries.list_requirements') as application:
            body = self.envelope(self.client.get('/api/v1/requirements', headers={'X-Large': 'x'*HTTP_REQUEST_BYTES}), 422)
            self.assertEqual(body['error']['details']['field_errors'][0]['reason'], 'TOO_LONG')
            application.assert_not_called()


if __name__ == '__main__':
    unittest.main()
