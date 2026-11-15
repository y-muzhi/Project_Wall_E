"""Default production factory and import ordering on owned published Schema200."""

import os
import subprocess

from fastapi.testclient import TestClient
import pytest

from backend.app.service import create_app
from backend.app.infrastructure.database import Database, SchemaMismatch, StorageUnavailable
from backend.app.infrastructure.data_retention import inspect_v151_source
from backend.app.infrastructure.schema_v20_release import load_release, ROOT
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.infrastructure.test_v20_schema_migration import seeded_source


def test_default_factory_accepts_only_published_200_and_never_upgrades_existing_151(
    workspace, tmp_path, monkeypatch
):
    source = workspace[0]
    original = seeded_source(workspace)
    monkeypatch.setenv('WALLE_DATABASE_PATH', str(source.path))
    with pytest.raises(SchemaMismatch):
        with TestClient(create_app()):
            pytest.fail('Existing 151 may not serve as a default V2 database')
    assert inspect_v151_source(source).data == original
    current = Database(tmp_path / 'default200.sqlite', schema_release=load_release())
    current.initialize()
    monkeypatch.setenv('WALLE_DATABASE_PATH', str(current.path))
    with TestClient(create_app()) as client:
        assert client.get('/api/v1/requirements').status_code == 200
        assert client.get('/api/v1/requirements').json()['data']['items'] == []
    missing = tmp_path / 'missing.sqlite'
    monkeypatch.setenv('WALLE_DATABASE_PATH', str(missing))
    with pytest.raises(StorageUnavailable):
        with TestClient(create_app()):
            pytest.fail('Missing databases must not be initialized by startup')
    assert not missing.exists()


def test_real_production_main_activates_fixed_native_sqlite_before_loading_database_modules(
    tmp_path,
):
    database = Database(tmp_path / 'production-main.sqlite', schema_release=load_release())
    database.initialize()
    environment = dict(os.environ)
    environment['WALLE_DATABASE_PATH'] = str(database.path)
    # A fresh Python interpreter, without tools/python-v20: actual __main__ must
    # bootstrap first. Only the listener is replaced; real app/worker/SQL run.
    completed = subprocess.run(
        [
            str(ROOT / '.venv/Scripts/python.exe'),
            '-u',
            '-B',
            '-X',
            'utf8',
            'backend/tests/infrastructure/v20_startup_worker.py',
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        encoding='utf-8',
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr
    assert 'DEFAULT_V20_STARTED 3.54.1' in completed.stdout
