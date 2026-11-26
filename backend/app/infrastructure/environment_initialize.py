"""Initialize or reconcile one original fresh Linux database operation."""

import os
import sqlite3
import stat
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone

from backend.app.shared.time import utc_milliseconds

from .database import SchemaMismatch
from .environment_binding import EnvironmentBinding, verify_snapshot_binding, write_initial_schema
from .environment_control import confirm_initial_control, read_control
from .environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    identity,
    no_acl,
    persisted_write,
    read_entry,
    require,
)
from .environment_installation import (
    database_identity,
    identity_record,
    sha_value,
    uuid_value,
    validate_target_file,
    version_record,
)
from .schema_inspection import verify_integrity

INTENT = 'intent.v1.json'
PROGRESS = 'progress.v1.json'
PHASES = ('INTENT_RECORDED', 'TARGET_BOUND', 'DATABASE_VERIFIED', 'COMPLETE', 'UNVERIFIED')


def now():
    return utc_milliseconds(datetime.now(timezone.utc))


def is_timestamp(value):
    try:
        return utc_milliseconds(datetime.fromisoformat(value)) == value
    except (ValueError, TypeError, OverflowError):
        return False


def intent_for(installation, operation_id):
    return {
        'format_version': 1,
        'operation_id': operation_id,
        'environment_id': installation.environment_id,
        'data_generation': installation.data_generation,
        'configuration_sha256': installation.configuration_sha256,
        'runtime_manifest_sha256': installation.description['runtime_manifest_sha256'],
        'schema_manifest_sha256': installation.description['schema_manifest_sha256'],
        'data_root': str(installation.path('data')),
        'database_relative_path': str(installation.database_relative),
        'lock_path': str(installation.path('lock') / 'environment.lock'),
    }


@contextmanager
def operation_directory(native, maintenance_fd, operation_id, *, create, installation):
    if create:
        try:
            os.mkdir(operation_id, 0o700, dir_fd=maintenance_fd)
        except FileExistsError as error:
            raise EnvironmentFailure('INITIALIZATION_INTENT_MISMATCH') from error
        os.fsync(maintenance_fd)
    fd = native.open_beneath(maintenance_fd, operation_id, os.O_DIRECTORY | os.O_RDONLY)
    try:
        metadata = os.fstat(fd)
        require(
            metadata.st_uid == installation.maintenance_uid
            and metadata.st_gid == installation.group
            and stat.S_IMODE(metadata.st_mode) == 0o700,
            'INITIALIZATION_INTENT_MISMATCH',
        )
        no_acl(fd)
        yield fd
    finally:
        os.close(fd)


def record_from(fd, name, installation):
    return read_entry(fd, name, owner=installation.maintenance_uid, group=installation.group)


def intent_digest(fd, installation, operation_id, mode, expected):
    code = 'INITIALIZATION_INTENT_MISMATCH'
    fixed = intent_for(installation, operation_id)
    if mode == 'prepare':
        raw = canonical({**fixed, 'prepared_at': now()})
        persisted_write(fd, INTENT, raw, mode=0o400)
        return digest(raw)
    raw = record_from(fd, INTENT, installation)
    record = decode(raw, code)
    timestamp = record.pop('prepared_at', None)
    require(digest(raw) == expected and record == fixed and is_timestamp(timestamp), code)
    return expected


def read_progress(fd, installation, operation_id, intent_sha):
    try:
        raw = record_from(fd, PROGRESS, installation)
    except FileNotFoundError:
        return None
    code = 'INITIALIZATION_INTENT_MISMATCH'
    record = decode(raw, code)
    fields = (
        'operation_id',
        'intent_sha256',
        'revision',
        'phase',
        'data_root_identity',
        'database_identity',
        'initialized_at',
        'reason_code',
        'observed_at',
    )
    version_record(record, fields, code)
    require(
        record['operation_id'] == operation_id
        and record['intent_sha256'] == intent_sha
        and type(record['revision']) is int
        and 1 <= record['revision'] <= MAX_REVISION
        and record['phase'] in PHASES
        and is_timestamp(record['observed_at']),
        code,
    )
    identity_record(record['data_root_identity'], code)
    phase = record['phase']
    if record['database_identity'] is not None:
        identity_record(record['database_identity'], code)
    elif phase in ('TARGET_BOUND', 'DATABASE_VERIFIED', 'COMPLETE'):
        raise EnvironmentFailure(code)
    if phase in ('DATABASE_VERIFIED', 'COMPLETE'):
        require(is_timestamp(record['initialized_at']) and record['reason_code'] is None, code)
    elif phase != 'UNVERIFIED':
        require(record['initialized_at'] is None and record['reason_code'] is None, code)
    return record


