"""CLI Chrome against actual C39/SQLite/native HTTP; Guard and supplier are explicit fixtures."""

import os
import subprocess
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from backend.app.code_tasks.task_live_configuration import advance_live_configuration
from backend.app.frontend import install_frontend
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure import test_v20_native_configuration_flow as joined
from backend.tests.infrastructure.test_v20_live_configuration_browser import serve_original_app
from backend.tests.infrastructure.test_v20_owned_browser_relay import _close
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot

package = joined.package
service = joined.service
isolated_readiness = joined.isolated_readiness
original_instance = joined.original_instance
ready = joined.ready
fixed_price = joined.fixed_price
opened = joined.opened
idle_task = joined.idle_task
versioned_runtime_fixture = joined.versioned_runtime_fixture
managed_roots = joined.managed_roots
native_task = joined.native_task
native_control = joined.native_control
native_creation_scope = joined.native_creation_scope

ROOT = Path(__file__).resolve().parents[3]
NODE = Path('C:/Program Files/nodejs/node.exe')


@pytest.mark.parametrize(
    'native_control',
    [
        {'directory_role': 'workspace', 'scope_fixture': 'native_creation_scope'},
    ],
    indirect=True,
)
@pytest.mark.parametrize('unknown_stage', [3, 4])
def test_browser_keeps_original_native_configuration_until_actual_group_is_adopted(
    native_task, native_control, monkeypatch, tmp_path, unknown_stage
):
    entry = os.environ.get('WALLE_BROWSER_CLI_ENTRY')
    if not entry:
        pytest.skip('An explicit installed Playwright CLI entry is required')
    entry = Path(entry).resolve(strict=True)
    driver, owner, scope, state, _ = joined.configured_driver(
        native_task, native_control, monkeypatch
    )
    database, runtime, client, _, _, task, _, _, _ = native_task
    proposal = joined.source.target(native_task, basis=False)
    old, grant, content, target_scope, snapshot = proposal
    version = old['execution_profile_version_id']
    with database.transaction() as connection:
        profile = connection.execute(
            'SELECT profile_id FROM code_execution_profile_versions WHERE id=?', (version,)
        ).fetchone()[0]
    maximum = min(
        content['limits']['max_check_output_bytes'],
        target_scope['limits']['max_check_output_bytes'],
    )
    frontend = tmp_path / 'compiled'
    built = subprocess.run(
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
    assert built.returncode == 0, built.stderr
    app = client.app
    install_frontend(app, frontend)
    nonce = uuid4().hex
    applying = driver.apply_native_configuration
    unknown = False
    patch_route = ('PATCH', '/session/' + joined.native._SESSION)
    query_route = ('GET', '/session/' + joined.native._SESSION)

    def native_application(*args, **kwargs):
        if unknown:
            if unknown_stage == 3 and kwargs['dispatch']:
                state['drops'].add(patch_route)
            elif unknown_stage == 4 and not kwargs['dispatch']:
                state['drops'].add(query_route)
        else:
            state['drops'].discard(patch_route)
            state['drops'].discard(query_route)
        return applying(*args, **kwargs)

    monkeypatch.setattr(driver, 'apply_native_configuration', native_application)

    @app.post('/__v20_fixture/live-control/{outcome}')
    def observe(outcome: str, request: Request):
        nonlocal unknown
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
        unknown = outcome == 'unknown'
        return {'advanced': advance_live_configuration(runtime, driver, cancelled=lambda: False)}

    work = tmp_path / 'native-browser'
    work.mkdir()
    with joined.source.live.resources(snapshot), serve_original_app(app, lifespan='off') as origin:
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
            'native-read',
        ]
        script = (
            'import subprocess,os;from pathlib import Path;env=dict(os.environ);'
            + f"env['WALLE_CHECK_TEMP']={os.environ['WALLE_CHECK_TEMP']!r};"
            + f"env['WALLE_FIXTURE_UNKNOWN_STAGE']={str(unknown_stage)!r};"
            + f'result=subprocess.run({command!r},env=env,capture_output=True,timeout=210);'
            + "Path('browser-result.txt').write_bytes(result.stdout+result.stderr);"
            + 'raise SystemExit(result.returncode)'
        )
        job = OwnedJob(active_process_limit=96, job_memory_limit_bytes=4 * 1024**3)
        child = None
        try:
            child = TestSuspendedRoot(job, work, script)
            child.resume()
            deadline = monotonic() + 220
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
    assert state['requests'].count(patch_route) == 1
    assert state['requests'].count(('POST', '/session')) == 1
    response = client.get(f'/api/v1/code-tasks/{task}')
    assert response.status_code == 200, response.text
    assert response.json()['data']['authorization_id'] == grant
    with driver._native_actions(owner, scope) as actions:
        assert len(actions._permission_history) == 1
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE operation_type='APPLY_CONFIGURATION'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
