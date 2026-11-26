"""Prepare and verify a separate, closed management registry generation."""

from contextlib import closing, contextmanager
from dataclasses import replace
import os
import sqlite3
from tempfile import TemporaryDirectory
from time import monotonic

from backend.app.infrastructure.environment_backup import SNAPSHOT, snapshot_artifact
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    read_entry,
    read_protected,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .attachment_observation import now
from .registry import REGISTRY_APP_ID, is_timestamp, verify_database
from .registry_dispatch import PAUSED, observe_dispatch
from .registry_schema import (
    OUTCOME_TABLE,
    RECOVERY_TABLES,
    RECOVERY_TRIGGERS,
    RECOVERY_RESOLUTION_SCHEMA_VERSION,
    RESTORED_SCHEMA_VERSION,
)
from .registry_snapshot import (
    MAX_SQLITE_BYTES,
    STORE as SNAPSHOTS,
    descriptor_path,
    read_snapshot,
    reopen_snapshot,
    snapshot_directory,
    snapshot_scope,
)

STORE = 'registry-recoveries'
POLICY = 'registry-recovery-policy.v1.json'
RECEIPT = 'registry-recovery-preparation.v1.json'
PREPARED = 'MANAGEMENT_REGISTRY_RECOVERY_PREPARED_CLOSED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_UNVERIFIED'
HISTORICAL_TABLES = (
    'managed_environments',
    'management_operations',
    'management_controls',
    'management_steps',
    'resource_claims',
    'delivery_snapshots',
)


def recovery_scope(installation, args):
    path, pin = args.registry_recovery_policy, args.registry_recovery_policy_sha256
    require(path.name == POLICY and sha_value(pin), UNVERIFIED)
    raw = read_protected(path)
    require(digest(raw) == pin, UNVERIFIED)
    value = decode(raw, UNVERIFIED)
    format_version = value.get('format_version')
    require(type(format_version) is int and format_version in (1, 2), UNVERIFIED)
    explicit = ('target_schema_version',) if format_version == 2 else ()
    exact(
        value,
        (
            'format_version',
            'operation_id',
            'registry_anchor_sha256',
            'registry_generation',
            'dispatch_hold_sha256',
            'snapshot_id',
            'snapshot_receipt_sha256',
            'catalog_sha256',
            'target_registry_generation',
            *explicit,
        ),
        UNVERIFIED,
    )
    version = value.get('target_schema_version', RESTORED_SCHEMA_VERSION)
    require(
        type(version) is int
        and version in RECOVERY_TABLES
        and value['registry_anchor_sha256'] == installation.sha256
        and value['registry_generation'] == installation.registry_generation
        and value['target_registry_generation'] != installation.registry_generation
        and all(
            uuid_value(value[field])
            for field in ('operation_id', 'snapshot_id', 'target_registry_generation')
        )
        and all(
            sha_value(value[field])
            for field in ('dispatch_hold_sha256', 'snapshot_receipt_sha256', 'catalog_sha256')
        ),
        UNVERIFIED,
    )
    return {
        **value,
        'status': PREPARED,
        'manager_id': installation.manager_id,
        'host_id': installation.host_id,
        'runtime_manifest_sha256': args.sha256,
        'recovery_policy_sha256': pin,
        'schema_version': version,
        'journal_mode': 'delete',
    }


def verify_pause(installation, scope):
    hold = observe_dispatch(installation, scope['operation_id'])
    require(
        hold['status'] == PAUSED and hold['hold_sha256'] == scope['dispatch_hold_sha256'],
        UNVERIFIED,
    )


@contextmanager
def original_snapshot(native, installation, proof, scope):
    expected = snapshot_scope(
        installation,
        scope['catalog_sha256'],
        scope['runtime_manifest_sha256'],
        scope['snapshot_id'],
    )
    with (
        snapshot_directory(native, installation, proof, SNAPSHOTS) as snapshots,
        snapshot_directory(native, installation, snapshots, scope['snapshot_id']) as source,
    ):
        receipt = read_snapshot(
            source, installation, expected, None, expected=scope['snapshot_receipt_sha256']
        )
        require(receipt['format_version'] in (2, 3), UNVERIFIED)
        database = descriptor_path(source) / SNAPSHOT
        reopen_snapshot(
            database, installation, receipt['initialized_at'], version=receipt['schema_version']
        )
        yield database, receipt['schema_version']
        require(
            read_snapshot(
                source, installation, expected, None, expected=scope['snapshot_receipt_sha256']
            )
            == receipt,
            UNVERIFIED,
        )


def populate_database(connection, scope, source_version, prepared_at):
    version = scope['schema_version']
    require(version in RECOVERY_TABLES and source_version <= version, UNVERIFIED)
    for statement in RECOVERY_TABLES[version]:
        connection.execute(statement)
    if source_version >= RESTORED_SCHEMA_VERSION:
        connection.execute(
            'INSERT INTO registry_generations SELECT registry_generation '
            'FROM original.registry_generations'
        )
    else:
        connection.execute(
            'INSERT INTO registry_generations VALUES (?)', (scope['registry_generation'],)
        )
    connection.execute(
        'INSERT INTO registry_generations VALUES (?)', (scope['target_registry_generation'],)
    )
    connection.execute(
        'INSERT INTO manager_state VALUES (1, ?, ?, ?, ?, ?)',
        (
            version,
            scope['manager_id'],
            scope['host_id'],
            scope['target_registry_generation'],
            prepared_at,
        ),
    )
    for table in HISTORICAL_TABLES:
        connection.execute(f'INSERT INTO {table} SELECT * FROM original.{table}')
    connection.execute(
        'INSERT INTO management_plans SELECT * FROM original.management_plans '
        'WHERE execution_operation_id IS NOT NULL'
    )
    if source_version >= RECOVERY_RESOLUTION_SCHEMA_VERSION:
        connection.execute(f'INSERT INTO {OUTCOME_TABLE} SELECT * FROM original.{OUTCOME_TABLE}')
    for statement in RECOVERY_TRIGGERS[version]:
        connection.execute(statement)
    connection.execute(f'PRAGMA application_id={REGISTRY_APP_ID}')
    connection.execute(f'PRAGMA user_version={version}')


