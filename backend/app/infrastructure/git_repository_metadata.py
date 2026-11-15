"""Original metadata tree/refs for fixed read-only queries, not Git object closure."""

import ctypes
import hashlib
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import object_format
from .git_ref_metadata import decode_loose_ref, decode_packed_refs, full_ref
from .git_ref_protocol import branch_namespace
from .git_repository_location import RepositoryLocationLease
from backend.app.shared.json_canonical import canonical_input
from .windows_config_source import LockedConfigSource
from .windows_executable_pin import UNSUPPORTED_ATTRIBUTES
from .windows_executable_pin import _api as read_api
from .windows_local_paths import FileIdentity, HandleInfo, LocalPathGuard, _identity


class MetadataTreeError(RuntimeError):
    def __init__(self, reason, native_error=None, *, changed=False):
        self.reason, self.native_error = reason, native_error
        self.code = 'SOURCE_CHANGED' if changed else 'REPOSITORY_UNSUPPORTED'
        if native_error in (32, 33):
            self.code = 'SOURCE_BUSY'
        elif native_error is not None:
            self.code = 'SOURCE_UNSUPPORTED'
        super().__init__(reason)


@dataclass(frozen=True)
class MetadataSnapshot:
    location_sha256: str
    object_format: str
    node_count: int
    heads: tuple[tuple[str, str], ...]
    lock_paths: tuple[str, ...] = field(repr=False)
    fingerprint_sha256: str


@dataclass(frozen=True)
class RepositoryReference:
    name: str
    kind: str
    value: str
    file: FileIdentity = field(repr=False)


