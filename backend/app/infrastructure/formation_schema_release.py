"""Pinned Schema210 candidate construction and byte-verified loading."""

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from .database import SchemaMismatch, _statements
from .formation_schema import extension_sql
from .schema_inspection import inspect_schema, verify_integrity
from .schema_v20_release import (
    ROOT,
    SchemaRelease,
    _read,
    _snapshot,
    canonical_bytes,
    digest,
)
from .schema_v20_release import (
    load_release as load_core,
)
from .sqlite_runtime import DLL_SHA256, SOURCE_ID, VERSION, require_active

RELEASE_PARENT = Path(__file__).with_name('schemas') / 'v2_1'
DESIGN_SOURCE = 'docs/iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md'
DESIGN_SHA256 = '4049f8d3b5d01bd704dd0439b8c0730155cec813f3f5ef8ef7ad8c5ba5b5b197'
RESOURCE_NAMES = ('objects.v1.json', 'fresh.v1.sql', 'upgrade-200.v1.sql')
SOURCE_NAMES = (
    'backend/app/infrastructure/formation_schema.py',
    'backend/app/infrastructure/formation_schema_release.py',
    'backend/app/infrastructure/formation_database.py',
    'backend/app/infrastructure/formation_schema_publish.py',
    'tools/schema-v21-release.py',
    'backend/app/infrastructure/formation_upgrade_source.py',
    'backend/app/infrastructure/formation_upgrade.py',
    'backend/app/infrastructure/formation_upgrade_cli.py',
    'tools/db-v21.py',
)
RUNTIME_FACT = {'version': VERSION, 'source_id': SOURCE_ID, 'dll_sha256': DLL_SHA256}


@dataclass(frozen=True)
class FormationRelease:
    release_id: str
    schema_contract_sha256: str
    expected_schema: object
    fresh: str
    upgrade: str
    manifest_sha256: str
    core: SchemaRelease

    @property
    def fresh_checksum(self):
        return digest(self.fresh.encode('utf-8'))

    @property
    def upgrade_checksum(self):
        return digest(self.upgrade.encode('utf-8'))


def core_fact(core):
    return {
        'release_id': core.release_id,
        'manifest_sha256': core.manifest_sha256,
        'schema_contract_sha256': core.schema_contract_sha256,
        'fresh_checksum': core.fresh_checksum,
        'upgrade_checksum': core.upgrade_checksum,
    }


def source_hashes():
    return {name: digest(_read(ROOT / name)) for name in SOURCE_NAMES}


def build_candidate(release_id):
    require_active()
    if type(release_id) is not str or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', release_id) is None:
        raise ValueError('A bounded release identity is required')
    core = load_core()
    before = source_hashes()
    if digest(_read(ROOT / DESIGN_SOURCE)) != DESIGN_SHA256:
        raise SchemaMismatch('Reviewed formation design changed; update mapping before publication')
    extension = extension_sql()
    fresh = core.fresh + '\n' + extension
    snapshots = []
    for parts in ((fresh,), (core.fresh, extension)):
        connection = sqlite3.connect(':memory:', isolation_level=None)
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('BEGIN IMMEDIATE')
            for sql in parts:
                for statement in _statements(sql):
                    connection.execute(statement)
            verify_integrity(connection)
            snapshots.append(inspect_schema(connection))
        finally:
            connection.close()
    if snapshots[0] != snapshots[1]:
        raise SchemaMismatch('Schema210 fresh and source-extension structures differ')
    files = {
        'objects.v1.json': canonical_bytes(asdict(snapshots[0])),
        'fresh.v1.sql': fresh.encode('utf-8'),
        'upgrade-200.v1.sql': extension.encode('utf-8'),
    }
    if before != source_hashes():
        raise SchemaMismatch('Schema210 sources changed during construction')
    manifest = {
        'release_id': release_id,
        'schema_version': 210,
        'schema_contract_sha256': digest(files['objects.v1.json']),
        'design_source': {'path': DESIGN_SOURCE, 'sha256': DESIGN_SHA256},
        'core': core_fact(core),
        'sqlite_runtime': RUNTIME_FACT,
        'sources': before,
        'resources': {
            name: {'bytes': len(data), 'sha256': digest(data)} for name, data in files.items()
        },
    }
    files['manifest.json'] = canonical_bytes(manifest)
    return files


def load_verified(directory, manifest_sha256):
    require_active()
    directory = Path(directory)
    raw = _read(directory / 'manifest.json')
    if digest(raw) != manifest_sha256:
        raise SchemaMismatch('Schema210 manifest differs from its compiled pin')
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SchemaMismatch('Schema210 manifest is not valid JSON') from None
    fields = {
        'release_id',
        'schema_version',
        'schema_contract_sha256',
        'design_source',
        'core',
        'sqlite_runtime',
        'sources',
        'resources',
    }
    if (
        type(manifest) is not dict
        or set(manifest) != fields
        or type(manifest['schema_version']) is not int
        or manifest['schema_version'] != 210
    ):
        raise SchemaMismatch('Unsupported Schema210 release manifest')
    core = load_core()
    if manifest['core'] != core_fact(core) or manifest['sqlite_runtime'] != RUNTIME_FACT:
        raise SchemaMismatch('Schema210 source release or SQLite identity changed')
    if manifest['design_source'] != {'path': DESIGN_SOURCE, 'sha256': DESIGN_SHA256}:
        raise SchemaMismatch('Schema210 reviewed design identity differs')
    if manifest['sources'] != source_hashes() or set(manifest['resources']) != set(RESOURCE_NAMES):
        raise SchemaMismatch('Schema210 source or resource membership changed')
    files = {}
    for name in RESOURCE_NAMES:
        data = _read(directory / name)
        if manifest['resources'][name] != {'bytes': len(data), 'sha256': digest(data)}:
            raise SchemaMismatch('Schema210 resource bytes changed')
        files[name] = data
    if digest(files['objects.v1.json']) != manifest['schema_contract_sha256']:
        raise SchemaMismatch('Schema210 final contract identity differs')
    snapshot = _snapshot(json.loads(files['objects.v1.json']))
    return FormationRelease(
        manifest['release_id'],
        manifest['schema_contract_sha256'],
        snapshot,
        files['fresh.v1.sql'].decode('utf-8'),
        files['upgrade-200.v1.sql'].decode('utf-8'),
        manifest_sha256,
        core,
    )


def load_release():
    from .formation_schema_admission import MANIFEST_SHA256, RELEASE_DIRECTORY

    release = load_verified(RELEASE_PARENT / RELEASE_DIRECTORY, MANIFEST_SHA256)
    if release.release_id != RELEASE_DIRECTORY:
        raise SchemaMismatch('Schema210 directory and released identity differ')
    return release
