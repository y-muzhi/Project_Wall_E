"""Make an inactive, attested registry generation ready for its fixed WAL runtime."""

from contextlib import contextmanager
import os
from time import monotonic

from backend.app.infrastructure.environment_backup import SNAPSHOT
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value

from .attachment_observation import now
from .registry import (
    INITIALIZED_NAME,
    INTENT_NAME,
    facts,
    is_timestamp,
    marker,
    open_registry,
    registry_version,
    verify_database,
)
from .registry_installation import GENERATIONS
from .registry_recovery import (
    HISTORICAL_TABLES,
    STORE,
    recovery_file_receipt,
    recovery_scope,
    verify_pause,
)
from .registry_recovery_installation import measured_database, placement_scope, read_slot_record
from .registry_schema import OUTCOME_TABLE, RECOVERY_RESOLUTION_SCHEMA_VERSION
from .registry_snapshot import descriptor_path, snapshot_directory

INTENT = 'registry-recovery-wal-intent.v1.json'
READY = 'registry-recovery-ready.v1.json'
VERIFIED = 'MANAGEMENT_REGISTRY_INSTALLATION_READY_CLOSED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_READINESS_UNVERIFIED'
TABLES = (
    'manager_state',
    'registry_generations',
    *HISTORICAL_TABLES,
    'management_plans',
    'environment_observations',
)


def readiness_scope(target, placement):
    return {
        'format_version': 1,
        'status': VERIFIED,
        'operation_id': placement['operation_id'],
        'target_anchor_sha256': target.sha256,
        'target_registry_generation': target.registry_generation,
        'target_database_identity': target.database_facts,
        'placement_receipt_sha256': placement['placement_receipt_sha256'],
        'prepared_at': placement['prepared_at'],
        'journal_mode': 'wal',
    }


def held_proof(proof, name, target):
    try:
        return read_entry(proof, name, owner=target.uid, group=target.gid, reject_writers=0o377)
    except FileNotFoundError:
        return None


def publish_fact(proof, name, target, value):
    raw = canonical(value)
    previous = held_proof(proof, name, target)
    if previous is None:
        persisted_write(proof, name, raw, mode=0o400)
        previous = held_proof(proof, name, target)
    require(previous == raw, UNVERIFIED)


def verify_initialization(proof, target, placement):
    attempted = marker(proof, INTENT_NAME, target)
    initialized = marker(proof, INITIALIZED_NAME, target)
    require(
        attempted is not None
        and initialized is not None
        and initialized['initialized_at'] == placement['prepared_at'],
        UNVERIFIED,
    )


def read_selected_readiness(proof, target, expected):
    raw = held_proof(proof, READY, target)
    require(raw is not None and digest(raw) == expected, UNVERIFIED)
    receipt = decode(raw, UNVERIFIED)
    verify_initialization(proof, target, receipt)
    return {**receipt, 'readiness_receipt_sha256': expected}


def read_ready(proof, target, placement, measured):
    raw = held_proof(proof, READY, target)
    if raw is None:
        return None
    scope = readiness_scope(target, placement)
    value = exact(
        decode(raw, UNVERIFIED),
        (*scope, 'database_bytes', 'database_sha256', 'verified_at'),
        UNVERIFIED,
    )
    require(
        all(canonical(value[key]) == canonical(item) for key, item in scope.items())
        and is_timestamp(value['verified_at'])
        and value['verified_at'] >= scope['prepared_at']
        and (value['database_bytes'], value['database_sha256']) == measured
        and held_proof(proof, INTENT, target) == canonical(scope),
        UNVERIFIED,
    )
    verify_initialization(proof, target, placement)
    return {**value, 'readiness_receipt_sha256': digest(raw)}


def compare_prepared_data(connection, archive):
    connection.execute(
        'ATTACH DATABASE ? AS prepared', (archive.as_uri() + '?mode=ro&immutable=1',)
    )
    try:
        tables = TABLES
        if registry_version(connection) >= RECOVERY_RESOLUTION_SCHEMA_VERSION:
            tables = (*tables, OUTCOME_TABLE)
        for table in tables:
            for left, right in (('main', 'prepared'), ('prepared', 'main')):
                change = connection.execute(
                    f'SELECT 1 FROM (SELECT * FROM {left}.{table} EXCEPT SELECT * FROM {right}.{table}) LIMIT 1'
                ).fetchone()
                require(change is None, UNVERIFIED)
    finally:
        connection.execute('DETACH DATABASE prepared')


