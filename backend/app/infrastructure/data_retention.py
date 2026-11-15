"""DB20-UPGRADE-1 typed old-column retention in a caller-owned read snapshot.

No database values are written or returned. Each field includes its storage type,
length and original bytes. Migration comparison uses the original column list.
"""

from dataclasses import dataclass
import hashlib
import sqlite3
import struct

from .database import Database, Migration, SchemaMismatch
from .schema_inspection import (
    SchemaSnapshot,
    inspect_schema,
    quote_identifier,
    require_snapshot,
    verify_integrity,
)

ENCODING = 'DB20-TYPED-ROWS-1'


@dataclass(frozen=True)
class TableProjection:
    table: str
    columns: tuple[str, ...]
    key_columns: tuple[str, ...]
    migration_ceiling: int | None = None

    def __post_init__(self) -> None:
        for name in (self.table, *self.columns, *self.key_columns):
            quote_identifier(name)
        if not self.columns or len(set(self.columns)) != len(self.columns):
            raise ValueError('A complete ordered column projection is required')
        if not self.key_columns or not set(self.key_columns) <= set(self.columns):
            raise ValueError('Projected primary-key columns are required')
        if self.migration_ceiling is not None and (
            self.table != 'schema_migrations'
            or type(self.migration_ceiling) is not int
            or self.migration_ceiling != 151
        ):
            raise ValueError('Only original 151 migration metadata may be filtered')


@dataclass(frozen=True)
class TableDigest:
    projection: TableProjection
    row_count: int
    sha256: str


@dataclass(frozen=True)
class RetentionManifest:
    tables: tuple[TableDigest, ...]
    sha256: str
    encoding: str = ENCODING


@dataclass(frozen=True)
class SourceInspection:
    schema: SchemaSnapshot
    data: RetentionManifest


def _part(digest, value: bytes) -> None:
    digest.update(struct.pack('>Q', len(value)))
    digest.update(value)


def _cell(kind: str, value: object) -> bytes:
    if kind == 'null' and value is None:
        return b'N'
    if kind == 'integer' and type(value) is int:
        return b'I' + struct.pack('>q', value)
    if kind == 'real' and type(value) is float:
        return b'R' + struct.pack('>d', value)
    if kind in ('text', 'blob') and type(value) is bytes:
        return (b'T' if kind == 'text' else b'B') + value
    raise SchemaMismatch('Unsupported SQLite storage value; preserve source')


def original_projections(connection: sqlite3.Connection) -> tuple[TableProjection, ...]:
    require_snapshot(connection)
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM main.sqlite_schema WHERE type='table' "
            "AND (lower(name) NOT GLOB 'sqlite_*' OR name='sqlite_sequence') ORDER BY name"
        )
    ]
    projections = []
    for name in names:
        info = list(connection.execute(f'PRAGMA main.table_xinfo({quote_identifier(name)})'))
        columns = tuple(row[1] for row in info)
        keys = tuple(row[1] for row in sorted(info, key=lambda row: row[5]) if row[5])
        if name == 'sqlite_sequence':
            keys = ('name',)
        projections.append(
            TableProjection(
                name,
                columns,
                keys,
                151 if name == 'schema_migrations' else None,
            )
        )
    return tuple(projections)


def capture_retained_data(
    connection: sqlite3.Connection,
    projections: tuple[TableProjection, ...] | None = None,
) -> RetentionManifest:
    require_snapshot(connection)
    selected = original_projections(connection) if projections is None else projections
    if len({item.table for item in selected}) != len(selected):
        raise ValueError('Duplicate retained table')
    tables = []
    complete = hashlib.sha256(ENCODING.encode('ascii'))
    for projection in sorted(selected, key=lambda item: item.table):
        digest = hashlib.sha256(ENCODING.encode('ascii'))
        _part(digest, projection.table.encode('utf-8'))
        for column in projection.columns:
            _part(digest, column.encode('utf-8'))
        _part(digest, b'END_COLUMNS')
        for key in projection.key_columns:
            _part(digest, key.encode('utf-8'))
        _part(digest, str(projection.migration_ceiling).encode('ascii'))
        fields = []
        for column in projection.columns:
            name = quote_identifier(column)
            fields.extend(
                (
                    f'typeof({name})',
                    f"CASE WHEN typeof({name}) IN ('integer','real') THEN {name} "
                    f'ELSE CAST({name} AS BLOB) END',
                )
            )
        sql = f'SELECT {",".join(fields)} FROM main.{quote_identifier(projection.table)}'
        parameters = ()
        if projection.migration_ceiling is not None:
            sql += ' WHERE version<=?'
            parameters = (projection.migration_ceiling,)
        sql += ' ORDER BY ' + ','.join(
            f'{quote_identifier(name)} COLLATE BINARY' for name in projection.key_columns
        )
        count = 0
        for row in connection.execute(sql, parameters):
            digest.update(b'ROW')
            for index in range(0, len(row), 2):
                _part(digest, _cell(row[index], row[index + 1]))
            count += 1
        digest.update(b'COUNT' + struct.pack('>Q', count))
        result = TableDigest(projection, count, digest.hexdigest())
        tables.append(result)
        _part(complete, projection.table.encode('utf-8'))
        _part(complete, bytes.fromhex(result.sha256))
    return RetentionManifest(tuple(tables), complete.hexdigest())


def verify_retained_data(connection: sqlite3.Connection, expected: RetentionManifest) -> None:
    if expected.encoding != ENCODING:
        raise SchemaMismatch('Unsupported retention encoding')
    actual = capture_retained_data(connection, tuple(item.projection for item in expected.tables))
    if actual != expected:
        raise SchemaMismatch('Original typed rows differ; preserve source and backup')


def inspect_v151_source(database: Database) -> SourceInspection:
    """Reuse frozen 151 validation; this does not grant maintenance authority.

    Path identity, audit backups, maintenance window, fixed runtime and package
    permissions are separate prerequisites, still unavailable for actual upgrade.
    """
    if database.migration.version != 151 or database.migration.checksum != Migration().checksum:
        raise SchemaMismatch('Only the frozen 151 source is supported')
    with database.transaction() as connection:
        # Pin and validate schema and data together, after the transaction begins.
        database._check_schema(connection)
        history = connection.execute(
            'SELECT version,checksum FROM schema_migrations ORDER BY version'
        ).fetchall()
        if len(history) != 1 or tuple(history[0]) != (151, database.migration.checksum):
            raise SchemaMismatch('Exact frozen 151 history is required')
        verify_integrity(connection)
        return SourceInspection(inspect_schema(connection), capture_retained_data(connection))
