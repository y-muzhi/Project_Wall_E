"""Pinned Schema200 resources and explicit construction of release candidates.

No function here opens a caller's database, executes arbitrary supplied SQL or
changes the application's current schema. Normal use loads the compiled pin.
"""

from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
from pathlib import Path
import re
import sqlite3

from .database import Migration, SchemaMismatch, _statements
from .schema_inspection import (
    SchemaObject,
    SchemaSnapshot,
    TableStructure,
    inspect_schema,
    verify_integrity,
)
from .schema_v20_assembly import fresh_sql, upgrade_sql
from .schema_v20_columns import DESIGN_SHA256
from .sqlite_runtime import require_active, DLL_SHA256, VERSION, SOURCE_ID

ROOT = Path(__file__).resolve().parents[3]
DESIGN_SOURCE = 'docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md'
RELEASE_PARENT = Path(__file__).with_name('schemas') / 'v2_0'
RESOURCE_NAMES = (
    'objects.v1.json',
    'fresh.v1.sql',
    'upgrade-151.v1.sql',
)
SOURCE_NAMES = (
    'backend/app/infrastructure/database.py',
    'backend/app/service.py',
    'backend/app/__main__.py',
    'tools/ai-service.py',
    'backend/app/infrastructure/transaction_savepoint.py',
    'backend/app/infrastructure/idempotency.py',
    'backend/app/infrastructure/command_receipts.py',
    'backend/app/shared/code_errors.py',
    'backend/app/infrastructure/schemas/v1_5.sql',
    'backend/app/infrastructure/schema_inspection.py',
    'backend/app/infrastructure/schema_v20_columns.py',
    'backend/app/infrastructure/schema_v20.py',
    'backend/app/infrastructure/schema_v20_legacy.py',
    'backend/app/infrastructure/schema_v20_relations.py',
    'backend/app/infrastructure/schema_v20_triggers.py',
    'backend/app/infrastructure/schema_v20_assembly.py',
    'backend/app/infrastructure/schema_v20_release.py',
    'backend/app/infrastructure/schema_v20_state.py',
    'backend/app/infrastructure/schema_v20_upgrade.py',
    'backend/app/infrastructure/schema_v20_assets.py',
    'backend/app/infrastructure/data_retention.py',
    'backend/app/infrastructure/process_lock.py',
    'backend/app/infrastructure/schema_v20_plan_codec.py',
    'backend/app/infrastructure/schema_v20_plan.py',
    'backend/app/infrastructure/schema_v20_maintenance.py',
    'backend/app/infrastructure/schema_v20_cli.py',
    'backend/app/infrastructure/schema_v20_publish.py',
    'tools/schema-v20-release.py',
    'tools/python-v20.py',
    'tools/db-v20.py',
    'backend/app/infrastructure/schema_v20_records.py',
    'backend/app/infrastructure/schema_v20_references.py',
    'backend/app/infrastructure/collaboration_admission.py',
    'backend/app/infrastructure/windows_local_paths.py',
    'backend/app/infrastructure/windows_private_package.py',
    'backend/app/infrastructure/sqlite_runtime.py',
    'backend/app/code_tasks/command_registry.py',
    'backend/app/code_tasks/operation_protocol.py',
    'backend/app/code_tasks/error_codes.py',
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
        )
        + '\n'
    ).encode('utf-8')


def _freeze(value: object):
    if type(value) is list:
        return tuple(_freeze(part) for part in value)
    if value is None or type(value) in (str, int):
        return value
    raise SchemaMismatch('Invalid released SQLite structure value')


