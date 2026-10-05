"""Actual subprocess/TCP service and explicit crash fixtures on isolated DBs.

The private runner uses the production factory and uvicorn server. Its stdin
shutdown switch is test IPC, never a public route. The crash test deliberately
holds the native worker before orchestration; acceptance/SQL/recovery are real.
No Provider request, fake business result or production database is involved.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from time import monotonic, sleep
import unittest

import httpx

from backend.app.infrastructure.database import Database, ROOT
from backend.app.infrastructure.process_lock import ProcessLock, ProcessAlreadyRunning
from backend.tests.requirements import test_create_requirement as creation


RUNNER = r'''
import asyncio, sys
import uvicorn
from backend.app.service import create_app
from backend.app.guide.worker import GuideWorker

class HeldWorker(GuideWorker):
    async def _drive(self, run_id, lease):
        # Explicit diagnostic dispatch stall. Native acceptance remains RUNNING.
        await asyncio.Event().wait()

async def main():
    factory = (lambda db, catalog: HeldWorker(db, catalog=catalog)) if sys.argv[2] == 'held' else None
    server = uvicorn.Server(uvicorn.Config(create_app(worker_factory=factory),
        host='127.0.0.1', port=int(sys.argv[1]), workers=1,
        timeout_graceful_shutdown=10, log_level='warning'))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.01)
    if task.done():
        await task
        raise SystemExit(1)
    await asyncio.to_thread(sys.stdin.readline)
    server.should_exit = True
    await task

asyncio.run(main())
'''


class ServiceProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-service-process-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'actual.sqlite'
        self.processes = []
        self.addCleanup(self.close_all)
        self.client = httpx.Client(timeout=1, trust_env=False)
        self.addCleanup(self.client.close)

    def env(self):
        values = {key: value for key, value in os.environ.items() if not key.startswith('WALLE_MODEL_')}
        values['WALLE_DATABASE_PATH'] = str(self.path)
        values['PYTHONIOENCODING'] = 'utf-8'
        return values

    def initialize(self):
        result = subprocess.run([sys.executable, '-m', 'backend.app.infrastructure.database', 'init'],
            cwd=ROOT, env=self.env(), capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.path.is_file())

    def start(self, mode='normal', *, main=False):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        log = (Path(self.directory.name) / f'process-{len(self.processes)}.log').open('w+', encoding='utf-8')
        arguments = [sys.executable, '-m', 'backend.app'] if main else [sys.executable, '-c', RUNNER, str(port), mode]
        process = subprocess.Popen(arguments, cwd=ROOT,
            env=self.env(), stdin=subprocess.PIPE, stdout=log, stderr=log, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        entry = (process, log, f'http://127.0.0.1:{port}')
        self.processes.append(entry)
        return entry

    def output(self, entry):
        entry[1].flush(); entry[1].seek(0)
        return entry[1].read()

    def ready(self, entry):
        due = monotonic() + 15
        while monotonic() < due and entry[0].poll() is None:
            try:
                response = self.client.get(entry[2] + '/api/v1/requirements')
                if response.status_code == 200:
                    return response
            except httpx.HTTPError:
                pass
            sleep(0.03)
        self.fail('Actual service did not start: ' + self.output(entry))

    def stop(self, entry):
        process = entry[0]
        if process.poll() is None:
            process.stdin.write('shutdown\n'); process.stdin.flush()
            process.wait(timeout=20)
        self.assertEqual(process.returncode, 0, self.output(entry))

    def close_all(self):
        for process, log, _ in self.processes:
            if process.poll() is None:
                self.kill_owned_process(process)
            if process.stdin is not None:
                process.stdin.close()
            log.close()

    def kill_owned_process(self, process):
        # Windows venv python.exe can be a redirector with a child interpreter.
        # Terminate only this live, test-owned process tree, not just the launcher.
        if os.name == 'nt':
            result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, 'Owned test process tree did not terminate')
        else:
            process.kill()
        process.wait(timeout=5)

    def wait_for_actual_lock_release(self):
        due = monotonic() + 3
        while True:
            try:
                with ProcessLock.for_database(self.path): return
            except ProcessAlreadyRunning:
                if monotonic() >= due: raise
                sleep(0.02)

    def create(self, entry):
        payload = creation.CreateRequirementTests().payload(); payload.pop('idempotency_key')
        return self.client.post(entry[2] + '/api/v1/requirements', json=payload,
            headers={'Idempotency-Key': creation.KEY})

    def test_actual_cli_init_tcp_native_acceptance_second_process_refusal_graceful_close_and_restart(self):
        self.initialize(); first = self.start(); self.ready(first)
        created = self.create(first)
        self.assertEqual(created.status_code, 201, created.text)
        data = created.json()['data']; identity = data['guide_run_id']
        due = monotonic() + 5
        while monotonic() < due:
            run = self.client.get(first[2] + f'/api/v1/guide-runs/{identity}')
            if run.json()['data']['status'] == 'FAILED': break
            sleep(0.01)
        self.assertEqual(run.json()['data']['error_code'], 'CONFIG_INVALID')
        second = self.start(); second[0].wait(timeout=15)
        self.assertNotEqual(second[0].returncode, 0)
        self.assertIn('ProcessAlreadyRunning', self.output(second))
        self.assertEqual(self.client.get(first[2] + '/api/v1/requirements/1').status_code, 200)
        self.stop(first)
        with ProcessLock.for_database(self.path): pass
        restarted = self.start(); self.ready(restarted)
        replay = self.create(restarted)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json()['data'], data)
        self.assertNotEqual(replay.json()['meta']['request_id'], created.json()['meta']['request_id'])
        self.assertEqual(self.client.get(restarted[2] + f'/api/v1/guide-runs/{identity}').json()['data']['status'], 'FAILED')
        self.stop(restarted)

    def test_forced_process_death_releases_os_lock_and_next_actual_startup_interrupts_without_resend(self):
        self.initialize(); held = self.start('held'); self.ready(held)
        created = self.create(held); self.assertEqual(created.status_code, 201, created.text)
        identity = created.json()['data']['guide_run_id']
        actual = self.client.get(held[2] + f'/api/v1/guide-runs/{identity}')
        self.assertEqual(actual.json()['data']['status'], 'RUNNING')
        self.kill_owned_process(held[0])
        self.wait_for_actual_lock_release()
        restarted = self.start(); self.ready(restarted)
        interrupted = self.client.get(restarted[2] + f'/api/v1/guide-runs/{identity}')
        self.assertEqual(interrupted.status_code, 200)
        self.assertEqual(interrupted.json()['data']['status'], 'FAILED')
        self.assertEqual(interrupted.json()['data']['error_code'], 'INTERRUPTED')
        replay = self.create(restarted)
        self.assertEqual(replay.status_code, 201); self.assertEqual(replay.json()['data'], created.json()['data'])
        with Database(self.path).transaction() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM llm_uses').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM guide_runs').fetchone()[0], 1)
        self.stop(restarted)

    def test_actual_process_startup_missing_database_refuses_before_binding_and_does_not_initialize(self):
        entry = self.start(main=True); entry[0].wait(timeout=15)
        self.assertNotEqual(entry[0].returncode, 0)
        output = self.output(entry)
        self.assertIn('StorageUnavailable', output)
        self.assertIn('Application startup failed', output)
        self.assertNotIn('Uvicorn running on', output)
        self.assertFalse(self.path.exists())


if __name__ == '__main__': unittest.main()
