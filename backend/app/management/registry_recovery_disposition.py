"""Record a verified original disposition while the selected registry remains paused."""

import os

from backend.app.infrastructure.environment_backup_package import read_policy
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    digest,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import (
    identity_record,
    sha_value,
    uuid_value,
)

from .attachment_observation import now
from .operation_contract import installed_record
from .operation_store import mutation
from .registry import registry_version, verified_locked_registry
from .registry_dispatch import (
    dispatch_lock,
    hold_bytes,
    hold_receipt,
    hold_scope,
    require_current_dispatch_anchor,
)
from .registry_recovery_backup import completed_backup_evidence
from .registry_recovery_history import (
    historical_snapshot,
    retained_snapshot_metadata,
    snapshot_matches_selection_pause,
    source_installation,
)
from .registry_recovery_outcome import (
    COLUMNS,
    ORIGINAL_STATES,
    UNVERIFIED,
    add_outcome,
    outcome_for_operation,
)
from .registry_recovery_reobserve import original_catalog
from .registry_recovery_undispatched import (
    ORIGINAL_FIELDS,
    UNDISPATCHED,
    undispatched_start_evidence,
)
from .registry_schema import RECOVERY_RESOLUTION_SCHEMA_VERSION
from .registry_snapshot import snapshot_directory

POLICY = 'registry-recovery-disposition-policy.v1.json'
RECEIPTS = 'registry-recovery-dispositions'
RECORDED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPOSITION_RECORDED'
CURRENT_FIELDS = ('manager_id', 'host_id', 'registry_generation', 'registry_anchor_sha256')
PINS = ('selection_receipt_sha256', 'source_snapshot_sha256', 'source_catalog_sha256')
FIELDS = (
    *CURRENT_FIELDS,
    'recovery_operation_id',
    *ORIGINAL_FIELDS,
    *PINS,
    'source_catalog_directory_identity',
    'disposition',
)


def disposition_policy(installation, args):
    record = read_policy(
        args.registry_disposition_policy, args.registry_disposition_policy_sha256, POLICY, FIELDS
    )
    require(
        record['manager_id'] == installation.manager_id
        and record['host_id'] == installation.host_id
        and record['registry_generation'] == installation.registry_generation
        and record['registry_anchor_sha256'] == installation.sha256
        and record['source_registry_generation'] != installation.registry_generation
        and all(
            uuid_value(record[key])
            for key in ('recovery_operation_id', 'source_registry_generation', 'operation_id')
        )
        and all(sha_value(record[key]) for key in (*PINS, 'source_intent_sha256'))
        and record['source_catalog_sha256'] == args.catalog_sha256
        and type(record['source_revision']) is int
        and 1 <= record['source_revision'] <= MAX_REVISION
        and type(record['disposition']) is str
        and record['disposition'] in ORIGINAL_STATES,
        UNVERIFIED,
    )
    identity_record(record['source_catalog_directory_identity'], UNVERIFIED)
    return record


def original_disposition_source(native, current, root, args, policy):
    source, selected = source_installation(
        current, args.sha256, expected=policy['selection_receipt_sha256']
    )
    raw = hold_bytes(root, current)
    require(
        source.registry_generation == policy['source_registry_generation']
        and selected['operation_id'] == policy['recovery_operation_id']
        and raw is not None,
        UNVERIFIED,
    )
    current_hold = hold_receipt(raw, hold_scope(source, policy['recovery_operation_id']))
    require(current_hold['hold_sha256'] == selected['dispatch_hold_sha256'], UNVERIFIED)
    with retained_snapshot_metadata(native, source, selected, args.sha256) as (_, snapshot):
        require(
            snapshot_matches_selection_pause(snapshot, selected)
            and snapshot['receipt_sha256'] == policy['source_snapshot_sha256']
            and snapshot['catalog_sha256'] == policy['source_catalog_sha256'],
            UNVERIFIED,
        )
    return source, selected


