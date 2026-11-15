"""Current-operator-only maintenance packages on verified local NTFS paths.

Only a NEW package directory receives a DACL. An explicit original-controller
read role is reserved for CONTROL_GIT preparation; private records stay owner-only.
Existing source/data permissions
are never changed or repaired. Normal assets and backups have no automatic GC.
"""

import ctypes
import re
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import PurePosixPath

from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_local_paths import _api as path_api

OPERATOR_ACCESS = 0x001F01FF
CONTROL_GIT_READ_EXECUTE = 0x001200A9


class PackageSecurityError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


class SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ('length', wintypes.DWORD),
        ('descriptor', wintypes.LPVOID),
        ('inherit_handle', wintypes.BOOL),
    ]


class SidAttributes(ctypes.Structure):
    _fields_ = [('sid', wintypes.LPVOID), ('attributes', wintypes.DWORD)]


class AclHeader(ctypes.Structure):
    _fields_ = [
        ('revision', ctypes.c_ubyte),
        ('reserved', ctypes.c_ubyte),
        ('size', wintypes.WORD),
        ('count', wintypes.WORD),
        ('reserved2', wintypes.WORD),
    ]


class AllowedAce(ctypes.Structure):
    _fields_ = [
        ('kind', ctypes.c_ubyte),
        ('flags', ctypes.c_ubyte),
        ('size', wintypes.WORD),
        ('mask', wintypes.DWORD),
    ]


def _api():
    kernel = path_api()
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetCurrentThread.argtypes = []
    kernel.GetCurrentThread.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.LocalFree.restype = wintypes.LPVOID
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
    kernel.CreateDirectoryW.restype = wintypes.BOOL
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.OpenThreadToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.BOOL,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenThreadToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorControl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID)]
    advapi.GetAce.restype = wintypes.BOOL
    return kernel, advapi


def _error(code):
    return PackageSecurityError(code, ctypes.get_last_error())


def _sid_text(kernel, advapi, sid):
    if not sid:
        raise PackageSecurityError('PACKAGE_OWNER_MISSING')
    result = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(result)):
        raise _error('SID_UNAVAILABLE')
    try:
        return result.value
    finally:
        kernel.LocalFree(ctypes.cast(result, wintypes.LPVOID))


def current_operator_sid():
    """No privilege enabling, token changes or impersonation."""
    kernel, advapi = _api()
    thread_token = wintypes.HANDLE()
    if advapi.OpenThreadToken(kernel.GetCurrentThread(), 0x8, True, ctypes.byref(thread_token)):
        kernel.CloseHandle(thread_token)
        raise PackageSecurityError('IMPERSONATED_OPERATOR_REJECTED')
    if ctypes.get_last_error() != 1008:  # ERROR_NO_TOKEN is the only accepted absence.
        raise _error('OPERATOR_THREAD_TOKEN_UNVERIFIED')
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x8, ctypes.byref(token)):
        raise _error('OPERATOR_TOKEN_UNAVAILABLE')
    try:
        size = wintypes.DWORD()
        appcontainer = wintypes.DWORD()
        if not advapi.GetTokenInformation(
            token, 29, ctypes.byref(appcontainer), ctypes.sizeof(appcontainer), ctypes.byref(size)
        ):
            raise _error('OPERATOR_TOKEN_UNVERIFIED')
        if appcontainer.value:
            raise PackageSecurityError('APPCONTAINER_OPERATOR_REJECTED')
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if ctypes.get_last_error() != 122 or not 16 <= size.value <= 65536:
            raise _error('OPERATOR_IDENTITY_UNAVAILABLE')
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, len(buffer), ctypes.byref(size)):
            raise _error('OPERATOR_IDENTITY_UNAVAILABLE')
        user = ctypes.cast(buffer, ctypes.POINTER(SidAttributes)).contents
        return _sid_text(kernel, advapi, user.sid)
    finally:
        kernel.CloseHandle(token)


def control_git_reader_sid(controller):
    """Captured actual reader identity only; not live execution authorization."""
    if controller is None:
        return None
    # The token module itself uses this module's native SID helpers.
    from .windows_controller_token import ControllerPrimaryToken, PrimaryTokenIdentity, _ordinary

    if (
        type(controller) is not ControllerPrimaryToken
        or type(controller.identity) is not PrimaryTokenIdentity
    ):
        raise PackageSecurityError('ORIGINAL_CONTROL_GIT_READER_REQUIRED')
    _ordinary(controller._expected)
    if controller.identity.user_sid != controller._expected.user_sid:
        raise PackageSecurityError('ORIGINAL_CONTROL_GIT_READER_DIFFERS')
    return controller.identity.user_sid


