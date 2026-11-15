"""Explicit Schema200 initialization and exact origin/history checks, isolated only."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import sqlite3
import unittest

from backend.app.infrastructure.database import (
    Database,
    Migration,
    SchemaMismatch,
    StorageUnavailable,
)
from backend.app.infrastructure.schema_inspection import verify_integrity
from backend.app.infrastructure.schema_v20_release import (
    build_candidate,
    _load_verified_release,
    digest,
)
from backend.app.infrastructure.sqlite_runtime import require_active, RuntimeNotAdmitted

try:
    require_active()
    ACTIVE = True
except RuntimeNotAdmitted:
    ACTIVE = False


@unittest.skipUnless(ACTIVE, 'Run through tools/python-v20.py')
class SchemaStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TemporaryDirectory(
            prefix='v20-state-', dir=os.environ.get('WALLE_CHECK_TEMP', Path.cwd() / '.tmp')
        )
        cls.root = Path(cls.context.name)
        files = build_candidate('state-test')
        package = cls.root / 'package'
        package.mkdir()
        for name, content in files.items():
            with (package / name).open('xb') as stream:
                stream.write(content)
        cls.release = _load_verified_release(package, digest(files['manifest.json']))

    @classmethod
    def tearDownClass(cls):
        cls.context.cleanup()

    def database(self, name):
        return Database(self.root / (name + '.sqlite'), schema_release=self.release)

    def test_explicit_fresh_and_repeat_verify_only_real_200_history(self):
        database = self.database('fresh')
        first = database.initialize()
        self.assertTrue(first['initialized'])
        self.assertEqual(first['schema_version'], 200)
        with database.transaction() as connection:
            self.assertEqual(
                [
                    tuple(row)
                    for row in connection.execute('SELECT version,checksum FROM schema_migrations')
                ],
                [(200, self.release.fresh_checksum)],
            )
            state = connection.execute('SELECT * FROM code_schema_state').fetchone()
            self.assertEqual(state['origin'], 'FRESH_V20')
            self.assertIsNone(state['upgrade_id'])
            verify_integrity(connection)
        self.assertFalse(database.initialize()['initialized'])
        with self.assertRaises(SchemaMismatch):
            with Database(database.path).transaction():
                self.fail('151 must refuse 200')

    def test_151_is_never_implicitly_upgraded_by_init_or_read(self):
        path = self.root / 'old.sqlite'
        old = Database(path)
        old.initialize()
        before = path.read_bytes()
        current = Database(path, schema_release=self.release)
        with self.assertRaises(SchemaMismatch):
            current.initialize()
        with self.assertRaises(SchemaMismatch):
            with current.transaction():
                self.fail('151 cannot be used as 200')
        with old.transaction() as connection:
            self.assertEqual(
                connection.execute('SELECT version FROM schema_migrations').fetchone()[0], 151
            )
        self.assertEqual(path.read_bytes(), before)

    def test_view_only_nonempty_database_is_not_overwritten(self):
        database = self.database('view')
        with closing(sqlite3.connect(database.path, isolation_level=None)) as connection:
            connection.execute('CREATE VIEW retained_view AS SELECT 1')
        with self.assertRaises(SchemaMismatch):
            database.initialize()
        with closing(sqlite3.connect(database.path, isolation_level=None)) as connection:
            self.assertEqual(connection.execute('SELECT * FROM retained_view').fetchone(), (1,))
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_schema WHERE name='code_tasks'"
                ).fetchone()
            )

    def test_missing_and_forged_history_or_extra_objects_are_refused(self):
        for mode in ('missing', 'forged', 'extra'):
            with self.subTest(mode=mode):
                database = self.database(mode)
                database.initialize()
                with closing(sqlite3.connect(database.path, isolation_level=None)) as connection:
                    if mode == 'missing':
                        connection.execute('DELETE FROM schema_migrations')
                    elif mode == 'forged':
                        connection.execute('UPDATE schema_migrations SET checksum=?', ('0' * 64,))
                    else:
                        connection.execute('CREATE TABLE unexpected(value TEXT)')
                with self.assertRaises(SchemaMismatch):
                    with database.transaction():
                        self.fail('Changed history or objects must be refused')

    def test_two_paths_must_be_explicit_and_missing_db_is_not_auto_created(self):
        with self.assertRaises(ValueError):
            Database(self.root / 'mixed.sqlite', migration=Migration(), schema_release=self.release)
        missing = self.database('missing-file')
        with self.assertRaises(StorageUnavailable):
            with missing.transaction():
                self.fail('Reads cannot initialize')
        self.assertFalse(missing.path.exists())

    def test_real_upgrade_marker_allows_subsequent_document_business_writes(self):
        from backend.app.infrastructure.idempotency import Idempotency
        from backend.app.infrastructure.process_lock import ProcessLock
        from backend.app.infrastructure.data_retention import (
            capture_retained_data,
            verify_retained_data,
        )
        from backend.app.infrastructure.database import _statements
        from backend.tests.requirements.test_v15_foundation import create

        path = self.root / 'upgraded.sqlite'
        source = Database(path)
        source.initialize()
        with ProcessLock.for_database(path) as lock:
            self.assertEqual(create(Idempotency(source, lock))['code'], 'CREATED')
        with source.transaction() as connection:
            retained = capture_retained_data(connection)
        with closing(sqlite3.connect(path, isolation_level=None)) as connection:
            connection.execute('PRAGMA foreign_keys=OFF')
            connection.execute('BEGIN IMMEDIATE')
            for statement in _statements(self.release.upgrade):
                connection.execute(statement)
            connection.execute(
                'INSERT INTO schema_migrations VALUES(200,?,?)',
                (self.release.upgrade_checksum, '2026-11-04T01:00:00.000Z'),
            )
            connection.execute(
                'INSERT INTO code_schema_state VALUES(1,200,?,?,?,?,?)',
                (
                    self.release.schema_contract_sha256,
                    'UPGRADED_V151',
                    '00000000-0000-4000-8000-000000000094',
                    retained.sha256,
                    '2026-11-04T01:00:00.000Z',
                ),
            )
            verify_retained_data(connection, retained)
            connection.commit()
        current = Database(path, schema_release=self.release)
        self.assertEqual(current.initialize()['checksum'], self.release.upgrade_checksum)
        with ProcessLock.for_database(path) as lock:
            self.assertEqual(
                create(Idempotency(current, lock), title='升级后的新业务')['code'], 'CREATED'
            )
        with current.transaction() as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 2
            )
            self.assertEqual(
                connection.execute('SELECT source_data_sha256 FROM code_schema_state').fetchone()[
                    0
                ],
                retained.sha256,
            )
            verify_integrity(connection)
        backup = current.backup_to(self.root / 'upgraded-backup.sqlite')
        with Database(backup, schema_release=self.release).transaction() as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 2
            )
