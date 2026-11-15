"""Only registered admission call references and explicitly declared config paths.

No credentials or file bodies are placed in metadata. External evidence stays
at its original absolute path and is never recursively copied into the package.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path

from backend.app.shared.validation import strict_integer, strict_json_object, object_fields
from backend.app.documents.snapshot import _time
from .collaboration_admission import evidence_database
from .data_retention import _part, _cell
from .schema_inspection import quote_identifier, verify_integrity
from .schema_v20_assets import capture_audit, _hash_file, MaintenancePreparationError
from .schema_v20_legacy import original_columns
from .schema_v20_release import canonical_bytes
from .windows_local_paths import FileIdentity, LocalPathGuard, local_absolute_path


@dataclass(frozen=True)
class RegisteredReference:
    kind: str
    path: str
    identity: FileIdentity
    sha256: str
    byte_count: int | None
    llm_use_id: int | None


def _document_call(session, path, identity):
    strict_integer(identity, 'llm_use_id')
    path = local_absolute_path(path)
    with LocalPathGuard(path, directory=False) as guard:
        native = guard.verify()
        internal = native == session.source_guard.identity
        digest = hashlib.sha256(b'DB20-DOCUMENT-CALL-1')
        with evidence_database(path, schema_release=session.release).transaction() as connection:
            verify_integrity(connection)
            columns = original_columns('llm_uses')
            fields = []
            for column in columns:
                name = quote_identifier(column)
                fields.extend(
                    (
                        f'typeof({name})',
                        f"CASE WHEN typeof({name}) IN ('integer','real') THEN {name} ELSE CAST({name} AS BLOB) END",
                    )
                )
            row = connection.execute(
                'SELECT '
                + ','.join(fields)
                + ' FROM llm_uses WHERE id=? AND guide_run_id IS NOT NULL',
                (identity,),
            ).fetchone()
            if row is None:
                raise MaintenancePreparationError('REGISTERED_DOCUMENT_EVIDENCE_UNAVAILABLE')
            for index, name in enumerate(columns):
                _part(digest, name.encode('utf-8'))
                _part(digest, _cell(row[index * 2], row[index * 2 + 1]))
            if not internal:
                history = [
                    tuple(item)
                    for item in connection.execute(
                        'SELECT version,checksum FROM schema_migrations ORDER BY version'
                    )
                ]
                _part(digest, canonical_bytes(history))
        guard.verify()
    return RegisteredReference(
        'INTERNAL_CALL' if internal else 'DOCUMENT_CALL',
        native.canonical_path,
        native,
        digest.hexdigest(),
        None,
        identity,
    )


def _config_file(path):
    path = local_absolute_path(path)
    with LocalPathGuard(path, directory=False) as guard:
        size, sha256 = _hash_file(path, guard)
        native = guard.verify()
    return RegisteredReference('CONFIG_FILE', native.canonical_path, native, sha256, size, None)


def capture_registered_references(session, audit, *, configuration_paths):
    """The native operator declares config file references; no .env autodiscovery."""
    session.verify()
    if capture_audit(session) != audit:
        raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
    references = []
    configuration_identities = set()
    for path in configuration_paths:
        reference = _config_file(path)
        if reference.identity == session.source_guard.identity:
            raise MaintenancePreparationError('CONFIG_REFERENCE_MUST_NOT_BE_DATABASE')
        if reference.identity in configuration_identities:
            raise MaintenancePreparationError('DUPLICATE_CONFIGURATION_REFERENCE')
        configuration_identities.add(reference.identity)
        references.append(reference)
    source_root = Path(audit.root_path)
    for file in audit.files:
        if not file.name.endswith('.admission.json'):
            continue
        with LocalPathGuard(source_root / file.name, directory=False) as guard:
            if guard.identity != file.identity or file.byte_count > 32768:
                raise MaintenancePreparationError('ADMISSION_REFERENCE_UNVERIFIED')
            with (source_root / file.name).open('rb') as stream:
                raw = stream.read(32769)
            if len(raw) != file.byte_count or hashlib.sha256(raw).hexdigest() != file.sha256:
                raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
            record = strict_json_object(raw)
            keys = ('schema_version', 'source_database', 'llm_use_id', 'approved_at', 'admission')
            object_fields(record, 'admission', keys, keys)
            if (
                type(record['schema_version']) is not int
                or record['schema_version'] != 1
                or type(record['admission']) is not dict
            ):
                raise MaintenancePreparationError('ADMISSION_REFERENCE_UNVERIFIED')
            _time(record['approved_at'])
            reference = _document_call(session, record['source_database'], record['llm_use_id'])
            references.append(reference)
            guard.verify()
    # A call referenced by multiple admissions is one registered reference, not a copied directory.
    unique = {}
    for reference in references:
        key = (reference.kind, reference.path, reference.llm_use_id)
        previous = unique.get(key)
        if previous is not None and previous != reference:
            raise MaintenancePreparationError('REGISTERED_REFERENCE_CHANGED')
        unique[key] = reference
    if capture_audit(session) != audit:
        raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
    session.verify()
    return tuple(
        sorted(unique.values(), key=lambda item: (item.kind, item.path, item.llm_use_id or 0))
    )


def verify_registered_references(session, references):
    session.verify()
    for expected in references:
        if expected.kind == 'CONFIG_FILE' and expected.llm_use_id is None:
            observed = _config_file(expected.path)
        elif (
            expected.kind in ('INTERNAL_CALL', 'DOCUMENT_CALL') and expected.llm_use_id is not None
        ):
            observed = _document_call(session, expected.path, expected.llm_use_id)
        else:
            raise MaintenancePreparationError('REGISTERED_REFERENCE_KIND_INVALID')
        if observed != expected:
            raise MaintenancePreparationError('REGISTERED_REFERENCE_CHANGED')
    session.verify()
