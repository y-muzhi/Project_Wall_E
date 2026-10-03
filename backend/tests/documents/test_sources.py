from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.snapshot import Provenance, assign_identities, create_snapshot, validate_snapshot
from backend.app.documents.sources import DocumentSources, close_edit_session, register_edit_session
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database, MIGRATIONS, StorageUnavailable
from backend.app.infrastructure.idempotency import Idempotency, Scope, Success
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.tests.documents.test_snapshot import TEMPLATE, T0, T1, T2
from backend.tests.infrastructure.test_database import insert_requirement


def seed_documents(connection, *, manual=True):
    insert_requirement(connection)
    # Explicit fixture only; not an application constructor or fake endpoint.
    snapshot = create_snapshot('原文\n', TEMPLATE, T0, lambda origin: origin == TEMPLATE)
    connection.execute("INSERT INTO requirement_documents VALUES (201,101,'CURRENT',?,?,1,?,?)", (snapshot.parsed.markdown, snapshot.state_json, T0, T0))
    if manual:
        connection.execute("INSERT INTO requirement_documents VALUES (202,101,'MANUAL_DRAFT',?,?,1,?,?)", (snapshot.parsed.markdown, snapshot.state_json, T0, T0))
        connection.execute('INSERT INTO manual_draft_context VALUES (202,201,1,?,?)', (snapshot.state_json, T0))
        connection.execute("UPDATE requirements SET document_work_state='MANUAL_EDITING',active_operation_type='MANUAL_DRAFT',active_operation_id=202,state_started_at=? WHERE id=101", (T0,))
    return snapshot


def remove_draft_and_release(connection):
    connection.execute('DELETE FROM manual_draft_context WHERE draft_id=202')
    connection.execute('DELETE FROM requirement_documents WHERE id=202')
    connection.execute("UPDATE requirements SET document_work_state='IDLE',active_operation_type=NULL,active_operation_id=NULL,state_started_at=NULL WHERE id=101")


def insert_guide(connection, catalog, identity, action, requirement=101):
    function = catalog.freeze(action, 'USER_INSTRUCTION')
    values = {'id': identity, 'requirement_id': requirement, 'idempotency_key': f'00000000-0000-4000-8000-{identity:012d}', 'trigger_type': 'INITIALIZE' if action == 'INITIALIZE' else 'ACTION', 'source_type': 'USER_INSTRUCTION', 'function_type': function.function_type, 'context_template_key': function.context_template, 'context_template_version': 'v1', 'prompt_version': 'v1', 'action_type': action, 'mode_snapshot': 'IDEATION' if action == 'INITIALIZE' else None, 'instruction_summary': '测试用户指令', 'scope_type': 'DOCUMENT', 'read_scope_manifest_json': '{}', 'allowed_targets_json': '{"schema_version":1,"targets":[]}', 'status': 'RUNNING', 'current_step': 'PERSISTING', 'created_at': T0, 'updated_at': T0}
    connection.execute('INSERT INTO guide_runs (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', tuple(values.values()))


class DocumentSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-sources-test-')
        self.database = Database(Path(self.directory.name) / 'real.sqlite')
        self.database.initialize()
        self.catalog = ResourceCatalog()
        with self.database.transaction(write=True) as connection:
            self.original = seed_documents(connection)

    def tearDown(self):
        self.directory.cleanup()

    def test_manual_sources_survive_commit_draft_deletion_and_fresh_transaction(self):
        origin = Provenance('USER', 'MANUAL_EDIT', 202)
        with self.database.transaction(write=True) as connection:
            register_edit_session(connection, 202, T0)
            verifier = DocumentSources(connection, 101, self.catalog)
            adopted = assign_identities('原文\n\n新增😀\n', [1, 2], 3, self.original, origin, T1, verifier)
            connection.execute('UPDATE requirement_documents SET markdown_content=?,block_state_json=?,content_version=content_version+1,updated_at=? WHERE id=201', (adopted.parsed.markdown, adopted.state_json, T2))
            remove_draft_and_release(connection)
            close_edit_session(connection, 202, 'COMPLETED', T2)
        with self.database.transaction() as connection:
            row = connection.execute('SELECT * FROM requirement_documents WHERE id=201').fetchone()
            verifier = DocumentSources(connection, 101, self.catalog)
            result = validate_snapshot(row['markdown_content'], json.loads(row['block_state_json']), verifier)
            self.assertEqual(result.by_id[2][1]['created_source_id'], 202)
            self.assertTrue(verifier(origin))
            self.assertIsNone(connection.execute('SELECT id FROM requirement_documents WHERE id=202').fetchone())
            self.assertEqual(tuple(connection.execute('SELECT status,closed_at FROM manual_edit_sessions').fetchone()), ('COMPLETED', T2))
        with self.assertRaises(RuntimeError):
            verifier(origin)

    def test_cancel_retains_minimal_source_without_committing_draft_content(self):
        with self.database.transaction(write=True) as connection:
            register_edit_session(connection, 202, T0)
            connection.execute("UPDATE requirement_documents SET markdown_content='未采用内容',content_version=2 WHERE id=202")
            remove_draft_and_release(connection)
            close_edit_session(connection, 202, 'CANCELLED', T1)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT markdown_content,content_version FROM requirement_documents WHERE id=201').fetchone()['markdown_content'], '原文\n')
            self.assertEqual(tuple(connection.execute('SELECT status,closed_at FROM manual_edit_sessions').fetchone()), ('CANCELLED', T1))
            self.assertTrue(DocumentSources(connection, 101, self.catalog)(Provenance('USER', 'MANUAL_EDIT', 202)))

    def test_failure_after_all_changes_rolls_back_body_deletion_release_and_close(self):
        with self.database.transaction(write=True) as connection:
            register_edit_session(connection, 202, T0)
        with self.assertRaisesRegex(RuntimeError, 'after close'):
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirement_documents SET markdown_content='候选',content_version=2 WHERE id=201")
                remove_draft_and_release(connection)
                close_edit_session(connection, 202, 'COMPLETED', T1)
                raise RuntimeError('after close')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT markdown_content FROM requirement_documents WHERE id=201').fetchone()[0], '原文\n')
            self.assertIsNotNone(connection.execute('SELECT id FROM requirement_documents WHERE id=202').fetchone())
            self.assertIsNotNone(connection.execute('SELECT draft_id FROM manual_draft_context WHERE draft_id=202').fetchone())
            self.assertEqual(connection.execute('SELECT document_work_state FROM requirements').fetchone()[0], 'MANUAL_EDITING')
            self.assertEqual(tuple(connection.execute('SELECT status,closed_at FROM manual_edit_sessions').fetchone()), ('EDITING', None))

    def test_cross_requirement_missing_source_role_and_real_guide_batch_relations(self):
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection, 102, 'REQ000002')
            register_edit_session(connection, 202, T0)
            insert_guide(connection, self.catalog, 501, 'INITIALIZE')
            insert_guide(connection, self.catalog, 502, 'MODIFY')
            insert_guide(connection, self.catalog, 503, 'INITIALIZE', 102)
            connection.execute("INSERT INTO suggestion_batches(id,requirement_id,guide_run_id,source_type,title,summary,status,base_content_version,created_at,updated_at) VALUES (601,101,502,'USER_INSTRUCTION','建议','测试','PENDING',1,?,?)", (T0, T0))
        with self.database.transaction() as connection:
            verifier = DocumentSources(connection, 101, self.catalog)
            for origin in (TEMPLATE, Provenance('USER', 'MANUAL_EDIT', 202), Provenance('AI', 'GUIDE_RUN', 501), Provenance('AI', 'SUGGESTION_BATCH', 601), Provenance('USER', 'SUGGESTION_BATCH', 601)):
                self.assertTrue(verifier(origin), origin)
            for origin in (Provenance('USER', 'MANUAL_EDIT', 999), Provenance('AI', 'MANUAL_EDIT', 202), Provenance('USER', 'TEMPLATE', None), Provenance('USER', 'GUIDE_RUN', 501), Provenance('AI', 'GUIDE_RUN', 502), Provenance('AI', 'GUIDE_RUN', 503), Provenance('SYSTEM', 'SUGGESTION_BATCH', 601)):
                self.assertFalse(verifier(origin), origin)
            other = DocumentSources(connection, 102, self.catalog)
            self.assertFalse(other(Provenance('USER', 'MANUAL_EDIT', 202)))
            self.assertFalse(other(Provenance('AI', 'SUGGESTION_BATCH', 601)))
            corrupt = self.original.state
            corrupt['blocks'][0].update(created_source_type='MANUAL_EDIT', created_source_id=999, created_by_type='USER')
            with self.assertRaises(DocumentInvalid):
                validate_snapshot('原文\n', corrupt, verifier)

    def test_session_identity_closed_time_and_permanent_retention_are_protected(self):
        with self.database.transaction(write=True) as connection:
            register_edit_session(connection, 202, T0)
            with self.assertRaises(DocumentInvalid):
                close_edit_session(connection, 202, 'COMPLETED', T1)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction(write=True) as connection:
                connection.execute('UPDATE manual_edit_sessions SET draft_id=203')
        with self.database.transaction(write=True) as connection:
            remove_draft_and_release(connection)
            close_edit_session(connection, 202, 'CANCELLED', T1)
        for sql in ("UPDATE manual_edit_sessions SET closed_at='2026-10-03T00:00:02.000Z'", "UPDATE manual_edit_sessions SET status='EDITING',closed_at=NULL", 'DELETE FROM manual_edit_sessions'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                with self.database.transaction(write=True) as connection:
                    connection.execute(sql)
        with self.database.transaction(write=True) as connection:
            with self.assertRaises(DocumentInvalid):
                close_edit_session(connection, 202, 'CANCELLED', T2)

    def test_register_requires_real_draft_context_version_and_write_transaction(self):
        with self.database.transaction() as connection:
            with self.assertRaises(RuntimeError):
                register_edit_session(connection, 202, T0)
        with self.database.transaction(write=True) as connection:
            for identity in (201, 999, True):
                with self.assertRaises(DocumentInvalid):
                    register_edit_session(connection, identity, T0)
            connection.execute('UPDATE manual_draft_context SET base_content_version=2')
            with self.assertRaises(DocumentInvalid):
                register_edit_session(connection, 202, T0)

    def test_unknown_commit_replays_original_success_without_second_session_close(self):
        with self.database.transaction(write=True) as connection:
            register_edit_session(connection, 202, T0)
        actual_transaction = self.database.transaction
        writes = 0
        @contextmanager
        def lose_ack(*, write=False):
            nonlocal writes
            with actual_transaction(write=write) as connection:
                yield connection
            if write:
                writes += 1
                if writes == 2:
                    raise CommitOutcomeUnknown('Injected acknowledgment loss after real commit')
        success = Success({'code': 'DRAFT_COMPLETED', 'data': {'id': 201, 'content_version': 2}, 'details': None}, 200)
        scope = Scope('APP-DOC-CMD-C03', 'Requirement:101', '00000000-0000-4000-8000-000000000009')
        with ProcessLock.for_database(self.database.path) as lock:
            self.database.transaction = lose_ack
            def operation(connection):
                connection.execute('UPDATE requirement_documents SET content_version=2 WHERE id=201')
                remove_draft_and_release(connection)
                close_edit_session(connection, 202, 'COMPLETED', T1)
                return success
            with self.assertRaises(CommitOutcomeUnknown):
                Idempotency(self.database, lock).execute(scope, {'expected_version': 1}, operation)
            self.database.transaction = actual_transaction
            replayed = Idempotency(self.database, lock).execute(scope, {'expected_version': 1}, lambda _: self.fail('must not close twice'))
            self.assertEqual(replayed, success)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_edit_sessions').fetchone()[0], 1)
            self.assertEqual(tuple(connection.execute('SELECT status,closed_at FROM manual_edit_sessions').fetchone()), ('COMPLETED', T1))
            self.assertEqual(connection.execute('SELECT content_version FROM requirement_documents WHERE id=201').fetchone()[0], 2)


class ManualSourceMigrationTests(unittest.TestCase):
    def test_v2_upgrade_backs_up_and_keeps_known_business_facts(self):
        with tempfile.TemporaryDirectory(prefix='walle-source-migration-') as directory:
            path = Path(directory) / 'real.sqlite'
            legacy = Database(path)
            legacy.migrations = MIGRATIONS[:2]  # Explicit actual v2 schema fixture.
            legacy.initialize()
            with legacy.transaction(write=True) as connection:
                seed_documents(connection, manual=False)
            result = Database(path).initialize()
            self.assertEqual(result['schema_version'], 3)
            self.assertTrue(result['migrated'])
            with closing(sqlite3.connect(result['backup_path'])) as connection:
                self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 2)
            with Database(path).transaction() as connection:
                self.assertEqual(connection.execute('SELECT markdown_content FROM requirement_documents').fetchone()[0], '原文\n')
                self.assertEqual(connection.execute('SELECT count(*) FROM manual_edit_sessions').fetchone()[0], 0)

    def test_unprovable_legacy_document_revision_or_audit_refuses_without_guessing(self):
        for kind in ('document', 'revision', 'audit'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='walle-legacy-source-') as directory:
                path = Path(directory) / 'real.sqlite'
                legacy = Database(path)
                legacy.migrations = MIGRATIONS[:2]
                legacy.initialize()
                with legacy.transaction(write=True) as connection:
                    snapshot = seed_documents(connection, manual=False)
                    state = snapshot.state
                    state['blocks'][0].update(created_by_type='USER', created_source_type='MANUAL_EDIT', created_source_id=202)
                    encoded = json.dumps(state)
                    if kind == 'document':
                        connection.execute('UPDATE requirement_documents SET block_state_json=?', (encoded,))
                    elif kind == 'revision':
                        connection.execute("INSERT INTO revisions VALUES (301,101,1,'BASELINE','原文',?,NULL,1,?)", (encoded, T0))
                    else:
                        connection.execute("INSERT INTO document_change_audits VALUES (1,101,201,'MANUAL_EDIT',202,'USER_MANUAL_EDIT',1,2,?)", (T0,))
                with self.assertRaises(StorageUnavailable):
                    Database(path).initialize()
                with closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 2)
                    self.assertEqual(connection.execute("SELECT count(*) FROM sqlite_master WHERE name='manual_edit_sessions'").fetchone()[0], 0)
                    self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)
                self.assertEqual(len(list(Path(directory).glob('*.backup.sqlite'))), 1)
