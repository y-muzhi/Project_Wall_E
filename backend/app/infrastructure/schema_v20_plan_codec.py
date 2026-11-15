"""Strict versioned maintenance metadata, never an arbitrary object/SQL decoder."""

from dataclasses import asdict, dataclass
import hashlib
import re
import sqlite3

from backend.app.documents.snapshot import _time
from backend.app.shared.validation import MAX_SAFE_INTEGER
from .database import Migration, _statements
from .data_retention import (
    ENCODING,
    RetentionManifest,
    TableDigest,
    TableProjection,
    original_projections,
    _part,
)
from .idempotency import request_key
from .schema_v20_assets import (
    AuditFile,
    AuditSnapshot,
    SpaceObservation,
    MaintenancePreparationError,
)
from .schema_v20_references import RegisteredReference
from .windows_local_paths import FileIdentity, local_absolute_path


def _invalid():
    raise MaintenancePreparationError('MAINTENANCE_PLAN_INVALID')


def _object(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        _invalid()
    return value


def _array(value):
    if type(value) is not list:
        _invalid()
    return value


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        _invalid()
    return value


def _hex(value, length=64):
    if type(value) is not str or re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is None:
        _invalid()
    return value


def _path(value):
    if type(value) is not str or str(local_absolute_path(value)) != value:
        _invalid()
    return value


def _identity(value, *, directory):
    row = _object(
        value, ('canonical_path', 'volume_serial', 'file_id', 'is_directory', 'filesystem')
    )
    if (
        type(row['is_directory']) is not bool
        or row['is_directory'] is not directory
        or row['filesystem'] != 'NTFS'
    ):
        _invalid()
    return FileIdentity(
        _path(row['canonical_path']),
        _hex(row['volume_serial'], 16),
        _hex(row['file_id'], 32),
        directory,
        'NTFS',
    )


def _retained(value):
    row = _object(value, ('tables', 'sha256', 'encoding'))
    if row['encoding'] != ENCODING:
        _invalid()
    # The complete original projection comes from the immutable 151 DDL, not plan input.
    connection = sqlite3.connect(':memory:', isolation_level=None)
    try:
        connection.execute('BEGIN')
        for statement in _statements(Migration().sql):
            connection.execute(statement)
        expected = original_projections(connection)
    finally:
        connection.close()
    tables = []
    for item in _array(row['tables']):
        table = _object(item, ('projection', 'row_count', 'sha256'))
        projection = _object(
            table['projection'], ('table', 'columns', 'key_columns', 'migration_ceiling')
        )
        if type(projection['table']) is not str:
            _invalid()
        columns = _array(projection['columns'])
        keys = _array(projection['key_columns'])
        if any(type(name) is not str for name in (*columns, *keys)):
            _invalid()
        ceiling = projection['migration_ceiling']
        if ceiling is not None and (type(ceiling) is not int or ceiling != 151):
            _invalid()
        parsed = TableProjection(projection['table'], tuple(columns), tuple(keys), ceiling)
        tables.append(TableDigest(parsed, _integer(table['row_count']), _hex(table['sha256'])))
    if tuple(table.projection for table in tables) != expected:
        _invalid()
    complete = hashlib.sha256(ENCODING.encode('ascii'))
    for table in tables:
        _part(complete, table.projection.table.encode('utf-8'))
        _part(complete, bytes.fromhex(table.sha256))
    if _hex(row['sha256']) != complete.hexdigest():
        _invalid()
    return RetentionManifest(tuple(tables), row['sha256'])


def _audit(value):
    row = _object(value, ('root_path', 'state', 'root_identity', 'files'))
    root = _path(row['root_path'])
    native = (
        None if row['root_identity'] is None else _identity(row['root_identity'], directory=True)
    )
    files = []
    for value in _array(row['files']):
        file = _object(value, ('name', 'byte_count', 'sha256', 'identity'))
        native_file = _identity(file['identity'], directory=False)
        if type(file['name']) is not str or native_file.canonical_path != str(
            local_absolute_path(root) / file['name']
        ):
            _invalid()
        files.append(
            AuditFile(file['name'], _integer(file['byte_count']), _hex(file['sha256']), native_file)
        )
    if [file.name for file in files] != sorted(
        (file.name for file in files), key=lambda name: name.encode('utf-8')
    ):
        _invalid()
    if native is not None and native.canonical_path != root:
        _invalid()
    return AuditSnapshot(root, row['state'], native, tuple(files))


def _references(value):
    references = []
    for item in _array(value):
        row = _object(item, ('kind', 'path', 'identity', 'sha256', 'byte_count', 'llm_use_id'))
        native = _identity(row['identity'], directory=False)
        path = _path(row['path'])
        if native.canonical_path != path:
            _invalid()
        if row['kind'] == 'CONFIG_FILE':
            size = _integer(row['byte_count'])
            if row['llm_use_id'] is not None:
                _invalid()
            use = None
        elif row['kind'] in ('INTERNAL_CALL', 'DOCUMENT_CALL'):
            use = _integer(row['llm_use_id'], 1)
            if row['byte_count'] is not None:
                _invalid()
            size = None
        else:
            _invalid()
        references.append(
            RegisteredReference(row['kind'], path, native, _hex(row['sha256']), size, use)
        )
    keys = [(ref.kind, ref.path, ref.llm_use_id or 0) for ref in references]
    if keys != sorted(set(keys)):
        _invalid()
    return tuple(references)


@dataclass(frozen=True)
class BackupFact:
    identity: FileIdentity
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class MaintenancePlan:
    schema_version: int
    upgrade_id: str
    created_at: str
    source_identity: FileIdentity
    package_identity: FileIdentity
    operator_sid: str
    release_id: str
    release_manifest_sha256: str
    schema_contract_sha256: str
    program_sha256: str
    retained: RetentionManifest
    audit: AuditSnapshot
    backup: BackupFact
    references: tuple[RegisteredReference, ...]
    space: SpaceObservation


def decode_plan(value):
    keys = tuple(MaintenancePlan.__dataclass_fields__)
    row = _object(value, keys)
    if type(row['schema_version']) is not int or row['schema_version'] != 1:
        _invalid()
    if type(row['upgrade_id']) is not str or request_key(row['upgrade_id']) != row['upgrade_id']:
        _invalid()
    _time(row['created_at'])
    source = _identity(row['source_identity'], directory=False)
    package = _identity(row['package_identity'], directory=True)
    if (
        type(row['operator_sid']) is not str
        or re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+)+', row['operator_sid']) is None
    ):
        _invalid()
    if (
        type(row['release_id']) is not str
        or re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', row['release_id']) is None
    ):
        _invalid()
    backup_row = _object(row['backup'], ('identity', 'byte_count', 'sha256'))
    backup = BackupFact(
        _identity(backup_row['identity'], directory=False),
        _integer(backup_row['byte_count'], 1),
        _hex(backup_row['sha256']),
    )
    if backup.identity.canonical_path != str(
        local_absolute_path(package.canonical_path) / 'source-backup.sqlite'
    ):
        _invalid()
    space_row = _object(row['space'], tuple(SpaceObservation.__dataclass_fields__))
    for key, number in space_row.items():
        if key == 'shared_volume':
            if type(number) is not bool:
                _invalid()
        else:
            _integer(number)
    retained = _retained(row['retained'])
    audit = _audit(row['audit'])
    references = _references(row['references'])
    if audit.root_path != source.canonical_path + '.count-audit':
        _invalid()
    for ref in references:
        if (ref.kind == 'INTERNAL_CALL') != (ref.identity == source) and ref.kind != 'CONFIG_FILE':
            _invalid()
        if ref.kind == 'CONFIG_FILE' and ref.identity == source:
            _invalid()
    plan = MaintenancePlan(
        1,
        row['upgrade_id'],
        row['created_at'],
        source,
        package,
        row['operator_sid'],
        row['release_id'],
        _hex(row['release_manifest_sha256']),
        _hex(row['schema_contract_sha256']),
        _hex(row['program_sha256']),
        retained,
        audit,
        backup,
        references,
        SpaceObservation(**space_row),
    )
    # Avoid a decoder silently changing any signed/canonical input representation.
    from .schema_v20_release import canonical_bytes

    if canonical_bytes(asdict(plan)) != canonical_bytes(value):
        _invalid()
    return plan
