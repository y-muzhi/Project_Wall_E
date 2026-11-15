"""Read-only deployment CLI uses actual source objects and creates no Guard runtime."""

import subprocess
import sys
from pathlib import Path

import pytest

from backend.tests.code_tasks import test_local_deployment as local
from backend.tests.infrastructure import test_v20_guard_deployment_configuration as guards

tmp_path = local.tmp_path
local_source = local.local_source
guard_source = guards.guard_source
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('kind', ['backend', 'guard'])
@pytest.mark.parametrize('changed', [False, True])
def test_explicit_source_is_checked_without_application_or_guard_creation(
    local_source, guard_source, kind, changed
):
    if kind == 'backend':
        _, manifest, environment = local_source
        sha = environment['WALLE_CODE_DEPLOYMENT_SHA256']
    else:
        value, manifest, sha = guard_source
    result = subprocess.run(
        [
            sys.executable,
            '-B',
            '-X',
            'utf8',
            str(ROOT / 'tools/inspect-code-deployment.py'),
            '--kind',
            kind,
            '--manifest',
            str(manifest),
            '--sha256',
            'e' * 64 if changed else sha,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )
    assert result.returncode == (1 if changed else 0), result.stdout + result.stderr
    if changed:
        assert result.stdout == ''
        assert result.stderr.strip() == 'DEPLOYMENT_SOURCE_REJECTED'
    else:
        assert (
            'BACKEND_SOURCE_RESOURCES_CHECKED'
            if kind == 'backend'
            else 'GUARD_SOURCE_SHAPE_CHECKED'
        ) in result.stdout
        assert result.stderr == ''
    if kind == 'guard':
        assert list(Path(value['journal_root']).iterdir()) == []
    manifest.rename(manifest.with_suffix('.released'))


def test_guard_cli_does_not_upgrade_shape_check_to_system_execution(guard_source):
    value, manifest, sha = guard_source
    result = subprocess.run(
        [
            sys.executable,
            '-B',
            str(ROOT / 'tools/inspect-code-deployment.py'),
            '--kind',
            'backend',
            '--manifest',
            str(manifest),
            '--sha256',
            sha,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )
    assert result.returncode == 1
    assert result.stderr.strip() == 'DEPLOYMENT_SOURCE_REJECTED'
    assert list(Path(value['journal_root']).iterdir()) == []
