"""New operation-private read-only empty directory for fixed Git hook overrides.

Only CreateDirectory receives this descriptor. Existing paths/ACLs are never
repaired. OWNER_RIGHTS removes the owner's implicit WRITE_DAC grant.
"""

import ctypes
import hashlib
import os
from contextlib import contextmanager, nullcontext
from ctypes import wintypes
from dataclasses import dataclass, field
from threading import RLock

from .windows_executable_pin import _api as read_api
from .windows_local_paths import FileIdentity, LocalPathGuard, _identity, local_absolute_path
from .windows_private_package import (
    AclHeader,
    AllowedAce,
    PackageSecurityError,
    PrivatePackageGuard,
    SecurityAttributes,
    _api,
    _sid_text,
    control_git_reader_sid,
    current_operator_sid,
)

READ_EXECUTE = 0x1200A9
OWNER_RIGHTS = 'S-1-3-4'


class _Descriptor:
    def __init__(self, kernel, pointer):
        self.kernel, self.pointer = kernel, pointer

    def close(self):
        if self.pointer is None:
            return
        if self.kernel.LocalFree(self.pointer):
            error = PackageSecurityError(
                'EMPTY_DIRECTORY_DESCRIPTOR_FREE_UNVERIFIED', ctypes.get_last_error()
            )
            error.retained_owner = self
            raise error
        self.pointer = None


