"""Build and load the V2.2 FRESH_ONLY extension of Schema200."""

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from .database import SchemaMismatch, _statements
from .schema_inspection import inspect_schema, verify_integrity
from .schema_v20_assembly import fresh_sql as base_fresh_sql
from .schema_v20_release import (
    DESIGN_SOURCE,
    RELEASE_PARENT,
    ROOT,
    SOURCE_NAMES,
    SchemaRelease,
    _read,
    _snapshot,
    canonical_bytes,
    digest,
)
from .schema_v22_ddl import fresh_sql

ENVIRONMENT_DESIGN = 'docs/iterations/pending/v2.01/WALL-E.环境分离后端迭代设计_V_2.01.md'
V22_SOURCES = (
    'backend/app/guide/collaboration_results.py',
    'backend/app/guide/commands.py',
    'backend/app/guide/orchestrator.py',
    'backend/app/guide/response_display.py',
    'backend/app/guide/result_persistence.py',
    'backend/app/guide/trusted_output.py',
    'backend/app/guide/worker.py',
    'backend/app/infrastructure/counting_journal.py',
    'backend/app/infrastructure/environment_admission.py',
    'backend/app/infrastructure/environment_http.py',
    'backend/app/infrastructure/environment_ordinary.py',
    'backend/app/infrastructure/execution_lease.py',
    'tools/linux_runtime/serve_environment.py',
    'backend/app/infrastructure/environment_binding.py',
    'backend/app/infrastructure/environment_command.py',
    'backend/app/infrastructure/environment_control.py',
    'backend/app/infrastructure/environment_files.py',
    'backend/app/infrastructure/environment_initialize.py',
    'backend/app/infrastructure/environment_installation.py',
    'backend/app/infrastructure/environment_lock.py',
    'backend/app/infrastructure/environment_provision.py',
    'backend/app/infrastructure/schema_v22_ddl.py',
    'backend/app/infrastructure/schema_v22_release.py',
    'backend/app/infrastructure/schema_v22_publish.py',
    'tools/linux_runtime/build-cpython.sh',
    'tools/linux_runtime/environment_lock.c',
    'tools/linux_runtime/environment_gateway.py',
    'tools/linux_runtime/prepare_wheels.py',
    'tools/linux_runtime/runtime.py',
    'tools/linux_runtime/seal_runtime.py',
)
MANIFEST = 'manifest.v2.json'
OBJECTS = 'objects.v1.json'
FRESH_SQL = 'fresh.v1.sql'
# The V2.2 structural delta is relative to this immutable release.
# The Windows Schema200 startup pin can advance independently.
BASE_RELEASE_DIRECTORY = 'db20-r50'
BASE_MANIFEST_SHA256 = '10ff02e670eb705e6ac537eb9335449a72de9dbc93eeffbe46b16d7d74557f31'
NEW_OBJECTS = {('table', 'environment_binding'), ('trigger', 'code_snapshots_origin_guard_insert')}
UPDATED_OBJECTS = {('table', 'code_snapshots'), ('trigger', 'code_snapshots_identity_fixed')}


@dataclass(frozen=True)
class FreshSchemaRelease(SchemaRelease):
    upgrade: None

    @property
    def upgrade_checksum(self) -> str:
        raise SchemaMismatch('SCHEMA_UPGRADE_NOT_ADMITTED')


def _source_hashes(source_root):
    return {source: digest(_read(source_root / source)) for source in (*SOURCE_NAMES, *V22_SOURCES)}


def _design_hashes(source_root):
    return [
        {'path': source, 'sha256': digest(_read(source_root / source))}
        for source in (DESIGN_SOURCE, ENVIRONMENT_DESIGN)
    ]


def _bound_fields(release_id, runtime_sha256, source_root=ROOT):
    if (
        type(release_id) is not str
        or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', release_id) is None
        or type(runtime_sha256) is not str
        or re.fullmatch(r'[a-f0-9]{64}', runtime_sha256) is None
    ):
        raise SchemaMismatch('SCHEMA_RELEASE_MISMATCH')
    return {
        'format_version': 2,
        'target_version': '2.2',
        'schema_version': 200,
        'release_id': release_id,
        'initialization_mode': 'FRESH_ONLY',
        'runtime_manifest_sha256': runtime_sha256,
        'expected_objects_ref': OBJECTS,
        'fresh_sql_ref': FRESH_SQL,
        'upgrade_sql_ref': None,
        'sources': _source_hashes(source_root),
        'design_sources': _design_hashes(source_root),
        'base_release': {
            'release_id': BASE_RELEASE_DIRECTORY,
            'manifest_sha256': BASE_MANIFEST_SHA256,
        },
    }


