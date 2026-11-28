"""Take an independent, restartable SQLite snapshot of the management registry."""

from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
import time

from backend.app.infrastructure.environment_backup import SNAPSHOT, snapshot_artifact
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    no_acl,
    persisted_write,
    protected_directory,
    read_entry,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .attachment_observation import now
from .operation_contract import CATALOG_NAME, INVALID
from .registry import is_timestamp, registry_version, verified_registry, verify_database
from .registry_dispatch import PAUSED, hold_receipt, hold_scope, observe_dispatch
from .registry_installation import ANCHOR_NAME, read_registry_anchor
from .registry_schema import SCHEMAS, SCHEMA_VERSION

STORE = 'registry-snapshots'
RECEIPT = 'management-registry-snapshot.v1.json'
VERIFIED = 'MANAGEMENT_REGISTRY_SNAPSHOT_VERIFIED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_SNAPSHOT_UNVERIFIED'
MAX_SQLITE_BYTES = (1 << 63) - 1


@contextmanager
def snapshot_directory(native, installation, parent, name):
    fd = native.open_beneath(parent, name, os.O_DIRECTORY | os.O_RDONLY)
    try:
        measured = os.fstat(fd)
        require(
            stat.S_ISDIR(measured.st_mode)
            and (measured.st_uid, measured.st_gid, stat.S_IMODE(measured.st_mode))
            == (installation.uid, installation.gid, 0o700),
            UNVERIFIED,
        )
        check_ext4(fd)
        no_acl(fd)
        yield fd
    finally:
        os.close(fd)


def descriptor_path(directory):
    return Path('/proc/self/fd') / str(directory)


def snapshot_scope(installation, catalog_sha, runtime_sha, operation, schema_version=None):
    return {
        'format_version': 2,
        'status': VERIFIED,
        'operation_id': operation,
        'manager_id': installation.manager_id,
        'host_id': installation.host_id,
        'registry_generation': installation.registry_generation,
        'registry_anchor_sha256': installation.sha256,
        'catalog_sha256': catalog_sha,
        'runtime_manifest_sha256': runtime_sha,
        'schema_version': schema_version,
        'journal_mode': 'delete',
    }


def snapshot_metadata(raw, installation, scope, initialized_at, *, capture=False):
    copied = decode(raw, UNVERIFIED)
    format_version = copied.get('format_version')
    version = copied.get('schema_version')
    require(
        type(format_version) is int
        and format_version in (1, 2, 3)
        and type(version) is int
        and version in SCHEMAS
        and (format_version != 1 or version == SCHEMA_VERSION)
        and (scope['schema_version'] is None or scope['schema_version'] == version)
        and (not capture or scope['format_version'] == format_version),
        UNVERIFIED,
    )
    expected = {**scope, 'format_version': format_version, 'schema_version': version}
    if format_version == 3:
        held = snapshot_hold_metadata(copied.get('dispatch_hold'), installation)
        require(
            scope.get('dispatch_hold', held) == held
            and is_timestamp(copied.get('snapshot_at'))
            and held['paused_at'] <= copied['snapshot_at'],
            UNVERIFIED,
        )
        expected['dispatch_hold'] = held
    exact(copied, (*expected, 'initialized_at', 'snapshot_at', 'database_artifact'), UNVERIFIED)
    require(
        all(canonical(copied[key]) == canonical(value) for key, value in expected.items())
        and is_timestamp(copied['initialized_at'])
        and (initialized_at is None or copied['initialized_at'] == initialized_at)
        and is_timestamp(copied['snapshot_at'])
        and copied['initialized_at'] <= copied['snapshot_at'],
        UNVERIFIED,
    )
    return copied


def snapshot_hold_metadata(held, installation):
    exact(held, ('operation_id', 'hold_sha256', 'paused_at'), UNVERIFIED)
    scope = hold_scope(installation, held['operation_id'])
    marker = canonical({**scope, 'paused_at': held['paused_at']})
    receipt = hold_receipt(marker, scope)
    require(receipt['hold_sha256'] == held['hold_sha256'], UNVERIFIED)
    return held


def read_snapshot(fd, installation, scope, initialized_at, *, expected=None, capture=False):
    raw = read_entry(
        fd, RECEIPT, owner=installation.uid, group=installation.gid, reject_writers=0o377
    )
    pin = digest(raw)
    require(expected is None or pin == expected, UNVERIFIED)
    copied = snapshot_metadata(raw, installation, scope, initialized_at, capture=capture)
    allowed = {SNAPSHOT, RECEIPT}
    if copied['format_version'] in (2, 3):
        allowed.update((ANCHOR_NAME, CATALOG_NAME))
        for name, checksum in archived_record_pins(scope).items():
            data = read_entry(
                fd, name, owner=installation.uid, group=installation.gid, reject_writers=0o377
            )
            require(digest(data) == checksum, UNVERIFIED)
    require(set(os.listdir(fd)) == allowed, UNVERIFIED)
    file = snapshot_artifact(fd, MAX_SQLITE_BYTES, installation.uid, installation.gid)
    require(copied['database_artifact'] == file, UNVERIFIED)
    return {**copied, 'receipt_sha256': pin}


