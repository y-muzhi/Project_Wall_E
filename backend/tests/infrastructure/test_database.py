from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest

from backend.app.infrastructure.database import Database, Migration, SchemaMismatch, StorageUnavailable

TIME = '2026-09-21T08:30:00.000Z'


def insert_requirement(connection, identity=101, number='REQ000001'):
    connection.execute('INSERT INTO requirements(id,requirement_no,requirement_type,initialization_mode,title,template_key,template_version,status,document_work_state,active_operation_type,active_operation_id,created_at,updated_at,completed_at,state_started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (identity, number, 'NEW', 'IDEATION', '需求甲', 'new-requirement', 'v1', 'INITIALIZING', 'IDLE', None, None, TIME, TIME, None, None))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-db-test-')
        self.root = Path(self.directory.name)
        self.path = self.root / 'actual.sqlite'
        self.database = Database(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_legacy_upgrade_keeps_backup_business_and_frozen_first_migration(self):
        legacy = Database(self.path, migration=Migration())
        legacy.initialize()
        with legacy.transaction(write=True) as connection:
            insert_requirement(connection)
        upgraded = self.database.initialize()
        self.assertFalse(upgraded['initialized'])
        self.assertTrue(upgraded['migrated'])
        self.assertEqual(upgraded['schema_version'], 4)
        with closing(sqlite3.connect(upgraded['backup_path'])) as connection:
            self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT title FROM requirements').fetchone()[0], '需求甲')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT checksum FROM schema_migrations WHERE version=1').fetchone()[0], Migration().checksum)
            self.assertEqual(connection.execute('SELECT title FROM requirements').fetchone()[0], '需求甲')
        self.assertFalse(self.database.initialize()['migrated'])
        self.assertEqual(len(list(self.root.glob('*.backup.sqlite'))), 1)

    def test_upgrade_failure_rolls_back_and_preserves_legacy_corrupt_facts_for_review(self):
        legacy = Database(self.path, migration=Migration())
        legacy.initialize()
        with legacy.transaction(write=True) as connection:
            insert_requirement(connection)
            # The v1 CHECK had SQLite UNKNOWN/null behavior. The correction must
            # reject this existing invalid fact rather than guess a status code.
            connection.execute("INSERT INTO idempotency_records VALUES ('APP-REQ-CMD-C01','RequirementCollection','00000000-0000-4000-8000-000000000001','{}','SUCCEEDED','old-epoch',?,?,?,NULL)", (TIME, TIME, '{"code":"CREATED","data":{"id":101},"details":null}'))
        with self.assertRaises(StorageUnavailable):
            self.database.initialize()
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)
            self.assertIsNone(connection.execute('SELECT http_status FROM idempotency_records').fetchone()[0])
            self.assertEqual(connection.execute("SELECT count(*) FROM sqlite_master WHERE name='idempotency_success_status_insert'").fetchone()[0], 0)
        self.assertEqual(len(list(self.root.glob('*.backup.sqlite'))), 1)

    def test_success_http_status_is_required_and_success_cannot_be_rewritten_or_deleted(self):
        self.database.initialize()
        identity = ('APP-REQ-CMD-C01', 'RequirementCollection', '00000000-0000-4000-8000-000000000001')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction(write=True) as connection:
                connection.execute("INSERT INTO idempotency_records VALUES (?,?,?,'{}','SUCCEEDED','epoch',?,?,'{}',NULL)", (*identity, TIME, TIME))
        with self.database.transaction(write=True) as connection:
            connection.execute("INSERT INTO idempotency_records VALUES (?,?,?,'{}','PROCESSING','epoch',?,?,NULL,NULL)", (*identity, TIME, TIME))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE idempotency_records SET status='SUCCEEDED',success_result_json='{}'")
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE idempotency_records SET status='SUCCEEDED',success_result_json='{}',http_status=201")
        for sql in ("UPDATE idempotency_records SET http_status=200", "DELETE FROM idempotency_records"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                with self.database.transaction(write=True) as connection:
                    connection.execute(sql)
        with self.database.transaction() as connection:
            self.assertEqual(tuple(connection.execute('SELECT status,http_status FROM idempotency_records').fetchone()), ('SUCCEEDED', 201))

    def test_initialization_and_repeated_verification_preserve_data(self):
        first = self.database.initialize()
        self.assertTrue(first['initialized'])
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection)
        second = self.database.initialize()
        self.assertFalse(second['initialized'])
        self.assertEqual(first['checksum'], second['checksum'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT id,requirement_no FROM requirements').fetchone()['requirement_no'], 'REQ000001')
            self.assertEqual(connection.execute('SELECT count(*) FROM conversation_messages').fetchone()[0], 0)
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(connection.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(connection.execute('PRAGMA busy_timeout').fetchone()[0], 5000)
            self.assertEqual(connection.execute('PRAGMA read_uncommitted').fetchone()[0], 0)

    def test_uninitialized_access_does_not_create_empty_database(self):
        with self.assertRaises(StorageUnavailable):
            with self.database.transaction():
                pass
        self.assertFalse(self.path.exists())

    def test_unknown_schema_refuses_without_erasing_existing_data(self):
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute('CREATE TABLE existing_data(value TEXT)')
            connection.execute("INSERT INTO existing_data VALUES ('keep-me')")
        with self.assertRaises(SchemaMismatch):
            self.database.initialize()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            self.assertEqual(connection.execute('SELECT value FROM existing_data').fetchone()[0], 'keep-me')

    def test_version_checksum_and_missing_object_are_distinct_startup_failures(self):
        self.database.initialize()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute('UPDATE schema_migrations SET version=5 WHERE version=4')
        with self.assertRaises(SchemaMismatch):
            self.database.initialize()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute('UPDATE schema_migrations SET version=4 WHERE version=5')
            connection.execute('UPDATE schema_migrations SET checksum=? WHERE version=1', ('wrong-checksum',))
        with self.assertRaises(SchemaMismatch):
            self.database.initialize()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            connection.execute('UPDATE schema_migrations SET checksum=? WHERE version=1', (Migration().checksum,))
            connection.execute('DROP INDEX revisions_one_baseline')
        with self.assertRaisesRegex(SchemaMismatch, 'revisions_one_baseline'):
            with self.database.transaction():
                pass

    def test_schema_creation_failure_has_no_partial_tables_and_can_retry(self):
        migration_path = self.root / 'broken.sql'
        migration_path.write_text('CREATE TABLE halfway(id INTEGER PRIMARY KEY);\nBROKEN SQL;\n', encoding='utf-8')
        failing = Database(self.path, migration=Migration(migration_path))
        with self.assertRaises(StorageUnavailable):
            failing.initialize()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM sqlite_master WHERE name='halfway'").fetchone()[0], 0)
        self.assertTrue(self.database.initialize()['initialized'])

    def test_shared_write_connection_commit_and_full_rollback(self):
        self.database.initialize()
        with self.assertRaisesRegex(RuntimeError, 'injected after second table'):
            with self.database.transaction(write=True) as connection:
                insert_requirement(connection)
                connection.execute('INSERT INTO sequences(entity_kind,last_value) VALUES (?,?)', ('Requirement', 101))
                raise RuntimeError('injected after second table')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM sequences').fetchone()[0], 0)
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection)
            connection.execute('INSERT INTO sequences(entity_kind,last_value) VALUES (?,?)', ('Requirement', 101))
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT last_value FROM sequences').fetchone()[0], 101)

    def test_unique_identity_and_number_competition_with_real_writers(self):
        self.database.initialize()
        barrier = Barrier(2)

        def write(identity):
            barrier.wait(timeout=5)
            try:
                with self.database.transaction(write=True) as connection:
                    insert_requirement(connection, identity=identity)
                return 'committed'
            except sqlite3.IntegrityError:
                return 'unique_conflict'

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(write, [101, 102]))
        self.assertCountEqual(outcomes, ['committed', 'unique_conflict'])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)

    def test_read_snapshot_stays_consistent_across_interleaved_committed_writer(self):
        self.database.initialize()
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection)
        with self.database.transaction() as reader:
            before = reader.execute('SELECT count(*) FROM requirements').fetchone()[0]
            with self.database.transaction(write=True) as writer:
                insert_requirement(writer, 102, 'REQ000002')
            same_snapshot_items = [row[0] for row in reader.execute('SELECT id FROM requirements ORDER BY id')]
            after = reader.execute('SELECT count(*) FROM requirements').fetchone()[0]
        self.assertEqual((before, after, same_snapshot_items), (1, 1, [101]))
        with self.database.transaction() as fresh:
            self.assertEqual(fresh.execute('SELECT count(*) FROM requirements').fetchone()[0], 2)

    def test_query_only_blocks_accidental_business_write(self):
        self.database.initialize()
        with self.assertRaises(StorageUnavailable):
            with self.database.transaction() as connection:
                insert_requirement(connection)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 0)

    def test_lock_exhaustion_is_known_failure_without_second_writer_effect(self):
        self.database.initialize()
        contender = Database(self.path, busy_timeout_ms=0)
        with self.database.transaction(write=True) as first:
            insert_requirement(first)
            with self.assertRaises(StorageUnavailable):
                with contender.transaction(write=True):
                    self.fail('Second writer must not obtain the write gate')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)

    def test_backup_api_preserves_source_and_refuses_overwrite(self):
        self.database.initialize()
        with self.database.transaction(write=True) as connection:
            insert_requirement(connection)
        backup = self.database.backup_to(self.root / 'saved.sqlite')
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute('SELECT requirement_no FROM requirements').fetchone()[0], 'REQ000001')
        with self.assertRaises(ValueError):
            self.database.backup_to(backup)
        with self.assertRaises(ValueError):
            self.database.backup_to(self.path)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)

    def test_repository_cannot_commit_or_change_transaction_controls(self):
        self.database.initialize()
        for command in ('COMMIT', 'ROLLBACK', 'SAVEPOINT hidden', 'PRAGMA query_only=OFF'):
            with self.subTest(command=command):
                with self.assertRaises(StorageUnavailable):
                    with self.database.transaction(write=True) as connection:
                        insert_requirement(connection)
                        connection.cursor().execute(command)
                with self.database.transaction() as connection:
                    self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 0)
        with self.assertRaises(StorageUnavailable):
            with self.database.transaction(write=True) as connection:
                insert_requirement(connection)
                connection.commit()
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
