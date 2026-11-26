"""Adopt a verified remote snapshot as an exclusive ordinary recovery package."""

import fcntl
import os
import stat
from types import SimpleNamespace

from .environment_backup_package import (
    private_root,
    read_policy,
    validate_location,
    verify_contents,
)
from .environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    identity,
    persisted_write,
    require,
)
from .environment_installation import sha_value, uuid_value
from .environment_restic_contract import offhost_verification_filename
from .environment_restic_offhost import (
    INVALID,
    UNVERIFIED,
    locked_restic,
    protected_fact,
    protected_reference,
)
from .environment_restic_offhost_verify import (
    POLICY as VERIFICATION_POLICY,
)
from .environment_restic_offhost_verify import (
    ROLE,
    check_restored_manifest,
    confirmed_verification,
    read_publication,
    snapshot_policy,
    verification_binding,
    verification_inputs,
)
from .environment_restic_restore import verified_snapshot_directory
from .schema_v22_publish import publish_directory

POLICY = 'offhost-backup-materialization.v1.json'
INTENT = 'OFFHOST_BACKUP_MATERIALIZATION_INTENT'
MATERIALIZED = 'OFFHOST_BACKUP_PACKAGE_MATERIALIZED'


def materialization_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'operation_id',
            'verification_policy',
            'verification_receipt_sha256',
            'output_directory',
            'output_identity',
        ),
    )
    require(
        uuid_value(plan['operation_id']) and sha_value(plan['verification_receipt_sha256']), INVALID
    )
    path, pin = protected_reference(plan['verification_policy'], VERIFICATION_POLICY)
    verification_args = SimpleNamespace(**{**vars(args), 'anchor': path, 'anchor_sha256': pin})
    verification, inputs, publication = verification_inputs(verification_args)
    output = validate_location(
        plan,
        'output_directory',
        'output_identity',
        (*inputs.package_boundaries, args.anchor.parent),
    )
    require(
        plan['operation_id']
        not in (
            publication['backup_id'],
            verification['verification_id'],
            publication['publication_operation_id'],
        ),
        INVALID,
    )
    binding = verification_binding(verification_args, verification, inputs, publication)
    return plan, output, verification, inputs, publication, binding


def checked_materialization_report(directory, plan, verification, inputs, publication, binding):
    name = offhost_verification_filename(verification['verification_id'])
    report = protected_fact(directory, name, inputs.principal)
    require(
        report is not None and digest(canonical(report)) == plan['verification_receipt_sha256'],
        UNVERIFIED,
    )
    return confirmed_verification(report, binding, publication, verification)


def package_receipt(directory, final, principal, binding, intent, known):
    expected = identity(final.stat(follow_symlinks=False))
    with private_root(final, expected, principal) as fd:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        manifest, measured = verify_contents(
            fd, principal, binding['backup_id'], expected_manifest=binding['backup_manifest_sha256']
        )
        check_restored_manifest(manifest, measured, binding)
        require(
            identity(final.stat(follow_symlinks=False)) == identity(os.fstat(fd)) == expected,
            UNVERIFIED,
        )
    os.fsync(directory)
    result = {
        **intent,
        'status': MATERIALIZED,
        'package_directory': str(final),
        'package_identity': expected,
    }
    require(known is None or known == result, UNVERIFIED)
    return result


def sync_restored_package(scratch):
    for _, _, files, fd in os.fwalk(scratch, topdown=False, follow_symlinks=False):
        for name in files:
            descriptor = os.open(
                name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
            )
            try:
                entry = os.fstat(descriptor)
                require(stat.S_ISREG(entry.st_mode) and entry.st_nlink == 1, UNVERIFIED)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(fd)


def materialize_offhost_backup_package(args):
    plan, output, verification, inputs, publication, binding = materialization_inputs(args)
    final = output / binding['backup_id']
    operation = plan['operation_id']
    intent_name = f'materialize-{operation}-intent.v1.json'
    result_name = f'materialize-{operation}-result.v1.json'
    with (
        locked_restic(verification, inputs, ROLE) as (directory, command, call, recheck),
        private_root(output, plan['output_identity'], inputs.principal) as destination,
    ):
        fcntl.flock(destination, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = checked_materialization_report(
            directory, plan, verification, inputs, publication, binding
        )
        require(
            identity(os.fstat(directory))['device'] == identity(os.fstat(destination))['device'],
            INVALID,
        )
        intent = {
            'format_version': 1,
            'status': INTENT,
            'operation_id': operation,
            'materialization_policy_sha256': args.anchor_sha256,
            'verification_receipt_sha256': plan['verification_receipt_sha256'],
            'output_identity': plan['output_identity'],
            **{
                key: binding[key]
                for key in ('backup_id', 'backup_manifest_sha256', 'snapshot_id', 'repository_id')
            },
        }
        previous = protected_fact(directory, intent_name, inputs.principal)
        known = protected_fact(directory, result_name, inputs.principal)
        exists = os.path.lexists(final)
        require(previous in (None, intent) and (known is None or exists), UNVERIFIED)
        require(not exists or previous == intent, UNVERIFIED)
        if previous is None:
            persisted_write(directory, intent_name, canonical(intent), mode=0o400)
        if not exists:
            with verified_snapshot_directory(
                inputs.work,
                directory,
                inputs.principal,
                snapshot_policy(verification, publication),
                command,
                call,
            ) as restored:
                scratch, manifest, measured, size, count = restored
                require(
                    (size, count) == (report['snapshot_bytes'], report['snapshot_entries']),
                    UNVERIFIED,
                )
                check_restored_manifest(manifest, measured, binding)
                require(
                    identity(output.stat(follow_symlinks=False))
                    == identity(os.fstat(destination))
                    == plan['output_identity']
                    and read_publication(verification, inputs) == publication,
                    UNVERIFIED,
                )
                recheck()
                sync_restored_package(scratch)
                try:
                    publish_directory(scratch, final)
                    os.fsync(destination)
                    os.fsync(directory)
                except OSError as error:
                    raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        try:
            result = package_receipt(destination, final, inputs.principal, binding, intent, known)
            recheck()
            if known is None:
                persisted_write(directory, result_name, canonical(result), mode=0o400)
            return result
        except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
