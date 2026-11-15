"""Native directory policy and effective restricted-token probe of a separate principal."""

import ctypes
from ctypes import wintypes
from dataclasses import replace

import pytest

from backend.app.infrastructure.windows_local_paths import (
    LocalDirectoryPin,
    PathBoundaryError,
    FileIdInfo,
    HandleInfo,
)
from backend.app.infrastructure.windows_private_package import (
    OPERATOR_ACCESS,
    PackageSecurityError,
    SidAttributes,
    _api,
    current_operator_sid,
)
from backend.app.infrastructure.windows_task_directories import TaskRuntimeRoot, _read_aces
from backend.tests.requirements.test_v15_foundation import tmp_path

BACKEND_SID = 'S-1-5-21-1-2-3-1001'
BACKEND_RIGHTS = 0x001000A0


def test_original_deployment_root_exact_acl_and_reopen(tmp_path):
    with LocalDirectoryPin(tmp_path) as base:
        with TaskRuntimeRoot.create(base, BACKEND_SID) as root:
            expected = root.verify()
            kernel, security = _api()
            owner, dacl, descriptor = (wintypes.LPVOID() for _ in range(3))
            assert (
                security.GetNamedSecurityInfoW(
                    str(root.path),
                    1,
                    5,
                    ctypes.byref(owner),
                    None,
                    ctypes.byref(dacl),
                    None,
                    ctypes.byref(descriptor),
                )
                == 0
            )
            try:
                assert _read_aces(kernel, security, dacl) == (
                    (0, 0, OPERATOR_ACCESS, current_operator_sid()),
                    (0, 0, BACKEND_RIGHTS, BACKEND_SID),
                )
            finally:
                assert not kernel.LocalFree(descriptor)
            with pytest.raises(PackageSecurityError, match='ROOT_MUST_BE_SEPARATE'):
                root.require_disjoint(replace(expected, canonical_path=str(root.path / 'journal')))
            with pytest.raises(PackageSecurityError, match='ROOT_MUST_BE_SEPARATE'):
                root.require_disjoint(replace(expected, canonical_path=str(tmp_path / 'alias')))
            sibling = tmp_path / 'journal'
            sibling.mkdir()
            with LocalDirectoryPin(sibling) as private:
                root.require_disjoint(private.verify())
        with TaskRuntimeRoot.open(base, BACKEND_SID, expected) as reopened:
            assert reopened.verify() == expected
        with pytest.raises(PathBoundaryError, match='ORIGINAL_DIRECTORY_PIN_DIFFERS'):
            TaskRuntimeRoot.open(base, BACKEND_SID, replace(expected, file_id='0' * 32))
        with pytest.raises(PackageSecurityError, match='TASK_DIRECTORY_SECURITY_DIFFERS'):
            TaskRuntimeRoot.open(base, 'S-1-5-21-1-2-3-1002', expected)
        with pytest.raises(PackageSecurityError, match='TASK_NEW_DIRECTORY_REQUIRED') as duplicate:
            TaskRuntimeRoot.create(base, BACKEND_SID)
        duplicate.value.retained_owner.close()
        with TaskRuntimeRoot.open(base, BACKEND_SID, expected) as reopened:
            assert reopened.verify() == expected


def _native_restricted_opens(path, expected=None):
    kernel, security = _api()
    convert = security.ConvertStringSidToSidW
    convert.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    convert.restype = wintypes.BOOL
    restrict = security.CreateRestrictedToken
    restrict.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SidAttributes),
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(SidAttributes),
        ctypes.POINTER(wintypes.HANDLE),
    ]
    restrict.restype = wintypes.BOOL
    security.ImpersonateLoggedOnUser.argtypes = [wintypes.HANDLE]
    security.ImpersonateLoggedOnUser.restype = wintypes.BOOL
    security.RevertToSelf.argtypes = []
    security.RevertToSelf.restype = wintypes.BOOL
    sid = wintypes.LPVOID()
    source, limited = wintypes.HANDLE(), wintypes.HANDLE()
    try:
        assert convert(BACKEND_SID, ctypes.byref(sid))
        assert security.OpenProcessToken(kernel.GetCurrentProcess(), 0xA, ctypes.byref(source))
        selector = SidAttributes(sid, 0)
        assert restrict(
            source, 0, 0, None, 0, None, 1, ctypes.byref(selector), ctypes.byref(limited)
        )
        assert security.ImpersonateLoggedOnUser(limited)
        try:
            # OPEN_EXISTING only, even for probes requesting mutation access.
            for rights in (0x80, BACKEND_RIGHTS, 0x1, 0x2, 0x4, 0x40, 0x10000, 0x40000, 0x80000):
                handle = kernel.CreateFileW(str(path), rights, 0x7, None, 3, 0x02200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    yield rights, ctypes.get_last_error()
                else:
                    try:
                        if expected is not None and rights in (0x80, BACKEND_RIGHTS):
                            identity, basic = FileIdInfo(), HandleInfo()
                            assert kernel.GetFileInformationByHandleEx(
                                handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)
                            )
                            assert kernel.GetFileInformationByHandle(handle, ctypes.byref(basic))
                            assert f'{identity.volume_serial:016x}' == expected.volume_serial
                            assert bytes(identity.file_id).hex() == expected.file_id
                            assert basic.attributes & 0x410 == 0x10
                    finally:
                        assert kernel.CloseHandle(handle)
                    yield rights, 0
        finally:
            assert security.RevertToSelf()
    finally:
        for handle in (limited, source):
            if handle:
                assert kernel.CloseHandle(handle)
        if sid:
            assert not kernel.LocalFree(sid)


def test_distinct_restricting_sid_can_open_attributes_without_enumeration_or_mutation(tmp_path):
    with LocalDirectoryPin(tmp_path) as base:
        with TaskRuntimeRoot.create(base, BACKEND_SID) as root:
            expected = root.verify()
            path = root.path
            child = path / 'operator-only'
            child.mkdir()
        # Close the Guard's pin first so DELETE cannot be denied by sharing alone.
        assert dict(_native_restricted_opens(path, expected)) == {
            0x80: 0,
            BACKEND_RIGHTS: 0,
            0x1: 5,
            0x2: 5,
            0x4: 5,
            0x40: 5,
            0x10000: 5,
            0x40000: 5,
            0x80000: 5,
        }
        assert dict(_native_restricted_opens(child))[BACKEND_RIGHTS] == 5
        with TaskRuntimeRoot.open(base, BACKEND_SID, expected) as reopened:
            assert reopened.verify() == expected
