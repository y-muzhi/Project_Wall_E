"""Offline SQLite primitives, not upgrade/release admission evidence."""

from contextlib import closing
from pathlib import Path
import sqlite3
import os
from tempfile import TemporaryDirectory
import unittest

from backend.app.infrastructure.database import (
    Database,
    Migration,
    SchemaMismatch,
    StorageUnavailable,
)
from backend.app.infrastructure.data_retention import (
    capture_retained_data,
    inspect_v151_source,
    original_projections,
    verify_retained_data,
)
from backend.app.infrastructure.schema_inspection import (
    inspect_schema,
    sql_tokens,
    verify_integrity,
    verify_schema,
)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:', isolation_level=None)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('CREATE TABLE original(id INTEGER PRIMARY KEY, value)')
        self.connection.execute('BEGIN')

    def tearDown(self):
        self.connection.close()

    def test_storage_classes_json_bytes_and_null_are_not_interchangeable(self):
        digests = []
        for value in (None, 0, 0.0, '0', b'0', '', b'', '{"x":1}', '{ "x": 1 }'):
            self.connection.execute('DELETE FROM original')
            self.connection.execute('INSERT INTO original VALUES(1,?)', (value,))
            digests.append(capture_retained_data(self.connection).sha256)
        self.assertEqual(len(set(digests)), len(digests))

    def test_lengths_unicode_nul_and_raw_text_bytes_are_preserved(self):
        for first, second in (('甲\0乙', '甲乙'), ('é', 'e\u0301'), ('ab', 'a')):
            self.connection.execute('DELETE FROM original')
            self.connection.execute('INSERT INTO original VALUES(1,?)', (first,))
            before = capture_retained_data(self.connection)
            self.connection.execute('UPDATE original SET value=?', (second,))
            self.assertNotEqual(before.sha256, capture_retained_data(self.connection).sha256)
        self.connection.execute("UPDATE original SET value=CAST(X'80FF' AS TEXT)")
        before = capture_retained_data(self.connection)
        self.assertEqual(before, capture_retained_data(self.connection))

    def test_primary_key_order_ignores_insert_order_and_detects_same_count_changes(self):
        self.connection.executemany('INSERT INTO original VALUES(?,?)', [(2, 'b'), (1, 'a')])
        before = capture_retained_data(self.connection)
        self.connection.execute('DELETE FROM original')
        self.connection.executemany('INSERT INTO original VALUES(?,?)', [(1, 'a'), (2, 'b')])
        verify_retained_data(self.connection, before)
        self.connection.execute("UPDATE original SET value='changed' WHERE id=2")
        with self.assertRaises(SchemaMismatch):
            verify_retained_data(self.connection, before)

    def test_new_columns_tables_and_200_history_do_not_rewrite_old_projection(self):
        self.connection.execute(
            'CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT)'
        )
        self.connection.execute("INSERT INTO schema_migrations VALUES(151,'frozen')")
        self.connection.execute("INSERT INTO original VALUES(1,'exact')")
        before = capture_retained_data(self.connection)
        self.connection.execute('ALTER TABLE original ADD COLUMN code_owner INTEGER')
        self.connection.execute('CREATE TABLE new_tasks(id INTEGER PRIMARY KEY)')
        self.connection.execute("INSERT INTO schema_migrations VALUES(200,'upgrade')")
        verify_retained_data(self.connection, before)
        self.connection.execute("UPDATE schema_migrations SET checksum='edited' WHERE version=151")
        with self.assertRaises(SchemaMismatch):
            verify_retained_data(self.connection, before)

    def test_explicit_snapshot_required(self):
        self.connection.rollback()
        for function in (capture_retained_data, inspect_schema, verify_integrity):
            with self.assertRaises(ValueError):
                function(self.connection)

    def test_tables_without_stable_primary_key_are_rejected(self):
        self.connection.execute('CREATE TABLE no_key(value TEXT)')
        with self.assertRaises(ValueError):
            original_projections(self.connection)

    def test_sequence_values_are_included(self):
        self.connection.execute('CREATE TABLE numbered(id INTEGER PRIMARY KEY AUTOINCREMENT)')
        self.connection.execute('INSERT INTO numbered DEFAULT VALUES')
        before = capture_retained_data(self.connection)
        self.connection.execute('UPDATE sqlite_sequence SET seq=99')
        with self.assertRaises(SchemaMismatch):
            verify_retained_data(self.connection, before)

    def test_foreign_key_failure_is_not_integrity_success(self):
        self.connection.rollback()
        self.connection.execute('PRAGMA foreign_keys=OFF')
        self.connection.execute(
            'CREATE TABLE child(id INTEGER PRIMARY KEY, parent INTEGER REFERENCES original(id))'
        )
        self.connection.execute('INSERT INTO child VALUES(1,100)')
        self.connection.execute('BEGIN')
        with self.assertRaisesRegex(SchemaMismatch, 'foreign key'):
            verify_integrity(self.connection)


