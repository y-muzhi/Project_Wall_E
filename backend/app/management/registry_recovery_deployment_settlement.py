"""Record the settled deployment in the selected registry while preserving original history."""

import os
import sqlite3

from backend.app.infrastructure.environment_backup_package import read_policy
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    persisted_write,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value

from .attachment_observation import now
from .operation_store import decoded, environment_row, mutation
from .registry import registry_version, verified_locked_registry
from .registry_recovery_capacity import measured_capacity, settle_capacity
from .registry_recovery_deployment_authorization import authorized_deployment
from .registry_recovery_disposition import (
    RECEIPTS,
    SOURCE_FIELDS,
    disposition_outcome,
    disposition_receipt,
    receipt_bytes,
)
from .registry_recovery_opened import (
    assessment_result,
    locked_opening_inputs,
    opened_claims_digest,
    opened_registration_projection,
)
from .registry_recovery_outcome import (
    OPENED_DEPLOYMENT,
    UNSTARTED_STEPS,
    add_outcome,
    disposition_schema,
    outcome_for_operation,
)
from .registry_recovery_undispatched import original_operation
from .registry_snapshot import snapshot_directory
from .release_reconciliation import update_opened_registration
from .runtime_capacity import DIMENSIONS, reservations_for

POLICY = 'registry-recovery-settle-opened-policy.v1.json'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_SETTLEMENT_UNVERIFIED'


def licensed_opening(current, policy, pin, assessed, target):
    proof_sha = policy['authorization_sha256']
    require(sha_value(proof_sha), UNVERIFIED)
    authorization = authorized_deployment(current, policy['operation_id'], proof_sha)
    original = assessed['result']
    verified = authorization['verification']
    require(
        authorization['assessment_sha256']
        == assessment_result(current, policy, pin, assessed)['assessment_sha256']
        and all(
            verified[key] == policy[key]
            for key in (
                'recovery_operation_id',
                'source_registry_generation',
                'selection_receipt_sha256',
            )
        )
        and verified['environment_id'] == assessed['environment_id']
        and verified['opened_receipt_sha256'] == assessed['opened_receipt_sha256']
        and all(
            verified['target'][key] == original[key]
            for key in (
                'environment_id',
                'data_generation',
                'deployment_id',
                'configuration_sha256',
                'run_id',
            )
        )
        and verified['target']['program_sha256'] == target['program_source']
        and verified['management_entry']['candidate_sha256']
        == decoded(target['configuration_ref'])['sha256'],
        UNVERIFIED,
    )
    return {
        **{
            key: policy[key]
            for key in (
                'operation_id',
                'source_registry_generation',
                'source_revision',
                'source_intent_sha256',
            )
        },
        'disposition': OPENED_DEPLOYMENT,
        'original_status': 'RUNNING',
        'action': assessed['action'],
        'environment_id': assessed['environment_id'],
        'step_kind': UNSTARTED_STEPS[assessed['action']],
        'step_status': 'DISPATCHING',
        'assessment_sha256': authorization['assessment_sha256'],
        'authorization_sha256': proof_sha,
        'target_registration_sha256': assessed['target_registration_sha256'],
        'target': verified['target'],
        'opened_receipt_sha256': verified['opened_receipt_sha256'],
        'stop_operation_id': verified['stop_operation_id'],
        'stop_receipt_sha256': verified['stop_receipt_sha256'],
        'management_entry_sha256': digest(canonical(verified['management_entry'])),
    }


def settle_in_registry(
    connection, lock, directory, current, catalog, args, policy, archived, pin, verify_scope
):
    previous, target, assessed = opened_registration_projection(
        archived, catalog, policy, args.sha256
    )
    identifier = policy['operation_id']
    environment = assessed['environment_id']
    evidence = licensed_opening(current, policy, pin, assessed, target)
    capacity = measured_capacity(reservations_for(archived, identifier), environment)
    require(capacity['count'] == len(DIMENSIONS), UNVERIFIED)
    evidence['capacity'] = capacity
    release = {
        key: evidence[key]
        for key in (
            'disposition',
            'authorization_sha256',
            'stop_operation_id',
            'stop_receipt_sha256',
        )
    }
    expected = disposition_outcome(
        current, pin, args.registry_disposition_policy_sha256, policy, evidence
    )
    existing = receipt_bytes(directory, identifier, current)
    with mutation(connection, lock):
        outcome = outcome_for_operation(connection, identifier)
        if outcome is None:
            require(existing is None, UNVERIFIED)
            copied = opened_registration_projection(connection, catalog, policy, args.sha256)
            require(copied == (previous, target, assessed), UNVERIFIED)
            update_opened_registration(connection, previous, target)
            outcome = {**expected, 'recorded_at': now()}
            add_outcome(connection, outcome)
            recorded = False
        else:
            require(all(outcome[key] == value for key, value in expected.items()), UNVERIFIED)
            recorded = True
        settle_capacity(connection, identifier, environment, capacity, release, recorded=recorded)
        current_row = environment_row(connection, environment)
        require(
            current_row is not None
            and dict(current_row) == target
            and original_operation(connection, policy) == original_operation(archived, policy)
            and opened_claims_digest(connection, policy, released=True)
            == assessed['claims_sha256'],
            UNVERIFIED,
        )
        verify_scope()
        receipt = disposition_receipt(policy, outcome, evidence)
        raw = canonical(receipt)
        require(existing is None or existing == raw, UNVERIFIED)
    try:
        if existing is None:
            persisted_write(directory, identifier + '.json', raw, mode=0o400)
        verify_scope()
        require(receipt_bytes(directory, identifier, current) == raw, UNVERIFIED)
    except (OSError, EnvironmentFailure) as error:
        raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return {**receipt, 'receipt_sha256': digest(raw)}


def settle_opened_deployment(native, installation, args):
    try:
        policy = read_policy(
            args.registry_disposition_policy,
            args.registry_disposition_policy_sha256,
            POLICY,
            (*SOURCE_FIELDS, 'authorization_sha256'),
        )
        with (
            locked_opening_inputs(native, installation, args, policy) as (
                catalog,
                lock,
                archive,
                pin,
                verify_scope,
            ),
            verified_locked_registry(native, installation, lock, read_only=False) as connection,
            installation.private_directory(native, 'proof') as proof,
        ):
            operation = original_operation(archive, policy)
            require(
                registry_version(connection)
                >= disposition_schema(OPENED_DEPLOYMENT, action=operation['action']),
                UNVERIFIED,
            )
            try:
                os.mkdir(RECEIPTS, mode=0o700, dir_fd=proof)
            except FileExistsError:
                pass
            os.fsync(proof)
            with snapshot_directory(native, installation, proof, RECEIPTS) as directory:
                return settle_in_registry(
                    connection,
                    lock,
                    directory,
                    installation,
                    catalog,
                    args,
                    policy,
                    archive,
                    pin,
                    verify_scope,
                )
    except EnvironmentFailure:
        raise
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
