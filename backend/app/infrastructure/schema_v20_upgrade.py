"""Explicit offline DB20 transaction/recovery engine, never service startup.

The CLI/package planner must additionally seal backups, audit bytes, space and
rehearsal evidence before calling this engine on any normal database.
"""

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
import sqlite3

from backend.app.shared.time import utc_milliseconds
from .database import Database, Migration, SchemaMismatch, CommitOutcomeUnknown, _statements
from .data_retention import RetentionManifest, capture_retained_data, verify_retained_data
from .idempotency import request_key
from .process_lock import ProcessLock
from .schema_inspection import verify_integrity, quote_identifier
from .schema_v20_release import SchemaRelease
from .schema_v20_state import check_v20
from .sqlite_runtime import require_active
from .windows_local_paths import LocalPathGuard, FileIdentity, local_absolute_path
from .windows_private_package import PrivatePackageGuard


class MaintenanceSession:
    """Hold actual original paths and the application's OS lock, without stopping services."""

    def __init__(self, database_path, package_path, release, *, maintenance_window_confirmed):
        require_active()
        if maintenance_window_confirmed is not True or not isinstance(release, SchemaRelease):
            raise ValueError('An explicit maintenance window and verified release are required')
        self.source_path = local_absolute_path(database_path)
        self.database = None
        self.package_path = local_absolute_path(package_path)
        self.release = release
        self._stack = None
        self.source_guard = None
        self.package_guard = None
        self.process_lock = None

    def __enter__(self):
        if self._stack is not None:
            raise RuntimeError('Maintenance session is already active')
        stack = ExitStack()
        self._stack = stack
        try:
            self.source_guard = stack.enter_context(
                LocalPathGuard(self.source_path, directory=False)
            )
            self.database = Database(
                self.source_guard.identity.canonical_path, migration=Migration()
            )
            self.package_guard = stack.enter_context(PrivatePackageGuard(self.package_path))
            # A stale file is not lock ownership; its original path must still be a regular file.
            lock_path = self.database.path.with_suffix(self.database.path.suffix + '.lock')
            if not lock_path.exists():
                with lock_path.open('xb') as stream:
                    stream.write(b'\0')
                    stream.flush()
                    os.fsync(stream.fileno())
            stack.enter_context(LocalPathGuard(lock_path, directory=False))
            self.process_lock = stack.enter_context(ProcessLock.for_database(self.database.path))
            self.verify()
            return self
        except BaseException:
            self.close()
            raise

    def verify(self):
        if self._stack is None or self.process_lock is None:
            raise RuntimeError('An active maintenance session is required')
        self.process_lock.assert_owned()
        self.source_guard.verify()
        self.package_guard.verify()

    def close(self):
        stack = self._stack
        self._stack = None
        try:
            if stack is not None:
                stack.close()
        finally:
            self.source_guard = None
            self.package_guard = None
            self.process_lock = None

    def __exit__(self, kind, error, traceback):
        self.close()


@dataclass(frozen=True)
class UpgradeIntent:
    upgrade_id: str
    release_manifest_sha256: str
    source_identity: FileIdentity
    retained: RetentionManifest

    def __post_init__(self):
        if request_key(self.upgrade_id) != self.upgrade_id:
            raise ValueError('Upgrade identity must be lowercase UUID v4')
        if re.fullmatch(r'[0-9a-f]{64}', self.release_manifest_sha256) is None:
            raise ValueError('The actual release manifest digest is required')
        if not isinstance(self.source_identity, FileIdentity) or self.source_identity.is_directory:
            raise ValueError('Original native database file identity is required')
        if not isinstance(self.retained, RetentionManifest):
            raise ValueError('The complete typed source manifest is required')


@dataclass(frozen=True)
class UpgradeObservation:
    status: str
    upgrade_id: str
    committed_at: str | None
    retained_data_matches: bool | None
    reason_code: str | None = None


def _bound(session, intent):
    session.verify()
    if (
        intent.release_manifest_sha256 != session.release.manifest_sha256
        or intent.source_identity != session.source_guard.identity
    ):
        raise SchemaMismatch('Upgrade identity, original path or release changed')


def _history(connection):
    return [
        tuple(row)
        for row in connection.execute(
            'SELECT version,checksum FROM schema_migrations ORDER BY version'
        )
    ]


def _marker(connection, release, intent):
    check_v20(connection, release)
    verify_integrity(connection)
    state = connection.execute('SELECT * FROM code_schema_state').fetchone()
    if (
        state['origin'] != 'UPGRADED_V151'
        or state['upgrade_id'] != intent.upgrade_id
        or state['source_data_sha256'] != intent.retained.sha256
    ):
        raise SchemaMismatch('The committed marker belongs to a different upgrade')
    matches = (
        capture_retained_data(
            connection, tuple(table.projection for table in intent.retained.tables)
        )
        == intent.retained
    )
    return UpgradeObservation(
        'ALREADY_COMMITTED',
        intent.upgrade_id,
        state['committed_at'],
        matches,
        None if matches else 'CURRENT_DATA_CHANGED',
    )