def _verify_security(path, operator_sid, reader_sid=None):
    kernel, security = _api()
    owner, dacl, descriptor = wintypes.LPVOID(), wintypes.LPVOID(), wintypes.LPVOID()
    code = security.GetNamedSecurityInfoW(
        '\\\\?\\' + str(path),
        1,
        0x1 | 0x4,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if code:
        raise PackageSecurityError('EMPTY_DIRECTORY_SECURITY_UNAVAILABLE', code)
    allocation = _Descriptor(kernel, descriptor)
    try:
        if not owner or not dacl or _sid_text(kernel, security, owner) != operator_sid:
            raise PackageSecurityError('EMPTY_DIRECTORY_OWNER_DIFFERS')
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not security.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            raise PackageSecurityError(
                'EMPTY_DIRECTORY_SECURITY_UNVERIFIED', ctypes.get_last_error()
            )
        acl = ctypes.cast(dacl, ctypes.POINTER(AclHeader)).contents
        expected = {operator_sid, OWNER_RIGHTS}
        if reader_sid is not None:
            expected.add(reader_sid)
        if not control.value & 0x1000 or acl.count != len(expected):
            raise PackageSecurityError('EMPTY_DIRECTORY_PROTECTED_DACL_REQUIRED')
        identities = []
        for index in range(acl.count):
            pointer = wintypes.LPVOID()
            if not security.GetAce(dacl, index, ctypes.byref(pointer)):
                raise PackageSecurityError(
                    'EMPTY_DIRECTORY_ACE_UNAVAILABLE', ctypes.get_last_error()
                )
            ace = ctypes.cast(pointer, ctypes.POINTER(AllowedAce)).contents
            if ace.kind != 0 or ace.flags != 0 or ace.mask != READ_EXECUTE or ace.size < 16:
                raise PackageSecurityError('EMPTY_DIRECTORY_READ_ONLY_ACES_REQUIRED')
            sid = wintypes.LPVOID(pointer.value + ctypes.sizeof(AllowedAce))
            identities.append(_sid_text(kernel, security, sid))
        if set(identities) != expected or len(set(identities)) != len(identities):
            raise PackageSecurityError('EMPTY_DIRECTORY_OWNER_RIGHTS_REQUIRED')
        security.GetSecurityDescriptorLength.argtypes = [wintypes.LPVOID]
        security.GetSecurityDescriptorLength.restype = wintypes.DWORD
        size = security.GetSecurityDescriptorLength(descriptor)
        if not 20 <= size <= 65536:
            raise PackageSecurityError('EMPTY_DIRECTORY_DESCRIPTOR_SIZE_INVALID')
        return hashlib.sha256(ctypes.string_at(descriptor, size)).hexdigest()
    finally:
        allocation.close()


@dataclass(frozen=True)
class EmptyDirectoryFacts:
    file: FileIdentity = field(repr=False)
    descriptor_sha256: str


class ReadOnlyEmptyDirectory:
    def __init__(self, path, *, control_git_reader=None):
        self._reader_sid = control_git_reader_sid(control_git_reader)
        self.path = local_absolute_path(path)
        self._gate = RLock()
        self._uses = 0
        self._closing = False
        self._guard = LocalPathGuard(self.path, directory=True)
        self._operator = current_operator_sid()
        self._original = None
        self._handle = None
        self._kernel = read_api()
        try:
            self._guard.__enter__()
            # Attribute-only opens do not participate in Windows data sharing.
            # Hold LIST_DIRECTORY as well, so no-DELETE sharing pins this path.
            handle = self._kernel.CreateFileW(
                '\\\\?\\' + str(self.path),
                0x81,
                0x1 | 0x2,
                None,
                3,
                0x00200000 | 0x02000000,
                None,
            )
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise PackageSecurityError(
                    'EMPTY_DIRECTORY_PIN_UNAVAILABLE', ctypes.get_last_error()
                )
            self._handle = handle
            self._original = self.verify()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def verify(self):
        with self._gate:
            if self._closing:
                raise PackageSecurityError('EMPTY_DIRECTORY_CLOSED')
            identity = self._guard.verify()
            if self._handle is None or _identity(self._kernel, self._handle, self.path) != identity:
                raise PackageSecurityError('EMPTY_DIRECTORY_PIN_CHANGED')
            security = _verify_security(self.path, self._operator, self._reader_sid)
            with os.scandir(self.path) as listing:
                if next(listing, None) is not None:
                    raise PackageSecurityError('EMPTY_DIRECTORY_HAS_CONTENT')
            actual = EmptyDirectoryFacts(identity, security)
            if self._original is not None and actual != self._original:
                raise PackageSecurityError('EMPTY_DIRECTORY_ORIGINAL_CHANGED')
            return actual

    @contextmanager
    def hold(self):
        with self._gate:
            self.verify()
            self._uses += 1
        try:
            yield self
        finally:
            with self._gate:
                self._uses -= 1
                self.verify()

    def close(self):
        with self._gate:
            if self._uses:
                raise PackageSecurityError('EMPTY_DIRECTORY_IN_USE')
            self._closing = True
            if self._handle is not None:
                if not self._kernel.CloseHandle(self._handle):
                    error = PackageSecurityError(
                        'EMPTY_DIRECTORY_PIN_CLOSE_UNVERIFIED', ctypes.get_last_error()
                    )
                    error.retained_owner = self
                    raise error
                self._handle = None
            try:
                self._guard.close()
            except BaseException as error:
                error.retained_owner = self
                raise

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def create_readonly_empty_directory(package, name):
    if type(package) is not PrivatePackageGuard:
        raise PackageSecurityError('ORIGINAL_PRIVATE_PACKAGE_REQUIRED')
    package.verify()
    if type(name) is not str:
        raise PackageSecurityError('EMPTY_DIRECTORY_CHILD_NAME_REQUIRED')
    target = local_absolute_path(package.path / name)
    if target.parent != package.path:
        raise PackageSecurityError('EMPTY_DIRECTORY_DIRECT_CHILD_REQUIRED')
    kernel, security = _api()
    descriptor = wintypes.LPVOID()
    sid = package.operator_sid
    readers = {sid, OWNER_RIGHTS}
    if package.reader_sid is not None:
        readers.add(package.reader_sid)
    sddl = (
        'O:' + sid + 'D:P' + ''.join('(A;;0x1200a9;;;' + reader + ')' for reader in sorted(readers))
    )
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise PackageSecurityError(
            'EMPTY_DIRECTORY_DESCRIPTOR_CREATION_FAILED', ctypes.get_last_error()
        )
    allocation = _Descriptor(kernel, descriptor)
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        creation = (
            nullcontext()
            if package._control_git_reader is None
            else package._control_git_reader.creation_handle()
        )
        with creation:
            if not kernel.CreateDirectoryW('\\\\?\\' + str(target), ctypes.byref(attributes)):
                raise PackageSecurityError('NEW_EMPTY_DIRECTORY_REQUIRED', ctypes.get_last_error())
            with ReadOnlyEmptyDirectory(target, control_git_reader=package._control_git_reader):
                pass
            package.verify()
            return target
    finally:
        allocation.close()
