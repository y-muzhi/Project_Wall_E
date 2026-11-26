"""Bind a detached reader to one frozen ordinary restore and its fixed candidate."""

from types import SimpleNamespace

from .environment_control import read_control
from .environment_files import absolute, canonical, digest, exact, require
from .environment_installation import database_identity, identity_record, sha_value, uuid_value
from .environment_lock import LIBRARY_REF, NativeEnvironmentFiles
from .environment_release_preflight import candidate_target, read_reference
from .environment_recovery_installation import INVALID, UNVERIFIED


def restore_proof_reference(reference, name, status, hash_field, *, code=INVALID):
    proof = read_reference(reference, name=name)
    details = {key: value for key, value in proof.items() if key != hash_field}
    require(
        type(proof['format_version']) is int
        and proof['format_version'] == 1
        and proof['status'] == status
        and proof[hash_field] == digest(canonical(details))
        and proof['outbound_hold_required'] is True,
        code,
    )
    return proof


def prepared_restore_reference(reference, *, code=INVALID):
    return restore_proof_reference(
        reference,
        'restore-target-data.v1.json',
        'RESTORE_TARGET_DATA_PREPARED',
        'restore_target_data_sha256',
        code=code,
    )


def approve_fixed_restore(args, plan, source, frontend, index, index_sha):
    fixed = exact(
        plan['fixed_restore'],
        ('prepared_data', 'candidate_proof', 'target_manifest', 'target_schema_directory'),
        INVALID,
    )
    prepared = prepared_restore_reference(fixed['prepared_data'])
    _, manifest, schema, program = candidate_target(
        fixed, SimpleNamespace(runtime_manifest_sha256=args.sha256)
    )
    release_root = absolute(fixed['target_manifest']['path'], INVALID).parent
    require(
        prepared['environment_id'] == source.environment_id
        and prepared['target_deployment_id'] == plan['deployment_id']
        and uuid_value(prepared['operation_id'])
        and prepared['operation_id'] not in (plan['initial_operation_id'], plan['operation_id'])
        and all(
            uuid_value(prepared[field])
            for field in ('selected_source_data_generation', 'selected_source_deployment_id')
        )
        and sha_value(prepared['source_control_sha256'])
        and prepared['target_data_identity'] == plan['rehearsal']['identity']
        and prepared['target_restore_receipt_sha256'] == plan['rehearsal']['receipt_sha256']
        and prepared['schema_contract_sha256'] == schema.schema_contract_sha256
        and prepared['target_schema_manifest_sha256'] == manifest['schema_manifest_sha256']
        and prepared['target_program_snapshot_sha256'] == program == args.program_sha256
        and prepared['target_frontend_index_sha256']
        == index_sha
        == manifest['frontend_index_ref']['sha256']
        and args.project == release_root / 'application'
        and frontend == release_root / 'frontend'
        and index == release_root / manifest['frontend_index_ref']['path'],
        INVALID,
    )
    identity_record(prepared['source_database_identity'], INVALID)
    return prepared, absolute(fixed['target_schema_directory'], INVALID)


def lock_frozen_source(resources, args, entry, runtime_hosts, source, prepared, *, code=UNVERIFIED):
    native = NativeEnvironmentFiles(args.root)
    entry['validate_mappings'](args.root, (args.root / LIBRARY_REF,), runtime_hosts)
    lock = resources.enter_context(source.lock(native))
    control_fd = resources.enter_context(source.directory(native, 'control'))
    data_fd = resources.enter_context(source.directory(native, 'data'))
    lock.assert_owned()
    source.check_hold()
    control = read_control(control_fd, source)
    require(
        (control['admission'], control['closed_reason'], control['outbound_hold'])
        == ('CLOSED', 'MAINTENANCE', True)
        and control['operation_id'] == control['maintenance_id'] == prepared['operation_id']
        and digest(canonical(control)) == prepared['source_control_sha256']
        and database_identity(source, data_fd) == prepared['source_database_identity'],
        code,
    )
    return lock


def match_prepared_archive(prepared, receipt, *, code=UNVERIFIED):
    require(
        receipt['operation_id'] == prepared['operation_id']
        and receipt['target_data_generation'] == prepared['target_data_generation']
        and receipt['backup_manifest_sha256'] == prepared['selected_backup_manifest_sha256']
        and receipt['database_artifact']['sha256'] == prepared['target_database_sha256']
        and receipt['restored_asset_index']['sha256'] == prepared['target_asset_index_sha256']
        and receipt['restored_at'] == prepared['target_restored_at']
        and receipt['content_sha256'] == prepared['selected_logical_content_sha256'],
        code,
    )
