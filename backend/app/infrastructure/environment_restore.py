"""Restore the verified SQLite component to a new data generation, offline."""

from contextlib import closing, ExitStack
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat
import time
from types import SimpleNamespace

from backend.app.shared.time import utc_milliseconds

from .data_retention import capture_retained_data, original_projections
from .database import SchemaMismatch
from .environment_backup import (
    SNAPSHOT,
    assert_contents,
    capture_policy,
    original_receipt,
    recovery_directory,
    snapshot_artifact,
)
from .environment_backup_assets import (
    AUDIT_COPY,
    AUDIT_INDEX,
    SCOPE_FIELDS,
    restore_count_audit,
    verify_count_audit,
)
from .environment_binding import EnvironmentBinding, verify_binding
from .environment_command import admission_inputs
from .environment_control import check_maintenance_reference, read_control, stopped_for_policy
from .environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    persisted_write,
    read_entry,
    read_protected,
    require,
)
from .environment_installation import identity_record, sha_value, uuid_value
from .schema_inspection import verify_integrity, verify_schema

POLICY = 'database-restore.v1.json'
TARGET = 'restore-target.v1.json'
RECEIPT = 'database-restore-receipt.v1.json'
INVALID = 'DATABASE_RESTORE_INTENT_MISMATCH'
UNVERIFIED = 'DATABASE_RESTORE_UNVERIFIED'
STALE = 'DATABASE_RESTORE_SOURCE_CHANGED'


def load_restore(path, expected):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    value = decode(raw, INVALID)
    version = value.get('format_version')
    assets = ('expected_asset_index_sha256',) if version == 2 else ()
    plan = exact(
        value,
        (
            'format_version',
            'operation_id',
            'source_environment_id',
            'source_data_generation',
            'source_deployment_id',
            'capture_policy',
            'expected_database_sha256',
            'target_directory',
            'target_identity',
            'target_data_generation',
            *assets,
            *(('maintenance',) if 'maintenance' in value else ()),
        ),
        INVALID,
    )
    require(
        type(plan['format_version']) is int
        and version in (1, 2)
        and all(
            uuid_value(plan[key])
            for key in (
                'operation_id',
                'source_environment_id',
                'source_data_generation',
                'source_deployment_id',
                'target_data_generation',
            )
        )
        and plan['source_data_generation'] != plan['target_data_generation']
        and sha_value(plan['expected_database_sha256'])
        and (version != 2 or sha_value(plan['expected_asset_index_sha256'])),
        INVALID,
    )
    if 'maintenance' in plan:
        check_maintenance_reference(plan['maintenance'], INVALID)
    absolute(plan['target_directory'], INVALID)
    identity_record(plan['target_identity'], INVALID)
    capture = exact(plan['capture_policy'], ('path', 'sha256'), INVALID)
    require(sha_value(capture['sha256']), INVALID)
    backup = capture_policy(absolute(capture['path'], INVALID), capture['sha256'])
    require(
        plan['operation_id'] != backup['operation_id']
        and version == backup['format_version']
        and all(
            plan['source_' + key] == backup[key]
            for key in (
                'environment_id',
                'data_generation',
                'deployment_id',
            )
        ),
        INVALID,
    )
    return plan, backup


def safe_target_file(fd, installation, expected=None):
    fd_file = os.open(
        SNAPSHOT, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd
    )
    try:
        props = os.fstat(fd_file)
        require(
            stat.S_ISREG(props.st_mode)
            and props.st_nlink == 1
            and props.st_uid == installation.maintenance_uid
            and props.st_gid == installation.group
            and stat.S_IMODE(props.st_mode) in (0o600, 0o400)
            and (expected is None or identity(props) == expected),
            UNVERIFIED,
        )
        no_acl(fd_file)
        if stat.S_IMODE(props.st_mode) == 0o400:
            require(os.pread(fd_file, 2, 18) == b'\x02\x02', UNVERIFIED)
        return props
    finally:
        os.close(fd_file)


