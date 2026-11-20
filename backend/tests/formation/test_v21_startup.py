"""Production lifecycle explicitly serves verified 210; startup never initializes/upgrades."""

import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from backend.app.service import create_app
from backend.app.infrastructure.database import Database, SchemaMismatch, StorageUnavailable
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.process_lock import ProcessLock, ProcessAlreadyRunning
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid
from backend.app.infrastructure.schema_v20_release import load_release
from backend.tests.formation.test_v21_schema import released, database

__all__ = ['released', 'database']


def test_explicit_production_210_actual_worker_routes_and_closed_provider_gate(
    database, monkeypatch
):
    monkeypatch.setenv('WALLE_DATABASE_PATH', str(database.path))
    monkeypatch.delenv('WALLE_MODEL_API_KEY', raising=False)
    monkeypatch.delenv('WALLE_MODEL_PROFILE', raising=False)
    app = create_app(schema_version=210)
    with TestClient(app) as client:
        runtime = app.state.walle_runtime
        assert runtime.worker.accepting and runtime.catalog.collaboration.formation_driven
        with runtime.database.transaction() as connection:
            assert (
                connection.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
                == 210
            )
        created = client.post(
            '/api/v1/requirements',
            json={
                'title': '生产入口检查',
                'requirement_type': 'NEW',
                'initial_idea': '验证实际入口',
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert created.status_code == 201, created.text
        document = client.post(
            '/api/v1/requirements/1/documents',
            json={'name': '设计', 'document_kind': 'DESIGN', 'template_ref': None},
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert document.status_code == 201, document.text
        read = client.get('/api/v1/requirements/1/documents/1/formation/steps')
        assert read.status_code == 409, read.text
        assert read.json()['error']['details']['reason'] == 'FORMATION_NOT_INITIALIZED'
        detail = client.get('/api/v1/requirements/1')
        assert detail.status_code == 200, detail.text
        with runtime.database.transaction() as connection:
            version = connection.execute(
                'SELECT discussion_version FROM requirement_documents WHERE id=1'
            ).fetchone()[0]
        accepted = client.post(
            '/api/v1/requirements/1/guide-runs',
            json={
                'document_id': 1,
                'expected_discussion_version': version,
                'operation': 'DISCUSS',
                'instruction': '保留本轮输入',
                'target': {
                    'discussion_step_ref': None,
                    'discussion_branch_ref': None,
                    'branch_intent': None,
                    'branch_resume_basis': None,
                },
                'scope': None,
                'source_refs': [],
                'proposal_ref': None,
                'proposal_intent': None,
                'acknowledge_source_changes': False,
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert accepted.status_code == 202, accepted.text
        identity = accepted.json()['data']['guide_run_id']
        due = time.monotonic() + 10
        while time.monotonic() < due:
            outcome = client.get('/api/v1/guide-runs/' + str(identity))
            assert outcome.status_code == 200, outcome.text
            if outcome.json()['data']['status'] == 'FAILED':
                break
            time.sleep(0.02)
        assert outcome.json()['data']['status'] == 'FAILED', outcome.text
        assert outcome.json()['data']['error_code'] == 'CONFIG_INVALID', outcome.text
        with runtime.database.transaction() as connection:
            assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
            assert connection.execute('SELECT count(*) FROM formation_heads').fetchone()[0] == 0
            assert (
                connection.execute(
                    "SELECT count(*) FROM conversation_messages WHERE role='USER' AND content='保留本轮输入'"
                ).fetchone()[0]
                == 1
            )
        with pytest.raises(ProcessAlreadyRunning):
            with TestClient(create_app(schema_version=210)):
                pytest.fail('Second process owner must not start')
    assert app.state.walle_runtime is None
    with ProcessLock.for_database(database.path):
        pass


def test_wrong_version_missing_database_and_catalog_refuse_without_initializing(
    database, tmp_path, monkeypatch
):
    original = database.path.read_bytes()
    monkeypatch.setenv('WALLE_DATABASE_PATH', str(database.path))
    with pytest.raises(SchemaMismatch):
        with TestClient(create_app()):
            pytest.fail('Default 200 must not infer 210')
    assert database.path.read_bytes() == original
    source = Database(tmp_path / 'source200.sqlite', schema_release=load_release())
    source.initialize()
    before = source.path.read_bytes()
    monkeypatch.setenv('WALLE_DATABASE_PATH', str(source.path))
    with pytest.raises(SchemaMismatch):
        with TestClient(create_app(schema_version=210)):
            pytest.fail('Startup must not upgrade 200')
    assert source.path.read_bytes() == before
    missing = tmp_path / 'missing210.sqlite'
    monkeypatch.setenv('WALLE_DATABASE_PATH', str(missing))
    with pytest.raises(StorageUnavailable):
        with TestClient(create_app(schema_version=210)):
            pytest.fail('Startup must not initialize 210')
    assert not missing.exists()
    with pytest.raises(ValueError):
        create_app(schema_version=True)
    with pytest.raises(ValueError):
        create_app(database=database)
    with pytest.raises(ConfigInvalid):
        with TestClient(
            create_app(database=database, schema_version=210, catalog=ResourceCatalog())
        ):
            pytest.fail('Explicit old catalog must not silently change')


def test_native_v21_main_bootstraps_fixed_sqlite_before_loading_service(database):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ)
    environment['WALLE_DATABASE_PATH'] = str(database.path)
    environment.pop('WALLE_MODEL_API_KEY', None)
    result = subprocess.run(
        [sys.executable, '-B', '-X', 'utf8', 'backend/tests/formation/v21_startup_worker.py'],
        cwd=root,
        env=environment,
        capture_output=True,
        encoding='utf-8',
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert 'EXPLICIT_V21_STARTED 3.54.1' in result.stdout
