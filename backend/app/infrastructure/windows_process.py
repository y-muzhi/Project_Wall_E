"""Read-only held process identities for the Runtime Guard.

No process is started, signaled, elevated, impersonated or terminated here.
A PID/path/exit code alone never proves identity or process-tree completion.
"""

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from threading import RLock

from .windows_private_package import _api as _security_api
from .windows_private_package import _sid_text

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
TOKEN_QUERY = 0x8


class ProcessObservationError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


@dataclass(frozen=True)
class NativeProcessIdentity:
    pid: int
    creation_time_hex: str
    image_path: str
    user_sid: str
    appcontainer_sid: str | None
    is_appcontainer: bool
    is_lpac: bool | None
    is_elevated: bool


@dataclass(frozen=True)
class NativeProcessObservation:
    identity: NativeProcessIdentity
    state: str
    exit_code: int | None


def _error(code):
    return ProcessObservationError(code, ctypes.get_last_error())


def _api():
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise ProcessObservationError('WINDOWS_X64_PROCESS_API_REQUIRED')
    kernel, security = _security_api()
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    return kernel, security


def _token_buffer(security, token, kind):
    size = wintypes.DWORD()
    if (
        security.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
        or ctypes.get_last_error() != 122
        or not 4 <= size.value <= 65536
    ):
        raise _error('PROCESS_TOKEN_INFORMATION_UNAVAILABLE')
    value = ctypes.create_string_buffer(size.value)
    if not security.GetTokenInformation(token, kind, value, len(value), ctypes.byref(size)):
        raise _error('PROCESS_TOKEN_INFORMATION_UNAVAILABLE')
    if size.value > len(value):
        raise ProcessObservationError('PROCESS_TOKEN_INFORMATION_SIZE_INVALID')
    return value, size.value


def _token_flag(security, token, kind, *, allow_unsupported=False):
    # Fixed DWORD classes can return ERROR_BAD_LENGTH instead of the variable
    # buffer convention. Query their known shape directly and verify its size.
    value = wintypes.DWORD()
    size = wintypes.DWORD()
    if not security.GetTokenInformation(
        token, kind, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)
    ):
        native_error = ctypes.get_last_error()
        if allow_unsupported and kind == 46 and native_error == 87 and size.value == 0:
            # An enum in an SDK is not proof this kernel implements its query.
            # Unknown MUST NOT qualify as a verified LPAC execution identity.
            return None
        raise ProcessObservationError('PROCESS_TOKEN_INFORMATION_UNAVAILABLE', native_error)
    if size.value != ctypes.sizeof(value):
        raise ProcessObservationError('PROCESS_TOKEN_FLAG_SIZE_INVALID')
    if value.value not in (0, 1):
        raise ProcessObservationError('PROCESS_TOKEN_FLAG_INVALID')
    return bool(value.value)


def _creation_time(kernel, handle):
    creation, exited, system, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exited),
        ctypes.byref(system),
        ctypes.byref(user),
    ):
        raise _error('PROCESS_CREATION_TIME_UNAVAILABLE')
    value = creation.dwHighDateTime << 32 | creation.dwLowDateTime
    if value == 0:
        raise ProcessObservationError('PROCESS_CREATION_TIME_INVALID')
    return f'{value:016x}'


def _image_path(kernel, handle):
    text = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(text))
    if not kernel.QueryFullProcessImageNameW(
        handle, 0, text, ctypes.byref(size)
    ) or not 1 <= size.value < len(text):
        raise _error('PROCESS_IMAGE_UNAVAILABLE')
    result = text.value
    try:
        result.encode('utf-8', errors='strict')
    except UnicodeError:
        raise ProcessObservationError('PROCESS_IMAGE_UNICODE_INVALID') from None
    return result