def verify_target_sidecars(fd, installation):
    sidecars = {SNAPSHOT + suffix for suffix in ('-wal', '-shm', '-journal')}
    require(set(os.listdir(fd)) <= {SNAPSHOT, TARGET, *sidecars}, UNVERIFIED)
    for name in sidecars:
        try:
            handle = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=fd,
            )
        except FileNotFoundError:
            continue
        try:
            info = os.fstat(handle)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == installation.maintenance_uid
                and info.st_gid == installation.group
                and stat.S_IMODE(info.st_mode) == 0o600,
                UNVERIFIED,
            )
            no_acl(handle)
        finally:
            os.close(handle)


def read_local(fd, name, installation):
    try:
        return decode(
            read_entry(fd, name, owner=installation.maintenance_uid, group=installation.group),
            UNVERIFIED,
        )
    except FileNotFoundError:
        return None


def target_marker(fd, installation, common):
    marker = read_local(fd, TARGET, installation)
    if marker is None:
        if os.listdir(fd):
            raise EnvironmentFailure(UNVERIFIED, uncertain=True)
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(SNAPSHOT, flags, 0o600, dir_fd=fd)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        props = safe_target_file(fd, installation)
        marker = {**common, 'database_identity': identity(props)}
        persisted_write(fd, TARGET, canonical(marker), mode=0o400)
    exact(marker, (*common, 'database_identity'), UNVERIFIED)
    require(all(marker[key] == value for key, value in common.items()), UNVERIFIED)
    identity_record(marker['database_identity'], UNVERIFIED)
    safe_target_file(fd, installation, marker['database_identity'])
    return marker


def archived_facts(connection, release, binding):
    verify_schema(connection, release.expected_schema)
    verify_integrity(connection)
    owners = connection.execute(
        'SELECT singleton_id,environment_id,data_generation,initialized_at FROM environment_binding'
    ).fetchall()
    require(
        len(owners) == 1
        and owners[0][:3] == (1, binding.environment_id, binding.data_generation)
        and type(owners[0][3]) is str,
        UNVERIFIED,
    )
    projections = tuple(
        replace(
            projection,
            migration_ceiling=None,
            columns=tuple(
                column
                for column in projection.columns
                if projection.table != 'environment_binding' or column != 'data_generation'
            ),
        )
        for projection in original_projections(connection)
    )
    return owners[0][3], capture_retained_data(connection, projections)


def reopen_archive(path, release, binding, *, inspect=None):
    # Closing every SQLite connection leaves a single database. Immutable read cannot acquire WAL sidecars.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
        connection.execute('BEGIN')
        result = archived_facts(connection, release, binding)
        if inspect is not None:
            inspect(connection)
        return result


def copy_to_target(source, destination, limit):
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro&immutable=1', uri=True)) as backup:
        page_size = backup.execute('PRAGMA page_size').fetchone()[0]
        deadline = time.monotonic() + 120

        def progress(_status, _remaining, total):
            require(total * page_size <= limit and time.monotonic() < deadline, UNVERIFIED)

        backup.backup(destination, pages=256, progress=progress)


