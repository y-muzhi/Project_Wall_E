"""Smoke the actual prepared backend EXE with a fresh temporary DB and owned port.

No application commands, model calls, user database/service replacement, Guard
installation or browser assertions. The ordinary backend listener is verified
against the original Popen PID before every request.
"""

import argparse
import hashlib
import json
import re
import socket
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def exercise(
    package, manifest_sha256, port, hold_file=None, browser_package=None, browser_check=None
):
    from backend.app.infrastructure.sqlite_runtime import activate

    activate()
    from backend.app.infrastructure.database import Database
    from backend.app.infrastructure.guard_backend_program import decode_backend_program_manifest
    from backend.app.infrastructure.schema_v20_release import load_release
    from backend.app.infrastructure.windows_process import ObservedProcess
    from backend.app.infrastructure.windows_task_endpoints import _listeners
    from tools.quality_gate import environment, stop_owned

    raw = (package / 'backend-program.v1.json').read_bytes()
    spec = decode_backend_program_manifest(raw, expected_sha256=manifest_sha256)
    members = {member.path: member for member in spec.files}

    def owners():
        return {
            pid
            for family in (socket.AF_INET, socket.AF_INET6)
            for _, observed_port, pid in _listeners(family)
            if observed_port == port
        }

    assert not owners(), 'Selected port is occupied; do not replace or probe another service'
    with TemporaryDirectory(prefix='walle-frozen-backend-http-') as temporary:
        root = Path(temporary)
        database = Database(root / 'fresh.sqlite', schema_release=load_release())
        database.initialize()
        values = environment(temporary)
        values['WALLE_DATABASE_PATH'] = str(database.path)
        executable = package / spec.entry
        process = subprocess.Popen(
            [str(executable), '--port', str(port)],
            cwd=root,
            env=values,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        rows = []
        try:
            with ObservedProcess(process.pid) as original:
                assert Path(original.identity.image_path) == executable
                assert not original.identity.is_appcontainer and not original.identity.is_elevated
                deadline = monotonic() + 45
                body = None
                while monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    listening = owners()
                    assert not listening or listening == {process.pid}, (
                        'Listener belongs to another process'
                    )
                    if listening:
                        try:
                            with urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                                if response.status == 200:
                                    body = response.read(1024 * 1024)
                                    break
                        except (HTTPError, URLError, TimeoutError):
                            pass
                    sleep(0.05)
                if body is None:
                    raise AssertionError('Prepared normal backend did not reach HTTP readiness')
                assert owners() == {process.pid}
                expected = members['_internal/frontend/dist/index.html']
                assert hashlib.sha256(body).hexdigest() == expected.sha256
                rows.append(('PACKAGED_INDEX', 200))
                scripts = re.findall(rb'<script[^>]+src="([^"]+)"', body)
                assert scripts
                for script in scripts:
                    path = script.decode('ascii')
                    assert path.startswith('/assets/') and owners() == {process.pid}
                    with urlopen(f'http://127.0.0.1:{port}' + path, timeout=5) as response:
                        actual = response.read(8 * 1024 * 1024)
                        assert response.status == 200
                    expected = members['_internal/frontend/dist' + path]
                    assert hashlib.sha256(actual).hexdigest() == expected.sha256
                rows.append(('PACKAGED_SCRIPT_BYTES', len(scripts)))
                for path in (
                    '/api/v1/requirements',
                    '/api/v1/code-execution-profiles',
                    '/api/v1/code-configuration-options?kind=RUNTIME&page=1',
                ):
                    assert owners() == {process.pid}
                    with urlopen(f'http://127.0.0.1:{port}' + path, timeout=15) as response:
                        value = json.loads(response.read(2 * 1024 * 1024))
                        assert response.status == 200 and 'data' in value
                    rows.append((path.split('?')[0], 200))
                if browser_package is not None:
                    from backend.tests.infrastructure.v20_real_browser_package_worker import (
                        exercise as check_browser,
                    )

                    if browser_check is None:
                        check_browser(browser_package, backend=(port, process.pid))
                    else:
                        browser_check(browser_package, (port, original.identity))
                with database.transaction() as connection:
                    assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
                    assert connection.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0
                print('FROZEN_BACKEND_HTTP_PASSED', rows, flush=True)
                if hold_file is not None:
                    until = monotonic() + 240
                    while not hold_file.exists() and monotonic() < until:
                        assert process.poll() is None and owners() == {process.pid}
                        sleep(0.1)
                    assert hold_file.exists(), 'Owned browser check exceeded its deadline'
                    with database.transaction() as connection:
                        assert (
                            connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
                        )
                        assert (
                            connection.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0
                        )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop_owned(process)
            log, _ = process.communicate(timeout=10)
            if not rows or len(rows) < 5:
                print(log[-7000:].decode('utf-8', 'replace'))
            assert process.pid not in owners(), 'Original test listener did not close'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('manifest_sha256')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--hold-file', type=Path)
    parser.add_argument('--browser-package', type=Path)
    values = parser.parse_args()
    exercise(
        values.package.resolve(strict=True),
        values.manifest_sha256,
        values.port,
        values.hold_file,
        None if values.browser_package is None else values.browser_package.resolve(strict=True),
    )


if __name__ == '__main__':
    main()
