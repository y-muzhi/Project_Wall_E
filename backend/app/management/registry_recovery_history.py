"""Read an original management operation from its retained, authorized registry snapshot."""

import sqlite3
from contextlib import closing, contextmanager

from backend.app.infrastructure.environment_backup import SNAPSHOT
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    decode,
    digest,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .management_query import operation_detail
from .operation_contract import CATALOG_NAME, DENIED, INVALID, MISSING, catalog_from_record
from .operation_store import may_read_operation, operation_by_key
from .registry import is_timestamp, registry_version, verify_database
from .registry_installation import SOURCE_ANCHOR, load_installation
from .registry_recovery import PREPARED
from .registry_recovery import RECEIPT as PREPARATION
from .registry_recovery import STORE as RECOVERIES
from .registry_recovery_installation import SELECTION_RECEIPT
from .registry_recovery_outcome import matching_original, outcome_for_operation
from .registry_recovery_selection import INTENT
from .registry_snapshot import RECEIPT as SNAPSHOT_RECEIPT
from .registry_snapshot import STORE as SNAPSHOTS
from .registry_snapshot import (
    descriptor_path,
    read_snapshot,
    snapshot_directory,
    snapshot_metadata,
    snapshot_scope,
)
from .runtime_controls import lookup_control, previous_control

UNVERIFIED = 'MANAGEMENT_PRIOR_REGISTRY_RESULT_UNVERIFIED'


def source_installation(current, runtime_sha, *, expected=None, installer=False):
    with protected_directory(current.directory_root) as directory:
        raw = read_entry(
            directory, SELECTION_RECEIPT, owner=0, group=current.gid, reject_writers=0o337
        )
    require(expected is None or digest(raw) == expected, UNVERIFIED)
    receipt = decode(raw, UNVERIFIED)
    require(
        receipt.get('format_version') == 1
        and receipt.get('status') == INTENT
        and receipt.get('manager_id') == current.manager_id
        and receipt.get('host_id') == current.host_id
        and receipt.get('target_anchor_sha256') == current.sha256
        and receipt.get('target_registry_generation') == current.registry_generation
        and uuid_value(receipt.get('operation_id'))
        and sha_value(receipt.get('recovery_preparation_sha256'))
        and sha_value(receipt.get('source_registry_anchor_sha256')),
        UNVERIFIED,
    )
    source = load_installation(
        current.directory_root / SOURCE_ANCHOR,
        receipt['source_registry_anchor_sha256'],
        runtime_sha,
        installer=installer,
        archived=True,
    )
    require(
        source.registry_generation == receipt.get('source_registry_generation')
        and source.manager_id == current.manager_id
        and source.host_id == current.host_id
        and source.uid == current.uid
        and source.gid == current.gid
        and source.anchor == current.anchor
        and source.root_facts == current.root_facts
        and source.lock_facts == current.lock_facts,
        UNVERIFIED,
    )
    return source, receipt


def find_source(current, generation, runtime_sha):
    seen = {current.registry_generation}
    while current.generation_root_facts is not None:
        source, receipt = source_installation(current, runtime_sha)
        require(source.registry_generation not in seen, UNVERIFIED)
        if source.registry_generation == generation:
            return source, receipt
        seen.add(source.registry_generation)
        current = source
    raise EnvironmentFailure(MISSING)


def archived_preparation(native, source, proof, selection):
    operation = selection['operation_id']
    with (
        snapshot_directory(native, source, proof, RECOVERIES) as recoveries,
        snapshot_directory(native, source, recoveries, operation) as closed,
    ):
        raw = read_entry(
            closed, PREPARATION, owner=source.uid, group=source.gid, reject_writers=0o377
        )
    require(digest(raw) == selection['recovery_preparation_sha256'], UNVERIFIED)
    record = decode(raw, UNVERIFIED)
    require(
        record.get('status') == PREPARED
        and record.get('operation_id') == operation
        and record.get('registry_generation') == source.registry_generation
        and record.get('registry_anchor_sha256') == source.sha256
        and record.get('target_registry_generation') == selection['target_registry_generation']
        and record.get('manager_id') == source.manager_id
        and record.get('host_id') == source.host_id
        and uuid_value(record.get('snapshot_id'))
        and all(
            sha_value(record.get(field)) for field in ('snapshot_receipt_sha256', 'catalog_sha256')
        ),
        UNVERIFIED,
    )
    return record


@contextmanager
def retained_snapshot_metadata(native, source, selection, runtime_sha):
    with source.private_directory(native, 'proof') as proof:
        preparation = archived_preparation(native, source, proof, selection)
        identifier = preparation['snapshot_id']
        pin = preparation['snapshot_receipt_sha256']
        with (
            snapshot_directory(native, source, proof, SNAPSHOTS) as snapshots,
            snapshot_directory(native, source, snapshots, identifier) as directory,
        ):
            receipt = read_entry(
                directory,
                SNAPSHOT_RECEIPT,
                owner=source.uid,
                group=source.gid,
                reject_writers=0o377,
            )
            require(digest(receipt) == pin, UNVERIFIED)
            scope = snapshot_scope(source, preparation['catalog_sha256'], runtime_sha, identifier)
            fields = snapshot_metadata(receipt, source, scope, None)
            require(fields['format_version'] in (2, 3), UNVERIFIED)
            yield directory, {**fields, 'receipt_sha256': pin}