def prepare_target(source, target, release, old, new, baseline, limit):
    with closing(
        sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, isolation_level=None)
    ) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        if (
            db.execute("SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'").fetchone()
            is None
        ):
            require(
                db.execute('PRAGMA user_version').fetchone() == (0,)
                and db.execute('SELECT 1 FROM sqlite_schema LIMIT 1').fetchone() is None,
                UNVERIFIED,
            )
            copy_to_target(source, db, limit)
        require(db.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',), UNVERIFIED)
        db.execute('BEGIN IMMEDIATE')
        current = db.execute(
            'SELECT data_generation FROM environment_binding WHERE singleton_id=1'
        ).fetchone()
        require(current in ((old.data_generation,), (new.data_generation,)), UNVERIFIED)
        if current[0] == old.data_generation:
            require(verify_binding(db, release, old) == baseline[0], UNVERIFIED)
            require(archived_facts(db, release, old) == baseline, UNVERIFIED)
            changed = db.execute(
                'UPDATE environment_binding SET data_generation=? WHERE singleton_id=1 '
                'AND environment_id=? AND data_generation=?',
                (new.data_generation, old.environment_id, old.data_generation),
            )
            require(changed.rowcount == 1, UNVERIFIED)
        require(verify_binding(db, release, new) == baseline[0], UNVERIFIED)
        require(archived_facts(db, release, new) == baseline, UNVERIFIED)
        db.execute('COMMIT')


def restoration_status(version):
    return (
        'DATABASE_AND_COUNT_AUDIT_RESTORE_VERIFIED' if version == 2 else 'DATABASE_RESTORE_VERIFIED'
    )


def completed(fd, installation, common, plan, capture):
    result = read_local(fd, RECEIPT, installation)
    if result is None:
        return None
    version = common['format_version']
    assets = ('restored_asset_index',) if version == 2 else ()
    exact(
        result,
        (
            *common,
            'status',
            'restored_at',
            'initialized_at',
            'database_artifact',
            'content_sha256',
            'outbound_hold_required',
            *assets,
        ),
        UNVERIFIED,
    )
    require(
        all(result[key] == value for key, value in common.items())
        and result['status'] == restoration_status(version)
        and result['outbound_hold_required'] is True
        and sha_value(result['content_sha256']),
        UNVERIFIED,
    )
    members = {SNAPSHOT, TARGET, RECEIPT}
    if version == 2:
        asset_index = exact(result['restored_asset_index'], ('name', 'bytes', 'sha256'), UNVERIFIED)
        require(asset_index['sha256'] == plan['expected_asset_index_sha256'], UNVERIFIED)
        original = {
            **{key: capture[key] for key in SCOPE_FIELDS},
            'intent_sha256': plan['capture_policy']['sha256'],
            'database_artifact': {'sha256': plan['expected_database_sha256']},
            'asset_index': asset_index,
        }
        members.update(verify_count_audit(installation, fd, capture, original))
    assert_contents(fd, members)
    marker = target_marker(fd, installation, common)
    artifact = snapshot_artifact(
        fd,
        capture['max_database_bytes'],
        installation.maintenance_uid,
        installation.group,
        expected_identity=marker['database_identity'],
    )
    require(result['database_artifact'] == artifact, UNVERIFIED)
    return result


def convert(installation, release, plan, capture, source, destination, fd, common):
    marker = target_marker(fd, installation, common)
    props = safe_target_file(fd, installation, marker['database_identity'])
    source_file = source / SNAPSHOT
    target_file = destination / SNAPSHOT
    old = EnvironmentBinding(installation.environment_id, plan['source_data_generation'])
    new = EnvironmentBinding(installation.environment_id, plan['target_data_generation'])
    baseline = reopen_archive(source_file, release, old)
    maximum = capture['max_database_bytes']
    if stat.S_IMODE(props.st_mode) == 0o600:
        verify_target_sidecars(fd, installation)
        prepare_target(source_file, target_file, release, old, new, baseline, maximum)
    safe_target_file(fd, installation, marker['database_identity'])
    if common['format_version'] == 2 and stat.S_IMODE(props.st_mode) == 0o400:
        members = set(os.listdir(fd))
        require(
            {SNAPSHOT, TARGET} <= members <= {SNAPSHOT, TARGET, AUDIT_COPY, AUDIT_INDEX}, UNVERIFIED
        )
    else:
        assert_contents(fd, {SNAPSHOT, TARGET})
    require(reopen_archive(target_file, release, new) == baseline, UNVERIFIED)
    artifact = snapshot_artifact(
        fd,
        maximum,
        installation.maintenance_uid,
        installation.group,
        expected_identity=marker['database_identity'],
        seal=stat.S_IMODE(props.st_mode) == 0o600,
    )
    return baseline, artifact


def planned_restore(plan, capture, restore_sha):
    target = {
        'recovery_directory': plan['target_directory'],
        'recovery_identity': plan['target_identity'],
        'operation_id': plan['operation_id'],
    }
    backup = Path(capture['recovery_directory'])
    destination = Path(target['recovery_directory'])
    require(
        not backup.is_relative_to(destination) and not destination.is_relative_to(backup), INVALID
    )
    common = {
        'format_version': plan['format_version'],
        'restore_sha256': restore_sha,
        **{
            key: plan[key]
            for key in (
                'operation_id',
                'source_environment_id',
                'source_data_generation',
                'source_deployment_id',
                'target_data_generation',
                'expected_database_sha256',
            )
        },
    }
    if plan['format_version'] == 2:
        common['expected_asset_index_sha256'] = plan['expected_asset_index_sha256']
    return target, common


def restore_database(native, active, args, entry):
    plan, capture = load_restore(args.restore_policy, args.restore_sha256)
    require(capture['installation_sha256'] == args.anchor_sha256, INVALID)
    program = Path(capture['source_program'])
    program_sha = entry['verify_program'](program)
    require(program_sha == capture['source_program_sha256'], INVALID)
    installation, release = admission_inputs(
        SimpleNamespace(anchor=args.anchor, anchor_sha256=args.anchor_sha256, project=program),
        active,
        program_sha,
    )
    installation.check_identity(maintenance=True)
    require(
        all(
            plan['source_' + key] == getattr(installation, key)
            for key in (
                'environment_id',
                'data_generation',
                'deployment_id',
            )
        ),
        INVALID,
    )
    target, common = planned_restore(plan, capture, args.restore_sha256)
    with_assets = plan['format_version'] == 2
    with recovery_directory(target, installation) as (destination, fd):
        try:
            existing = completed(fd, installation, common, plan, capture)
            if existing is not None:
                return existing
            with ExitStack() as opened:
                lock = opened.enter_context(installation.lock(native))
                existing = completed(fd, installation, common, plan, capture)
                if existing is not None:
                    return existing
                installation.check_hold()
                control_fd = opened.enter_context(installation.directory(native, 'control'))
                control = read_control(control_fd, installation)
                require(
                    stopped_for_policy(control_fd, control, plan.get('maintenance'))
                    and control['control_revision'] >= capture['control_revision'],
                    STALE,
                )
                source, source_fd = opened.enter_context(recovery_directory(capture, installation))
                receipt = original_receipt(
                    source_fd, capture, installation, plan['capture_policy']['sha256']
                )
                require(
                    receipt is not None
                    and receipt['database_artifact']['sha256'] == plan['expected_database_sha256'],
                    UNVERIFIED,
                )
                if with_assets:
                    require(
                        receipt['asset_index']['sha256'] == plan['expected_asset_index_sha256'],
                        UNVERIFIED,
                    )
                facts, artifact = convert(
                    installation, release, plan, capture, source, destination, fd, common
                )
                asset_index = None
                if with_assets:
                    asset_index = restore_count_audit(installation, source_fd, fd, capture, receipt)
                require(
                    original_receipt(
                        source_fd, capture, installation, plan['capture_policy']['sha256']
                    )
                    == receipt,
                    UNVERIFIED,
                )
                lock.assert_owned()
                require(read_control(control_fd, installation) == control, STALE)
                installation.check_hold()
                result = {
                    **common,
                    'status': restoration_status(plan['format_version']),
                    'restored_at': utc_milliseconds(datetime.now(timezone.utc)),
                    'initialized_at': facts[0],
                    'content_sha256': facts[1].sha256,
                    'database_artifact': artifact,
                    'outbound_hold_required': True,
                }
                if asset_index is not None:
                    result['restored_asset_index'] = asset_index
                persisted_write(fd, RECEIPT, canonical(result), mode=0o400)
                return completed(fd, installation, common, plan, capture)
        except (OSError, sqlite3.Error, ValueError, SchemaMismatch, EnvironmentFailure) as error:
            if os.listdir(fd):
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
            raise
