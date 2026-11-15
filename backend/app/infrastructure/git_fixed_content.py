"""Inspect fixed commit entries and stream policy-verified original blobs."""

import re
from dataclasses import dataclass
from time import monotonic

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import ContentEntry, ContentLimits
from .content_paths import ContentPathIndex
from .git_commit_closure import ClosureLimits, GitClosureError, OriginalObjectReads
from .git_object_graph import decode_commit_edges, decode_tree_edges


@dataclass(frozen=True)
class FixedTreeContent:
    commit_oid: str
    tree_oid: str
    source_fingerprint_sha256: str
    entries: tuple[ContentEntry, ...]
    byte_count: int
    enumerated_entries: int


def reject_lfs_pointer(raw):
    if not raw or len(raw) >= 1024 or not raw.endswith(b'\n'):
        return
    try:
        raw.decode('utf-8', errors='strict')
    except UnicodeError:
        return
    lines = raw[:-1].split(b'\n')
    if lines[0] not in (
        b'version https://git-lfs.github.com/spec/v1',
        b'version https://hawser.github.com/spec/v1',
    ):
        return
    fields = {}
    order = []
    for line in lines[1:]:
        key, separator, value = line.partition(b' ')
        if (
            not separator
            or not value
            or b'\r' in value
            or re.fullmatch(rb'[a-z0-9.-]+', key) is None
            or key in fields
            or key == b'version'
        ):
            return
        fields[key] = value
        order.append(key)
    if order != sorted(order):
        return
    if (
        re.fullmatch(rb'sha256:[0-9a-f]{64}', fields.get(b'oid', b'')) is not None
        and re.fullmatch(rb'0|[1-9][0-9]*', fields.get(b'size', b'')) is not None
    ):
        raise GitClosureError('CONTENT_LFS_POINTER_UNSUPPORTED')


def inspect_fixed_tree(
    commit_oid,
    *,
    format,
    read_object,
    source_fingerprint,
    verify_source,
    check_active,
    read_limits,
    content_limits,
    materialization_root,
    check_file,
    started_at,
    check_path=None,
    consume_file=None,
    clock=monotonic,
):
    """The trusted caller must supply its registered file policy; no default allow.

    This returns checked file metadata, never a secret-policy/Guard admission.
    It does not inspect parents: full history uses inspect_commit_closure separately.
    """
    if type(content_limits) is not ContentLimits or type(read_limits) is not ClosureLimits:
        raise GitClosureError('CONTENT_AND_READ_LIMITS_REQUIRED')
    if not callable(check_file) or materialization_root is None:
        raise GitClosureError('CONTENT_FILE_POLICY_AND_TARGET_REQUIRED')
    if consume_file is not None and not callable(consume_file):
        raise GitClosureError('CONTENT_FILE_CONSUMER_INVALID')
    reads = OriginalObjectReads(
        format,
        read_object,
        source_fingerprint,
        verify_source,
        check_active,
        read_limits,
        started_at,
        clock,
    )
    commit = reads.read_original('commit', commit_oid)
    root = decode_commit_edges(
        commit,
        max_object_bytes=read_limits.max_object_bytes,
        max_headers=min(MAX_SAFE_INTEGER, read_limits.max_edges + 3),
    ).tree_oid
    namespace = ContentPathIndex(materialization_root=materialization_root)
    pending = [('', root)]
    entries = []
    total, enumerated = 0, 1
    while pending:
        prefix, oid = pending.pop()
        tree = reads.read_original('tree', oid)
        children = decode_tree_edges(
            tree, max_object_bytes=read_limits.max_object_bytes, max_entries=read_limits.max_edges
        )
        if enumerated + len(children) > read_limits.max_edges:
            raise GitClosureError('CONTENT_ENUMERATION_LIMIT_EXCEEDED')
        enumerated += len(children)
        for child in children:
            reads.checkpoint()
            path = prefix + child.name
            if child.object_type == 'tree':
                namespace.add_directory(path)
                pending.append((path + '/', child.object_oid))
                continue
            namespace.add_file(path, child.mode)
            if check_path is not None and (
                not callable(check_path) or check_path(path) is not None
            ):
                raise GitClosureError('CONTENT_PATH_POLICY_UNVERIFIED')
            if len(entries) >= content_limits.max_snapshot_files:
                raise GitClosureError('CONTENT_FILE_COUNT_EXCEEDED')
            # Read at most the remaining per-file/content budget (plus the
            # reader's one-byte EOF probe), not just the operational IO budget.
            maximum = min(content_limits.max_file_bytes, content_limits.max_snapshot_bytes - total)
            blob = reads.read_original('blob', child.object_oid, maximum=max(1, maximum))
            if (
                blob.byte_count > content_limits.max_file_bytes
                or total + blob.byte_count > content_limits.max_snapshot_bytes
            ):
                raise GitClosureError('CONTENT_FILE_BYTES_EXCEEDED')
            reject_lfs_pointer(blob.raw)
            if check_file(path, blob) is not None:
                raise GitClosureError('CONTENT_FILE_POLICY_UNVERIFIED')
            reads.checkpoint()
            total += blob.byte_count
            entry = ContentEntry(path, child.mode, child.object_oid, blob.byte_count, blob.sha256)
            if consume_file is not None and consume_file(entry, blob.raw) is not None:
                raise GitClosureError('CONTENT_FILE_CONSUMER_UNVERIFIED')
            entries.append(entry)
    ordered = tuple(sorted(entries, key=lambda value: value.path.encode('utf-8')))
    reads.checkpoint()
    return FixedTreeContent(commit_oid, root, source_fingerprint, ordered, total, enumerated)
