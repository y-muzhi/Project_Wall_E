"""Prove that an original waiting START never obtained dispatch authority."""

from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import sha_value

from .lifecycle_operations import STEPS, lifecycle_intent
from .operation_store import decoded, environment_row
from .registry import is_timestamp
from .registry_recovery_capacity import measured_capacity
from .registry_recovery_outcome import RESERVED_START, UNDISPATCHED, UNVERIFIED
from .runtime_capacity import CLAIM_KIND, CLAIM_SCOPE, DIMENSIONS, reservations_for

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


def undispatched_step(connection, operation, *, required_kind=STEPS['START']):
    steps = connection.execute(
        'SELECT * FROM management_steps WHERE operation_id=? ORDER BY ordinal',
        (operation['operation_id'],),
    ).fetchall()
    require(len(steps) == 1, UNVERIFIED)
    step = steps[0]
    require(
        step['ordinal'] == 1
        and step['step_kind'] == required_kind
        and step['status'] == 'PLANNED'
        and step['executor_ref'] is None
        and step['external_identity_json'] is None,
        UNVERIFIED,
    )
    return step


def waiting_step(connection, operation):
    step = undispatched_step(connection, operation)
    require(type(step['result_json']) is str, UNVERIFIED)
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


def require_no_claims(connection, operation_id, *, allow_capacity=False, linked_plan=None):
    occupied = connection.execute(
        'SELECT EXISTS (SELECT 1 FROM resource_claims WHERE operation_id=? '
        'AND (NOT ? OR kind!=? OR scope_ref!=?)) '
        'OR EXISTS (SELECT 1 FROM management_plans WHERE execution_operation_id=? '
        'AND (? IS NULL OR plan_id!=?)) '
        'OR EXISTS (SELECT 1 FROM delivery_snapshots WHERE operation_id=?) '
        'OR EXISTS (SELECT 1 FROM managed_environments WHERE fence_operation_id=?)',
        (
            operation_id,
            allow_capacity,
            CLAIM_KIND,
            CLAIM_SCOPE,
            operation_id,
            linked_plan,
            linked_plan,
            operation_id,
            operation_id,
        ),
    ).fetchone()[0]
    require(occupied == 0, UNVERIFIED)


def undispatched_operation(connection, policy, expected_status):
    operation = original_operation(connection, policy)
    require(
        operation['action'] == 'START'
        and operation['status'] == expected_status
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
    return operation, environment


def undispatched_start_evidence(connection, policy):
    operation, _ = undispatched_operation(connection, policy, 'WAITING_CAPACITY')
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


def reserved_start_evidence(connection, catalog, policy):
    operation, environment = undispatched_operation(connection, policy, 'ACCEPTED')
    identifier = operation['operation_id']
    require(undispatched_step(connection, operation)['result_json'] is None, UNVERIFIED)
    require_no_claims(connection, identifier, allow_capacity=True)
    require(
        environment['host_id'] == catalog.scope['host_id']
        and sha_value(catalog.capacity_policy_sha256),
        UNVERIFIED,
    )
    return {
        **{field: policy[field] for field in ORIGINAL_FIELDS},
        'environment_id': environment['environment_id'],
        'original_status': operation['status'],
        'step_kind': STEPS['START'],
        'configuration_sha256': environment['configuration_sha256'],
        'profile_ref': environment['profile_ref'],
        'capacity_policy_sha256': catalog.capacity_policy_sha256,
        'disposition': RESERVED_START,
    }


def reserved_start_capacity(connection, evidence):
    identifier = evidence['operation_id']
    claims = reservations_for(connection, identifier)
    measured = measured_capacity(claims, evidence['environment_id'])
    count = connection.execute(
        'SELECT COUNT(*) FROM resource_claims WHERE operation_id=?', (identifier,)
    ).fetchone()[0]
    require(count == measured['count'] == len(DIMENSIONS), UNVERIFIED)
    require(
        decoded(claims[0]['identity_json'])
        == {
            'policy_sha256': evidence['capacity_policy_sha256'],
            'profile_ref': evidence['profile_ref'],
            'configuration_sha256': evidence['configuration_sha256'],
        },
        UNVERIFIED,
    )
    return measured
