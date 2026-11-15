"""Real child process death: original DDL rolls back or whole durable 200 survives."""

import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
from threading import Thread

import pytest

from tools.quality_gate import stop_owned
from backend.app.infrastructure import schema_v20_maintenance as maintenance
from backend.app.infrastructure import schema_v20_plan as plans
from backend.app.infrastructure.schema_v20_upgrade import MaintenanceSession
from backend.app.infrastructure.schema_v20_release import ROOT, build_candidate
from backend.app.infrastructure.data_retention import inspect_v151_source
from backend.tests.infrastructure.test_v20_upgrade_engine import offline, release
from backend.tests.requirements.test_v15_foundation import tmp_path, setup
from backend.tests.documents.test_v15_documents import workspace


@pytest.mark.parametrize(
    'phase,expected', [('BEFORE_MARKER', 'NOT_APPLIED'), ('AFTER_COMMIT', 'ALREADY_COMMITTED')]
)
def test_killed_original_maintenance_process_has_only_real_pre_or_post_commit_state(
    offline, phase, expected
):
    session, intent, source, original = offline
    plan, sha = plans.prepare_plan(session, configuration_paths=())
    keys = {'upgrade_id': plan.upgrade_id, 'plan_sha256': sha}
    maintenance.rehearse_plan(session, **keys)
    directory = session.package_path / 'owned-release-fixture'
    directory.mkdir()
    for name, data in build_candidate(session.release.release_id).items():
        with (directory / name).open('xb') as stream:
            stream.write(data)
    database_path, package, release = session.database.path, session.package_path, session.release
    before_receipts = tuple((package / 'receipts').iterdir())
    session.close()
    process = subprocess.Popen(
        [
            str(ROOT / '.venv/Scripts/python.exe'),
            '-u',
            '-B',
            '-X',
            'utf8',
            'tools/python-v20.py',
            'backend/tests/infrastructure/v20_maintenance_crash_worker.py',
            '--database',
            str(database_path),
            '--package',
            str(package),
            '--upgrade-id',
            plan.upgrade_id,
            '--plan-sha256',
            sha,
            '--release',
            str(directory),
            '--release-sha256',
            release.manifest_sha256,
            '--phase',
            phase,
        ],
        cwd=ROOT,
        env=dict(os.environ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
    )
    queue = Queue()
    reader = Thread(target=lambda: queue.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        try:
            observed = queue.get(timeout=45)
        except Empty:
            pytest.fail('Owned maintenance child did not reach the requested boundary')
        assert observed.strip() == 'OWNED_MAINTENANCE_BOUNDARY_READY'
        stop_owned(process)
        process.communicate(timeout=15)
        assert process.returncode != 0
    finally:
        if process.poll() is None:
            stop_owned(process)
        process.communicate(timeout=15)
        reader.join(timeout=5)
    # No receipt from the killed action; process exit alone is not its outcome.
    assert tuple((package / 'receipts').iterdir()) == before_receipts
    with MaintenanceSession(
        database_path, package, release, maintenance_window_confirmed=True
    ) as reopened:
        result = maintenance.recover_plan(reopened, **keys)
        assert result.status == expected and result.retained_data_matches is True
        if expected == 'NOT_APPLIED':
            assert inspect_v151_source(reopened.database).data == plan.retained
        else:
            assert result.committed_at is not None
    assert inspect_v151_source(source).data == original
