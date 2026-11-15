"""Strict files-backend refs before fixed read-only Git metadata commands."""

from dataclasses import dataclass, replace

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid, object_format
from .git_ref_protocol import RefProtocolError, branch_namespace, branch_ref
from .windows_worktree_heads import metadata_line


class RefMetadataError(ValueError):
    pass


def full_ref(value):
    if type(value) is not str or not value.startswith('refs/'):
        raise RefMetadataError('METADATA_FULL_REF_REQUIRED')
    try:
        branch_ref('refs/heads/' + value[5:])
    except RefProtocolError:
        raise RefMetadataError('METADATA_REF_NAME_INVALID') from None
    if value.casefold().startswith('refs/heads/') and not value.startswith('refs/heads/'):
        raise RefMetadataError('METADATA_HEAD_NAMESPACE_ALIAS')
    if value.casefold() == 'refs/replace' or value.casefold().startswith('refs/replace/'):
        raise RefMetadataError('METADATA_REPLACE_REFS_UNSUPPORTED')
    return value


def _oid(value, format):
    try:
        git_oid(value, format)
    except ValueError:
        raise RefMetadataError('METADATA_REF_OID_INVALID') from None
    if set(value) == {'0'}:
        raise RefMetadataError('METADATA_ZERO_REF_OID_UNSUPPORTED')
    return value


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise RefMetadataError('METADATA_REF_LIMIT_INVALID')
    return value


@dataclass(frozen=True)
class PackedRef:
    name: str
    object_oid: str
    peeled_oid: str | None


def decode_packed_refs(raw, *, format, max_output_bytes, max_refs):
    object_format(format)
    maximum, count = _limit(max_output_bytes), _limit(max_refs)
    if type(raw) is not bytes or len(raw) > maximum or b'\0' in raw or b'\r' in raw:
        raise RefMetadataError('METADATA_PACKED_REFS_BYTES_INVALID')
    if raw and not raw.endswith(b'\n'):
        raise RefMetadataError('METADATA_PACKED_REFS_INCOMPLETE')
    rows, seen = [], set()
    for line in raw[:-1].split(b'\n') if raw else ():
        if not line:
            raise RefMetadataError('METADATA_PACKED_REFS_EMPTY_LINE')
        if line.startswith(b'#'):
            continue
        if line.startswith(b'^'):
            if (
                not rows
                or rows[-1].peeled_oid is not None
                or rows[-1].name.startswith('refs/heads/')
            ):
                raise RefMetadataError('METADATA_PACKED_PEELED_REF_INVALID')
            try:
                oid = _oid(line[1:].decode('ascii'), format)
            except UnicodeError:
                raise RefMetadataError('METADATA_REF_OID_INVALID') from None
            rows[-1] = replace(rows[-1], peeled_oid=oid)
            continue
        if len(rows) >= count:
            raise RefMetadataError('METADATA_REF_COUNT_EXCEEDED')
        try:
            oid, separator, name = line.decode('utf-8', errors='strict').partition(' ')
        except UnicodeError:
            raise RefMetadataError('METADATA_PACKED_REFS_UTF8_INVALID') from None
        if not separator:
            raise RefMetadataError('METADATA_PACKED_REF_FIELDS_INVALID')
        full_ref(name)
        _oid(oid, format)
        if name in seen:
            raise RefMetadataError('METADATA_DUPLICATE_PACKED_REF')
        seen.add(name)
        rows.append(PackedRef(name, oid, None))
    try:
        branch_namespace(tuple(row.name for row in rows if row.name.startswith('refs/heads/')))
    except RefProtocolError:
        raise RefMetadataError('METADATA_BRANCH_ALIAS_OR_CONFLICT') from None
    return tuple(rows)


def decode_loose_ref(name, raw, *, format):
    object_format(format)
    full_ref(name)
    value = metadata_line(raw)
    if value.startswith('ref: '):
        if name.startswith('refs/heads/'):
            raise RefMetadataError('METADATA_HEAD_SYMREF_UNSUPPORTED')
        return 'SYMBOLIC', full_ref(value[5:])
    return 'DIRECT', _oid(value, format)
