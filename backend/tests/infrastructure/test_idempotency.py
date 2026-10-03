from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import queue
import signal
import subprocess
import sys
import tempfile
from threading import Barrier, Thread
import unittest

from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Claim, Idempotency, IdempotencyConflict, Replay, RequestInProgress, Scope, Success, canonical_input, request_key
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.shared.validation import InvalidInput
from backend.tests.infrastructure.crash_worker import INPUT, SCOPE, SUCCESS
from backend.tests.infrastructure.test_database import insert_requirement

ROOT = Path(__file__).resolve().parents[3]
TIME = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-idempotency-test-')
        self.database = Database(Path(self.directory.name) / 'actual.sqlite')
        self.database.initialize()
        self.lock = ProcessLock.for_database(self.database.path).acquire()
        self.idempotency = Idempotency(self.database, self.lock, clock=lambda: TIME)

    def tearDown(self):
        if self.lock.owner_epoch is not None:
            self.lock.release()
        self.directory.cleanup()

    def test_canonical_comparison_uuid_scope_and_missing_null(self):
        self.assertEqual(canonical_input({'b': [1, 2], 'a': {'😀': '原文'}}), canonical_input({'a': {'😀': '原文'}, 'b': [1, 2]}))
        self.assertNotEqual(canonical_input({'a': [1, 2]}), canonical_input({'a': [2, 1]}))
        self.assertNotEqual(canonical_input({}), canonical_input({'description': None}))
        key = 'ABCDEF00-1234-4321-ABCD-012345678900'
        self.assertEqual(request_key(key), key.lower())
        for invalid in (None, '', key.replace('-', ''), '{' + key + '}', ' ' + key, key.replace('4321', '1321')):
            with self.subTest(invalid=invalid), self.assertRaises(InvalidInput):
                request_key(invalid)
        for invalid in ({'x': float('nan')}, {'x': object()}, {1: 'x'}, {'x': '\ud800'}, {'x': 9_007_199_254_740_992}):
            with self.assertRaises((ValueError, UnicodeError)):
                canonical_input(invalid)
        self.assertIsInstance(self.idempotency.claim(SCOPE, INPUT), Claim)
        with self.assertRaises(RequestInProgress):
            self.idempotency.claim(SCOPE, INPUT)
        with self.assertRaises(IdempotencyConflict):
            self.idempotency.claim(SCOPE, {'title': '其他'})
        self.assertIsInstance(self.idempotency.claim(Scope(SCOPE.capability_id, 'Requirement:1', SCOPE.key), INPUT), Claim)
        self.assertIsInstance(self.idempotency.claim(Scope('APP-DOC-CMD-C01', SCOPE.target_identity, SCOPE.key), INPUT), Claim)

    def test_success_and_business_atomic_replay_frozen_payload(self):
        def operation(connection):
            insert_requirement(connection)
            return SUCCESS
        success = self.idempotency.execute(SCOPE, INPUT, operation)
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET title='已改变' WHERE id=101")
        def forbidden(_):
            self.fail('Replay must not execute business again')
        replay = Idempotency(Database(self.database.path), self.lock).execute(SCOPE, INPUT, forbidden)
        self.assertEqual(success, replay)
        self.assertEqual(replay.http_status, 201)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)
            row = connection.execute('SELECT status,created_at,updated_at FROM idempotency_records').fetchone()
            self.assertEqual(tuple(row), ('SUCCEEDED', '2026-10-03T00:00:00.000Z', '2026-10-03T00:00:00.000Z'))

    def test_failure_rolls_back_and_releases_known_claim_for_recheck(self):
        def fail(connection):
            insert_requirement(connection)
            raise RuntimeError('injected after business write')
        with self.assertRaises(RuntimeError):
            self.idempotency.execute(SCOPE, INPUT, fail)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0], 0)
        self.assertIsInstance(self.idempotency.claim(SCOPE, INPUT), Claim)

    def test_reject_malformed_success_rolls_back_business(self):
        def invalid(connection):
            insert_requirement(connection)
            return Success({'code': 'CREATED', 'data': {'id': 101}, 'details': {'invalid': True}}, 201)
        with self.assertRaises(ValueError):
            self.idempotency.execute(SCOPE, INPUT, invalid)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 0)

    def test_barrier_competition_has_only_one_claim(self):
        barrier = Barrier(5)
        def compete(_):
            barrier.wait(timeout=5)
            try:
                return self.idempotency.claim(SCOPE, INPUT)
            except RequestInProgress:
                return 'PROCESSING'
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(compete, range(5)))
        self.assertEqual(sum(isinstance(item, Claim) for item in results), 1)
        self.assertEqual(results.count('PROCESSING'), 4)

    def test_commit_acknowledgment_failure_keeps_success_fact(self):
        original = self.database.transaction
        writes = 0
        @contextmanager
        def lost_acknowledgment(*, write=False):
            nonlocal writes
            with original(write=write) as connection:
                yield connection
            if write:
                writes += 1
                if writes == 2:  # Claim committed first; business committed second.
                    raise CommitOutcomeUnknown('Injected after real COMMIT, before acknowledgment')
        self.database.transaction = lost_acknowledgment
        def operation(connection):
            insert_requirement(connection)
            return SUCCESS
        with self.assertRaises(CommitOutcomeUnknown):
            self.idempotency.execute(SCOPE, INPUT, operation)
        self.database.transaction = original
        self.assertEqual(self.idempotency.execute(SCOPE, INPUT, lambda _: self.fail('must replay')), SUCCESS)

    def _worker(self, mode):
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        return subprocess.run([sys.executable, '-m', 'backend.tests.infrastructure.crash_worker', str(self.database.path), mode], cwd=ROOT, capture_output=True, text=True, timeout=10, creationflags=flags)

    def test_abrupt_crash_before_business_and_inside_business_recovery(self):
        for mode, exit_code in (('claimed', 21), ('uncommitted', 22)):
            with self.subTest(mode=mode):
                self.lock.release()
                result = self._worker(mode)
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.lock.acquire()
                self.idempotency = Idempotency(self.database, self.lock)
                with self.database.transaction() as connection:
                    self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 0)
                    self.assertEqual(connection.execute('SELECT status FROM idempotency_records').fetchone()[0], 'PROCESSING')
                self.assertEqual(self.idempotency.recover_previous_process(), 1)
                self.assertEqual(self.idempotency.recover_previous_process(), 0)

    def test_abrupt_exit_after_commit_replays_without_second_effect(self):
        self.lock.release()
        result = self._worker('committed')
        self.assertEqual(result.returncode, 23, result.stderr)
        self.lock.acquire()
        recovered = Idempotency(self.database, self.lock)
        self.assertEqual(recovered.recover_previous_process(), 0)
        self.assertEqual(recovered.execute(SCOPE, INPUT, lambda _: self.fail('duplicate effect')), SUCCESS)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM requirements').fetchone()[0], 1)

    def test_second_process_rejected_and_forced_termination_releases_os_lock(self):
        self.assertEqual(self._worker('hold-lock').returncode, 7)
        self.lock.release()
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        child = subprocess.Popen([sys.executable, '-m', 'backend.tests.infrastructure.crash_worker', str(self.database.path), 'hold-lock'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
        line_queue = queue.Queue()
        reader = Thread(target=lambda: line_queue.put(child.stdout.readline()), daemon=True)
        reader.start()
        try:
            ready = line_queue.get(timeout=5).strip().split()
            self.assertEqual(ready[0], 'READY')
            worker_pid = int(ready[1])
            self.assertEqual(self._worker('hold-lock').returncode, 7)
            # Windows venv python.exe is a launcher. Kill the actual interpreter
            # identified by the test fixture, rather than orphan its child.
            os.kill(worker_pid, signal.SIGTERM)
            child.wait(timeout=5)
            self.lock.acquire()
            self.lock.assert_owned()
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
            reader.join(timeout=5)

    def test_recovery_requires_held_correct_database_lock_and_preserves_current_claim(self):
        self.idempotency.claim(SCOPE, INPUT)
        self.assertEqual(self.idempotency.recover_previous_process(), 0)
        with ProcessLock(Path(self.directory.name) / 'wrong.lock') as wrong:
            with self.assertRaises(ValueError):
                Idempotency(self.database, wrong)
        self.lock.release()
        with self.assertRaises(RuntimeError):
            self.idempotency.recover_previous_process()
