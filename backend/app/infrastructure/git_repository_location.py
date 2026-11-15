"""Read-only original repository location BEFORE entering a repository with Git.

This binds selected root/gitdir/commondir/config and initial forbidden markers.
It is not full repository/object/worktree admission and authorizes no Git argv.
"""

import ctypes
import hashlib
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from threading import RLock

from backend.app.shared.validation import MAX_SAFE_INTEGER

from backend.app.shared.json_canonical import canonical_input
from .windows_config_source import LockedConfigSource
from .windows_executable_pin import UNSUPPORTED_ATTRIBUTES
from .windows_executable_pin import _api as read_api
from .windows_local_paths import FileIdentity, HandleInfo, LocalPathGuard, local_absolute_path
from .windows_worktree_heads import _key, _overlap, metadata_head, metadata_line, metadata_pointer


class RepositoryLocationError(RuntimeError):
    def __init__(self, reason, native_error=None, *, changed=False):
        self.reason = reason
        self.native_error = native_error
        self.code = 'SOURCE_CHANGED' if changed else 'SOURCE_UNSUPPORTED'
        if native_error in (32, 33):
            self.code = 'SOURCE_BUSY'
        super().__init__(reason)


@dataclass(frozen=True)
class RepositoryLocationFacts:
    root: FileIdentity = field(repr=False)
    git_directory: FileIdentity = field(repr=False)
    common_directory: FileIdentity = field(repr=False)
    config: FileIdentity = field(repr=False)
    config_sha256: str
    expected_bare: bool
    linked: bool
    fingerprint_sha256: str


