"""Delete only pinned entries within the original stopped TASK runtime root."""

import ctypes
import hashlib
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import get_ident

from .guard_task_files import _publish_original, _read_original
from .runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from .windows_config_copy import _api, _Disposition
from .windows_local_paths import FileIdentity, LocalPathGuard, _identity, local_absolute_path
from .windows_task_directories import TASK_ROLES, TaskLpacDirectories
from .windows_task_native_launch import TaskNativeLaunch

_MAX_ENTRIES = 100_000
_MAX_DEPTH = 64
_RECORD_BYTES = 4096
_DELETE = 0x10000
_READ_ATTRIBUTES = 0x80
_SHARE_READ = 1
_OPEN_EXISTING = 3
_OPEN_REPARSE_POINT_AND_BACKUP_SEMANTICS = 0x00200000 | 0x02000000
_FILE_DISPOSITION_INFO = 4


class TaskDirectoryReleaseError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class OwnedTreeEntry:
    file: FileIdentity
    parent: FileIdentity


class OwnedTreeDeletion:
    """Pin each parent and delete the exact enumerated NTFS object by handle."""

    def __init__(self, parent_identity):
        self.parent_identity = parent_identity
        self._kernel = _api()
        self._handle = None
        self._pending = None
        self._marked = False

    @staticmethod
    def path(identity):
        return local_absolute_path(identity.canonical_path)

    def inventory(self, root, checkpoint, *, children=None):
        root_path = self.path(root)
        if root_path.parent != self.path(self.parent_identity):
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_ROOT_DIFFERS')
        entries = []
        seen = {(root.volume_serial, root.file_id)}

        def collect(parent, depth):
            if depth > _MAX_DEPTH:
                raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_LIMIT')
            path = self.path(parent)
            with LocalPathGuard(path, directory=True) as held, os.scandir(path) as items:
                if held.verify() != parent:
                    raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_TREE_DIFFERS')
                names = set()
                for item in items:
                    checkpoint()
                    if len(seen) >= _MAX_ENTRIES:
                        raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_LIMIT')
                    target = path / item.name
                    if target.parent != path or not target.is_relative_to(root_path):
                        raise TaskDirectoryReleaseError(
                            'ORIGINAL_TASK_DIRECTORY_RELEASE_TREE_DIFFERS'
                        )
                    with LocalPathGuard(
                        target, directory=item.is_dir(follow_symlinks=False)
                    ) as member:
                        identity = member.verify()
                    name = item.name.casefold()
                    key = (identity.volume_serial, identity.file_id)
                    if (
                        key in seen
                        or identity.volume_serial != root.volume_serial
                        or name in names
                        or (
                            depth == 0
                            and children is not None
                            and children.get(item.name) != identity
                        )
                    ):
                        raise TaskDirectoryReleaseError(
                            'ORIGINAL_TASK_DIRECTORY_RELEASE_TREE_DIFFERS'
                        )
                    names.add(name)
                    seen.add(key)
                    if identity.is_directory:
                        collect(identity, depth + 1)
                    entries.append(OwnedTreeEntry(identity, parent))
                if depth == 0 and children is not None and names != set(children):
                    raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_TREE_DIFFERS')
                if held.verify() != parent:
                    raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_TREE_DIFFERS')

        collect(root, 0)
        entries.append(OwnedTreeEntry(root, self.parent_identity))
        return tuple(entries)

    def _close_handle(self):
        if self._handle is not None:
            if not self._kernel.CloseHandle(self._handle):
                raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_CLOSE_UNKNOWN')
            self._handle = None

    def is_pending(self, entry):
        return self._pending == entry

    def close(self):
        self._close_handle()

    def delete(self, entry, checkpoint):
        if self._pending is not None and not self.is_pending(entry):
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_ENTRY_IN_FLIGHT')
        path, parent = self.path(entry.file), self.path(entry.parent)
        if path.parent != parent:
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_PARENT_DIFFERS')
        with LocalPathGuard(parent, directory=True) as held:
            if held.verify() != entry.parent:
                raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_PARENT_DIFFERS')
            if not self._marked:
                checkpoint()
                if self._handle is None:
                    handle = self._kernel.CreateFileW(
                        '\\\\?\\' + str(path),
                        _DELETE | _READ_ATTRIBUTES,
                        _SHARE_READ,
                        None,
                        _OPEN_EXISTING,
                        _OPEN_REPARSE_POINT_AND_BACKUP_SEMANTICS,
                        None,
                    )
                    if not handle or handle == ctypes.c_void_p(-1).value:
                        raise TaskDirectoryReleaseError(
                            'ORIGINAL_TASK_DIRECTORY_RELEASE_OPEN_UNKNOWN'
                        )
                    self._handle = handle
                    self._pending = entry
                try:
                    if _identity(self._kernel, self._handle, path) != entry.file:
                        raise TaskDirectoryReleaseError(
                            'ORIGINAL_TASK_DIRECTORY_RELEASE_FILE_DIFFERS'
                        )
                    if entry.file.is_directory:
                        with os.scandir(path) as children:
                            if next(children, None) is not None:
                                raise TaskDirectoryReleaseError(
                                    'ORIGINAL_TASK_DIRECTORY_RELEASE_NOT_EMPTY'
                                )
                    checkpoint()
                    disposition = _Disposition(1)
                    if not self._kernel.SetFileInformationByHandle(
                        self._handle,
                        _FILE_DISPOSITION_INFO,
                        ctypes.byref(disposition),
                        ctypes.sizeof(disposition),
                    ):
                        raise TaskDirectoryReleaseError(
                            'ORIGINAL_TASK_DIRECTORY_RELEASE_MARK_UNKNOWN'
                        )
                except BaseException:
                    self._close_handle()
                    self._pending = None
                    raise
                self._marked = True
            self._close_handle()
            try:
                path.lstat()
            except FileNotFoundError:
                if held.verify() != entry.parent:
                    raise TaskDirectoryReleaseError(
                        'ORIGINAL_TASK_DIRECTORY_RELEASE_PARENT_DIFFERS'
                    )
                self._marked = False
                self._pending = None
                return
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_ABSENCE_UNKNOWN')


