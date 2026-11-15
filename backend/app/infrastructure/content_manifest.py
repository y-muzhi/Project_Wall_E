"""CONTENT20-STORE-1 canonical metadata and raw blob integrity.

No filesystem/Git IO, capture, secret-policy approval, publishing or DB writes.
A valid manifest is metadata, not proof that its tree/object closure exists.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import re

from backend.app.shared.validation import MAX_SAFE_INTEGER, InvalidInput, strict_json_object
from .content_paths import ContentPathIndex, content_file_mode, relative_content_path

CONTENT_POLICY = 'CONTENT20-STORE-1'


class ContentManifestError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _integer(value, *, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise ContentManifestError('CONTENT_INTEGER_INVALID')
    return value


def object_format(value):
    if type(value) is not str or value not in ('sha1', 'sha256'):
        raise ContentManifestError('CONTENT_OBJECT_FORMAT_INVALID')
    return value


def git_oid(value, format):
    length = 40 if object_format(format) == 'sha1' else 64
    if type(value) is not str or re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is None:
        raise ContentManifestError('CONTENT_OBJECT_ID_INVALID')
    return value


def _sha256(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ContentManifestError('CONTENT_SHA256_INVALID')
    return value


@dataclass(frozen=True)
class ContentLimits:
    max_file_bytes: int
    max_snapshot_bytes: int
    max_snapshot_files: int
    max_manifest_bytes: int

    def __post_init__(self):
        for value in asdict(self).values():
            _integer(value, minimum=1)


@dataclass(frozen=True)
class ContentEntry:
    path: str
    mode: str
    blob_oid: str
    byte_count: int
    sha256: str


def _entry(value, format, limits):
    if type(value) is not ContentEntry:
        raise ContentManifestError('CONTENT_ENTRY_INVALID')
    relative_content_path(value.path)
    content_file_mode(value.mode)
    git_oid(value.blob_oid, format)
    _sha256(value.sha256)
    _integer(value.byte_count)
    if value.byte_count > limits.max_file_bytes:
        raise ContentManifestError('CONTENT_FILE_LIMIT_EXCEEDED')
    return value


def _entries(values, format, limits, *, materialization_root=None):
    if type(limits) is not ContentLimits:
        raise ContentManifestError('CONTENT_LIMITS_REQUIRED')
    object_format(format)
    index = ContentPathIndex(materialization_root=materialization_root)
    output = []
    total = 0
    for value in values:
        if len(output) >= limits.max_snapshot_files:
            raise ContentManifestError('CONTENT_FILE_COUNT_EXCEEDED')
        entry = _entry(value, format, limits)
        index.add_file(entry.path, entry.mode)
        total += entry.byte_count
        if total > MAX_SAFE_INTEGER or total > limits.max_snapshot_bytes:
            raise ContentManifestError('CONTENT_TOTAL_BYTES_EXCEEDED')
        output.append(entry)
    return tuple(sorted(output, key=lambda entry: entry.path.encode('utf-8'))), total


@dataclass(frozen=True)
class ContentManifest:
    schema_version: int
    content_policy_version: str
    content_profile_version_id: int
    object_format: str
    content_tree_oid: str
    entries: tuple[ContentEntry, ...]
    file_count: int
    byte_count: int

    def as_dict(self):
        value = asdict(self)
        value['entries'] = [asdict(entry) for entry in self.entries]
        return value


def _canonical(value):
    return (
        json.dumps(
            value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False
        )
        + '\n'
    ).encode('utf-8')


def validate_manifest(value, limits, *, materialization_root=None):
    if type(value) is not ContentManifest or type(value.entries) is not tuple:
        raise ContentManifestError('CONTENT_MANIFEST_INVALID')
    if type(value.schema_version) is not int or value.schema_version != 1:
        raise ContentManifestError('CONTENT_SCHEMA_VERSION_INVALID')
    if (
        type(value.content_policy_version) is not str
        or value.content_policy_version != CONTENT_POLICY
    ):
        raise ContentManifestError('CONTENT_POLICY_INVALID')
    _integer(value.content_profile_version_id, minimum=1)
    git_oid(value.content_tree_oid, value.object_format)
    entries, total = _entries(
        value.entries, value.object_format, limits, materialization_root=materialization_root
    )
    if entries != value.entries:
        raise ContentManifestError('CONTENT_ENTRY_ORDER_INVALID')
    _integer(value.file_count)
    _integer(value.byte_count)
    if value.file_count != len(entries) or value.byte_count != total:
        raise ContentManifestError('CONTENT_MANIFEST_COUNTS_DIFFER')
    return value


def encode_manifest(value, limits, *, materialization_root=None):
    validate_manifest(value, limits, materialization_root=materialization_root)
    raw = _canonical(value.as_dict())
    if len(raw) > limits.max_manifest_bytes:
        raise ContentManifestError('CONTENT_MANIFEST_BYTES_EXCEEDED')
    return raw


def manifest_sha256(raw):
    if type(raw) is not bytes:
        raise ContentManifestError('CONTENT_MANIFEST_BYTES_REQUIRED')
    return hashlib.sha256(raw).hexdigest()


def fixed_entries_sha256(entries):
    """Digest the exact ordered entries of a registered original Git baseline."""
    from backend.app.shared.json_canonical import canonical_input

    value = canonical_input({'entries': [asdict(entry) for entry in entries]})
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def build_manifest(
    entries,
    *,
    content_profile_version_id,
    format,
    content_tree_oid,
    limits,
    materialization_root=None,
):
    ordered, total = _entries(entries, format, limits, materialization_root=materialization_root)
    manifest = ContentManifest(
        1,
        CONTENT_POLICY,
        content_profile_version_id,
        format,
        content_tree_oid,
        ordered,
        len(ordered),
        total,
    )
    # Validate before returning a nominally complete metadata object.
    encode_manifest(manifest, limits, materialization_root=materialization_root)
    return manifest


def decode_manifest(
    raw,
    *,
    limits,
    expected_sha256=None,
    expected_format=None,
    expected_profile_version_id=None,
    materialization_root=None,
):
    if type(raw) is not bytes:
        raise ContentManifestError('CONTENT_MANIFEST_BYTES_REQUIRED')
    if type(limits) is not ContentLimits:
        raise ContentManifestError('CONTENT_LIMITS_REQUIRED')
    if len(raw) > limits.max_manifest_bytes:
        raise ContentManifestError('CONTENT_MANIFEST_BYTES_EXCEEDED')
    if expected_sha256 is not None and manifest_sha256(raw) != _sha256(expected_sha256):
        raise ContentManifestError('CONTENT_MANIFEST_DIGEST_DIFFERS')
    try:
        row = strict_json_object(raw)
    except InvalidInput:
        raise ContentManifestError('CONTENT_MANIFEST_JSON_INVALID') from None
    if set(row) != set(ContentManifest.__dataclass_fields__) or type(row['entries']) is not list:
        raise ContentManifestError('CONTENT_MANIFEST_FIELDS_INVALID')
    entries = []
    if len(row['entries']) > limits.max_snapshot_files:
        raise ContentManifestError('CONTENT_FILE_COUNT_EXCEEDED')
    for value in row['entries']:
        if type(value) is not dict or set(value) != set(ContentEntry.__dataclass_fields__):
            raise ContentManifestError('CONTENT_ENTRY_FIELDS_INVALID')
        entries.append(ContentEntry(**value))
    manifest = ContentManifest(**{**row, 'entries': tuple(entries)})
    encoded = encode_manifest(manifest, limits, materialization_root=materialization_root)
    if raw != encoded:
        raise ContentManifestError('CONTENT_MANIFEST_NOT_CANONICAL')
    if expected_format is not None and manifest.object_format != object_format(expected_format):
        raise ContentManifestError('CONTENT_OBJECT_FORMAT_DIFFERS')
    if expected_profile_version_id is not None and manifest.content_profile_version_id != _integer(
        expected_profile_version_id, minimum=1
    ):
        raise ContentManifestError('CONTENT_PROFILE_VERSION_DIFFERS')
    return manifest


class BlobVerifier:
    """Incremental raw bytes only. Native reader must separately bound IO/time."""

    def __init__(self, entry, *, format, limits):
        if type(limits) is not ContentLimits:
            raise ContentManifestError('CONTENT_LIMITS_REQUIRED')
        self._entry = _entry(entry, format, limits)
        self._content = hashlib.sha256()
        self._object = hashlib.new(format)
        self._object.update(b'blob ' + str(entry.byte_count).encode('ascii') + b'\0')
        self._count = 0
        self._closed = False

    @property
    def entry(self):
        return self._entry

    def feed(self, data):
        if self._closed:
            raise ContentManifestError('CONTENT_BLOB_VERIFIER_CLOSED')
        if type(data) is not bytes or not data:
            self._closed = True
            raise ContentManifestError('CONTENT_BLOB_CHUNK_INVALID')
        if self._count + len(data) > self.entry.byte_count:
            self._closed = True
            raise ContentManifestError('CONTENT_BLOB_LENGTH_DIFFERS')
        self._count += len(data)
        self._content.update(data)
        self._object.update(data)

    def finish(self):
        if self._closed:
            raise ContentManifestError('CONTENT_BLOB_VERIFIER_CLOSED')
        self._closed = True
        if self._count != self.entry.byte_count:
            raise ContentManifestError('CONTENT_BLOB_LENGTH_DIFFERS')
        if self._content.hexdigest() != self.entry.sha256:
            raise ContentManifestError('CONTENT_BLOB_SHA256_DIFFERS')
        if self._object.hexdigest() != self.entry.blob_oid:
            raise ContentManifestError('CONTENT_BLOB_OBJECT_ID_DIFFERS')
        return self.entry


@dataclass(frozen=True)
class ContentDifference:
    path: str
    before: ContentEntry | None
    after: ContentEntry | None


def compare_content(before, after, *, format, limits):
    """Exact paths only; baseline entries do not require a persisted manifest."""
    old, _ = _entries(before, format, limits)
    new, _ = _entries(after, format, limits)
    old_by_path = {entry.path: entry for entry in old}
    new_by_path = {entry.path: entry for entry in new}
    changes = []
    for path in sorted(
        old_by_path.keys() | new_by_path.keys(), key=lambda value: value.encode('utf-8')
    ):
        prior, current = old_by_path.get(path), new_by_path.get(path)
        if prior != current:
            changes.append(ContentDifference(path, prior, current))
    return tuple(changes)
