"""SQLite initialization and shared short transactions (D-003 / INF-DB/TX).

No repository may commit the connection given by a transaction. Provider I/O
must happen outside this context. Startup worker recovery is a separate unit.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
from typing import Iterator
from uuid import uuid4

from backend.app.shared.time import utc_milliseconds
from .process_lock import ProcessLock

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MIGRATION = Path(__file__).with_name('migrations') / '001_initial.sql'
SCHEMA_VERSION = 4


class SchemaMismatch(RuntimeError):
    """Refuse unknown, incomplete, modified or newer databases without rewriting."""


class StorageUnavailable(RuntimeError):
    """Known transaction failure or inability to establish access."""


class CommitOutcomeUnknown(StorageUnavailable):
    """Do not equate a commit exception with proof that no data was committed."""


@dataclass(frozen=True)
class Migration:
    path: Path = DEFAULT_MIGRATION
    version: int = 1

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding='utf-8')

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


MIGRATIONS = (Migration(), Migration(DEFAULT_MIGRATION.with_name('002_idempotency_guards.sql'), 2), Migration(DEFAULT_MIGRATION.with_name('003_manual_edit_sources.sql'), 3), Migration(DEFAULT_MIGRATION.with_name('004_manual_identity_proofs.sql'), 4))


def configured_path() -> Path:
    return Path(os.environ.get('WALLE_DATABASE_PATH', ROOT / 'data' / 'wall-e.sqlite')).expanduser().resolve()


def _statements(sql: str) -> Iterator[str]:
    """Keep trigger BEGIN/END together; executescript would escape our transaction."""
    pending = ''
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    if pending.strip() and any(line.strip() and not line.lstrip().startswith('--') for line in pending.splitlines()):
        raise SchemaMismatch('Migration contains an incomplete SQL statement')


class Database:
    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5_000, migration: Migration | None = None):
        self.path = Path(path).resolve()
        if type(busy_timeout_ms) is not int or busy_timeout_ms < 0:
            raise ValueError('Nonnegative integer lock timeout required')
        self.busy_timeout_ms = busy_timeout_ms
        self.migration = migration or Migration()
        self.migrations = (migration,) if migration is not None else MIGRATIONS

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        if not create and not self.path.is_file():
            raise StorageUnavailable('Database has not been initialized')
        try:
            if create:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            mode = 'rwc' if create else 'rw'
            connection = sqlite3.connect(self.path.as_uri() + '?mode=' + mode, uri=True, isolation_level=None, timeout=self.busy_timeout_ms / 1_000)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA read_uncommitted=OFF')
            connection.execute(f'PRAGMA busy_timeout={self.busy_timeout_ms}')
            return connection
        except (OSError, sqlite3.Error) as error:
            if 'connection' in locals():
                connection.close()
            raise StorageUnavailable('Cannot establish database access') from error

    def _check_schema(self, connection: sqlite3.Connection, *, allow_previous: bool = False) -> int:
        try:
            rows = connection.execute('SELECT version, checksum FROM schema_migrations ORDER BY version').fetchall()
        except sqlite3.Error as error:
            raise SchemaMismatch('Missing schema version metadata; explicit initialization required') from error
        if not rows or len(rows) > len(self.migrations) or not allow_previous and len(rows) != len(self.migrations) or any(row['version'] != migration.version or row['checksum'] != migration.checksum for row, migration in zip(rows, self.migrations)):
            raise SchemaMismatch('Database version or migration checksum differs; preserve data and review migration')
        actual = {row['name']: (row['type'], row['sql']) for row in connection.execute("SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
        for statement in (statement for migration in self.migrations[:len(rows)] for statement in _statements(migration.sql)):
            match = re.search(r'CREATE\s+(TABLE|TRIGGER|(?:UNIQUE\s+)?INDEX)\s+([a-z_0-9]+)\b', statement)
            if match is None:
                continue
            name = match[2]
            expected = statement[match.start():].strip().removesuffix(';')
            kind = 'index' if 'INDEX' in match[1] else match[1].lower()
            if name not in actual or actual[name] != (kind, expected):
                raise SchemaMismatch(f'Missing or altered schema object: {name}; preserve database for review')
        mode = connection.execute('PRAGMA journal_mode').fetchone()[0]
        if mode.lower() != 'wal':
            raise SchemaMismatch('Database must use the approved WAL configuration')
        return len(rows)

    def initialize(self) -> dict[str, object]:
        """Atomic empty DB setup; repeated calls verify, never drop existing objects."""
        with ProcessLock.for_database(self.path):
            return self._initialize_locked()

    def _initialize_locked(self) -> dict[str, object]:
        # Parse all migrations before making any persistent change.
        statements = [list(_statements(migration.sql)) for migration in self.migrations]
        checksum = self.migrations[-1].checksum
        connection = self._connect(create=True)
        backup_path = None
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables:
                applied = self._check_schema(connection, allow_previous=True)
                if applied == len(self.migrations):
                    return {'schema_version': self.migrations[-1].version, 'checksum': checksum, 'initialized': False, 'migrated': False, 'path': str(self.path)}
                backup_path = self.path.with_name(self.path.name + f'.before-v{self.migrations[-1].version}-{uuid4().hex}.backup.sqlite')
                target = sqlite3.connect(backup_path)
                try:
                    connection.backup(target)
                finally:
                    target.close()
            else:
                applied = 0
            mode = connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]
            if mode.lower() != 'wal':
                raise StorageUnavailable('WAL configuration could not be enabled')
            connection.execute('BEGIN IMMEDIATE')
            for migration, statements_for_migration in zip(self.migrations[applied:], statements[applied:]):
                for statement in statements_for_migration:
                    connection.execute(statement)
                connection.execute('INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (?,?,?)', (migration.version, migration.checksum, utc_milliseconds(datetime.now(timezone.utc))))
            try:
                connection.commit()
            except sqlite3.Error as error:
                raise CommitOutcomeUnknown('Initialization commit must be verified before retry') from error
            self._check_schema(connection)
            return {'schema_version': self.migrations[-1].version, 'checksum': checksum, 'initialized': not tables, 'migrated': bool(tables), 'backup_path': str(backup_path) if backup_path else None, 'path': str(self.path)}
        except (SchemaMismatch, StorageUnavailable):
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            raise StorageUnavailable('Initialization failed; no partial schema accepted') from error
        except OSError as error:
            if connection.in_transaction:
                connection.rollback()
            raise StorageUnavailable('Migration backup could not complete; preserve database') from error
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Connection shared by all repositories; reads/counts share one snapshot."""
        connection = self._connect()
        try:
            self._check_schema(connection)
            connection.execute('PRAGMA query_only=' + ('OFF' if write else 'ON'))
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            def authorize(action: int, first: str | None, second: str | None, database: str | None, trigger: str | None) -> int:
                if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT):
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_PRAGMA and second is not None:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorize)
            yield connection
            connection.set_authorizer(None)
            if not connection.in_transaction:
                raise StorageUnavailable('Inner code must not commit or roll back the shared transaction')
            try:
                connection.commit()
            except sqlite3.Error as error:
                raise CommitOutcomeUnknown('Transaction commit must be verified from persisted facts') from error
        except BaseException as error:
            connection.set_authorizer(None)
            if connection.in_transaction:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    # Keep the original cause; this failed cleanup is not commit proof.
                    pass
            if isinstance(error, sqlite3.IntegrityError):
                # The capability must distinguish its unique/state conflict.
                raise
            if isinstance(error, sqlite3.Error):
                raise StorageUnavailable('Database operation could not complete') from error
            raise
        finally:
            connection.close()

    def backup_to(self, destination: Path | str) -> Path:
        """SQLite backup API; preserve an existing backup rather than overwrite."""
        target = Path(destination).resolve()
        if target == self.path or target.exists():
            raise ValueError('Backup must be a new destination')
        source = self._connect()
        backup = None
        try:
            self._check_schema(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = sqlite3.connect(target)
            source.backup(backup)
            return target
        except (OSError, sqlite3.Error) as error:
            raise StorageUnavailable('Backup could not complete; retain source') from error
        finally:
            if backup is not None:
                backup.close()
            source.close()


def main() -> None:
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Initialize or verify the approved WALL-E SQLite schema without overwriting existing data')
    parser.add_argument('command', choices=['init', 'check'])
    parser.add_argument('--database', type=Path, default=configured_path())
    arguments = parser.parse_args()
    database = Database(arguments.database)
    if arguments.command == 'init':
        print(json.dumps(database.initialize(), ensure_ascii=False))
    else:
        with database.transaction() as connection:
            version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        print(json.dumps({'schema_version': version, 'path': str(database.path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
