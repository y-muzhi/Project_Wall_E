"""Capture the SQLite component of a stopped ordinary environment recovery point."""

from contextlib import closing, contextmanager, ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat
import time
from types import SimpleNamespace

from .database import SchemaMismatch
from .environment_backup_assets import (
    AUDIT_LIMIT,
    AUDIT_UNSUPPORTED,
    AUDIT_UNVERIFIED,
    capture_count_audit,
    verify_count_audit,
)
from .environment_binding import EnvironmentBinding, verify_binding
from .environment_command import admission_inputs
from .environment_control import check_maintenance_reference, read_control, stopped_for_policy
from .environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    persisted_write,
    protected_directory,
    read_entry,
    read_protected,
    require,
)
from .environment_initialize import assert_database
from .environment_installation import database_identity, identity_record, sha_value, uuid_value
from .environment_ordinary import EXTERNAL_EFFECTS
from .schema_inspection import verify_integrity

POLICY = 'database-capture.v1.json'
SNAPSHOT = 'database.sqlite3'
RECEIPT = 'database-capture-receipt.v1.json'
INVALID = 'DATABASE_CAPTURE_INTENT_MISMATCH'
UNVERIFIED = 'DATABASE_CAPTURE_UNVERIFIED'
STALE = 'DATABASE_CAPTURE_SOURCE_CHANGED'
LIMIT = 'DATABASE_CAPTURE_LIMIT'
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def capture_policy(path, expected):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    value = decode(raw, INVALID)
    version = value.get('format_version')
    assets = ('max_audit_files', 'max_audit_bytes') if version == 2 else ()
    result = exact(
        value,
        (
            'format_version',
            'operation_id',
            'environment_id',
            'data_generation',
            'deployment_id',
            'control_revision',
            'installation_sha256',
            'source_program',
            'source_program_sha256',
            'recovery_directory',
            'recovery_identity',
            'max_database_bytes',
            *assets,
            *(('maintenance',) if 'maintenance' in value else ()),
        ),
        INVALID,
    )
    require(
        raw == canonical(result)
        and type(result['format_version']) is int
        and version in (1, 2)
        and all(
            uuid_value(result[field])
            for field in ('operation_id', 'environment_id', 'data_generation', 'deployment_id')
        )
        and all(
            sha_value(result[field]) for field in ('installation_sha256', 'source_program_sha256')
        )
        and type(result['control_revision']) is int
        and result['control_revision'] > 0
        and type(result['max_database_bytes']) is int
        and 4096 <= result['max_database_bytes'] <= 1024**4,
        INVALID,
    )
    if version == 2:
        require(
            type(result['max_audit_files']) is int
            and 1 <= result['max_audit_files'] <= 512
            and type(result['max_audit_bytes']) is int
            and 1 <= result['max_audit_bytes'] <= 1024**4,
            INVALID,
        )
    if 'maintenance' in result:
        check_maintenance_reference(result['maintenance'], INVALID)
    absolute(result['source_program'], INVALID)
    absolute(result['recovery_directory'], INVALID)
    identity_record(result['recovery_identity'], INVALID)
    return result


@contextmanager
def recovery_directory(plan, installation):
    folder = Path(plan['recovery_directory'])
    roots = (installation.environment_root, installation.project, installation.schema)
    require(
        folder.name == plan['operation_id']
        and not any(folder.is_relative_to(root) or root.is_relative_to(folder) for root in roots),
        INVALID,
    )
    with protected_directory(folder.parent) as parent:
        fd = os.open(
            folder.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=parent
        )
        try:
            checked = os.fstat(fd)
            require(
                (checked.st_uid, checked.st_gid, stat.S_IMODE(checked.st_mode))
                == (installation.maintenance_uid, installation.group, 0o700)
                and identity(checked) == plan['recovery_identity'],
                UNVERIFIED,
            )
            no_acl(fd)
            check_ext4(fd)
            yield folder, fd
        finally:
            os.close(fd)


def assert_contents(fd, expected):
    require(set(os.listdir(fd)) == expected, UNVERIFIED)


