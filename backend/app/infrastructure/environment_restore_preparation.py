"""Prepare one planned restored database while the original remains locked and closed."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from .environment_backup import SNAPSHOT
from .environment_backup_package import VERIFY_POLICY, read_evidence, read_manifest
from .environment_backup_rehearsal import (
    POLICY as DATA_POLICY,
    anchored_path,
    data_rehearsal,
    principal_for_process,
    rehearsal_directories,
    rehearsal_inputs,
    recovery_contract,
)
from .environment_binding import EnvironmentBinding
from .environment_control import read_control
from .environment_files import absolute, canonical, decode, digest, require
from .environment_recovery_installation import checked_ref
from .environment_release_preflight import read_reference
from .environment_restore import RECEIPT, completed, reopen_archive, restoration_status
from .environment_restore_preflight import RestorePreflight, locked_restore_preflight
from .environment_result_archive import read_sealed

INVALID = 'RESTORE_DATA_PREPARATION_INTENT_MISMATCH'
UNVERIFIED = 'RESTORE_DATA_PREPARATION_UNVERIFIED'


def target_inputs(args, verified):
    policy, pin = checked_ref(verified.plan['data_preparation'], DATA_POLICY)
    data_args = SimpleNamespace(
        anchor=policy,
        anchor_sha256=pin,
        root=args.root,
        project=args.project,
        home=args.home,
        temporary=args.temporary,
    )
    plan, backup, selected_root, target, schema = rehearsal_inputs(data_args)
    receipt = verified.receipt
    require(
        plan['operation_id'] == receipt['operation_id']
        and plan['package_verification'] == verified.plan['selected']['verification']
        and plan['source_environment_id'] == receipt['environment_id']
        and plan['target_data_generation'] == receipt['target_data_generation']
        and backup['backup_id'] == receipt['selected_backup_id']
        and backup['backup_manifest_sha256'] == receipt['selected_backup_manifest_sha256'],
        INVALID,
    )
    preservation = read_reference(verified.plan['preserved']['verification'], name=VERIFY_POLICY)
    preserved_root = absolute(preservation['package_directory'], INVALID)
    boundaries = (verified.source.installation.environment_root, preserved_root)
    require(
        all(
            not (target.is_relative_to(root) or root.is_relative_to(target)) for root in boundaries
        ),
        INVALID,
    )
    return data_args, plan, backup, selected_root, target, schema


@dataclass(frozen=True)
class RestoreTarget:
    verified: RestorePreflight
    plan: dict
    backup: dict
    selected_fd: int
    target_fd: int
    schema: Path
    policy_sha256: str
    principal: SimpleNamespace


@contextmanager
def locked_restore_target(native, active, args, entry):
    with locked_restore_preflight(native, active, args, entry) as verified:
        data_args, plan, backup, selected, target, schema = target_inputs(args, verified)
        principal = principal_for_process()
        with rehearsal_directories(
            principal, selected, backup['package_identity'], target, plan['target_identity']
        ) as (source_fd, target_fd):
            yield RestoreTarget(
                verified,
                plan,
                backup,
                source_fd,
                target_fd,
                schema,
                data_args.anchor_sha256,
                principal,
            )


def target_receipt(directory, principal, verified, record):
    raw = read_sealed(directory, RECEIPT, principal)
    proof = verified.receipt
    binding = EnvironmentBinding(proof['environment_id'], proof['target_data_generation'])
    initialized, logical = reopen_archive(
        anchored_path(directory) / SNAPSHOT, verified.schema, binding
    )
    require(
        record == decode(raw, UNVERIFIED)
        and record['target_data_generation'] == proof['target_data_generation']
        and record['operation_id'] == proof['operation_id']
        and record['backup_manifest_sha256'] == proof['selected_backup_manifest_sha256']
        and record['initialized_at'] == initialized
        and record['content_sha256'] == logical.sha256 == proof['selected_logical_content_sha256']
        and record['outbound_hold_required'] is True,
        UNVERIFIED,
    )
    require(read_sealed(directory, RECEIPT, principal) == raw, UNVERIFIED)
    return record, digest(raw)


def restore_data_result(target, receipt):
    verified = target.verified
    record, recorded_sha = target_receipt(target.target_fd, target.principal, verified, receipt)
    source = verified.source
    source.lock.assert_owned()
    source.installation.check_hold()
    require(read_control(source.control_fd, source.installation) == source.control, UNVERIFIED)
    proof = verified.receipt
    result = {
        'format_version': 1,
        'status': 'RESTORE_TARGET_DATA_PREPARED',
        **{
            key: proof[key]
            for key in (
                'operation_id',
                'environment_id',
                'restore_preflight_sha256',
                'source_control_sha256',
                'source_database_identity',
                'preserved_backup_manifest_sha256',
                'preserved_result_index_sha256',
                'selected_backup_manifest_sha256',
                'selected_source_data_generation',
                'selected_source_deployment_id',
                'selected_result_index_sha256',
                'target_data_generation',
                'target_deployment_id',
                'target_configuration_sha256',
                'target_program_snapshot_sha256',
                'target_schema_manifest_sha256',
                'target_frontend_index_sha256',
                'schema_contract_sha256',
            )
        },
        'target_data_identity': target.plan['target_identity'],
        'target_restore_receipt_sha256': recorded_sha,
        'target_database_sha256': record['database_artifact']['sha256'],
        'target_asset_index_sha256': record['restored_asset_index']['sha256'],
        'target_restored_at': record['restored_at'],
        'selected_logical_content_sha256': record['content_sha256'],
        'outbound_hold_required': True,
    }
    return {**result, 'restore_target_data_sha256': digest(canonical(result))}


def prepare_restore_data(native, active, args, entry):
    with locked_restore_target(native, active, args, entry) as target:
        prepared = data_rehearsal(
            target.principal,
            target.schema,
            target.selected_fd,
            target.target_fd,
            target.plan,
            target.backup,
            active,
            target.policy_sha256,
        )
        require(
            prepared['original_result_index_sha256']
            == target.verified.receipt['selected_result_index_sha256'],
            UNVERIFIED,
        )
        record = {
            key: value if key != 'status' else restoration_status(2)
            for key, value in prepared.items()
            if key not in ('verification_status', 'original_result_index_sha256')
        }
        return restore_data_result(target, record)


def inspect_prepared_data(target):
    manifest, _ = read_manifest(
        target.selected_fd,
        target.principal,
        target.backup['backup_id'],
        expected_manifest=target.backup['backup_manifest_sha256'],
    )
    evidence = read_evidence(target.selected_fd, target.principal, manifest)
    planned, captured, common = recovery_contract(target.plan, target.backup, manifest, evidence)
    common['rehearsal_policy_sha256'] = target.policy_sha256
    record = completed(target.target_fd, target.principal, common, planned, captured)
    require(record is not None, UNVERIFIED)
    return restore_data_result(target, record)