class TaskDirectoryRelease:
    """Observe, journal, and remove an original plan without sweeping other paths."""

    def __init__(self, directories, native):
        if (
            type(directories) is not TaskLpacDirectories
            or type(native) is not TaskNativeLaunch
            or native._dirs is not directories
        ):
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_OWNER_REQUIRED')
        self._directories, self._native = directories, native
        self._parent, self._parent_identity = directories._parent, directories._parent_identity
        self._scope = directories.scope
        self._package = directories._actions._journal._package
        self._thread = get_ident()
        self._deletion = OwnedTreeDeletion(self._parent_identity)
        self._plan = self._intent = self._result = None
        self._content_closed = False
        self._index = 0

    def _read(self, suffix):
        return _read_original(
            self._package,
            self._scope.key + '.task-directory-release-' + suffix + '.json',
            _RECORD_BYTES,
        )

    def _write(self, suffix, raw):
        if self._read(suffix) is None:
            _publish_original(
                self._package,
                self._scope.key + '.task-directory-release-' + suffix + '.json',
                raw,
                _RECORD_BYTES,
            )
        if self._read(suffix) != raw:
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_RECEIPT_DIFFERS')

    def _check_parent(self):
        if get_ident() != self._thread or self._parent.verify() != self._parent_identity:
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_PARENT_DIFFERS')

    def _inventory(self, checkpoint, stop_ref):
        known = {row.role: row.file for row in self._directories.verify()}
        if set(known) != set(TASK_ROLES):
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_ROOT_DIFFERS')
        root = known.pop('root')
        if self._deletion.path(root) != self._directories.root:
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_ROOT_DIFFERS')
        entries = self._deletion.inventory(root, checkpoint, children=known)
        digest = hashlib.sha256()
        for entry in entries:
            digest.update(_bytes(asdict(entry)))
        intent = _bytes(
            {
                'schema_version': 1,
                'scope': self._scope.key,
                'binding_ref': self._directories.binding_ref,
                'native_stop_ref': stop_ref,
                'root': asdict(root),
                'entry_count': len(entries),
                'plan_sha256': digest.hexdigest(),
            }
        )
        return tuple(entries), intent

    def release(self, checkpoint):
        self._check_parent()
        stop_ref = self._native.stopped_evidence()
        if self._result is not None:
            return self.verify()
        try:
            if self._plan is None:
                if self._read('intent') is not None or self._read('ack') is not None:
                    raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_PLAN_UNKNOWN')
                self._plan, self._intent = self._inventory(checkpoint, stop_ref)
            self._write('intent', self._intent)
            if not self._content_closed:
                self._directories.close_content()
                self._content_closed = True
            while self._index < len(self._plan):
                self._check_parent()
                self._deletion.delete(self._plan[self._index], checkpoint)
                self._index += 1
            self._native.stopped_evidence()
            self._result = _bytes(
                {
                    'schema_version': 1,
                    'scope': self._scope.key,
                    'intent_sha256': hashlib.sha256(self._intent).hexdigest(),
                    'removed_entries': len(self._plan),
                }
            )
            self._write('ack', self._result)
            return self.verify()
        except BaseException as error:
            if getattr(error, 'retained_owner', None) is None:
                error.retained_owner = self
            raise

    def verify(self):
        self._check_parent()
        if (
            self._result is None
            or self._read('intent') != self._intent
            or self._read('ack') != self._result
            or self._index != len(self._plan)
        ):
            raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_UNVERIFIED')
        try:
            Path(self._directories.root).lstat()
        except FileNotFoundError:
            self._check_parent()
            self._native.stopped_evidence()
            return hashlib.sha256(self._result).hexdigest()
        raise TaskDirectoryReleaseError('ORIGINAL_TASK_DIRECTORY_RELEASE_ABSENCE_UNKNOWN')
