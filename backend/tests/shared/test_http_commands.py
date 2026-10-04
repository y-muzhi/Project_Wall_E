"""Actual ASGI mutations, durable replay and ambiguity after real commits."""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch
from uuid import UUID

from backend.app.documents.snapshot import Provenance, create_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.shared.http_boundary import HttpRuntime, HTTP_REQUEST_BYTES
from backend.tests.shared import test_http_reads as read_fixtures
from backend.tests.infrastructure.test_database import insert_requirement

KEY = '00000000-0000-4000-8000-00000000000a'
OTHER = '00000000-0000-4000-8000-00000000000b'
THIRD = '00000000-0000-4000-8000-00000000000c'
BASE = '/api/v1/requirements/101'


class HttpCommandTests(unittest.TestCase):
    facts = read_fixtures.HttpReadTests.facts

    def setUp(self):
        read_fixtures.HttpReadTests.setUp(self)
        self.app.state.walle_runtime = HttpRuntime(self.database, self.catalog, Idempotency(self.database, self.lock))

    def tearDown(self):
        read_fixtures.HttpReadTests.tearDown(self)

    def envelope(self, response, status=200):
        self.assertEqual(response.status_code, status, response.text)
        value = response.json()
        self.assertEqual(set(value), {'success', 'data', 'error', 'meta'})
        self.assertEqual(str(UUID(value['meta']['request_id'])), value['meta']['request_id'])
        self.assertEqual(UUID(value['meta']['request_id']).version, 4)
        self.assertEqual(value['success'], status in (200, 201))
        self.assertNotIn('pagination', value['meta'])
        if status in (200, 201):
            self.assertIsNone(value['error'])
        else:
            self.assertIsNone(value['data'])
        return value

    def command(self, method, url, body=None, *, key=KEY, status=200):
        options = {'headers': {'Idempotency-Key': key}}
        if body is not None:
            options['json'] = body
        return self.envelope(self.client.request(method, url, **options), status)

    def draft(self):
        return self.envelope(self.client.get(BASE+'/manual-draft'))['data']

    def save_body(self, draft=None):
        document = draft or self.draft()
        return {'expected_version': document['content_version'], 'markdown_content': document['markdown_content'], 'block_state_json': deepcopy(document['block_state_json'])}

    def cancel(self):
        return self.command('DELETE', BASE+'/manual-draft', {'expected_version': self.draft()['content_version']})

    def seed_initializing(self):
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
            template = self.catalog.template('NEW', 'new-requirement', 'v1')
            original = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), read_fixtures.T0, DocumentSources(connection, 102, self.catalog))
            connection.execute("INSERT INTO requirement_documents VALUES (301,102,'CURRENT',?,?,9,?,?)", (original.parsed.markdown, original.state_json, read_fixtures.T0, read_fixtures.T0))
            connection.execute("UPDATE sequences SET last_value=301 WHERE entity_kind='RequirementDocument'")
        return '/api/v1/requirements/102'

    def test_patch_updates_only_submitted_fields_and_identical_value_is_no_change(self):
        current = self.envelope(self.client.get(BASE+'/current-document'))['data']
        updated = self.envelope(self.client.patch(BASE, json={'title': '  修改😀  '}))['data']
        self.assertEqual(updated['title'], '修改😀')
        self.assertEqual(self.envelope(self.client.patch(BASE, json={'title': '修改😀'}))['data']['updated_at'], updated['updated_at'])
        before = self.facts()
        self.command('PATCH', BASE, {'title': '不应写入', 'initialization_mode': 'DESIGN'}, status=409)
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.envelope(self.client.get(BASE+'/current-document'))['data'], current)

    def test_start_renames_current_version_and_replays_original_201_data(self):
        target = self.seed_initializing()
        self.command('POST', target+'/manual-draft', {'expected_version': 8}, status=409)
        from backend.app.documents.commands import start_manual_draft
        with patch('backend.app.documents.api.commands.start_manual_draft', wraps=start_manual_draft) as application:
            first = self.command('POST', target+'/manual-draft', {'expected_version': 9}, status=201)
            self.assertEqual(application.call_count, 1)
            self.assertEqual(application.call_args.args[1], {'requirement_id': 102, 'expected_content_version': 9, 'idempotency_key': KEY})
        replay = self.command('POST', target+'/manual-draft', {'expected_version': 9}, key=KEY.upper(), status=201)
        self.assertEqual(replay['data'], first['data'])
        self.assertNotEqual(replay['meta']['request_id'], first['meta']['request_id'])
        self.assertEqual(first['data']['manual_draft']['content_version'], 1)
        self.assertEqual(self.envelope(self.client.get(target+'/current-document'))['data']['content_version'], 9)

    def test_save_is_not_idempotent_and_cancel_uses_draft_version_then_old_cancel_replays(self):
        payload = self.save_body()
        saved = self.envelope(self.client.put(BASE+'/manual-draft', json=payload))['data']
        self.assertEqual(saved['content_version'], 2)
        self.command('PUT', BASE+'/manual-draft', payload, status=409)
        self.command('DELETE', BASE+'/manual-draft', {'expected_version': 1}, status=409)
        cancelled = self.command('DELETE', BASE+'/manual-draft', {'expected_version': 2})
        self.assertTrue(cancelled['data']['cancelled'])
        fresh = self.command('POST', BASE+'/manual-draft', {'expected_version': 7}, key=OTHER, status=201)['data']['manual_draft']
        replay = self.command('DELETE', BASE+'/manual-draft', {'expected_version': 2})
        self.assertEqual(replay['data'], cancelled['data'])
        self.assertEqual(self.draft()['id'], fresh['id'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT status FROM manual_edit_sessions WHERE draft_id=?', (self.draft_id,)).fetchone()[0], 'CANCELLED')
            self.assertEqual(connection.execute("SELECT count(*) FROM idempotency_records WHERE capability_id='APP-DOC-CMD-C02'").fetchone()[0], 0)

    def test_requirement_completion_and_bodyless_reactivation_replay_across_later_state(self):
        self.command('POST', BASE+'/complete', {'expected_version': 7}, status=409)
        self.cancel()
        self.command('POST', BASE+'/complete', {'expected_version': 6}, status=409)
        completed = self.command('POST', BASE+'/complete', {'expected_version': 7})['data']
        self.assertEqual(completed['status'], 'COMPLETED')
        self.assertIsNotNone(completed['completed_at'])
        revived = self.command('POST', BASE+'/reactivate')['data']
        self.assertEqual(revived['status'], 'ACTIVE')
        self.assertIsNone(revived['completed_at'])
        self.command('POST', BASE+'/complete', {'expected_version': 7}, key=OTHER)
        self.assertEqual(self.command('POST', BASE+'/reactivate')['data'], revived)
        self.assertEqual(self.envelope(self.client.get(BASE))['data']['status'], 'COMPLETED')
        self.command('POST', BASE+'/reactivate', {}, key=THIRD, status=422)

    def test_initialization_uses_its_declared_version_name_and_preserves_current(self):
        target = self.seed_initializing()
        before = self.envelope(self.client.get(target+'/current-document'))['data']
        self.command('POST', target+'/complete-initialization', {'expected_version': 9}, status=422)
        result = self.command('POST', target+'/complete-initialization', {'expected_content_version': 9})['data']
        self.assertEqual(result['requirement']['status'], 'ACTIVE')
        self.assertEqual(result['baseline_revision']['revision_type'], 'BASELINE')
        self.assertEqual(result['current_document'], {'id': 301, 'content_version': 9})
        self.assertEqual(self.envelope(self.client.get(target+'/current-document'))['data'], before)

    def test_manual_revision_201_normalized_description_and_canonical_replay(self):
        self.cancel()
        first = self.command('POST', BASE+'/revisions', {'expected_version': 7, 'description': '\r\n  备注😀 \r\n'}, status=201)['data']
        self.assertEqual((first['version_no'], first['revision_type'], first['description']), (2, 'MANUAL', '备注😀'))
        self.command('POST', BASE+'/revisions', {'expected_version': 7, 'description': None}, status=409)
        from backend.app.revisions.commands import create_manual_revision
        with patch('backend.app.revisions.api.commands.create_manual_revision', wraps=create_manual_revision) as application:
            no_description = self.command('POST', BASE+'/revisions', {'expected_version': 7}, key=OTHER, status=201)['data']
            self.assertIsNone(application.call_args.args[1]['description'])
            self.assertEqual(application.call_count, 1)
        self.assertIsNone(no_description['description'])
        for description in (None, ' \r\n '):
            self.assertEqual(self.command('POST', BASE+'/revisions', {'description': description, 'expected_version': 7}, key=OTHER, status=201)['data'], no_description)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 3)

    def test_media_root_duplicate_keys_missing_fields_and_unknown_locations_reject_before_app(self):
        examples = (
            ('{"title":"a"}', 'text/plain'), ('"string"', 'application/json'), ('[]', 'application/json'),
            ('null', 'application/json'), ('{', 'application/json'), ('{"title":"a","title":"b"}', 'application/json'),
            ('{}', 'application/json'), ('{"requirement_id":101,"title":"a"}', 'application/json'),
            ('{"title":null}', 'application/json'), ('{"title":true}', 'application/json'),
        )
        with patch('backend.app.requirements.api.commands.update_requirement') as application:
            for raw, media in examples:
                self.envelope(self.client.patch(BASE, content=raw, headers={'Content-Type': media}), 422)
            self.envelope(self.client.patch(BASE, content=''), 422)
            self.envelope(self.client.patch(BASE+'?unknown=1', json={'title': 'a'}), 422)
            application.assert_not_called()

    def test_idempotency_header_required_uuid_format_case_and_duplicates(self):
        target = self.seed_initializing()
        with patch('backend.app.documents.api.commands.start_manual_draft') as application:
            for headers in ({}, {'Idempotency-Key': 'bad'}, {'Idempotency-Key': '00000000-0000-1000-8000-000000000001'}, {'Idempotency-Key': ' '+KEY}, [('Idempotency-Key', KEY), ('idempotency-key', KEY)]):
                response = self.client.post(target+'/manual-draft', json={'expected_version': 9}, headers=headers)
                self.envelope(response, 422)
            application.assert_not_called()
        accepted = self.envelope(self.client.post(target+'/manual-draft', json={'expected_version': 9}, headers={'iDeMpOtEnCy-KeY': KEY.upper()}), 201)
        self.assertEqual(accepted['data']['requirement']['id'], 102)

    def test_nested_transport_types_and_duplicate_fields_reject_before_save(self):
        original = self.save_body()
        variants = []
        for field, value in (('schema_version', True), ('schema_version', 1.0), ('next_block_id', '10'), ('blocks', {}), ('extra', 'unregistered')):
            body = deepcopy(original); body['block_state_json'][field] = value; variants.append(body)
        for field, value in (('created_source_id', True), ('block_id', 1.0), ('section_path', 'title'), ('created_at', '2026-02-30T00:00:00.000Z'), ('extra', 'unregistered')):
            body = deepcopy(original); body['block_state_json']['blocks'][0][field] = value; variants.append(body)
        variants += [{**original, 'expected_version': True}, {**original, 'block_state_json': '{}'}, {**original, 'markdown_content': '\ud800'}]
        with patch('backend.app.documents.api.commands.save_manual_draft') as application:
            for body in variants:
                with self.subTest(body_keys=list(body)):
                    self.envelope(self.client.put(BASE+'/manual-draft', content=json.dumps(body), headers={'Content-Type': 'application/json'}), 422)
            raw = json.dumps(original).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
            self.envelope(self.client.put(BASE+'/manual-draft', content=raw, headers={'Content-Type': 'application/json'}), 422)
            application.assert_not_called()

    def test_well_typed_semantic_snapshot_failure_is_document_invalid_and_rolls_back(self):
        from backend.app.documents.commands import save_manual_draft
        payload = self.save_body()
        payload['markdown_content'] = 'one paragraph'
        before = self.facts()
        with patch('backend.app.documents.api.commands.save_manual_draft', wraps=save_manual_draft) as application:
            body = self.command('PUT', BASE+'/manual-draft', payload, status=422)
            self.assertEqual(body['error']['code'], 'DOCUMENT_INVALID')
            self.assertEqual(application.call_count, 1)
        self.assertEqual(self.facts(), before)

    def test_successful_save_then_boundary_conversion_failure_preserves_fact_and_old_version_conflicts(self):
        payload = self.save_body()
        with patch('backend.app.documents.http_models.SaveManualDraftResponse.project', side_effect=ValueError('confidential conversion fault')):
            response = self.client.put(BASE+'/manual-draft', json=payload)
            self.envelope(response, 500)
            self.assertNotIn('confidential', response.text)
        self.assertEqual(self.draft()['content_version'], 2)
        self.command('PUT', BASE+'/manual-draft', payload, status=409)

    def test_idempotent_start_then_conversion_failure_replays_actual_original_resource(self):
        target = self.seed_initializing()
        with patch('backend.app.documents.http_models.StartManualDraftResponse.project', side_effect=ValueError('injected conversion fault')):
            self.command('POST', target+'/manual-draft', {'expected_version': 9}, status=500)
        saved = self.envelope(self.client.get(target+'/manual-draft'))['data']
        replay = self.command('POST', target+'/manual-draft', {'expected_version': 9}, status=201)['data']
        self.assertEqual(replay['manual_draft'], saved)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM requirement_documents WHERE requirement_id=102 AND document_type='MANUAL_DRAFT'").fetchone()[0], 1)

    def test_actual_sql_failure_maps_storage_error_without_committing_or_leaking_sql(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER test_http_save_fault AFTER UPDATE ON requirement_documents BEGIN SELECT RAISE(ABORT,'confidential SQL failure'); END")
            connection.commit()
        payload = self.save_body()
        before = self.facts()
        response = self.client.put(BASE+'/manual-draft', json=payload)
        self.assertEqual(self.envelope(response, 503)['error']['code'], 'STORAGE_UNAVAILABLE')
        self.assertNotIn('confidential', response.text)
        self.assertEqual(self.facts(), before)

    def test_nonrequired_idempotency_header_is_ignored_and_whole_body_cap_is_not_content_length(self):
        payload = self.save_body()
        self.envelope(self.client.put(BASE+'/manual-draft', json=payload, headers={'Idempotency-Key': 'not-required'}))
        with patch('backend.app.requirements.api.commands.update_requirement') as application:
            response = self.client.patch(BASE, content=' '*HTTP_REQUEST_BYTES+'{}', headers={'Content-Type': 'application/json', 'Content-Length': '2'})
            self.assertEqual(self.envelope(response, 422)['error']['details']['field_errors'][0]['reason'], 'TOO_LONG')
            application.assert_not_called()

    def test_actual_version_exhaustion_and_missing_executor_are_not_false_success(self):
        from backend.app.shared.validation import MAX_SAFE_INTEGER
        with self.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=? WHERE id=?', (MAX_SAFE_INTEGER, self.draft_id))
        payload = self.save_body()
        before = self.facts()
        response = self.client.put(BASE+'/manual-draft', json=payload)
        self.assertEqual(self.envelope(response, 503)['error']['code'], 'CAPACITY_EXHAUSTED')
        self.assertEqual(self.facts(), before)
        self.app.state.walle_runtime = HttpRuntime(self.database, self.catalog)
        with patch('backend.app.documents.api.commands.cancel_manual_draft') as application:
            self.command('DELETE', BASE+'/manual-draft', {'expected_version': MAX_SAFE_INTEGER}, status=500)
            application.assert_not_called()
        self.assertEqual(self.facts(), before)


if __name__ == '__main__':
    unittest.main()
