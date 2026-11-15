"""Read-only effective NTFS rights of the original ordinary controller.

No ACL/owner/privilege is changed. These access facts do not by themselves admit
a package, authenticate a Python script or prove a task's LPAC/WFP boundary.
"""

import ctypes
import hashlib
from ctypes import wintypes
from dataclasses import dataclass
from threading import RLock

from .windows_controller_token import (
    ControllerPrimaryToken,
    TokenStatistics,
    _luid,
    _non_inheritable,
)
from .windows_local_paths import FileIdentity, LocalPathGuard, _identity
from .windows_local_paths import _api as file_api
from .windows_private_package import _sid_text
from .windows_process import _token_buffer, _token_flag

FILE_MUTATIONS = 0x2 | 0x4 | 0x10 | 0x100 | 0x10000 | 0x40000 | 0x80000
DIRECTORY_MUTATIONS = FILE_MUTATIONS | 0x40
ANCESTOR_MUTATIONS = 0x10 | 0x100 | 0x40 | 0x10000 | 0x40000 | 0x80000


class NativeAccessError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


@dataclass(frozen=True)
class ControllerAccess:
    file: FileIdentity
    controller_user_sid: str
    owner_sid: str
    descriptor_sha256: str
    granted_access: int


class GenericMapping(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in ('read', 'write', 'execute', 'all')]


def _failure(code):
    return NativeAccessError(code, ctypes.get_last_error())


def _api(controller):
    kernel = file_api()
    security = controller._security
    security.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    security.GetSecurityInfo.restype = wintypes.DWORD
    security.IsValidSecurityDescriptor.argtypes = [wintypes.LPVOID]
    security.IsValidSecurityDescriptor.restype = wintypes.BOOL
    security.GetSecurityDescriptorLength.argtypes = [wintypes.LPVOID]
    security.GetSecurityDescriptorLength.restype = wintypes.DWORD
    security.AccessCheck.argtypes = [
        wintypes.LPVOID,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(GenericMapping),
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.BOOL),
    ]
    security.AccessCheck.restype = wintypes.BOOL
    # path_api intentionally does not grant current process/token powers.
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    return kernel, security


def require_controller_read_only(facts, *, role):
    if (
        type(facts) is not ControllerAccess
        or type(facts.file) is not FileIdentity
        or role not in ('FILE', 'PACKAGE_DIRECTORY', 'ANCESTOR')
        or type(facts.granted_access) is not int
        or not 0 <= facts.granted_access <= 0x0FFFFFFF
    ):
        raise NativeAccessError('CONTROLLED_ACCESS_FACTS_REQUIRED')
    directory = role != 'FILE'
    if facts.file.is_directory != directory:
        raise NativeAccessError('CONTROLLED_ACCESS_ROLE_DIFFERS')
    mask = {
        'FILE': FILE_MUTATIONS,
        'PACKAGE_DIRECTORY': DIRECTORY_MUTATIONS,
        'ANCESTOR': ANCESTOR_MUTATIONS,
    }[role]
    if facts.granted_access & mask:
        raise NativeAccessError('CONTROLLER_CAN_MUTATE_CONTROLLED_RESOURCE')
    return facts


