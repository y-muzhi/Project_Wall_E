"""Isolated schema construction checks, not a released Schema200 upgrade."""

import json
import sqlite3
import unittest

from backend.app.code_tasks.command_registry import COMMAND_ROUTES, registered_command
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.schema_v20 import column_sql, create_table_sql
from backend.app.infrastructure.schema_v20_columns import COLUMNS
from backend.app.infrastructure.schema_v20_legacy import (
    idempotency_table_sql,
    llm_table_sql,
    original_columns,
)
from backend.app.infrastructure.schema_v20_relations import table_constraints
from backend.app.shared.validation import InvalidInput

KEY = '00000000-0000-4000-8000-000000000001'
AT = '2026-11-04T01:00:00.000Z'


class CommandIdentityTests(unittest.TestCase):
    def test_original_scope_is_registered_and_body_independent(self):
        command = registered_command('POST', '/api/v1/code-tasks/12/terminate', KEY)
        self.assertEqual(
            command.scope.identity,
            (
                'APP-CODE-CMD-C37',
                'POST /api/v1/code-tasks/12/terminate',
                KEY,
            ),
        )
        testing = registered_command('POST', '/api/v1/testing-tasks/12/terminate', KEY)
        self.assertNotEqual(testing.scope.identity, command.scope.identity)
        collection = registered_command('POST', '/api/v1/code-repositories', KEY)
        self.assertEqual(collection.scope.target_identity, 'POST /api/v1/code-repositories')
        self.assertEqual(len(COMMAND_ROUTES), 48)

    def test_close_cannot_target_get_close_or_unregistered_urls(self):
        for method, path in (
            ('GET', '/api/v1/code-tasks/12'),
            ('POST', '/api/v1/command-intents/close'),
            ('POST', 'https://example.test/api/v1/code-repositories'),
            ('POST', '/api/v1/code-tasks/01/terminate'),
            ('POST', '/api/v1/code-tasks/0/terminate'),
            ('POST', '/api/v1/code-tasks/1/terminate?force=1'),
            ('POST', '/api/v1/code-tasks/1/terminate#fragment'),
            ('POST', '/api/v1/code-tasks/%31/terminate'),
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                registered_command(method, path, KEY)
        with self.assertRaises(InvalidInput):
            registered_command('POST', '/api/v1/code-tasks/9007199254740992/terminate', KEY)

    def test_steps_do_not_cross_module_or_invent_new_workflows(self):
        self.assertEqual(operation_steps('CODING', 'TERMINATE')[0], 'BLOCK_NEW')
        self.assertEqual(operation_steps('TESTING', 'TERMINATE')[0], 'FENCE')
        self.assertEqual(
            operation_steps('RESOURCE', 'REGISTER_BASE'),
            ('VALIDATE_COMMIT', 'PIN_COMMIT', 'VERIFY_PINNED_OBJECTS', 'SAVE_BASELINE'),
        )
        with self.assertRaises(ValueError):
            operation_steps('CODING', 'RUN_TEST')


class ColumnAndLegacyTests(unittest.TestCase):
    def test_strict_micro_money_storage_rejects_exponent_negative_and_bad_fraction(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute(
            'CREATE TABLE t(' + column_sql('CodeTask', 'amount', 'Money', False) + ') STRICT'
        )
        for amount in ('0.000000', '1.000001', '999999999999999999999999.000001'):
            connection.execute('INSERT INTO t VALUES(?)', (amount,))
        for amount in (
            '-1.000000',
            '+1.000000',
            '1e2',
            '1.00000',
            '1..00000',
            '01.000000',
            '1.00.000',
            '1.0000000',
            '1.00000\n',
        ):
            with self.subTest(amount=amount), self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO t VALUES(?)', (amount,))

    def test_id_boolean_and_json_top_level_are_real_sql_constraints(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute(
            'CREATE TABLE t('
            + ','.join(
                (
                    column_sql('x', 'id', 'ID', False),
                    column_sql('x', 'enabled', 'Boolean', False),
                    column_sql('x', 'refs', 'EvidenceRef[]', False),
                )
            )
            + ') STRICT'
        )
        connection.execute("INSERT INTO t VALUES(1,1,'[]')")
        for values in ((0, 1, '[]'), (1, 2, '[]'), (1, 1, '{}'), (1, 1, None)):
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO t VALUES(?,?,?)', values)

    def test_unmapped_enum_fails_closed_and_known_columns_construct(self):
        with self.assertRaisesRegex(ValueError, 'Unregistered.action'):
            column_sql('x', 'action', 'Unregistered.action枚举（本节取值）', False)
        self.assertEqual(len(COLUMNS), 56)
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        for table in COLUMNS:
            if table != 'llm_uses':
                connection.execute(create_table_sql(table, table_constraints(table)))
        self.assertEqual(
            connection.execute("SELECT count(*) FROM sqlite_schema WHERE type='table'").fetchone()[
                0
            ],
            55,
        )

    def test_original_key_close_and_rejected_results_have_exclusive_sql_shapes(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        capabilities = tuple(route.capability_id for route in COMMAND_ROUTES)
        connection.execute(idempotency_table_sql(capabilities))
        closed = {
            'code': 'COMMAND_CLOSED',
            'data': None,
            'details': {
                'method': 'POST',
                'path': '/api/v1/code-repositories',
                'closed_at': AT,
            },
        }
        base = [
            'APP-CODE-CMD-C01',
            'POST /api/v1/code-repositories',
            KEY,
            None,
            'CLOSED',
            'owner',
            AT,
            AT,
            None,
            409,
            json.dumps(closed),
        ]
        connection.execute('INSERT INTO idempotency_records VALUES(?,?,?,?,?,?,?,?,?,?,?)', base)
        connection.execute('DELETE FROM idempotency_records')
        for index, replacement in (
            (0, 'APP-REQ-CMD-C01'),
            (3, '{}'),
            (9, 200),
            (10, '{"code":"COMMAND_CLOSED"}'),
        ):
            row = list(base)
            row[index] = replacement
            with self.subTest(index=index), self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    'INSERT INTO idempotency_records VALUES(?,?,?,?,?,?,?,?,?,?,?)', row
                )
        rejected = list(base)
        rejected[3] = '{"frozen":"input"}'
        rejected[4] = 'REJECTED'
        rejected[9] = 422
        rejected[10] = json.dumps(
            {'code': 'INVALID_INPUT', 'data': None, 'details': {'field_errors': []}}
        )
        connection.execute(
            'INSERT INTO idempotency_records VALUES(?,?,?,?,?,?,?,?,?,?,?)', rejected
        )

    def test_llm_old_columns_are_present_and_new_owners_cannot_be_mixed(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute(llm_table_sql())
        actual = {row[1] for row in connection.execute('PRAGMA table_info(llm_uses)')}
        self.assertTrue(set(original_columns('llm_uses')) <= actual)
        row = dict(
            id=1,
            guide_run_id=1,
            call_no=1,
            attempt_no=1,
            provider='original',
            model_name='original',
            function_type='ANSWER_REQUIREMENT',
            prompt_config='v1',
            request_snapshot_json='{"kept": 1}',
            input_summary='原值',
            context_manifest_json='{}',
            parse_status='PENDING',
            validation_status='PENDING',
            call_status='RUNNING',
            started_at=AT,
            provider_request_id='',
        )
        columns = ','.join(row)
        connection.execute(
            f'INSERT INTO llm_uses({columns}) VALUES({",".join("?" for _ in row)})',
            tuple(row.values()),
        )
        self.assertEqual(
            connection.execute(
                'SELECT request_snapshot_json,provider_request_id FROM llm_uses'
            ).fetchone(),
            ('{"kept": 1}', ''),
        )
        row['id'] = 2
        row['execution_session_id'] = 1
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                f'INSERT INTO llm_uses({",".join(row)}) VALUES({",".join("?" for _ in row)})',
                tuple(row.values()),
            )


class FullConstructionTests(unittest.TestCase):
    def test_fresh_and_rebuild_have_identical_real_objects_and_foreign_keys(self):
        from backend.app.infrastructure.database import Migration, _statements
        from backend.app.infrastructure.schema_v20_assembly import fresh_sql, upgrade_sql
        from backend.app.infrastructure.schema_inspection import inspect_schema, verify_integrity

        snapshots = []
        for origin in ('fresh', 'upgrade'):
            connection = sqlite3.connect(':memory:', isolation_level=None)
            try:
                connection.execute('BEGIN')
                if origin == 'upgrade':
                    for statement in _statements(Migration().sql):
                        connection.execute(statement)
                for statement in _statements(fresh_sql() if origin == 'fresh' else upgrade_sql()):
                    connection.execute(statement)
                verify_integrity(connection)
                snapshots.append(inspect_schema(connection))
                self.assertEqual(len(snapshots[-1].tables), 72)
            finally:
                connection.close()
        self.assertEqual(snapshots[0], snapshots[1])

    def test_terminal_receipts_cannot_be_changed_deleted_or_reopened(self):
        from backend.app.infrastructure.schema_v20_assembly import fresh_sql

        connection = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(connection.close)
        # Use every production guard; positional slices can silently omit a new one.
        connection.executescript(fresh_sql())
        outcome = json.dumps(
            {
                'code': 'COMMAND_CLOSED',
                'data': None,
                'details': {
                    'method': 'POST',
                    'path': '/api/v1/code-repositories',
                    'closed_at': AT,
                },
            }
        )
        connection.execute(
            'INSERT INTO idempotency_records VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (
                'APP-CODE-CMD-C01',
                'POST /api/v1/code-repositories',
                KEY,
                None,
                'CLOSED',
                'epoch',
                AT,
                AT,
                None,
                409,
                outcome,
            ),
        )
        for statement in (
            'DELETE FROM idempotency_records',
            "UPDATE idempotency_records SET status='PROCESSING',business_input_json='{}',error_result_json=NULL,http_status=NULL",
            "UPDATE idempotency_records SET updated_at='later'",
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(statement)


class DesignColumnCoverageTests(unittest.TestCase):
    def test_all_521_design_fields_are_present_with_exact_type_and_nullability(self):
        from pathlib import Path
        import hashlib
        from backend.app.infrastructure.schema_v20_columns import DESIGN_SHA256

        path = Path(__file__).resolve().parents[3] / 'docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md'
        source = path.read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), DESIGN_SHA256)
        owners = {owner: fields for owner, fields in COLUMNS.values()}
        reviewed = {}
        for line in source.decode('utf-8').splitlines()[168:1267]:
            if not line.startswith('| '):
                continue
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if len(cells) != 6 or '.' not in cells[0]:
                continue
            owner, name = cells[0].split('.', 1)
            if owner in owners:
                reviewed.setdefault(owner, []).append((name, cells[1], cells[3] == '是'))
        self.assertEqual(sum(len(fields) for fields in reviewed.values()), 521)
        private_fields = {
            'NativePermission': (
                ('native_observation', 'PrivateNativePermissionObservation', True),
            ),
        }
        for owner, fields in reviewed.items():
            extensions = private_fields.get(owner, ())
            public = tuple(field for field in owners[owner] if field not in extensions)
            self.assertEqual(public, tuple(fields), owner)
            self.assertEqual(
                tuple(field for field in owners[owner] if field in extensions), extensions, owner
            )
        for owner, name in (
            ('CodeCandidate', 'manifest_sha256'),
            ('DeliveryPlan', 'target_manifest_sha256'),
            ('Delivery', 'commit_input_sha256'),
            ('TestPackVersion', 'sha256'),
        ):
            self.assertIn(name, {field[0] for field in owners[owner]})
