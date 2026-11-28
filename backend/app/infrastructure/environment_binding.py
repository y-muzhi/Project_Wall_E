"""Bind a fresh Schema200 database to one explicit environment and data generation."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re

from backend.app.shared.time import utc_milliseconds

from .data_retention import capture_retained_data, original_projections
from .database import SchemaMismatch, _statements
from .schema_inspection import verify_integrity, verify_schema
from .schema_v22_release import DocumentAiSchemaRelease

UUID_V4 = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}')


@dataclass(frozen=True)
class EnvironmentBinding:
    environment_id: str
    data_generation: str

    def __post_init__(self):
        for value in (self.environment_id, self.data_generation):
            if type(value) is not str or UUID_V4.fullmatch(value) is None:
                raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')


def _valid_time(value):
    try:
        return utc_milliseconds(datetime.fromisoformat(value)) == value
    except (ValueError, OverflowError, TypeError):
        return False


def _core_facts(release):
    if isinstance(release, DocumentAiSchemaRelease):
        return release.core_fresh_checksum, release.core_contract_sha256
    return release.fresh_checksum, release.schema_contract_sha256


def _verify_formation(connection, release, migrations, initialized_at):
    rows = connection.execute('SELECT * FROM formation_schema_state').fetchall()
    if len(rows) != 1 or len(migrations) != 2:
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    owner = tuple(rows[0])
    committed_at = owner[7]
    lifecycle = owner[4:7]
    if lifecycle == ('FRESH_V21', None, None):
        checksum = release.fresh_checksum
        if committed_at != initialized_at:
            raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    elif (
        lifecycle[0] == 'UPGRADED_V200'
        and type(lifecycle[1]) is str
        and UUID_V4.fullmatch(lifecycle[1])
        and type(lifecycle[2]) is str
        and re.fullmatch(r'[a-f0-9]{64}', lifecycle[2])
    ):
        checksum = release.formation_checksum
        if committed_at < initialized_at:
            raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    else:
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    if (
        owner[:4] != (1, 210, release.schema_contract_sha256, release.core_contract_sha256)
        or tuple(migrations[1]) != (210, checksum, committed_at)
        or not _valid_time(committed_at)
    ):
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')


def verify_snapshot_binding(connection, release, binding):
    """Verify persisted Schema200 history and owner within one transaction."""
    if not connection.in_transaction:
        raise SchemaMismatch('Binding verification needs an active transaction')
    verify_schema(connection, release.expected_schema)
    migrations = connection.execute(
        'SELECT version,checksum,applied_at FROM schema_migrations ORDER BY version'
    ).fetchall()
    states = connection.execute(
        'SELECT singleton_id,schema_version,schema_contract_sha256,origin,upgrade_id,'
        'source_data_sha256,committed_at FROM code_schema_state'
    ).fetchall()
    owners = connection.execute(
        'SELECT singleton_id,environment_id,data_generation,initialized_at FROM environment_binding'
    ).fetchall()
    if not migrations or len(states) != 1 or len(owners) != 1:
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')

    initialized_at = owners[0][3]
    checksum, contract = _core_facts(release)
    if (
        tuple(migrations[0]) != (200, checksum, initialized_at)
        or tuple(states[0]) != (1, 200, contract, 'FRESH_V20', None, None, initialized_at)
        or tuple(owners[0]) != (1, binding.environment_id, binding.data_generation, initialized_at)
        or not _valid_time(initialized_at)
    ):
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    if isinstance(release, DocumentAiSchemaRelease):
        _verify_formation(connection, release, migrations, initialized_at)
    elif len(migrations) != 1:
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    return initialized_at


def verify_binding(connection, release, binding):
    """Require the normal application database's WAL connection as well as its binding."""
    initialized_at = verify_snapshot_binding(connection, release, binding)
    if connection.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    return initialized_at


def write_formation_marker(connection, release, committed_at, *, operation=None, source=None):
    checksum = release.fresh_checksum
    origin = 'FRESH_V21'
    if operation is not None:
        checksum = release.formation_checksum
        origin = 'UPGRADED_V200'
    connection.execute(
        'INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (210,?,?)',
        (checksum, committed_at),
    )
    connection.execute(
        'INSERT INTO formation_schema_state(singleton_id,schema_version,schema_contract_sha256,'
        'core_contract_sha256,origin,upgrade_id,source_data_sha256,committed_at) '
        'VALUES (1,210,?,?,?,?,?,?)',
        (
            release.schema_contract_sha256,
            release.core_contract_sha256,
            origin,
            operation,
            source,
            committed_at,
        ),
    )


