"""Actual Windows handles/NTFS, all files owned by this temporary test context."""

import base64
import ctypes
from types import SimpleNamespace
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from backend.app.infrastructure.windows_local_paths import (
    LocalPathGuard,
    PathBoundaryError,
    local_absolute_path,
)


@unittest.skipUnless(os.name == 'nt', 'Native Windows path checks')
class LocalPathTests(unittest.TestCase):
    def setUp(self):
        self.context = TemporaryDirectory(
            prefix='v20-native-path-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path.cwd() / '.tmp'),
        )
        self.addCleanup(self.context.cleanup)
        self.root = Path(self.context.name)
        self.parent = self.root / 'parent'
        self.parent.mkdir()
        self.source = self.parent / '原路径.dat'
        with self.source.open('xb') as stream:
            stream.write(b'original')

    def test_ambiguous_device_stream_namespace_and_network_names_are_rejected_before_io(self):
        for value in (
            'relative.dat',
            r'C:relative.dat',
            r'\root-relative',
            r'\\server\share\file',
            r'\\?\C:\data\file',
            r'C:\data\..\file',
            r'C:\data\.\file',
            r'C:\data\file:stream',
            r'C:\data\NUL.txt',
            r'C:\data\COM¹',
            r'C:\data\CONIN$',
            r'C:\data\CON .txt',
            r'C:\data\trailing.',
            'C:\\data\\trailing ',
            r'C:\data\wild*card',
            r'C:\data\\file',
        ):
            with self.subTest(value=value), self.assertRaises(PathBoundaryError):
                local_absolute_path(value)
        self.assertEqual(local_absolute_path(self.source), self.source)

    def test_live_identity_has_real_volume_and_128bit_id_and_allows_sqlite_style_writes(self):
        with LocalPathGuard(self.source, directory=False) as guard:
            identity = guard.verify()
            self.assertEqual(identity.filesystem, 'NTFS')
            self.assertFalse(identity.is_directory)
            self.assertEqual(len(identity.file_id), 32)
            self.assertEqual(len(identity.volume_serial), 16)
            with self.source.open('ab') as stream:
                stream.write(b'-append')
            self.assertEqual(guard.verify(), identity)
        self.assertEqual(self.source.read_bytes(), b'original-append')
        with self.assertRaises(RuntimeError):
            guard.verify()

    def test_failed_close_retains_only_exact_unclosed_handles_and_cannot_look_active(self):
        guard = LocalPathGuard(self.source, directory=False)
        guard.__enter__()
        kernel = guard._kernel
        first = guard._held[-1][0]

        def close(handle):
            if handle == first:
                ctypes.set_last_error(5)
                return False
            return kernel.CloseHandle(handle)

        guard._kernel = SimpleNamespace(CloseHandle=close)
        try:
            with self.assertRaises(PathBoundaryError) as caught:
                guard.close()
            self.assertEqual(caught.exception.code, 'PATH_HANDLE_CLOSE_UNVERIFIED')
            self.assertIs(caught.exception.retained_owner, guard)
            self.assertEqual([item[0] for item in guard._held], [first])
            with self.assertRaises(RuntimeError):
                guard.verify()
        finally:
            guard._kernel = kernel
            guard.close()
        self.assertEqual(guard._held, [])
        self.assertIsNone(guard._kernel)

    def test_file_and_ancestor_replacement_are_blocked_until_handles_close(self):
        replacement = self.parent / 'replacement.dat'
        with replacement.open('xb') as stream:
            stream.write(b'new')
        with LocalPathGuard(self.source, directory=False) as guard:
            old = guard.verify()
            with self.assertRaises(OSError):
                os.replace(replacement, self.source)
            with self.assertRaises(OSError):
                self.parent.rename(self.root / 'renamed-parent')
            self.assertEqual(guard.verify(), old)
        os.replace(replacement, self.source)
        with LocalPathGuard(self.source, directory=False) as guard:
            self.assertNotEqual(guard.identity.file_id, old.file_id)
        self.assertEqual(self.source.read_bytes(), b'new')

    def test_existing_hard_link_is_rejected_and_failed_open_leaves_no_handle(self):
        alias = self.parent / 'alias.dat'
        os.link(self.source, alias)
        with self.assertRaises(PathBoundaryError) as caught:
            with LocalPathGuard(self.source, directory=False):
                self.fail('A linked source must not be admitted')
        self.assertEqual(caught.exception.code, 'MULTIPLE_HARD_LINKS_REJECTED')
        alias.unlink()
        with LocalPathGuard(self.source, directory=False) as guard:
            guard.verify()

    def test_directory_junction_in_any_ancestor_is_rejected_without_reading_target(self):
        target = self.root / 'junction-target'
        target.mkdir()
        with (target / 'evidence.dat').open('xb') as stream:
            stream.write(b'retained target')
        junction = self.root / 'junction'
        quoted = lambda path: "'" + str(path).replace("'", "''") + "'"
        script = (
            'New-Item -ItemType Junction -Path '
            + quoted(junction)
            + ' -Target '
            + quoted(target)
            + ' -ErrorAction Stop | Out-Null'
        )
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        result = subprocess.run(
            [
                'powershell.exe',
                '-NoLogo',
                '-NoProfile',
                '-NonInteractive',
                '-EncodedCommand',
                encoded,
            ],
            capture_output=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaises(PathBoundaryError) as caught:
                with LocalPathGuard(junction / 'evidence.dat', directory=False):
                    self.fail('A redirected ancestor must not be admitted')
            self.assertEqual(caught.exception.code, 'REPARSE_POINT_REJECTED')
        finally:
            self.assertEqual(junction.parent, self.root)
            junction.rmdir()
        self.assertEqual((target / 'evidence.dat').read_bytes(), b'retained target')

    def test_path_kind_is_verified_and_failed_open_releases_all_ancestors(self):
        with self.assertRaises(PathBoundaryError):
            with LocalPathGuard(self.source, directory=True):
                self.fail('A file is not a directory')
        with self.assertRaises(PathBoundaryError):
            with LocalPathGuard(self.parent, directory=False):
                self.fail('A directory is not a database file')
        moved = self.root / 'movable-after-failure'
        self.parent.rename(moved)
        moved.rename(self.parent)
        with LocalPathGuard(self.parent, directory=True) as guard:
            self.assertTrue(guard.verify().is_directory)