def _snapshot(value: object) -> SchemaSnapshot:
    if type(value) is not dict or set(value) != {'objects', 'tables'}:
        raise SchemaMismatch('Invalid released final object structure')
    if type(value['objects']) is not list or type(value['tables']) is not list:
        raise SchemaMismatch('Released schema collections must be arrays')
    objects = []
    for row in value['objects']:
        if type(row) is not dict or set(row) != {'kind', 'name', 'table', 'definition'}:
            raise SchemaMismatch('Invalid released schema object')
        if any(type(row[key]) is not str or not row[key] for key in ('kind', 'name', 'table')):
            raise SchemaMismatch('Invalid released object identity')
        if (
            row['kind'] not in ('table', 'index', 'trigger', 'view')
            or type(row['definition']) is not list
        ):
            raise SchemaMismatch('Invalid released object definition')
        if any(type(token) is not str for token in row['definition']):
            raise SchemaMismatch('Invalid released SQL tokens')
        objects.append(
            SchemaObject(row['kind'], row['name'], row['table'], tuple(row['definition']))
        )
    tables = []
    fields = {
        'name',
        'columns',
        'foreign_keys',
        'indexes',
        'index_columns',
        'without_rowid',
        'strict',
    }
    for row in value['tables']:
        if type(row) is not dict or set(row) != fields or type(row['name']) is not str:
            raise SchemaMismatch('Invalid released table structure')
        if any(
            type(row[key]) is not int or row[key] not in (0, 1)
            for key in ('without_rowid', 'strict')
        ):
            raise SchemaMismatch('Invalid released table flags')
        arrays = tuple(
            _freeze(row[key]) for key in ('columns', 'foreign_keys', 'indexes', 'index_columns')
        )
        if any(type(array) is not tuple for array in arrays):
            raise SchemaMismatch('Invalid released PRAGMA structure')
        tables.append(TableStructure(row['name'], *arrays, row['without_rowid'], row['strict']))
    if not objects or not tables or len({(obj.kind, obj.name) for obj in objects}) != len(objects):
        raise SchemaMismatch('Empty or duplicate released schema objects')
    return SchemaSnapshot(tuple(objects), tuple(tables))


@dataclass(frozen=True)
class SchemaRelease:
    release_id: str
    schema_contract_sha256: str
    expected_schema: SchemaSnapshot
    fresh: str
    upgrade: str
    manifest_sha256: str

    @property
    def fresh_checksum(self) -> str:
        return digest(self.fresh.encode('utf-8'))

    @property
    def upgrade_checksum(self) -> str:
        return digest(self.upgrade.encode('utf-8'))


def _read(path: Path, maximum: int = 4 * 1024 * 1024) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise SchemaMismatch('Released schema resource is unavailable')
    return path.read_bytes()


def _load_verified_release(directory: Path, manifest_sha256: str) -> SchemaRelease:
    require_active()
    raw = _read(directory / 'manifest.json')
    if digest(raw) != manifest_sha256:
        raise SchemaMismatch('Schema release manifest differs from the compiled pin')
    manifest = json.loads(raw.decode('utf-8'))
    required = {
        'release_id',
        'schema_version',
        'schema_contract_sha256',
        'expected_objects_ref',
        'fresh_sql_ref',
        'upgrade_sql_ref',
        'resources',
        'sources',
        'sqlite_runtime',
        'design_source',
    }
    if type(manifest) is not dict or set(manifest) != required or manifest['schema_version'] != 200:
        raise SchemaMismatch('Unsupported schema release manifest')
    if manifest['design_source'] != {'path': DESIGN_SOURCE, 'sha256': DESIGN_SHA256}:
        raise SchemaMismatch('Schema release reviewed design differs')
    if manifest['sqlite_runtime'] != {
        'version': VERSION,
        'dll_sha256': DLL_SHA256,
        'source_id': SOURCE_ID,
    }:
        raise SchemaMismatch('Schema release SQLite build differs')
    if (
        manifest['expected_objects_ref'] != RESOURCE_NAMES[0]
        or manifest['fresh_sql_ref'] != RESOURCE_NAMES[1]
        or manifest['upgrade_sql_ref'] != RESOURCE_NAMES[2]
        or set(manifest['resources']) != set(RESOURCE_NAMES)
        or set(manifest['sources']) != set(SOURCE_NAMES)
    ):
        raise SchemaMismatch('Schema release references differ from the registered resources')
    for source in SOURCE_NAMES:
        if digest(_read(ROOT / source)) != manifest['sources'][source]:
            raise SchemaMismatch(
                'Schema construction sources changed; prepare a new reviewed release'
            )
    data = {}
    for name in RESOURCE_NAMES:
        content = _read(directory / name)
        fact = manifest['resources'][name]
        if type(fact) is not dict or set(fact) != {'sha256', 'bytes'}:
            raise SchemaMismatch('Invalid schema resource digest')
        if (
            fact['sha256'] != digest(content)
            or type(fact['bytes']) is not int
            or fact['bytes'] != len(content)
        ):
            raise SchemaMismatch('Schema release resource bytes differ')
        data[name] = content
    if digest(data[RESOURCE_NAMES[0]]) != manifest['schema_contract_sha256']:
        raise SchemaMismatch('Schema final object contract differs')
    expected = _snapshot(json.loads(data[RESOURCE_NAMES[0]].decode('utf-8')))
    return SchemaRelease(
        manifest['release_id'],
        manifest['schema_contract_sha256'],
        expected,
        data[RESOURCE_NAMES[1]].decode('utf-8'),
        data[RESOURCE_NAMES[2]].decode('utf-8'),
        manifest_sha256,
    )