def store_progress(
    fd, prior, operation_id, intent_sha, root, phase, *, target=None, timestamp=None, reason=None
):
    revision = 1 if prior is None else prior['revision'] + 1
    require(revision <= MAX_REVISION, 'INITIALIZATION_INTENT_MISMATCH')
    record = {
        'format_version': 1,
        'operation_id': operation_id,
        'intent_sha256': intent_sha,
        'revision': revision,
        'phase': phase,
        'data_root_identity': root,
        'database_identity': target,
        'initialized_at': timestamp,
        'reason_code': reason,
        'observed_at': now(),
    }
    persisted_write(fd, PROGRESS, canonical(record), replace=prior is not None)
    return record


def confirm_initialized(native, installation, maintenance_fd, operation, target, timestamp):
    """Confirm the locally recorded original initialization before its first START."""
    try:
        with operation_directory(
            native, maintenance_fd, operation, create=False, installation=installation
        ) as fd:
            original = digest(record_from(fd, INTENT, installation))
            intent_digest(fd, installation, operation, 'check', original)
            record = read_progress(fd, installation, operation, original)
            require(
                record is not None
                and record['phase'] == 'COMPLETE'
                and record['data_root_identity'] == installation.roots['data']
                and record['database_identity'] == target
                and record['initialized_at'] == timestamp,
                'INITIALIZATION_NOT_CONFIRMED',
            )
    except (OSError, EnvironmentFailure) as error:
        raise EnvironmentFailure('INITIALIZATION_NOT_CONFIRMED') from error


