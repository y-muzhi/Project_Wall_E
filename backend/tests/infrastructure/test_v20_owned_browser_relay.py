"""Verify Chromium traffic against two original, independently owned Windows Jobs."""

import json
import os
import sys
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import pytest

from backend.app.infrastructure.owned_browser_relay import (
    BrowserApplication,
    BrowserRoute,
    OwnedBrowserRelay,
)
from backend.app.infrastructure.owned_check_http import OwnedHttpEndpoint, OwnedHttpUnavailable
from backend.app.infrastructure.runtime_launch_journal import (
    TestingLaunchScope as OriginalTestingScope,
)
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot

_APP = """
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
class App(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *_):
        pass
    def do_GET(self):
        found = self.path == app_path
        body = payload if found else b''
        self.send_response(200 if found else 404)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
with HTTPServer(('127.0.0.1', 0), App) as server:
    Path('ready').write_text(str(server.server_port), encoding='ascii')
    server.serve_forever()
"""
_FRONT = b"""<!doctype html><title>Owned candidate</title>
<button id="load">Load</button><output id="result"></output><script>
document.querySelector('#load').addEventListener('click', async () => {
  const response = await fetch('/api/status', {headers: {accept: 'application/json'}});
  document.querySelector('#result').textContent = (await response.json()).status;
});
</script>"""
_NODE = r"""
const {chromium} = require(process.argv[1]);
(async () => {
    const browser = await chromium.launch({
        executablePath: process.argv[2], headless: true, chromiumSandbox: true
    });
    try {
        const context = await browser.newContext({serviceWorkers: 'block'});
        const origin = 'http://candidate.invalid';
        let sequence = 0;
        await context.route('**/*', async route => {
            const request = route.request();
            const url = new URL(request.url());
            if (url.origin !== origin) { await route.abort(); return; }
            const headers = {};
            for (const key of ['accept', 'content-type']) {
                if (request.headers()[key]) headers[key] = request.headers()[key];
            }
            const response = await fetch(process.argv[3], {
                method: 'POST',
                body: JSON.stringify({seq: ++sequence, origin_ref: 'candidate',
                    path: url.pathname + url.search, method: request.method(), headers, body: ''})
            });
            if (!response.ok) { await route.abort(); return; }
            const data = await response.json();
            await route.fulfill({status: data.status, headers: Object.fromEntries(data.headers),
                body: Buffer.from(data.body, 'hex')});
        });
        const page = await context.newPage();
        await page.goto(origin + '/index.html', {timeout: 10000});
        await page.getByRole('button', {name: 'Load'}).click({timeout: 10000});
        await page.locator('#result').filter({hasText: 'from-owned-backend'}).waitFor({timeout: 10000});
    } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
"""


def _close(job, child):
    try:
        job.terminate_owned(1)
        deadline = monotonic() + 6
        while monotonic() < deadline:
            state = job.observe_members()
            if state.complete and not state.process_ids:
                return
            sleep(0.02)
        pytest.fail('Owned fixture Job did not empty')
    finally:
        job.close()
        if child is not None:
            child.close()


@contextmanager
def _application(root, nonce, ref, path, payload, mime):
    root.mkdir()
    job = OwnedJob(active_process_limit=2, job_memory_limit_bytes=128 * 1024**2)
    child = None
    try:
        with (root / 'payload').open('xb') as stream:
            stream.write(payload)
        source = (
            f'from pathlib import Path\napp_path={path!r}\nmime={mime!r}\npayload=Path("payload").read_bytes()\n'
            + _APP
        )
        child = TestSuspendedRoot(job, root, source, executable=sys._base_executable)
        child.resume()
        ready = root / 'ready'
        deadline = monotonic() + 10
        while (not ready.exists() or not ready.stat().st_size) and monotonic() < deadline:
            sleep(0.02)
        endpoint = OwnedHttpEndpoint(ref, int(ready.read_text(encoding='ascii')))
        scope = OriginalTestingScope('a' * 64, 1, 4, nonce * 32, 1, 1)

        def verify():
            members = job.observe_members()
            if not members.complete or child.pid not in members.process_ids:
                raise OwnedHttpUnavailable(
                    f'Fixture original Job differs: root={child.pid}, members={members!r}'
                )

        with ObservedProcess(child.pid) as process:
            yield BrowserApplication(scope, endpoint, process.identity, nonce * 64, verify)
    finally:
        _close(job, child)


def _relay(frontend, backend, intents):
    return OwnedBrowserRelay(
        OriginalTestingScope('a' * 64, 1, 4, 'c' * 32, 1, 1),
        (
            BrowserRoute('candidate', '/', 'FRONTEND', frontend),
            BrowserRoute('candidate', '/api/', 'BACKEND', backend),
        ),
        request_limit=8192,
        output_limit=32768,
        count_limit=8,
        before_send=lambda sequence, route, digest: intents.append((sequence, route.role, digest)),
    )