class RepositoryMetadataLease:
    def __init__(
        self, location, *, format, max_entries, max_open_handles, max_file_bytes, max_metadata_bytes
    ):
        if type(location) is not RepositoryLocationLease:
            raise MetadataTreeError('ORIGINAL_REPOSITORY_LOCATION_REQUIRED')
        object_format(format)
        for value in (max_entries, max_open_handles, max_file_bytes, max_metadata_bytes):
            if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
                raise MetadataTreeError('METADATA_TREE_LIMIT_INVALID')
        self._location, self._format = location, format
        self._entry_limit, self._handle_limit = max_entries, max_open_handles
        self._file_limit, self._byte_limit = max_file_bytes, max_metadata_bytes
        self._gate = RLock()
        self._nodes, self._sources, self._listings = {}, {}, {}
        self._references_by_name = {}
        self._used_handles, self._used_bytes = 0, 0
        self._users = 0
        self._closing = False
        self._context = None
        self._kernel = read_api()
        self._snapshot = None
        try:
            self._context = location.hold()
            original = self._context.__enter__()
            self._common = Path(original.common_directory.canonical_path)
            self._pin(Path(original.root.canonical_path), directory=True)
            self._walk(self._common)
            heads, locks, source_facts = self._references()
            self.verify()
            evidence = {
                'location': original.fingerprint_sha256,
                'format': format,
                'nodes': [asdict(node[0].identity) for _, node in sorted(self._nodes.items())],
                'listings': {
                    str(path): list(names) for path, names in sorted(self._listings.items())
                },
                'sources': source_facts,
                'heads': [list(row) for row in heads],
                'locks': list(locks),
            }
            encoded = canonical_input(evidence).encode('utf-8')
            if len(encoded) + self._used_bytes > self._byte_limit:
                raise MetadataTreeError('METADATA_TREE_RECORD_LIMIT_EXCEEDED')
            self._snapshot = MetadataSnapshot(
                original.fingerprint_sha256,
                format,
                len(self._nodes),
                heads,
                locks,
                hashlib.sha256(encoded).hexdigest(),
            )
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _reserve(self, count):
        if self._used_handles + count > self._handle_limit:
            raise MetadataTreeError('METADATA_TREE_HANDLE_LIMIT_EXCEEDED')
        self._used_handles += count

    def _pin(self, path, *, directory):
        key = str(path)
        if key in self._nodes:
            return
        if len(self._nodes) >= self._entry_limit:
            raise MetadataTreeError('METADATA_TREE_ENTRY_LIMIT_EXCEEDED')
        self._reserve(len(path.parts) + 1)
        guard = LocalPathGuard(path, directory=directory)
        self._nodes[key] = [guard, None]
        guard.__enter__()
        handle = self._kernel.CreateFileW(
            '\\\\?\\' + str(path),
            0x81,
            0x1 if not directory else 0x1 | 0x2,
            None,
            3,
            0x00200000 | 0x02000000,
            None,
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise MetadataTreeError('METADATA_TREE_READ_PIN_UNAVAILABLE', ctypes.get_last_error())
        self._nodes[key][1] = handle
        self._verify_node(self._nodes[key])

    def _verify_node(self, node):
        guard, handle = node
        if handle is None or _identity(self._kernel, handle, guard.path) != guard.verify():
            raise MetadataTreeError('METADATA_TREE_ORIGINAL_NODE_CHANGED', changed=True)
        info = HandleInfo()
        if not self._kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise MetadataTreeError('METADATA_TREE_ATTRIBUTES_UNAVAILABLE', ctypes.get_last_error())
        if info.attributes & (UNSUPPORTED_ATTRIBUTES & ~0x10):
            raise MetadataTreeError('METADATA_TREE_ATTRIBUTES_UNSUPPORTED')

    def _listing(self, path):
        names = []
        with os.scandir(path) as listing:
            for entry in listing:
                if len(names) >= self._entry_limit:
                    raise MetadataTreeError('METADATA_TREE_ENTRY_LIMIT_EXCEEDED')
                names.append(entry.name)
        if len({name.casefold() for name in names}) != len(names):
            raise MetadataTreeError('METADATA_TREE_NAME_ALIAS')
        return tuple(sorted(names))

    def _walk(self, path):
        pending = [path]
        while pending:
            directory = pending.pop()
            self._pin(directory, directory=True)
            names = self._listing(directory)
            self._listings[directory] = names
            for name in names:
                child = directory / name
                attributes = child.lstat().st_file_attributes
                is_directory = bool(attributes & 0x10)
                self._pin(child, directory=is_directory)
                if is_directory:
                    pending.append(child)

    def _source(self, path):
        remaining = self._byte_limit - self._used_bytes
        if remaining <= 0:
            raise MetadataTreeError('METADATA_TREE_BYTES_EXCEEDED')
        self._reserve(len(path.parts) + 1)
        key = str(path)
        try:
            source = LockedConfigSource(
                path,
                max_file_bytes=min(self._file_limit, remaining),
                expected_file=self._nodes[key][0].identity,
            )
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if type(retained) is LockedConfigSource:
                self._sources[key] = retained
            raise
        self._sources[key] = source
        self._used_bytes += source.snapshot.byte_count
        return source.snapshot

    def _references(self):
        packed, loose, locks, facts = [], {}, [], []
        packed_path = self._common / 'packed-refs'
        key = str(packed_path)
        if key in self._nodes:
            source = self._source(packed_path)
            packed = decode_packed_refs(
                source.raw,
                format=self._format,
                max_output_bytes=self._file_limit,
                max_refs=self._entry_limit,
            )
            for row in packed:
                self._references_by_name[row.name] = RepositoryReference(
                    row.name, 'DIRECT', row.object_oid, source.file
                )
        for key, (guard, _) in sorted(self._nodes.items()):
            if guard.directory:
                continue
            path = guard.path
            relative = (
                path.relative_to(self._common).as_posix()
                if path.is_relative_to(self._common)
                else None
            )
            if relative is None:
                continue
            if relative.casefold().startswith('refs/') and not relative.startswith('refs/'):
                raise MetadataTreeError('METADATA_REF_NAMESPACE_ALIAS')
            parts = relative.split('/')
            administrative = len(parts) >= 3 and parts[0].casefold() == 'worktrees'
            if administrative and parts[2].casefold() in ('config.worktree', 'shallow', 'reftable'):
                raise MetadataTreeError('METADATA_UNSUPPORTED_WORKTREE_LAYOUT')
            if path.name.endswith('.lock'):
                locks.append(relative)
                continue
            if relative.startswith('refs/'):
                source = self._source(path)
                kind, value = decode_loose_ref(relative, source.raw, format=self._format)
                loose[relative] = (kind, value)
                self._references_by_name[relative] = RepositoryReference(
                    relative, kind, value, source.file
                )
            if relative.casefold().endswith('.promisor'):
                raise MetadataTreeError('METADATA_PROMISOR_UNSUPPORTED')
        names = [row.name for row in packed] + list(loose)
        branch_namespace(tuple(name for name in names if name.startswith('refs/heads/')))
        heads = {row.name: row.object_oid for row in packed if row.name.startswith('refs/heads/')}
        heads.update(
            {
                name: value
                for name, (kind, value) in loose.items()
                if name.startswith('refs/heads/') and kind == 'DIRECT'
            }
        )
        for key, source in sorted(self._sources.items()):
            facts.append({'file': asdict(source.snapshot.file), 'sha256': source.snapshot.sha256})
        return tuple(sorted(heads.items())), tuple(sorted(locks)), facts

    def _verify_pins(self):
        if self._closing:
            raise MetadataTreeError('METADATA_TREE_CLOSED')
        self._location.verify()
        for node in self._nodes.values():
            self._verify_node(node)
        for source in self._sources.values():
            source.verify()

    def verify(self):
        with self._gate:
            self._verify_pins()
            for path, names in self._listings.items():
                if self._listing(path) != names:
                    raise MetadataTreeError('METADATA_TREE_LIST_CHANGED', changed=True)
            return self._snapshot

    def reference(self, name):
        """Observe the exact files-backend reference without following a symbolic ref."""
        full_ref(name)
        with self._gate:
            self.verify()
            if any(
                existing != name and existing.casefold() == name.casefold()
                for existing in self._references_by_name
            ):
                raise MetadataTreeError('METADATA_REF_NAME_ALIAS')
            return self._references_by_name.get(name)

    @property
    def location(self):
        return self._location

    @contextmanager
    def hold(self):
        with self._gate:
            self.verify()
            self._users += 1
        try:
            yield self
        finally:
            with self._gate:
                self._users -= 1
                self.verify()

    def close(self):
        with self._gate:
            if self._users:
                raise MetadataTreeError('METADATA_TREE_IN_USE')
            self._closing = True
            try:
                for key, source in tuple(self._sources.items()):
                    source.close()
                    del self._sources[key]
                for key, node in reversed(tuple(self._nodes.items())):
                    if node[1] is not None:
                        if not self._kernel.CloseHandle(node[1]):
                            raise MetadataTreeError('METADATA_TREE_CLOSE_UNVERIFIED')
                        node[1] = None
                    node[0].close()
                    del self._nodes[key]
                if self._context is not None:
                    context, self._context = self._context, None
                    context.__exit__(None, None, None)
            except BaseException as error:
                error.retained_owner = self
                raise

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
