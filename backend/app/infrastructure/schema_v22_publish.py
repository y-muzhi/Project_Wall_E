"""Publish a fresh Schema200 candidate without replacing any existing release."""

from contextlib import closing
import ctypes
from datetime import datetime, timezone
import errno
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

from backend.app.shared.time import utc_milliseconds

from .database import SchemaMismatch
from .environment_binding import (
    EnvironmentBinding,
    extend_document_ai_copy,
    verify_binding,
    write_initial_schema,
)
from .schema_inspection import verify_integrity

from .schema_v20_release import digest
from .schema_v22_release import MANIFEST, DocumentAiSchemaRelease, build_candidate, load_release


class PublicationUnverified(RuntimeError):
    pass


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_directory(source, target):
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as error:
        raise OSError(errno.ENOSYS, 'RENAME_NOREPLACE is required') from error
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    at_fdcwd = -100
    rename_noreplace = 1
    if rename(at_fdcwd, os.fsencode(source), at_fdcwd, os.fsencode(target), rename_noreplace):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)


def _check_reopen(path, release):
    binding = EnvironmentBinding(str(uuid4()), str(uuid4()))
    with closing(sqlite3.connect(path, isolation_level=None)) as database:
        database.execute('PRAGMA foreign_keys=ON')
        database.execute('PRAGMA synchronous=FULL')
        database.execute('PRAGMA journal_mode=WAL')
        database.execute('BEGIN IMMEDIATE')
        write_initial_schema(database, release, binding)
        database.commit()
    uri = path.as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as database:
        database.execute('BEGIN')
        verify_binding(database, release, binding)
        verify_integrity(database)
        wrong_owner = EnvironmentBinding(str(uuid4()), binding.data_generation)
        try:
            verify_binding(database, release, wrong_owner)
        except SchemaMismatch as error:
            if str(error) != 'ENVIRONMENT_BINDING_MISMATCH':
                raise
        else:
            raise SchemaMismatch('Cross-environment startup was not rejected')


def _write_candidate(directory, resources):
    directory.mkdir(mode=0o700)
    for name, data in resources.items():
        with (directory / name).open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
    _sync_directory(directory)


def _check_extension(scratch, target, runtime_sha256):
    original = scratch / 'ordinary-source'
    resources = build_candidate(original.name, runtime_sha256)
    _write_candidate(original, resources)
    source = load_release(original, digest(resources[MANIFEST]), runtime_sha256)
    workspace = str(uuid4())
    old = EnvironmentBinding(workspace, str(uuid4()))
    new = EnvironmentBinding(workspace, str(uuid4()))
    path = scratch / 'verify-extension.sqlite'
    with closing(sqlite3.connect(path, isolation_level=None)) as database:
        database.execute('PRAGMA foreign_keys=ON')
        database.execute('PRAGMA journal_mode=WAL')
        database.execute('BEGIN IMMEDIATE')
        write_initial_schema(database, source, old)
        database.commit()
        database.execute('BEGIN IMMEDIATE')
        extend_document_ai_copy(
            database,
            source,
            target,
            old,
            new,
            str(uuid4()),
            utc_milliseconds(datetime.now(timezone.utc)),
        )
        database.commit()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as database:
        database.execute('BEGIN')
        verify_binding(database, target, new)


def build_and_publish(output: Path, release_id: str, runtime_sha256: str, *, document_ai=False):
    """The caller owns this directory. Return a candidate digest for explicit adoption."""
    if (
        not output.is_absolute()
        or output.resolve(strict=True) != output
        or output.stat().st_uid != os.geteuid()
        or output.stat().st_mode & 0o077
    ):
        raise ValueError('A private release directory owned by the builder is required')

    resources = build_candidate(release_id, runtime_sha256, document_ai=document_ai)
    expected = digest(resources[MANIFEST])
    target = output / release_id
    with TemporaryDirectory(prefix='.schema-build-', dir=output) as scratch:
        scratch = Path(scratch)
        staging = scratch / 'release' / release_id
        staging.parent.mkdir(mode=0o700)
        _write_candidate(staging, resources)
        candidate = load_release(staging, expected, runtime_sha256)
        _check_reopen(scratch / 'verification.sqlite', candidate)
        if isinstance(candidate, DocumentAiSchemaRelease):
            _check_extension(scratch, candidate, runtime_sha256)
        publish_directory(staging, target)
        try:
            _sync_directory(output)
            return load_release(target, expected, runtime_sha256)
        except (OSError, RuntimeError, ValueError) as error:
            raise PublicationUnverified(
                f'PUBLICATION_UNVERIFIED {release_id} {expected}'
            ) from error
