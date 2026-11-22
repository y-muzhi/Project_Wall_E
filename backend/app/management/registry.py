"""Explicit registry initialization and fixed-generation read-only admission."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import os
import sqlite3
import stat

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    identity,
    no_acl,
    persisted_write,
    read_entry,
    require,
)
from backend.app.infrastructure.sqlite_runtime import require_active
from backend.app.shared.time import utc_milliseconds

from .registry_dispatch import require_dispatch_open
from .registry_installation import DATABASE_NAME, IDENTITY_ERROR, load_installation
from .registry_schema import SCHEMAS, SCHEMA_VERSION, STATEMENTS

REGISTRY_APP_ID = 0x57414C4D
INTENT_NAME = 'registry-init-attempt.v1.json'
INITIALIZED_NAME = 'registry-initialized.v1.json'
REGISTRY_ERROR = 'MANAGEMENT_REGISTRY_INVALID'
NOT_INITIALIZED = 'MANAGEMENT_REGISTRY_NOT_INITIALIZED'
NEEDS_RECONCILE = 'MANAGEMENT_REGISTRY_INITIALIZATION_UNVERIFIED'


def is_timestamp(value):
    if type(value) is not str:
        return False
    try:
        at = datetime.fromisoformat(value)
        return utc_milliseconds(at) == value
    except (ValueError, OverflowError):
        return False


def schema_rows(connection):
    return tuple(
        connection.execute(
            'SELECT type, name, tbl_name, sql FROM main.sqlite_schema '
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    )


@lru_cache(maxsize=len(SCHEMAS))
def expected_schema(version=SCHEMA_VERSION):
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
        for statement in SCHEMAS[version]:
            connection.execute(statement)
        return schema_rows(connection)


def allow_file(native, installation, data, name, *, optional=False, expected_identity=None):
    try:
        fd = native.open_beneath(data, name, os.O_RDONLY)
    except FileNotFoundError:
        if optional:
            return None
        raise EnvironmentFailure(IDENTITY_ERROR) from None
    try:
        metadata = os.fstat(fd)
        require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and metadata.st_uid == installation.uid
            and metadata.st_gid == installation.gid
            and stat.S_IMODE(metadata.st_mode) == 0o600
            and (expected_identity is None or identity(metadata) == expected_identity),
            IDENTITY_ERROR,
        )
        no_acl(fd)
        return metadata
    finally:
        os.close(fd)


def verify_file(native, installation, data):
    primary = allow_file(
        native, installation, data, DATABASE_NAME, expected_identity=installation.database_facts
    )
    for associated in ('-wal', '-shm'):
        allow_file(native, installation, data, DATABASE_NAME + associated, optional=True)
    return primary


@contextmanager
def open_registry(native, installation, data, *, read_only):
    verify_file(native, installation, data)
    uri = f'file:/proc/self/fd/{data}/{DATABASE_NAME}?mode={"ro" if read_only else "rw"}'
    with closing(sqlite3.connect(uri, uri=True, isolation_level=None, timeout=2)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA synchronous=FULL')
        if read_only:
            connection.execute('PRAGMA query_only=ON')
        require(
            connection.execute('PRAGMA foreign_keys').fetchone() == (1,)
            and connection.execute('PRAGMA synchronous').fetchone() == (2,)
            and connection.execute('PRAGMA trusted_schema').fetchone() == (0,),
            REGISTRY_ERROR,
        )
        verify_file(native, installation, data)
        yield connection


def facts(installation):
    return {
        'format_version': 1,
        'installation_sha256': installation.sha256,
        'manager_id': installation.manager_id,
        'host_id': installation.host_id,
        'registry_generation': installation.registry_generation,
        'database_identity': installation.database_facts,
    }


def marker(proof, name, installation):
    try:
        raw = read_entry(
            proof, name, owner=installation.uid, group=installation.gid, reject_writers=0o377
        )
    except FileNotFoundError:
        return None
    value = decode(raw, REGISTRY_ERROR)
    timestamp = value.get('initialized_at') if name == INITIALIZED_NAME else None
    require(
        value
        == (
            {**facts(installation), 'initialized_at': timestamp}
            if name == INITIALIZED_NAME
            else facts(installation)
        )
        and (name != INITIALIZED_NAME or is_timestamp(timestamp)),
        REGISTRY_ERROR,
    )
    return value


def registry_version(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    require(type(version) is int and version in SCHEMAS, REGISTRY_ERROR)
    return version


def verify_database(connection, installation, *, integrity, journal_mode='wal'):
    require(connection.execute('PRAGMA journal_mode').fetchone() == (journal_mode,), REGISTRY_ERROR)
    version = registry_version(connection)
    require(
        connection.execute('PRAGMA application_id').fetchone() == (REGISTRY_APP_ID,)
        and schema_rows(connection) == expected_schema(version),
        REGISTRY_ERROR,
    )
    rows = connection.execute(
        'SELECT schema_version, manager_id, host_id, registry_generation, initialized_at FROM manager_state'
    ).fetchall()
    require(
        len(rows) == 1
        and rows[0][:4]
        == (
            version,
            installation.manager_id,
            installation.host_id,
            installation.registry_generation,
        )
        and is_timestamp(rows[0][4]),
        REGISTRY_ERROR,
    )
    if integrity:
        require(
            connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)], REGISTRY_ERROR
        )
        require(connection.execute('PRAGMA foreign_key_check').fetchone() is None, REGISTRY_ERROR)
    return rows[0][4]


def initialize_database(native, installation, data, lock):
    with open_registry(native, installation, data, read_only=False) as connection:
        require(
            schema_rows(connection) == ()
            and connection.execute('PRAGMA application_id').fetchone() == (0,)
            and connection.execute('PRAGMA user_version').fetchone() == (0,),
            REGISTRY_ERROR,
        )
        require(
            connection.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',), REGISTRY_ERROR
        )
        connection.execute('BEGIN IMMEDIATE')
        for statement in STATEMENTS:
            connection.execute(statement)
        connection.execute(f'PRAGMA application_id={REGISTRY_APP_ID}')
        connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        initialized_at = utc_milliseconds(datetime.now(timezone.utc))
        connection.execute(
            'INSERT INTO manager_state VALUES (1, ?, ?, ?, ?, ?)',
            (
                SCHEMA_VERSION,
                installation.manager_id,
                installation.host_id,
                installation.registry_generation,
                initialized_at,
            ),
        )
        lock.assert_owned()
        connection.execute('COMMIT')


@contextmanager
def verified_locked_registry(native, installation, lock, *, read_only, before_open=None):
    require_active()
    lock.assert_owned()
    with (
        installation.private_directory(native, 'data') as data,
        installation.private_directory(native, 'proof') as proof,
    ):
        attempted = marker(proof, INTENT_NAME, installation)
        finished = marker(proof, INITIALIZED_NAME, installation)
        require(attempted is not None and finished is not None, NOT_INITIALIZED)
        if before_open is not None:
            before_open(installation)
        with open_registry(native, installation, data, read_only=read_only) as connection:
            at = verify_database(connection, installation, integrity=True)
            require(at == finished['initialized_at'], REGISTRY_ERROR)
            lock.assert_owned()
            connection.row_factory = sqlite3.Row
            yield connection


@contextmanager
def verified_registry(native, installation, *, writable):
    require_active()
    with installation.lock(native) as lock:
        guard = require_dispatch_open if writable else None
        with verified_locked_registry(
            native, installation, lock, read_only=not writable, before_open=guard
        ) as connection:
            yield connection, lock


def verify_registered_data(native, installation, runtime_sha):
    load_installation(installation.anchor, installation.sha256, runtime_sha)
    with installation.private_directory(native, 'data') as current_data:
        verify_file(native, installation, current_data)


@contextmanager
def read_registry(native, installation, runtime_sha, *, integrity=False):
    """Open a fresh read snapshot for externally committed management operations."""
    require_active()
    verify_registered_data(native, installation, runtime_sha)
    with (
        installation.private_directory(native, 'data') as data,
        installation.private_directory(native, 'proof') as proof,
    ):
        attempted = marker(proof, INTENT_NAME, installation)
        finished = marker(proof, INITIALIZED_NAME, installation)
        require(attempted is not None and finished is not None, NOT_INITIALIZED)
        with open_registry(native, installation, data, read_only=True) as connection:
            connection.execute('BEGIN')
            try:
                at = verify_database(connection, installation, integrity=integrity)
                require(at == finished['initialized_at'], REGISTRY_ERROR)
                connection.row_factory = sqlite3.Row
                yield connection
                verify_registered_data(native, installation, runtime_sha)
            finally:
                connection.execute('ROLLBACK')


def registry_command(action, native, installation):
    """Only initialization and its read-only reconciliation can write proof."""
    require_active()
    require(action in ('initialize', 'reconcile', 'diagnose'), REGISTRY_ERROR)
    with (
        installation.lock(native) as lock,
        installation.private_directory(native, 'data') as data,
        installation.private_directory(native, 'proof') as proof,
    ):
        attempted = marker(proof, INTENT_NAME, installation)
        initialized = marker(proof, INITIALIZED_NAME, installation)
        require(initialized is None or attempted is not None, REGISTRY_ERROR)
        if action != 'diagnose':
            require_dispatch_open(installation)
        if action == 'initialize' and attempted is None:
            current = verify_file(native, installation, data)
            require(
                current.st_size == 0
                and all(
                    allow_file(native, installation, data, DATABASE_NAME + suffix, optional=True)
                    is None
                    for suffix in ('-wal', '-shm')
                ),
                REGISTRY_ERROR,
            )
            lock.assert_owned()
            persisted_write(proof, INTENT_NAME, canonical(facts(installation)), mode=0o400)
            try:
                initialize_database(native, installation, data, lock)
            except (OSError, sqlite3.Error, EnvironmentFailure) as error:
                raise EnvironmentFailure(NEEDS_RECONCILE, uncertain=True) from error
        else:
            require(attempted is not None, NOT_INITIALIZED)
            if initialized is None and action != 'reconcile':
                raise EnvironmentFailure(NEEDS_RECONCILE, uncertain=True)
        with open_registry(native, installation, data, read_only=True) as connection:
            connection.execute('BEGIN')
            at = verify_database(connection, installation, integrity=True)
            version = registry_version(connection)
            connection.execute('COMMIT')
        verify_file(native, installation, data)
        lock.assert_owned()
        if initialized is None:
            persisted_write(
                proof,
                INITIALIZED_NAME,
                canonical({**facts(installation), 'initialized_at': at}),
                mode=0o400,
            )
        else:
            require(at == initialized['initialized_at'], REGISTRY_ERROR)
        return {
            'status': 'REGISTRY_VERIFIED',
            'manager_id': installation.manager_id,
            'host_id': installation.host_id,
            'registry_generation': installation.registry_generation,
            'schema_version': version,
            'initialized_at': at,
        }
