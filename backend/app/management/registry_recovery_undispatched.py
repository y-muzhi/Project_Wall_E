"""Prove that an original waiting START never obtained dispatch authority."""

from backend.app.infrastructure.environment_files import canonical, digest, exact, require

from .lifecycle_operations import STEPS, lifecycle_intent
from .operation_store import decoded, environment_row
from .registry import is_timestamp
from .registry_recovery_outcome import UNDISPATCHED, UNVERIFIED
from .runtime_capacity import DIMENSIONS

ORIGINAL_FIELDS = (
    'operation_id',
    'source_registry_generation',
    'source_revision',
    'source_intent_sha256',
)


def original_operation(connection, policy):
    operation = connection.execute(
        'SELECT * FROM management_operations WHERE operation_id=? AND registry_generation=?',
        (policy['operation_id'], policy['source_registry_generation']),
    ).fetchone()
    require(
        operation is not None
        and operation['revision'] == policy['source_revision']
        and operation['intent_sha256'] == policy['source_intent_sha256']
        and operation['intent_version'] == 1
        and is_timestamp(operation['created_at']),
        UNVERIFIED,
    )
    return operation


def waiting_step(connection, operation):
    steps = connection.execute(
        'SELECT * FROM management_steps WHERE operation_id=? ORDER BY ordinal',
        (operation['operation_id'],),
    ).fetchall()
    require(len(steps) == 1, UNVERIFIED)
    step = steps[0]
    require(
        step['ordinal'] == 1
        and step['step_kind'] == STEPS['START']
        and step['status'] == 'PLANNED'
        and step['executor_ref'] is None
        and step['external_identity_json'] is None
        and type(step['result_json']) is str,
        UNVERIFIED,
    )
    wait = exact(decoded(step['result_json']), ('observed_at', 'missing'), UNVERIFIED)
    missing = wait['missing']
    require(
        is_timestamp(wait['observed_at'])
        and type(missing) is list
        and 0 < len(missing) <= len(DIMENSIONS)
        and all(isinstance(name, str) and name in DIMENSIONS for name in missing)
        and len(set(missing)) == len(missing),
        UNVERIFIED,
    )
    return wait


def require_no_claims(connection, operation_id):
    occupied = connection.execute(
        'SELECT EXISTS (SELECT 1 FROM resource_claims WHERE operation_id=?) '
        'OR EXISTS (SELECT 1 FROM management_plans WHERE execution_operation_id=?) '
        'OR EXISTS (SELECT 1 FROM delivery_snapshots WHERE operation_id=?) '
        'OR EXISTS (SELECT 1 FROM managed_environments WHERE fence_operation_id=?)',
        (operation_id,) * 4,
    ).fetchone()[0]
    require(occupied == 0, UNVERIFIED)


def undispatched_start_evidence(connection, policy):
    operation = original_operation(connection, policy)
    require(
        operation['action'] == 'START'
        and operation['status'] == 'WAITING_CAPACITY'
        and operation['cancel_requested'] == 0,
        UNVERIFIED,
    )
    intent = lifecycle_intent(decoded(operation['intent_json']))
    require(
        intent['action'] == 'START'
        and intent['environment_id'] == operation['environment_id']
        and intent['expected_record_version'] == operation['expected_record_version']
        and intent['expected_assignment_generation'] == operation['expected_assignment_generation']
        and digest(canonical(intent)) == operation['intent_sha256'],
        UNVERIFIED,
    )
    environment = environment_row(connection, operation['environment_id'])
    require(
        environment is not None
        and environment['record_version'] == operation['expected_record_version']
        and environment['assignment_generation'] == operation['expected_assignment_generation']
        and environment['configuration_sha256'] == intent['expected_configuration_sha256']
        and environment['registration_state'] == 'ACTIVE'
        and environment['preparation_state'] == 'PREPARED'
        and environment['assignment_control_state'] == 'OPEN',
        UNVERIFIED,
    )
    waiting = waiting_step(connection, operation)
    require_no_claims(connection, operation['operation_id'])
    return {
        **{field: policy[field] for field in ORIGINAL_FIELDS},
        'environment_id': operation['environment_id'],
        'original_status': operation['status'],
        'step_kind': STEPS['START'],
        'waiting_evidence_sha256': digest(canonical(waiting)),
        'disposition': UNDISPATCHED,
    }
