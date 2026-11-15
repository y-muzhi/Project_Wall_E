"""Original NTFS worktree/HEAD cohort for GIT20-LOCAL-1.

Internal decoded Git observations are bound to held originals and bidirectional
linked-worktree metadata. This read-only lease is not whole-repository admission,
a Git invocation, delivery authorization or a cross-program repository lock.
"""

import ctypes
import hashlib
import ntpath
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .git_ref_protocol import RefProtocolError, branch_ref
from .git_worktrees import validate_worktree_links
from backend.app.shared.json_canonical import canonical_input
from .windows_config_source import LockedConfigSource
from .windows_executable_pin import UNSUPPORTED_ATTRIBUTES
from .windows_executable_pin import _api as read_api
from .windows_local_paths import (
    FileIdentity,
    HandleInfo,
    LocalPathGuard,
    _identity,
    local_absolute_path,
)


class WorktreeHeadError(RuntimeError):
    def __init__(self, reason, native_error=None, *, code='SOURCE_UNSUPPORTED'):
        self.reason = reason
        self.native_error = native_error
        self.code = 'SOURCE_BUSY' if native_error in (32, 33) else code
        super().__init__(reason)


def metadata_line(raw):
    """One exact UTF-8 line; no whitespace stripping or implicit ref following."""
    if type(raw) is not bytes or not raw or b'\0' in raw:
        raise WorktreeHeadError('WORKTREE_METADATA_LINE_INVALID')
    if raw.endswith(b'\r\n'):
        raw = raw[:-2]
    elif raw.endswith(b'\n'):
        raw = raw[:-1]
    if not raw or b'\n' in raw or b'\r' in raw:
        raise WorktreeHeadError('WORKTREE_METADATA_LINE_INVALID')
    try:
        return raw.decode('utf-8', errors='strict')
    except UnicodeError:
        raise WorktreeHeadError('WORKTREE_METADATA_UTF8_INVALID') from None


def metadata_pointer(raw, *, base_directory, gitfile=False):
    text = metadata_line(raw)
    if type(gitfile) is not bool:
        raise WorktreeHeadError('WORKTREE_POINTER_KIND_INVALID')
    if gitfile:
        if not text.startswith('gitdir: '):
            raise WorktreeHeadError('WORKTREE_GITFILE_PREFIX_INVALID')
        text = text[8:]
    base = local_absolute_path(base_directory)
    if not text:
        raise WorktreeHeadError('WORKTREE_POINTER_EMPTY')
    text = text.replace('/', '\\')
    drive, rest = ntpath.splitdrive(text)
    if drive:
        # Fully qualified drive paths only, never UNC/device/drive-relative.
        return local_absolute_path(text)
    if rest.startswith('\\'):
        raise WorktreeHeadError('WORKTREE_POINTER_ROOT_RELATIVE')
    # Validate components BEFORE collapsing dot segments, so "bad./.." cannot
    # disguise an NTFS alias. Dots are permitted only in these metadata pointers.
    for part in text.split('\\'):
        if not part:
            raise WorktreeHeadError('WORKTREE_POINTER_COMPONENT_EMPTY')
        if part not in ('.', '..'):
            local_absolute_path('C:\\' + part)
    return local_absolute_path(ntpath.normpath(ntpath.join(str(base), text)))


def metadata_head(raw, *, format):
    text = metadata_line(raw)
    if format not in ('sha1', 'sha256'):
        raise WorktreeHeadError('WORKTREE_HEAD_FORMAT_INVALID')
    if text.startswith('ref: '):
        try:
            return 'BRANCH', branch_ref(text[5:])
        except RefProtocolError:
            raise WorktreeHeadError('WORKTREE_HEAD_REF_INVALID') from None
    length = 40 if format == 'sha1' else 64
    if (
        len(text) != length
        or any(char not in '0123456789abcdef' for char in text)
        or set(text) == {'0'}
    ):
        raise WorktreeHeadError('WORKTREE_HEAD_OID_INVALID')
    return 'DETACHED', text


def _key(identity):
    return identity.volume_serial, identity.file_id


def _overlap(left, right):
    left = ntpath.normcase(left.canonical_path)
    right = ntpath.normcase(right.canonical_path)
    try:
        return ntpath.commonpath((left, right)) in (left, right)
    except ValueError:
        return False


