"""Native DACL checks affect only newly created private temporary packages."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    PrivatePackageGuard,
    create_private_package,
    current_operator_sid,
    _api,
)


def test_only_set_dacl(path, sddl, *, protected=True):
    """Fault injection on a new owned test package, never on normal source/data."""
    kernel, advapi = _api()
    advapi.GetSecurityDescriptorDacl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.BOOL),
    ]
    advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    descriptor = wintypes.LPVOID()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise RuntimeError('Test descriptor construction failed')
    try:
        dacl = wintypes.LPVOID()
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        if not advapi.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
        ):
            raise RuntimeError('Test DACL construction failed')
        result = advapi.SetNamedSecurityInfoW(
            '\\\\?\\' + str(path),
            1,
            0x4 | (0x80000000 if protected else 0x20000000),
            None,
            None,
            dacl,
            None,
        )
        if result:
            raise RuntimeError('Test DACL injection failed: ' + str(result))
    finally:
        kernel.LocalFree(descriptor)


# This helper takes native arguments and is not a parametrized product test.
test_only_set_dacl.__test__ = False


@unittest.skipUnless(os.name == 'nt', 'Native Windows package DACL checks')
class PrivatePackageTests(unittest.TestCase):
    def setUp(self):
        self.context = TemporaryDirectory(
            prefix='v20-private-package-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path.cwd() / '.tmp'),
        )
        self.addCleanup(self.context.cleanup)
        self.root = Path(self.context.name)
        self.path = self.root / 'new-package'

    def test_new_package_has_exact_protected_operator_acl_and_children_inherit(self):
        sid = current_operator_sid()
        self.assertTrue(sid.startswith('S-1-'))
        self.assertEqual(create_private_package(self.path), self.path)
        directory = self.path / 'audit-copy'
        directory.mkdir()
        file = directory / 'evidence.dat'
        with file.open('xb') as stream:
            stream.write(b'private test fixture')
        with PrivatePackageGuard(self.path) as package:
            identity = package.verify()
            self.assertEqual(identity.filesystem, 'NTFS')
            self.assertEqual(package.operator_sid, sid)
            self.assertTrue(package.verify_member('audit-copy', directory=True).is_directory)
            self.assertFalse(
                package.verify_member('audit-copy/evidence.dat', directory=False).is_directory
            )
        self.assertEqual(file.read_bytes(), b'private test fixture')

    def test_existing_directory_is_refused_without_changing_its_security_or_content(self):
        create_private_package(self.path)
        with (self.path / 'original.dat').open('xb') as stream:
            stream.write(b'retain')
        with self.assertRaises(PackageSecurityError) as caught:
            create_private_package(self.path)
        self.assertEqual(caught.exception.code, 'NEW_PRIVATE_PACKAGE_REQUIRED')
        with PrivatePackageGuard(self.path) as package:
            package.verify_member('original.dat', directory=False)
        self.assertEqual((self.path / 'original.dat').read_bytes(), b'retain')

    def test_broad_root_dacl_is_detected_again_while_guard_is_active(self):
        create_private_package(self.path)
        sid = current_operator_sid()
        with PrivatePackageGuard(self.path) as package:
            test_only_set_dacl(self.path, 'D:P(A;OICI;FA;;;' + sid + ')(A;OICI;FR;;;WD)')
            with self.assertRaises(PackageSecurityError) as caught:
                package.verify()
            self.assertEqual(caught.exception.code, 'PACKAGE_DACL_MUST_ONLY_ALLOW_OPERATOR')

    def test_unprotected_dacl_is_not_treated_as_a_private_package(self):
        create_private_package(self.path)
        sid = current_operator_sid()
        test_only_set_dacl(self.path, 'D:(A;OICI;FA;;;' + sid + ')', protected=False)
        with self.assertRaises(PackageSecurityError) as caught:
            with PrivatePackageGuard(self.path):
                self.fail('Inherited broad permissions must not be accepted')
        self.assertEqual(caught.exception.code, 'PACKAGE_DACL_MUST_BE_PROTECTED')

    def test_changed_child_permissions_are_rejected_and_traversal_cannot_leave_package(self):
        create_private_package(self.path)
        file = self.path / 'evidence.dat'
        with file.open('xb') as stream:
            stream.write(b'owned')
        sid = current_operator_sid()
        with PrivatePackageGuard(self.path) as package:
            for value in ('../outside', '/absolute', 'C:/outside', 'a\\b', '', 'a//b'):
                with self.subTest(value=value), self.assertRaises(PackageSecurityError):
                    package.verify_member(value, directory=False)
            test_only_set_dacl(file, 'D:P(A;;FA;;;' + sid + ')(A;;FR;;;WD)')
            with self.assertRaises(PackageSecurityError):
                package.verify_member('evidence.dat', directory=False)
            package.verify()
        self.assertEqual(file.read_bytes(), b'owned')

    def test_close_and_failed_enter_release_all_native_handles(self):
        create_private_package(self.path)
        with PrivatePackageGuard(self.path) as package:
            package.verify()
        with self.assertRaises(RuntimeError):
            package.verify()
        moved = self.root / 'moved'
        self.path.rename(moved)
        with PrivatePackageGuard(moved):
            pass
