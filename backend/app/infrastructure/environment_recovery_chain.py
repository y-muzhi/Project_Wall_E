"""Revalidate same-source ordinary capture, result index and isolated restore components."""

from dataclasses import dataclass
import fcntl
from pathlib import Path
from types import SimpleNamespace

from .environment_backup import SNAPSHOT, capture_inputs, recovery_directory
from .environment_backup_coverage import check_coverage
from .environment_binding import EnvironmentBinding
from .environment_files import absolute, canonical, decode, digest, exact, read_protected, require
from .environment_installation import Installation, sha_value, uuid_value
from .environment_restore import (
    DOCUMENT_AI,
    archived_document_ai_source,
    completed,
    document_ai_release,
    load_restore,
    planned_restore,
    reopen_archive,
    reopen_document_ai_target,
)
from .environment_result_archive import load_inputs as load_index_inputs, read_index, read_shard

POLICY = 'recovery-chain-policy.v1.json'
INVALID = 'RECOVERY_CHAIN_INTENT_MISMATCH'
UNVERIFIED = 'RECOVERY_CHAIN_UNVERIFIED'
POLICY_REFS = ('capture_policy', 'result_index_policy', 'restore_policy')
PIN_FIELDS = ('coverage_sha256', 'result_index_sha256', 'restore_receipt_sha256')


@dataclass(frozen=True)
class RecoveryComponents:
    proof: dict
    coverage: dict
    restore_receipt: dict
    capture: dict
    installation: Installation
    index_target: dict
    index_common: dict
    index_limit: int


def load_chain_policy(path, expected):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    value = exact(
        decode(raw, INVALID),
        ('format_version', 'backup_id', *POLICY_REFS, *PIN_FIELDS),
        INVALID,
    )
    require(
        type(value['format_version']) is int
        and value['format_version'] == 1
        and uuid_value(value['backup_id'])
        and all(sha_value(value[key]) for key in PIN_FIELDS),
        INVALID,
    )
    for key in POLICY_REFS:
        reference = exact(value[key], ('path', 'sha256'), INVALID)
        absolute(reference['path'], INVALID)
        require(sha_value(reference['sha256']), INVALID)
    return value


def read_restore_component(
    target, installation, release, common, plan, capture, coverage, pin, *, ai_release=None
):
    with recovery_directory(target, installation) as (folder, fd):
        receipt = completed(fd, installation, common, plan, capture)
        require(
            receipt is not None
            and digest(canonical(receipt)) == pin
            and receipt['restored_asset_index'] == coverage['asset_index'],
            UNVERIFIED,
        )
        restored = EnvironmentBinding(installation.environment_id, plan['target_data_generation'])
        if ai_release is None:
            initialized, content = reopen_archive(folder / SNAPSHOT, release, restored)
            require(content.sha256 == coverage['logical_content_sha256'], UNVERIFIED)
        else:
            original = EnvironmentBinding(
                installation.environment_id, plan['source_data_generation']
            )
            with recovery_directory(capture, installation) as (source, _):
                original_file = source / SNAPSHOT
                _, coverage_content = reopen_archive(original_file, release, original)
                require(coverage_content.sha256 == coverage['logical_content_sha256'], UNVERIFIED)
                source_facts = archived_document_ai_source(original_file, release, original)
            initialized, content = reopen_document_ai_target(
                folder / SNAPSHOT, ai_release, restored, plan['operation_id'], source_facts
            )
        require(
            initialized == receipt['initialized_at']
            and content.sha256 == receipt['content_sha256']
            and completed(fd, installation, common, plan, capture) == receipt,
            UNVERIFIED,
        )
    return receipt


def read_archive_component(target, installation, common, plan, pin):
    with recovery_directory(target, installation) as (_, fd):
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        value, actual = read_index(fd, installation, common, plan['max_entries'], expected_sha=pin)
        for bucket, reference in value['shards'].items():
            read_shard(fd, installation, bucket, reference, common['policy_sha256'])
    return actual


