"""Verify that a preserved accepted maintenance or archive operation never dispatched."""

import os

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .backup_capture import EXECUTIONS as BACKUP_EXECUTIONS
from .backup_operations import backup_input, confirmed_backup
from .operation_contract import RELEASE_ACTIONS
from .operation_store import decoded, environment_row
from .registry_recovery_outcome import (
    UNSTARTED_OPERATION,
    UNSTARTED_STEPS,
    UNVERIFIED,
    matching_original,
)
from .registry_recovery_undispatched import (
    ORIGINAL_FIELDS,
    original_operation,
    require_no_claims,
    undispatched_step,
)
from .release_execution import EXECUTIONS as RELEASE_EXECUTIONS
from .release_execution import execution_directory
from .release_operations import confirmed_preview, raw_plan, release_input
from .restore_execution import EXECUTIONS as RESTORE_EXECUTIONS
from .restore_operations import confirmed_restore, restore_input

EXECUTIONS = {
    'BACKUP': BACKUP_EXECUTIONS,
    **dict.fromkeys(RELEASE_ACTIONS, RELEASE_EXECUTIONS),
    'RESTORE': RESTORE_EXECUTIONS,
}


def original_plan(connection, operation, intent):
    action = operation['action']
    if action == 'ARCHIVE':
        from .environment_archive import archive_intent

        archive_intent(intent)
        return None
    if action in RELEASE_ACTIONS:
        release_input(intent, confirmation=True)
        confirmation = confirmed_preview
    elif action == 'BACKUP':
        backup_input(intent, confirmed=True)
        confirmation = confirmed_backup
    else:
        restore_input(intent, confirmed=True)
        confirmation = confirmed_restore

    plan = raw_plan(connection, intent['plan_id'])
    preview = confirmation(plan, operation['principal'], intent)
    require(
        plan['execution_operation_id'] == operation['operation_id']
        and plan['record_version'] == operation['expected_record_version']
        and plan['assignment_generation'] == operation['expected_assignment_generation']
        and (action != 'RESTORE' or preview['operation_id'] == operation['operation_id']),
        UNVERIFIED,
    )
    return plan


def require_no_publication(catalog, operation, action):
    observations = catalog.directory / 'observations'
    with protected_directory(catalog.directory):
        try:
            with protected_directory(observations) as directory:
                for name in (f'archive-{operation}.v1.json', f'start-runtime-{operation}'):
                    try:
                        os.stat(name, dir_fd=directory, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    raise EnvironmentFailure(UNVERIFIED)
        except FileNotFoundError:
            pass
        if action in EXECUTIONS:
            try:
                with execution_directory(catalog, EXECUTIONS[action], operation) as (_, directory):
                    require(not os.listdir(directory), UNVERIFIED)
            except FileNotFoundError:
                pass


def unstarted_evidence(connection, catalog, policy):
    operation = original_operation(connection, policy)
    action = operation['action']
    require(
        matching_original(UNSTARTED_OPERATION, action, operation['status'])
        and operation['registry_generation'] == catalog.scope['registry_generation']
        and operation['cancel_requested'] == 0
        and catalog.access(operation['principal']).role == 'MANAGER',
        UNVERIFIED,
    )
    identifier = operation['operation_id']
    step = undispatched_step(connection, operation, required_kind=UNSTARTED_STEPS[action])
    require(step['result_json'] is None, UNVERIFIED)
    intent = decoded(operation['intent_json'])
    environment = environment_row(connection, operation['environment_id'])
    require(
        environment is not None
        and environment['host_id'] == catalog.scope['host_id']
        and environment['purpose'] in ('DEVELOPMENT', 'INTEGRATION')
        and sha_value(environment['configuration_sha256'])
        and sha_value(environment['program_source'])
        and type(environment['configuration_ref']) is str
        and environment['registration_state'] == 'ACTIVE'
        and environment['preparation_state'] == 'PREPARED'
        and environment['assignment_control_state'] == 'OPEN'
        and intent['action'] == action
        and intent['environment_id'] == operation['environment_id']
        and intent['expected_record_version']
        == operation['expected_record_version']
        == environment['record_version']
        and intent['expected_assignment_generation']
        == operation['expected_assignment_generation']
        == environment['assignment_generation']
        and digest(canonical(intent)) == operation['intent_sha256']
        and connection.execute(
            "SELECT 1 FROM management_controls WHERE operation_id=? AND command!='RECONCILE'",
            (identifier,),
        ).fetchone()
        is None,
        UNVERIFIED,
    )
    attachment = exact(
        decoded(environment['configuration_ref']), ('candidate_ref', 'sha256'), UNVERIFIED
    )
    require(uuid_value(attachment['candidate_ref']) and sha_value(attachment['sha256']), UNVERIFIED)
    plan = original_plan(connection, operation, intent)
    require_no_claims(connection, identifier, linked_plan=None if plan is None else plan['plan_id'])
    require_no_publication(catalog, identifier, action)
    return {
        **{field: policy[field] for field in ORIGINAL_FIELDS},
        'environment_id': environment['environment_id'],
        'original_status': operation['status'],
        'step_kind': step['step_kind'],
        'action': action,
        'plan_sha256': None if plan is None else plan['plan_sha256'],
        'disposition': UNSTARTED_OPERATION,
    }


def unstarted_operation_evidence(connection, catalog, policy):
    try:
        return unstarted_evidence(connection, catalog, policy)
    except (EnvironmentFailure, OSError, ValueError, TypeError, KeyError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
