"""Real v3 upgrades retain proven drafts; unknown historical allocations refuse."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.app.infrastructure.database import Database, MIGRATIONS, StorageUnavailable
from backend.tests.infrastructure.test_database import insert_requirement, TIME


class ManualIdentityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-identity-migration-')
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.legacy = Database(self.path)
        self.legacy.migrations = MIGRATIONS[:3]
        self.legacy.initialize()
        self.state = {'schema_version': 1, 'next_block_id': 2, 'blocks': [{
            'block_id': 1, 'block_type': 'PARAGRAPH', 'section_path': [],
            'created_by_type': 'SYSTEM', 'created_source_type': 'TEMPLATE', 'created_source_id': None,
            'created_at': TIME, 'last_modified_by_type': 'SYSTEM', 'last_modified_source_type': 'TEMPLATE',
            'last_modified_source_id': None, 'last_modified_at': TIME}]}
        with self.legacy.transaction(write=True) as connection:
            insert_requirement(connection)
            for identity, kind in ((201, 'CURRENT'), (202, 'MANUAL_DRAFT')):
                connection.execute('INSERT INTO requirement_documents VALUES (?,101,?,?,?,1,?,?)', (identity, kind, 'body', json.dumps(self.state), TIME, TIME))
            connection.execute('INSERT INTO manual_draft_context VALUES (202,201,1,?,?)', (json.dumps(self.state), TIME))
            connection.execute("INSERT INTO manual_edit_sessions VALUES (202,101,201,'EDITING',?,NULL)", (TIME,))
            connection.execute("UPDATE requirements SET document_work_state='MANUAL_EDITING',active_operation_type='MANUAL_DRAFT',active_operation_id=202,state_started_at=?", (TIME,))
        self.database = Database(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_upgrade_retains_proven_draft_and_backup(self):
        outcome = self.database.initialize()
        self.assertEqual(outcome['schema_version'], 4)
        with closing(sqlite3.connect(outcome['backup_path'])) as backup:
            self.assertEqual(backup.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 3)
        with self.database.transaction() as connection:
            self.assertEqual(json.loads(connection.execute('SELECT block_state_json FROM requirement_documents WHERE id=202').fetchone()[0]), self.state)
            self.assertEqual(connection.execute('SELECT count(*) FROM manual_block_origins').fetchone()[0], 0)

    def test_unproven_higher_watermark_new_identity_or_changed_birth_refuses_without_partial_upgrade(self):
        for mutation in ('watermark', 'identity', 'birth'):
            with self.subTest(mutation=mutation):
                state = json.loads(json.dumps(self.state))
                if mutation == 'watermark':
                    state['next_block_id'] = 3
                elif mutation == 'identity':
                    state['blocks'][0]['block_id'] = 2
                else:
                    state['blocks'][0]['created_by_type'] = 'USER'
                with self.legacy.transaction(write=True) as connection:
                    connection.execute('UPDATE requirement_documents SET block_state_json=? WHERE id=202', (json.dumps(state),))
                with self.assertRaises(StorageUnavailable):
                    self.database.initialize()
                with closing(sqlite3.connect(self.path)) as connection:
                    self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 3)
                    self.assertEqual(json.loads(connection.execute('SELECT block_state_json FROM requirement_documents WHERE id=202').fetchone()[0]), state)
                    self.assertEqual(connection.execute("SELECT count(*) FROM sqlite_master WHERE name='manual_block_origins'").fetchone()[0], 0)
        self.assertEqual(len(list(self.path.parent.glob('*.backup.sqlite'))), 3)

    def test_sql_ranges_origins_immutable_and_cleanup_order(self):
        self.database.initialize()
        with self.database.transaction(write=True) as connection:
            connection.execute('INSERT INTO manual_block_allocation_ranges VALUES (202,2,9007199254740991,?)', (TIME,))
            connection.execute("INSERT INTO manual_block_origins VALUES (202,3,'USER','MANUAL_EDIT',202,?)", (TIME,))
        for sql in (
            "INSERT INTO manual_block_allocation_ranges VALUES (202,3,4,'2026-09-21T08:30:00.000Z')",
            'UPDATE manual_block_allocation_ranges SET start_block_id=4',
            "INSERT INTO manual_block_origins VALUES (202,1,'USER','MANUAL_EDIT',202,'2026-09-21T08:30:00.000Z')",
            "UPDATE manual_block_origins SET created_at='2026-09-22T08:30:00.000Z'",
            'DELETE FROM manual_draft_context WHERE draft_id=202',
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                with self.database.transaction(write=True) as connection:
                    connection.execute(sql)
        with self.database.transaction(write=True) as connection:
            connection.execute('DELETE FROM manual_block_origins WHERE draft_id=202')
            connection.execute('DELETE FROM manual_block_allocation_ranges WHERE draft_id=202')
            connection.execute('DELETE FROM manual_draft_context WHERE draft_id=202')


if __name__ == '__main__':
    unittest.main()
