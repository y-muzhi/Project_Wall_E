"""Select a restored ordinary data generation under the original closed control."""

from types import SimpleNamespace

from .environment_files import MAX_REVISION, decode, require
from .environment_installation import read_restore_generation
from .environment_release_switch import DIFFERENT, UNVERIFIED, commit_selection
from .environment_restore import RECEIPT
from .environment_restore_generation import read_generation, sealed_audit
from .environment_restore_preparation import inspect_prepared_data, locked_restore_target
from .environment_restore_readiness import readiness_inputs, verify_prepared_readiness
from .environment_result_archive import read_sealed


def select_restore_deployment(native, active, selection, entry):
    source = selection.source
    target = selection.target
    readiness_path, readiness_pin = selection.restore_readiness
    readiness_args = SimpleNamespace(
        restore_readiness_policy=readiness_path, restore_readiness_policy_sha256=readiness_pin
    )
    plan, read = readiness_inputs(readiness_args)
    with locked_restore_target(native, active, selection.preflight, entry) as staged:
        verified = staged.verified
        checked = verified.source
        receipt = verified.receipt
        binding = target.description['deployment_slot']
        installed = {
            'target_release_id': binding['release_id'],
            'target_release_manifest_sha256': binding['manifest_sha256'],
            'target_program_snapshot_sha256': target.description['program_source']['sha256'],
            'target_schema_manifest_sha256': target.description['schema_manifest_sha256'],
            'target_frontend_index_sha256': binding['frontend_index_sha256'],
            'target_data_generation': target.data_generation,
            'target_deployment_id': target.deployment_id,
            'target_configuration_sha256': target.configuration_sha256,
        }
        require(
            checked.installation == source
            and receipt['operation_id'] == selection.operation_id
            and receipt['restore_preflight_sha256'] == selection.preflight_sha256
            and all(receipt[field] == value for field, value in installed.items())
            and 1 <= checked.control['control_revision'] < MAX_REVISION - 3,
            DIFFERENT,
        )
        actual = inspect_prepared_data(staged)
        ready = verify_prepared_readiness(readiness_args, active, receipt, actual, plan, read)
        generation, pin = read_restore_generation(
            source.environment_root,
            target.environment_id,
            target.data_generation,
            expected=target.restore_generation_sha256,
        )
        require(
            generation['restore_readiness_sha256'] == ready['restore_readiness_sha256']
            and generation['data_identity'] == target.roots['data']
            and all(
                generation[field] == actual[field]
                for field in (
                    'operation_id',
                    'source_control_sha256',
                    'source_database_identity',
                    'restore_target_data_sha256',
                    'target_database_sha256',
                    'target_asset_index_sha256',
                )
            ),
            UNVERIFIED,
        )
        restore = decode(read_sealed(staged.target_fd, RECEIPT, staged.principal), UNVERIFIED)
        audit = sealed_audit(staged.target_fd, staged.principal, restore)
        placed = read_generation(target.path('data').parent, source, restore, audit)
        require(all(placed[field] == generation[field] for field in placed), UNVERIFIED)
        return commit_selection(
            selection,
            checked.control,
            checked.control_fd,
            checked.lock,
            backup_manifest_sha256=receipt['preserved_backup_manifest_sha256'],
            preserved_result_index_sha256=receipt['preserved_result_index_sha256'],
            selected_backup_manifest_sha256=receipt['selected_backup_manifest_sha256'],
            selected_result_index_sha256=receipt['selected_result_index_sha256'],
            selected_source_data_generation=receipt['selected_source_data_generation'],
            logical_content_sha256=actual['selected_logical_content_sha256'],
            database_identity=placed['database_identity'],
            source_database_identity=checked.database_identity,
            restore_generation_sha256=pin,
        )
