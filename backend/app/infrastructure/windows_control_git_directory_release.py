"""Delete only original empty Control Git preparation directories."""

import ctypes
import re
from threading import get_ident

from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_config_copy import _api, _Disposition
from .windows_empty_directory import ReadOnlyEmptyDirectory
from .windows_local_paths import _identity
from .windows_private_package import PrivatePackageGuard


class ControlGitDirectoryReleaseError(LaunchOutcomeUnknown):
    pass


class ControlGitDirectoryRelease:
    def __init__(self, parent, child, *, package_nonce):
        if type(parent) is not PrivatePackageGuard:
            raise TypeError('Original private parent required')
        if type(package_nonce) is not str or re.fullmatch('[0-9a-f]{32}', package_nonce) is None:
            raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_NONCE_REQUIRED')
        name = 'control-git-' + package_nonce
        self._parent_identity = parent.verify()
        if type(child) is PrivatePackageGuard:
            if (
                parent.is_control_git_read_package
                or not child.is_control_git_read_package
                or child.path != parent.path / name
            ):
                raise ControlGitDirectoryReleaseError('ORIGINAL_CONTROL_GIT_PACKAGE_DIFFERS')
            identity = child.verify()
        elif type(child) is ReadOnlyEmptyDirectory:
            if (
                not parent.is_control_git_read_package
                or parent.path.name != name
                or child.path != parent.path / 'hooks'
                or child._reader_sid != parent.reader_sid
            ):
                raise ControlGitDirectoryReleaseError('ORIGINAL_CONTROL_GIT_HOOKS_DIFFERS')
            identity = child.verify().file
        else:
            raise TypeError('Original read package or hooks required')
        self._thread = get_ident()
        self._kernel = _api()
        self._parent = parent
        self._child = child
        self._path = child.path
        self._identity = identity
        self._child_closed = False
        self._handle = None
        self._marked = False
        self._released = False

    def _check_parent(self):
        if self._parent.verify() != self._parent_identity:
            raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_PARENT_DIFFERS')

    def _close_delete_handle(self):
        if not self._kernel.CloseHandle(self._handle):
            raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_DELETE_CLOSE_UNVERIFIED')
        self._handle = None

    def _mark_original_empty_directory(self):
        if self._handle is None:
            handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(self._path),
                0x10000 | 0x80,
                0x1,
                None,
                3,
                0x00200000 | 0x02000000,
                None,
            )
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_DELETE_OPEN_UNVERIFIED')
            self._handle = handle
        try:
            if _identity(self._kernel, self._handle, self._path) != self._identity:
                raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_FILE_ID_DIFFERS')
            self._check_parent()
            disposition = _Disposition(1)
            if not self._kernel.SetFileInformationByHandle(
                self._handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
            ):
                raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_DELETE_UNVERIFIED')
        except BaseException:
            self._close_delete_handle()
            raise
        self._marked = True

    def close(self):
        if get_ident() != self._thread:
            raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_ACTOR_DIFFERS')
        if self._released:
            return
        try:
            self._check_parent()
            if not self._child_closed:
                self._child.close()
                self._child_closed = True
            if not self._marked:
                self._mark_original_empty_directory()
            if self._handle is not None:
                self._close_delete_handle()
            try:
                self._path.lstat()
            except FileNotFoundError:
                self._check_parent()
                self._released = True
                return
            raise ControlGitDirectoryReleaseError('ORIGINAL_DIRECTORY_ABSENCE_UNVERIFIED')
        except BaseException as error:
            error.retained_owner = self
            raise
