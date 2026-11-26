"""Verify an ordinary RESTORE's frozen source, chosen backup and fixed target."""

from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from backend.app.management.attachment_observation import now
from backend.app.management.recovery_evidence import backup_cutoff, parse_local_recovery
from backend.app.management.recovery_offhost import offhost_authority, offhost_metadata
from backend.app.management.registry import is_timestamp

from .environment_backup_coverage import LockedBackupCoverage, locked_coverage
from .environment_backup_rehearsal import POLICY as DATA_POLICY
from .environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    read_protected,
    require,
)
from .environment_installation import sha_value, uuid_value, version_record
from .environment_recovery_installation import checked_ref
from .environment_release_preflight import (
    CAPTURE_POLICY,
    backup_point_from_manifest,
    candidate_target,
    read_reference,
    verified_backup,
)
from .schema_v22_release import SchemaRelease

POLICY = 'restore-source-preflight.v1.json'
OFFHOST_POLICY = 'restore-source-preflight.v2.json'
POLICIES = {POLICY: 1, OFFHOST_POLICY: 2}
OFFHOST_FIELDS = ('offhost_authority', 'offhost_verification')
INVALID = 'RESTORE_PREFLIGHT_INTENT_MISMATCH'
UNVERIFIED = 'RESTORE_PREFLIGHT_UNVERIFIED'