class SchemaInspectionTests(unittest.TestCase):
    def test_lexer_preserves_sql_semantics_and_allows_only_lexical_spacing(self):
        self.assertEqual(
            sql_tokens("CREATE TABLE t(x TEXT DEFAULT 'a  b');"),
            sql_tokens("CREATE\nTABLE t ( x TEXT DEFAULT 'a  b' ) ; -- end"),
        )
        for first, second in (
            ("DEFAULT 'a b'", "DEFAULT 'a  b'"),
            ('"a b"', '"a  b"'),
            ('x>=1', 'x> =1'),
            ('1.0', '1 . 0'),
            ('NOT NULL', 'NOTNULL'),
            ('1--2', '1 - -2'),
            ("'a''b'", "'ab'"),
        ):
            self.assertNotEqual(sql_tokens(first), sql_tokens(second))
        for invalid in ("'unterminated", '/* unterminated', '"unterminated'):
            with self.assertRaises(SchemaMismatch):
                sql_tokens(invalid)

    def test_schema_membership_constraints_predicates_and_pragma(self):
        with closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
            connection.execute('CREATE TABLE t(id INTEGER PRIMARY KEY, label TEXT)')
            connection.execute('CREATE INDEX filtered ON t(label) WHERE id>0')
            connection.execute('BEGIN')
            expected = inspect_schema(connection)
            verify_schema(connection, expected)
            connection.execute('DROP INDEX filtered')
            connection.execute('CREATE INDEX filtered ON t(label) WHERE id>=0')
            with self.assertRaisesRegex(SchemaMismatch, 'definition'):
                verify_schema(connection, expected)
            connection.execute('CREATE VIEW extra AS SELECT id FROM t')
            with self.assertRaisesRegex(SchemaMismatch, 'membership'):
                verify_schema(connection, expected)

    def test_actual_151_backup_matches_and_legacy_checksum_rejects(self):
        with TemporaryDirectory(
            prefix='v20-retention-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        ) as directory:
            source = Database(Path(directory) / 'source.sqlite')
            source.initialize()
            with source.transaction(write=True) as connection:
                connection.execute(
                    "INSERT INTO sequences(entity_kind,last_value) VALUES('proof',123)"
                )
            before = inspect_v151_source(source)
            self.assertEqual(len(before.data.tables), 17)
            backup_path = source.backup_to(Path(directory) / 'backup.sqlite')
            backup = Database(backup_path)
            # Existing backup is a genuine SQLite backup, no generated schema200.
            with closing(backup._connect()) as connection:
                connection.execute('PRAGMA journal_mode=WAL')
            self.assertEqual(inspect_v151_source(backup), before)
            with source.transaction(write=True) as connection:
                connection.execute("UPDATE sequences SET last_value=124 WHERE entity_kind='proof'")
            self.assertNotEqual(inspect_v151_source(source).data, before.data)
            with closing(sqlite3.connect(backup_path, isolation_level=None)) as connection:
                connection.execute("UPDATE schema_migrations SET checksum='altered'")
            with self.assertRaises(SchemaMismatch):
                inspect_v151_source(backup)
            self.assertEqual(Migration().version, 151)

    def test_shared_transaction_still_denies_state_changes_and_commit(self):
        with TemporaryDirectory(
            prefix='v20-guards-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        ) as directory:
            database = Database(Path(directory) / 'source.sqlite')
            database.initialize()
            for statement in (
                'PRAGMA query_only=OFF',
                'PRAGMA foreign_keys=OFF',
                'PRAGMA writable_schema=ON',
                'PRAGMA user_version=200',
                'PRAGMA journal_mode=DELETE',
                'COMMIT',
                'ROLLBACK',
                'SAVEPOINT hidden',
                "INSERT INTO sequences VALUES('unexpected',1)",
            ):
                with self.subTest(statement=statement), self.assertRaises(StorageUnavailable):
                    with database.transaction() as connection:
                        connection.execute(statement)
            with database.transaction() as connection:
                self.assertTrue(connection.execute('PRAGMA table_xinfo(requirements)').fetchall())
                self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
                self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0], 1)

    def test_open_wal_is_backed_up_without_copying_main_file(self):
        with TemporaryDirectory(
            prefix='v20-wal-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        ) as directory:
            source = Database(Path(directory) / 'source.sqlite')
            source.initialize()
            with closing(source._connect()) as keeper:
                keeper.execute("INSERT INTO sequences VALUES('wal-only',321)")
                self.assertGreater(Path(str(source.path) + '-wal').stat().st_size, 0)
                before = inspect_v151_source(source)
                target = Database(source.backup_to(Path(directory) / 'backup.sqlite'))
                self.assertEqual(inspect_v151_source(target), before)
                self.assertEqual(keeper.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def test_sqlite_prefix_lookalike_is_not_hidden_from_validation(self):
        self.assertNotEqual(sql_tokens('1_000'), sql_tokens('1 _000'))
        with TemporaryDirectory(
            prefix='v20-extra-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        ) as directory:
            source = Database(Path(directory) / 'source.sqlite')
            source.initialize()
            with closing(sqlite3.connect(source.path, isolation_level=None)) as connection:
                connection.execute('CREATE TABLE sqliteX_hidden(id INTEGER PRIMARY KEY)')
                connection.execute('BEGIN')
                self.assertIn(
                    'sqliteX_hidden', {obj.name for obj in inspect_schema(connection).objects}
                )
                self.assertIn(
                    'sqliteX_hidden', {item.table for item in original_projections(connection)}
                )
                connection.commit()
            with self.assertRaises(SchemaMismatch):
                inspect_v151_source(source)

    def test_source_rechecks_exact_schema_inside_its_read_snapshot(self):
        from unittest.mock import patch

        with TemporaryDirectory(
            prefix='v20-race-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        ) as directory:
            source = Database(Path(directory) / 'source.sqlite')
            source.initialize()
            original = source._check_schema
            calls = []

            def check_then_change(connection):
                result = original(connection)
                calls.append(True)
                if len(calls) == 1:
                    with closing(sqlite3.connect(source.path, isolation_level=None)) as writer:
                        writer.execute('CREATE TABLE external_change(id INTEGER PRIMARY KEY)')
                return result

            with patch.object(source, '_check_schema', side_effect=check_then_change):
                with self.assertRaises(SchemaMismatch):
                    inspect_v151_source(source)

    def test_typed_manifest_uses_one_wal_read_snapshot(self):
        with TemporaryDirectory(
            prefix='v20-snapshot-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        ) as directory:
            source = Database(Path(directory) / 'source.sqlite')
            source.initialize()
            with source.transaction(write=True) as connection:
                connection.execute("INSERT INTO sequences VALUES('snapshot',1)")
            with source.transaction() as reader:
                before = capture_retained_data(reader)
                with closing(source._connect()) as writer:
                    writer.execute("UPDATE sequences SET last_value=2 WHERE entity_kind='snapshot'")
                self.assertEqual(capture_retained_data(reader), before)
            self.assertNotEqual(inspect_v151_source(source).data, before)
