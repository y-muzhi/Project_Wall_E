"""Open the fixed restored deployment under the capacity reserved by its original operation."""

import os

from backend.app.infrastructure.environment_files import require
from backend.app.infrastructure.environment_installation import read_restore_generation, uuid_value
from backend.app.infrastructure.environment_release_switch import RESTORE_SWITCH_POLICY

from .attachment_observation import candidate_environment, path_resource
from .lifecycle_operations import authorized, expected_versions
from .operation_contract import INVALID, RESOURCE, UNAVAILABLE, installed_record
from .operation_store import decoded, mutation, register_resources, unclaimed
from .release_configuration import CHANGED
from .release_execution import execution_directory, optional_fact
from .release_open_admission import (
    OPEN_AUTHORIZED,
    TARGET,
    check_open_request,
    reserve_selected_opening,
)
from .release_runtime import SelectedDeployment, start_selected_deployment
from .restore_execution import (
    EXECUTIONS,
    HOLD_RECEIPT,
    RETIREMENT,
    AdmittedRestore,
    admitted_restore,
    checked_restore_configuration,
    known_restore_maintenance,
    original_restore_grant,
    restore_operation,
)
from .restore_selection import SELECTED, TARGET_ATTACHMENT, checked_target, verify_selection


def read_restore_selection(catalog, grant, expected=None):
    directory = catalog.directory / EXECUTIONS / grant['confirmation']['operation_id']
    recorded = installed_record(directory / SELECTED, expected)
    maintenance = installed_record(directory / HOLD_RECEIPT)
    policy = installed_record(directory / RESTORE_SWITCH_POLICY)
    attachment = installed_record(
        directory / TARGET_ATTACHMENT, recorded['target_attachment']['sha256']
    )
    verify_selection(recorded, grant, maintenance, policy, attachment)
    reference = recorded['target_attachment']
    require(
        catalog.candidate(reference['candidate_ref'], reference['sha256']) == attachment, RESOURCE
    )
    return recorded, attachment


def restore_registry_row(connection, principal, intent, grant):
    row = authorized(connection, principal, intent['environment_id'])
    expected_versions(row, intent)
    preview = grant['confirmation']
    source = preview['source']
    work = decoded(row['work_package_json'])
    require(
        row['configuration_sha256'] == source['configuration_sha256']
        and row['program_source'] == source['program_sha256']
        and decoded(row['configuration_ref']) == preview['source_attachment']
        and work['data_generation'] == source['data_generation']
        and work['deployment_id'] == source['deployment_id'],
        CHANGED,
    )
    return row


def restore_claims(target):
    receipt, _ = read_restore_generation(
        target.environment_root,
        target.environment_id,
        target.data_generation,
        expected=target.restore_generation_sha256,
    )
    return [
        path_resource('DATA_ROOT', target.path('data'), target.roots['data']),
        path_resource('BUSINESS_DATABASE', target.database, receipt['database_identity']),
    ]


def admit_restore_open(connection, lock, catalog, request, runtime_sha):
    check_open_request(request)
    with mutation(connection, lock):
        operation, step = restore_operation(connection, catalog, request['operation_id'])
        require(
            operation['status'] == 'RUNNING'
            and step['status'] == 'DISPATCHING'
            and step['external_identity_json'] is not None
            and not operation['cancel_requested'],
            UNAVAILABLE,
        )
        principal, intent, grant = original_restore_grant(connection, catalog, operation)
        state = decoded(step['external_identity_json'])
        require(state['maintenance'] == grant, RESOURCE)
        configuration = checked_restore_configuration(catalog, grant)
        selected, attachment = read_restore_selection(
            catalog, grant, request['selection_receipt_sha256']
        )
        require(all(selected[key] == request[key] for key in TARGET), CHANGED)
        row = restore_registry_row(connection, principal, intent, grant)
        require(row['profile_ref'] == attachment['profile_ref'], CHANGED)
        source_ref = grant['confirmation']['source_attachment']
        source = candidate_environment(
            catalog.candidate(source_ref['candidate_ref'], source_ref['sha256']), runtime_sha
        )
        target = checked_target(
            AdmittedRestore(grant, configuration, source), attachment, runtime_sha
        )
        claims = unclaimed(connection, row['environment_id'], restore_claims(target))
        outcome = reserve_selected_opening(
            connection, catalog, operation, state, row, selected, request
        )
        if outcome['status'] == OPEN_AUTHORIZED:
            register_resources(connection, row['environment_id'], operation['operation_id'], claims)
        return outcome


def start_managed_restore(catalog, registry, args, entry, manager):
    operation = args.release_operation_id
    require(os.geteuid() == 0 and uuid_value(operation), INVALID)
    with execution_directory(catalog, EXECUTIONS, operation) as (_, fd):
        require(optional_fact(fd, RETIREMENT) is None, UNAVAILABLE)
        admitted = admitted_restore(catalog, registry, args, manager)
        hold = known_restore_maintenance(fd, admitted)
        require(hold is not None and optional_fact(fd, SELECTED) is not None, RESOURCE)
        selection, attachment = read_restore_selection(catalog, admitted.grant)
        target = SelectedDeployment(
            checked_target(admitted, attachment, args.sha256),
            selection,
            selection['target_attachment'],
            attachment['profile_ref'],
            '_admit-restore-open',
        )
        return start_selected_deployment(catalog, registry, args, entry, manager, fd, target)
