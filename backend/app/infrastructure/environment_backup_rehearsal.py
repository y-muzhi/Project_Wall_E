"""Rehearse a sealed ordinary backup into an independently reserved data generation."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from sqlite3 import Error as SQLiteError
from types import SimpleNamespace

from backend.app.shared.time import utc_milliseconds

from .database import SchemaMismatch
from .environment_backup import SNAPSHOT
from .environment_backup_assets import restore_count_audit
from .environment_backup_package import (
    LIMITS,
    anchored_path,
    principal_for_process,
    private_root,
    read_evidence,
    read_policy,
    validate_location,
    verification_inputs,
    verify_contents,
)
from .environment_binding import EnvironmentBinding
from .environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    exact,
    persisted_write,
    protected_directory,
    require,
)
from .environment_installation import sha_value, uuid_value
from .environment_restore import RECEIPT, completed, convert, reopen_archive, restoration_status
from .schema_v22_release import load_release

POLICY = 'backup-package-rehearsal.v1.json'
INVALID = 'BACKUP_REHEARSAL_INTENT_MISMATCH'
UNVERIFIED = 'BACKUP_REHEARSAL_UNVERIFIED'


def rehearsal_inputs(args):
    plan = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'operation_id',
            'package_verification',
            'source_environment_id',
            'target_data_generation',
            'target_directory',
            'target_identity',
            'schema_directory',
        ),
    )
    require(
        all(
            uuid_value(plan[field])
            for field in ('operation_id', 'source_environment_id', 'target_data_generation')
        ),
        INVALID,
    )
    verification = exact(plan['package_verification'], ('path', 'sha256'), INVALID)
    verification_path = absolute(verification['path'], INVALID)
    require(sha_value(verification['sha256']), INVALID)
    verified, source = verification_inputs(
        SimpleNamespace(
            anchor=verification_path,
            anchor_sha256=verification['sha256'],
            root=args.root,
            project=args.project,
            home=args.home,
            temporary=args.temporary,
        )
    )
    schema = absolute(plan['schema_directory'], INVALID)
    require(not (source.is_relative_to(schema) or schema.is_relative_to(source)), INVALID)
    target = validate_location(
        plan,
        'target_directory',
        'target_identity',
        (
            source,
            schema,
            args.root,
            args.project,
            args.anchor.parent,
            args.home,
            args.temporary,
            verification_path.parent,
        ),
    )
    require(target.name == plan['operation_id'] != verified['backup_id'], INVALID)
    return plan, verified, source, target, schema


def recovery_contract(plan, verified, manifest, evidence):
    capture = evidence['capture_receipt_ref']
    previous_restore = evidence['restore_verification_ref']
    require(
        manifest['source_environment_id'] == plan['source_environment_id']
        and plan['target_data_generation']
        not in (
            manifest['source_data_generation'],
            previous_restore['target_data_generation'],
        )
        and plan['operation_id'] != previous_restore['operation_id'],
        INVALID,
    )
    common = {
        'format_version': 2,
        'operation_id': plan['operation_id'],
        'backup_id': verified['backup_id'],
        'backup_manifest_sha256': verified['backup_manifest_sha256'],
        'source_environment_id': manifest['source_environment_id'],
        'source_data_generation': manifest['source_data_generation'],
        'source_deployment_id': manifest['source_deployment_id'],
        'target_data_generation': plan['target_data_generation'],
        'expected_database_sha256': manifest['database_artifact']['sha256'],
        'expected_asset_index_sha256': manifest['asset_index_ref']['sha256'],
    }
    target_plan = {**common, 'capture_policy': {'sha256': capture['intent_sha256']}}
    source_limits = {
        **{
            field: capture[field]
            for field in (
                'operation_id',
                'environment_id',
                'data_generation',
                'deployment_id',
                'control_revision',
            )
        },
        **LIMITS,
        'max_database_bytes': manifest['database_artifact']['bytes'],
    }
    return target_plan, source_limits, common


def pinned_schema(active, schema, manifest):
    program = manifest['program_and_configuration_refs']
    require(program['runtime_manifest_sha256'] == active.runtime_manifest_sha256, INVALID)
    with protected_directory(schema):
        release = load_release(
            schema, program['schema_manifest_sha256'], active.runtime_manifest_sha256
        )
    require(release.schema_contract_sha256 == program['schema_contract_sha256'], UNVERIFIED)
    return release


def data_rehearsal(principal, schema, source, target, plan, verified, active, intent):
    def inspect_package():
        return verify_contents(
            source,
            principal,
            verified['backup_id'],
            expected_manifest=verified['backup_manifest_sha256'],
        )[0]

    manifest = inspect_package()
    evidence = read_evidence(source, principal, manifest)
    target_plan, capture, common = recovery_contract(plan, verified, manifest, evidence)
    common['rehearsal_policy_sha256'] = intent
    release = pinned_schema(active, schema, manifest)
    model = SimpleNamespace(
        environment_id=common['source_environment_id'],
        maintenance_uid=principal.maintenance_uid,
        group=principal.group,
    )
    source_path = anchored_path(source)
    target_path = anchored_path(target)
    try:
        existing = completed(target, model, common, target_plan, capture)
        if existing is None:
            facts, artifact = convert(
                model, release, target_plan, capture, source_path, target_path, target, common
            )
            require(facts[1].sha256 == manifest['logical_content_sha256'], UNVERIFIED)
            asset_index = restore_count_audit(
                model, source, target, capture, evidence['capture_receipt_ref']
            )
            require(inspect_package() == manifest, UNVERIFIED)
            receipt = {
                **common,
                'status': restoration_status(2),
                'restored_at': utc_milliseconds(datetime.now(timezone.utc)),
                'initialized_at': facts[0],
                'content_sha256': facts[1].sha256,
                'database_artifact': artifact,
                'restored_asset_index': asset_index,
                'outbound_hold_required': True,
            }
            persisted_write(target, RECEIPT, canonical(receipt), mode=0o400)
            existing = completed(target, model, common, target_plan, capture)
        else:
            os.fsync(target)
        binding = EnvironmentBinding(
            common['source_environment_id'], common['target_data_generation']
        )
        initialized, content = reopen_archive(target_path / SNAPSHOT, release, binding)
        require(
            existing is not None
            and initialized == existing['initialized_at']
            and content.sha256 == existing['content_sha256'] == manifest['logical_content_sha256']
            and completed(target, model, common, target_plan, capture) == existing,
            UNVERIFIED,
        )
    except (OSError, SQLiteError, ValueError, SchemaMismatch, EnvironmentFailure) as error:
        if os.listdir(target):
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        raise
    return {
        **existing,
        'status': 'BACKUP_PACKAGE_DATA_REHEARSED',
        'verification_status': 'UNVERIFIED',
        'original_result_index_sha256': manifest['original_result_index_ref']['sha256'],
    }


@contextmanager
def rehearsal_directories(principal, source, source_identity, target, target_identity):
    with (
        private_root(source, source_identity, principal) as source_fd,
        private_root(target, target_identity, principal) as target_fd,
    ):
        require(not os.path.samestat(os.fstat(source_fd), os.fstat(target_fd)), INVALID)
        fcntl.flock(source_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(target_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield source_fd, target_fd


def rehearse_backup_package(active, args):
    plan, verified, source, target, schema = rehearsal_inputs(args)
    principal = principal_for_process()
    with rehearsal_directories(
        principal, source, verified['package_identity'], target, plan['target_identity']
    ) as (source_fd, target_fd):
        return data_rehearsal(
            principal, schema, source_fd, target_fd, plan, verified, active, args.anchor_sha256
        )
