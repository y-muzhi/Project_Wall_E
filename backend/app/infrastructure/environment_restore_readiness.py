"""Check independently verified read-only recovery against one prepared restore."""

from pathlib import Path

from backend.app.management.attachment_observation import now
from backend.app.management.recovery_evidence import parse_local_recovery

from .environment_backup_package import read_policy
from .environment_files import canonical, digest, require
from .environment_installation import sha_value
from .environment_release_preflight import read_reference
from .environment_restore_preparation import inspect_prepared_data, locked_restore_target

POLICY = 'restore-readiness-policy.v1.json'
INVALID = 'RESTORE_READINESS_INTENT_MISMATCH'
UNVERIFIED = 'RESTORE_READINESS_UNVERIFIED'


def readiness_inputs(args):
    plan = read_policy(
        args.restore_readiness_policy,
        args.restore_readiness_policy_sha256,
        POLICY,
        ('restore_preflight_sha256', 'restore_target_data_sha256', 'read_verification'),
    )
    require(
        sha_value(plan['restore_preflight_sha256'])
        and sha_value(plan['restore_target_data_sha256']),
        INVALID,
    )
    read = parse_local_recovery(read_reference(plan['read_verification']), UNVERIFIED)
    require(
        Path(plan['read_verification']['path']).name
        == f'local-verified-{read["verification_id"]}.v1.json',
        INVALID,
    )
    return plan, read


def verify_prepared_readiness(args, active, verified, actual, plan, read):
    expected_read = {
        'environment_id': actual['environment_id'],
        'data_generation': actual['target_data_generation'],
        'deployment_id': actual['target_deployment_id'],
        'backup_id': verified['selected_backup_id'],
        'backup_manifest_sha256': actual['selected_backup_manifest_sha256'],
        'rehearsal_receipt_sha256': actual['target_restore_receipt_sha256'],
        'schema_manifest_sha256': actual['target_schema_manifest_sha256'],
        'program_snapshot_sha256': actual['target_program_snapshot_sha256'],
        'frontend_index_sha256': actual['target_frontend_index_sha256'],
        'database_sha256': actual['target_database_sha256'],
        'logical_content_sha256': actual['selected_logical_content_sha256'],
        'runtime_manifest_sha256': active.runtime_manifest_sha256,
    }
    require(
        plan['restore_preflight_sha256'] == actual['restore_preflight_sha256']
        and plan['restore_target_data_sha256'] == actual['restore_target_data_sha256']
        and all(read[field] == value for field, value in expected_read.items())
        and read['configuration_sha256'] != actual['target_configuration_sha256']
        and actual['target_restored_at'] <= read['verified_at'] <= now(),
        UNVERIFIED,
    )
    observed = {
        'format_version': 1,
        'status': 'RESTORE_PREPARED_COPY_VERIFIED',
        'restore_readiness_policy_sha256': args.restore_readiness_policy_sha256,
        'operation_id': actual['operation_id'],
        'environment_id': actual['environment_id'],
        'source_control_sha256': actual['source_control_sha256'],
        'restore_preflight_sha256': actual['restore_preflight_sha256'],
        'restore_target_data_sha256': actual['restore_target_data_sha256'],
        'target_data_generation': actual['target_data_generation'],
        'target_deployment_id': actual['target_deployment_id'],
        'target_configuration_sha256': actual['target_configuration_sha256'],
        'read_only_configuration_sha256': read['configuration_sha256'],
        'read_verification_sha256': plan['read_verification']['sha256'],
        'verified_scopes': read['verified_scopes'],
        'verified_at': read['verified_at'],
        'outbound_hold_required': True,
    }
    return {**observed, 'restore_readiness_sha256': digest(canonical(observed))}


def check_restore_readiness(native, active, args, entry):
    plan, read = readiness_inputs(args)
    with locked_restore_target(native, active, args, entry) as target:
        actual = inspect_prepared_data(target)
        return verify_prepared_readiness(args, active, target.verified.receipt, actual, plan, read)
