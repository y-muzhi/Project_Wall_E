"""Verify a sealed ordinary backup independently of its source installation."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
from types import SimpleNamespace

from .environment_backup import SNAPSHOT, assert_contents, snapshot_artifact
from .environment_backup_assets import (
    AUDIT_INDEX,
    SCOPE_FIELDS,
    audit_directory,
    verify_count_audit,
)
from .environment_files import (
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    protected_directory,
    read_protected,
    require,
)
from .environment_installation import identity_record, sha_value, uuid_value
from .environment_result_archive import (
    INDEX,
    indexed_summary,
    original_result,
    read_index,
    read_sealed,
    read_shard,
    scope_key,
)

MANIFEST = 'backup-manifest.v1.json'
PACKAGE = 'package'
RESULTS = 'original-results'
VERIFY_POLICY = 'backup-package-verification.v1.json'
INVALID = 'BACKUP_PACKAGE_INTENT_MISMATCH'
UNVERIFIED = 'BACKUP_PACKAGE_UNVERIFIED'
LIMITS = {'max_audit_files': 512, 'max_audit_bytes': 1024**4}
PROGRAM_FIELDS = (
    'program_sha256',
    'configuration_sha256',
    'runtime_manifest_sha256',
    'schema_manifest_sha256',
    'schema_contract_sha256',
)
SOURCE_FIELDS = {
    'source_environment_id': 'environment_id',
    'source_data_generation': 'data_generation',
    'source_deployment_id': 'deployment_id',
    'source_control_revision': 'control_revision',
    'cutoff_at': 'cutoff_at',
}
EVIDENCE = {
    'capture_receipt_ref': 'database-capture-receipt.v1.json',
    'coverage_ref': 'ordinary-backup-coverage.v1.json',
    'restore_verification_ref': 'database-restore-verification.v1.json',
    'recovery_chain_ref': 'recovery-chain.v1.json',
}


def read_policy(path, expected, filename, fields):
    require(path.is_absolute() and path.name == filename and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    record = exact(decode(raw, INVALID), ('format_version', *fields), INVALID)
    require(type(record['format_version']) is int and record['format_version'] == 1, INVALID)
    return record


def validate_location(record, folder_field, identity_field, boundaries):
    folder = absolute(record[folder_field], INVALID)
    identity_record(record[identity_field], INVALID)
    require(
        not any(folder.is_relative_to(root) or root.is_relative_to(folder) for root in boundaries),
        INVALID,
    )
    return folder


@contextmanager
def private_root(folder, expected, principal):
    with protected_directory(folder.parent) as parent:
        with audit_directory(
            parent, folder.name, principal.maintenance_uid, principal.group, source=False
        ) as directory:
            require(identity(os.fstat(directory)) == expected, UNVERIFIED)
            yield directory


def anchored_path(directory):
    return Path(f'/proc/self/fd/{directory}')


def principal_for_process():
    require(os.geteuid() != 0, INVALID)
    return SimpleNamespace(maintenance_uid=os.geteuid(), group=os.getegid())


def reference(path, raw):
    return {'path': path, 'bytes': len(raw), 'sha256': digest(raw)}


def genuine_digest(record, key):
    stripped = {name: value for name, value in record.items() if name != key}
    require(record.get(key) == digest(canonical(stripped)), UNVERIFIED)
    return record[key]


def read_evidence(directory, principal, manifest):
    records = {}
    for key, filename in EVIDENCE.items():
        raw = read_sealed(directory, filename, principal)
        require(manifest[key] == reference(filename, raw), UNVERIFIED)
        records[key] = decode(raw, UNVERIFIED)
    return records


def check_evidence(manifest, evidence, expected_chain):
    capture = evidence['capture_receipt_ref']
    coverage = evidence['coverage_ref']
    restore = evidence['restore_verification_ref']
    chain = evidence['recovery_chain_ref']
    program = exact(manifest['program_and_configuration_refs'], PROGRAM_FIELDS, UNVERIFIED)
    require(
        genuine_digest(chain, 'recovery_chain_sha256') == manifest['recovery_chain_sha256']
        and (expected_chain is None or expected_chain == manifest['recovery_chain_sha256'])
        and chain['status'] == 'RECOVERY_COMPONENTS_MATCHED'
        and coverage['status'] == 'ORDINARY_BACKUP_COVERAGE_CHECKED'
        and capture['format_version'] == restore['format_version'] == 2
        and restore['status'] == 'DATABASE_AND_COUNT_AUDIT_RESTORE_VERIFIED',
        UNVERIFIED,
    )
    require(
        manifest['backup_id'] == capture['operation_id'] == chain['backup_id']
        and all(
            manifest[key] == capture[source] == coverage[source]
            for key, source in SOURCE_FIELDS.items()
        )
        and all(
            chain[key.removeprefix('source_')] == manifest[key]
            for key in ('source_environment_id', 'cutoff_at')
        )
        and all(
            chain[key] == manifest[key]
            for key in ('source_data_generation', 'source_deployment_id', 'source_control_revision')
        )
        and all(capture[key] == coverage[key] for key in (*SCOPE_FIELDS, 'asset_index')),
        UNVERIFIED,
    )
    require(
        capture['intent_sha256'] == coverage['capture_policy_sha256']
        and coverage['capture_receipt_sha256'] == manifest['capture_receipt_ref']['sha256']
        and genuine_digest(coverage, 'coverage_sha256') == chain['coverage_sha256']
        and manifest['restore_verification_ref']['sha256'] == chain['restore_receipt_sha256']
        and manifest['original_result_index_ref']['sha256'] == chain['result_index_sha256'],
        UNVERIFIED,
    )
    require(
        capture['database_artifact']['sha256']
        == coverage['database_sha256']
        == chain['database_sha256']
        == restore['expected_database_sha256']
        and capture['asset_index'] == chain['asset_index'] == restore['restored_asset_index']
        and manifest['logical_content_sha256']
        == coverage['logical_content_sha256']
        == chain['logical_content_sha256']
        == restore['content_sha256'],
        UNVERIFIED,
    )
    require(
        restore['source_environment_id'] == capture['environment_id']
        and restore['source_data_generation'] == capture['data_generation']
        and restore['source_deployment_id'] == capture['deployment_id']
        and restore['operation_id'] == chain['restore_operation_id']
        and restore['target_data_generation'] == chain['target_data_generation']
        and uuid_value(restore['target_data_generation'])
        and restore['target_data_generation'] != capture['data_generation']
        and restore['outbound_hold_required'] is chain['outbound_hold_required'] is True,
        UNVERIFIED,
    )
    require(
        all(sha_value(value) for value in program.values())
        and all(program[key] == coverage[key] for key in PROGRAM_FIELDS),
        UNVERIFIED,
    )
    return capture


def read_package_index(directory, principal, capture, expected_reference, expected_common=None):
    raw = read_sealed(directory, INDEX, principal)
    require(expected_reference == reference(f'{RESULTS}/{INDEX}', raw), UNVERIFIED)
    value = decode(raw, UNVERIFIED)
    common = {
        'format_version': 1,
        'operation_id': value['operation_id'],
        'policy_sha256': value['policy_sha256'],
        'capture_receipt_sha256': digest(canonical(capture)),
        **{field: capture[field] for field in SCOPE_FIELDS if field != 'operation_id'},
    }
    require(
        uuid_value(common['operation_id'])
        and common['operation_id'] != capture['operation_id']
        and sha_value(common['policy_sha256'])
        and (expected_common is None or common == expected_common),
        UNVERIFIED,
    )
    index, _ = read_index(directory, principal, common, 50000, expected_sha=digest(raw))
    return index


def read_results(directory, principal, capture, expected_reference, expected_common=None):
    index = read_package_index(directory, principal, capture, expected_reference, expected_common)
    for bucket, item in index['shards'].items():
        read_shard(directory, principal, bucket, item, index['policy_sha256'])
    return index


def read_manifest(directory, principal, backup_id, *, expected_manifest, expected_intent=None):
    raw = read_sealed(directory, MANIFEST, principal)
    measured = digest(raw)
    require(expected_manifest is None or measured == expected_manifest, UNVERIFIED)
    manifest = exact(
        decode(raw, UNVERIFIED),
        (
            'format_version',
            'backup_id',
            'verification_status',
            'seal_policy_sha256',
            *SOURCE_FIELDS,
            'database_artifact',
            'asset_index_ref',
            'original_result_index_ref',
            'program_and_configuration_refs',
            'logical_content_sha256',
            'recovery_chain_sha256',
            *EVIDENCE,
        ),
        UNVERIFIED,
    )
    require(
        type(manifest['format_version']) is int
        and manifest['format_version'] == 1
        and manifest['backup_id'] == backup_id
        and manifest['verification_status'] == 'UNVERIFIED'
        and sha_value(manifest['seal_policy_sha256'])
        and (expected_intent is None or manifest['seal_policy_sha256'] == expected_intent),
        UNVERIFIED,
    )
    return manifest, measured


def verify_contents(
    directory,
    principal,
    backup_id,
    *,
    expected_manifest=None,
    expected_chain=None,
    expected_intent=None,
):
    manifest, measured = read_manifest(
        directory,
        principal,
        backup_id,
        expected_manifest=expected_manifest,
        expected_intent=expected_intent,
    )
    evidence = read_evidence(directory, principal, manifest)
    capture = check_evidence(manifest, evidence, expected_chain)
    database = snapshot_artifact(directory, 1024**4, principal.maintenance_uid, principal.group)
    portable = {'path': SNAPSHOT, 'bytes': database['bytes'], 'sha256': database['sha256']}
    original = {
        'path': SNAPSHOT,
        **{field: capture['database_artifact'][field] for field in ('bytes', 'sha256')},
    }
    require(manifest['database_artifact'] == portable == original, UNVERIFIED)
    audit = read_sealed(directory, AUDIT_INDEX, principal)
    require(manifest['asset_index_ref'] == reference(AUDIT_INDEX, audit), UNVERIFIED)
    assets = verify_count_audit(principal, directory, LIMITS, capture)
    with audit_directory(
        directory, RESULTS, principal.maintenance_uid, principal.group, source=False
    ) as results:
        read_results(results, principal, capture, manifest['original_result_index_ref'])
    assert_contents(directory, {SNAPSHOT, MANIFEST, RESULTS, *EVIDENCE.values(), *assets})
    return manifest, measured


def verified_record(manifest, measured, status):
    return {
        'format_version': 1,
        'status': status,
        'verification_status': manifest['verification_status'],
        'backup_id': manifest['backup_id'],
        'backup_manifest_sha256': measured,
        'recovery_chain_sha256': manifest['recovery_chain_sha256'],
    }


def verification_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        VERIFY_POLICY,
        ('backup_id', 'package_directory', 'package_identity', 'backup_manifest_sha256'),
    )
    require(uuid_value(plan['backup_id']) and sha_value(plan['backup_manifest_sha256']), INVALID)
    folder = validate_location(
        plan,
        'package_directory',
        'package_identity',
        (args.root, args.project, args.anchor.parent, args.home, args.temporary),
    )
    return plan, folder


def verify_backup_package(args):
    plan, folder = verification_inputs(args)
    principal = principal_for_process()
    with private_root(folder, plan['package_identity'], principal) as directory:
        fcntl.flock(directory, fcntl.LOCK_SH | fcntl.LOCK_NB)
        manifest, measured = verify_contents(
            directory,
            principal,
            plan['backup_id'],
            expected_manifest=plan['backup_manifest_sha256'],
        )
    return verified_record(manifest, measured, 'BACKUP_PACKAGE_INTEGRITY_CHECKED')


def lookup_backup_result(args):
    plan, folder = verification_inputs(args)
    principal = principal_for_process()
    key = scope_key(
        args.original_capability, args.original_target, args.original_request_key, INVALID
    )
    with private_root(folder, plan['package_identity'], principal) as directory:
        fcntl.flock(directory, fcntl.LOCK_SH | fcntl.LOCK_NB)
        manifest, measured = read_manifest(
            directory,
            principal,
            plan['backup_id'],
            expected_manifest=plan['backup_manifest_sha256'],
        )
        require(
            args.source_environment_id == manifest['source_environment_id']
            and args.source_data_generation == manifest['source_data_generation'],
            INVALID,
        )
        capture = check_evidence(manifest, read_evidence(directory, principal, manifest), None)
        index_ref = manifest['original_result_index_ref']
        with audit_directory(
            directory, RESULTS, principal.maintenance_uid, principal.group, source=False
        ) as results:
            index = read_package_index(results, principal, capture, index_ref)
            summary = indexed_summary(results, principal, index, key)
    result = original_result(summary, capture, index_ref['sha256'], index['capture_receipt_sha256'])
    result['evidence']['backup_manifest_sha256'] = measured
    return result
