"""Read-only DB20-UPGRADE-1 final objects; history is validated separately."""

import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache

from .database import SchemaMismatch


def quote_identifier(name: str) -> str:
    if type(name) is not str or not name or '\x00' in name:
        raise ValueError('A complete SQLite identifier is required')
    return '"' + name.replace('"', '""') + '"'


def _scan_sql_tokens(sql: str) -> tuple[str, ...]:
    """Normalize lexical whitespace only, preserving literals and token boundaries."""
    tokens = []
    position = 0
    while position < len(sql):
        char = sql[position]
        if char in ' \t\n\r\f':
            position += 1
            continue
        if sql.startswith('--', position):
            end = sql.find('\n', position)
            position = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith('/*', position):
            end = sql.find('*/', position + 2)
            if end < 0:
                raise SchemaMismatch('Unterminated SQL comment')
            position = end + 2
            continue
        start = position
        if char in (chr(39), chr(34), chr(96), '['):
            closing = ']' if char == '[' else char
            position += 1
            while position < len(sql):
                if sql[position] == closing:
                    position += 1
                    if char != '[' and position < len(sql) and sql[position] == closing:
                        position += 1
                        continue
                    break
                position += 1
            else:
                raise SchemaMismatch('Unterminated SQL quote')
            tokens.append(sql[start:position])
            continue
        number = re.match(
            r'(?:0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|(?:[0-9](?:_?[0-9])*(?:\.(?:[0-9](?:_?[0-9])*)?)?|\.[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?)',
            sql[position:],
        )
        if number is not None:
            token = number[0]
        elif char.isalpha() or char == '_' or ord(char) >= 128:
            position += 1
            while position < len(sql):
                part = sql[position]
                if not (part.isalnum() or part in '_$' or ord(part) >= 128):
                    break
                position += 1
            tokens.append(sql[start:position])
            continue
        else:
            token = next(
                (
                    op
                    for op in ('->>', '->', '||', '<<', '>>', '<=', '>=', '==', '!=', '<>')
                    if sql.startswith(op, position)
                ),
                char,
            )
        tokens.append(token)
        position += len(token)
    if tokens and tokens[-1] == ';':
        tokens.pop()
    return tuple(tokens)


@lru_cache(maxsize=512)
def _cached_sql_tokens(sql: str) -> tuple[str, ...]:
    return _scan_sql_tokens(sql)


def sql_tokens(sql: str) -> tuple[str, ...]:
    # This cache holds only exact text -> immutable lexical tokens. Every
    # schema inspection still reads the actual objects and every PRAGMA.
    if len(sql) > 8192:
        return _scan_sql_tokens(sql)
    return _cached_sql_tokens(sql)


@dataclass(frozen=True)
class SchemaObject:
    kind: str
    name: str
    table: str
    definition: tuple[str, ...]


@dataclass(frozen=True)
class TableStructure:
    name: str
    columns: tuple[tuple, ...]
    foreign_keys: tuple[tuple, ...]
    indexes: tuple[tuple, ...]
    index_columns: tuple[tuple[str, tuple[tuple, ...]], ...]
    without_rowid: int
    strict: int


@dataclass(frozen=True)
class SchemaSnapshot:
    objects: tuple[SchemaObject, ...]
    tables: tuple[TableStructure, ...]


def require_snapshot(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise ValueError('One explicit SQLite transaction is required')


def inspect_schema(connection: sqlite3.Connection) -> SchemaSnapshot:
    require_snapshot(connection)
    objects = tuple(
        SchemaObject(row[0], row[1], row[2], sql_tokens(row[3]))
        for row in connection.execute(
            'SELECT type,name,tbl_name,sql FROM main.sqlite_schema '
            "WHERE sql IS NOT NULL AND lower(name) NOT GLOB 'sqlite_*' ORDER BY type,name"
        )
    )
    flags = {
        row[1]: (row[4], row[5])
        for row in connection.execute('PRAGMA main.table_list')
        if row[0] == 'main'
    }
    tables = []
    for obj in objects:
        if obj.kind != 'table':
            continue
        name = quote_identifier(obj.name)
        columns = []
        for row in connection.execute(f'PRAGMA main.table_xinfo({name})'):
            values = list(row)
            if values[4] is not None:
                values[4] = sql_tokens(values[4])
            columns.append(tuple(values))
        indexes = tuple(
            sorted(tuple(row)[1:] for row in connection.execute(f'PRAGMA main.index_list({name})'))
        )
        index_columns = tuple(
            (
                index[0],
                tuple(
                    tuple(row)
                    for row in connection.execute(
                        f'PRAGMA main.index_xinfo({quote_identifier(index[0])})'
                    )
                ),
            )
            for index in indexes
        )
        without_rowid, strict = flags[obj.name]
        tables.append(
            TableStructure(
                obj.name,
                tuple(columns),
                tuple(
                    tuple(row)
                    for row in connection.execute(f'PRAGMA main.foreign_key_list({name})')
                ),
                indexes,
                index_columns,
                without_rowid,
                strict,
            )
        )
    return SchemaSnapshot(objects, tuple(tables))


def verify_schema(connection: sqlite3.Connection, expected: SchemaSnapshot) -> None:
    actual = inspect_schema(connection)
    if actual != expected:
        actual_names = {(obj.kind, obj.name) for obj in actual.objects}
        expected_names = {(obj.kind, obj.name) for obj in expected.objects}
        if actual_names != expected_names:
            raise SchemaMismatch('Final schema object membership differs')
        raise SchemaMismatch('Final schema definition or PRAGMA structure differs')


def verify_integrity(connection: sqlite3.Connection) -> None:
    require_snapshot(connection)
    rows = connection.execute('PRAGMA main.integrity_check').fetchall()
    if len(rows) != 1 or tuple(rows[0]) != ('ok',):
        raise SchemaMismatch('SQLite integrity check failed; preserve database')
    if connection.execute('PRAGMA main.foreign_key_check').fetchone() is not None:
        raise SchemaMismatch('SQLite foreign key check failed; preserve database')
