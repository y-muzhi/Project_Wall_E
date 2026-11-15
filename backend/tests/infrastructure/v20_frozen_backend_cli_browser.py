"""CLI-first browser inspection of the real prepared backend, with owned process cleanup."""

import ctypes
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from queue import Queue, Empty
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep
from uuid import uuid4

from backend.app.infrastructure.windows_job import OwnedJob
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from tools.quality_gate import environment, stop_owned

ROOT = Path(__file__).resolve().parents[3]
NPM = 'C:/Program Files/nodejs/npx.cmd'
CLI = '@playwright/cli@0.1.24'
DIGEST = 'a15a7f37d003f32413689a07a75e75679fec1b8703334e0d76c000ad8f172f14'


def main():
    artifact_parent = ROOT / 'output/playwright'
    artifact_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.we-frozen-ui-', dir=artifact_parent) as temporary:
        state = Path(temporary)
        for folder in ('home', 'appdata', 'localappdata', 'tmp'):
            (state / folder).mkdir()
        values = {
            'SystemRoot': os.environ['SystemRoot'],
            'SystemDrive': os.environ.get('SystemDrive', 'C:'),
            'PATH': os.pathsep.join(
                ('C:/Program Files/nodejs', str(Path(os.environ['SystemRoot']) / 'System32'))
            ),
            'USERPROFILE': str(state / 'home'),
            'APPDATA': str(state / 'appdata'),
            'LOCALAPPDATA': str(state / 'localappdata'),
            'TEMP': str(state / 'tmp'),
            'TMP': str(state / 'tmp'),
            'npm_config_cache': str(state / 'npm'),
            'npm_config_ignore_scripts': 'true',
            'npm_config_update_notifier': 'false',
            'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
        }
        config = {
            'browser': {
                'browserName': 'chromium',
                'launchOptions': {
                    'headless': True,
                    'chromiumSandbox': True,
                    'executablePath': 'C:/Program Files/Google/Chrome/Application/chrome.exe',
                    'args': [
                        '--disable-background-networking',
                        '--disable-component-update',
                        '--disable-sync',
                    ],
                },
                'contextOptions': {'viewport': {'width': 1440, 'height': 900}},
            },
        }
        with (state / 'playwright-cli.json').open('x', encoding='utf-8') as output:
            json.dump(config, output)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        stop_file = state / 'stop-http'
        package = ROOT / 'backend/distributions/windows/prepared-20261113-1758'
        http = subprocess.Popen(
            [
                sys.executable,
                '-B',
                '-u',
                str(ROOT / 'tools/python-v20.py'),
                str(ROOT / 'backend/tests/infrastructure/v20_frozen_backend_http_worker.py'),
                str(package),
                DIGEST,
                '--port',
                str(port),
                '--hold-file',
                str(stop_file),
            ],
            cwd=ROOT,
            env=environment(state),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        lines = Queue()

        def capture():
            for line in iter(http.stdout.readline, b''):
                lines.put(line.decode('utf-8', 'replace'))

        reader = Thread(target=capture, daemon=True)
        reader.start()
        job = OwnedJob(active_process_limit=64, job_memory_limit_bytes=1024 * 1024 * 1024)
        session = 'walle-frozen-' + uuid4().hex[:12]
        number = 0
        opened = False

        def command(*arguments):
            nonlocal number
            number += 1
            result_path = state / f'cli-result-{number}.txt'
            argv = [NPM, '--yes', '--package', CLI, 'playwright-cli', '-s=' + session, *arguments]
            source = (
                'import os,subprocess,sys\nfrom pathlib import Path\n'
                + 'values='
                + repr(values)
                + '\n'
                + 'p=subprocess.run('
                + repr(argv)
                + ',cwd='
                + repr(str(state))
                + ',env=values,capture_output=True,timeout=70)\n'
                + 'raw=b"EXIT="+str(p.returncode).encode()+b"\\n"+p.stdout+p.stderr\n'
                + 'with Path('
                + repr(str(result_path))
                + ').open("xb") as output: output.write(raw)\n'
                + 'raise SystemExit(p.returncode)\n'
            )
            root = TestSuspendedRoot(job, state, source)
            try:
                root.resume()
                assert job._kernel.WaitForSingleObject(root.info.process, 85000) == 0, (
                    'CLI command timed out'
                )
                assert result_path.exists(), 'CLI command did not record its bounded result'
                result = result_path.read_text(encoding='utf-8', errors='replace')
                print('BROWSER_CLI', arguments[0], result[:1800], flush=True)
                assert result.startswith('EXIT=0\n') and '### Error' not in result, result[-5000:]
                return result
            finally:
                root.close()

        def snapshot():
            result = command('snapshot')
            paths = re.findall(r'\(([^)]+\.ya?ml)\)', result)
            if not paths:
                paths = re.findall(r'(?m)^.*?([.]playwright-cli/[^\s]+[.]ya?ml)', result)
            assert paths, result
            path = (state / paths[-1]).resolve()
            assert path.is_relative_to(state.resolve())
            text = path.read_text(encoding='utf-8')
            print('BROWSER_DOM', text[:12000], flush=True)
            return text

        try:
            until = monotonic() + 60
            ready = False
            while monotonic() < until:
                try:
                    line = lines.get(timeout=1)
                except Empty:
                    assert http.poll() is None, 'Owned HTTP worker exited before readiness'
                    continue
                print(line.strip(), flush=True)
                if 'FROZEN_BACKEND_HTTP_PASSED' in line:
                    ready = True
                    break
            assert ready
            command(
                'open',
                f'http://127.0.0.1:{port}/',
                '--config',
                str(state / 'playwright-cli.json'),
            )
            opened = True
            text = snapshot()
            for label in ('代码开发', '测试验收'):
                match = re.search(r'button "' + label + r'"[^\n]*\[ref=(e[0-9]+)\]', text)
                assert match, 'Missing real navigation: ' + label
                command('click', match[1])
                text = snapshot()
                assert label in text
            command('resize', '900', '720')
            text = snapshot()
            assert '测试验收' in text and '代码开发' in text
            errors = command('console', 'error')
            assert not re.search(r'(?m)^\[ERROR\]', errors), errors
            print('FROZEN_BACKEND_BROWSER_CLI_PASSED', flush=True)
        finally:
            try:
                if opened:
                    command('close')
            finally:
                job.terminate_owned(1)
                until = monotonic() + 10
                while job.observe_members().process_ids and monotonic() < until:
                    sleep(0.02)
                assert not job.observe_members().process_ids and job.observe_members().complete
                job.close()
                stop_file.touch(exist_ok=False)
                try:
                    http.wait(timeout=20)
                finally:
                    if http.poll() is None:
                        stop_owned(http)
                reader.join(timeout=2)
                assert http.returncode == 0
        print('FROZEN_BROWSER_OWNED_JOB_AND_HTTP_CLEANED', flush=True)


if __name__ == '__main__':
    main()