class RepositoryLocationLease:
    def __init__(
        self, root_path, *, private_roots, max_file_bytes, max_open_handles, max_metadata_entries
    ):
        for limit in (max_file_bytes, max_open_handles, max_metadata_entries):
            if type(limit) is not int or not 1 <= limit <= MAX_SAFE_INTEGER:
                raise RepositoryLocationError('REPOSITORY_LOCATION_LIMIT_INVALID')
        if type(private_roots) is not tuple or not private_roots:
            raise RepositoryLocationError('REPOSITORY_PRIVATE_SCOPES_REQUIRED')
        root = local_absolute_path(root_path)
        private = tuple(local_absolute_path(path) for path in private_roots)
        self._gate = RLock()
        self._file_limit, self._handle_limit = max_file_bytes, max_open_handles
        self._entry_limit = max_metadata_entries
        self._reserved, self._users = 0, 0
        self._paths, self._sources = {}, {}
        self._absent = set()
        self._closing = False
        self._private = ()
        self._kernel = read_api()
        self._facts = None
        self._pack_names = None
        self._pack = None
        try:
            self._private = tuple(self._guard(path, directory=True).identity for path in private)
            self._root = self._directory(root)
            marker = self._probe(root / '.git', optional=True)
            self._bare = marker is None
            self._linked = False
            if marker is None:
                self._git = self._root
                self._common = self._root
                self._require_absent(root / 'commondir')
            elif marker.directory:
                self._git = self._directory(marker.path)
                self._common = self._git
                self._require_absent(self._git.path / 'commondir')
            else:
                pointer = self._source(marker.path)
                target = metadata_pointer(pointer.snapshot.raw, base_directory=root, gitfile=True)
                self._git = self._directory(target)
                common_pointer = self._probe(target / 'commondir', optional=True)
                if common_pointer is None:
                    self._common = self._git
                else:
                    common = self._source(common_pointer.path)
                    self._common = self._directory(
                        metadata_pointer(common.snapshot.raw, base_directory=target)
                    )
                    if _key(self._common.identity) == _key(self._git.identity):
                        raise RepositoryLocationError('REPOSITORY_COMMON_SELF_REFERENCE')
                    admin = self._directory(self._common.path / 'worktrees')
                    actual_parent = self._directory(self._git.path.parent)
                    if _key(admin.identity) != _key(actual_parent.identity):
                        raise RepositoryLocationError('REPOSITORY_LINKED_ADMIN_LOCATION_INVALID')
                    backlink = self._source(self._git.path / 'gitdir')
                    backlink_path = metadata_pointer(backlink.snapshot.raw, base_directory=target)
                    if self._probe(backlink_path).identity != marker.identity:
                        raise RepositoryLocationError('REPOSITORY_LINKED_BACKLINK_DIFFERS')
                    self._linked = True
            self._directory(self._common.path / 'objects')
            self._directory(self._common.path / 'refs')
            self._config = self._source(self._common.path / 'config')
            head = self._source(self._git.path / 'HEAD')
            text = metadata_line(head.snapshot.raw)
            # Provisional grammar only; the object format is confirmed from
            # parsed config and complete original Git observations later.
            metadata_head(head.snapshot.raw, format='sha256' if len(text) == 64 else 'sha1')
            for directory in {self._git.path, self._common.path}:
                self._require_absent(directory / 'config.worktree')
            for relative in (
                'shallow',
                'info/grafts',
                'refs/replace',
                'reftable',
                'objects/info/alternates',
                'objects/info/http-alternates',
            ):
                self._require_absent(self._common.path / relative)
            self._pack = self._probe(self._common.path / 'objects/pack', optional=True)
            if self._pack is not None:
                if not self._pack.directory:
                    raise RepositoryLocationError('REPOSITORY_PACK_DIRECTORY_REQUIRED')
                self._pack_names = self._pack_listing()
            self.verify()
            evidence = {
                'root': asdict(self._root.identity),
                'git_directory': asdict(self._git.identity),
                'common_directory': asdict(self._common.identity),
                'paths': [asdict(guard.identity) for _, guard in sorted(self._paths.items())],
                'sources': [
                    {'file': asdict(source.snapshot.file), 'sha256': source.snapshot.sha256}
                    for _, source in sorted(self._sources.items())
                ],
                'absent': sorted(str(path) for path in self._absent),
                'pack_names': None if self._pack_names is None else list(self._pack_names),
                'expected_bare': self._bare,
                'linked': self._linked,
            }
            self._facts = RepositoryLocationFacts(
                self._root.identity,
                self._git.identity,
                self._common.identity,
                self._config.snapshot.file,
                self._config.snapshot.sha256,
                self._bare,
                self._linked,
                hashlib.sha256(canonical_input(evidence).encode('utf-8')).hexdigest(),
            )
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _reserve(self, count):
        if self._reserved + count > self._handle_limit:
            raise RepositoryLocationError('REPOSITORY_LOCATION_HANDLE_LIMIT_EXCEEDED')
        self._reserved += count

    def _guard(self, path, *, directory):
        key = str(path)
        if key not in self._paths:
            self._reserve(len(path.parts))
            guard = LocalPathGuard(path, directory=directory)
            self._paths[key] = guard
            guard.__enter__()
            self._attributes(guard)
        guard = self._paths[key]
        if guard.directory != directory:
            raise RepositoryLocationError('REPOSITORY_LOCATION_TYPE_DIFFERS')
        return guard

    def _attributes(self, guard):
        guard.verify()
        basic = HandleInfo()
        if not self._kernel.GetFileInformationByHandle(guard._held[-1][0], ctypes.byref(basic)):
            raise RepositoryLocationError(
                'REPOSITORY_METADATA_ATTRIBUTES_UNAVAILABLE', ctypes.get_last_error()
            )
        if basic.attributes & (UNSUPPORTED_ATTRIBUTES & ~0x10):
            raise RepositoryLocationError('REPOSITORY_METADATA_ATTRIBUTES_UNSUPPORTED')

    def _source_path(self, path, *, directory):
        guard = self._guard(path, directory=directory)
        if any(_overlap(guard.identity, private) for private in self._private):
            raise RepositoryLocationError('REPOSITORY_PRIVATE_SCOPE_OVERLAP')
        return guard

    def _directory(self, path):
        return self._source_path(path, directory=True)

    def _probe(self, path, *, optional=False):
        try:
            attributes = path.lstat().st_file_attributes
        except FileNotFoundError:
            if optional:
                self._absent.add(path)
                return None
            raise RepositoryLocationError('REPOSITORY_METADATA_MISSING') from None
        except OSError as error:
            raise RepositoryLocationError(
                'REPOSITORY_METADATA_UNAVAILABLE', getattr(error, 'winerror', None)
            ) from error
        return self._source_path(path, directory=bool(attributes & 0x10))

    def _source(self, path):
        key = str(path)
        guard = self._probe(path)
        if guard.directory:
            raise RepositoryLocationError('REPOSITORY_METADATA_FILE_REQUIRED')
        if key not in self._sources:
            self._reserve(len(path.parts) + 1)
            try:
                self._sources[key] = LockedConfigSource(
                    path, max_file_bytes=self._file_limit, expected_file=guard.identity
                )
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if type(retained) is LockedConfigSource:
                    self._sources[key] = retained
                raise
        return self._sources[key]

    def _require_absent(self, path):
        if self._probe(path, optional=True) is not None:
            raise RepositoryLocationError('REPOSITORY_UNSUPPORTED_METADATA_PRESENT')

    def _pack_listing(self):
        with os.scandir(self._pack.path) as listing:
            names = []
            for entry in listing:
                if len(names) >= self._entry_limit:
                    raise RepositoryLocationError('REPOSITORY_PACK_LIST_LIMIT_EXCEEDED')
                if entry.name.casefold().endswith('.promisor'):
                    raise RepositoryLocationError('REPOSITORY_PROMISOR_PACK_UNSUPPORTED')
                names.append(entry.name)
        return tuple(sorted(names))

    def verify(self):
        with self._gate:
            if self._closing:
                raise RepositoryLocationError('REPOSITORY_LOCATION_CLOSED')
            for guard in self._paths.values():
                self._attributes(guard)
            for source in self._sources.values():
                source.verify()
            for path in self._absent:
                try:
                    path.lstat()
                except FileNotFoundError:
                    continue
                raise RepositoryLocationError('REPOSITORY_METADATA_ABSENCE_CHANGED', changed=True)
            if self._pack_names is not None and self._pack_listing() != self._pack_names:
                raise RepositoryLocationError('REPOSITORY_PACK_LIST_CHANGED', changed=True)
            return self._facts

    def require_disjoint_directory(self, directory):
        facts = self.verify()
        if (
            type(directory) is not FileIdentity
            or not directory.is_directory
            or any(
                _overlap(source, directory)
                for source in (facts.root, facts.git_directory, facts.common_directory)
            )
        ):
            raise RepositoryLocationError('REPOSITORY_PRIVATE_SCOPE_OVERLAP')

    @property
    def config_source(self):
        self.verify()
        return self._config

    @contextmanager
    def hold(self):
        with self._gate:
            facts = self.verify()
            self._users += 1
        try:
            yield facts
        finally:
            with self._gate:
                self._users -= 1
                self.verify()

    def close(self):
        with self._gate:
            if self._users:
                raise RepositoryLocationError('REPOSITORY_LOCATION_IN_USE')
            self._closing = True
            for key, source in tuple(self._sources.items()):
                try:
                    source.close()
                except BaseException as error:
                    error.retained_owner = self
                    raise
                del self._sources[key]
            for key, guard in reversed(tuple(self._paths.items())):
                try:
                    guard.close()
                except BaseException as error:
                    error.retained_owner = self
                    raise
                del self._paths[key]

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
