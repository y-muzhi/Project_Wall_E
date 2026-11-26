"""Inspect the original plan, opening receipt and selected registry before \
any deployment adoption."""

from contextlib import contextmanager

from backend.app.infrastructure.environment_backup_package import read_policy
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)

from .attachment_observation import candidate_environment
from .management_query import business_entry
from .operation_contract import RELEASE_ACTIONS
from .operation_store import decoded
from .registry import verified_locked_registry
from .registry_dispatch import dispatch_lock, require_current_dispatch_anchor
from .registry_recovery_disposition import (
    SOURCE_FIELDS,
    original_disposition_source,
    validate_source_scope,
)
from .registry_recovery_history import historical_snapshot
from .registry_recovery_outcome import outcome_for_operation
from .registry_recovery_reobserve import original_catalog
from .registry_recovery_undispatched import original_operation
from .release_execution import HOLD_EXECUTOR as RELEASE_EXECUTOR
from .release_execution import grant_subject, operation_record
from .release_open_admission import check_open_request_shape
from .release_operations import confirmed_preview, raw_plan, release_input, row_for_release
from .release_reconciliation import (
    opened_evidence,
    opened_registration_row,
    projected_opened_registration,
    retained_business_origin,
)
from .restore_execution import HOLD_EXECUTOR as RESTORE_EXECUTOR
from .restore_execution import original_restore_grant, restore_operation
from .restore_reconciliation import opened_restore, restore_adoption
from .restore_runtime import restore_claims, restore_registry_row
from .runtime_capacity import (
    CLAIM_KIND,
    CLAIM_SCOPE,
    DIMENSIONS,
    MAXIMUM,
    MINIMUM,
    reservations_for,
)

POLICY = 'registry-recovery-opened-policy.v1.json'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_OPENING_UNVERIFIED'
INSPECTED = 'MANAGEMENT_REGISTRY_RECOVERY_OPENING_INSPECTED'


def original_opening_scope(connection, catalog, operation):
    principal = catalog.access(operation['principal'])
    intent = decoded(operation['intent_json'])
    require(
        operation['action'] in (*RELEASE_ACTIONS, 'RESTORE')
        and operation['action'] == intent['action']
        and operation['registry_generation'] == catalog.scope['registry_generation']
        and operation['status'] == 'RUNNING'
        and operation['cancel_requested'] == 0
        and principal.role == 'MANAGER'
        and intent['environment_id'] == operation['environment_id']
        and intent['expected_record_version'] == operation['expected_record_version']
        and intent['expected_assignment_generation'] == operation['expected_assignment_generation']
        and digest(canonical(intent)) == operation['intent_sha256'],
        UNVERIFIED,
    )
    plan = raw_plan(connection, intent['plan_id'])
    require(
        plan is not None
        and plan['execution_operation_id'] == operation['operation_id']
        and plan['record_version'] == operation['expected_record_version']
        and plan['assignment_generation'] == operation['expected_assignment_generation'],
        UNVERIFIED,
    )
    if operation['action'] in RELEASE_ACTIONS:
        release_input(intent, confirmation=True)
        preview = confirmed_preview(plan, principal.id, intent)
        grant = grant_subject(preview, operation, catalog)
        row = row_for_release(connection, principal, intent)
        _, step = operation_record(connection, catalog, operation['operation_id'])
    else:
        principal, intent, grant = original_restore_grant(connection, catalog, operation)
        row = restore_registry_row(connection, principal, intent, grant)
        _, step = restore_operation(connection, catalog, operation['operation_id'])
    require(
        row['host_id'] == catalog.scope['host_id']
        and connection.execute(
            'SELECT COUNT(*) FROM management_steps WHERE operation_id=?',
            (operation['operation_id'],),
        ).fetchone()[0]
        == 1
        and step['status'] == 'DISPATCHING'
        and step['executor_ref']
        == (RELEASE_EXECUTOR if operation['action'] in RELEASE_ACTIONS else RESTORE_EXECUTOR)
        and step['result_json'] is None
        and type(step['external_identity_json']) is str,
        UNVERIFIED,
    )
    external = exact(
        decoded(step['external_identity_json']), ('maintenance', 'opening'), UNVERIFIED
    )
    require(external['maintenance'] == grant, UNVERIFIED)
    request = external['opening']
    check_open_request_shape(request)
    usage = exact(request['limits'], DIMENSIONS, UNVERIFIED)
    require(
        request['operation_id'] == operation['operation_id']
        and request['environment_id'] == row['environment_id']
        and all(
            type(usage[key]) is int and MINIMUM[key] <= usage[key] <= MAXIMUM[key]
            for key in DIMENSIONS
        ),
        UNVERIFIED,
    )
    return row, grant, request, plan['plan_sha256']


def opening_claim_rows(connection, operation):
    return [
        dict(row)
        for row in connection.execute(
            'SELECT resource_id,environment_id,kind,scope_ref,locator,'
            'identity_json,quota,released_at '
            'FROM resource_claims WHERE operation_id=? ORDER BY resource_id',
            (operation['operation_id'],),
        )
    ]


def opened_claims_digest(connection, operation, *, released=False):
    claims = opening_claim_rows(connection, operation)
    if released:
        claims = [
            {**row, 'released_at': None}
            if row['kind'] == CLAIM_KIND and row['scope_ref'] == CLAIM_SCOPE
            else row
            for row in claims
        ]
    return digest(canonical(claims))