def load_release() -> SchemaRelease:
    try:
        pin = importlib.import_module('backend.app.infrastructure.schema_v20_admission')
    except ModuleNotFoundError as error:
        raise SchemaMismatch('No Schema200 release has been prepared') from error
    name = pin.RELEASE_DIRECTORY
    if type(name) is not str or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name) is None:
        raise SchemaMismatch('Invalid compiled schema release identity')
    release = _load_verified_release(RELEASE_PARENT / name, pin.MANIFEST_SHA256)
    if release.release_id != name:
        raise SchemaMismatch('Compiled directory and schema release identity differ')
    return release


def build_candidate(release_id: str) -> dict[str, bytes]:
    """Return real SQL/objects after fixed-runtime fresh/rebuild equivalence."""
    require_active()
    if re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', release_id) is None:
        raise ValueError('A bounded release identity is required')
    if digest(_read(ROOT / DESIGN_SOURCE, 4 * 1024 * 1024)) != DESIGN_SHA256:
        raise SchemaMismatch(
            'Reviewed design changed; update implementation mapping before release'
        )
    source_hashes = {name: digest(_read(ROOT / name)) for name in SOURCE_NAMES}
    fresh = fresh_sql()
    upgrade = upgrade_sql()
    snapshots = []
    for is_upgrade, sql in ((False, fresh), (True, upgrade)):
        connection = sqlite3.connect(':memory:', isolation_level=None)
        try:
            connection.execute('BEGIN IMMEDIATE')
            if is_upgrade:
                for statement in _statements(Migration().sql):
                    connection.execute(statement)
            for statement in _statements(sql):
                connection.execute(statement)
            verify_integrity(connection)
            snapshots.append(inspect_schema(connection))
        finally:
            connection.close()
    if snapshots[0] != snapshots[1]:
        raise SchemaMismatch('Fresh and rebuilt final schemas differ')
    files = {
        RESOURCE_NAMES[0]: canonical_bytes(asdict(snapshots[0])),
        RESOURCE_NAMES[1]: fresh.encode('utf-8'),
        RESOURCE_NAMES[2]: upgrade.encode('utf-8'),
    }
    if source_hashes != {name: digest(_read(ROOT / name)) for name in SOURCE_NAMES}:
        raise SchemaMismatch('Schema construction sources changed during the build')
    manifest = {
        'design_source': {'path': DESIGN_SOURCE, 'sha256': DESIGN_SHA256},
        'release_id': release_id,
        'schema_version': 200,
        'schema_contract_sha256': digest(files[RESOURCE_NAMES[0]]),
        'expected_objects_ref': RESOURCE_NAMES[0],
        'fresh_sql_ref': RESOURCE_NAMES[1],
        'upgrade_sql_ref': RESOURCE_NAMES[2],
        'resources': {
            name: {'sha256': digest(content), 'bytes': len(content)}
            for name, content in files.items()
        },
        'sources': source_hashes,
        'sqlite_runtime': {'version': VERSION, 'dll_sha256': DLL_SHA256, 'source_id': SOURCE_ID},
    }
    files['manifest.json'] = canonical_bytes(manifest)
    return files
