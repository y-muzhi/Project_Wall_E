"""Private per-task SQL fence; retirement cannot authorize a late commit.

The actual Database still owns BEGIN/schema/authorizer/rollback/commit. Only
worker transactions use this wrapper; public command transactions stay native.
"""
from contextlib import contextmanager
import sqlite3
import sys
from threading import RLock

from .database import Database


class ExecutionRetired(BaseException):
    """Unwind every application Exception mapper and roll back the live stage."""


class ExecutionLease:
    def __init__(self):
        self._gate = RLock()
        self._retired = False
        self._connections = set()

    @property
    def retired(self):
        with self._gate: return self._retired

    def _check(self):
        if self._retired: raise ExecutionRetired()

    def retire(self):
        # Commit and retirement compete on the same gate. A completed commit
        # remains a fact; retirement winning rejects every following commit.
        with self._gate:
            self._retired = True
            for connection in tuple(self._connections):
                try: connection.interrupt()
                except sqlite3.Error: pass  # Already closed, never commit proof.


class LeasedDatabase(Database):
    def __init__(self, database, lease):
        self.database, self.lease = database, lease
        self.path = database.path
        self.busy_timeout_ms = database.busy_timeout_ms
        self.migration, self.migrations = database.migration, database.migrations

    @contextmanager
    def transaction(self, *, write=False):
        lease = self.lease
        with lease._gate: lease._check()
        manager = self.database.transaction(write=write)
        connection = manager.__enter__()
        registered = False
        try:
            with lease._gate:
                lease._check()
                lease._connections.add(connection); registered = True
            try:
                yield connection
            except BaseException:
                manager.__exit__(*sys.exc_info())
                raise
            else:
                with lease._gate:
                    if lease._retired:
                        error = ExecutionRetired()
                        manager.__exit__(type(error), error, None)
                        raise error
                    # Hold the fence through the actual commit and connection
                    # close, including an uncertain commit exception.
                    manager.__exit__(None, None, None)
        except BaseException:
            if not registered:
                manager.__exit__(*sys.exc_info())
            raise
        finally:
            with lease._gate: lease._connections.discard(connection)
