"""Assemble one portable backup from already verified ordinary recovery components."""

import fcntl
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from .environment_backup import SNAPSHOT, original_receipt, recovery_directory, snapshot_artifact
from .environment_backup_assets import (
    AUDIT_INDEX,
    TARGET_FLAGS,
    audit_directory,
    restore_count_audit,
)
from .environment_backup_package import (
    EVIDENCE,
    INVALID,
    MANIFEST,
    PACKAGE,
    PROGRAM_FIELDS,
    RESULTS,
    SOURCE_FIELDS,
    UNVERIFIED,
    anchored_path,
    principal_for_process,
    private_root,
    read_policy,
    read_results,
    reference,
    validate_location,
    verified_record,
    verify_contents,
)
from .environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    digest,
    exact,
    persisted_write,
    require,
)
from .environment_installation import sha_value, uuid_value
from .environment_recovery_chain import inspect_recovery_chain
from .environment_result_archive import INDEX, read_sealed, shard_name
from .schema_v22_publish import publish_directory

POLICY = 'backup-package-policy.v1.json'


def sealing_inputs(args):
    plan = read_policy(
        args.backup_package_policy,
        args.backup_package_policy_sha256,
        POLICY,
        (
            'operation_id',
            'backup_id',
            'installation_sha256',
            'chain_policy',
            'recovery_chain_sha256',
            'recovery_directory',
            'recovery_identity',
        ),
    )
    require(
        uuid_value(plan['operation_id'])
        and uuid_value(plan['backup_id'])
        and plan['operation_id'] != plan['backup_id']
        and plan['installation_sha256'] == args.anchor_sha256
        and sha_value(plan['installation_sha256'])
        and sha_value(plan['recovery_chain_sha256']),
        INVALID,
    )
    chain = exact(plan['chain_policy'], ('path', 'sha256'), INVALID)
    chain_path = absolute(chain['path'], INVALID)
    require(sha_value(chain['sha256']), INVALID)
    output = validate_location(
        plan,
        'recovery_directory',
        'recovery_identity',
        (
            args.root,
            args.project,
            args.anchor.parent,
            args.home,
            args.temporary,
            args.backup_package_policy.parent,
            chain_path.parent,
        ),
    )
    require(output.name == plan['operation_id'], INVALID)
    return (
        plan,
        output,
        SimpleNamespace(
            anchor=args.anchor,
            anchor_sha256=args.anchor_sha256,
            recovery_chain_policy=chain_path,
            recovery_chain_policy_sha256=chain['sha256'],
        ),
    )


def copy_snapshot(source, target, cap, measured, principal):
    fd = os.open(SNAPSHOT, TARGET_FLAGS, 0o600, dir_fd=target)
    with os.fdopen(fd, 'wb') as sink:
        original = snapshot_artifact(
            source,
            cap['max_database_bytes'],
            principal.maintenance_uid,
            principal.group,
            expected_identity=measured['identity'],
            sink=sink,
        )
        require(original == measured, UNVERIFIED)
        sink.flush()
        os.fchmod(sink.fileno(), 0o400)
        os.fsync(sink.fileno())
    return {'path': SNAPSHOT, 'bytes': measured['bytes'], 'sha256': measured['sha256']}


def write_captured(directory, components):
    installation = components.installation
    plan = components.capture
    intent = components.coverage['capture_policy_sha256']
    with recovery_directory(plan, installation) as (_, source):
        capture = original_receipt(source, plan, installation, intent)
        require(
            capture is not None
            and digest(canonical(capture)) == components.coverage['capture_receipt_sha256'],
            UNVERIFIED,
        )
        database = copy_snapshot(
            source, directory, plan, capture['database_artifact'], installation
        )
        restore_count_audit(installation, source, directory, plan, capture)
        raw = read_sealed(directory, AUDIT_INDEX, installation)
        return capture, database, reference(AUDIT_INDEX, raw)


