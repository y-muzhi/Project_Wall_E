"""Program-owned savepoints inside an existing Database transaction.

The SQLite authorizer still denies callback COMMIT/ROLLBACK/SAVEPOINT commands.
Only the owner opens a brief permission for one exact savepoint instruction.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import sqlite3


@dataclass
class TransactionControl:
    connection: sqlite3.Connection
    savepoint_permission: tuple[str, str] | None = None
    business_active: bool = False

    def _execute(self, operation: str, sql: str) -> None:
        if self.savepoint_permission is not None:
            raise RuntimeError('Reentrant transaction control is forbidden')
        self.savepoint_permission = (operation, 'walle_business')
        try:
            self.connection.execute(sql)
        finally:
            self.savepoint_permission = None

    @contextmanager
    def reversible(self):
        if (
            self.business_active
            or not self.connection.in_transaction
            or self.connection.execute('PRAGMA query_only').fetchone()[0] != 0
        ):
            raise RuntimeError('A single owned write transaction is required')
        self._execute('BEGIN', 'SAVEPOINT "walle_business"')
        self.business_active = True
        attempt = BusinessAttempt(self)
        try:
            try:
                yield attempt
            except BaseException:
                attempt.rollback()
                raise
        finally:
            try:
                self._execute('RELEASE', 'RELEASE SAVEPOINT "walle_business"')
            finally:
                self.business_active = False
                attempt.active = False


@dataclass
class BusinessAttempt:
    control: TransactionControl
    active: bool = True
    rolled_back: bool = False

    def rollback(self) -> None:
        if not self.active or not self.control.business_active:
            raise RuntimeError('The business attempt has ended')
        if not self.rolled_back:
            self.control._execute('ROLLBACK', 'ROLLBACK TO SAVEPOINT "walle_business"')
            self.rolled_back = True
