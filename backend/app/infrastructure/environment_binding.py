"""Bind a fresh Schema200 database to one explicit environment and data generation."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from backend.app.shared.time import utc_milliseconds

from .database import SchemaMismatch, _statements
from .schema_inspection import verify_integrity, verify_schema

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


def verify_binding(connection, release, binding):
    """Inspect complete schema, history and expected owner inside the caller's transaction."""
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
    if len(migrations) != 1 or len(states) != 1 or len(owners) != 1:
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')

    initialized_at = owners[0][3]
    if (
        tuple(migrations[0]) != (200, release.fresh_checksum, initialized_at)
        or tuple(states[0])
        != (1, 200, release.schema_contract_sha256, 'FRESH_V20', None, None, initialized_at)
        or tuple(owners[0]) != (1, binding.environment_id, binding.data_generation, initialized_at)
        or not _valid_time(initialized_at)
        or connection.execute('PRAGMA journal_mode').fetchone()[0] != 'wal'
    ):
        raise SchemaMismatch('ENVIRONMENT_BINDING_MISMATCH')
    return initialized_at


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
    connection.execute(
        'INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (200,?,?)',
        (release.fresh_checksum, initialized_at),
    )
    connection.execute(
        'INSERT INTO code_schema_state(singleton_id,schema_version,schema_contract_sha256,'
        'origin,upgrade_id,source_data_sha256,committed_at) '
        "VALUES (1,200,?,'FRESH_V20',NULL,NULL,?)",
        (release.schema_contract_sha256, initialized_at),
    )
    connection.execute(
        'INSERT INTO environment_binding(singleton_id,environment_id,data_generation,initialized_at) '
        'VALUES (1,?,?,?)',
        (binding.environment_id, binding.data_generation, initialized_at),
    )
    verify_binding(connection, release, binding)
    verify_integrity(connection)