def check_recovery_chain(native, active, args, entry):
    return inspect_recovery_chain(native, active, args, entry).proof


def inspect_recovery_chain(native, active, args, entry):
    policy_sha = args.recovery_chain_policy_sha256
    plan = load_chain_policy(args.recovery_chain_policy, policy_sha)
    cap_ref = plan['capture_policy']
    index_ref = plan['result_index_policy']
    restore_ref = plan['restore_policy']
    operations = SimpleNamespace(
        anchor=args.anchor,
        anchor_sha256=args.anchor_sha256,
        capture_policy=Path(cap_ref['path']),
        capture_sha256=cap_ref['sha256'],
        result_index_policy=Path(index_ref['path']),
        result_index_policy_sha256=index_ref['sha256'],
    )
    capture, installation, release = capture_inputs(active, operations, entry)
    restore, restore_capture = load_restore(Path(restore_ref['path']), restore_ref['sha256'])
    index, index_capture, index_installation, index_target, index_common = load_index_inputs(
        operations, active, entry
    )
    require(
        capture['format_version'] == restore['format_version'] == 2
        and capture['operation_id'] == plan['backup_id']
        and len({capture['operation_id'], restore['operation_id'], index['operation_id']}) == 3
        and capture == restore_capture == index_capture
        and cap_ref == restore['capture_policy'] == index['capture_policy']
        and installation == index_installation,
        INVALID,
    )
    restore_target, restore_common = planned_restore(restore, capture, restore_ref['sha256'])
    coverage = check_coverage(native, active, operations, entry)
    require(
        coverage['coverage_sha256'] == plan['coverage_sha256']
        and index['expected_capture_receipt_sha256'] == coverage['capture_receipt_sha256']
        and restore['expected_database_sha256'] == coverage['database_sha256']
        and restore['expected_asset_index_sha256'] == coverage['asset_index']['sha256'],
        UNVERIFIED,
    )
    observed_index = read_archive_component(
        index_target,
        installation,
        index_common,
        index,
        plan['result_index_sha256'],
    )
    ai_release = document_ai_release(restore, installation, release, active, entry)
    result = read_restore_component(
        restore_target,
        installation,
        release,
        restore_common,
        restore,
        capture,
        coverage,
        plan['restore_receipt_sha256'],
        ai_release=ai_release,
    )
    verified = {
        'format_version': 1,
        'status': 'RECOVERY_COMPONENTS_MATCHED',
        'backup_id': plan['backup_id'],
        'recovery_chain_policy_sha256': policy_sha,
        'environment_id': coverage['environment_id'],
        'source_data_generation': coverage['data_generation'],
        'source_deployment_id': coverage['deployment_id'],
        'source_control_revision': coverage['control_revision'],
        'cutoff_at': coverage['cutoff_at'],
        'database_sha256': coverage['database_sha256'],
        'coverage_sha256': coverage['coverage_sha256'],
        'asset_index': coverage['asset_index'],
        'restore_operation_id': result['operation_id'],
        'restore_receipt_sha256': plan['restore_receipt_sha256'],
        'target_data_generation': result['target_data_generation'],
        'result_index_sha256': observed_index,
        'logical_content_sha256': coverage['logical_content_sha256'],
        'outbound_hold_required': result['outbound_hold_required'],
    }
    if ai_release is not None:
        verified.update(
            status='DOCUMENT_AI_RECOVERY_COMPONENTS_MATCHED',
            document_ai_schema=result[DOCUMENT_AI],
            target_logical_content_sha256=result['content_sha256'],
        )
    proof = {**verified, 'recovery_chain_sha256': digest(canonical(verified))}
    return RecoveryComponents(
        proof,
        coverage,
        result,
        capture,
        installation,
        index_target,
        index_common,
        index['max_entries'],
    )