def _package_rights(operator_sid, reader_sid):
    rights = {operator_sid: OPERATOR_ACCESS}
    if reader_sid is not None and reader_sid != operator_sid:
        rights[reader_sid] = CONTROL_GIT_READ_EXECUTE
    return rights


def _package_sddl(operator_sid, reader_sid):
    return (
        'O:'
        + operator_sid
        + 'D:P'
        + ''.join(
            f'(A;OICI;0x{mask:08x};;;{sid})'
            for sid, mask in sorted(_package_rights(operator_sid, reader_sid).items())
        )
    )


def _verify_acl(path, operator_sid, *, protected, reader_sid=None):
    kernel, advapi = _api()
    owner, dacl, descriptor = wintypes.LPVOID(), wintypes.LPVOID(), wintypes.LPVOID()
    result = advapi.GetNamedSecurityInfoW(
        '\\\\?\\' + str(path),
        1,
        0x1 | 0x4,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise PackageSecurityError('PACKAGE_SECURITY_UNAVAILABLE', result)
    try:
        if _sid_text(kernel, advapi, owner) != operator_sid or not dacl:
            raise PackageSecurityError('PACKAGE_OWNER_OR_DACL_DIFFERS')
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not advapi.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            raise _error('PACKAGE_SECURITY_UNAVAILABLE')
        if protected and not control.value & 0x1000:
            raise PackageSecurityError('PACKAGE_DACL_MUST_BE_PROTECTED')
        rights = _package_rights(operator_sid, reader_sid)
        mismatch = (
            'PACKAGE_DACL_MUST_ONLY_ALLOW_OPERATOR'
            if len(rights) == 1
            else 'PACKAGE_DACL_MUST_MATCH_CONTROL_GIT_READER'
        )
        acl = ctypes.cast(dacl, ctypes.POINTER(AclHeader)).contents
        if acl.count != len(rights) or acl.size < ctypes.sizeof(AclHeader):
            raise PackageSecurityError(mismatch)
        seen = set()
        for number in range(acl.count):
            pointer = wintypes.LPVOID()
            if not advapi.GetAce(dacl, number, ctypes.byref(pointer)):
                raise _error('PACKAGE_ACE_UNAVAILABLE')
            ace = ctypes.cast(pointer, ctypes.POINTER(AllowedAce)).contents
            if ace.kind != 0 or ace.flags & 0x8 or ace.size < ctypes.sizeof(AllowedAce) + 8:
                raise PackageSecurityError('PACKAGE_OPERATOR_ACCESS_DIFFERS')
            sid = _sid_text(
                kernel, advapi, wintypes.LPVOID(pointer.value + ctypes.sizeof(AllowedAce))
            )
            if sid not in rights or sid in seen:
                raise PackageSecurityError(mismatch)
            if ace.mask != rights[sid]:
                raise PackageSecurityError(
                    'PACKAGE_OPERATOR_ACCESS_DIFFERS'
                    if sid == operator_sid
                    else 'PACKAGE_READER_ACCESS_DIFFERS'
                )
            if protected and ace.flags != 0x3:
                raise PackageSecurityError('PACKAGE_DACL_INHERITANCE_DIFFERS')
            seen.add(sid)
    finally:
        kernel.LocalFree(descriptor)


def _create_package(target, *, operator_sid, controller=None, expected_parent=None):
    reader_sid = control_git_reader_sid(controller)
    kernel, advapi = _api()
    descriptor = wintypes.LPVOID()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        _package_sddl(operator_sid, reader_sid), 1, ctypes.byref(descriptor), None
    ):
        raise _error('PACKAGE_SECURITY_CREATION_FAILED')
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        with LocalPathGuard(target.parent, directory=True) as parent:
            if expected_parent is not None and parent.verify() != expected_parent:
                raise PackageSecurityError('ORIGINAL_CONTROL_GIT_PARENT_CHANGED')
            if not kernel.CreateDirectoryW('\\\\?\\' + str(target), ctypes.byref(attributes)):
                raise _error('NEW_PRIVATE_PACKAGE_REQUIRED')
            # Unknown/partial preparation is retained; never repair an existing path.
            with PrivatePackageGuard(target, control_git_reader=controller):
                pass
    finally:
        kernel.LocalFree(descriptor)
    return target


