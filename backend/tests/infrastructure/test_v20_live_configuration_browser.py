"""Drive C39 through the actual compiled SPA, HTTP service and isolated Schema200."""

import os
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import httpx
import pytest
import uvicorn

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.schema_v20_release import load_release
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.service import create_app
from backend.tests.code_tasks.test_authorizations import approve, scope
from backend.tests.code_tasks.test_execution_profile_versions import publish, resources
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.infrastructure.test_v20_owned_browser_relay import _close
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path  # noqa: F401

_ROOT = Path(__file__).resolve().parents[3]
_NODE = Path(r'C:\Program Files\nodejs\node.exe')
_CHROME = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
_SCRIPT = """
const assert = require('node:assert/strict');
const [modulePath, chrome, origin, task, profile, version, grant] = process.argv.slice(1);
const {chromium} = require(modulePath);
(async () => {
  const browser = await chromium.launch({
    executablePath: chrome, chromiumSandbox: true, headless: true,
    args: ['--disable-background-networking', '--disable-component-update', '--disable-sync'],
  });
  try {
    const page = await browser.newPage({viewport: {width: 360, height: 800}});
    page.setDefaultTimeout(10000);
    const routePath = origin + '/api/v1/code-tasks/' + task + '/configuration';
    let writes = 0;
    let acceptance;
    await page.route(routePath, async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      writes += 1;
      const response = await route.fetch({maxRetries: 0});
      acceptance = await response.json();
      assert.equal(response.status(), 202);
      assert.equal(acceptance.data.operation_status, 'RUNNING');
      await route.abort('connectionreset');
    });
    await page.goto(origin + '/code-tasks/' + task);
    const open = page.getByRole('button', {name: '更换任务配置', exact: true});
    await open.click();
    const form = page.getByRole('form', {name: '选择任务配置'});
    await form.getByLabel('新执行配置').selectOption(profile);
    await form.getByLabel('新配置版本').selectOption(version);
    await form.getByLabel('新适用授权').selectOption(grant);
    await form.getByLabel('变更说明').fill('实际页面选择已批准配置');
    await form.getByRole('button', {name: '应用配置', exact: true}).click();
    const lookup = page.getByRole('button', {name: '核对原配置请求', exact: true});
    await lookup.waitFor();
    await page.reload();
    await lookup.click();
    await page.getByText(new RegExp('配置版本 #' + version + '.*待启动核对')).waitFor();
    assert.equal(await page.getByText(new RegExp('配置版本 #' + version + '.*已核实生效')).count(), 0);
    assert.equal(writes, 1);
    assert.ok(acceptance.data.operation_id > 0);
    await page.setViewportSize({width: 1280, height: 800});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
"""


@contextmanager
def serve_original_app(app, *, lifespan='on'):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host='127.0.0.1',
                port=port,
                log_level='warning',
                access_log=False,
                timeout_graceful_shutdown=5,
                lifespan=lifespan,
            )
        )
        thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 25
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.03)
            assert server.started, 'The isolated HTTP service did not start'
            yield f'http://127.0.0.1:{port}'
        finally:
            server.should_exit = True
            thread.join(8)
            if thread.is_alive():
                server.force_exit = True
                thread.join(3)
            assert not thread.is_alive(), 'The isolated HTTP service did not close'


def test_live_configuration_keeps_original_request_after_browser_disconnect(tmp_path):  # noqa: F811
    module = os.environ.get('WALLE_BROWSER_FIXTURE_MODULE')
    if not module:
        pytest.skip('Local Playwright fixture module not configured')
    module = Path(module).resolve(strict=True)
    assert _NODE.is_file() and _CHROME.is_file()
    assert tmp_path.resolve().is_relative_to(Path(os.environ['WALLE_CHECK_TEMP']).resolve())
    frontend = tmp_path / 'frontend'
    result = subprocess.run(
        [
            str(_NODE),
            str(_ROOT / 'frontend/node_modules/vite/bin/vite.js'),
            'build',
            '--outDir',
            str(frontend),
            '--logLevel',
            'error',
        ],
        cwd=_ROOT / 'frontend',
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    database = Database(tmp_path / 'configuration.sqlite', schema_release=load_release())
    database.initialize()
    app = create_app(database=database, frontend_directory=frontend)
    with (
        serve_original_app(app) as origin,
        httpx.Client(base_url=origin, trust_env=False) as client,
    ):
        task = seed_task(database, app.state.walle_runtime, client)
        with resources():
            published = publish(client)
            assert published.status_code == 201, published.text
            version = published.json()['data']['resource_id']
            approved = approve(client, {'profile_version_id': version, 'scope': scope()})
            assert approved.status_code == 201, approved.text
            grant = approved.json()['data']['resource_id']
            with database.transaction() as connection:
                profile = connection.execute(
                    'SELECT profile_id FROM code_execution_profile_versions WHERE id=?', (version,)
                ).fetchone()[0]
            command = [
                str(_NODE),
                '-e',
                _SCRIPT,
                str(module),
                str(_CHROME),
                origin,
                *(str(item) for item in (task, profile, version, grant)),
            ]
            worker_source = (
                'import subprocess; from pathlib import Path; '
                f'run = subprocess.run({command!r}, capture_output=True, timeout=55); '
                "Path('browser-result.txt').write_bytes(run.stderr); "
                'raise SystemExit(run.returncode)'
            )
            job = OwnedJob(active_process_limit=48, job_memory_limit_bytes=4 * 1024**3)
            child = None
            try:
                child = TestSuspendedRoot(job, tmp_path, worker_source)
                child.resume()
                deadline = monotonic() + 65
                with ObservedProcess(child.pid) as process:
                    while process.observe().state == 'RUNNING' and monotonic() < deadline:
                        sleep(0.03)
                    observed = process.observe()
                diagnostic = tmp_path / 'browser-result.txt'
                assert observed.exit_code == 0, (
                    diagnostic.read_text(encoding='utf-8') if diagnostic.exists() else observed
                )
            finally:
                _close(job, child)
            response = client.get(f'/api/v1/code-tasks/{task}')
            assert response.status_code == 200, response.text
            saved = response.json()['data']
            assert saved['configuration_application']['status'] == 'PENDING'
            assert saved['execution_profile_version_id'] == version
            assert saved['authorization_id'] == grant
            with database.transaction() as connection:
                assert (
                    connection.execute(
                        "SELECT count(*) FROM code_operations WHERE operation_type='APPLY_CONFIGURATION'"
                    ).fetchone()[0]
                    == 1
                )
                assert connection.execute('SELECT count(*) FROM code_instances').fetchone()[0] == 0