def snapshot_artifact(fd, maximum, owner, group, *, expected_identity=None, seal=False, sink=None):
    fd_snapshot = os.open(SNAPSHOT, READ_FLAGS, dir_fd=fd)
    with os.fdopen(fd_snapshot, 'rb') as file:
        before = os.fstat(file.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and (before.st_uid, before.st_gid, before.st_nlink) == (owner, group, 1)
            and stat.S_IMODE(before.st_mode) == (0o600 if seal else 0o400)
            and (expected_identity is None or identity(before) == expected_identity)
            and 0 < before.st_size <= maximum,
            UNVERIFIED,
        )
        no_acl(file.fileno())
        hashed = sha256()
        size = 0
        while block := file.read(128 * 1024):
            size += len(block)
            require(size <= before.st_size, UNVERIFIED)
            hashed.update(block)
            if sink is not None:
                sink.write(block)
        after = os.fstat(file.fileno())
        require(
            size == before.st_size
            and (before.st_ctime_ns, before.st_mtime_ns) == (after.st_ctime_ns, after.st_mtime_ns),
            UNVERIFIED,
        )
        if seal:
            os.fchmod(file.fileno(), 0o400)
            os.fsync(file.fileno())
            os.fsync(fd)
        return {'identity': identity(before), 'bytes': size, 'sha256': hashed.hexdigest()}


def original_receipt(fd, plan, installation, intent):
    try:
        raw = read_entry(fd, RECEIPT, owner=installation.maintenance_uid, group=installation.group)
    except FileNotFoundError:
        return None
    version = plan['format_version']
    asset_fields = ('asset_index',) if version == 2 else ()
    result = exact(
        decode(raw, UNVERIFIED),
        (
            'format_version',
            'status',
            'intent_sha256',
            'operation_id',
            'environment_id',
            'data_generation',
            'deployment_id',
            'control_revision',
            'cutoff_at',
            'database_artifact',
            *asset_fields,
        ),
        UNVERIFIED,
    )
    require(
        raw == canonical(result)
        and type(result['format_version']) is int
        and result['format_version'] == version
        and result['status'] == capture_status(version)
        and result['intent_sha256'] == intent
        and all(
            result[key] == plan[key]
            for key in (
                'operation_id',
                'environment_id',
                'data_generation',
                'deployment_id',
                'control_revision',
            )
        ),
        UNVERIFIED,
    )
    expected = {SNAPSHOT, RECEIPT}
    if version == 2:
        expected.update(verify_count_audit(installation, fd, plan, result))
    assert_contents(fd, expected)
    artifact = snapshot_artifact(
        fd, plan['max_database_bytes'], installation.maintenance_uid, installation.group
    )
    require(result['database_artifact'] == artifact, UNVERIFIED)
    return result


def copy_database(installation, release, data_fd, folder, output_fd, plan):
    source_identity = database_identity(installation, data_fd)
    require(source_identity is not None, STALE)
    assert_database(installation, data_fd, source_identity)
    binding = EnvironmentBinding(installation.environment_id, installation.data_generation)
    source_uri = installation.database.as_uri() + '?mode=ro'
    snapshot_uri = (folder / SNAPSHOT).as_uri()
    created = False
    try:
        with closing(sqlite3.connect(source_uri, uri=True, isolation_level=None)) as source:
            source.execute('PRAGMA query_only=ON')
            source.execute('BEGIN')
            verify_binding(source, release, binding)
            verify_integrity(source)
            for check in EXTERNAL_EFFECTS:
                require(source.execute(check).fetchone() is None, 'EXTERNAL_RECOVERY_REQUIRED')
            page_count = source.execute('PRAGMA page_count').fetchone()[0]
            page_size = source.execute('PRAGMA page_size').fetchone()[0]
            require(page_count * page_size <= plan['max_database_bytes'], LIMIT)
            cutoff = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
            fd = os.open(
                SNAPSHOT,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=output_fd,
            )
            created = True
            try:
                expected = identity(os.fstat(fd))
            finally:
                os.close(fd)

            deadline = time.monotonic() + 120

            def progress(_status, _remaining, total):
                require(total * page_size <= plan['max_database_bytes'], LIMIT)
                require(time.monotonic() < deadline, UNVERIFIED)

            with closing(sqlite3.connect(snapshot_uri + '?mode=rw', uri=True)) as target:
                target.execute('PRAGMA synchronous=FULL')
                source.backup(target, pages=256, progress=progress)
                require(
                    target.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal',
                    UNVERIFIED,
                )
        assert_database(installation, data_fd, source_identity)
        assert_contents(output_fd, {SNAPSHOT})
        with closing(sqlite3.connect(snapshot_uri + '?mode=rw', uri=True)) as check:
            check.execute('PRAGMA query_only=ON')
            check.execute('BEGIN')
            verify_binding(check, release, binding)
            verify_integrity(check)
        assert_contents(output_fd, {SNAPSHOT})
        artifact = snapshot_artifact(
            output_fd,
            plan['max_database_bytes'],
            installation.maintenance_uid,
            installation.group,
            expected_identity=expected,
            seal=True,
        )
        return cutoff, artifact
    except (OSError, sqlite3.Error, ValueError, SchemaMismatch, EnvironmentFailure) as error:
        if created:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        raise