def document_ai_source_facts(connection):
    original = tuple(
        replace(projection, migration_ceiling=None)
        for projection in original_projections(connection)
    )
    retained = tuple(
        projection
        for projection in original
        if projection.table not in ('environment_binding', 'schema_migrations')
    )
    return capture_retained_data(connection, original), capture_retained_data(connection, retained)


def verify_document_ai_copy(connection, release, binding, operation, source, retained):
    initialized = verify_snapshot_binding(connection, release, binding)
    verify_integrity(connection)
    record = connection.execute(
        'SELECT origin,upgrade_id,source_data_sha256 FROM formation_schema_state'
    ).fetchone()
    projections = tuple(item.projection for item in retained.tables)
    if (
        record is None
        or tuple(record) != ('UPGRADED_V200', operation, source.sha256)
        or capture_retained_data(connection, projections) != retained
    ):
        raise SchemaMismatch('DOCUMENT_AI_CONVERSION_CHANGED_SOURCE_ROWS')
    return initialized


def extend_document_ai_copy(
    connection, source_release, target_release, old_binding, new_binding, operation, committed_at
):
    """Extend an isolated ordinary copy in the caller's exclusive transaction."""
    if (
        isinstance(source_release, DocumentAiSchemaRelease)
        or not isinstance(target_release, DocumentAiSchemaRelease)
        or _core_facts(source_release) != _core_facts(target_release)
        or old_binding.environment_id != new_binding.environment_id
        or old_binding.data_generation == new_binding.data_generation
        or type(operation) is not str
        or not UUID_V4.fullmatch(operation)
        or not _valid_time(committed_at)
    ):
        raise SchemaMismatch('DOCUMENT_AI_CONVERSION_MISMATCH')
    initialized_at = verify_binding(connection, source_release, old_binding)
    if committed_at < initialized_at:
        raise SchemaMismatch('DOCUMENT_AI_CONVERSION_MISMATCH')
    verify_integrity(connection)
    source, retained = document_ai_source_facts(connection)
    for statement in _statements(target_release.formation_sql):
        connection.execute(statement)
    changed = connection.execute(
        'UPDATE environment_binding SET data_generation=? WHERE environment_id=? AND data_generation=?',
        (new_binding.data_generation, old_binding.environment_id, old_binding.data_generation),
    )
    if changed.rowcount != 1:
        raise SchemaMismatch('DOCUMENT_AI_CONVERSION_MISMATCH')
    write_formation_marker(
        connection, target_release, committed_at, operation=operation, source=source.sha256
    )
    verify_document_ai_copy(connection, target_release, new_binding, operation, source, retained)
    return source.sha256


def write_initial_schema(connection, release, binding):
    """Initialize only an empty database in the caller's exclusive installation scope."""
    if (
        not connection.in_transaction
        or release.upgrade is not None
        or connection.execute('PRAGMA journal_mode').fetchone()[0] != 'wal'
    ):
        raise SchemaMismatch('Fresh initialization requires the new WAL transaction')
    if (
        connection.execute("SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'").fetchone()
        is not None
    ):
        raise SchemaMismatch('The initialization target already holds a schema')
    if (
        connection.execute("SELECT 1 FROM sqlite_schema WHERE name='sqlite_sequence'").fetchone()
        is not None
        and connection.execute('SELECT 1 FROM sqlite_sequence LIMIT 1').fetchone() is not None
    ):
        raise SchemaMismatch('Initialization target contains existing sequence data')
    for statement in _statements(release.fresh):
        connection.execute(statement)
    initialized_at = utc_milliseconds(datetime.now(timezone.utc))
    checksum, contract = _core_facts(release)
    connection.execute(
        'INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (200,?,?)',
        (checksum, initialized_at),
    )
    connection.execute(
        'INSERT INTO code_schema_state(singleton_id,schema_version,schema_contract_sha256,'
        'origin,upgrade_id,source_data_sha256,committed_at) '
        "VALUES (1,200,?,'FRESH_V20',NULL,NULL,?)",
        (contract, initialized_at),
    )
    connection.execute(
        'INSERT INTO environment_binding(singleton_id,environment_id,data_generation,initialized_at) '
        'VALUES (1,?,?,?)',
        (binding.environment_id, binding.data_generation, initialized_at),
    )
    if isinstance(release, DocumentAiSchemaRelease):
        write_formation_marker(connection, release, initialized_at)
    verify_binding(connection, release, binding)
    verify_integrity(connection)
