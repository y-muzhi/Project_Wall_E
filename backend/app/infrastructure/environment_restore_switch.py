"""Select a restored ordinary data generation under the original closed control."""

import os
from types import SimpleNamespace

from .environment_binding import EnvironmentBinding
from .environment_control import (
    CONTROL_NAME,
    control_bytes,
    document_ai_revert_name,
    maintained_control,
    read_control,
    read_maintenance_intent,
)
from .environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    persisted_write,
    require,
)
from .environment_initialize import database_has_sidecars
from .environment_installation import database_identity, read_restore_generation
from .environment_maintenance import write_fact
from .environment_release_compatibility import checked_schema
from .environment_release_switch import DIFFERENT, UNVERIFIED, commit_selection, original_transition
from .environment_restore import DOCUMENT_AI, RECEIPT, reopen_archive
from .environment_restore_generation import read_generation, sealed_audit
from .environment_restore_preparation import inspect_prepared_data, locked_restore_target
from .environment_restore_readiness import readiness_inputs, verify_prepared_readiness
from .environment_result_archive import read_sealed


def revert_closed_document_ai(native, active, selection):
    source = selection.source
    target = selection.target
    require(
        source.description['purpose'] == target.description['purpose'] == 'DEVELOPMENT', DIFFERENT
    )
    with source.lock(native) as lock, source.directory(native, 'control') as fd:
        source.check_hold()
        transition = original_transition(fd, selection)
        require(transition is not None and 'source_logical_content_sha256' in transition, DIFFERENT)
        intent = read_maintenance_intent(fd, source, selection.operation_id)
        require(
            transition['before']
            == maintained_control(intent['before'], selection.operation_id, intent['plan_sha256'])
            and transition['after']['control_revision'] < MAX_REVISION - 1,
            DIFFERENT,
        )
        released = {
            **intent['before'],
            'control_revision': transition['after']['control_revision'] + 1,
        }
        name = document_ai_revert_name(selection.operation_id)
        receipt = {
            'format_version': 1,
            'status': 'DOCUMENT_AI_RESTORE_REVERTED_CLOSED',
            'operation_id': selection.operation_id,
            'environment_id': source.environment_id,
            'restored_deployment_id': source.deployment_id,
            'restored_data_generation': source.data_generation,
            'retained_deployment_id': target.deployment_id,
            'retained_data_generation': target.data_generation,
            'transition_sha256': digest(canonical(transition)),
            'control_sha256': digest(canonical(released)),
            'control_revision': released['control_revision'],
        }
        _, raw = control_bytes(fd, source)
        if raw == canonical(released):
            require(write_fact(fd, source, name, receipt), UNVERIFIED)
            require(read_control(fd, source) == released, UNVERIFIED)
            os.fsync(fd)
            return receipt

        is_selected = raw == canonical(transition['after'])
        current = transition['after'] if is_selected else transition['before']
        current_installation = target if is_selected else source
        require(raw == canonical(current), DIFFERENT)
        for installation in (source, target):
            require(
                not any(
                    os.path.lexists(installation.path('runtime') / name)
                    for name in ('walle.sock', 'walle-check.sock')
                ),
                DIFFERENT,
            )
        release = checked_schema(
            source.schema,
            source.description['schema_manifest_sha256'],
            active.runtime_manifest_sha256,
            source.project,
        )
        with source.directory(native, 'data') as data:
            require(
                database_identity(source, data) == transition['source_database_identity']
                and not database_has_sidecars(source.database),
                UNVERIFIED,
            )
            binding = EnvironmentBinding(source.environment_id, source.data_generation)
            _, contents = reopen_archive(source.database, release, binding)
            require(
                contents.sha256 == transition['source_logical_content_sha256']
                and database_identity(source, data) == transition['source_database_identity']
                and not database_has_sidecars(source.database),
                UNVERIFIED,
            )
        with source.host_admission():
            lock.assert_owned()
            require(read_control(fd, current_installation) == current, DIFFERENT)
            write_fact(fd, source, name, receipt, create=True)
            lock.assert_owned()
            require(read_control(fd, current_installation) == current, DIFFERENT)
            persisted_write(fd, CONTROL_NAME, canonical(released), mode=0o640, replace=True)
        try:
            require(read_control(fd, source) == released, UNVERIFIED)
        except (OSError, RuntimeError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        return receipt


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
            and generation.get('document_ai_schema_contract_sha256')
            == actual.get(DOCUMENT_AI, {}).get('contract_sha256')
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
        logical = actual['selected_logical_content_sha256']
        conversion = {}
        if DOCUMENT_AI in actual:
            require(
                generation['source_logical_content_sha256'] == logical
                and generation['target_logical_content_sha256']
                == actual['target_logical_content_sha256'],
                UNVERIFIED,
            )
            conversion = {'source_logical_content_sha256': logical}
            logical = actual['target_logical_content_sha256']
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
            logical_content_sha256=logical,
            **conversion,
            database_identity=placed['database_identity'],
            source_database_identity=checked.database_identity,
            restore_generation_sha256=pin,
        )
