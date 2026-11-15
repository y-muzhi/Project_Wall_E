"""Observe one original TASK tree from actual directory identities and file bytes."""

import hashlib
import os
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from time import monotonic

from .content_manifest import ContentLimits
from .content_paths import ContentPathEntry, ContentPathError, ContentPathIndex
from .content_secret_policy import SecretPolicy
from .content_selection import ContentSelection
from .git_fixed_content import reject_lfs_pointer
from .runtime_launch_journal import _bytes
from .windows_config_source import ConfigReadError, LockedFileSource
from .windows_file_streams import FileStreamError, require_default_data_stream
from .windows_local_paths import (
    FileIdentity,
    LocalPathGuard,
    PathBoundaryError,
    local_absolute_path,
)
from .windows_task_workspace_lease import WorkspaceWriteError

_MAX_ENTRIES = 16384
_MAX_LAUNCH_HANDLES = 4096
_MAX_TREE_BYTES = 2 * 1024**3


def workspace_tree_sha256(files, directories):
    digest = hashlib.sha256(b'WALL-E-TASK-TREE-2\n')
    for path, identity in sorted(directories.items()):
        digest.update(_bytes(['directory', path, identity.volume_serial, identity.file_id]))
    for path, (identity, size, sha256) in sorted(files.items()):
        digest.update(
            _bytes(['file', path, identity.volume_serial, identity.file_id, size, sha256])
        )
    return digest.hexdigest()


def _verify_streams(kernel, handle, *, directory):
    try:
        require_default_data_stream(kernel, handle, directory=directory)
    except FileStreamError as error:
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_' + str(error)) from error


@dataclass(frozen=True)
class CandidateWorkspaceLimits:
    content: ContentLimits
    max_entries: int
    max_handles: int
    max_seconds: int

    def __post_init__(self):
        if (
            type(self.content) is not ContentLimits
            or type(self.max_entries) is not int
            or not 1 <= self.max_entries <= _MAX_ENTRIES
            or type(self.max_handles) is not int
            or not 1 <= self.max_handles <= _MAX_LAUNCH_HANDLES
            or type(self.max_seconds) is not int
            or not 1 <= self.max_seconds <= 300
        ):
            raise ValueError('Candidate workspace limits are outside the admitted range')


@dataclass(frozen=True)
class CandidateWorkspaceEntry:
    path: str
    mode: str
    byte_count: int
    sha256: str


class CandidateWorkspaceError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _CandidateScan:
    selection: ContentSelection
    secret_policy: SecretPolicy
    limits: CandidateWorkspaceLimits