@dataclass(frozen=True)
class WorktreeHeadBinding:
    root: FileIdentity = field(repr=False)
    git_directory: FileIdentity = field(repr=False)
    head: FileIdentity = field(repr=False)
    head_sha256: str


class WorktreeHeadLease:
    def __init__(
        self,
        listing,
        branches,
        *,
        common_directory,
        private_roots,
        max_file_bytes,
        max_open_handles,
    ):
        validate_worktree_links(listing, branches)
        for limit in (max_file_bytes, max_open_handles):
            if type(limit) is not int or not 1 <= limit <= MAX_SAFE_INTEGER:
                raise WorktreeHeadError('WORKTREE_LEASE_LIMIT_INVALID')
        if type(private_roots) is not tuple or not private_roots:
            raise WorktreeHeadError('WORKTREE_PRIVATE_SCOPES_REQUIRED')
        common = local_absolute_path(common_directory)
        scopes = tuple(local_absolute_path(path) for path in private_roots)
        self._listing, self._branches = listing, branches
        self._file_limit, self._handle_limit = max_file_bytes, max_open_handles
        self._reserved = 0
        self._gate = RLock()
        self._closing = False
        self._directories = {}
        self._sources = {}
        self._probes = {}
        self._absent = set()
        self._private = ()
        self._bindings = ()
        self._linked = set()
        self._admin_names = ()
        self._admin_directory = None
        self._kernel = read_api()
        try:
            self._private = tuple(self._directory(path).identity for path in scopes)
            self._common = self._source_directory(common)
            bindings = []
            roots = set()
            mains = 0
            for entry in listing.entries:
                root = self._source_directory(local_absolute_path(entry.path))
                if _key(root.identity) in roots:
                    raise WorktreeHeadError('WORKTREE_ROOT_IDENTITY_DUPLICATE')
                roots.add(_key(root.identity))
                gitdir = self._git_directory(entry, root)
                if _key(gitdir.identity) == _key(self._common.identity):
                    mains += 1
                self._require_absent(gitdir.path / 'config.worktree')
                head = self._source(gitdir.path / 'HEAD')
                kind, value = metadata_head(head.snapshot.raw, format=listing.object_format)
                if not entry.bare:
                    expected = (
                        ('BRANCH', entry.branch_ref)
                        if entry.branch_ref is not None
                        else ('DETACHED', entry.head_oid)
                    )
                    if (kind, value) != expected:
                        raise WorktreeHeadError(
                            'WORKTREE_HEAD_OBSERVATION_DIFFERS', code='SOURCE_CHANGED'
                        )
                bindings.append(
                    WorktreeHeadBinding(
                        root.identity, gitdir.identity, head.snapshot.file, head.snapshot.sha256
                    )
                )
            if mains != 1:
                raise WorktreeHeadError('WORKTREE_MAIN_COHORT_INVALID')
            self._bindings = tuple(bindings)
            self._bind_admin_cohort()
            self.verify()
            self._fingerprint = self._digest()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _reserve(self, count):
        if self._reserved + count > self._handle_limit:
            raise WorktreeHeadError('WORKTREE_HANDLE_LIMIT_EXCEEDED')
        self._reserved += count

    def _metadata_identity(self, handle, path):
        identity = _identity(self._kernel, handle, path)
        basic = HandleInfo()
        if not self._kernel.GetFileInformationByHandle(handle, ctypes.byref(basic)):
            raise WorktreeHeadError('WORKTREE_ATTRIBUTES_UNAVAILABLE', ctypes.get_last_error())
        if basic.attributes & (UNSUPPORTED_ATTRIBUTES & ~0x10):
            raise WorktreeHeadError('WORKTREE_METADATA_ATTRIBUTES_UNSUPPORTED')
        return identity

    def _directory(self, path):
        key = str(path)
        if key not in self._directories:
            self._reserve(len(path.parts))
            guard = LocalPathGuard(path, directory=True)
            # Retain the original owner even if entry or cleanup cannot finish.
            self._directories[key] = guard
            guard.__enter__()
            if self._metadata_identity(guard._held[-1][0], path) != guard.identity:
                raise WorktreeHeadError('WORKTREE_METADATA_CHANGED', code='SOURCE_CHANGED')
        return self._directories[key]

    def _source_directory(self, path):
        guard = self._directory(path)
        if any(_overlap(guard.identity, scope) for scope in self._private):
            raise WorktreeHeadError('WORKTREE_PRIVATE_SCOPE_OVERLAP')
        return guard

    def _probe(self, path, *, optional=False):
        key = str(path)
        if key in self._probes:
            return self._probes[key][1]
        self._source_directory(path.parent)
        self._reserve(1)
        handle = self._kernel.CreateFileW(
            '\\\\?\\' + key, 0x80, 0x1 | 0x2, None, 3, 0x00200000 | 0x02000000, None
        )
        if handle == ctypes.c_void_p(-1).value or not handle:
            error = ctypes.get_last_error()
            self._reserved -= 1
            if optional and error == 2:
                return None
            raise WorktreeHeadError('WORKTREE_METADATA_UNAVAILABLE', error)
        self._probes[key] = (handle, None, path)
        identity = self._metadata_identity(handle, path)
        self._probes[key] = (handle, identity, path)
        return identity

    def _require_absent(self, path):
        if self._probe(path, optional=True) is not None:
            raise WorktreeHeadError('WORKTREE_UNSUPPORTED_METADATA_PRESENT')
        self._absent.add(str(path))

    def _source(self, path, *, expected_file=None):
        key = str(path)
        self._source_directory(path.parent)
        if key not in self._sources:
            self._reserve(len(path.parts) + 1)
            try:
                self._sources[key] = LockedConfigSource(
                    path, max_file_bytes=self._file_limit, expected_file=expected_file
                )
            except BaseException as error:
                owner = getattr(error, 'retained_owner', None)
                if isinstance(owner, LockedConfigSource):
                    self._sources[key] = owner
                raise
        source = self._sources[key]
        if expected_file is not None and source.snapshot.file != expected_file:
            raise WorktreeHeadError('WORKTREE_ORIGINAL_FILE_DIFFERS', code='SOURCE_CHANGED')
        return source

    def _git_directory(self, entry, root):
        if entry.bare:
            if _key(root.identity) != _key(self._common.identity):
                raise WorktreeHeadError('WORKTREE_BARE_COMMON_DIFFERS')
            self._require_absent(root.path / 'commondir')
            return root
        gitfile = root.path / '.git'
        original = self._probe(gitfile)
        if original.is_directory:
            gitdir = self._source_directory(gitfile)
            if _key(gitdir.identity) != _key(self._common.identity):
                raise WorktreeHeadError('WORKTREE_MAIN_COMMON_DIFFERS')
            self._require_absent(gitdir.path / 'commondir')
            return gitdir
        source = self._source(gitfile, expected_file=original)
        target = metadata_pointer(source.snapshot.raw, base_directory=root.path, gitfile=True)
        gitdir = self._source_directory(target)
        if _key(gitdir.identity) == _key(self._common.identity):
            self._require_absent(gitdir.path / 'commondir')
            return gitdir
        admin = self._source_directory(self._common.path / 'worktrees')
        parent = self._source_directory(gitdir.path.parent)
        if _key(parent.identity) != _key(admin.identity):
            raise WorktreeHeadError('WORKTREE_LINKED_ADMIN_LOCATION_INVALID')
        common = self._source(gitdir.path / 'commondir')
        actual_common = self._source_directory(
            metadata_pointer(common.snapshot.raw, base_directory=gitdir.path)
        )
        if _key(actual_common.identity) != _key(self._common.identity):
            raise WorktreeHeadError('WORKTREE_LINKED_COMMON_DIFFERS')
        backlink = self._source(gitdir.path / 'gitdir')
        backlink_path = metadata_pointer(backlink.snapshot.raw, base_directory=gitdir.path)
        if self._probe(backlink_path) != original:
            raise WorktreeHeadError('WORKTREE_BACKLINK_DIFFERS')
        identity = _key(gitdir.identity)
        if identity in self._linked:
            raise WorktreeHeadError('WORKTREE_LINKED_ADMIN_DUPLICATE')
        self._linked.add(identity)
        return gitdir

    def _admin_children(self):
        if self._admin_directory is None:
            return ()
        # Directory enumeration has its own bounded lifetime and reservation.
        self._reserve(1)
        names = []
        try:
            with os.scandir(self._admin_directory.path) as entries:
                for entry in entries:
                    if len(names) >= self._handle_limit:
                        raise WorktreeHeadError('WORKTREE_ADMIN_COUNT_EXCEEDED')
                    names.append(entry.name)
        finally:
            self._reserved -= 1
        return tuple(sorted(names, key=lambda name: name.encode('utf-8')))

    def _bind_admin_cohort(self):
        path = self._common.path / 'worktrees'
        original = self._probe(path, optional=True)
        if original is None:
            if self._linked:
                raise WorktreeHeadError('WORKTREE_LINKED_ADMIN_MISSING')
            self._absent.add(str(path))
            return
        if not original.is_directory:
            raise WorktreeHeadError('WORKTREE_ADMIN_NOT_DIRECTORY')
        self._admin_directory = self._source_directory(path)
        names = self._admin_children()
        identities = set()
        for name in names:
            actual = self._source_directory(local_absolute_path(path / name)).identity
            identities.add(_key(actual))
        if identities != self._linked or len(identities) != len(names):
            raise WorktreeHeadError('WORKTREE_ADMIN_COHORT_DIFFERS', code='SOURCE_CHANGED')
        self._admin_names = names

    def _digest(self):
        facts = {
            'listing_sha256': self._listing.listing_sha256,
            'branches': [asdict(branch) for branch in self._branches],
            'bindings': [asdict(binding) for binding in self._bindings],
            'sources': [
                {'file': asdict(source.snapshot.file), 'sha256': source.snapshot.sha256}
                for _, source in sorted(self._sources.items())
            ],
        }
        return hashlib.sha256(canonical_input(facts).encode('utf-8')).hexdigest()

    @property
    def fingerprint_sha256(self):
        return self._fingerprint

    def verify(self):
        with self._gate:
            if self._closing:
                raise WorktreeHeadError('WORKTREE_LEASE_CLOSED')
            for guard in self._directories.values():
                original = guard.verify()
                if self._metadata_identity(guard._held[-1][0], guard.path) != original:
                    raise WorktreeHeadError('WORKTREE_METADATA_CHANGED', code='SOURCE_CHANGED')
            for handle, expected, path in self._probes.values():
                if self._metadata_identity(handle, path) != expected:
                    raise WorktreeHeadError('WORKTREE_METADATA_CHANGED', code='SOURCE_CHANGED')
            for source in self._sources.values():
                source.verify()
            for path in tuple(self._absent):
                if self._probe(Path(path), optional=True) is not None:
                    raise WorktreeHeadError('WORKTREE_ABSENCE_CHANGED', code='SOURCE_CHANGED')
            if self._admin_children() != self._admin_names:
                raise WorktreeHeadError('WORKTREE_ADMIN_COHORT_CHANGED', code='SOURCE_CHANGED')
            return self._bindings

    def verify_observation(self, listing, branches):
        with self._gate:
            validate_worktree_links(listing, branches)
            self.verify()
            if listing != self._listing or branches != self._branches:
                raise WorktreeHeadError('WORKTREE_GIT_OBSERVATION_CHANGED', code='SOURCE_CHANGED')
            return self.fingerprint_sha256

    def close(self):
        with self._gate:
            self._closing = True
            # Never release ancestors after an uncertain data/probe close.
            for key, source in tuple(self._sources.items()):
                try:
                    source.close()
                except BaseException as error:
                    error.retained_owner = self
                    raise
                del self._sources[key]
            for key, (handle, _, _) in tuple(self._probes.items()):
                if not self._kernel.CloseHandle(handle):
                    error = WorktreeHeadError('WORKTREE_CLOSE_UNVERIFIED', ctypes.get_last_error())
                    error.retained_owner = self
                    raise error
                del self._probes[key]
            for key, guard in reversed(tuple(self._directories.items())):
                try:
                    guard.close()
                except BaseException as error:
                    error.retained_owner = self
                    raise
                del self._directories[key]

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
