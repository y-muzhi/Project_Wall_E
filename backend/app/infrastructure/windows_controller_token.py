"""Retained ordinary-controller primary token for Guard native creation.

This is not Pipe/program authentication and starts no process. The Guard caller
must authenticate and retain the real backend process first. No service/current
process token fallback, privilege enabling or token/session modification exists.
"""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from threading import RLock

from .windows_process import (
    NativeProcessIdentity,
    ObservedProcess,
    _api as process_api,
    _identity,
    _token_buffer,
    _token_flag,
)
from .windows_private_package import _sid_text

TOKEN_ASSIGN_PRIMARY = 0x1
TOKEN_DUPLICATE = 0x2
TOKEN_QUERY = 0x8
CREATION_TOKEN_ACCESS = TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY
SERVICE_SIDS = frozenset(('S-1-5-18', 'S-1-5-19', 'S-1-5-20'))


class ControllerTokenError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


class Luid(ctypes.Structure):
    _fields_ = [('low', wintypes.DWORD), ('high', wintypes.LONG)]


class TokenStatistics(ctypes.Structure):
    _fields_ = [
        ('token_id', Luid),
        ('authentication_id', Luid),
        ('expiration_time', ctypes.c_int64),
        ('token_type', ctypes.c_int),
        ('impersonation_level', ctypes.c_int),
        ('dynamic_charged', wintypes.DWORD),
        ('dynamic_available', wintypes.DWORD),
        ('group_count', wintypes.DWORD),
        ('privilege_count', wintypes.DWORD),
        ('modified_id', Luid),
    ]


@dataclass(frozen=True)
class PrimaryTokenIdentity:
    user_sid: str
    authentication_id_hex: str
    session_id: int
    token_id_hex: str
    modified_id_hex: str


def _failure(code):
    return ControllerTokenError(code, ctypes.get_last_error())


def _luid(value):
    return f'{((value.high & 0xFFFFFFFF) << 32) | value.low:016x}'


def _api():
    kernel, security = process_api()
    if ctypes.sizeof(Luid) != 8 or ctypes.sizeof(TokenStatistics) != 56:
        raise ControllerTokenError('CONTROLLER_TOKEN_LAYOUT_UNSUPPORTED')
    security.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    security.DuplicateTokenEx.restype = wintypes.BOOL
    kernel.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel.SetHandleInformation.restype = wintypes.BOOL
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    return kernel, security


def _ordinary(identity):
    if (
        identity.is_appcontainer
        or identity.appcontainer_sid is not None
        or identity.is_lpac is not False
    ):
        raise ControllerTokenError('CONTROLLER_APPCONTAINER_REJECTED')
    if identity.is_elevated or identity.user_sid in SERVICE_SIDS:
        raise ControllerTokenError('ORDINARY_CONTROLLER_TOKEN_REQUIRED')


def _no_thread_impersonation(kernel, security):
    token = wintypes.HANDLE()
    if security.OpenThreadToken(kernel.GetCurrentThread(), TOKEN_QUERY, True, ctypes.byref(token)):
        if not kernel.CloseHandle(token):
            raise _failure('GUARD_THREAD_TOKEN_CLOSE_UNVERIFIED')
        raise ControllerTokenError('GUARD_IMPERSONATING_THREAD_REJECTED')
    if ctypes.get_last_error() != 1008:
        raise _failure('GUARD_THREAD_TOKEN_UNVERIFIED')


def _non_inheritable(kernel, handle):
    flags = wintypes.DWORD()
    if not kernel.GetHandleInformation(handle, ctypes.byref(flags)) or flags.value & 1:
        raise _failure('CONTROLLER_TOKEN_INHERITANCE_UNVERIFIED')


def _dword(security, token, kind):
    value = wintypes.DWORD()
    size = wintypes.DWORD()
    if not security.GetTokenInformation(
        token, kind, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size)
    ):
        raise _failure('CONTROLLER_TOKEN_INFORMATION_UNAVAILABLE')
    if size.value != ctypes.sizeof(value):
        raise ControllerTokenError('CONTROLLER_TOKEN_INFORMATION_SIZE_INVALID')
    return value.value


def _read_token(kernel, security, token):
    if _token_flag(security, token, 29):
        raise ControllerTokenError('CONTROLLER_APPCONTAINER_REJECTED')
    if _token_flag(security, token, 20):
        raise ControllerTokenError('ORDINARY_CONTROLLER_TOKEN_REQUIRED')
    user, size = _token_buffer(security, token, 1)
    if size < ctypes.sizeof(ctypes.c_void_p):
        raise ControllerTokenError('CONTROLLER_TOKEN_USER_INVALID')
    pointer = ctypes.cast(user, ctypes.POINTER(wintypes.LPVOID)).contents
    sid = _sid_text(kernel, security, pointer)
    if sid in SERVICE_SIDS:
        raise ControllerTokenError('ORDINARY_CONTROLLER_TOKEN_REQUIRED')
    statistics = TokenStatistics()
    returned = wintypes.DWORD()
    if not security.GetTokenInformation(
        token, 10, ctypes.byref(statistics), ctypes.sizeof(statistics), ctypes.byref(returned)
    ):
        raise _failure('CONTROLLER_TOKEN_STATISTICS_UNAVAILABLE')
    if returned.value != ctypes.sizeof(statistics) or statistics.token_type != 1:
        raise ControllerTokenError('CONTROLLER_PRIMARY_TOKEN_REQUIRED')
    return PrimaryTokenIdentity(
        sid,
        _luid(statistics.authentication_id),
        _dword(security, token, 12),
        _luid(statistics.token_id),
        _luid(statistics.modified_id),
    )