def copy_registry_database(source, destination, installation, initialized_at):
    deadline = time.monotonic() + 120

    def within_deadline(*_):
        require(time.monotonic() < deadline, UNVERIFIED)

    with closing(sqlite3.connect(destination.as_uri(), uri=True, isolation_level=None)) as target:
        target.execute('PRAGMA synchronous=FULL')
        source.backup(target, pages=256, progress=within_deadline)
        require(target.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',), UNVERIFIED)
    reopen_snapshot(destination, installation, initialized_at)


def reopen_snapshot(destination, installation, initialized_at, *, version=None):
    with closing(sqlite3.connect(destination.as_uri() + '?mode=ro&immutable=1', uri=True)) as check:
        require(
            (version is None or registry_version(check) == version)
            and verify_database(check, installation, integrity=True, journal_mode='delete')
            == initialized_at,
            UNVERIFIED,
        )


def archived_record_pins(scope):
    return {
        ANCHOR_NAME: scope['registry_anchor_sha256'],
        CATALOG_NAME: scope['catalog_sha256'],
    }


def source_records(installation, args, scope):
    require(args.catalog.name == CATALOG_NAME, INVALID)
    with protected_directory(installation.anchor.parent) as parent:
        _, anchor = read_registry_anchor(parent, installation.anchor.name)
    records = {ANCHOR_NAME: anchor, CATALOG_NAME: read_protected(args.catalog)}
    require(
        all(digest(records[name]) == pin for name, pin in archived_record_pins(scope).items()),
        UNVERIFIED,
    )
    return records


def prepare_snapshot(
    source, native, installation, parent, operation, scope, initialized_at, records
):
    location = descriptor_path(parent)
    with TemporaryDirectory(prefix='.walle-registry-snapshot-', dir=location) as temporary:
        stage = Path(temporary)
        cutoff = now()
        copy_registry_database(source, stage / SNAPSHOT, installation, initialized_at)
        with snapshot_directory(native, installation, parent, stage.name) as fd:
            require(set(os.listdir(fd)) == {SNAPSHOT}, UNVERIFIED)
            artifact = snapshot_artifact(
                fd, MAX_SQLITE_BYTES, installation.uid, installation.gid, seal=True
            )
            for name, raw in records.items():
                persisted_write(fd, name, raw, mode=0o400)
            persisted_write(
                fd,
                RECEIPT,
                canonical(
                    {
                        **scope,
                        'initialized_at': initialized_at,
                        'snapshot_at': cutoff,
                        'database_artifact': artifact,
                    }
                ),
                mode=0o400,
            )
            read_snapshot(fd, installation, scope, initialized_at, capture=True)
            os.fsync(fd)
        publish_directory(stage, location / operation)


def active_snapshot_hold(installation, args):
    operation = getattr(args, 'registry_snapshot_hold_id', None)
    expected = getattr(args, 'registry_snapshot_hold_sha256', None)
    if operation is None and expected is None:
        return None
    require(uuid_value(operation) and sha_value(expected), INVALID)
    observed = observe_dispatch(installation, operation, current_only=True)
    require(observed['status'] == PAUSED and observed['hold_sha256'] == expected, UNVERIFIED)
    return {key: observed[key] for key in ('operation_id', 'hold_sha256', 'paused_at')}


def snapshot_registry(native, installation, args):
    operation = args.registry_snapshot_id
    require(
        uuid_value(operation) and sha_value(args.catalog_sha256) and sha_value(args.sha256), INVALID
    )
    with (
        verified_registry(native, installation, writable=False) as (source, lock),
        installation.private_directory(native, 'proof') as proof,
    ):
        initialized = source.execute('SELECT initialized_at FROM manager_state').fetchone()[0]
        scope = snapshot_scope(
            installation, args.catalog_sha256, args.sha256, operation, registry_version(source)
        )
        hold = active_snapshot_hold(installation, args)
        if hold is not None:
            scope = {**scope, 'format_version': 3, 'dispatch_hold': hold}
        try:
            os.mkdir(STORE, mode=0o700, dir_fd=proof)
        except FileExistsError:
            pass
        os.fsync(proof)
        with snapshot_directory(native, installation, proof, STORE) as parent:
            if operation not in os.listdir(parent):
                lock.assert_owned()
                prepare_snapshot(
                    source,
                    native,
                    installation,
                    parent,
                    operation,
                    scope,
                    initialized,
                    source_records(installation, args, scope),
                )
            try:
                with snapshot_directory(native, installation, parent, operation) as published:
                    result = read_snapshot(
                        published, installation, scope, initialized, capture=True
                    )
                require(active_snapshot_hold(installation, args) == hold, UNVERIFIED)
                os.fsync(parent)
                lock.assert_owned()
            except (OSError, ValueError, EnvironmentFailure) as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return result


def verify_registry_snapshot(native, installation, args):
    operation = args.registry_snapshot_id
    pin = args.registry_snapshot_receipt_sha256
    require(
        uuid_value(operation)
        and all(sha_value(value) for value in (pin, args.catalog_sha256, args.sha256)),
        INVALID,
    )
    scope = snapshot_scope(installation, args.catalog_sha256, args.sha256, operation)
    with (
        installation.private_directory(native, 'proof') as proof,
        snapshot_directory(native, installation, proof, STORE) as store,
        snapshot_directory(native, installation, store, operation) as published,
    ):
        receipt = read_snapshot(published, installation, scope, None, expected=pin)
        reopen_snapshot(
            descriptor_path(published) / SNAPSHOT,
            installation,
            receipt['initialized_at'],
            version=receipt['schema_version'],
        )
        require(
            read_snapshot(published, installation, scope, None, expected=pin) == receipt, UNVERIFIED
        )
    return {**receipt, 'status': 'MANAGEMENT_REGISTRY_SNAPSHOT_REOPENED'}