@contextmanager
def _bridge(relay):
    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            try:
                result = relay.send(json.loads(raw), deadline=monotonic() + 6, active=lambda: None)
            except RuntimeError:
                self.send_error(502)
                return
            wire = json.dumps(
                {'status': result.status, 'headers': result.headers, 'body': result.body.hex()}
            ).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

    with HTTPServer(('127.0.0.1', 0), Bridge) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}/'
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def browser_applications(tmp_path):
    with (
        _application(
            tmp_path / 'front', 'a', 'frontend', '/index.html', _FRONT, 'text/html'
        ) as front,
        _application(
            tmp_path / 'back',
            'b',
            'backend',
            '/api/status',
            b'{"status":"from-owned-backend"}',
            'application/json',
        ) as back,
    ):
        yield front, back


def test_browser_relay_routes_original_windows_roots_and_blocks_foreign_origin(
    browser_applications,
):
    front, back = browser_applications
    intents = []
    request = {'seq': 1, 'origin_ref': 'candidate', 'method': 'GET', 'headers': {}, 'body': ''}
    relay = _relay(front, back, intents)
    for sequence, path, expected in (
        (1, '/index.html', b'Owned candidate'),
        (2, '/api/status', b'from-owned-backend'),
    ):
        response = relay.send(
            {**request, 'seq': sequence, 'path': path},
            deadline=monotonic() + 6,
            active=lambda: None,
        )
        assert response.status == 200 and expected in response.body
    assert [(n, role, scope) for n, role, scope, _ in relay.traffic] == [
        (1, 'FRONTEND', front.scope),
        (2, 'BACKEND', back.scope),
    ]
    with pytest.raises(OwnedHttpUnavailable):
        _relay(front, back, intents).send(
            {**request, 'origin_ref': 'foreign', 'path': '/api/status'},
            deadline=monotonic() + 6,
            active=lambda: None,
        )
    assert [(n, role) for n, role, _ in intents] == [(1, 'FRONTEND'), (2, 'BACKEND')]


def test_real_chromium_page_fetches_through_both_original_jobs(tmp_path, browser_applications):
    module = os.environ.get('WALLE_BROWSER_FIXTURE_MODULE')
    if not module:
        pytest.skip('Local Playwright fixture module not configured')
    module = str(Path(module).resolve(strict=True))
    node = r'C:\Program Files\nodejs\node.exe'
    chrome = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    intents = []
    relay = _relay(*browser_applications, intents)
    job = OwnedJob(active_process_limit=40, job_memory_limit_bytes=3 * 1024**3)
    child = None
    with _bridge(relay) as target:
        command = [node, '-e', _NODE, module, chrome, target]
        code = (
            'import subprocess;from pathlib import Path;'
            "stream=Path('browser-check.log').open('xb');"
            f'raise SystemExit(subprocess.run({command!r},stdout=stream,stderr=stream).returncode)'
        )
        try:
            child = TestSuspendedRoot(job, tmp_path, code)
            child.resume()
            deadline = monotonic() + 40
            with ObservedProcess(child.pid) as process:
                while process.observe().state == 'RUNNING' and monotonic() < deadline:
                    sleep(0.04)
                observed = process.observe()
            log = tmp_path / 'browser-check.log'
            assert observed.state == 'EXITED' and observed.exit_code == 0, (
                log.read_text(encoding='utf-8', errors='replace') if log.exists() else observed
            )
            assert [(n, role) for n, role, _ in intents] == [(1, 'FRONTEND'), (2, 'BACKEND')]
        finally:
            _close(job, child)


@pytest.mark.parametrize(
    'size,budget,allowed',
    [
        (3 * 1024 * 1024, 8 * 1024 * 1024, True),
        (4 * 1024 * 1024 + 1, 8 * 1024 * 1024, False),
        (3 * 1024 * 1024, 1024 * 1024, False),
    ],
)
def test_large_asset_keeps_response_and_remaining_budget_bounds(tmp_path, size, budget, allowed):
    from backend.app.infrastructure.owned_check_http import OwnedHttpUnknown

    payload = b'x' * size
    with _application(
        tmp_path / 'asset', 'a', 'frontend', '/asset.js', payload, 'application/javascript'
    ) as app:
        relay = OwnedBrowserRelay(
            OriginalTestingScope('a' * 64, 1, 4, 'c' * 32, 1, 1),
            (BrowserRoute('candidate', '/', 'FRONTEND', app),),
            request_limit=8192,
            output_limit=budget,
            count_limit=2,
            before_send=lambda *_: None,
        )
        request = {
            'seq': 1,
            'origin_ref': 'candidate',
            'path': '/asset.js',
            'method': 'GET',
            'headers': {},
            'body': '',
        }
        if allowed:
            result = relay.send(request, deadline=monotonic() + 8, active=lambda: None)
            assert result.status == 200 and result.body == payload
        else:
            with pytest.raises(OwnedHttpUnknown, match='RELAY_RESULT_UNVERIFIED') as rejected:
                relay.send(request, deadline=monotonic() + 8, active=lambda: None)
            assert str(rejected.value.__cause__) == 'ORIGINAL_CHECK_HTTP_RESPONSE_LIMIT'
            assert relay.traffic == ()