def _facts(resources):
    return {name: {'sha256': digest(data), 'bytes': len(data)} for name, data in resources.items()}


def _base_schema(source_root=ROOT):
    directory = source_root / RELEASE_PARENT.relative_to(ROOT) / BASE_RELEASE_DIRECTORY
    raw = _read(directory / 'manifest.json')
    if digest(raw) != BASE_MANIFEST_SHA256:
        raise SchemaMismatch('Unexpected original Schema200 release')
    base = json.loads(raw)
    objects = _read(directory / OBJECTS)
    frozen_fresh = _read(directory / FRESH_SQL)
    if _facts({OBJECTS: objects, FRESH_SQL: frozen_fresh}) != {
        name: base['resources'][name] for name in (OBJECTS, FRESH_SQL)
    } or frozen_fresh != base_fresh_sql().encode('utf-8'):
        raise SchemaMismatch('Original Schema200 SQL or object bytes differ')
    return _snapshot(json.loads(objects))


def _check_delta(base, updated):
    original = {(item.kind, item.name): item for item in base.objects}
    current = {(item.kind, item.name): item for item in updated.objects}
    if (
        len(base.tables) != 72
        or len(updated.tables) != 73
        or len(original) != 299
        or len(current) != 301
        or current.keys() - original.keys() != NEW_OBJECTS
        or original.keys() - current.keys()
        or {key for key in original if original[key] != current[key]} != UPDATED_OBJECTS
    ):
        raise SchemaMismatch('Unexpected V2.2 object delta')

    original_tables = {item.name: item for item in base.tables}
    current_tables = {item.name: item for item in updated.tables}
    binding = current_tables['environment_binding']
    if (
        current_tables.keys() - original_tables.keys() != {'environment_binding'}
        or original_tables.keys() - current_tables.keys()
        or {key for key in original_tables if original_tables[key] != current_tables[key]}
        != {'code_snapshots'}
        or not binding.strict
        or not binding.without_rowid
    ):
        raise SchemaMismatch('Unexpected V2.2 table structure delta')


def _construct(sql):
    connection = sqlite3.connect(':memory:', isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        for statement in _statements(sql):
            connection.execute(statement)
        verify_integrity(connection)
        return inspect_schema(connection)
    finally:
        connection.close()


def build_candidate(release_id, runtime_sha256):
    """Construct and inspect the full fresh SQL with the caller's admitted SQLite."""
    manifest = _bound_fields(release_id, runtime_sha256)
    base = _base_schema()
    sql = fresh_sql()
    snapshot = _construct(sql)
    _check_delta(base, snapshot)
    if manifest != _bound_fields(release_id, runtime_sha256):
        raise SchemaMismatch('Schema source inputs changed during construction')
    resources = {OBJECTS: canonical_bytes(asdict(snapshot)), FRESH_SQL: sql.encode('utf-8')}
    manifest['schema_contract_sha256'] = digest(resources[OBJECTS])
    manifest['resources'] = _facts(resources)
    return {**resources, MANIFEST: canonical_bytes(manifest)}


def load_release(
    directory: Path, expected_digest: str, runtime_sha256: str, *, source_root: Path = ROOT
) -> FreshSchemaRelease:
    """Verify the pinned V2.2 schema against the admitted program's source bytes."""
    if any(
        path.is_symlink() or path.resolve(strict=True) != path for path in (directory, source_root)
    ):
        raise SchemaMismatch('SCHEMA_RELEASE_MISMATCH')
    path = directory / MANIFEST
    raw = _read(path)
    if digest(raw) != expected_digest:
        raise SchemaMismatch('SCHEMA_RELEASE_MISMATCH')
    bound = _bound_fields(directory.name, runtime_sha256, source_root)
    resources = {name: _read(directory / name) for name in (OBJECTS, FRESH_SQL)}
    contract = digest(resources[OBJECTS])
    expected_bytes = canonical_bytes(
        {**bound, 'schema_contract_sha256': contract, 'resources': _facts(resources)}
    )
    if raw != expected_bytes:
        raise SchemaMismatch('SCHEMA_RELEASE_MISMATCH')
    snapshot = _snapshot(json.loads(resources[OBJECTS]))
    _check_delta(_base_schema(source_root), snapshot)
    return FreshSchemaRelease(
        directory.name,
        contract,
        snapshot,
        resources[FRESH_SQL].decode('utf-8'),
        None,
        expected_digest,
    )