def make_wal_ready(native, target, data, proof, placement, archive, lock):
    scope = readiness_scope(target, placement)
    first = held_proof(proof, INTENT, target)
    if first is None:
        require(
            measured_database(native, target)
            == (placement['source_database_bytes'], placement['source_database_sha256']),
            UNVERIFIED,
        )
        with open_registry(native, target, data, read_only=True) as database:
            require(
                verify_database(database, target, integrity=True, journal_mode='delete')
                == scope['prepared_at'],
                UNVERIFIED,
            )
        lock.assert_owned()
    publish_fact(proof, INTENT, target, scope)
    deadline = monotonic() + 120
    with open_registry(native, target, data, read_only=False) as database:
        database.set_progress_handler(lambda: int(monotonic() >= deadline), 2048)
        mode = database.execute('PRAGMA main.journal_mode').fetchone()
        require(mode in (('delete',), ('wal',)), UNVERIFIED)
        if mode == ('delete',):
            require(
                measured_database(native, target)
                == (placement['source_database_bytes'], placement['source_database_sha256']),
                UNVERIFIED,
            )
            lock.assert_owned()
            require(
                database.execute('PRAGMA main.journal_mode=WAL').fetchone() == ('wal',), UNVERIFIED
            )
        require(
            verify_database(database, target, integrity=True) == scope['prepared_at'], UNVERIFIED
        )
        compare_prepared_data(database, archive)
    measured = measured_database(native, target)
    lock.assert_owned()
    publish_fact(proof, INTENT_NAME, target, facts(target))
    publish_fact(
        proof, INITIALIZED_NAME, target, {**facts(target), 'initialized_at': scope['prepared_at']}
    )
    publish_fact(
        proof,
        READY,
        target,
        {
            **scope,
            'database_bytes': measured[0],
            'database_sha256': measured[1],
            'verified_at': now(),
        },
    )


@contextmanager
def recovery_material(native, installation, args, recovery):
    pin = args.registry_recovery_receipt_sha256
    require(sha_value(pin), UNVERIFIED)
    with (
        installation.private_directory(native, 'proof') as proof,
        snapshot_directory(native, installation, proof, STORE) as store,
        snapshot_directory(native, installation, store, recovery['operation_id']) as archive,
    ):
        source = recovery_file_receipt(archive, installation, recovery, expected=pin)
        yield source, descriptor_path(archive) / SNAPSHOT
        require(
            recovery_file_receipt(archive, installation, recovery, expected=pin) == source,
            UNVERIFIED,
        )


@contextmanager
def prepared_slot(native, installation, args, recovery, *, installer):
    pin = args.registry_placement_receipt_sha256
    require(sha_value(pin), UNVERIFIED)
    path = installation.anchor.parent / GENERATIONS / recovery['target_registry_generation']
    with recovery_material(native, installation, args, recovery) as (source, archive):
        scope = placement_scope(installation, args, recovery, source)
        placement, target = read_slot_record(
            installation, args, path, scope, installer=installer, expected=pin
        )
        yield placement, target, archive


def ready_registry_recovery(native, installation, args):
    recovery = recovery_scope(installation, args)
    with installation.lock(native) as lock:
        verify_pause(installation, recovery)
        with prepared_slot(native, installation, args, recovery, installer=False) as (
            placement,
            target,
            archive,
        ):
            with (
                target.private_directory(native, 'data') as data,
                target.private_directory(native, 'proof') as proof,
            ):
                measured = measured_database(native, target)
                if read_ready(proof, target, placement, measured) is None:
                    make_wal_ready(native, target, data, proof, placement, archive, lock)
                try:
                    result = read_ready(proof, target, placement, measured_database(native, target))
                    require(result is not None, UNVERIFIED)
                    # Use a writable SQLite handle for its normal WAL sidecar cleanup.
                    with open_registry(native, target, data, read_only=False) as database:
                        database.execute('PRAGMA query_only=ON')
                        require(
                            verify_database(database, target, integrity=True)
                            == result['prepared_at'],
                            UNVERIFIED,
                        )
                    require(
                        result
                        == read_ready(proof, target, placement, measured_database(native, target)),
                        UNVERIFIED,
                    )
                    lock.assert_owned()
                    verify_pause(installation, recovery)
                    os.fsync(proof)
                except (OSError, ValueError, EnvironmentFailure) as error:
                    raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return result