class ControllerAccessQuery:
    def __init__(self, controller):
        if type(controller) is not ControllerPrimaryToken:
            raise NativeAccessError('ORIGINAL_CONTROLLER_TOKEN_REQUIRED')
        self._controller = controller
        self._gate = RLock()
        self._kernel, self._security = _api(controller)
        self._token = None
        self._files = []
        self._descriptors = []
        self._closing = False
        try:
            with controller.creation_handle() as source:
                copied = wintypes.HANDLE()
                # Identification token only; never impersonate the Guard thread.
                if not self._security.DuplicateTokenEx(
                    source, 0x8, None, 1, 2, ctypes.byref(copied)
                ):
                    raise _failure('CONTROLLER_ACCESS_TOKEN_DUPLICATE_FAILED')
                self._token = copied.value
                self._verify_token()
        except BaseException as original:
            try:
                self.close()
            except NativeAccessError as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _verify_token(self):
        if self._closing or self._token is None:
            raise NativeAccessError('CONTROLLER_ACCESS_QUERY_CLOSED')
        _non_inheritable(self._kernel, self._token)
        token = self._token
        if _token_flag(self._security, token, 29) or _token_flag(self._security, token, 20):
            raise NativeAccessError('ORDINARY_ACCESS_TOKEN_REQUIRED')
        user, count = _token_buffer(self._security, token, 1)
        if count < ctypes.sizeof(ctypes.c_void_p):
            raise NativeAccessError('CONTROLLER_ACCESS_TOKEN_USER_INVALID')
        sid = _sid_text(
            self._kernel,
            self._security,
            ctypes.cast(user, ctypes.POINTER(wintypes.LPVOID)).contents,
        )
        statistics = TokenStatistics()
        returned = wintypes.DWORD()
        if not self._security.GetTokenInformation(
            token,
            10,
            ctypes.byref(statistics),
            ctypes.sizeof(statistics),
            ctypes.byref(returned),
        ):
            raise _failure('CONTROLLER_ACCESS_TOKEN_STATISTICS_UNAVAILABLE')
        if returned.value != ctypes.sizeof(statistics):
            raise NativeAccessError('CONTROLLER_ACCESS_TOKEN_STATISTICS_SIZE_INVALID')
        session = wintypes.DWORD()
        if not self._security.GetTokenInformation(
            token,
            12,
            ctypes.byref(session),
            ctypes.sizeof(session),
            ctypes.byref(returned),
        ) or returned.value != ctypes.sizeof(session):
            raise _failure('CONTROLLER_ACCESS_TOKEN_SESSION_UNAVAILABLE')
        expected = self._controller.identity
        if (
            statistics.token_type != 2
            or statistics.impersonation_level != 1
            or sid != expected.user_sid
            or _luid(statistics.authentication_id) != expected.authentication_id_hex
            or session.value != expected.session_id
        ):
            raise NativeAccessError('CONTROLLER_ACCESS_TOKEN_BINDING_DIFFERS')

    def query(self, guard):
        if type(guard) is not LocalPathGuard:
            raise NativeAccessError('ORIGINAL_NATIVE_FILE_GUARD_REQUIRED')
        with self._gate, self._controller.creation_handle():
            self._verify_token()
            expected = guard.verify()
            handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(guard.path),
                0x20080,
                0x1 | 0x2,
                None,
                3,
                0x00200000 | 0x02000000,
                None,
            )
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise _failure('CONTROLLED_RESOURCE_SECURITY_HANDLE_UNAVAILABLE')
            self._files.append(handle)
            try:
                if _identity(self._kernel, handle, guard.path) != expected:
                    raise NativeAccessError('CONTROLLED_RESOURCE_IDENTITY_DIFFERS')
                result = self._access(handle, expected)
                if (
                    guard.verify() != expected
                    or _identity(self._kernel, handle, guard.path) != expected
                ):
                    raise NativeAccessError('CONTROLLED_RESOURCE_IDENTITY_DIFFERS')
                self._verify_token()
                return result
            finally:
                if not self._kernel.CloseHandle(handle):
                    self._closing = True
                    error = _failure('CONTROLLED_SECURITY_HANDLE_CLOSE_UNVERIFIED')
                    error.retained_owner = self
                    raise error
                self._files.remove(handle)

    def _access(self, handle, identity):
        owner, descriptor = wintypes.LPVOID(), wintypes.LPVOID()
        code = self._security.GetSecurityInfo(
            handle,
            1,
            0x1 | 0x2 | 0x4,
            ctypes.byref(owner),
            None,
            None,
            None,
            ctypes.byref(descriptor),
        )
        if code or not descriptor.value:
            raise NativeAccessError('CONTROLLED_SECURITY_DESCRIPTOR_UNAVAILABLE', code)
        self._descriptors.append(descriptor.value)
        try:
            if not owner.value or not self._security.IsValidSecurityDescriptor(descriptor):
                raise NativeAccessError('CONTROLLED_SECURITY_DESCRIPTOR_INVALID')
            size = self._security.GetSecurityDescriptorLength(descriptor)
            if not 20 <= size <= 65536:
                raise NativeAccessError('CONTROLLED_SECURITY_DESCRIPTOR_SIZE_INVALID')
            descriptor_sha = hashlib.sha256(ctypes.string_at(descriptor, size)).hexdigest()
            owner_sid = _sid_text(self._kernel, self._security, owner)
            privileges = ctypes.create_string_buffer(4096)
            privilege_size = wintypes.DWORD(len(privileges))
            granted, allowed = wintypes.DWORD(), wintypes.BOOL()
            mapping = GenericMapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
            if not self._security.AccessCheck(
                descriptor,
                self._token,
                0x02000000,
                ctypes.byref(mapping),
                privileges,
                ctypes.byref(privilege_size),
                ctypes.byref(granted),
                ctypes.byref(allowed),
            ):
                raise _failure('CONTROLLER_EFFECTIVE_ACCESS_UNAVAILABLE')
            if (
                not 8 <= privilege_size.value <= len(privileges)
                or allowed.value not in (0, 1)
                or granted.value & 0xF0000000
                or not allowed.value
                and granted.value != 0
            ):
                raise NativeAccessError('CONTROLLER_EFFECTIVE_ACCESS_INVALID')
            return ControllerAccess(
                identity,
                self._controller.identity.user_sid,
                owner_sid,
                descriptor_sha,
                granted.value,
            )
        finally:
            if self._kernel.LocalFree(descriptor):
                self._closing = True
                error = _failure('CONTROLLED_SECURITY_DESCRIPTOR_FREE_UNVERIFIED')
                error.retained_owner = self
                raise error
            self._descriptors.remove(descriptor.value)

    def close(self):
        with self._gate:
            self._closing = True
            failures = []
            for pointer in tuple(self._descriptors):
                if self._kernel.LocalFree(pointer):
                    failures.append(ctypes.get_last_error())
                else:
                    self._descriptors.remove(pointer)
            for handle in tuple(self._files):
                if self._kernel.CloseHandle(handle):
                    self._files.remove(handle)
                else:
                    failures.append(ctypes.get_last_error())
            if self._token is not None:
                if self._kernel.CloseHandle(self._token):
                    self._token = None
                else:
                    failures.append(ctypes.get_last_error())
            if failures:
                error = NativeAccessError('CONTROLLER_ACCESS_QUERY_CLOSE_UNVERIFIED', failures[0])
                error.retained_owner = self
                raise error

    def __enter__(self):
        self._verify_token()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