def capture_status(version):
    return 'DATABASE_AND_COUNT_AUDIT_VERIFIED' if version == 2 else 'DATABASE_SNAPSHOT_VERIFIED'


def capture_inputs(active, args, entry):
    plan = capture_policy(args.capture_policy, args.capture_sha256)
    require(plan['installation_sha256'] == args.anchor_sha256, INVALID)
    source_program = Path(plan['source_program'])
    program_sha = entry['verify_program'](source_program)
    require(program_sha == plan['source_program_sha256'], INVALID)
    installation, release = admission_inputs(
        SimpleNamespace(
            anchor=args.anchor, anchor_sha256=args.anchor_sha256, project=source_program
        ),
        active,
        program_sha,
    )
    installation.check_identity(maintenance=True)
    for key in ('environment_id', 'data_generation', 'deployment_id'):
        require(plan[key] == getattr(installation, key), INVALID)
    return plan, installation, release


def capture_database(native, active, args, entry):
    plan, installation, release = capture_inputs(active, args, entry)
    with recovery_directory(plan, installation) as (folder, fd):
        previous = original_receipt(fd, plan, installation, args.capture_sha256)
        if previous is not None:
            return previous
        with ExitStack() as opened:
            lock = opened.enter_context(installation.lock(native))
            acquired = original_receipt(fd, plan, installation, args.capture_sha256)
            if acquired is not None:
                return acquired
            if os.listdir(fd):
                raise EnvironmentFailure(UNVERIFIED, uncertain=True)
            installation.check_hold()
            control_fd = opened.enter_context(installation.directory(native, 'control'))
            control = read_control(control_fd, installation)
            require(
                stopped_for_policy(control_fd, control, plan.get('maintenance'))
                and control['control_revision'] == plan['control_revision'],
                STALE,
            )
            data_fd = opened.enter_context(installation.directory(native, 'data'))
            cutoff, artifact = copy_database(installation, release, data_fd, folder, fd, plan)
            try:
                lock.assert_owned()
                require(read_control(control_fd, installation) == control, STALE)
                installation.check_hold()
                result = {
                    'format_version': plan['format_version'],
                    'status': capture_status(plan['format_version']),
                    'intent_sha256': args.capture_sha256,
                    **{
                        key: plan[key]
                        for key in (
                            'operation_id',
                            'environment_id',
                            'data_generation',
                            'deployment_id',
                            'control_revision',
                        )
                    },
                    'cutoff_at': cutoff,
                    'database_artifact': artifact,
                }
                if plan['format_version'] == 2:
                    result['asset_index'] = capture_count_audit(
                        installation, data_fd, fd, plan, result
                    )
                    members = verify_count_audit(installation, fd, plan, result)
                    assert_contents(fd, {SNAPSHOT, *members})
                lock.assert_owned()
                require(read_control(control_fd, installation) == control, STALE)
                persisted_write(fd, RECEIPT, canonical(result), mode=0o400)
                return original_receipt(fd, plan, installation, args.capture_sha256)
            except EnvironmentFailure as error:
                code = (
                    error.code
                    if error.code in (AUDIT_UNSUPPORTED, AUDIT_LIMIT, AUDIT_UNVERIFIED)
                    else UNVERIFIED
                )
                raise EnvironmentFailure(code, uncertain=True) from error
            except OSError as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
