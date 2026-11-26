"""Save and consume confirmed release previews in the existing registry transaction."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.shared.time import utc_milliseconds

from .attachment_observation import FRESH_MS
from .operation_contract import (
    DENIED,
    INVALID,
    RECONFIGURE,
    RELEASE,
    RELEASE_ACTIONS,
    RESOURCE,
    ROLLBACK_CODE,
    UNAVAILABLE,
    VERSION,
    version,
)
from .operation_store import (
    decoded,
    environment_row,
    insert_operation,
    insert_step,
    mutation,
    operation_by_key,
    operation_result,
    require_no_conflicting_action,
    stored,
)
from .registry import is_timestamp, verified_registry
from .release_candidates import candidate_inputs, verify_candidate
from .release_configuration import CHANGED, INCOMPATIBLE, read_configuration
from .release_observation import TUPLE_FIELDS, observed_configuration
from .runtime_capacity import CLAIM_KIND

COMMON_INPUTS = (
    'environment_id',
    'expected_record_version',
    'expected_assignment_generation',
    'configuration_ref',
)
PLAN_INPUTS = {
    RELEASE: (*COMMON_INPUTS, 'compatibility_ref', 'release_ref', 'recovery_policy_ref'),
    ROLLBACK_CODE: (
        *COMMON_INPUTS,
        'compatibility_ref',
        'retained_release_ref',
        'repair_of_operation_id',
    ),
    RECONFIGURE: (*COMMON_INPUTS, 'recovery_policy_ref'),
}
STEP = 'RELEASE_DEPLOYMENT'


def release_input(value, *, confirmation=False):
    fields = ('action', 'plan_id', 'plan_sha256') if confirmation else ('kind',)
    require(type(value) is dict, INVALID)
    action = value.get(fields[0])
    require(action in RELEASE_ACTIONS, UNAVAILABLE)
    inputs = PLAN_INPUTS[action]
    exact(value, (*fields, *inputs), INVALID)
    references = {
        RELEASE: ('compatibility_ref', 'release_ref', 'recovery_policy_ref'),
        ROLLBACK_CODE: ('compatibility_ref', 'retained_release_ref'),
        RECONFIGURE: ('recovery_policy_ref',),
    }[action]
    require(
        all(uuid_value(value[key]) for key in ('environment_id', 'configuration_ref', *references))
        and version(value['expected_record_version'])
        and version(value['expected_assignment_generation'])
        and (
            action != ROLLBACK_CODE
            or value['repair_of_operation_id'] is None
            or uuid_value(value['repair_of_operation_id'])
        ),
        INVALID,
    )
    if confirmation:
        require(uuid_value(value['plan_id']) and sha_value(value['plan_sha256']), INVALID)
    return {key: value[key] for key in inputs}


def raw_plan(connection, plan_id):
    return connection.execute(
        'SELECT * FROM management_plans WHERE plan_id=?', (plan_id,)
    ).fetchone()


def row_for_release(connection, principal, variables):
    require(principal.role == 'MANAGER', DENIED)
    row = environment_row(connection, variables['environment_id'])
    require(row is not None, DENIED)
    require(
        row['purpose'] in ('DEVELOPMENT', 'INTEGRATION')
        and row['registration_state'] == 'ACTIVE'
        and row['preparation_state'] == 'PREPARED'
        and row['assignment_control_state'] == 'OPEN'
        and row['configuration_ref'] is not None,
        UNAVAILABLE,
    )
    require(
        row['record_version'] == variables['expected_record_version']
        and row['assignment_generation'] == variables['expected_assignment_generation'],
        VERSION,
    )
    return row


def binding_for_release(catalog, row, variables, *, fresh, action=RELEASE):
    config = read_configuration(catalog, variables['configuration_ref'])
    require(
        config.action == action
        and all(variables[key] == value for key, value in config.public_references().items())
        and decoded(row['configuration_ref']) == config.source_reference
        and row['writer_principal'] == config.source['owner_principal']
        and row['task_id'] == config.source['task_id']
        and row['profile_ref'] == config.source['profile_ref']
        and row['host_id'] == catalog.scope['host_id'],
        CHANGED,
    )
    proof = observed_configuration(catalog, config, fresh=fresh)
    source = proof['source']
    work = decoded(row['work_package_json'])
    require(
        source['data_generation'] == work['data_generation']
        and source['deployment_id'] == work['deployment_id']
        and source['configuration_sha256'] == row['configuration_sha256']
        and source['program_sha256'] == row['program_source'],
        CHANGED,
    )
    return config, proof


def check_repair_reference(connection, catalog, row, variables, source):
    identifier = variables.get('repair_of_operation_id')
    if identifier is None:
        return
    original = connection.execute(
        'SELECT op.action,op.status,step.status AS step_status,step.result_json '
        'FROM management_operations AS op JOIN management_steps AS step USING(operation_id) '
        'WHERE op.operation_id=? AND op.registry_generation=? AND '
        'op.environment_id=? AND step.ordinal=1',
        (identifier, catalog.scope['registry_generation'], row['environment_id']),
    ).fetchone()
    require(
        original is not None
        and original['action'] in (*RELEASE_ACTIONS, 'RESTORE')
        and original['status'] == original['step_status'] == 'SUCCEEDED'
        and type(original['result_json']) is str,
        CHANGED,
    )
    outcome = decoded(original['result_json'])
    require(
        all(
            outcome.get(key) == source[key]
            for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        ),
        CHANGED,
    )


def no_live_reservation(connection, environment_id):
    held = connection.execute(
        'SELECT 1 FROM resource_claims WHERE environment_id=? AND kind=? AND released_at IS NULL LIMIT 1',
        (environment_id, CLAIM_KIND),
    ).fetchone()
    require(held is None, RESOURCE)


def confirmed_subject(config, proof, candidate):
    return {
        'configuration_record_sha256': config.sha256,
        'release_candidate_sha256': config.candidate_sha256,
        'release_manifest_sha256': candidate['manifest_sha256'],
        'schema_manifest_sha256': candidate['schema_manifest_sha256'],
        'runtime_manifest_sha256': candidate['runtime_manifest_sha256'],
        'schema_contract_sha256': candidate['schema_contract_sha256'],
        'verification_state': candidate['verification_readiness']['state'],
        'compatibility_sha256': config.compatibility_reference['sha256'],
        'compatibility_mode': 'SAME_SCHEMA',
        'completion': 'OPEN_TARGET',
        'recovery_policy_sha256': config.recovery_sha256,
        'recovery_requirement': config.recovery['minimum_verification'],
        'source_attachment': config.source_reference,
        'target_attachment': config.target_reference,
        'source_observation_sha256': digest(canonical(proof)),
        'source_observed_at': proof['observed_at'],
        'source_database_identity_sha256': digest(canonical(proof['source']['database_identity'])),
        'source': {
            key: proof['source'][key]
            for key in (*TUPLE_FIELDS, 'control_revision', 'control_sha256')
        },
        'target': proof['target'],
        'required_capabilities': proof['required_capabilities'],
    }


def create_preview(connection, lock, catalog, principal, variables, runtime_sha, *, action=RELEASE):
    row = row_for_release(connection, principal, variables)
    require_no_conflicting_action(connection, row['environment_id'])
    no_live_reservation(connection, row['environment_id'])
    config, proof = binding_for_release(catalog, row, variables, fresh=True, action=action)
    check_repair_reference(connection, catalog, row, variables, proof['source'])
    candidate = verify_candidate(
        catalog,
        config.release_ref,
        config.candidate_sha256,
        runtime_sha,
        candidate_inputs(connection, catalog, config.release_ref, config.candidate_sha256),
    )
    require(
        candidate['candidate_sha256'] == config.candidate_sha256
        and candidate['manifest_sha256'] == config.manifest_reference['sha256']
        and candidate['verification_readiness']['state'] == 'REQUIRED_EVIDENCE_RECORDED',
        INCOMPATIBLE,
    )
    plan_id = str(uuid4())
    instant = datetime.now(UTC)
    expires_at = utc_milliseconds(instant + timedelta(milliseconds=FRESH_MS))
    preview = {
        'kind': action,
        'plan_id': plan_id,
        'expires_at': expires_at,
        **variables,
        **confirmed_subject(config, proof, candidate),
    }
    if config.rollback_source is not None:
        preview['rollback_source_sha256'] = digest(canonical(config.rollback_source))
    elif config.target_access_sha256 is not None:
        preview['target_access_sha256'] = config.target_access_sha256
        preview['fixed_release_ref'] = config.release_ref
    pin = digest(canonical(preview))
    with mutation(connection, lock):
        require_no_conflicting_action(connection, row['environment_id'])
        no_live_reservation(connection, row['environment_id'])
        live = row_for_release(connection, principal, variables)
        live_config, live_proof = binding_for_release(
            catalog, live, variables, fresh=True, action=action
        )
        check_repair_reference(connection, catalog, live, variables, live_proof['source'])
        require((live_config, live_proof) == (config, proof), CHANGED)
        connection.execute(
            'INSERT INTO management_plans (plan_id,environment_id,principal,kind,record_version,'
            'assignment_generation,plan_sha256,preview_json,expires_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (
                plan_id,
                row['environment_id'],
                principal.id,
                action,
                row['record_version'],
                row['assignment_generation'],
                pin,
                stored(preview),
                expires_at,
            ),
        )
    return {'plan_id': plan_id, 'plan_sha256': pin, 'expires_at': expires_at, 'preview': preview}


def plan_release(native, installation, catalog, principal, body, runtime_sha):
    require(principal.role == 'MANAGER', DENIED)
    variables = release_input(body)
    with verified_registry(native, installation, writable=True) as (connection, lock):
        return create_preview(
            connection, lock, catalog, principal, variables, runtime_sha, action=body['kind']
        )


def confirmed_preview(plan, principal_id, intent, *, unused=False):
    require(
        plan is not None
        and plan['principal'] == principal_id
        and plan['environment_id'] == intent['environment_id']
        and plan['kind'] == intent['action']
        and plan['kind'] in RELEASE_ACTIONS
        and (not unused or plan['execution_operation_id'] is None),
        CHANGED,
    )
    preview = decoded(plan['preview_json'])
    require(
        preview['plan_id'] == plan['plan_id'] == intent['plan_id']
        and preview['kind'] == plan['kind']
        and preview['expires_at'] == plan['expires_at']
        and digest(canonical(preview)) == plan['plan_sha256'] == intent['plan_sha256']
        and all(preview[key] == intent[key] for key in PLAN_INPUTS[plan['kind']]),
        CHANGED,
    )
    if unused:
        require(
            is_timestamp(plan['expires_at'])
            and datetime.now(UTC) < datetime.fromisoformat(plan['expires_at']),
            CHANGED,
        )
    return preview


def accept_release(connection, lock, catalog, principal, key, intent):
    require(principal.role == 'MANAGER', DENIED)
    with mutation(connection, lock):
        row = row_for_release(connection, principal, intent)
        plan = raw_plan(connection, intent['plan_id'])
        preview = confirmed_preview(plan, principal.id, intent, unused=True)
        require_no_conflicting_action(connection, row['environment_id'])
        no_live_reservation(connection, row['environment_id'])
        config, proof = binding_for_release(
            catalog, row, intent, fresh=True, action=intent['action']
        )
        check_repair_reference(connection, catalog, row, intent, proof['source'])
        require(
            config.sha256 == preview['configuration_record_sha256']
            and digest(canonical(proof)) == preview['source_observation_sha256'],
            CHANGED,
        )
        generation = catalog.scope['registry_generation']
        operation = insert_operation(
            connection,
            generation,
            key,
            principal,
            intent,
            row['environment_id'],
            utc_milliseconds(datetime.now(UTC)),
            status='ACCEPTED',
        )
        change = connection.execute(
            'UPDATE management_plans SET execution_operation_id=? WHERE plan_id=? AND execution_operation_id IS NULL',
            (operation, plan['plan_id']),
        )
        require(change.rowcount == 1, CHANGED)
        insert_step(connection, operation, STEP, None, status='PLANNED')
        return operation_result(connection, operation_by_key(connection, generation, key))
