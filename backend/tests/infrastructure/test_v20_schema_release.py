"""Fixed-runtime schema resource integrity; every package is temporary."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from backend.app.infrastructure.database import SchemaMismatch
from backend.app.infrastructure.schema_v20_release import (
    build_candidate,
    digest,
    _load_verified_release,
)
from backend.app.infrastructure import sqlite_runtime

try:
    sqlite_runtime.require_active()
    ACTIVE = True
except sqlite_runtime.RuntimeNotAdmitted:
    ACTIVE = False


@unittest.skipUnless(ACTIVE, 'Run through tools/python-v20.py for fixed native SQLite tests')
class SchemaReleaseTests(unittest.TestCase):
    def package(self):
        context = TemporaryDirectory(
            prefix='v20-package-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        )
        self.addCleanup(context.cleanup)
        root = Path(context.name)
        files = build_candidate('db-test')
        for name, content in files.items():
            with (root / name).open('xb') as stream:
                stream.write(content)
        return root, files

    def test_real_native_candidate_loads_with_all_bytes_and_final_objects(self):
        root, files = self.package()
        release = _load_verified_release(root, digest(files['manifest.json']))
        self.assertEqual(release.release_id, 'db-test')
        self.assertEqual(len(release.expected_schema.tables), 72)
        self.assertEqual(release.fresh_checksum, digest(files['fresh.v1.sql']))
        self.assertEqual(release.upgrade_checksum, digest(files['upgrade-151.v1.sql']))

    def test_changed_sql_or_manifest_is_rejected_before_execution(self):
        root, files = self.package()
        with self.assertRaises(SchemaMismatch):
            _load_verified_release(root, '0' * 64)
        # Modify a copied temporary schema candidate, never a frozen package.
        with (root / 'fresh.v1.sql').open('ab') as stream:
            stream.write(b'\n-- unexpected')
        with self.assertRaises(SchemaMismatch):
            _load_verified_release(root, digest(files['manifest.json']))

    def test_unproven_existing_binding_and_wrong_dll_are_not_admitted(self):
        with patch.object(sqlite_runtime, '_DLL_HANDLE', None):
            with self.assertRaises(sqlite_runtime.RuntimeNotAdmitted):
                sqlite_runtime.activate()
        with TemporaryDirectory(
            prefix='v20-runtime-',
            dir=os.environ.get('WALLE_CHECK_TEMP', Path(__file__).resolve().parents[3] / '.tmp'),
        ) as directory:
            root = Path(directory)
            with (root / 'sqlite3.dll').open('xb') as stream:
                stream.write(b'not-a-library')
            original = json.loads((sqlite_runtime.BUNDLE / 'manifest.json').read_bytes())
            with (root / 'manifest.json').open('x', encoding='utf-8') as stream:
                json.dump(original, stream)
            with patch.object(sqlite_runtime, 'BUNDLE', root):
                with self.assertRaises(sqlite_runtime.RuntimeNotAdmitted):
                    sqlite_runtime.activate()
