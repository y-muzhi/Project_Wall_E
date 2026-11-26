"""Verify the preserved completion of an original ordinary STOP."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    protected_directory,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .lifecycle_operations import STEPS, lifecycle_intent
from .operation_contract import installed_record
from .operation_store import decoded
from .registry_recovery_capacity import measured_capacity, settle_capacity
from .registry_recovery_outcome import STOP_COMPLETED, UNVERIFIED, matching_original
from .registry_recovery_undispatched import ORIGINAL_FIELDS, original_operation, require_no_claims
from .runtime_capacity import reservations_for
from .runtime_stop import run_claim, stop_record

STEP = STEPS['STOP']
EXECUTOR = 'SYSTEMD_ORDINARY_RUNTIME'
STOP_STEP_STATES = {'SUCCEEDED': 'SUCCEEDED', 'ACCEPTED': 'PLANNED', 'UNKNOWN': 'UNKNOWN'}
STOP_RESULT_FIELDS = ('environment_id', 'run_id', 'runtime_state', 'observed_at', 'proof_id')


def original_runtime_identity(value, operation_id):
    external = exact(value, ('start_operation_id', 'run_id', 'policy_sha256'), UNVERIFIED)
    require(
        uuid_value(external['start_operation_id'])
        and external['start_operation_id'] != operation_id
        and uuid_value(external['run_id'])
        and sha_value(external['policy_sha256']),
        UNVERIFIED,
    )
    return external


def stopped_runtime_unit(environment_id, start_operation_id):
    require(uuid_value(environment_id) and uuid_value(start_operation_id), UNVERIFIED)
    return f'walle-env-{environment_id}-{start_operation_id}.service'


def observed_stop_receipt(catalog, identifier, environment, run, external=None):
    require(all(uuid_value(value) for value in (identifier, environment, run)), UNVERIFIED)
    directory = catalog.directory / 'observations'
    name = f'stop-{identifier}.v1.json'
    claim = f'stop-claim-{environment}-{run}.v1.json'
    observed = installed_record(directory / name)
    marked = {
        'start_operation_id': observed.get('start_operation_id'),
        'run_id': observed.get('run_id'),
        'policy_sha256': observed.get('stop_policy_sha256'),
    }
    original_runtime_identity(marked, identifier)
    require(marked['run_id'] == run and (external is None or external == marked), UNVERIFIED)
    original = {
        'format_version': 1,
        **catalog.scope,
        'stop_operation_id': identifier,
        'environment_id': environment,
        'run_id': run,
        'start_operation_id': marked['start_operation_id'],
        'stop_policy_sha256': marked['policy_sha256'],
        'runtime_policy_sha256': observed.get('runtime_policy_sha256'),
    }
    require(sha_value(original['runtime_policy_sha256']), UNVERIFIED)
    with protected_directory(directory) as root:
        stop = stop_record(root, name, original)
        require(
            stop is not None
            and stop == observed
            and stop['state'] == 'STOPPED'
            and run_claim(root, claim, original, create=False),
            UNVERIFIED,
        )
    return stop


def require_stopped_source(connection, operation, external):
    identifier = external['start_operation_id']
    start = connection.execute(
        'SELECT op.environment_id,op.status,step.status AS step_status,step.result_json '
        'FROM management_operations AS op JOIN management_steps AS step USING(operation_id) '
        'WHERE op.operation_id=? AND step.ordinal=1 AND '
        "((op.action='START' AND step.step_kind='RUNTIME_STARTED') OR "
        "(op.action IN ('RELEASE','ROLLBACK_CODE','RECONFIGURE') "
        "AND step.step_kind='RELEASE_DEPLOYMENT') OR "
        "(op.action='RESTORE' AND step.step_kind='RESTORE_ENVIRONMENT'))",
        (identifier,),
    ).fetchone()
    require(
        start is not None
        and start['status'] == start['step_status'] == 'SUCCEEDED'
        and start['environment_id'] == operation['environment_id']
        and type(start['result_json']) is str
        and decoded(start['result_json'])['run_id'] == external['run_id'],
        UNVERIFIED,
    )


def stop_capacity_evidence(connection, evidence):
    claims = reservations_for(connection, evidence['start_operation_id'])
    require(evidence['original_status'] != 'SUCCEEDED' or not claims, UNVERIFIED)
    return measured_capacity(claims, evidence['environment_id'])


def settle_stop_capacity(connection, evidence, *, recorded):
    released = {'stop_operation_id': evidence['operation_id'], **evidence['completion']}
    settle_capacity(
        connection,
        evidence['start_operation_id'],
        evidence['environment_id'],
        evidence['capacity'],
        released,
        recorded=recorded,
    )


def completed_stop_evidence(connection, catalog, binding):
    try:
        return stop_evidence(connection, catalog, binding)
    except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error


def stop_evidence(connection, catalog, binding):
    operation = original_operation(connection, binding)
    require(
        matching_original(STOP_COMPLETED, operation['action'], operation['status'])
        and operation['cancel_requested'] == 0
        and operation['registry_generation'] == catalog.scope['registry_generation'],
        UNVERIFIED,
    )
    intent = lifecycle_intent(decoded(operation['intent_json']))
    require(
        intent['action'] == 'STOP'
        and digest(canonical(intent)) == operation['intent_sha256']
        and intent['environment_id'] == operation['environment_id']
        and intent['expected_record_version'] == operation['expected_record_version']
        and intent['expected_assignment_generation'] == operation['expected_assignment_generation'],
        UNVERIFIED,
    )
    steps = connection.execute(
        'SELECT * FROM management_steps WHERE operation_id=? ORDER BY ordinal',
        (operation['operation_id'],),
    ).fetchall()
    require(len(steps) == 1, UNVERIFIED)
    step = steps[0]
    require(
        step['ordinal'] == 1
        and step['step_kind'] == STEP
        and step['status'] == STOP_STEP_STATES[operation['status']],
        UNVERIFIED,
    )
    identifier = operation['operation_id']
    target = intent['target']['run_id']
    external = None
    if step['status'] == 'PLANNED':
        require(step['executor_ref'] is None and step['external_identity_json'] is None, UNVERIFIED)
    else:
        require(
            step['executor_ref'] == EXECUTOR and type(step['external_identity_json']) is str,
            UNVERIFIED,
        )
        external = original_runtime_identity(decoded(step['external_identity_json']), identifier)
    require_no_claims(connection, identifier)
    receipt = observed_stop_receipt(
        catalog, identifier, operation['environment_id'], target, external
    )
    source = {'start_operation_id': receipt['start_operation_id'], 'run_id': receipt['run_id']}
    require_stopped_source(connection, operation, source)
    sample = receipt['observation']
    result = {
        'environment_id': operation['environment_id'],
        'run_id': source['run_id'],
        'runtime_state': 'STOPPED',
        'observed_at': sample['observed_at'],
        'proof_id': sample['proof_id'],
    }
    if step['status'] == 'SUCCEEDED':
        require(
            type(step['result_json']) is str
            and canonical(decoded(step['result_json'])) == canonical(result),
            UNVERIFIED,
        )
    else:
        require(step['result_json'] is None, UNVERIFIED)
    return {
        **{field: binding[field] for field in ORIGINAL_FIELDS},
        'environment_id': operation['environment_id'],
        'original_status': operation['status'],
        'step_kind': STEP,
        'step_status': step['status'],
        **source,
        'completion': result,
        'stop_receipt_sha256': digest(canonical(receipt)),
        'disposition': STOP_COMPLETED,
    }
