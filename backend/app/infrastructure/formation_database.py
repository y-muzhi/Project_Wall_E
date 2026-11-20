"""Schema210 on the existing Database connection and short-transaction machinery."""

import sqlite3

from backend.app.shared.command_execution import operation_time

from .database import (
    CommitOutcomeUnknown,
    Database,
    Migration,
    SchemaMismatch,
    StorageUnavailable,
    _statements,
)
from .schema_inspection import verify_integrity, verify_schema
from .sqlite_runtime import require_active


def check_v21(connection, release):
    require_active()
    if not connection.in_transaction:
        raise SchemaMismatch('Schema210 validation requires one caller transaction')
    verify_schema(connection, release.expected_schema)
    states = connection.execute('SELECT * FROM formation_schema_state').fetchall()
    core_states = connection.execute('SELECT * FROM code_schema_state').fetchall()
    if len(states) != 1 or len(core_states) != 1:
        raise SchemaMismatch('Schema210 requires its target and core origin markers')
    state, core = states[0], core_states[0]
    if (
        state['singleton_id'] != 1
        or state['schema_version'] != 210
        or state['schema_contract_sha256'] != release.schema_contract_sha256
        or state['core_contract_sha256'] != release.core.schema_contract_sha256
        or core['singleton_id'] != 1
        or core['schema_version'] != 200
        or core['schema_contract_sha256'] != release.core.schema_contract_sha256
    ):
        raise SchemaMismatch('Schema210 released target or retained core contract differs')
    history = [
        (row['version'], row['checksum'])
        for row in connection.execute(
            'SELECT version,checksum FROM schema_migrations ORDER BY version'
        )
    ]
    if core['origin'] == 'FRESH_V20':
        expected_core = [(200, release.core.fresh_checksum)]
        if core['upgrade_id'] is not None or core['source_data_sha256'] is not None:
            raise SchemaMismatch('Fresh core must not invent upgrade evidence')
    elif core['origin'] == 'UPGRADED_V151':
        expected_core = [(151, Migration().checksum), (200, release.core.upgrade_checksum)]
        if not core['upgrade_id'] or not core['source_data_sha256']:
            raise SchemaMismatch('Retained upgraded core lost its provenance')
    else:
        raise SchemaMismatch('Unknown retained core origin')
    if state['origin'] == 'FRESH_V21':
        checksum = release.fresh_checksum
        if (
            core['origin'] != 'FRESH_V20'
            or state['upgrade_id'] is not None
            or state['source_data_sha256'] is not None
        ):
            raise SchemaMismatch('Fresh Schema210 history contains upgrade evidence')
    elif state['origin'] == 'UPGRADED_V200':
        checksum = release.upgrade_checksum
        if not state['upgrade_id'] or not state['source_data_sha256']:
            raise SchemaMismatch('Schema210 upgrade lost its fixed source evidence')
    else:
        raise SchemaMismatch('Unknown Schema210 origin')
    if history != [*expected_core, (210, checksum)]:
        raise SchemaMismatch('Schema210 migration history differs from the released origin')
    if connection.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'wal':
        raise SchemaMismatch('Schema210 requires WAL')
    return len(history)


class FormationDatabase(Database):
    """All repositories still receive the same real sqlite3.Connection."""

    def __init__(self, path, *, formation_release, busy_timeout_ms=5000, read_only=False):
        self.formation_release = formation_release
        super().__init__(
            path,
            schema_release=formation_release.core,
            busy_timeout_ms=busy_timeout_ms,
            read_only=read_only,
        )

    def _check_schema(self, connection):
        return check_v21(connection, self.formation_release)

    def _initialize_locked(self):
        release = self.formation_release
        statements = list(_statements(release.fresh))
        connection = self._connect(create=True)
        initialized = False
        try:
            objects = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE lower(name) NOT GLOB 'sqlite_*' LIMIT 1"
            ).fetchone()
            if objects is not None:
                connection.execute('BEGIN')
                check_v21(connection, release)
                connection.rollback()
            else:
                if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower() != 'wal':
                    raise StorageUnavailable('Schema210 WAL could not be enabled')
                connection.execute('BEGIN IMMEDIATE')
                if (
                    connection.execute(
                        "SELECT 1 FROM sqlite_schema WHERE lower(name) NOT GLOB 'sqlite_*' LIMIT 1"
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
                    raise SchemaMismatch('Initialization target contains prior sequence data')
                for statement in statements:
                    connection.execute(statement)
                at = operation_time(None)
                connection.executemany(
                    'INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (?,?,?)',
                    [(200, release.core.fresh_checksum, at), (210, release.fresh_checksum, at)],
                )
                connection.execute(
                    'INSERT INTO code_schema_state(singleton_id,schema_version,schema_contract_sha256,'
                    'origin,upgrade_id,source_data_sha256,committed_at) '
                    "VALUES(1,200,?,'FRESH_V20',NULL,NULL,?)",
                    (release.core.schema_contract_sha256, at),
                )
                connection.execute(
                    'INSERT INTO formation_schema_state(singleton_id,schema_version,'
                    'schema_contract_sha256,core_contract_sha256,origin,upgrade_id,source_data_sha256,committed_at) '
                    "VALUES(1,210,?,?,'FRESH_V21',NULL,NULL,?)",
                    (release.schema_contract_sha256, release.core.schema_contract_sha256, at),
                )
                check_v21(connection, release)
                verify_integrity(connection)
                try:
                    connection.commit()
                except sqlite3.Error as error:
                    raise CommitOutcomeUnknown(
                        'Schema210 initialization commit requires verification'
                    ) from error
                initialized = True
        except (SchemaMismatch, StorageUnavailable):
            raise
        except (sqlite3.Error, OSError) as error:
            raise StorageUnavailable(
                'Schema210 initialization failed; preserve the target'
            ) from error
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        with self.transaction() as reopened:
            verify_integrity(reopened)
        return {
            'schema_version': 210,
            'checksum': release.fresh_checksum,
            'initialized': initialized,
            'migrated': False,
            'path': str(self.path),
        }
