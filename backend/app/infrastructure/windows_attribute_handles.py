"""Duplicate and verify original NTFS attribute-only handles."""

import ctypes
from ctypes import wintypes
from threading import RLock

from .windows_controller_token import ControllerPrimaryToken
from .windows_local_paths import PathBoundaryError, local_absolute_path
from .windows_local_paths import _api as path_api
from .windows_local_paths import _identity as file_identity
from .windows_process import _identity as process_identity
from .windows_stdio import ObjectBasicInformation, _handle
from .windows_stdio import _api as duplicate_api

FILE_READ_ATTRIBUTES = 0x80
SYNCHRONIZE = 0x100000


class GuardAttributeHandles:
    """Retain the exact objects without reopening caller-supplied paths."""

    def __init__(self, controller, owner, entries, *, error_type, error_prefix):
        self._error_type, self._error_prefix = error_type, error_prefix
        if type(controller) is not ControllerPrimaryToken or owner != controller._expected:
            raise self._error('SCOPE_DIFFERS')
        self._controller, self._entries = controller, dict(entries)
        self._kernel, security, self._native = duplicate_api()
        self._paths = path_api()
        self._gate = RLock()
        self._closing = False
        self._process = None
        self._handles = {}
        try:
            with controller.creation_handle():
                self._process = self._kernel.OpenProcess(0x40 | 0x1000 | 0x100000, False, owner.pid)
                if not self._process:
                    raise self._error('PROCESS_UNAVAILABLE', ctypes.get_last_error())
                if process_identity(self._kernel, security, self._process, owner.pid) != owner:
                    raise self._error('PROCESS_DIFFERS')
                for role, (_, source) in self._entries.items():
                    self._duplicate(role, source)
                self._verify_handles()
                if not self._kernel.CloseHandle(self._process):
                    raise self._error('PROCESS_CLOSE_UNVERIFIED', ctypes.get_last_error())
                self._process = None
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from error
            raise

    def _error(self, code, native_error=None):
        return self._error_type(self._error_prefix + '_' + code, native_error)

    def _duplicate(self, role, source):
        target = wintypes.HANDLE()
        if not self._kernel.DuplicateHandle(
            self._process,
            _handle(source),
            self._kernel.GetCurrentProcess(),
            ctypes.byref(target),
            0,
            False,
            2,
        ):
            raise self._error('DUPLICATE_UNVERIFIED', ctypes.get_last_error())
        self._handles[role] = target.value

    def _verify_handles(self):
        if self._closing or set(self._handles) != set(self._entries):
            raise self._error('COHORT_CLOSED')
        for role, handle in self._handles.items():
            information = ObjectBasicInformation()
            returned = wintypes.ULONG()
            status = self._native.NtQueryObject(
                handle,
                0,
                ctypes.byref(information),
                ctypes.sizeof(information),
                ctypes.byref(returned),
            )
            if (
                status != 0
                or returned.value != ctypes.sizeof(information)
                or information.granted_access
                not in (FILE_READ_ATTRIBUTES, FILE_READ_ATTRIBUTES | SYNCHRONIZE)
            ):
                raise self._error('READ_ATTRIBUTES_REQUIRED')
            flags = wintypes.DWORD()
            if (
                not self._kernel.GetHandleInformation(handle, ctypes.byref(flags))
                or flags.value & 1
                or self._kernel.GetFileType(handle) != 1
            ):
                raise self._error('HANDLE_TYPE_OR_INHERITANCE_UNVERIFIED')
            expected = self._entries[role][0]
            try:
                actual = file_identity(
                    self._paths, handle, local_absolute_path(expected.canonical_path)
                )
            except PathBoundaryError as error:
                raise self._error('DIFFERS') from error
            if actual != expected:
                raise self._error('DIFFERS')

    def verify(self):
        with self._gate, self._controller.creation_handle():
            self._verify_handles()

    def close(self):
        with self._gate:
            self._closing = True
            errors = []
            for role, handle in reversed(tuple(self._handles.items())):
                if self._kernel.CloseHandle(handle):
                    del self._handles[role]
                else:
                    errors.append(ctypes.get_last_error())
            if self._process is not None:
                if self._kernel.CloseHandle(self._process):
                    self._process = None
                else:
                    errors.append(ctypes.get_last_error())
            if errors:
                error = self._error('CLOSE_UNVERIFIED', errors[0])
                error.retained_owner = self
                raise error

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, traceback):
        self.close()
