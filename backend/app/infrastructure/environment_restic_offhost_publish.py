"""Publish one original sealed backup to the fixed remote repository."""

import fcntl
import os

from backend.app.management.attachment_observation import now
from backend.app.management.recovery_evidence import backup_cutoff
from backend.app.management.registry import is_timestamp

from .environment_backup_package import (
    private_root,
    read_policy,
    validate_location,
    verify_contents,
)
from .environment_files import EnvironmentFailure, canonical, identity, persisted_write, require
from .environment_installation import sha_value, uuid_value, version_record
from .environment_restic_contract import (
    BACKUP_POINT_FIELDS,
    OFFHOST_PUBLICATION_FIELDS,
    OFFHOST_UPLOADED,
    VERSION,
    offhost_publication_filename,
)
from .environment_restic_offhost import (
    COMMON_FIELDS,
    INVALID,
    UNVERIFIED,
    admitted_restic,
    locked_restic,
    protected_fact,
)
from .environment_restic_publish import backup_snapshot, find_snapshot, package_coverage

POLICY = 'offhost-backup-publication.v1.json'
ROLE = 'PUBLISHER'
INTENT = 'OFFHOST_PUBLICATION_INTENT'


def publication_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            *COMMON_FIELDS,
            'operation_id',
            'backup_id',
            'backup_manifest_sha256',
            'package_directory',
            'package_identity',
            'max_publish_seconds',
            'max_package_bytes',
            'max_files',
        ),
    )
    require(
        all(uuid_value(plan[key]) for key in ('operation_id', 'backup_id'))
        and plan['operation_id'] != plan['backup_id']
        and sha_value(plan['backup_manifest_sha256'])
        and all(
            type(plan[key]) is int and 1 <= plan[key] <= maximum
            for key, maximum in (
                ('max_publish_seconds', 3600),
                ('max_package_bytes', 1024**4),
                ('max_files', 8192),
            )
        ),
        INVALID,
    )
    inputs = admitted_restic(args, plan, ROLE)
    package = validate_location(
        plan, 'package_directory', 'package_identity', inputs.package_boundaries
    )
    require(package.name == plan['backup_id'], INVALID)
    return plan, inputs, package


def publication_binding(args, plan, inputs, package, source):
    manifest, measured = verify_contents(
        source,
        inputs.principal,
        plan['backup_id'],
        expected_manifest=plan['backup_manifest_sha256'],
    )
    require(
        manifest['source_environment_id'] == inputs.profile['environment_id']
        and measured == plan['backup_manifest_sha256'],
        UNVERIFIED,
    )
    cutoff = backup_cutoff(manifest['cutoff_at'], UNVERIFIED)
    require(cutoff <= now(), UNVERIFIED)
    return {
        'format_version': 1,
        'publication_operation_id': plan['operation_id'],
        'publication_policy_sha256': args.anchor_sha256,
        'source_host_id': inputs.host['host_id'],
        'source_host_anchor_sha256': plan['host']['sha256'],
        'source_machine_id_sha256': inputs.host['machine_id_sha256'],
        'source_environment_id': manifest['source_environment_id'],
        **{
            key: manifest[key]
            for key in BACKUP_POINT_FIELDS
            if key not in ('cutoff_at', 'backup_manifest_sha256')
        },
        'cutoff_at': cutoff,
        'backup_manifest_sha256': measured,
        'storage_profile_sha256': plan['storage']['sha256'],
        'repository_id': inputs.profile['repository_id'],
        'snapshot_subdirectory': package.as_posix(),
        'restic_sha256': plan['restic']['sha256'],
        'restic_version': VERSION,
    }


def confirmed_publication(result, binding, snapshot):
    version_record(result, OFFHOST_PUBLICATION_FIELDS, UNVERIFIED)
    require(
        result['status'] == OFFHOST_UPLOADED
        and all(result[key] == value for key, value in binding.items())
        and sha_value(snapshot)
        and result['snapshot_id'] == snapshot
        and is_timestamp(result['published_at'])
        and binding['cutoff_at'] <= result['published_at'] <= now(),
        UNVERIFIED,
    )
    return result


def publish_offhost_backup_snapshot(args):
    plan, inputs, package = publication_inputs(args)
    repo_plan = {**plan, 'repository_id': inputs.profile['repository_id']}
    result_name = offhost_publication_filename(plan['operation_id'])
    intent_name = f'publish-{plan["operation_id"]}-offhost-intent.v1.json'
    with (
        locked_restic(plan, inputs, ROLE) as (directory, command, call, recheck),
        private_root(package, plan['package_identity'], inputs.principal) as source,
    ):
        fcntl.flock(source, fcntl.LOCK_SH | fcntl.LOCK_NB)
        binding = publication_binding(args, plan, inputs, package, source)
        package_coverage(package, {**plan, 'max_restore_bytes': plan['max_package_bytes']})
        intent = {**binding, 'status': INTENT}
        previous = protected_fact(directory, intent_name, inputs.principal)
        stored = protected_fact(directory, result_name, inputs.principal)
        require(previous in (None, intent) and (stored is None or previous == intent), INVALID)
        snapshot = find_snapshot(command, repo_plan, package, inputs.work, call)
        if stored is not None:
            result = confirmed_publication(stored, binding, snapshot)
            os.fsync(directory)
            return result

        if previous is None:
            require(snapshot is None, INVALID)
            recheck()
            persisted_write(directory, intent_name, canonical(intent), mode=0o400)
            try:
                backup_snapshot(command, repo_plan, package, inputs.work, call)
            except EnvironmentFailure:
                pass
        try:
            if previous is None:
                snapshot = find_snapshot(command, repo_plan, package, inputs.work, call)
            require(sha_value(snapshot), UNVERIFIED)
            require(
                identity(package.stat(follow_symlinks=False))
                == identity(os.fstat(source))
                == plan['package_identity']
                and publication_binding(args, plan, inputs, package, source) == binding,
                UNVERIFIED,
            )
            recheck()
            result = confirmed_publication(
                {
                    **binding,
                    'status': OFFHOST_UPLOADED,
                    'snapshot_id': snapshot,
                    'published_at': now(),
                },
                binding,
                snapshot,
            )
            persisted_write(directory, result_name, canonical(result), mode=0o400)
            return result
        except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