def reopened_installation(installation, scope):
    return replace(installation, registry_generation=scope['target_registry_generation'])


def build_database(original, source_version, target, installation, scope, prepared_at):
    deadline = monotonic() + 120
    with closing(sqlite3.connect(target.as_uri(), uri=True, isolation_level=None)) as connection:
        connection.set_progress_handler(lambda: int(monotonic() >= deadline), 2048)
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA synchronous=FULL')
        require(connection.execute('PRAGMA foreign_keys').fetchone() == (1,), UNVERIFIED)
        connection.execute(
            'ATTACH DATABASE ? AS original', (original.as_uri() + '?mode=ro&immutable=1',)
        )
        connection.execute('BEGIN IMMEDIATE')
        populate_database(connection, scope, source_version, prepared_at)
        require(
            verify_database(
                connection,
                reopened_installation(installation, scope),
                integrity=True,
                journal_mode='delete',
            )
            == prepared_at,
            UNVERIFIED,
        )
        connection.execute('COMMIT')
        connection.execute('DETACH DATABASE original')


def recovery_file_receipt(directory, installation, scope, *, expected=None):
    raw = read_entry(
        directory, RECEIPT, owner=installation.uid, group=installation.gid, reject_writers=0o377
    )
    pin = digest(raw)
    require(expected is None or pin == expected, UNVERIFIED)
    record = exact(
        decode(raw, UNVERIFIED), (*scope, 'prepared_at', 'database_artifact'), UNVERIFIED
    )
    require(
        all(canonical(record[key]) == canonical(value) for key, value in scope.items())
        and is_timestamp(record['prepared_at'])
        and set(os.listdir(directory)) == {SNAPSHOT, RECEIPT},
        UNVERIFIED,
    )
    require(
        snapshot_artifact(directory, MAX_SQLITE_BYTES, installation.uid, installation.gid)
        == record['database_artifact'],
        UNVERIFIED,
    )
    return {**record, 'receipt_sha256': pin}


def read_recovery(directory, installation, scope, *, expected=None):
    record = recovery_file_receipt(directory, installation, scope, expected=expected)
    reopen_snapshot(
        descriptor_path(directory) / SNAPSHOT,
        reopened_installation(installation, scope),
        record['prepared_at'],
        version=scope['schema_version'],
    )
    return record


def stage_recovery(native, installation, parent, source, source_version, scope, lock):
    output = descriptor_path(parent)
    with TemporaryDirectory(prefix='.walle-registry-recovery-', dir=output) as temporary:
        target = output / os.path.basename(temporary)
        prepared = now()
        build_database(source, source_version, target / SNAPSHOT, installation, scope, prepared)
        with snapshot_directory(native, installation, parent, target.name) as stage:
            artifact = snapshot_artifact(
                stage, MAX_SQLITE_BYTES, installation.uid, installation.gid, seal=True
            )
            persisted_write(
                stage,
                RECEIPT,
                canonical({**scope, 'prepared_at': prepared, 'database_artifact': artifact}),
                mode=0o400,
            )
            read_recovery(stage, installation, scope)
            os.fsync(stage)
        lock.assert_owned()
        verify_pause(installation, scope)
        publish_directory(target, output / scope['operation_id'])


def prepare_registry_recovery(native, installation, args):
    scope = recovery_scope(installation, args)
    with (
        installation.lock(native) as lock,
        installation.private_directory(native, 'proof') as proof,
    ):
        verify_pause(installation, scope)
        with original_snapshot(native, installation, proof, scope) as (source, version):
            try:
                os.mkdir(STORE, mode=0o700, dir_fd=proof)
            except FileExistsError:
                pass
            os.fsync(proof)
            with snapshot_directory(native, installation, proof, STORE) as parent:
                if scope['operation_id'] not in os.listdir(parent):
                    stage_recovery(native, installation, parent, source, version, scope, lock)
                try:
                    with snapshot_directory(
                        native, installation, parent, scope['operation_id']
                    ) as published:
                        result = read_recovery(published, installation, scope)
                    os.fsync(parent)
                    lock.assert_owned()
                    verify_pause(installation, scope)
                except (OSError, sqlite3.Error, EnvironmentFailure) as error:
                    raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return result


def verify_registry_recovery(native, installation, args):
    scope = recovery_scope(installation, args)
    pin = args.registry_recovery_receipt_sha256
    require(sha_value(pin), UNVERIFIED)
    with (
        installation.private_directory(native, 'proof') as proof,
        snapshot_directory(native, installation, proof, STORE) as parent,
        snapshot_directory(native, installation, parent, scope['operation_id']) as published,
    ):
        result = read_recovery(published, installation, scope, expected=pin)
        require(read_recovery(published, installation, scope, expected=pin) == result, UNVERIFIED)
    return {**result, 'status': 'MANAGEMENT_REGISTRY_RECOVERY_REOPENED_CLOSED'}