def _scan_task_workspace_tree(
    path,
    original,
    checkpoint,
    custody=None,
    candidate=None,
    *,
    namespace=None,
    launch_handle_limit=None,
):
    handles = 0
    file_sources = {}
    modes = {}
    if candidate is None:
        entry_limit, handle_limit = _MAX_ENTRIES, _MAX_LAUNCH_HANDLES
        if launch_handle_limit is not None:
            if type(launch_handle_limit) is not int or not 1 <= launch_handle_limit <= 32768:
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_LAUNCH_HANDLE_LIMIT_INVALID')
            handle_limit = launch_handle_limit
        file_limit, file_bytes, tree_limit = _MAX_ENTRIES, _MAX_TREE_BYTES, _MAX_TREE_BYTES
    else:
        limits = candidate.limits
        entry_limit, handle_limit = limits.max_entries, limits.max_handles
        file_limit = limits.content.max_snapshot_files
        file_bytes = limits.content.max_file_bytes
        tree_limit = limits.content.max_snapshot_bytes

    def hold(factory, handle_count):
        nonlocal handles
        if custody is None:
            return factory()
        handles += handle_count
        if handles > handle_limit:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_LAUNCH_HANDLE_LIMIT_EXCEEDED')
        return nullcontext(custody.enter_context(factory()))

    if namespace is None:
        namespace = ContentPathIndex(materialization_root=path)
    pending = [('', path, original)]
    files, directories = {}, {}
    count = total = 0
    while pending:
        prefix, directory, expected = pending.pop()
        checkpoint()
        with (
            hold(
                lambda directory=directory: LocalPathGuard(directory, directory=True),
                len(directory.parts),
            ) as held,
            os.scandir(directory) as listing,
        ):
            if held.verify() != expected:
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_TREE_DIRECTORY_DIFFERS')
            _verify_streams(held._kernel, held._held[-1][0], directory=True)
            for child in listing:
                checkpoint()
                count += 1
                if count > entry_limit:
                    raise WorkspaceWriteError('ORIGINAL_WORKSPACE_TREE_LIMIT_EXCEEDED')
                name = prefix + child.name
                is_directory = child.is_dir(follow_symlinks=False)
                if is_directory:
                    namespace.add_directory(name)
                    if candidate is not None and candidate.selection.prune_directory(name):
                        continue
                    with LocalPathGuard(child.path, directory=True) as member:
                        identity = member.verify()
                    directories[name] = identity
                    pending.append((name + '/', path / name, identity))
                    continue

                if candidate is None:
                    mode = '100644'
                else:
                    selected = candidate.selection.file(name)
                    if selected is None:
                        # Names still participate in the namespace check. Excluded
                        # content is not opened or followed.
                        namespace.add_file(name, '100644')
                        continue
                    mode = selected.mode
                    candidate.secret_policy.check_path(name)
                namespace.add_file(name, mode)
                if len(files) >= file_limit:
                    raise WorkspaceWriteError('ORIGINAL_WORKSPACE_TREE_LIMIT_EXCEEDED')
                byte_limit = min(file_bytes, max(1, tree_limit - total))

                @contextmanager
                def locked_file(child_path=child.path, limit=byte_limit):
                    # Construction has already read and checked every byte while
                    # the original data handle denies writes and replacement.
                    source = LockedFileSource(
                        child_path,
                        max_file_bytes=limit,
                        capture_raw=False,
                        checkpoint=checkpoint,
                    )
                    try:
                        yield source
                    finally:
                        source.close()

                with hold(locked_file, len((path / name).parts) + 1) as source:
                    blob = source.snapshot
                    _verify_streams(source._kernel, source._handle, directory=False)
                    total += blob.byte_count
                    if total > tree_limit:
                        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_TREE_LIMIT_EXCEEDED')
                    files[name] = blob.file, blob.byte_count, blob.sha256
                    modes[name] = mode
                    if custody is not None and candidate is not None:
                        file_sources[name] = source
    checkpoint()
    return files, directories, modes, file_sources


def observe_task_workspace_tree(path, original, checkpoint):
    files, directories, _, _ = _scan_task_workspace_tree(path, original, checkpoint)
    return workspace_tree_sha256(files, directories)


@contextmanager
def hold_task_workspace_tree(
    path, original, expected_sha256, checkpoint, *, launch_handle_limit=None
):
    with ExitStack() as custody:
        files, directories, _, _ = _scan_task_workspace_tree(
            path, original, checkpoint, custody, launch_handle_limit=launch_handle_limit
        )
        digest = workspace_tree_sha256(files, directories)
        if digest != expected_sha256:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_LAUNCH_TREE_DIFFERS')
        try:
            yield digest
        finally:
            if observe_task_workspace_tree(path, original, checkpoint) != digest:
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_LAUNCH_TREE_DIFFERS')


