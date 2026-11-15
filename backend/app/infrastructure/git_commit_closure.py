"""Bounded closure of explicit commit roots using original backend-owned reads.

No launch, retry, DB transaction, content materialization or admission decision.
Callbacks belong to the trusted caller retaining the original repository lease.
"""

import hashlib
import math
from collections import deque
from dataclasses import asdict, dataclass
from time import monotonic

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid, object_format
from .git_object_graph import decode_commit_edges, decode_tree_links, require_original_object
from backend.app.shared.json_canonical import canonical_input


class GitClosureError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        self.code = (
            'SOURCE_CHANGED' if reason == 'GIT_CLOSURE_SOURCE_CHANGED' else 'CONTENT_NOT_READY'
        )
        super().__init__(reason)


def _positive(value):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise GitClosureError('GIT_CLOSURE_LIMIT_INVALID')
    return value


@dataclass(frozen=True)
class ClosureLimits:
    max_objects: int
    max_edges: int
    max_object_bytes: int
    max_total_bytes: int
    max_seconds: int

    def __post_init__(self):
        for value in asdict(self).values():
            _positive(value)


@dataclass(frozen=True)
class ObjectReadRequest:
    format: str
    object_type: str
    object_oid: str
    max_output_bytes: int
    remaining_seconds: float


@dataclass(frozen=True)
class ObjectReadFact:
    object_type: str
    object_oid: str
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class CommitClosure:
    format: str
    source_fingerprint_sha256: str
    roots: tuple[str, ...]
    objects: tuple[ObjectReadFact, ...]
    edge_count: int
    byte_count: int
    fingerprint_sha256: str


