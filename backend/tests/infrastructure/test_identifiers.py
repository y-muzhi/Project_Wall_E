from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier
import unittest

from backend.app.infrastructure.database import Database
from backend.app.infrastructure.identifiers import CapacityExhausted, EntityKind, block_id, entity_id, increment, message_sequence, requirement_number, revision_number
from backend.app.shared.validation import MAX_SAFE_INTEGER


class IdentifierTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='walle-ids-test-')
        self.database = Database(Path(self.directory.name) / 'ids.sqlite')
        self.database.initialize()

    def tearDown(self):
        self.directory.cleanup()

    def test_entity_kinds_and_business_numbers_are_independent_and_persistent(self):
        with self.database.transaction(write=True) as connection:
            self.assertEqual(entity_id(connection, EntityKind.REQUIREMENT), 1)
            self.assertEqual(entity_id(connection, EntityKind.COMMENT), 1)
            self.assertEqual(requirement_number(connection), 'REQ000001')
        reopened = Database(self.database.path)
        with reopened.transaction(write=True) as connection:
            self.assertEqual(entity_id(connection, EntityKind.REQUIREMENT), 2)
            self.assertEqual(requirement_number(connection), 'REQ000002')
        with self.database.transaction() as connection:
            with self.assertRaises(RuntimeError):
                entity_id(connection, EntityKind.COMMENT)
        with self.database.transaction(write=True) as connection:
            with self.assertRaises(ValueError):
                entity_id(connection, 'Unregistered')

    def test_rollbacks_do_not_consume_ids(self):
        with self.assertRaises(RuntimeError):
            with self.database.transaction(write=True) as connection:
                entity_id(connection, EntityKind.DOCUMENT)
                requirement_number(connection)
                raise RuntimeError('injected before business commit')
        with self.database.transaction(write=True) as connection:
            self.assertEqual(entity_id(connection, EntityKind.DOCUMENT), 1)
            self.assertEqual(requirement_number(connection), 'REQ000001')

    def test_actual_concurrent_allocations_have_no_duplicate_success(self):
        barrier = Barrier(6)
        def allocate(_):
            barrier.wait(timeout=5)
            with self.database.transaction(write=True) as connection:
                return entity_id(connection, EntityKind.GUIDE_RUN), requirement_number(connection)
        with ThreadPoolExecutor(max_workers=6) as executor:
            values = list(executor.map(allocate, range(6)))
        self.assertEqual(sorted(x[0] for x in values), list(range(1, 7)))
        self.assertEqual(sorted(x[1] for x in values), [f'REQ{x:06d}' for x in range(1, 7)])

    def test_last_entity_and_req_number_succeed_then_exhaust_without_mutation(self):
        with self.database.transaction(write=True) as connection:
            connection.executemany('INSERT INTO sequences VALUES (?,?)', [('Comment', MAX_SAFE_INTEGER - 1), ('RequirementNumber', 999_998)])
            self.assertEqual(entity_id(connection, EntityKind.COMMENT), MAX_SAFE_INTEGER)
            self.assertEqual(requirement_number(connection), 'REQ999999')
        for allocator in (lambda c: entity_id(c, EntityKind.COMMENT), requirement_number):
            with self.assertRaises(CapacityExhausted):
                with self.database.transaction(write=True) as connection:
                    allocator(connection)
        with self.database.transaction() as connection:
            self.assertEqual(dict(connection.execute('SELECT entity_kind,last_value FROM sequences').fetchall()), {'Comment': MAX_SAFE_INTEGER, 'RequirementNumber': 999_999})

    def test_version_block_high_water_and_empty_local_sequences(self):
        self.assertEqual(increment(MAX_SAFE_INTEGER - 1), MAX_SAFE_INTEGER)
        self.assertEqual(block_id(MAX_SAFE_INTEGER - 1), (MAX_SAFE_INTEGER - 1, MAX_SAFE_INTEGER))
        for operation in (lambda: increment(MAX_SAFE_INTEGER), lambda: block_id(MAX_SAFE_INTEGER)):
            with self.assertRaises(CapacityExhausted):
                operation()
        for value in (True, 0, -1, '1', 1.0, MAX_SAFE_INTEGER + 1):
            with self.assertRaises(ValueError):
                increment(value)
        with self.database.transaction(write=True) as connection:
            self.assertEqual(message_sequence(connection, 101), 1)
            self.assertEqual(revision_number(connection, 101), 1)
        # Existing immutable message/revision allocation is also verified with
        # real fixtures when those capability units construct full aggregates.