def snapshot_matches_selection_pause(receipt, selection):
    hold = receipt.get('dispatch_hold')
    return (
        hold is not None
        and hold['operation_id'] == selection['operation_id']
        and hold['hold_sha256'] == selection['dispatch_hold_sha256']
    )


def original_snapshot_catalog(native, source, selection, runtime_sha, catalog_pin):
    with retained_snapshot_metadata(native, source, selection, runtime_sha) as (directory, receipt):
        require(receipt['catalog_sha256'] == catalog_pin, UNVERIFIED)
        raw = read_entry(
            directory, CATALOG_NAME, owner=source.uid, group=source.gid, reject_writers=0o377
        )
        require(digest(raw) == catalog_pin, UNVERIFIED)
        return raw


@contextmanager
def historical_snapshot(native, source, selection, runtime_sha):
    with source.private_directory(native, 'proof') as proof:
        preparation = archived_preparation(native, source, proof, selection)
        catalog_pin = preparation['catalog_sha256']
        identifier = preparation['snapshot_id']
        expected = preparation['snapshot_receipt_sha256']
        scope = snapshot_scope(source, catalog_pin, runtime_sha, identifier)
        with (
            snapshot_directory(native, source, proof, SNAPSHOTS) as snapshots,
            snapshot_directory(native, source, snapshots, identifier) as directory,
        ):
            receipt = read_snapshot(directory, source, scope, None, expected=expected)
            require(receipt['format_version'] in (2, 3), UNVERIFIED)
            raw = read_entry(
                directory, CATALOG_NAME, owner=source.uid, group=source.gid, reject_writers=0o377
            )
            require(digest(raw) == catalog_pin, UNVERIFIED)
            path = descriptor_path(directory)
            catalog = catalog_from_record(decode(raw, UNVERIFIED), path, source)
            uri = (path / SNAPSHOT).as_uri() + '?mode=ro&immutable=1'
            with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as connection:
                connection.execute('PRAGMA query_only=ON')
                require(
                    registry_version(connection) == receipt['schema_version']
                    and verify_database(connection, source, integrity=True, journal_mode='delete')
                    == receipt['initialized_at'],
                    UNVERIFIED,
                )
                connection.row_factory = sqlite3.Row
                yield connection, catalog, expected
            require(
                read_snapshot(directory, source, scope, None, expected=expected) == receipt,
                UNVERIFIED,
            )


def recovery_disposition(connection, original):
    outcome = outcome_for_operation(connection, original['operation_id'])
    if outcome is None:
        return None
    require(
        outcome['source_registry_generation'] == original['registry_generation']
        and outcome['source_revision'] == original['revision']
        and outcome['source_intent_sha256'] == original['intent_sha256']
        and is_timestamp(outcome['recorded_at'])
        and matching_original(outcome['disposition'], original['action'], original['status']),
        UNVERIFIED,
    )
    return {
        'operation_id': outcome['operation_id'],
        'source_registry_generation': outcome['source_registry_generation'],
        'source_revision': outcome['source_revision'],
        'recorded_registry_generation': outcome['recorded_registry_generation'],
        'recorded_at': outcome['recorded_at'],
        'disposition': outcome['disposition'],
    }


def prior_result(
    native, current, connection, principal, generation, key, runtime_sha, *, operation=None
):
    require(
        uuid_value(generation)
        and generation != current.registry_generation
        and uuid_value(key)
        and (operation is None or uuid_value(operation)),
        INVALID,
    )
    try:
        source, selection = find_source(current, generation, runtime_sha)
        with historical_snapshot(native, source, selection, runtime_sha) as (
            archived,
            original_catalog,
            snapshot_pin,
        ):
            original_principal = original_catalog.access(principal.id)
            if operation is None:
                row = operation_by_key(archived, generation, key)
                require(row is not None, MISSING)
                require(may_read_operation(connection, principal, row), DENIED)
                result = operation_detail(
                    archived, original_catalog, original_principal, key, by_key=True
                )
            else:
                row = archived.execute(
                    'SELECT * FROM management_operations WHERE operation_id=? AND registry_generation=?',
                    (operation, generation),
                ).fetchone()
                require(row is not None, MISSING)
                require(may_read_operation(connection, principal, row), DENIED)
                control = previous_control(archived, original_catalog, key)
                require(control is not None and control['operation_id'] == operation, MISSING)
                require(control['principal'] == principal.id or principal.role == 'MANAGER', DENIED)
                result = lookup_control(
                    archived, original_catalog, original_principal, key, {'operation_id': operation}
                )
            disposition = recovery_disposition(connection, row)
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        if getattr(error, 'code', None) in (INVALID, DENIED, MISSING):
            raise
        raise EnvironmentFailure(UNVERIFIED) from error
    response = {
        'source_registry_generation': generation,
        'snapshot_receipt_sha256': snapshot_pin,
        'result': result,
    }
    if disposition is not None:
        response['recovery_disposition'] = disposition
    return response
