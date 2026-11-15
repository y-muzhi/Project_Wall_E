"""Real two-connection original-key races and receipts on isolated Schema200."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
import os
import sqlite3
import unittest

from backend.app.code_tasks.command_registry import registered_command
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import (
    Idempotency,
    Success,
    Claim,
    Scope,
    canonical_input,
)
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.schema_v20_release import (
    build_candidate,
    _load_verified_release,
    digest,
)
from backend.app.infrastructure.sqlite_runtime import require_active, RuntimeNotAdmitted
from backend.app.shared.code_errors import empty_conflict

KEY = '00000000-0000-4000-8000-000000000011'
AT = '2026-11-04T01:00:00.000Z'
try:
    require_active()
    ACTIVE = True
except RuntimeNotAdmitted:
    ACTIVE = False


@unittest.skipUnless(ACTIVE, 'Run through tools/python-v20.py')
class CommandReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TemporaryDirectory(
            prefix='v20-receipts-', dir=os.environ.get('WALLE_CHECK_TEMP', Path.cwd() / '.tmp')
        )
        cls.root = Path(cls.context.name)
        files = build_candidate('receipts-test')
        package = cls.root / 'package'
        package.mkdir()
        for name, content in files.items():
            with (package / name).open('xb') as stream:
                stream.write(content)
        cls.release = _load_verified_release(package, digest(files['manifest.json']))

    @classmethod
    def tearDownClass(cls):
        cls.context.cleanup()

    def setUp(self):
        directory = TemporaryDirectory(prefix='case-', dir=self.root)
        self.addCleanup(directory.cleanup)
        self.database = Database(Path(directory.name) / 'db.sqlite', schema_release=self.release)
        self.database.initialize()
        self.lock = ProcessLock.for_database(self.database.path).acquire()
        self.addCleanup(self.lock.release)
        self.executor = Idempotency(self.database, self.lock)
        self.scope = registered_command('POST', '/api/v1/code-execution-profiles', KEY).scope
        self.calls = 0

    def create_profile(self, connection):
        self.calls += 1
        connection.execute('INSERT INTO code_execution_profiles VALUES(1,?,?)', ('profile', AT))
        return Success(
            {
                'code': 'CREATED',
                'data': {'resource_kind': 'EXECUTION_PROFILE', 'resource_id': 1},
                'details': None,
            },
            201,
        )

    def test_close_before_late_receive_closes_whole_key_and_preserves_original_time(self):
        # A previously empty lookup is not authority to execute after this close.
        self.assertEqual(self.executor.command_receipt(self.scope)['lookup_status'], 'NOT_FOUND')
        closed = self.executor.close_command(self.scope)
        self.assertEqual(closed['close_status'], 'CLOSED')
        self.assertEqual(closed['original_receipt']['record_status'], 'CLOSED')
        for body in ({'name': 'different'}, {'invalid': object()}):
            result = self.executor.execute(self.scope, body, self.create_profile)
            self.assertIsInstance(result, Rejection)
            self.assertEqual(result.code, 'COMMAND_CLOSED')
            self.assertEqual(result.http_status, 409)
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.executor.close_command(self.scope), closed)
        with self.database.transaction() as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM code_execution_profiles').fetchone()[0], 0
            )
            self.assertEqual(
                connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0], 1
            )

    def test_success_is_replayed_and_close_only_reads_the_original_result(self):
        first = self.executor.execute(self.scope, {'name': 'profile'}, self.create_profile)
        second = self.executor.execute(self.scope, {'name': 'profile'}, self.create_profile)
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 1)
        conflict = self.executor.execute(self.scope, {'name': 'changed'}, self.create_profile)
        self.assertEqual(conflict.code, 'OPERATION_CONFLICT')
        closed = self.executor.close_command(self.scope)
        self.assertEqual(closed['close_status'], 'ALREADY_RECEIVED')
        receipt = closed['original_receipt']
        self.assertEqual(receipt['original_http_status'], 201)
        self.assertEqual(
            receipt['original_outcome'],
            {'success': True, 'data': first.result['data'], 'error': None},
        )
        with self.database.transaction(write=True) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('DELETE FROM idempotency_records')

    def test_certain_rejection_is_durable_and_never_revalidated_on_replay(self):
        rejected = Rejection('VERSION_CONFLICT', empty_conflict())
        first = self.executor.execute(self.scope, {'name': 'profile'}, lambda _: rejected)
        self.assertEqual(first, rejected)
        replay = self.executor.execute(self.scope, {'name': 'profile'}, self.create_profile)
        self.assertEqual(replay, rejected)
        self.assertEqual(self.calls, 0)
        receipt = self.executor.close_command(self.scope)['original_receipt']
        self.assertEqual(receipt['record_status'], 'REJECTED')
        self.assertEqual(receipt['original_http_status'], 409)
        self.assertEqual(receipt['original_outcome']['error']['code'], 'VERSION_CONFLICT')

    def test_certain_rejection_rolls_back_business_and_commits_only_the_original_claim(self):
        def rejected(connection):
            self.create_profile(connection)
            return Rejection('VERSION_CONFLICT', empty_conflict())

        result = self.executor.execute(self.scope, {}, rejected)
        self.assertEqual(result.code, 'VERSION_CONFLICT')
        self.assertEqual(self.executor.command_receipt(self.scope)['record_status'], 'REJECTED')
        with self.database.transaction() as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM code_execution_profiles').fetchone()[0], 0
            )
        self.executor.execute(
            self.scope, {}, lambda _: self.fail('A rejected command must not run again')
        )

    def test_application_4xx_exception_is_rejected_after_known_business_rollback(self):
        from backend.app.shared.command_execution import Rejected

        def rejected(connection):
            self.create_profile(connection)
            raise Rejected('NOT_FOUND')

        result = self.executor.execute(self.scope, {}, rejected)
        self.assertEqual(result.http_status, 404)
        with self.database.transaction() as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM code_execution_profiles').fetchone()[0], 0
            )
        self.assertEqual(self.executor.command_receipt(self.scope)['record_status'], 'REJECTED')

    def test_unknown_failure_and_500_are_never_converted_to_permanent_rejections(self):
        def failed(connection):
            self.create_profile(connection)
            raise RuntimeError('Injected failure with no accepted external work')

        with self.assertRaises(RuntimeError):
            self.executor.execute(self.scope, {}, failed)
        self.assertEqual(self.executor.command_receipt(self.scope)['lookup_status'], 'NOT_FOUND')
        with self.database.transaction() as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM code_execution_profiles').fetchone()[0], 0
            )
        with self.assertRaises(ValueError):
            self.executor.execute(self.scope, {}, lambda _: Rejection('INTERNAL_ERROR', None))
        self.assertEqual(self.executor.command_receipt(self.scope)['lookup_status'], 'NOT_FOUND')

    def test_owned_savepoint_does_not_permit_callback_transaction_control_or_foreign_reads(self):
        with self.database.transaction(write=True) as connection:
            with self.database.reversible(connection) as attempt:
                self.create_profile(connection)
                for sql in (
                    'COMMIT',
                    'ROLLBACK',
                    'SAVEPOINT walle_business',
                    'RELEASE SAVEPOINT walle_business',
                    'ROLLBACK TO SAVEPOINT walle_business',
                ):
                    with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                        connection.execute(sql)
                with self.assertRaises(RuntimeError):
                    with self.database.reversible(connection):
                        self.fail('Nested business savepoint must be rejected')
                attempt.rollback()
            with self.assertRaises(RuntimeError):
                attempt.rollback()
            self.assertEqual(
                connection.execute('SELECT count(*) FROM code_execution_profiles').fetchone()[0], 0
            )
        with self.database.transaction() as connection:
            with self.assertRaises(RuntimeError):
                with self.database.reversible(connection):
                    self.fail('Read snapshot cannot own business writes')
        self.assertEqual(self.database._transaction_controls, {})

    def test_processing_unknown_survives_startup_cleanup_and_cannot_be_abandoned(self):
        with self.database.transaction(write=True) as connection:
            for scope in (self.scope, Scope('APP-REQ-CMD-C01', 'old-document', KEY)):
                connection.execute(
                    'INSERT INTO idempotency_records(capability_id,target_identity,idempotency_key,business_input_json,status,owner_epoch,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                    (
                        *scope.identity,
                        canonical_input({}),
                        'PROCESSING',
                        'previous-process',
                        AT,
                        AT,
                    ),
                )
        self.assertEqual(self.executor.recover_previous_process(), 1)
        receipt = self.executor.command_receipt(self.scope)
        self.assertEqual(
            (receipt['lookup_status'], receipt['record_status']), ('UNKNOWN', 'PROCESSING')
        )
        self.assertEqual(
            self.executor.close_command(self.scope)['close_status'], 'ALREADY_RECEIVED'
        )
        self.assertEqual(
            self.executor.execute(self.scope, {}, self.create_profile).code, 'OPERATION_IN_PROGRESS'
        )
        with self.assertRaises(ValueError):
            self.executor.abandon(Claim(self.scope, '{}', self.executor.owner_epoch))
        with self.database.transaction(write=True) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('DELETE FROM idempotency_records')
        self.assertEqual(self.calls, 0)

    def test_isolated_claim_or_mismatched_scope_is_never_accepted(self):
        with self.assertRaises(ValueError):
            self.executor.claim(self.scope, {})
        bad = Scope('APP-TEST-CMD-C06', self.scope.target_identity, KEY)
        with self.assertRaises(ValueError):
            self.executor.execute(bad, {}, self.create_profile)
        self.assertEqual(self.calls, 0)

    def test_receive_commit_wins_real_second_connection_close(self):
        entered = Event()
        release = Event()

        def receive(connection):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Test release timeout')
            return self.create_profile(connection)

        with ThreadPoolExecutor(max_workers=2) as pool:
            receiving = pool.submit(self.executor.execute, self.scope, {'name': 'profile'}, receive)
            self.assertTrue(entered.wait(10))
            closing = pool.submit(self.executor.close_command, self.scope)
            release.set()
            self.assertEqual(receiving.result(timeout=15).http_status, 201)
            self.assertEqual(closing.result(timeout=15)['close_status'], 'ALREADY_RECEIVED')
        self.assertEqual(self.calls, 1)

    def test_lost_commit_ack_is_not_rejected_and_replay_does_not_execute_again(self):
        original = self.database.transaction
        armed = True

        @contextmanager
        def lost_ack(*, write=False):
            nonlocal armed
            with original(write=write) as connection:
                yield connection
            if write and armed:
                armed = False
                raise CommitOutcomeUnknown('Injected missing acknowledgment after durable commit')

        with patch.object(self.database, 'transaction', lost_ack):
            with self.assertRaises(CommitOutcomeUnknown):
                self.executor.execute(self.scope, {'name': 'profile'}, self.create_profile)
            receipt = self.executor.command_receipt(self.scope)
            self.assertEqual(receipt['record_status'], 'SUCCEEDED')
            self.assertEqual(
                self.executor.execute(
                    self.scope, {'name': 'profile'}, self.create_profile
                ).http_status,
                201,
            )
        self.assertEqual(self.calls, 1)

    def test_async_receipt_requires_real_original_operation_in_the_same_transaction(self):
        scope = registered_command('POST', '/api/v1/code-repositories/1/refresh', KEY).scope
        with self.database.transaction(write=True) as connection:
            # Only receipt ownership is under test; no Git readiness is claimed.
            connection.execute(
                'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
                (
                    'repository',
                    'C:/isolated-receipt-only',
                    'C:/isolated-receipt-only/.git',
                    'sha1',
                    AT,
                ),
            )
        success = Success(
            {
                'code': 'OPERATION_ACCEPTED',
                'data': {
                    'resource_kind': 'REPOSITORY',
                    'resource_id': 1,
                    'operation_id': 1,
                    'operation_status': 'PENDING',
                },
                'details': None,
            },
            202,
        )
        with self.assertRaises(ValueError):
            self.executor.execute(scope, {}, lambda _: success)

        def accept(connection):
            connection.execute(
                'INSERT INTO code_operations VALUES(1,NULL,NULL,?,?,NULL,?,?,NULL,?,NULL,?,?,NULL,NULL,NULL)',
                ('REPOSITORY', 1, 'REFRESH_REPOSITORY', KEY, '{}', 'PENDING', AT),
            )
            return success

        self.executor.execute(scope, {}, accept)
        receipt = self.executor.close_command(scope)['original_receipt']
        self.assertEqual(receipt['record_status'], 'SUCCEEDED')
        self.assertEqual(receipt['operation_id'], 1)
        self.assertIsNone(receipt['task_id'])
        self.assertIsNone(receipt['testing_task_id'])

    def test_close_commit_wins_a_real_late_receive_connection(self):
        entered = Event()
        release = Event()
        receiving = Event()

        def close_time():
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Test close release timeout')
            return AT

        def late_receive():
            receiving.set()
            return self.executor.execute(self.scope, {'name': 'profile'}, self.create_profile)

        with patch.object(self.executor, '_time', close_time):
            with ThreadPoolExecutor(max_workers=2) as pool:
                closing = pool.submit(self.executor.close_command, self.scope)
                self.assertTrue(entered.wait(10))
                late = pool.submit(late_receive)
                self.assertTrue(receiving.wait(10))
                release.set()
                self.assertEqual(closing.result(timeout=15)['close_status'], 'CLOSED')
                self.assertEqual(late.result(timeout=15).code, 'COMMAND_CLOSED')
        self.assertEqual(self.calls, 0)

    def test_unknown_close_commit_ack_requires_original_fact_and_never_reopens_the_key(self):
        original = self.database.transaction
        armed = True

        @contextmanager
        def lost_ack(*, write=False):
            nonlocal armed
            with original(write=write) as connection:
                yield connection
            if write and armed:
                armed = False
                raise CommitOutcomeUnknown('Injected close commit acknowledgment loss')

        with patch.object(self.database, 'transaction', lost_ack):
            with self.assertRaises(CommitOutcomeUnknown):
                self.executor.close_command(self.scope)
            self.assertEqual(self.executor.command_receipt(self.scope)['record_status'], 'CLOSED')
            self.assertEqual(self.executor.close_command(self.scope)['close_status'], 'CLOSED')
            self.assertEqual(
                self.executor.execute(self.scope, {}, self.create_profile).code, 'COMMAND_CLOSED'
            )
        self.assertEqual(self.calls, 0)