class OriginalObjectReads:
    def __init__(
        self,
        format,
        read_object,
        source_fingerprint,
        verify_source,
        check_active,
        limits,
        started_at,
        clock,
    ):
        object_format(format)
        if type(limits) is not ClosureLimits:
            raise GitClosureError('GIT_CLOSURE_LIMITS_REQUIRED')
        if (
            type(source_fingerprint) is not str
            or len(source_fingerprint) != 64
            or any(char not in '0123456789abcdef' for char in source_fingerprint)
        ):
            raise GitClosureError('GIT_CLOSURE_ORIGINAL_SOURCE_REQUIRED')
        if not all(callable(value) for value in (read_object, verify_source, check_active, clock)):
            raise GitClosureError('GIT_CLOSURE_ORIGINAL_READERS_REQUIRED')
        if type(started_at) not in (int, float) or not math.isfinite(started_at) or started_at < 0:
            raise GitClosureError('GIT_CLOSURE_START_TIME_INVALID')
        self.format, self.limits = format, limits
        self.read_object, self.verify_source, self.check_active, self.clock = (
            read_object,
            verify_source,
            check_active,
            clock,
        )
        self.source = source_fingerprint
        self.deadline = started_at + limits.max_seconds
        self.last_time = started_at
        self.facts = {}
        self.byte_count = 0

    def remaining(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self.last_time:
            raise GitClosureError('GIT_CLOSURE_CLOCK_UNVERIFIED')
        self.last_time = now
        if now >= self.deadline:
            raise GitClosureError('GIT_CLOSURE_TIME_LIMIT_EXCEEDED')
        return self.deadline - now

    def checkpoint(self):
        self.remaining()
        if self.check_active() is not None:
            raise GitClosureError('GIT_CLOSURE_ACTIVE_CHECK_UNVERIFIED')
        source = self.verify_source()
        if type(source) is not str or source != self.source:
            raise GitClosureError('GIT_CLOSURE_SOURCE_CHANGED')
        return self.remaining()

    def read_original(self, kind, oid, *, maximum=None):
        git_oid(oid, self.format)
        if set(oid) == {'0'}:
            raise GitClosureError('GIT_CLOSURE_NULL_OBJECT')
        if oid not in self.facts and len(self.facts) >= self.limits.max_objects:
            raise GitClosureError('GIT_CLOSURE_OBJECT_LIMIT_EXCEEDED')
        if oid in self.facts and self.facts[oid].object_type != kind:
            raise GitClosureError('GIT_CLOSURE_OBJECT_KIND_CONFLICT')
        if maximum is not None:
            _positive(maximum)
        remaining_seconds = self.checkpoint()
        remaining_bytes = self.limits.max_total_bytes - self.byte_count
        # With no bytes left only a one-byte bounded probe can prove an empty
        # object. Any nonempty response fails before a success fact is retained.
        maximum = max(
            1,
            min(
                self.limits.max_object_bytes,
                remaining_bytes,
                maximum if maximum is not None else self.limits.max_object_bytes,
            ),
        )
        request = ObjectReadRequest(self.format, kind, oid, maximum, remaining_seconds)
        value = self.read_object(request)
        self.checkpoint()
        original = require_original_object(value, kind, maximum)
        if original.format != self.format or original.object_oid != oid:
            raise GitClosureError('GIT_CLOSURE_ORIGINAL_OBJECT_DIFFERS')
        if self.byte_count + original.byte_count > self.limits.max_total_bytes:
            raise GitClosureError('GIT_CLOSURE_BYTE_LIMIT_EXCEEDED')
        self.byte_count += original.byte_count
        self.facts[oid] = ObjectReadFact(kind, oid, original.byte_count, original.sha256)
        return original


class _Inspection(OriginalObjectReads):
    def __init__(
        self,
        roots,
        format,
        read_object,
        source_fingerprint,
        verify_source,
        check_active,
        limits,
        started_at,
        clock,
    ):
        if type(limits) is not ClosureLimits:
            raise GitClosureError('GIT_CLOSURE_LIMITS_REQUIRED')
        if type(roots) is not tuple or not roots or len(roots) > limits.max_edges:
            raise GitClosureError('GIT_CLOSURE_ROOTS_INVALID')
        super().__init__(
            format,
            read_object,
            source_fingerprint,
            verify_source,
            check_active,
            limits,
            started_at,
            clock,
        )
        self.roots = roots
        self.pending, self.scheduled = deque(), {}
        self.edges = 0
        for root in roots:
            self.add('commit', root)

    def add(self, kind, oid):
        git_oid(oid, self.format)
        if set(oid) == {'0'}:
            raise GitClosureError('GIT_CLOSURE_NULL_OBJECT')
        if self.edges >= self.limits.max_edges:
            raise GitClosureError('GIT_CLOSURE_EDGE_LIMIT_EXCEEDED')
        self.edges += 1
        if oid in self.scheduled:
            if self.scheduled[oid] != kind:
                raise GitClosureError('GIT_CLOSURE_OBJECT_KIND_CONFLICT')
            return
        if len(self.scheduled) >= self.limits.max_objects:
            raise GitClosureError('GIT_CLOSURE_OBJECT_LIMIT_EXCEEDED')
        self.scheduled[oid] = kind
        self.pending.append((kind, oid))

    def read_one(self, kind, oid):
        original = self.read_original(kind, oid)
        maximum = self.limits.max_object_bytes
        if kind == 'commit':
            edges = decode_commit_edges(
                original,
                max_object_bytes=maximum,
                max_headers=min(MAX_SAFE_INTEGER, self.limits.max_edges + 3),
            )
            self.add('tree', edges.tree_oid)
            for parent in edges.parent_oids:
                self.add('commit', parent)
        elif kind == 'tree':
            entries = decode_tree_links(
                original, max_object_bytes=maximum, max_entries=self.limits.max_edges
            )
            for entry in entries:
                if entry.mode == '160000':
                    raise GitClosureError('GIT_CLOSURE_EXTERNAL_GITLINK_UNSUPPORTED')
                self.add(entry.object_type, entry.object_oid)

    def inspect(self):
        while self.pending:
            self.read_one(*self.pending.popleft())
        self.checkpoint()
        records = tuple(sorted(self.facts.values(), key=lambda value: value.object_oid))
        payload = {
            'schema_version': 1,
            'format': self.format,
            'source': self.source,
            'roots': list(self.roots),
            'objects': [asdict(value) for value in records],
            'edge_count': self.edges,
            'byte_count': self.byte_count,
        }
        digest = hashlib.sha256(canonical_input(payload).encode('utf-8')).hexdigest()
        self.checkpoint()
        return CommitClosure(
            self.format, self.source, self.roots, records, self.edges, self.byte_count, digest
        )


def inspect_commit_closure(
    roots,
    *,
    format,
    read_object,
    source_fingerprint,
    verify_source,
    check_active,
    limits,
    started_at,
    clock=monotonic,
):
    """Read the exact root closure once; every failure propagates, without retries."""
    return _Inspection(
        roots,
        format,
        read_object,
        source_fingerprint,
        verify_source,
        check_active,
        limits,
        started_at,
        clock,
    ).inspect()
