"""Confirm a fixed deployment's original withdrawal without redispatch."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)

from .operation_store import decoded
from .registry_recovery_outcome import RELEASE_RETIRED, UNVERIFIED, matching_original
from .registry_recovery_restore_retirement import (
    STEP_STATES,
    require_no_opening,
    require_unselected_history,
)
from .registry_recovery_undispatched import ORIGINAL_FIELDS, original_operation
from .release_configuration import read_configuration
from .release_execution import (
    EXECUTIONS,
    HOLD_EXECUTOR,
    grant_subject,
    operation_record,
    retained_binding,
)
from .release_operations import STEP, confirmed_preview, raw_plan
from .release_retirement import original_retirement


def retired_release_evidence(connection, catalog, binding):
    try:
        return checked_retired_release(connection, catalog, binding)
    except (EnvironmentFailure, OSError, TypeError, KeyError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error


def checked_retired_release(connection, catalog, binding):
    original = original_operation(connection, binding)
    operation, step = operation_record(connection, catalog, binding['operation_id'])
    action, status = operation['action'], operation['status']
    require(
        original == operation
        and matching_original(RELEASE_RETIRED, action, status)
        and bool(operation['cancel_requested']) == (status == 'CANCELLED')
        and step['status'] == STEP_STATES[status]
        and step['executor_ref'] == HOLD_EXECUTOR
        and step['result_json'] is None
        and type(step['external_identity_json']) is str,
        UNVERIFIED,
    )
    principal = catalog.access(operation['principal'])
    require(principal.role == 'MANAGER', UNVERIFIED)
    intent = decoded(operation['intent_json'])
    plan = raw_plan(connection, intent['plan_id'])
    preview = confirmed_preview(plan, principal.id, intent)
    require(
        intent['action'] == action
        and intent['environment_id'] == operation['environment_id']
        and digest(canonical(intent)) == operation['intent_sha256']
        and intent['expected_record_version']
        == operation['expected_record_version']
        == plan['record_version']
        and intent['expected_assignment_generation']
        == operation['expected_assignment_generation']
        == plan['assignment_generation']
        and plan['execution_operation_id'] == operation['operation_id'],
        UNVERIFIED,
    )
    grant = grant_subject(preview, operation, catalog)
    configuration = read_configuration(catalog, intent['configuration_ref'])
    require(
        configuration.action == action
        and configuration.sha256 == grant['configuration_record_sha256']
        and retained_binding(configuration, grant),
        UNVERIFIED,
    )
    require_unselected_history(connection, operation)
    fields = ('maintenance', 'retirement_sha256') if status == 'CANCELLED' else ('maintenance',)
    external = exact(decoded(step['external_identity_json']), fields, UNVERIFIED)
    require(external['maintenance'] == grant, UNVERIFIED)
    receipt = original_retirement(catalog, grant)
    require(receipt is not None, UNVERIFIED)
    require_no_opening(catalog, operation, area=EXECUTIONS)
    pin = digest(canonical(receipt))
    require(status != 'CANCELLED' or external['retirement_sha256'] == pin, UNVERIFIED)
    return {
        **{field: binding[field] for field in ORIGINAL_FIELDS},
        'environment_id': operation['environment_id'],
        'original_status': status,
        'action': action,
        'step_kind': STEP,
        'step_status': step['status'],
        'maintenance_grant_sha256': digest(canonical(grant)),
        'retirement_sha256': pin,
        'disposition': RELEASE_RETIRED,
    }