def _identity(kernel, security, handle, pid):
    if kernel.GetProcessId(handle) != pid:
        raise _error('PROCESS_HANDLE_IDENTITY_DIFFERS')
    creation = _creation_time(kernel, handle)
    image = _image_path(kernel, handle)
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
        raise _error('PROCESS_TOKEN_UNAVAILABLE')
    try:
        user, size = _token_buffer(security, token, 1)
        if size < ctypes.sizeof(ctypes.c_void_p):
            raise ProcessObservationError('PROCESS_TOKEN_USER_INVALID')
        sid = ctypes.cast(user, ctypes.POINTER(wintypes.LPVOID)).contents
        user_sid = _sid_text(kernel, security, sid)
        is_appcontainer = _token_flag(security, token, 29)
        is_lpac = (
            _token_flag(security, token, 46, allow_unsupported=True) if is_appcontainer else False
        )
        is_elevated = _token_flag(security, token, 20)
        appcontainer_sid = None
        if is_appcontainer:
            container, size = _token_buffer(security, token, 31)
            if size < ctypes.sizeof(ctypes.c_void_p):
                raise ProcessObservationError('PROCESS_APPCONTAINER_SID_INVALID')
            sid = ctypes.cast(container, ctypes.POINTER(wintypes.LPVOID)).contents
            appcontainer_sid = _sid_text(kernel, security, sid)
        if is_lpac and not is_appcontainer:
            raise ProcessObservationError('PROCESS_TOKEN_FACTS_CONFLICT')
    finally:
        kernel.CloseHandle(token)
    if _creation_time(kernel, handle) != creation:
        raise ProcessObservationError('PROCESS_CREATION_IDENTITY_CHANGED')
    return NativeProcessIdentity(
        pid, creation, image, user_sid, appcontainer_sid, is_appcontainer, is_lpac, is_elevated
    )


class ObservedProcess:
    """Own one non-inheritable QUERY/SYNCHRONIZE handle; never reopen by old PID."""

    def __init__(self, pid, *, expected=None):
        if type(pid) is not int or not 1 <= pid <= 0xFFFFFFFF:
            raise ProcessObservationError('PROCESS_ID_INVALID')
        if expected is not None and not isinstance(expected, NativeProcessIdentity):
            raise ProcessObservationError('EXPECTED_PROCESS_IDENTITY_INVALID')
        self._gate = RLock()
        self._kernel, self._security = _api()
        self._handle = self._kernel.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
        )
        if not self._handle:
            raise _error('PROCESS_HANDLE_UNAVAILABLE')
        try:
            self.identity = _identity(self._kernel, self._security, self._handle, pid)
            if expected is not None and self.identity != expected:
                raise ProcessObservationError('EXPECTED_PROCESS_IDENTITY_DIFFERS')
        except BaseException:
            self.close()
            raise

    def observe(self):
        with self._gate:
            if not self._handle:
                raise ProcessObservationError('PROCESS_HANDLE_CLOSED')
            if (
                self._kernel.GetProcessId(self._handle) != self.identity.pid
                or _creation_time(self._kernel, self._handle) != self.identity.creation_time_hex
            ):
                raise ProcessObservationError('PROCESS_HANDLE_IDENTITY_DIFFERS')
            result = self._kernel.WaitForSingleObject(self._handle, 0)
            if result == 258:
                return NativeProcessObservation(self.identity, 'RUNNING', None)
            if result != 0:
                raise _error('PROCESS_WAIT_RESULT_UNKNOWN')
            exit_code = wintypes.DWORD()
            if not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(exit_code)):
                raise _error('PROCESS_EXIT_CODE_UNAVAILABLE')
            # 259 is a valid observed exit code once the process is signaled.
            return NativeProcessObservation(self.identity, 'EXITED', exit_code.value)

    def duplicate(self):
        """Independently own THIS original read-only object, with identical rights."""
        with self._gate:
            self.observe()
            result = object.__new__(ObservedProcess)
            result._gate = RLock()
            result._kernel, result._security = self._kernel, self._security
            result._handle, result.identity = None, self.identity
            current = self._kernel.GetCurrentProcess()
            copied = wintypes.HANDLE()
            if not self._kernel.DuplicateHandle(
                current, self._handle, current, ctypes.byref(copied), 0, False, 2
            ):
                raise _error('ORIGINAL_PROCESS_DUPLICATE_FAILED')
            if not copied.value:
                raise ProcessObservationError('ORIGINAL_PROCESS_DUPLICATE_UNVERIFIED')
            result._handle = copied.value
            try:
                flags = wintypes.DWORD()
                if (
                    not self._kernel.GetHandleInformation(result._handle, ctypes.byref(flags))
                    or flags.value & 1
                ):
                    raise _error('ORIGINAL_PROCESS_DUPLICATE_INHERITANCE_UNVERIFIED')
                result.observe()
                return result
            except BaseException as original:
                try:
                    result.close()
                except BaseException as cleanup:
                    cleanup.retained_owner = result
                    raise cleanup from original
                raise

    def close(self):
        with self._gate:
            if self._handle:
                if not self._kernel.CloseHandle(self._handle):
                    error = _error('PROCESS_HANDLE_CLOSE_FAILED')
                    error.retained_owner = self
                    raise error
                self._handle = None

    def __enter__(self):
        if not self._handle:
            raise ProcessObservationError('PROCESS_HANDLE_CLOSED')
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