def create_private_package(path):
    """Create exactly one new operator-only directory; never change existing ACLs."""
    return _create_package(local_absolute_path(path), operator_sid=current_operator_sid())


def create_control_git_read_package(parent, package_nonce, controller):
    """Create only this pre-recorded new child; the reader is an actual native token."""
    if type(parent) is not PrivatePackageGuard or parent.is_control_git_read_package:
        raise PackageSecurityError('ORIGINAL_OPERATOR_ONLY_PARENT_REQUIRED')
    if type(package_nonce) is not str or re.fullmatch('[0-9a-f]{32}', package_nonce) is None:
        raise PackageSecurityError('ORIGINAL_CONTROL_GIT_PACKAGE_NONCE_REQUIRED')
    control_git_reader_sid(controller)
    if controller is None:
        raise PackageSecurityError('ORIGINAL_CONTROL_GIT_READER_REQUIRED')
    original = parent.verify()
    target = parent.path / ('control-git-' + package_nonce)
    with controller.creation_handle():
        result = _create_package(
            target,
            operator_sid=parent.operator_sid,
            controller=controller,
            expected_parent=original,
        )
        if parent.verify() != original:
            raise PackageSecurityError('ORIGINAL_CONTROL_GIT_PARENT_CHANGED')
        return result


class PrivatePackageGuard:
    def __init__(self, path, *, control_git_reader=None):
        self._control_git_reader = control_git_reader
        self._reader_sid = control_git_reader_sid(control_git_reader)
        self.path = local_absolute_path(path)
        self.operator_sid = None
        self._guard = None

    @property
    def reader_sid(self):
        return self._reader_sid

    @property
    def is_control_git_read_package(self):
        return self._control_git_reader is not None

    def __enter__(self):
        if self._guard is not None:
            raise RuntimeError('Private package guard is already active')
        self.operator_sid = current_operator_sid()
        self._guard = LocalPathGuard(self.path, directory=True)
        try:
            self._guard.__enter__()
            self.verify()
            return self
        except BaseException:
            self.close()
            raise

    def verify(self):
        if self._guard is None:
            raise RuntimeError('An active private package guard is required')
        if current_operator_sid() != self.operator_sid:
            raise PackageSecurityError('PACKAGE_OPERATOR_CHANGED')
        identity = self._guard.verify()
        _verify_acl(self.path, self.operator_sid, protected=True, reader_sid=self.reader_sid)
        self._guard.verify()
        return identity

    @contextmanager
    def file_creation_attributes(self):
        """Fix a NEW file's owner and exact role DACL before any bytes exist."""
        self.verify()
        kernel, security = _api()
        descriptor = wintypes.LPVOID()
        rights = _package_rights(self.operator_sid, self.reader_sid)
        sddl = (
            'O:'
            + self.operator_sid
            + 'D:P'
            + ''.join(f'(A;;0x{mask:08x};;;{sid})' for sid, mask in sorted(rights.items()))
        )
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise _error('PACKAGE_SECURITY_CREATION_FAILED')
        try:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            yield attributes
            self.verify()
        finally:
            kernel.LocalFree(descriptor)

    def publish_new_file(self, filename, raw, *, max_file_bytes):
        """Use the existing original-handle, no-replace publisher for fixed file roles."""
        from .windows_private_record import PrivateRecordAppend

        with PrivateRecordAppend(self, filename, raw, max_record_bytes=max_file_bytes) as record:
            return record.publish()

    def verify_member(self, relative, *, directory):
        self.verify()
        if type(relative) is not str or not relative or '\\' in relative or ':' in relative:
            raise PackageSecurityError('PACKAGE_MEMBER_PATH_INVALID')
        parts = relative.split('/')
        if any(part in ('', '.', '..') for part in parts) or PurePosixPath(relative).is_absolute():
            raise PackageSecurityError('PACKAGE_MEMBER_PATH_INVALID')
        target = self.path.joinpath(*parts)
        with LocalPathGuard(target, directory=directory) as member:
            _verify_acl(target, self.operator_sid, protected=False, reader_sid=self.reader_sid)
            identity = member.verify()
        self.verify()
        return identity

    def close(self):
        if self._guard is not None:
            self._guard.close()
        self._guard = None

    def __exit__(self, error_type, error, traceback):
        self.close()