def restore_plan(path, expected):
    version = POLICIES.get(path.name)
    require(path.is_absolute() and version is not None and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    plan = decode(raw, INVALID)
    fields = (
        'operation_id',
        'installation_sha256',
        'source_data_generation',
        'source_deployment_id',
        'source_control_revision',
        'source_configuration_sha256',
        'preserved',
        'selected',
        'accepted_backup_cutoff_at',
        'data_handling',
        'candidate_proof',
        'target_manifest',
        'target_schema_directory',
        'target_data_generation',
        'target_deployment_id',
        'target_configuration_sha256',
        'data_preparation',
    )
    if version == 2:
        exact(plan, ('format_version', *fields, *OFFHOST_FIELDS), INVALID)
        require(type(plan['format_version']) is int and plan['format_version'] == 2, INVALID)
        offhost_authority(plan['offhost_authority'], INVALID)
        reference = exact(plan['offhost_verification'], ('path', 'sha256'), INVALID)
        require(sha_value(reference['sha256']), INVALID)
    else:
        version_record(plan, fields, INVALID)
    preserved = exact(plan['preserved'], ('backup_id', 'capture_policy', 'verification'), INVALID)
    selected = exact(plan['selected'], ('backup_id', 'verification', 'local_verification'), INVALID)
    require(
        all(
            uuid_value(plan[key])
            for key in (
                'operation_id',
                'source_data_generation',
                'source_deployment_id',
                'target_data_generation',
                'target_deployment_id',
            )
        )
        and uuid_value(preserved['backup_id'])
        and uuid_value(selected['backup_id'])
        and len({plan['operation_id'], preserved['backup_id'], selected['backup_id']}) == 3
        and all(
            sha_value(plan[key])
            for key in (
                'installation_sha256',
                'source_configuration_sha256',
                'target_configuration_sha256',
            )
        )
        and type(plan['source_control_revision']) is int
        and 1 <= plan['source_control_revision'] < MAX_REVISION
        and is_timestamp(plan['accepted_backup_cutoff_at'])
        and plan['data_handling'] == 'PRESERVE_CURRENT_SOURCE',
        INVALID,
    )
    require(
        plan['target_data_generation'] != plan['source_data_generation']
        and plan['target_deployment_id'] != plan['source_deployment_id'],
        INVALID,
    )
    checked_ref(plan['data_preparation'], DATA_POLICY)
    return plan


def restore_authorization(plan):
    # The frozen maintenance intent precedes capture of the current source.
    chosen = {
        **plan,
        'preserved': {'backup_id': plan['preserved']['backup_id']},
    }
    return digest(canonical(chosen))


@dataclass(frozen=True)
class RestorePreflight:
    plan: dict
    receipt: dict
    schema: SchemaRelease
    source: LockedBackupCoverage


def confirm_current_source(plan, source):
    facts = source.facts
    control = source.control
    require(
        (control['admission'], control['closed_reason'], control['outbound_hold'])
        == ('CLOSED', 'MAINTENANCE', True)
        and control['operation_id'] == control['maintenance_id'] == plan['operation_id']
        and control['plan_sha256'] == restore_authorization(plan)
        and control['control_revision'] == plan['source_control_revision']
        and (facts['data_generation'], facts['deployment_id'], facts['configuration_sha256'])
        == (
            plan['source_data_generation'],
            plan['source_deployment_id'],
            plan['source_configuration_sha256'],
        )
        and facts['operation_id'] == plan['preserved']['backup_id'],
        UNVERIFIED,
    )


def selected_offhost_report(plan, point, environment_id, ceiling, code):
    reference = plan['offhost_verification']
    try:
        report = read_reference(reference)
    except (EnvironmentFailure, OSError) as error:
        raise EnvironmentFailure(code) from error
    metadata = offhost_metadata(
        report, point, environment_id, ceiling, plan['offhost_authority'], code
    )
    return {**metadata, 'verification_sha256': reference['sha256']}


def verify_selection(args, plan, source, target_schema):
    preserved = plan['preserved']
    chosen = plan['selected']
    before, before_sha, before_coverage = verified_backup(
        args, preserved['verification'], preserved['backup_id']
    )
    require(before_coverage == source.facts, UNVERIFIED)
    selected, selected_sha, selected_coverage = verified_backup(
        args, chosen['verification'], chosen['backup_id']
    )
    local = parse_local_recovery(read_reference(chosen['local_verification']), UNVERIFIED)
    accepted_cutoff = backup_cutoff(selected['cutoff_at'], UNVERIFIED)
    require(
        accepted_cutoff == plan['accepted_backup_cutoff_at']
        and accepted_cutoff <= backup_cutoff(before['cutoff_at'], UNVERIFIED)
        and before['source_environment_id']
        == selected['source_environment_id']
        == local['environment_id']
        == source.installation.environment_id
        and local['backup_id'] == selected['backup_id']
        and local['backup_manifest_sha256'] == selected_sha
        and local['logical_content_sha256'] == selected['logical_content_sha256']
        and local['runtime_manifest_sha256'] == selected_coverage['runtime_manifest_sha256']
        and local['schema_manifest_sha256'] == selected_coverage['schema_manifest_sha256']
        and accepted_cutoff <= local['verified_at']
        and local['data_generation'] != selected['source_data_generation']
        and local['deployment_id'] != selected['source_deployment_id']
        and plan['target_data_generation']
        not in (
            local['data_generation'],
            selected['source_data_generation'],
        )
        and plan['target_deployment_id']
        not in (
            local['deployment_id'],
            selected['source_deployment_id'],
        )
        and before_coverage['schema_contract_sha256']
        == selected_coverage['schema_contract_sha256']
        == target_schema.schema_contract_sha256,
        UNVERIFIED,
    )
    offhost = {}
    if plan['format_version'] == 2:
        point = backup_point_from_manifest(selected, selected_sha, UNVERIFIED)
        verified = selected_offhost_report(
            plan, point, source.installation.environment_id, now(), UNVERIFIED
        )
        offhost = {'selected_offhost_verification_sha256': verified['verification_sha256']}
    return before, before_sha, selected, selected_sha, offhost


@contextmanager
def locked_restore_preflight(native, active, args, entry):
    plan = restore_plan(args.restore_preflight_policy, args.restore_preflight_policy_sha256)
    require(plan['installation_sha256'] == args.anchor_sha256, INVALID)
    candidate, release, schema, program = candidate_target(plan, active)
    capture_path, capture_sha = checked_ref(plan['preserved']['capture_policy'], CAPTURE_POLICY)
    capture = SimpleNamespace(
        anchor=args.anchor,
        anchor_sha256=args.anchor_sha256,
        capture_policy=capture_path,
        capture_sha256=capture_sha,
    )
    with locked_coverage(native, active, capture, entry) as source:
        confirm_current_source(plan, source)
        before, before_sha, selected, selected_sha, offhost = verify_selection(
            args, plan, source, schema
        )
        source.lock.assert_owned()
        observed = {
            'format_version': 1,
            'status': 'CLOSED_RESTORE_PRECONDITIONS_VERIFIED',
            'restore_preflight_policy_sha256': args.restore_preflight_policy_sha256,
            'operation_id': plan['operation_id'],
            'maintenance_plan_sha256': source.control['plan_sha256'],
            'data_preparation_policy_sha256': plan['data_preparation']['sha256'],
            'environment_id': source.installation.environment_id,
            'source_data_generation': source.facts['data_generation'],
            'source_deployment_id': source.facts['deployment_id'],
            'source_control_revision': source.facts['control_revision'],
            'source_control_sha256': digest(canonical(source.control)),
            'source_database_identity': source.database_identity,
            'source_configuration_sha256': source.facts['configuration_sha256'],
            'preserved_backup_id': before['backup_id'],
            'preserved_backup_manifest_sha256': before_sha,
            'preserved_result_index_sha256': before['original_result_index_ref']['sha256'],
            'preserved_cutoff_at': backup_cutoff(before['cutoff_at'], UNVERIFIED),
            'selected_backup_id': selected['backup_id'],
            'selected_source_data_generation': selected['source_data_generation'],
            'selected_source_deployment_id': selected['source_deployment_id'],
            'selected_backup_manifest_sha256': selected_sha,
            'selected_result_index_sha256': selected['original_result_index_ref']['sha256'],
            'selected_logical_content_sha256': selected['logical_content_sha256'],
            'selected_backup_cutoff_at': plan['accepted_backup_cutoff_at'],
            'selected_local_verification_sha256': plan['selected']['local_verification']['sha256'],
            **offhost,
            'data_handling': plan['data_handling'],
            'target_release_id': release['release_id'],
            'target_release_manifest_sha256': candidate['manifest_sha256'],
            'target_program_snapshot_sha256': program,
            'target_schema_manifest_sha256': release['schema_manifest_sha256'],
            'target_frontend_index_sha256': release['frontend_index_ref']['sha256'],
            'target_data_generation': plan['target_data_generation'],
            'target_deployment_id': plan['target_deployment_id'],
            'target_configuration_sha256': plan['target_configuration_sha256'],
            'schema_contract_sha256': schema.schema_contract_sha256,
            'outbound_hold_required': True,
        }
        receipt = {**observed, 'restore_preflight_sha256': digest(canonical(observed))}
        yield RestorePreflight(plan, receipt, schema, source)


def preflight_restore(native, active, args, entry):
    with locked_restore_preflight(native, active, args, entry) as verified:
        return verified.receipt