def original_opening_claims(connection, operation, environment, expected):
    claims = opening_claim_rows(connection, operation)
    capacity = reservations_for(connection, operation['operation_id'])
    capacity_ids = {row['resource_id'] for row in capacity}
    resources = [
        {
            'kind': row['kind'],
            'scope': row['scope_ref'],
            'locator': row['locator'],
            'object_identity': decoded(row['identity_json']) if row['identity_json'] else None,
        }
        for row in claims
        if row['resource_id'] not in capacity_ids
    ]
    require(
        all(row['environment_id'] == environment and row['released_at'] is None for row in claims)
        and sorted(map(canonical, resources)) == sorted(map(canonical, expected)),
        UNVERIFIED,
    )
    return digest(canonical(claims))


def opened_registration_projection(connection, catalog, policy, runtime_sha):
    operation = original_operation(connection, policy)
    require(outcome_for_operation(connection, operation['operation_id']) is None, UNVERIFIED)
    row, grant, request, plan_sha = original_opening_scope(connection, catalog, operation)
    recovery, origin = None, None
    if operation['action'] in RELEASE_ACTIONS:
        receipt = opened_evidence(catalog, grant, request)
        adoption = grant
        origin = retained_business_origin(catalog, row, operation['action'])
    else:
        restored = opened_restore(catalog, grant, request)
        require(restored is not None, UNVERIFIED)
        selected, receipt = restored
        adoption, recovery = restore_adoption(grant, selected)
        origin = business_entry(catalog, row, decoded(row['work_package_json']))
    require(receipt is not None, UNVERIFIED)
    attachment = adoption['target_attachment']
    candidate = catalog.candidate(attachment['candidate_ref'], attachment['sha256'])
    target = candidate_environment(candidate, runtime_sha)
    require(
        candidate['profile_ref'] == row['profile_ref']
        and target.environment_id == row['environment_id']
        and target.data_generation == request['data_generation']
        and target.deployment_id == request['deployment_id']
        and target.configuration_sha256 == request['configuration_sha256']
        and target.description['program_source']['sha256'] == adoption['target']['program_sha256'],
        UNVERIFIED,
    )
    required_resources = [] if recovery is None else restore_claims(target)
    work, outcome = projected_opened_registration(
        connection,
        operation,
        row,
        adoption,
        request,
        receipt,
        recovery=recovery,
        business_entry=origin,
    )
    claims_sha = original_opening_claims(
        connection, operation, row['environment_id'], required_resources
    )
    evidence = {
        'operation_id': operation['operation_id'],
        'action': operation['action'],
        'environment_id': row['environment_id'],
        'source_revision': operation['revision'],
        'source_registration_sha256': digest(canonical(dict(row))),
        'source_record_version': row['record_version'],
        'plan_sha256': plan_sha,
        'opened_receipt_sha256': digest(canonical(receipt)),
        'claims_sha256': claims_sha,
        'target_registration_sha256': digest(
            canonical(
                {
                    'record_version': outcome['record_version'],
                    'configuration_ref': adoption['target_attachment'],
                    'configuration_sha256': adoption['target']['configuration_sha256'],
                    'program_source': adoption['target']['program_sha256'],
                    'work_package': work,
                }
            )
        ),
        'target_program_sha256': adoption['target']['program_sha256'],
        'result': outcome,
    }

    return row, opened_registration_row(row, adoption, work, outcome), evidence


def opened_registration_assessment(connection, catalog, policy, runtime_sha):
    _, _, evidence = opened_registration_projection(connection, catalog, policy, runtime_sha)
    return evidence


def assessment_result(installation, policy, pin, evidence):
    result = {
        'status': INSPECTED,
        'source_registry_generation': policy['source_registry_generation'],
        'registry_generation': installation.registry_generation,
        'selection_receipt_sha256': policy['selection_receipt_sha256'],
        'source_snapshot_sha256': pin,
        'assessment': evidence,
    }
    return {**result, 'assessment_sha256': digest(canonical(result))}


@contextmanager
def locked_opening_inputs(native, installation, args, policy):
    validate_source_scope(installation, args, policy)
    with dispatch_lock(installation, exclusive=False) as root, installation.lock(native) as lock:
        require_current_dispatch_anchor(root, installation)
        source, selected = original_disposition_source(native, installation, root, args, policy)
        original = original_catalog(native, source, selected, args)
        catalog, _, directory_identity = original
        require(directory_identity == policy['source_catalog_directory_identity'], UNVERIFIED)

        def verify_scope():
            require(
                original_catalog(native, source, selected, args) == original
                and original_disposition_source(native, installation, root, args, policy)
                == (source, selected),
                UNVERIFIED,
            )
            lock.assert_owned()

        with historical_snapshot(native, source, selected, args.sha256) as (connection, _, pin):
            require(pin == policy['source_snapshot_sha256'], UNVERIFIED)
            yield catalog, lock, connection, pin, verify_scope


def inspect_recovered_deployment(native, installation, args):
    try:
        policy = read_policy(
            args.registry_disposition_policy,
            args.registry_disposition_policy_sha256,
            POLICY,
            SOURCE_FIELDS,
        )
        with locked_opening_inputs(native, installation, args, policy) as (
            catalog,
            lock,
            archived,
            pin,
            verify_scope,
        ):
            evidence = opened_registration_assessment(archived, catalog, policy, args.sha256)
            with verified_locked_registry(native, installation, lock, read_only=True) as connection:
                copied = opened_registration_assessment(connection, catalog, policy, args.sha256)
                require(copied == evidence, UNVERIFIED)
            verify_scope()
            return assessment_result(installation, policy, pin, evidence)
    except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
