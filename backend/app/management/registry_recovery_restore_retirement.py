"""Prove that an original managed restore retired before any target selection."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)

from .operation_contract import installed_record
from .operation_store import decoded
from .registry_recovery_outcome import RESTORE_RETIRED, UNVERIFIED, matching_original
from .registry_recovery_undispatched import ORIGINAL_FIELDS, original_operation
from .release_operations import raw_plan
from .release_runtime import DISPATCH, OPENED
from .restore_execution import (
    EXECUTIONS,
    HOLD_EXECUTOR,
    checked_restore_configuration,
    original_restore_grant,
    restore_operation,
)
from .restore_operations import STEP
from .restore_retirement import original_retirement

STEP_STATES = {'RUNNING': 'DISPATCHING', 'CANCELLED': 'SKIPPED'}


def require_unselected_history(connection, operation):
    identifier = operation['operation_id']
    count = connection.execute(
        'SELECT COUNT(*) FROM management_steps WHERE operation_id=?', (identifier,)
    ).fetchone()[0]
    linked = connection.execute(
        'SELECT EXISTS (SELECT 1 FROM resource_claims WHERE operation_id=?) '
        'OR EXISTS (SELECT 1 FROM delivery_snapshots WHERE operation_id=?) '
        'OR EXISTS (SELECT 1 FROM managed_environments WHERE fence_operation_id=?)',
        (identifier,) * 3,
    ).fetchone()[0]
    require(count == 1 and linked == 0, UNVERIFIED)


def require_no_opening(catalog, operation, *, area=EXECUTIONS):
    directory = catalog.directory / area / operation['operation_id']
    for name in (DISPATCH, OPENED):
        try:
            installed_record(directory / name)
        except FileNotFoundError:
            continue
        raise EnvironmentFailure(UNVERIFIED)


def retired_restore_evidence(connection, catalog, binding):
    try:
        return retirement_evidence(connection, catalog, binding)
    except (EnvironmentFailure, OSError, TypeError, KeyError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error


def retirement_evidence(connection, catalog, binding):
    original = original_operation(connection, binding)
    operation, step = restore_operation(connection, catalog, binding['operation_id'])
    status = operation['status']
    require(
        original == operation
        and matching_original(RESTORE_RETIRED, operation['action'], status)
        and bool(operation['cancel_requested']) == (status == 'CANCELLED')
        and step['status'] == STEP_STATES[status]
        and step['executor_ref'] == HOLD_EXECUTOR
        and step['result_json'] is None
        and type(step['external_identity_json']) is str,
        UNVERIFIED,
    )
    _, intent, grant = original_restore_grant(connection, catalog, operation)
    plan = raw_plan(connection, intent['plan_id'])
    require(
        digest(canonical(intent)) == operation['intent_sha256']
        and intent['environment_id'] == operation['environment_id']
        and intent['expected_record_version']
        == operation['expected_record_version']
        == plan['record_version']
        and intent['expected_assignment_generation']
        == operation['expected_assignment_generation']
        == plan['assignment_generation'],
        UNVERIFIED,
    )
    checked_restore_configuration(catalog, grant)
    require_unselected_history(connection, operation)
    fields = ('maintenance', 'retirement_sha256') if status == 'CANCELLED' else ('maintenance',)
    external = exact(decoded(step['external_identity_json']), fields, UNVERIFIED)
    require(external['maintenance'] == grant, UNVERIFIED)
    receipt = original_retirement(catalog, grant)
    require(receipt is not None, UNVERIFIED)
    require_no_opening(catalog, operation)
    pin = digest(canonical(receipt))
    require(status != 'CANCELLED' or external['retirement_sha256'] == pin, UNVERIFIED)
    return {
        **{field: binding[field] for field in ORIGINAL_FIELDS},
        'environment_id': operation['environment_id'],
        'original_status': status,
        'step_kind': STEP,
        'step_status': step['status'],
        'maintenance_grant_sha256': digest(canonical(grant)),
        'retirement_sha256': pin,
        'disposition': RESTORE_RETIRED,
    }
