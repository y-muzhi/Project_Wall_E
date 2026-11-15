"""New local Guard pipe endpoint with explicit rights; no service or dispatch.

The installation reference and backend SID are trusted deployment inputs.
Creation changes only this new kernel object, never an existing DACL. Endpoint
security alone does not admit the Guard package, peer program or owner_epoch.
"""

import ctypes
import re
from contextlib import contextmanager
from ctypes import wintypes
from threading import RLock, get_ident

from .windows_executable_pin import ExecutablePin
from .windows_pipe_peer import NamedPipePeerLease
from .windows_private_package import (
    AclHeader,
    AllowedAce,
    SecurityAttributes,
    _sid_text,
    current_operator_sid,
)
from .windows_private_package import _api as security_api
from .windows_process import NativeProcessIdentity

SERVER_ACCESS = 0x001F01FF
# Explicit data/read-attribute/control/synchronize; no CREATE_PIPE_INSTANCE (0x4).
CLIENT_ACCESS = 0x00120083


class GuardPipeError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


def pipe_name(installation_ref):
    if type(installation_ref) is not str or re.fullmatch('[0-9a-f]{64}', installation_ref) is None:
        raise GuardPipeError('REGISTERED_GUARD_INSTALLATION_REFERENCE_REQUIRED')
    return r'\\.\pipe\WALLE.RuntimeGuard.' + installation_ref


def _error(code):
    return GuardPipeError(code, ctypes.get_last_error())


def _api():
    kernel, security = security_api()
    kernel.CreateNamedPipeW.argtypes = (
        [wintypes.LPCWSTR] + [wintypes.DWORD] * 6 + [ctypes.POINTER(SecurityAttributes)]
    )
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    kernel.GetNamedPipeInfo.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.DWORD)] * 4
    kernel.GetNamedPipeInfo.restype = wintypes.BOOL
    kernel.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        *[ctypes.POINTER(wintypes.DWORD)] * 3,
    ]
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    kernel.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    kernel.DisconnectNamedPipe.restype = wintypes.BOOL
    security.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    security.ConvertStringSidToSidW.restype = wintypes.BOOL
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
    return kernel, security


def _sid(kernel, security, value):
    if type(value) is not str or not 1 <= len(value) <= 184:
        raise GuardPipeError('REGISTERED_BACKEND_SID_REQUIRED')
    native = wintypes.LPVOID()
    if not security.ConvertStringSidToSidW(value, ctypes.byref(native)):
        raise _error('REGISTERED_BACKEND_SID_INVALID')
    try:
        if _sid_text(kernel, security, native) != value:
            raise GuardPipeError('CANONICAL_BACKEND_SID_REQUIRED')
    finally:
        kernel.LocalFree(native)
    return value


