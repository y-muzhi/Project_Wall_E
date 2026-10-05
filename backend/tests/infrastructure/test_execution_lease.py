"""Actual file transactions and competing retirement/commit, no in-memory DB."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
import unittest

from backend.app.infrastructure.execution_lease import ExecutionLease, ExecutionRetired, LeasedDatabase
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database, StorageUnavailable
from backend.tests.requirements import test_create_requirement as creation


class ExecutionLeaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=creation.CreateRequirementTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.create();self.lease=ExecutionLease();self.database=LeasedDatabase(self.fixture.database,self.lease)

    def title(self):
        with self.fixture.database.transaction() as connection:return connection.execute('SELECT title FROM requirements WHERE id=1').fetchone()[0]

    def test_retirement_after_real_update_before_commit_rolls_back_and_rejects_future_reads(self):
        before=self.title();entered=Event();resume=Event()
        def write():
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirements SET title='retired write' WHERE id=1")
                entered.set();resume.wait(5)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(write);self.assertTrue(entered.wait(3));self.lease.retire();resume.set()
            with self.assertRaises(ExecutionRetired):future.result()
        self.assertEqual(self.title(),before)
        with self.assertRaises(ExecutionRetired):
            with self.database.transaction():pass
        self.assertEqual(self.lease._connections,set())

    def test_real_commit_before_retirement_remains_a_fact_no_late_second_write(self):
        with self.database.transaction(write=True) as connection:connection.execute("UPDATE requirements SET title='committed' WHERE id=1")
        self.lease.retire();self.assertEqual(self.title(),'committed')
        with self.assertRaises(ExecutionRetired):
            with self.database.transaction(write=True) as connection:connection.execute("UPDATE requirements SET title='late' WHERE id=1")
        self.assertEqual(self.title(),'committed')

    def test_native_exception_rolls_back_unregisters_without_retiring_valid_future_stage(self):
        before=self.title()
        with self.assertRaisesRegex(ValueError,'controlled'):
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirements SET title='rolled back' WHERE id=1")
                raise ValueError('controlled')
        self.assertEqual(self.title(),before);self.assertFalse(self.lease.retired);self.assertEqual(self.lease._connections,set())
        with self.database.transaction(write=True) as connection:connection.execute("UPDATE requirements SET title='next real stage' WHERE id=1")
        self.assertEqual(self.title(),'next real stage')

    def test_commit_ack_loss_is_not_rewritten_as_rollback_or_erased(self):
        class Lost(Database):
            @contextmanager
            def transaction(inner,*,write=False):
                with super().transaction(write=write) as connection:yield connection
                if write:raise CommitOutcomeUnknown('actual commit lost response')
        database=LeasedDatabase(Lost(self.fixture.path),self.lease)
        with self.assertRaises(CommitOutcomeUnknown):
            with database.transaction(write=True) as connection:connection.execute("UPDATE requirements SET title='real committed' WHERE id=1")
        self.assertEqual(self.title(),'real committed');self.assertEqual(self.lease._connections,set())

    def test_retirement_interrupts_real_long_sql_and_rolls_back(self):
        entered=Event()
        def work():
            with self.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirements SET title='uncommitted' WHERE id=1")
                connection.set_progress_handler(lambda:entered.set() or 0,100)
                connection.execute('WITH RECURSIVE nums(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM nums WHERE n<100000000) SELECT sum(n) FROM nums').fetchone()
        before=self.title()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(work);self.assertTrue(entered.wait(3));self.lease.retire()
            with self.assertRaises(StorageUnavailable):future.result(timeout=3)
        self.assertEqual(self.title(),before);self.assertEqual(self.lease._connections,set())