class ControllerPrimaryToken:
    """No PID reopen: only an authenticated caller's original held process."""

    def __init__(self, controller, *, expected):
        if type(controller) is not ObservedProcess or type(expected) is not NativeProcessIdentity:
            raise ControllerTokenError('HELD_CONTROLLER_IDENTITY_REQUIRED')
        if controller.identity != expected:
            raise ControllerTokenError('ORIGINAL_CONTROLLER_IDENTITY_DIFFERS')
        if expected.pid == os.getpid():
            raise ControllerTokenError('GUARD_SELF_TOKEN_REJECTED')
        _ordinary(expected)
        self._gate = RLock()
        self._controller = controller
        self._expected = expected
        self._handle = None
        self._source_handle = None
        self._kernel, self._security = _api()
        self._copy_identity = None
        original = wintypes.HANDLE()
        try:
            with controller._gate:
                self._verify_controller()
                _no_thread_impersonation(self._kernel, self._security)
                if not self._security.OpenProcessToken(
                    controller._handle, TOKEN_QUERY | TOKEN_DUPLICATE, ctypes.byref(original)
                ):
                    raise _failure('CONTROLLER_SOURCE_TOKEN_UNAVAILABLE')
                self._source_handle = original.value
                source = _read_token(self._kernel, self._security, self._source_handle)
                if source.user_sid != expected.user_sid:
                    raise ControllerTokenError('CONTROLLER_TOKEN_USER_DIFFERS')
                duplicate = wintypes.HANDLE()
                if not self._security.DuplicateTokenEx(
                    self._source_handle, CREATION_TOKEN_ACCESS, None, 2, 1, ctypes.byref(duplicate)
                ):
                    raise _failure('CONTROLLER_TOKEN_DUPLICATE_FAILED')
                self._handle = duplicate.value
                if not self._kernel.SetHandleInformation(self._handle, 1, 0):
                    raise _failure('CONTROLLER_TOKEN_INHERITANCE_UNVERIFIED')
                flags = wintypes.DWORD()
                if (
                    not self._kernel.GetHandleInformation(self._handle, ctypes.byref(flags))
                    or flags.value & 1
                ):
                    raise _failure('CONTROLLER_TOKEN_INHERITANCE_UNVERIFIED')
                copied = _read_token(self._kernel, self._security, self._handle)
                if (
                    copied.user_sid != source.user_sid
                    or copied.authentication_id_hex != source.authentication_id_hex
                    or copied.session_id != source.session_id
                ):
                    raise ControllerTokenError('CONTROLLER_TOKEN_COPY_DIFFERS')
                self._copy_identity = copied
                self._verify_controller()
                if not self._kernel.CloseHandle(self._source_handle):
                    raise _failure('CONTROLLER_SOURCE_TOKEN_CLOSE_UNVERIFIED')
                self._source_handle = None
        except BaseException as original_error:
            try:
                self.close()
            except ControllerTokenError as cleanup_error:
                cleanup_error.retained_owner = self
                raise cleanup_error from original_error
            raise

    @property
    def identity(self):
        return self._copy_identity

    def _verify_controller(self):
        if self._controller.observe().state != 'RUNNING':
            raise ControllerTokenError('ORIGINAL_CONTROLLER_EXITED')
        actual = _identity(
            self._kernel, self._security, self._controller._handle, self._expected.pid
        )
        if actual != self._expected:
            raise ControllerTokenError('ORIGINAL_CONTROLLER_IDENTITY_DIFFERS')
        _ordinary(actual)

    @contextmanager
    def creation_handle(self):
        with self._gate, self._controller._gate:
            if self._handle is None:
                raise ControllerTokenError('CONTROLLER_TOKEN_CLOSED')
            _no_thread_impersonation(self._kernel, self._security)
            _non_inheritable(self._kernel, self._handle)
            self._verify_controller()
            if _read_token(self._kernel, self._security, self._handle) != self.identity:
                raise ControllerTokenError('CONTROLLER_TOKEN_CHANGED')
            try:
                yield self._handle
            finally:
                # A late exit still enters the caller's original owned stop path.
                self._verify_controller()
                if _read_token(self._kernel, self._security, self._handle) != self.identity:
                    raise ControllerTokenError('CONTROLLER_TOKEN_CHANGED')

    def close(self):
        with self._gate:
            errors = []
            for field in ('_source_handle', '_handle'):
                handle = getattr(self, field)
                if handle is None:
                    continue
                if self._kernel.CloseHandle(handle):
                    setattr(self, field, None)
                else:
                    errors.append(ctypes.get_last_error())
            if errors:
                error = ControllerTokenError('CONTROLLER_TOKEN_CLOSE_UNVERIFIED', errors[0])
                # Guard resource owner may retry cleanup of THESE handles, never
                # reopen another process/token or return a serialized handle.
                error.retained_owner = self
                raise error

    def __enter__(self):
        if self._handle is None:
            raise ControllerTokenError('CONTROLLER_TOKEN_CLOSED')
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
