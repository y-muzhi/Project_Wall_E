"""Restore a pinned remote snapshot on the independent verification host."""

import os

from backend.app.management.attachment_observation import now
from backend.app.management.recovery_evidence import backup_cutoff
from backend.app.management.registry import is_timestamp

from .environment_backup_package import read_policy
from .environment_files import (
    MAX_REVISION,
    canonical,
    persisted_write,
    relative,
    require,
)
from .environment_installation import sha_value, uuid_value, version_record
from .environment_restic_contract import (
    BACKUP_POINT_FIELDS,
    OFFHOST_PUBLICATION_FIELDS,
    OFFHOST_RECEIPT_FIELDS,
    OFFHOST_RETRIEVED,
    OFFHOST_UPLOADED,
    VERSION,
    offhost_publication_filename,
    offhost_verification_filename,
)
from .environment_restic_offhost import (
    COMMON_FIELDS,
    INVALID,
    RESTORE_LIMITS,
    UNVERIFIED,
    admitted_restic,
    locked_restic,
    protected_fact,
    protected_reference,
)
from .environment_restic_restore import restore_verified_package

POLICY = 'offhost-backup-verification.v1.json'
ROLE = 'VERIFIER'


def read_publication(plan, inputs):
    filename = offhost_publication_filename(plan['publication_operation_id'])
    path, pin = protected_reference(plan['publication_receipt'], filename)
    require(not path.is_relative_to(inputs.work), INVALID)
    proof = read_policy(path, pin, filename, OFFHOST_PUBLICATION_FIELDS)
    subdirectory = proof['snapshot_subdirectory']
    require(
        proof['status'] == OFFHOST_UPLOADED
        and proof['publication_operation_id'] == plan['publication_operation_id']
        and proof['source_host_id'] == plan['source_host_id']
        and proof['source_host_anchor_sha256'] == plan['source_host_anchor_sha256']
        and proof['source_host_id'] != inputs.host['host_id']
        and proof['source_machine_id_sha256'] != inputs.host['machine_id_sha256']
        and proof['source_environment_id'] == inputs.profile['environment_id']
        and proof['repository_id'] == inputs.profile['repository_id']
        and proof['storage_profile_sha256'] == plan['storage']['sha256']
        and proof['restic_version'] == VERSION
        and all(
            sha_value(proof[key])
            for key in (
                'publication_policy_sha256',
                'source_machine_id_sha256',
                'backup_manifest_sha256',
                'logical_content_sha256',
                'snapshot_id',
                'restic_sha256',
            )
        )
        and all(
            uuid_value(proof[key])
            for key in ('backup_id', 'source_deployment_id', 'source_data_generation')
        )
        and len({proof['backup_id'], plan['publication_operation_id'], plan['verification_id']})
        == 3
        and type(proof['source_control_revision']) is int
        and 1 <= proof['source_control_revision'] < MAX_REVISION
        and is_timestamp(proof['cutoff_at'])
        and is_timestamp(proof['published_at'])
        and proof['cutoff_at'] <= proof['published_at'] <= now()
        and type(subdirectory) is str
        and subdirectory.startswith('/')
        and relative(subdirectory[1:], INVALID).name == proof['backup_id'],
        UNVERIFIED,
    )
    return proof


def verification_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            *COMMON_FIELDS,
            'verification_id',
            'publication_operation_id',
            'publication_receipt',
            'source_host_id',
            'source_host_anchor_sha256',
            *(name for name, _ in RESTORE_LIMITS),
        ),
    )
    require(
        all(
            uuid_value(plan[key])
            for key in ('verification_id', 'publication_operation_id', 'source_host_id')
        )
        and sha_value(plan['source_host_anchor_sha256'])
        and all(
            type(plan[key]) is int and 1 <= plan[key] <= limit for key, limit in RESTORE_LIMITS
        ),
        INVALID,
    )
    inputs = admitted_restic(args, plan, ROLE)
    return plan, inputs, read_publication(plan, inputs)


def verification_binding(args, plan, inputs, publication):
    return {
        'format_version': 1,
        'status': OFFHOST_RETRIEVED,
        'verification_id': plan['verification_id'],
        'verification_policy_sha256': args.anchor_sha256,
        **{
            key: publication[key]
            for key in (
                'publication_operation_id',
                'source_host_id',
                'storage_profile_sha256',
                'repository_id',
                'source_environment_id',
                *BACKUP_POINT_FIELDS,
                'snapshot_id',
            )
        },
        'verification_host_id': inputs.host['host_id'],
        'verification_anchor_sha256': plan['host']['sha256'],
        'restic_sha256': plan['restic']['sha256'],
        'restic_version': VERSION,
    }


def confirmed_verification(receipt, binding, publication, plan):
    version_record(receipt, OFFHOST_RECEIPT_FIELDS, UNVERIFIED)
    require(
        all(receipt[key] == value for key, value in binding.items())
        and type(receipt['snapshot_bytes']) is int
        and 0 < receipt['snapshot_bytes'] <= plan['max_restore_bytes']
        and type(receipt['snapshot_entries']) is int
        and 0 < receipt['snapshot_entries'] <= plan['max_files']
        and is_timestamp(receipt['retrieved_at'])
        and publication['published_at'] <= receipt['retrieved_at'] <= now(),
        UNVERIFIED,
    )
    return receipt


def snapshot_policy(plan, publication):
    command_policy = {
        key: publication[key]
        for key in (
            'publication_operation_id',
            'backup_id',
            'repository_id',
            'snapshot_id',
            'snapshot_subdirectory',
            'backup_manifest_sha256',
        )
    }
    command_policy.update({key: plan[key] for key, _ in RESTORE_LIMITS})
    return command_policy


def check_restored_manifest(manifest, measured, binding):
    require(
        measured == binding['backup_manifest_sha256']
        and manifest['source_environment_id'] == binding['source_environment_id']
        and all(
            manifest[key] == binding[key]
            for key in BACKUP_POINT_FIELDS
            if key not in ('cutoff_at', 'backup_manifest_sha256')
        )
        and backup_cutoff(manifest['cutoff_at'], UNVERIFIED) == binding['cutoff_at'],
        UNVERIFIED,
    )


def verify_offhost_backup_snapshot(args):
    plan, inputs, publication = verification_inputs(args)
    binding = verification_binding(args, plan, inputs, publication)
    filename = offhost_verification_filename(plan['verification_id'])
    with locked_restic(plan, inputs, ROLE) as (directory, command, call, recheck):
        previous = protected_fact(directory, filename, inputs.principal)
        if previous is not None:
            confirmed = confirmed_verification(previous, binding, publication, plan)
            os.fsync(directory)
            return confirmed
        manifest, measured, size, count = restore_verified_package(
            inputs.work,
            directory,
            inputs.principal,
            snapshot_policy(plan, publication),
            command,
            call,
        )
        check_restored_manifest(manifest, measured, binding)
        require(read_publication(plan, inputs) == publication, UNVERIFIED)
        recheck()
        result = confirmed_verification(
            {
                **binding,
                'retrieved_at': now(),
                'snapshot_bytes': size,
                'snapshot_entries': count,
            },
            binding,
            publication,
            plan,
        )
        persisted_write(directory, filename, canonical(result), mode=0o400)
        return result
