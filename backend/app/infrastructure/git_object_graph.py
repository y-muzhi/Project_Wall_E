"""Bounded edges from verified raw commit/tree objects; no history traversal.

Identity/header bytes and messages remain private and unmodified. This decoder
does not execute signatures, expand paths, materialize content or approve a tree.
"""

from dataclasses import dataclass, field

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid
from .content_paths import ContentPathIndex, relative_content_path
from .git_object_read import ReadGitObject, verify_git_object


class GitObjectGraphError(ValueError):
    code = 'CONTENT_NOT_READY'


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise GitObjectGraphError('GIT_OBJECT_GRAPH_LIMIT_INVALID')
    return value


def require_original_object(value, kind, max_object_bytes):
    _limit(max_object_bytes)
    if (
        type(value) is not ReadGitObject
        or value.object_type != kind
        or type(value.byte_count) is not int
        or type(value.sha256) is not str
    ):
        raise GitObjectGraphError('ORIGINAL_GIT_OBJECT_KIND_REQUIRED')
    original = verify_git_object(
        value.raw,
        format=value.format,
        object_type=kind,
        oid=value.object_oid,
        max_output_bytes=max_object_bytes,
    )
    if original != value:
        raise GitObjectGraphError('ORIGINAL_GIT_OBJECT_FACTS_DIFFER')
    return original


def _oid(raw, format):
    try:
        value = raw.decode('ascii')
        git_oid(value, format)
    except (UnicodeError, ValueError):
        raise GitObjectGraphError('GIT_OBJECT_GRAPH_OID_INVALID') from None
    if set(value) == {'0'}:
        raise GitObjectGraphError('GIT_OBJECT_GRAPH_OID_INVALID')
    return value


@dataclass(frozen=True)
class CommitEdges:
    tree_oid: str
    parent_oids: tuple[str, ...]


def decode_commit_edges(value, *, max_object_bytes, max_headers):
    original = require_original_object(value, 'commit', max_object_bytes)
    maximum = _limit(max_headers)
    separator = original.raw.find(b'\n\n')
    if separator < 0:
        raise GitObjectGraphError('GIT_COMMIT_HEADER_TERMINATOR_MISSING')
    header = original.raw[:separator]
    if not header or b'\0' in header or b'\r' in header:
        raise GitObjectGraphError('GIT_COMMIT_HEADER_INVALID')
    lines = header.split(b'\n')
    if len(lines) > maximum:
        raise GitObjectGraphError('GIT_COMMIT_HEADER_LIMIT_EXCEEDED')
    if not lines[0].startswith(b'tree '):
        raise GitObjectGraphError('GIT_COMMIT_FIRST_TREE_REQUIRED')
    tree = _oid(lines[0][5:], original.format)
    parents = []
    position = 1
    while position < len(lines) and lines[position].startswith(b'parent '):
        parents.append(_oid(lines[position][7:], original.format))
        position += 1
    for key in (b'author', b'committer'):
        if position >= len(lines) or not lines[position].startswith(key + b' '):
            raise GitObjectGraphError('GIT_COMMIT_IDENTITY_HEADER_MISSING')
        if not lines[position][len(key) + 1 :]:
            raise GitObjectGraphError('GIT_COMMIT_IDENTITY_HEADER_EMPTY')
        position += 1
    previous = None
    for line in lines[position:]:
        if line.startswith(b' '):
            if previous is None:
                raise GitObjectGraphError('GIT_COMMIT_ORPHAN_HEADER_CONTINUATION')
            continue
        key, delimiter, body = line.partition(b' ')
        if (
            not delimiter
            or not key
            or not body
            or any(byte < 33 or byte > 126 for byte in key)
            or key in (b'tree', b'parent', b'author', b'committer')
        ):
            raise GitObjectGraphError('GIT_COMMIT_EXTRA_HEADER_INVALID')
        previous = key
    return CommitEdges(tree, tuple(parents))


@dataclass(frozen=True)
class TreeEdge:
    name: str
    mode: str
    object_type: str
    object_oid: str


@dataclass(frozen=True)
class TreeLink:
    name: bytes = field(repr=False)
    mode: str
    object_type: str
    object_oid: str


def decode_tree_links(value, *, max_object_bytes, max_entries):
    original = require_original_object(value, 'tree', max_object_bytes)
    maximum = _limit(max_entries)
    oid_bytes = 20 if original.format == 'sha1' else 32
    raw = original.raw
    position, previous = 0, None
    names, entries = set(), []
    while position < len(raw):
        if len(entries) >= maximum:
            raise GitObjectGraphError('GIT_TREE_ENTRY_LIMIT_EXCEEDED')
        space = raw.find(b' ', position)
        end = raw.find(b'\0', space + 1) if space >= 0 else -1
        if space < 0 or end < 0 or end + 1 + oid_bytes > len(raw):
            raise GitObjectGraphError('GIT_TREE_RECORD_INCOMPLETE')
        mode = raw[position:space]
        if mode not in (b'40000', b'100644', b'100755', b'120000', b'160000'):
            raise GitObjectGraphError('GIT_TREE_MODE_UNSUPPORTED')
        name_bytes = raw[space + 1 : end]
        if b'/' in name_bytes or not name_bytes:
            raise GitObjectGraphError('GIT_TREE_SINGLE_COMPONENT_REQUIRED')
        directory = mode == b'40000'
        # Git compares a directory basename as if it had a trailing slash.
        key = name_bytes + (b'/' if directory else b'\0')
        if (previous is not None and key <= previous) or name_bytes in names:
            raise GitObjectGraphError('GIT_TREE_ORDER_OR_DUPLICATE_INVALID')
        previous = key
        names.add(name_bytes)
        oid = raw[end + 1 : end + 1 + oid_bytes].hex()
        if set(oid) == {'0'}:
            raise GitObjectGraphError('GIT_TREE_NULL_OBJECT_UNSUPPORTED')
        kind = 'tree' if directory else 'commit' if mode == b'160000' else 'blob'
        entries.append(TreeLink(name_bytes, mode.decode('ascii'), kind, oid))
        position = end + 1 + oid_bytes
    return tuple(entries)


def decode_tree_edges(value, *, max_object_bytes, max_entries):
    links = decode_tree_links(value, max_object_bytes=max_object_bytes, max_entries=max_entries)
    index = ContentPathIndex()
    entries = []
    for link in links:
        if link.mode not in ('40000', '100644', '100755'):
            raise GitObjectGraphError('GIT_TREE_MODE_UNSUPPORTED')
        try:
            name = link.name.decode('utf-8', errors='strict')
        except UnicodeError:
            raise GitObjectGraphError('GIT_TREE_NAME_UTF8_INVALID') from None
        relative_content_path(name)
        if link.mode == '40000':
            index.add_directory(name)
        else:
            index.add_file(name, link.mode)
        entries.append(TreeEdge(name, link.mode, link.object_type, link.object_oid))
    return tuple(entries)
