"""Explicit pinned SQLite activation before any SQLite/Python database import.

Only the project-owned Windows x64 bundle is supported. No PATH lookup, download,
global Python replacement, fallback library or user database access occurs here.
"""

from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

BUNDLE = Path(__file__).resolve().parents[2] / 'runtime/sqlite/3.54.1/win-x64'
DLL_SHA256 = '4b59d3cded9dc1608544160f3b4b10ac974c6ac0d6ffc23064e5f4c8dbd05aea'
ARCHIVE_SHA3 = 'c2d09c8babb9399277055c057c97a53f1ffd7c5f11d0c1f2118ffdfa39f2daa4'
SOURCE_ID = '2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76'
VERSION = '3.54.1'
_DLL_HANDLE = None


class RuntimeNotAdmitted(RuntimeError):
    pass


@dataclass(frozen=True)
class SQLiteRuntime:
    version: str
    source_id: str
    sha256: str
    bundle_ref: str = 'sqlite-3.54.1-win-x64'


def activate() -> SQLiteRuntime:
    global _DLL_HANDLE
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeNotAdmitted('The pinned Windows x64 SQLite bundle is required')
    library = BUNDLE / 'sqlite3.dll'
    if library.is_symlink() or not library.is_file():
        raise RuntimeNotAdmitted('The fixed SQLite library is unavailable')
    metadata = json.loads((BUNDLE / 'manifest.json').read_text(encoding='utf-8'))
    if (
        metadata.get('version') != VERSION
        or metadata.get('dll_sha256') != DLL_SHA256
        or metadata.get('source_id') != SOURCE_ID
        or metadata.get('archive_sha3_256') != ARCHIVE_SHA3
    ):
        raise RuntimeNotAdmitted('SQLite bundle metadata differs from the fixed build')
    if hashlib.sha256(library.read_bytes()).hexdigest() != DLL_SHA256:
        raise RuntimeNotAdmitted('SQLite library bytes differ from the fixed build')
    if 'sqlite3' in sys.modules and _DLL_HANDLE is None:
        raise RuntimeNotAdmitted('SQLite was imported before fixed runtime activation')
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeNotAdmitted('A 64-bit Python process is required')
    if 'sqlite3' not in sys.modules:
        try:
            _DLL_HANDLE = ctypes.WinDLL(str(library))
        except OSError as error:
            raise RuntimeNotAdmitted('The fixed SQLite library could not be loaded') from error
    import sqlite3

    connection = sqlite3.connect(':memory:')
    try:
        source = connection.execute('SELECT sqlite_source_id()').fetchone()[0]
        if sqlite3.sqlite_version != VERSION or source != SOURCE_ID:
            raise RuntimeNotAdmitted('SQLite was imported before the pinned runtime was activated')
        connection.execute('PRAGMA foreign_keys=ON')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise RuntimeNotAdmitted('SQLite foreign key enforcement is unavailable')
        connection.execute('CREATE TABLE runtime_probe(id INTEGER PRIMARY KEY,value TEXT) STRICT')
        if connection.execute("SELECT json_valid('{}')").fetchone()[0] != 1:
            raise RuntimeNotAdmitted('SQLite JSON support is unavailable')
    finally:
        connection.close()
    return SQLiteRuntime(VERSION, SOURCE_ID, DLL_SHA256)


def require_active() -> SQLiteRuntime:
    """Require the identity established before the Python binding was loaded."""
    if _DLL_HANDLE is None or 'sqlite3' not in sys.modules:
        raise RuntimeNotAdmitted('Activate the fixed runtime before importing the database')
    import sqlite3

    if sqlite3.sqlite_version != VERSION:
        raise RuntimeNotAdmitted('The active SQLite binding differs from the fixed runtime')
    return SQLiteRuntime(VERSION, SOURCE_ID, DLL_SHA256)