def create_target(native, installation, data_fd):
    name = str(installation.database_relative)
    for suffix in ('-journal', '-wal', '-shm'):
        try:
            os.stat(name + suffix, dir_fd=data_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise EnvironmentFailure('TARGET_OWNERSHIP_UNVERIFIED')
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    fd = native.open_beneath(data_fd, name, flags, 0o660)
    try:
        os.fchmod(fd, 0o660)
        observed = validate_target_file(installation, os.fstat(fd))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(data_fd)
    return observed


def assert_database(installation, data_fd, expected):
    require(database_identity(installation, data_fd) == expected, 'TARGET_OWNERSHIP_UNVERIFIED')
    name = str(installation.database_relative)
    for suffix in ('-journal', '-wal', '-shm'):
        try:
            metadata = os.stat(name + suffix, dir_fd=data_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        validate_target_file(installation, metadata)


def database_has_sidecars(path):
    return any(
        os.path.lexists(path.with_name(path.name + suffix))
        for suffix in ('-wal', '-shm', '-journal')
    )


@contextmanager
def read_locked_database(path):
    """Read a database while its stable environment lock is held."""
    sidecars = database_has_sidecars(path)
    uri = path.as_uri() + ('?mode=ro' if sidecars else '?mode=ro&immutable=1')
    with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as source:
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        yield source
    require(sidecars or not database_has_sidecars(path), 'TARGET_OWNERSHIP_UNVERIFIED')


def verify_locked_binding(database, path, release, binding):
    # SQLite reports DELETE on an immutable connection even for a WAL database.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        header = stream.read(20)
    require(
        header[:16] == b'SQLite format 3\x00' and header[18:20] == b'\x02\x02',
        'ENVIRONMENT_BINDING_MISMATCH',
    )
    return verify_snapshot_binding(database, release, binding)


def inspect_database(installation, data_fd, file_identity, release, binding):
    assert_database(installation, data_fd, file_identity)
    with read_locked_database(installation.database) as database:
        objects = database.execute(
            "SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
        ).fetchone()
        if objects is None:
            has_sequences = database.execute(
                "SELECT 1 FROM sqlite_schema WHERE name='sqlite_sequence'"
            ).fetchone()
            require(
                database.execute('PRAGMA user_version').fetchone()[0] == 0
                and (
                    has_sequences is None
                    or database.execute('SELECT 1 FROM sqlite_sequence LIMIT 1').fetchone() is None
                ),
                'TARGET_OWNERSHIP_UNVERIFIED',
            )
            timestamp = None
        else:
            timestamp = verify_locked_binding(database, installation.database, release, binding)
            verify_integrity(database)
        assert_database(installation, data_fd, file_identity)
        return timestamp


def write_database(installation, data_fd, file_identity, release, binding):
    assert_database(installation, data_fd, file_identity)
    uri = installation.database.as_uri() + '?mode=rw'
    with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as database:
        database.execute('PRAGMA foreign_keys=ON')
        database.execute('PRAGMA synchronous=FULL')
        database.execute('PRAGMA journal_mode=WAL')
        database.execute('BEGIN IMMEDIATE')
        write_initial_schema(database, release, binding)
        assert_database(installation, data_fd, file_identity)
        database.commit()


def _result(status, operation_id, intent_sha, timestamp=None, reason=None):
    return {
        'status': status,
        'operation_id': operation_id,
        'intent_sha256': intent_sha,
        'initialized_at': timestamp,
        'reason_code': reason,
    }


def perform_initialization(native, installation, release, mode, operation_id, expected=None):
    require(
        uuid_value(operation_id) and mode in ('prepare', 'continue', 'check'),
        'INITIALIZATION_INTENT_MISMATCH',
    )
    require(
        expected is None if mode == 'prepare' else sha_value(expected),
        'INITIALIZATION_INTENT_MISMATCH',
    )
    installation.check_identity(maintenance=True)
    installation.check_hold()
    binding = EnvironmentBinding(installation.environment_id, installation.data_generation)
    with ExitStack() as stack:
        lock = stack.enter_context(installation.lock(native))
        installation.check_hold()
        return _initialize_under_lock(
            stack, native, installation, release, binding, lock, mode, operation_id, expected
        )


def _initialize_under_lock(
    stack, native, installation, release, binding, lock, mode, operation_id, expected
):
    control_fd = stack.enter_context(installation.directory(native, 'control'))
    data_fd = stack.enter_context(installation.directory(native, 'data'))
    maintenance_fd = stack.enter_context(installation.directory(native, 'maintenance'))
    if mode == 'prepare':
        confirm_initial_control(control_fd, installation, operation_id, create=False)
        require(database_identity(installation, data_fd) is None, 'TARGET_OWNERSHIP_UNVERIFIED')
    fd = stack.enter_context(
        operation_directory(
            native,
            maintenance_fd,
            operation_id,
            create=mode == 'prepare',
            installation=installation,
        )
    )
    intent_sha = intent_digest(fd, installation, operation_id, mode, expected)
    progress = read_progress(fd, installation, operation_id, intent_sha)
    root = identity(os.fstat(data_fd))
    target = database_identity(installation, data_fd)

    def advance(phase, timestamp=None):
        nonlocal progress
        lock.assert_owned()
        progress = store_progress(
            fd, progress, operation_id, intent_sha, root, phase, target=target, timestamp=timestamp
        )

    def pending(reason):
        return _result('PENDING_RECONCILIATION', operation_id, intent_sha, reason=reason)

    try:
        if progress is None:
            if target is not None:
                return pending('TARGET_OWNERSHIP_UNVERIFIED')
            if mode == 'check':
                return pending('INITIALIZATION_INCOMPLETE')
            advance('INTENT_RECORDED')
        require(progress['data_root_identity'] == root, 'TARGET_OWNERSHIP_UNVERIFIED')
        if mode == 'prepare':
            confirm_initial_control(control_fd, installation, operation_id, create=True)
            return _result('PREPARED', operation_id, intent_sha)
        if progress['database_identity'] != target:
            # A completed or target-bound operation cannot adopt a replacement inode.
            if progress['database_identity'] is not None:
                raise EnvironmentFailure('TARGET_OWNERSHIP_UNVERIFIED')
            return pending('TARGET_OWNERSHIP_UNVERIFIED')
        if target is None:
            if mode == 'check':
                return pending('INITIALIZATION_INCOMPLETE')
            require(progress['phase'] == 'INTENT_RECORDED', 'TARGET_OWNERSHIP_UNVERIFIED')
            confirm_initial_control(control_fd, installation, operation_id, create=True)
            lock.assert_owned()
            target = create_target(native, installation, data_fd)
            advance('TARGET_BOUND')
        elif progress['phase'] == 'COMPLETE':
            read_control(control_fd, installation)
        else:
            require(
                confirm_initial_control(control_fd, installation, operation_id, create=False),
                'ENVIRONMENT_CONTROL_MISMATCH',
            )

        timestamp = inspect_database(installation, data_fd, target, release, binding)
        if progress['phase'] == 'COMPLETE':
            require(
                timestamp and timestamp == progress['initialized_at'],
                'ENVIRONMENT_BINDING_MISMATCH',
            )
            return _result('ALREADY_INITIALIZED', operation_id, intent_sha, timestamp)
        if progress['phase'] == 'DATABASE_VERIFIED':
            require(
                timestamp and timestamp == progress['initialized_at'],
                'ENVIRONMENT_BINDING_MISMATCH',
            )
        if timestamp is None:
            if mode == 'check':
                return pending('INITIALIZATION_INCOMPLETE')
            lock.assert_owned()
            try:
                write_database(installation, data_fd, target, release, binding)
            except sqlite3.Error:
                # The operation may have committed before SQLite reported an error.
                timestamp = inspect_database(installation, data_fd, target, release, binding)
                if timestamp is None:
                    return pending('DATABASE_COMMIT_UNVERIFIED')
            else:
                timestamp = inspect_database(installation, data_fd, target, release, binding)
            if timestamp is None:
                return pending('DATABASE_COMMIT_UNVERIFIED')
        advance('DATABASE_VERIFIED', timestamp)
        advance('COMPLETE', timestamp)
        return _result(
            'INITIALIZED' if mode != 'check' else 'ALREADY_INITIALIZED',
            operation_id,
            intent_sha,
            timestamp,
        )
    except SchemaMismatch as error:
        raise EnvironmentFailure('ENVIRONMENT_BINDING_MISMATCH') from error
    except EnvironmentFailure as error:
        if error.uncertain:
            return pending(error.code)
        raise
    except (OSError, sqlite3.Error):
        return pending('INITIALIZATION_IO_UNVERIFIED')
