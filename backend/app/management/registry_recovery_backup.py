"""Verify the completed external effect of an original managed backup."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)

from .backup_capture import backup_record, capture_grant
from .backup_operations import STEP, backup_input, backup_policy, confirmed_backup
from .backup_reconciliation import original_backup_result
from .operation_store import decoded
from .registry_recovery_outcome import BACKUP_COMPLETED, UNVERIFIED, matching_original
from .registry_recovery_undispatched import ORIGINAL_FIELDS, original_operation
from .release_operations import raw_plan

EXECUTOR = 'NATIVE_DATABASE_BACKUP'


def matches_step_status(original_status, step_status):
    if original_status == 'SUCCEEDED':
        return step_status == 'SUCCEEDED'
    return step_status in ('DISPATCHING', 'UNKNOWN')


def backup_step(connection, operation, step):
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
    require(
        count == 1
        and linked == 0
        and matches_step_status(operation['status'], step['status'])
        and step['executor_ref'] == EXECUTOR
        and type(step['external_identity_json']) is str,
        UNVERIFIED,
    )
    return exact(decoded(step['external_identity_json']), ('capture',), UNVERIFIED)['capture']


def completion_evidence(connection, catalog, binding):
    original = original_operation(connection, binding)
    operation, step = backup_record(connection, catalog, binding['operation_id'])
    require(
        original == operation
        and matching_original(BACKUP_COMPLETED, operation['action'], operation['status'])
        and operation['cancel_requested'] == 0
        and catalog.access(operation['principal']).role == 'MANAGER',
        UNVERIFIED,
    )
    intent = decoded(operation['intent_json'])
    backup_input(intent, confirmed=True)
    require(
        digest(canonical(intent)) == operation['intent_sha256']
        and intent['environment_id'] == operation['environment_id']
        and intent['expected_record_version'] == operation['expected_record_version']
        and intent['expected_assignment_generation'] == operation['expected_assignment_generation'],
        UNVERIFIED,
    )
    plan = raw_plan(connection, intent['plan_id'])
    preview = confirmed_backup(plan, operation['principal'], intent)
    require(
        plan['execution_operation_id'] == operation['operation_id']
        and plan['record_version'] == operation['expected_record_version']
        and plan['assignment_generation'] == operation['expected_assignment_generation'],
        UNVERIFIED,
    )
    strategy, pin = backup_policy(
        catalog, preview['backup_policy_ref'], operation['environment_id']
    )
    grant = backup_step(connection, operation, step)
    require(
        pin == preview['backup_policy_sha256']
        and grant == capture_grant(catalog, operation, preview, strategy),
        UNVERIFIED,
    )
    result = original_backup_result(catalog, operation, grant)
    require(result is not None, UNVERIFIED)
    if operation['status'] == 'SUCCEEDED':
        recorded = step['result_json']
        require(
            type(recorded) is str and canonical(decoded(recorded)) == canonical(result), UNVERIFIED
        )
    else:
        require(step['result_json'] is None, UNVERIFIED)
    return {
        **{field: binding[field] for field in ORIGINAL_FIELDS},
        'environment_id': operation['environment_id'],
        'original_status': operation['status'],
        'step_kind': STEP,
        'step_status': step['status'],
        'backup_id': grant['backup_id'],
        'capture_grant_sha256': digest(canonical(grant)),
        'completion_result_sha256': digest(canonical(result)),
        'disposition': BACKUP_COMPLETED,
    }


def completed_backup_evidence(connection, catalog, binding):
    try:
        return completion_evidence(connection, catalog, binding)
    except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
