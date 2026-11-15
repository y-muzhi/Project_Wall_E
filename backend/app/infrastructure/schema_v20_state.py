"""Schema200 final-contract/history validation on the existing Database connection."""

from datetime import datetime, timezone
import sqlite3

from backend.app.shared.time import utc_milliseconds
from .database import (
    Migration,
    SchemaMismatch,
    StorageUnavailable,
    CommitOutcomeUnknown,
    _statements,
)
from .schema_inspection import verify_schema, verify_integrity
from .sqlite_runtime import require_active


def check_v20(connection, release):
    """Read only; legitimate post-upgrade business writes need not match the old data hash."""
    require_active()
    if not connection.in_transaction:
        raise SchemaMismatch('Schema200 validation requires the caller transaction')
    verify_schema(connection, release.expected_schema)
    rows = connection.execute(
        'SELECT version,checksum FROM schema_migrations ORDER BY version'
    ).fetchall()
    states = connection.execute('SELECT * FROM code_schema_state').fetchall()
    if len(states) != 1:
        raise SchemaMismatch('Schema200 requires exactly one committed origin marker')
    state = states[0]
    if (
        state['singleton_id'] != 1
        or state['schema_version'] != 200
        or state['schema_contract_sha256'] != release.schema_contract_sha256
    ):
        raise SchemaMismatch('Schema200 origin marker differs from the released contract')
    history = [(row['version'], row['checksum']) for row in rows]
    if state['origin'] == 'FRESH_V20':
        if (
            history != [(200, release.fresh_checksum)]
            or state['upgrade_id'] is not None
            or state['source_data_sha256'] is not None
        ):
            raise SchemaMismatch('Fresh Schema200 history or source marker differs')
    elif state['origin'] == 'UPGRADED_V151':
        if (
            history != [(151, Migration().checksum), (200, release.upgrade_checksum)]
            or not state['upgrade_id']
            or not state['source_data_sha256']
        ):
            raise SchemaMismatch('Upgraded Schema200 history or source marker differs')
    else:
        raise SchemaMismatch('Unknown Schema200 origin')
    if connection.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'wal':
        raise SchemaMismatch('Schema200 requires the approved WAL configuration')
    return len(history)


def initialize_v20(database):
    """Explicit empty initialization, never an automatic migration of a nonempty database."""
    release = database.schema_release
    statements = list(_statements(release.fresh))
    connection = database._connect(create=True)
    initialized = False
    checksum = release.fresh_checksum
    try:
        # Inspection and DDL are serialized by the existing ProcessLock and SQLite writer lock.
        mode = connection.execute('PRAGMA journal_mode').fetchone()[0].lower()
        objects = connection.execute(
            "SELECT name FROM sqlite_schema WHERE lower(name) NOT GLOB 'sqlite_*'"
        ).fetchall()
        if objects:
            connection.execute('BEGIN')
            check_v20(connection, release)
            checksum = connection.execute(
                'SELECT checksum FROM schema_migrations WHERE version=200'
            ).fetchone()[0]
            connection.rollback()
        else:
            if mode != 'wal':
                mode = connection.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()
            if mode != 'wal':
                raise StorageUnavailable('WAL configuration could not be enabled')
            connection.execute('BEGIN IMMEDIATE')
            # A writer outside our application may have appeared after the first inspection.
            if (
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE lower(name) NOT GLOB 'sqlite_*'"
                ).fetchone()
                is not None
            ):
                raise SchemaMismatch('Initialization target changed; preserve it for review')
            if (
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name='sqlite_sequence'"
                ).fetchone()
                is not None
                and connection.execute('SELECT 1 FROM sqlite_sequence LIMIT 1').fetchone()
                is not None
            ):
                raise SchemaMismatch('Initialization target contains logical sequence data')
            for statement in statements:
                connection.execute(statement)
            now = utc_milliseconds(datetime.now(timezone.utc))
            connection.execute(
                'INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (200,?,?)',
                (release.fresh_checksum, now),
            )
            connection.execute(
                'INSERT INTO code_schema_state(singleton_id,schema_version,'
                'schema_contract_sha256,origin,upgrade_id,source_data_sha256,committed_at) '
                "VALUES (1,200,?,'FRESH_V20',NULL,NULL,?)",
                (release.schema_contract_sha256, now),
            )
            check_v20(connection, release)
            verify_integrity(connection)
            try:
                connection.commit()
            except sqlite3.Error as error:
                raise CommitOutcomeUnknown(
                    'Schema200 initialization commit requires verification'
                ) from error
            initialized = True
    except (SchemaMismatch, StorageUnavailable):
        raise
    except (sqlite3.Error, OSError) as error:
        raise StorageUnavailable('Schema200 initialization failed; preserve the target') from error
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
    # A new connection proves that the durable schema and marker can actually be reopened.
    with database.transaction() as reopened:
        verify_integrity(reopened)
    return {
        'schema_version': 200,
        'checksum': checksum,
        'initialized': initialized,
        'migrated': False,
        'path': str(database.path),
    }