def write_results(directory, components, capture):
    installation = components.installation
    os.mkdir(RESULTS, 0o700, dir_fd=directory)
    with (
        recovery_directory(components.index_target, installation) as (_, source),
        audit_directory(
            directory, RESULTS, installation.maintenance_uid, installation.group, source=False
        ) as target,
    ):
        fcntl.flock(source, fcntl.LOCK_SH | fcntl.LOCK_NB)
        raw = read_sealed(source, INDEX, installation)
        original = reference(f'{RESULTS}/{INDEX}', raw)
        require(original['sha256'] == components.proof['result_index_sha256'], UNVERIFIED)
        index = read_results(source, installation, capture, original, components.index_common)
        require(index['entry_count'] <= components.index_limit, UNVERIFIED)
        for bucket in index['shards']:
            filename = shard_name(bucket)
            persisted_write(
                target, filename, read_sealed(source, filename, installation), mode=0o400
            )
        persisted_write(target, INDEX, raw, mode=0o400)
        os.fsync(target)
    return original


def write_package(directory, components, intent):
    capture, database, audit = write_captured(directory, components)
    index = write_results(directory, components, capture)
    records = {
        'capture_receipt_ref': capture,
        'coverage_ref': components.coverage,
        'restore_verification_ref': components.restore_receipt,
        'recovery_chain_ref': components.proof,
    }
    refs = {}
    for key, record in records.items():
        filename = EVIDENCE[key]
        raw = canonical(record)
        persisted_write(directory, filename, raw, mode=0o400)
        refs[key] = reference(filename, raw)
    manifest = {
        'format_version': 1,
        'backup_id': components.proof['backup_id'],
        'verification_status': 'UNVERIFIED',
        'seal_policy_sha256': intent,
        **{key: capture[source] for key, source in SOURCE_FIELDS.items()},
        'database_artifact': database,
        'asset_index_ref': audit,
        'original_result_index_ref': index,
        'program_and_configuration_refs': {key: components.coverage[key] for key in PROGRAM_FIELDS},
        'logical_content_sha256': components.coverage['logical_content_sha256'],
        'recovery_chain_sha256': components.proof['recovery_chain_sha256'],
        **refs,
    }
    raw = canonical(manifest)
    persisted_write(directory, MANIFEST, raw, mode=0o400)
    return digest(raw)


def read_package(parent, principal, plan, intent, expected_manifest=None):
    with audit_directory(
        parent, PACKAGE, principal.maintenance_uid, principal.group, source=False
    ) as directory:
        return verify_contents(
            directory,
            principal,
            plan['backup_id'],
            expected_manifest=expected_manifest,
            expected_chain=plan['recovery_chain_sha256'],
            expected_intent=intent,
        )


def seal_locked(parent, principal, components, plan, intent):
    folder = anchored_path(parent)
    published = False
    try:
        with TemporaryDirectory(prefix='.backup-', dir=folder) as staging:
            with audit_directory(
                parent, Path(staging).name, principal.maintenance_uid, principal.group, source=False
            ) as directory:
                expected = write_package(directory, components, intent)
                verify_contents(
                    directory,
                    principal,
                    plan['backup_id'],
                    expected_manifest=expected,
                    expected_chain=plan['recovery_chain_sha256'],
                    expected_intent=intent,
                )
                os.fsync(directory)
            publish_directory(staging, folder / PACKAGE)
            published = True
            os.fsync(parent)
            return read_package(parent, principal, plan, intent, expected)
    except (EnvironmentFailure, OSError, KeyError, ValueError, TypeError) as error:
        if published:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        raise


def seal_backup_package(native, active, args, entry):
    plan, output, chain_args = sealing_inputs(args)
    intent = args.backup_package_policy_sha256
    principal = principal_for_process()
    with private_root(output, plan['recovery_identity'], principal) as parent:
        fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            os.stat(PACKAGE, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            components = inspect_recovery_chain(native, active, chain_args, entry)
            require(
                components.proof['backup_id'] == plan['backup_id']
                and components.proof['recovery_chain_sha256'] == plan['recovery_chain_sha256']
                and plan['operation_id']
                not in (
                    components.capture['operation_id'],
                    components.restore_receipt['operation_id'],
                    components.index_common['operation_id'],
                ),
                INVALID,
            )
            with recovery_directory(plan, components.installation) as (_, admitted):
                require(os.path.samestat(os.fstat(admitted), os.fstat(parent)), INVALID)
                manifest, measured = seal_locked(parent, principal, components, plan, intent)
        else:
            os.fsync(parent)
            manifest, measured = read_package(parent, principal, plan, intent)
    return verified_record(manifest, measured, 'BACKUP_PACKAGE_SEALED')
