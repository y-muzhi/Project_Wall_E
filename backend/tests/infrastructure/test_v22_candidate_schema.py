"""Verify a fixed candidate's schema against its own indexed source package."""

from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
from uuid import uuid4

import pytest

from backend.app.infrastructure import schema_v22_release as schema
from backend.app.infrastructure.database import SchemaMismatch
from backend.app.infrastructure.environment_binding import (
    EnvironmentBinding,
    document_ai_source_facts,
    extend_document_ai_copy,
    verify_binding,
    verify_document_ai_copy,
    write_initial_schema,
)
from backend.app.shared.time import utc_milliseconds


def test_fixed_schema_binds_the_candidate_program_instead_of_manager_bytes(tmp_path):
    runtime_pin = '1' * 64
    release_name = 'candidate-schema-test'
    contents = schema.build_candidate(release_name, runtime_pin)
    manifest = json.loads(contents[schema.MANIFEST])
    root = tmp_path / 'fixed-program'
    base = manifest['base_release']
    assert base['release_id'] == 'db20-r50'
    base_release = schema.RELEASE_PARENT.relative_to(schema.ROOT) / base['release_id']
    base_manifest = (schema.ROOT / base_release / 'manifest.json').read_bytes()
    assert schema.digest(base_manifest) == base['manifest_sha256']
    paths = (
        *manifest['sources'],
        *(item['path'] for item in manifest['design_sources']),
        *(base_release / name for name in ('manifest.json', schema.FRESH_SQL, schema.OBJECTS)),
    )
    changed_source = 'backend/app/infrastructure/environment_installation.py'
    for path in paths:
        original = (schema.ROOT / path).read_bytes()
        if path == changed_source:
            original += b'\n# Fixed candidate source has separate program metadata.\n'
            manifest['sources'][path] = schema.digest(original)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)

    released = tmp_path / release_name
    released.mkdir()
    contents[schema.MANIFEST] = schema.canonical_bytes(manifest)
    for name, data in contents.items():
        (released / name).write_bytes(data)
    pin = schema.digest(contents[schema.MANIFEST])

    with pytest.raises(SchemaMismatch, match='SCHEMA_RELEASE_MISMATCH'):
        schema.load_release(released, pin, runtime_pin)
    loaded = schema.load_release(released, pin, runtime_pin, source_root=root)
    assert loaded.schema_contract_sha256 == manifest['schema_contract_sha256']
    assert loaded.manifest_sha256 == pin
    with pytest.raises(SchemaMismatch, match='SCHEMA_RELEASE_MISMATCH'):
        schema.load_release(released, pin, '2' * 64, source_root=root)


def test_document_ai_layout_preserves_original_rows_and_uses_a_distinct_generation(tmp_path):
    def release(name, *, document_ai=False):
        path = tmp_path / name
        path.mkdir()
        files = schema.build_candidate(name, '1' * 64, document_ai=document_ai)
        for member, raw in files.items():
            (path / member).write_bytes(raw)
        return schema.load_release(path, schema.digest(files[schema.MANIFEST]), '1' * 64)

    ordinary = release('manual-environment')
    target = release('document-ai-environment', document_ai=True)
    assert isinstance(target, schema.DocumentAiSchemaRelease)
    assert target.core_contract_sha256 == ordinary.schema_contract_sha256
    assert ordinary.schema_contract_sha256 != target.schema_contract_sha256
    assert len(target.expected_schema.objects) == len(ordinary.expected_schema.objects) + 74

    environment = str(uuid4())
    source = EnvironmentBinding(environment, str(uuid4()))
    replacement = EnvironmentBinding(environment, str(uuid4()))
    operation = str(uuid4())
    source_path = tmp_path / 'source.sqlite'
    target_path = tmp_path / 'target.sqlite'
    with (
        closing(sqlite3.connect(source_path, isolation_level=None)) as original,
        closing(sqlite3.connect(target_path, isolation_level=None)) as copied,
    ):
        original.execute('PRAGMA foreign_keys=ON')
        original.execute('PRAGMA journal_mode=WAL')
        original.execute('BEGIN IMMEDIATE')
        write_initial_schema(original, ordinary, source)
        original.execute("INSERT INTO sequences(entity_kind,last_value) VALUES ('requirement',17)")
        original.commit()
        original.backup(copied)
        copied.execute('PRAGMA foreign_keys=ON')

        copied.execute('BEGIN IMMEDIATE')
        at = utc_milliseconds(datetime.now(timezone.utc))
        with pytest.raises(SchemaMismatch, match='DOCUMENT_AI_CONVERSION_MISMATCH'):
            extend_document_ai_copy(copied, ordinary, target, source, source, operation, at)
        digest = extend_document_ai_copy(
            copied, ordinary, target, source, replacement, operation, at
        )
        assert len(digest) == 64
        copied.commit()

        original.execute('BEGIN')
        verify_binding(original, ordinary, source)
        source_facts, retained = document_ai_source_facts(original)
        assert source_facts.sha256 == digest
        copied.execute('BEGIN')
        verify_binding(copied, target, replacement)
        with pytest.raises(SchemaMismatch, match='ENVIRONMENT_BINDING_MISMATCH'):
            verify_binding(copied, target, source)
        versions = copied.execute('SELECT version FROM schema_migrations ORDER BY 1').fetchall()
        assert versions == [(200,), (210,)]
        assert copied.execute('SELECT last_value FROM sequences').fetchone() == (17,)
        source_fact = copied.execute(
            'SELECT upgrade_id,source_data_sha256 FROM formation_schema_state'
        ).fetchone()
        assert source_fact == (operation, digest)
        verify_document_ai_copy(copied, target, replacement, operation, source_facts, retained)
        copied.execute("UPDATE sequences SET last_value=18 WHERE entity_kind='requirement'")
        with pytest.raises(SchemaMismatch, match='DOCUMENT_AI_CONVERSION_CHANGED_SOURCE_ROWS'):
            verify_document_ai_copy(copied, target, replacement, operation, source_facts, retained)
        copied.rollback()

    with closing(sqlite3.connect(tmp_path / 'brand-new.sqlite', isolation_level=None)) as fresh:
        fresh.execute('PRAGMA foreign_keys=ON')
        fresh.execute('PRAGMA journal_mode=WAL')
        fresh.execute('BEGIN IMMEDIATE')
        write_initial_schema(fresh, target, replacement)
        verify_binding(fresh, target, replacement)
        assert fresh.execute('SELECT origin FROM formation_schema_state').fetchone() == (
            'FRESH_V21',
        )