class LockedCandidateWorkspace:
    """Only the bytes from the original, retained NTFS file handles."""

    def __init__(self, path, original, checkpoint, scan, custody):
        self._path, self._original, self._checkpoint, self._scan = path, original, checkpoint, scan
        self._namespace = ContentPathIndex(materialization_root=path)
        self._files, self._directories, self._modes, self._readers = _scan_task_workspace_tree(
            path, original, checkpoint, custody, scan, namespace=self._namespace
        )
        self._entries = {
            name: CandidateWorkspaceEntry(name, self._modes[name], size, digest)
            for name, (_, size, digest) in self._files.items()
        }
        self.entries = tuple(
            self._entries[name] for name in sorted(self._entries, key=lambda name: name.encode())
        )
        self._closed = False
        self._capture_complete = False
        self._checked = set()

    def file_identity(self, entry):
        if self._closed or self._entries.get(entry.path) != entry:
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        return self._files[entry.path][0]

    def plan_retained_files(self, entries):
        if self._closed or any(self._entries.get(entry.path) != entry for entry in entries):
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        self._namespace = self._namespace.without_files(
            [ContentPathEntry(entry.path, entry.mode) for entry in entries]
        )

    def plan_missing_file(self, relative, mode):
        """Reserve a missing name against the exact observed NTFS namespace."""
        if self._closed:
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        try:
            entry = self._namespace.add_file(relative, mode)
        except ContentPathError as error:
            raise CandidateWorkspaceError('SOURCE_CHANGED') from error
        parts = entry.path.split('/')
        ancestors = {'': self._original}
        for count in range(1, len(parts)):
            path = '/'.join(parts[:count])
            ancestors[path] = self._directories.get(path)
        return ancestors

    def read(self, entry):
        if (
            self._closed
            or self._capture_complete
            or type(entry) is not CandidateWorkspaceEntry
            or self._entries.get(entry.path) != entry
        ):
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        self._checkpoint()
        raw = self._readers[entry.path].verified_raw()
        reject_lfs_pointer(raw)
        self._scan.secret_policy.check_bytes(entry.path, raw)
        self._checkpoint()
        self._checked.add(entry.path)
        return raw

    def verify(self):
        if self._closed:
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        if self._checked != self._entries.keys():
            raise CandidateWorkspaceError('CONTENT_NOT_READY')
        files, directories, modes, _ = _scan_task_workspace_tree(
            self._path, self._original, self._checkpoint, candidate=self._scan
        )
        if (files, directories, modes) != (self._files, self._directories, self._modes):
            raise CandidateWorkspaceError('SOURCE_CHANGED')
        for source in self._readers.values():
            self._checkpoint()
            source.verify()
        self._checkpoint()

    def finish_capture(self):
        """Fix the final inventory immediately before the caller seals the package."""
        if self._capture_complete:
            raise CandidateWorkspaceError('CONTENT_NOT_READY')
        self.verify()
        self._capture_complete = True


@contextmanager
def hold_candidate_workspace(
    path,
    original,
    *,
    selection,
    secret_policy,
    limits,
    quiescent,
    started_at,
):
    """Keep actual selected source locked until the caller finishes sealing."""
    if (
        type(original) is not FileIdentity
        or not original.is_directory
        or type(selection) is not ContentSelection
        or type(secret_policy) is not SecretPolicy
        or type(limits) is not CandidateWorkspaceLimits
        or not callable(quiescent)
    ):
        raise CandidateWorkspaceError('SOURCE_UNSUPPORTED')
    if type(started_at) not in (float, int) or not 0 <= started_at <= monotonic():
        raise CandidateWorkspaceError('SOURCE_UNSUPPORTED')
    deadline = started_at + limits.max_seconds

    def checkpoint():
        if monotonic() >= deadline:
            raise CandidateWorkspaceError('SOURCE_BUSY')
        if quiescent() is not None:
            raise CandidateWorkspaceError('WRITER_ACTIVE')

    scan = _CandidateScan(selection, secret_policy, limits)
    try:
        with ExitStack() as custody:
            owner = LockedCandidateWorkspace(
                local_absolute_path(path), original, checkpoint, scan, custody
            )
            try:
                yield owner
                if not owner._capture_complete:
                    owner.verify()
            finally:
                owner._closed = True
    except ConfigReadError as error:
        raise CandidateWorkspaceError(error.code) from error
    except (ContentPathError, PathBoundaryError, OSError) as error:
        raise CandidateWorkspaceError('SOURCE_UNSUPPORTED') from error
    except WorkspaceWriteError as error:
        code = 'SOURCE_CHANGED' if str(error).endswith('_DIFFERS') else 'SOURCE_UNSUPPORTED'
        raise CandidateWorkspaceError(code) from error
