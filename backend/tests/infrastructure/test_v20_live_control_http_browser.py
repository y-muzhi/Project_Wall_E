"""CLI Chrome uses actual C39/receipt/projection HTTP, with offline native reads.

The candidate is the explicitly logical fast-state fixture. Actual sealed NTFS
candidate/C30 evidence is in test_task_capture_quiescence, not claimed here.
"""

import os
import subprocess
from copy import deepcopy
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from backend.app.code_tasks.authorizations import project_grant
from backend.app.code_tasks.task_live_configuration import advance_live_configuration
from backend.app.frontend import install_frontend
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.code_tasks import test_task_delivery_authorization as delivery_tests
from backend.tests.code_tasks.test_authorizations import approve
from backend.tests.code_tasks.test_execution_profile_versions import (
    fixture_snapshot,
    publish,
    resources,
)
from backend.tests.code_tasks.test_task_check_configuration import (
    check_profile,  # noqa: F401
    check_resources,
    fixture_project_admission,
    prepare_check_pair,
)
from backend.tests.code_tasks.test_task_live_configuration import (
    ReadOnlyDriver,
    fixed_price,  # noqa: F401
    idle_task,  # noqa: F401
    isolated_readiness,  # noqa: F401
    opened,  # noqa: F401
    original_instance,  # noqa: F401
    ready,  # noqa: F401
    target_pair,
    versioned_runtime_fixture,  # noqa: F401
)
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.infrastructure.test_v20_live_configuration_browser import serve_original_app
from backend.tests.infrastructure.test_v20_owned_browser_relay import _close
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
NODE = Path(r'C:\Program Files\nodejs\node.exe')


@pytest.fixture(autouse=True)
def original_delivery_scope(change_checks, monkeypatch, request):
    request.getfixturevalue('versioned_runtime_fixture')
    if change_checks == 'delivery':
        delivery_tests.configure_original_delivery(monkeypatch, True)