def verify_pipe_security(kernel, security, handle, *, server_sid, backend_sid):
    owner, dacl, descriptor = wintypes.LPVOID(), wintypes.LPVOID(), wintypes.LPVOID()
    code = security.GetSecurityInfo(
        handle,
        6,
        0x1 | 0x4,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if code or not descriptor.value:
        raise GuardPipeError('GUARD_PIPE_SECURITY_UNAVAILABLE', code)
    try:
        if not owner.value or _sid_text(kernel, security, owner) != server_sid or not dacl.value:
            raise GuardPipeError('GUARD_PIPE_OWNER_OR_DACL_DIFFERS')
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not security.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            raise _error('GUARD_PIPE_DACL_CONTROL_UNAVAILABLE')
        if not control.value & 0x1000:
            raise GuardPipeError('GUARD_PIPE_PROTECTED_DACL_REQUIRED')
        expected = {backend_sid: CLIENT_ACCESS, server_sid: SERVER_ACCESS}
        acl = ctypes.cast(dacl, ctypes.POINTER(AclHeader)).contents
        if acl.count != len(expected) or acl.size < ctypes.sizeof(AclHeader):
            raise GuardPipeError('GUARD_PIPE_EXACT_DACL_REQUIRED')
        actual = {}
        for number in range(acl.count):
            pointer = wintypes.LPVOID()
            if not security.GetAce(dacl, number, ctypes.byref(pointer)):
                raise _error('GUARD_PIPE_ACE_UNAVAILABLE')
            ace = ctypes.cast(pointer, ctypes.POINTER(AllowedAce)).contents
            if ace.kind != 0 or ace.flags != 0 or ace.size < ctypes.sizeof(AllowedAce) + 8:
                raise GuardPipeError('GUARD_PIPE_EXACT_ALLOW_ACE_REQUIRED')
            sid = _sid_text(
                kernel, security, wintypes.LPVOID(pointer.value + ctypes.sizeof(AllowedAce))
            )
            if sid in actual:
                raise GuardPipeError('GUARD_PIPE_DUPLICATE_ACE')
            actual[sid] = ace.mask
        if actual != expected:
            raise GuardPipeError('GUARD_PIPE_ACCESS_RIGHTS_DIFFER')
    finally:
        kernel.LocalFree(descriptor)


class _OwnedGuardPipe:
    def _initialize(self):
        self._owner_thread = get_ident()
        self._gate = RLock()
        self._kernel, self._security = _api()
        self._handle = None
        self._peer = None
        self._users = 0

    def _check_thread(self):
        if get_ident() != self._owner_thread:
            raise GuardPipeError('ORIGINAL_GUARD_PIPE_OWNER_THREAD_DIFFERS')

    def _verify_handle(self, *, expected_flags, operator_sid):
        if self._handle is None:
            raise GuardPipeError('GUARD_PIPE_CLOSED')
        flags = wintypes.DWORD()
        if (
            not self._kernel.GetHandleInformation(self._handle, ctypes.byref(flags))
            or flags.value & 1
        ):
            raise _error('GUARD_PIPE_INHERITANCE_UNVERIFIED')
        if self._kernel.GetFileType(self._handle) != 3:
            raise GuardPipeError('GUARD_PIPE_TYPE_DIFFERS')
        info, instances = wintypes.DWORD(), wintypes.DWORD()
        if not self._kernel.GetNamedPipeInfo(
            self._handle, ctypes.byref(info), None, None, ctypes.byref(instances)
        ):
            raise _error('GUARD_PIPE_INFORMATION_UNAVAILABLE')
        if info.value != expected_flags or instances.value != 1:
            raise GuardPipeError('GUARD_PIPE_SINGLE_LOCAL_BYTE_ENDPOINT_REQUIRED')
        if current_operator_sid() != operator_sid:
            raise GuardPipeError('GUARD_PIPE_OPERATOR_CHANGED')
        verify_pipe_security(
            self._kernel,
            self._security,
            self._handle,
            server_sid=self.server_sid,
            backend_sid=self.backend_sid,
        )

    @contextmanager
    def endpoint(self):
        self._check_thread()
        with self._gate:
            self.verify()
            self._users += 1
            try:
                yield self._handle
            finally:
                self._users -= 1
                self.verify()

    def close(self):
        self._check_thread()
        with self._gate:
            if self._users:
                raise GuardPipeError('GUARD_PIPE_IN_USE')
            if self._peer is not None:
                try:
                    self._peer.close()
                    self._peer = None
                except BaseException as error:
                    error.retained_owner = self
                    raise
            if self._handle is not None:
                if not self._kernel.CloseHandle(self._handle):
                    error = _error('GUARD_PIPE_CLOSE_UNVERIFIED')
                    error.retained_owner = self
                    raise error
                self._handle = None

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


class GuardPipeServer(_OwnedGuardPipe):
    """Own a first-instance, local-only, duplex overlapped endpoint."""

    def __init__(self, installation_ref, *, backend_sid):
        self.name = pipe_name(installation_ref)
        self._initialize()
        self.server_sid = current_operator_sid()
        self.backend_sid = _sid(self._kernel, self._security, backend_sid)
        descriptor = wintypes.LPVOID()
        rights = {self.backend_sid: CLIENT_ACCESS, self.server_sid: SERVER_ACCESS}
        sddl = (
            'O:'
            + self.server_sid
            + 'D:P'
            + ''.join(f'(A;;0x{mask:08x};;;{sid})' for sid, mask in sorted(rights.items()))
        )
        if not self._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise _error('GUARD_PIPE_SECURITY_CREATION_FAILED')
        try:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            handle = self._kernel.CreateNamedPipeW(
                self.name,
                3 | 0x80000 | 0x40000000,
                8,
                1,
                65536,
                65536,
                1000,
                ctypes.byref(attributes),
            )
            if handle in (None, ctypes.c_void_p(-1).value):
                raise _error('NEW_GUARD_PIPE_INSTANCE_REQUIRED')
            self._handle = handle
            try:
                self.verify()
            except BaseException:
                self.close()
                raise
        finally:
            self._kernel.LocalFree(descriptor)

    def verify(self):
        self._check_thread()
        with self._gate:
            self._verify_handle(expected_flags=0x9, operator_sid=self.server_sid)

    def disconnect_closed_peer(self):
        """Retire a closed session while retaining the original first instance."""
        self._check_thread()
        with self._gate:
            if self._users:
                raise GuardPipeError('GUARD_PIPE_IN_USE')
            self.verify()
            if self._kernel.PeekNamedPipe(self._handle, None, 0, None, None, None):
                raise GuardPipeError('GUARD_PIPE_PEER_CLOSURE_REQUIRED')
            observed = ctypes.get_last_error()
            if observed not in (109, 232):  # Original client disconnected.
                raise GuardPipeError('GUARD_PIPE_PEER_CLOSURE_UNVERIFIED', observed)
            if not self._kernel.DisconnectNamedPipe(self._handle):
                error = _error('GUARD_PIPE_DISCONNECT_UNVERIFIED')
                error.retained_owner = self
                raise error
            self.verify()

    def _disconnect_unusable_connection(self):
        """Host-only retirement of an unadmitted or verified poisoned connection."""
        self._check_thread()
        with self._gate:
            if self._users:
                raise GuardPipeError('GUARD_PIPE_IN_USE')
            self.verify()
            if not self._kernel.DisconnectNamedPipe(self._handle):
                error = _error('GUARD_PIPE_UNADMITTED_DISCONNECT_UNVERIFIED')
                error.retained_owner = self
                raise error
            self.verify()


class GuardPipeClient(_OwnedGuardPipe):
    """One local connection, bound to an original trusted Guard process/image."""

    def __init__(self, installation_ref, *, backend_sid, server_sid, expected_guard, program):
        self.name = pipe_name(installation_ref)
        if type(expected_guard) is not NativeProcessIdentity or type(program) is not ExecutablePin:
            raise TypeError('Trusted original Guard process and program registration required')
        self._initialize()
        self.server_sid = _sid(self._kernel, self._security, server_sid)
        self.backend_sid = _sid(self._kernel, self._security, backend_sid)
        if current_operator_sid() != self.backend_sid or expected_guard.user_sid != self.server_sid:
            raise GuardPipeError('REGISTERED_GUARD_CONNECTION_USERS_DIFFER')
        # OVERLAPPED; SQOS PRESENT + Identification prevents impersonation/delegation.
        handle = self._kernel.CreateFileW(
            self.name,
            CLIENT_ACCESS,
            0,
            None,
            3,
            0x40000000 | 0x00100000 | (1 << 16),
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            raise _error('ORIGINAL_GUARD_PIPE_UNAVAILABLE')
        self._handle = handle
        try:
            self._verify_handle(expected_flags=0x8, operator_sid=self.backend_sid)
            self._peer = NamedPipePeerLease(
                self._handle,
                peer_kind='SERVER',
                expected=expected_guard,
                program=program,
                expected_user_sid=self.server_sid,
            )
            self.verify()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def verify(self):
        self._check_thread()
        with self._gate:
            self._verify_handle(expected_flags=0x8, operator_sid=self.backend_sid)
            if self._peer is None:
                raise GuardPipeError('ORIGINAL_GUARD_PIPE_PEER_REQUIRED')
            self._peer.verify()
