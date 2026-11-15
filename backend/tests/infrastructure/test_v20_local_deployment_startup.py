"""Actual startup consumes the pinned local deployment; no system Guard is installed."""

import os
import subprocess
import sys
from pathlib import Path

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.schema_v20_release import load_release
from backend.tests.code_tasks import test_local_deployment as source

local_source = source.local_source
tmp_path = source.tmp_path
ROOT = Path(__file__).resolve().parents[3]


def test_actual_main_passes_held_deployment_into_real_app_lifetime(local_source, tmp_path):
    _, _, environment = local_source
    database = Database(tmp_path / 'startup.sqlite', schema_release=load_release())
    database.initialize()
    environment = {**os.environ, **environment}
    environment['WALLE_DATABASE_PATH'] = str(database.path)
    environment['WALLE_TEST_DEPLOYMENT_MODE'] = 'valid'
    result = subprocess.run(
        [
            sys.executable,
            '-B',
            '-X',
            'utf8',
            str(ROOT / 'backend/tests/infrastructure/v20_local_deployment_startup_worker.py'),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'LOCAL_DEPLOYMENT_STARTUP_PASSED' in result.stdout


def test_actual_main_rejects_changed_source_before_initializing_any_application(
    local_source, tmp_path
):
    _, _, environment = local_source
    environment = {**os.environ, **environment}
    environment['WALLE_CODE_DEPLOYMENT_SHA256'] = 'c' * 64
    environment['WALLE_DATABASE_PATH'] = str(tmp_path / 'must-not-be-created.sqlite')
    environment['WALLE_TEST_DEPLOYMENT_MODE'] = 'reject'
    result = subprocess.run(
        [
            sys.executable,
            '-B',
            '-X',
            'utf8',
            str(ROOT / 'backend/tests/infrastructure/v20_local_deployment_startup_worker.py'),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'LOCAL_DEPLOYMENT_REJECTED_BEFORE_DATABASE' in result.stdout
    assert not Path(environment['WALLE_DATABASE_PATH']).exists()