@pytest.mark.parametrize('unknown_stage', [3, 4])
@pytest.mark.parametrize('change_checks', ['controls', 'checks', 'output', 'models', 'delivery'])
def test_cli_browser_adopts_only_observed_pair_through_actual_http(
    idle_task,  # noqa: F811
    tmp_path,  # noqa: F811
    change_checks,
    unknown_stage,
):
    entry = os.environ.get('WALLE_BROWSER_CLI_ENTRY')
    if not entry:
        pytest.skip('An explicit installed Playwright CLI entry is required')
    entry = Path(entry).resolve(strict=True)
    assert entry.name == 'playwright-cli.js' and NODE.is_file()
    assert tmp_path.resolve().is_relative_to(Path(os.environ['WALLE_CHECK_TEMP']).resolve())
    database, runtime, client, ingress, _parent, task, _, _, _ = idle_task
    original, version, grant, content = (
        prepare_check_pair(
            idle_task,
            output_profile=128 if change_checks == 'output' else None,
            output_grant=64 if change_checks == 'output' else None,
        )
        if change_checks in ('checks', 'output')
        else target_pair(
            idle_task,
            {'models': 'model-revoke', 'delivery': 'delivery-revoke'}.get(
                change_checks, 'controls'
            ),
        )
    )
    if change_checks == 'delivery':
        with database.transaction() as connection:
            original_grant = connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (original['authorization_id'],)
            ).fetchone()
            assert project_grant(original_grant)['scope']['allow_local_delivery'] is True
    admissions = (fixture_project_admission(),) if change_checks in ('checks', 'output') else ()
    client.app.state.walle_repository_registration.project_check_admissions = admissions
    snapshot = (
        check_resources(content)
        if change_checks in ('checks', 'output')
        else fixture_snapshot(content)
    )
    with database.transaction() as connection:
        profile = connection.execute(
            'SELECT profile_id FROM code_execution_profile_versions WHERE id=?', (version,)
        ).fetchone()[0]
        scope = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?',
                (grant,),
            ).fetchone()
        )['scope']
        maximum = min(
            content['limits']['max_check_output_bytes'], scope['limits']['max_check_output_bytes']
        )
    invalid_target = ()
    if change_checks in ('models', 'delivery'):
        invalid_target = (change_checks,)
    if change_checks == 'controls':
        invalid = deepcopy(content)
        invalid['limits']['max_file_bytes'] += 1
        with resources(snapshot):
            result = publish(client, invalid)
            assert result.status_code == 201, result.text
            invalid_version = result.json()['data']['resource_id']
            result = approve(client, {'profile_version_id': invalid_version, 'scope': scope})
            assert result.status_code == 201, result.text
            invalid_target = (str(invalid_version), str(result.json()['data']['resource_id']))
    frontend = tmp_path / 'compiled'
    build = subprocess.run(
        [
            str(NODE),
            str(ROOT / 'frontend/node_modules/vite/bin/vite.js'),
            'build',
            '--outDir',
            str(frontend),
            '--logLevel',
            'error',
        ],
        cwd=ROOT / 'frontend',
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    initial = client.get(f'/api/v1/code-tasks/{task}')
    assert initial.status_code == 200, initial.text
    app = client.app
    install_frontend(app, frontend)
    nonce = uuid4().hex

    class ApplicationReads(ReadOnlyDriver):
        application_unknown = False

        def observe_control_configuration(self, *args):
            observed = super().observe_control_configuration(*args)
            if self.application_unknown and len(self.calls) >= unknown_stage - 1:
                return None
            return observed

    native = ApplicationReads(idle_task)

    @app.post('/__v20_fixture/live-control/{outcome}')
    def observe(outcome: str, request: Request):
        if request.headers.get('X-Fixture-Nonce') != nonce or outcome not in (
            'unknown',
            'success',
            'unavailable',
            'ready',
        ):
            raise HTTPException(404)
        if outcome in ('unavailable', 'ready'):
            app.state.walle_repository_registration.accepts_live_configuration = outcome == 'ready'
            return {'advanced': True}
        native.application_unknown = outcome == 'unknown'
        return {
            'advanced': advance_live_configuration(
                runtime, native, cancelled=lambda: False, check_admissions=admissions
            )
        }

    work = tmp_path / 'browser'
    work.mkdir()
    with resources(snapshot), serve_original_app(app, lifespan='off') as origin:
        command = [
            str(NODE),
            str(ROOT / 'tools/verify-v20-live-control-http.mjs'),
            str(work),
            str(entry),
            origin,
            *(str(item) for item in (task, profile, version, grant)),
            nonce,
            str(content['check_set_version_id']),
            str(maximum),
            *invalid_target,
        ]
        script = (
            'import subprocess,os;from pathlib import Path;env=dict(os.environ);'
            + f"env['WALLE_CHECK_TEMP']={os.environ['WALLE_CHECK_TEMP']!r};"
            + f"env['WALLE_FIXTURE_UNKNOWN_STAGE']={str(unknown_stage)!r};"
            + f'result=subprocess.run({command!r},env=env,capture_output=True,timeout=100);'
            + "Path('browser-result.txt').write_bytes(result.stdout+result.stderr);"
            + 'raise SystemExit(result.returncode)'
        )
        job = OwnedJob(active_process_limit=96, job_memory_limit_bytes=4 * 1024**3)
        child = None
        try:
            child = TestSuspendedRoot(job, work, script)
            child.resume()
            deadline = monotonic() + 110
            with ObservedProcess(child.pid) as process:
                while process.observe().state == 'RUNNING' and monotonic() < deadline:
                    sleep(0.03)
                observed = process.observe()
            diagnostic = work / 'browser-result.txt'
            result = (
                diagnostic.read_text(encoding='utf-8', errors='replace')
                if diagnostic.exists()
                else repr(observed)
            )
            assert observed.exit_code == 0, result
            assert 'V20_LIVE_CONTROL_HTTP_BROWSER_PASSED' in result, result
        finally:
            _close(job, child)
    current = client.get(f'/api/v1/code-tasks/{task}')
    assert current.status_code == 200, current.text
    view = current.json()['data']
    assert (view['execution_profile_version_id'], view['authorization_id']) == (version, grant)
    assert view['configuration_application']['status'] == 'APPLIED'
    assert view['budget']['limit_cny'] == '0.200000'
    assert view['active_session_id'] == ingress.window.execution_session_id
    assert view['current_candidate_id'] == original['current_candidate_id']
    assert len(native.calls) == 4
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM code_operations WHERE task_id=? AND operation_type='APPLY_CONFIGURATION'",
                (task,),
            ).fetchone()[0]
            == 1
        )
        assert connection.execute('SELECT COUNT(*) FROM llm_uses').fetchone()[0] == 0
