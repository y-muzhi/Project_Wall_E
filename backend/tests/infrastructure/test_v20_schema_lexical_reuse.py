"""Pure lexical reuse must never become a cached database/schema admission."""

import sqlite3
from contextlib import closing

import pytest

from backend.app.infrastructure import schema_inspection as schema
from backend.app.infrastructure.database import SchemaMismatch
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.mark.parametrize('sql', ["'unfinished", '/* unfinished', '"unfinished'])
def test_malformed_sql_is_rejected_after_repeated_lexical_attempts(sql):
    before = schema._cached_sql_tokens.cache_info().currsize
    for _ in range(2):
        with pytest.raises(SchemaMismatch):
            schema.sql_tokens(sql)
    assert schema._cached_sql_tokens.cache_info().currsize == before


def test_literal_boundaries_remain_distinct_after_warm_reuse():
    for first, second in [
        ("DEFAULT 'one two'", "DEFAULT 'one  two'"),
        ('id>=1', 'id> =1'),
        ("'a''b'", "'ab'"),
        ('1.0', '1 . 0'),
    ]:
        baseline = schema.sql_tokens(first)
        assert schema.sql_tokens(first) is baseline
        assert baseline != schema.sql_tokens(second)


def test_long_source_is_not_resident_and_entry_count_remains_bounded():
    schema._cached_sql_tokens.cache_clear()
    long = "SELECT '" + 'a' * 8192 + "'"
    original = schema.sql_tokens(long)
    assert schema.sql_tokens(long) == original
    assert schema._cached_sql_tokens.cache_info().currsize == 0
    for index in range(600):
        schema.sql_tokens(f'SELECT {index}')
    assert schema._cached_sql_tokens.cache_info().currsize == 512


def test_warm_tokens_still_read_actual_schema_after_other_connection_changes(tmp_path):
    path = tmp_path / 'schema.sqlite'
    with (
        closing(sqlite3.connect(path, isolation_level=None)) as first,
        closing(sqlite3.connect(path, isolation_level=None)) as second,
    ):
        first.execute('CREATE TABLE t(id INTEGER PRIMARY KEY, value TEXT)')
        first.execute('CREATE INDEX filtered ON t(value) WHERE id>0')
        first.execute('BEGIN')
        expected = schema.inspect_schema(first)
        schema.verify_schema(first, expected)
        first.commit()
        second.execute('DROP INDEX filtered')
        second.execute('CREATE INDEX filtered ON t(value) WHERE id>=0')
        first.execute('BEGIN')
        with pytest.raises(SchemaMismatch, match='definition'):
            schema.verify_schema(first, expected)
        first.rollback()
        second.execute('CREATE VIEW extra AS SELECT id FROM t')
        first.execute('BEGIN')
        with pytest.raises(SchemaMismatch, match='membership'):
            schema.verify_schema(first, expected)
        first.rollback()
    # Identical database paths/names are never a cache key for schema admission.
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as unrelated:
        unrelated.execute('CREATE TABLE t(id INTEGER PRIMARY KEY, value BLOB)')
        unrelated.execute('CREATE INDEX filtered ON t(value) WHERE id>0')
        unrelated.execute('BEGIN')
        with pytest.raises(SchemaMismatch, match='definition'):
            schema.verify_schema(unrelated, expected)