def require_no_start_publication(catalog, evidence):
    operation = evidence['operation_id']
    observations = catalog.directory / 'observations'
    try:
        with protected_directory(observations) as directory:
            for name in (
                f'start-{operation}.v1.json',
                f'prepare-{operation}.v1.json',
                f'start-runtime-{operation}',
            ):
                try:
                    os.stat(name, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise EnvironmentFailure(UNVERIFIED)
    except FileNotFoundError:
        return
    try:
        lease = installed_record(observations / f'start-claim-{evidence["environment_id"]}.v1.json')
    except FileNotFoundError:
        return
    holder = lease.get('start_operation_id')
    require(uuid_value(holder) and holder != operation, UNVERIFIED)


def disposition_outcome(current, source_pin, policy_pin, policy, evidence):
    return {
        **{field: policy[field] for field in ORIGINAL_FIELDS},
        'recorded_registry_generation': current.registry_generation,
        'source_snapshot_sha256': source_pin,
        'policy_sha256': policy_pin,
        'evidence_sha256': digest(canonical(evidence)),
        'disposition': evidence['disposition'],
    }


def disposition_receipt(policy, outcome, evidence):
    return {
        'format_version': 1,
        'status': RECORDED,
        **{
            key: policy[key]
            for key in (*CURRENT_FIELDS, 'recovery_operation_id', 'selection_receipt_sha256')
        },
        'outcome': {key: outcome[key] for key in COLUMNS},
        'evidence': evidence,
    }


def receipt_bytes(directory, identifier, installation):
    try:
        return read_entry(
            directory,
            identifier + '.json',
            owner=installation.uid,
            group=installation.gid,
            reject_writers=0o377,
        )
    except FileNotFoundError:
        return None


def disposition_evidence(connection, catalog, policy):
    if policy['disposition'] == UNDISPATCHED:
        evidence = undispatched_start_evidence(connection, policy)
        require_no_start_publication(catalog, evidence)
        return evidence
    return completed_backup_evidence(connection, catalog, policy)


def record_disposition(connection, lock, directory, current, catalog, policy, expected, evidence):
    identifier = expected['operation_id']
    previous = receipt_bytes(directory, identifier, current)
    with mutation(connection, lock):
        outcome = outcome_for_operation(connection, identifier)
        require(disposition_evidence(connection, catalog, policy) == evidence, UNVERIFIED)
        if outcome is None:
            require(previous is None, UNVERIFIED)
            outcome = {**expected, 'recorded_at': now()}
            add_outcome(connection, outcome)
        require(all(outcome[key] == value for key, value in expected.items()), UNVERIFIED)
        receipt = disposition_receipt(policy, outcome, evidence)
        raw = canonical(receipt)
        require(previous is None or previous == raw, UNVERIFIED)
    try:
        if previous is None:
            persisted_write(directory, identifier + '.json', raw, mode=0o400)
        lock.assert_owned()
        require(receipt_bytes(directory, identifier, current) == raw, UNVERIFIED)
    except (OSError, EnvironmentFailure) as error:
        raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return {**receipt, 'receipt_sha256': digest(raw)}


def settle_registry_recovery_disposition(native, installation, args):
    policy = disposition_policy(installation, args)
    with dispatch_lock(installation, exclusive=False) as root, installation.lock(native) as lock:
        require_current_dispatch_anchor(root, installation)
        source, selected = original_disposition_source(native, installation, root, args, policy)
        catalog, _, directory_identity = original_catalog(native, source, selected, args)
        require(directory_identity == policy['source_catalog_directory_identity'], UNVERIFIED)
        with historical_snapshot(native, source, selected, args.sha256) as (connection, _, pin):
            require(pin == policy['source_snapshot_sha256'], UNVERIFIED)
            evidence = disposition_evidence(connection, catalog, policy)
        outcome = disposition_outcome(
            installation, pin, args.registry_disposition_policy_sha256, policy, evidence
        )
        with (
            verified_locked_registry(native, installation, lock, read_only=False) as connection,
            installation.private_directory(native, 'proof') as proof,
        ):
            require(registry_version(connection) == RECOVERY_RESOLUTION_SCHEMA_VERSION, UNVERIFIED)
            try:
                os.mkdir(RECEIPTS, mode=0o700, dir_fd=proof)
            except FileExistsError:
                pass
            os.fsync(proof)
            with snapshot_directory(native, installation, proof, RECEIPTS) as directory:
                return record_disposition(
                    connection, lock, directory, installation, catalog, policy, outcome, evidence
                )