def _save_marker(connection, release, intent, at):
    connection.execute(
        'INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(200,?,?)',
        (release.upgrade_checksum, at),
    )
    connection.execute(
        'INSERT INTO code_schema_state VALUES(1,200,?,?,?,?,?)',
        (
            release.schema_contract_sha256,
            'UPGRADED_V151',
            intent.upgrade_id,
            intent.retained.sha256,
            at,
        ),
    )


def _new_business_tables_empty(connection, release, retained):
    old = {table.projection.table for table in retained.tables}
    for table in release.expected_schema.tables:
        if table.name in old or table.name == 'code_schema_state':
            continue
        if (
            connection.execute(f'SELECT 1 FROM {quote_identifier(table.name)} LIMIT 1').fetchone()
            is not None
        ):
            raise SchemaMismatch('Upgrade unexpectedly created new business data')


def _commit_once(connection):
    try:
        connection.commit()
    except sqlite3.Error as error:
        raise CommitOutcomeUnknown(
            'Upgrade commit must be reconciled from the original marker'
        ) from error


def _close_connection(connection):
    try:
        if connection.in_transaction:
            connection.rollback()
        connection.execute('PRAGMA foreign_keys=ON')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise SchemaMismatch('Maintenance connection foreign keys could not be restored')
    finally:
        connection.close()


def rebuild_locked(session: MaintenanceSession, intent: UpgradeIntent) -> UpgradeObservation:
    """One offline transaction, single commit; never replace the original database file."""
    _bound(session, intent)
    release = session.release
    connection = session.database._connect()
    committed = False
    observation = None
    try:
        connection.execute('PRAGMA foreign_keys=OFF')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 0:
            raise SchemaMismatch('Maintenance foreign-key setting could not be verified')
        connection.execute('BEGIN IMMEDIATE')
        _bound(session, intent)
        history = _history(connection)
        if any(version == 200 for version, _ in history):
            observation = _marker(connection, release, intent)
            connection.rollback()
        else:
            session.database._check_schema(connection)
            verify_integrity(connection)
            # Full source projections are regenerated; a caller cannot omit an old table.
            if capture_retained_data(connection) != intent.retained:
                raise SchemaMismatch('SOURCE_CHANGED: the approved source no longer matches')
            for statement in _statements(release.upgrade):
                connection.execute(statement)
            at = utc_milliseconds(datetime.now(timezone.utc))
            _save_marker(connection, release, intent, at)
            check_v20(connection, release)
            verify_retained_data(connection, intent.retained)
            _new_business_tables_empty(connection, release, intent.retained)
            verify_integrity(connection)
            _bound(session, intent)
            _commit_once(connection)
            committed = True
            observation = UpgradeObservation('UPGRADED', intent.upgrade_id, at, True)
    finally:
        _close_connection(connection)
    # A durable marker alone never substitutes for a new connection's structural health.
    try:
        _bound(session, intent)
        database = Database(session.database.path, schema_release=release, read_only=True)
        with database.transaction() as reopened:
            actual = _marker(reopened, release, intent)
            if committed:
                verify_retained_data(reopened, intent.retained)
                _new_business_tables_empty(reopened, release, intent.retained)
            if actual.committed_at != observation.committed_at:
                raise SchemaMismatch('Durable upgrade marker differs after reopening')
    except Exception as error:
        raise CommitOutcomeUnknown('Upgrade postconditions require explicit recovery') from error
    return observation


def recover_locked(session: MaintenanceSession, intent: UpgradeIntent) -> UpgradeObservation:
    """Read persisted facts for the original intent; never retry DDL or restore a backup."""
    _bound(session, intent)
    connection = Database(session.database.path, read_only=True)._connect()
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        history = _history(connection)
        if history == [(151, Migration().checksum)]:
            session.database._check_schema(connection)
            verify_integrity(connection)
            if capture_retained_data(connection) != intent.retained:
                return UpgradeObservation(
                    'UNKNOWN', intent.upgrade_id, None, False, 'SOURCE_CHANGED'
                )
            return UpgradeObservation('NOT_APPLIED', intent.upgrade_id, None, True)
        return _marker(connection, session.release, intent)
    except (SchemaMismatch, sqlite3.Error):
        return UpgradeObservation('UNKNOWN', intent.upgrade_id, None, None, 'DATABASE_UNVERIFIED')
    finally:
        connection.close()
