"""Nonempty isolated construction drills; not DB20 runtime admission."""

from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import sqlite3

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.guide.test_v15_acceptance import accept
from backend.app.infrastructure.database import Database, SchemaMismatch, _statements
from backend.app.infrastructure.data_retention import capture_retained_data, verify_retained_data
from backend.app.infrastructure.schema_inspection import inspect_schema, verify_integrity
from backend.app.infrastructure.schema_v20_assembly import upgrade_sql

AT = '2026-11-04T01:00:00.000Z'


def seeded_source(workspace):
    database = workspace[0]
    assert (
        document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))[
            'code'
        ]
        == 'CREATED'
    )
    assert document(workspace, name='第二份固定依据')['code'] == 'CREATED'
    accepted = accept(workspace)
    assert accepted['code'] == 'GUIDE_ACCEPTED'
    run_id = accepted['data']['guide_run_id']
    with database.transaction(write=True) as connection:
        row = dict(
            id=1,
            guide_run_id=run_id,
            call_no=1,
            attempt_no=1,
            provider='original-provider',
            model_name='original-model',
            function_type='ANSWER_REQUIREMENT',
            prompt_config='original',
            request_snapshot_json='{ "original": "保留", "zero": 0 }',
            input_summary='原始正文\n保留空白 ',
            context_manifest_json='{}',
            raw_response_json=None,
            parse_status='PENDING',
            validation_status='PENDING',
            call_status='RUNNING',
            input_tokens=0,
            output_tokens=None,
            provider_request_id='',
            started_at=AT,
            cost='0.000000',
            cost_currency='CNY',
        )
        connection.execute(
            f'INSERT INTO llm_uses({",".join(row)}) VALUES({",".join("?" for _ in row)})',
            tuple(row.values()),
        )
        connection.execute(
            'INSERT INTO idempotency_records VALUES(?,?,?,?,?,?,?,?,?,?)',
            (
                'APP-REQ-CMD-C01',
                'original-processing-scope',
                '00000000-0000-4000-8000-000000000081',
                '{ "pending": true }',
                'PROCESSING',
                'original-owner',
                AT,
                AT,
                None,
                None,
            ),
        )
    with database.transaction() as connection:
        return capture_retained_data(connection)


def test_nonempty_151_rebuild_retains_every_old_typed_value_after_reopen(workspace, tmp_path):
    source = workspace[0]
    original = seeded_source(workspace)
    target = source.backup_to(tmp_path / 'construction.sqlite')
    sql = upgrade_sql()
    with closing(sqlite3.connect(target, isolation_level=None)) as connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 0
        connection.execute('BEGIN IMMEDIATE')
        for statement in _statements(sql):
            connection.execute(statement)
        verify_retained_data(connection, original)
        verify_integrity(connection)
        expected = inspect_schema(connection)
        contract = hashlib.sha256(json.dumps(asdict(expected), sort_keys=True).encode()).hexdigest()
        connection.execute(
            'INSERT INTO schema_migrations VALUES(200,?,?)',
            (hashlib.sha256(sql.encode()).hexdigest(), AT),
        )
        connection.execute(
            'INSERT INTO code_schema_state VALUES(1,200,?,?,?,?,?)',
            (
                contract,
                'UPGRADED_V151',
                '00000000-0000-4000-8000-000000000082',
                original.sha256,
                AT,
            ),
        )
        connection.commit()
        connection.execute('PRAGMA foreign_keys=ON')
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    with closing(sqlite3.connect(target, isolation_level=None)) as connection:
        connection.execute('BEGIN')
        verify_retained_data(connection, original)
        verify_integrity(connection)
        assert inspect_schema(connection) == expected
        assert connection.execute(
            'SELECT input_tokens,output_tokens,provider_request_id,execution_session_id,testing_task_id,usage_status FROM llm_uses'
        ).fetchone() == (0, None, '', None, None, None)
        assert connection.execute(
            "SELECT business_input_json,error_result_json FROM idempotency_records WHERE status='PROCESSING'"
        ).fetchone() == ('{ "pending": true }', None)
        assert [
            row[0]
            for row in connection.execute('SELECT version FROM schema_migrations ORDER BY version')
        ] == [151, 200]
        assert connection.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM testing_tasks').fetchone()[0] == 0
    with pytest.raises(SchemaMismatch):
        with Database(target).transaction():
            pass
    with source.transaction() as connection:
        verify_retained_data(connection, original)


def test_rebuild_exception_rolls_back_all_ddl_and_old_data(workspace, tmp_path):
    original = seeded_source(workspace)
    target = workspace[0].backup_to(tmp_path / 'rollback.sqlite')
    with closing(sqlite3.connect(target, isolation_level=None)) as connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('BEGIN IMMEDIATE')
        for statement in _statements(upgrade_sql()):
            connection.execute(statement)
        # Exercise SQLite rollback after actual copy/drop/rename and new triggers.
        connection.rollback()
    with Database(target).transaction() as connection:
        verify_retained_data(connection, original)
        verify_integrity(connection)
        assert (
            connection.execute(
                "SELECT count(*) FROM sqlite_schema WHERE name='code_tasks'"
            ).fetchone()[0]
            == 0
        )
