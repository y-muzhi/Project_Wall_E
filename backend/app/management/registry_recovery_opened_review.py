"""Reobserve a settled deployment against its untouched source inventory."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    require,
)

from .operation_store import stored
from .registry_recovery_deployment_authorization import authorized_deployment
from .registry_recovery_deployment_entry import admitted_deployment
from .registry_recovery_effects import (
    checked_deployment_opening,
    deployment_step_binding,
    resource_observation,
)
from .registry_recovery_observation import (
    inventory_rows,
    observe_environment,
    pending_deployment_observation,
    workspace_observer,
)
from .registry_recovery_outcome import OPENED_DEPLOYMENT
from .registry_recovery_stop import observed_stop_receipt

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_ADOPTION_EFFECT_UNVERIFIED'


def stopped_adoption(
    native, current, args, entry, catalog, row, step, subject, evidence, workspace
):
    identifier = step['operation_id']
    authorization = authorized_deployment(current, identifier, evidence['authorization_sha256'])
    verified = authorization['verification']
    scope = ('source_registry_generation', 'selection_receipt_sha256', 'inventory_receipt_sha256')
    require(
        authorization['assessment_sha256'] == evidence['assessment_sha256']
        and verified['recovery_operation_id'] == subject['operation_id']
        and all(verified[key] == subject[key] for key in scope)
        and verified['entry_admission_receipt_sha256']
        == args.registry_entry_admission_receipt_sha256
        and all(
            verified[key] == evidence[key]
            for key in (
                'target',
                'opened_receipt_sha256',
                'stop_operation_id',
                'stop_receipt_sha256',
                'environment_id',
            )
        ),
        UNVERIFIED,
    )
    physical = pending_deployment_observation(native, catalog, row, step, args.sha256, entry)
    require(
        physical['state'] == 'OPENED_STOPPED'
        and all(
            physical[key] == verified[key]
            for key in (
                'target',
                'opened_receipt_sha256',
                'closed_control_sha256',
                'database_identity',
            )
        ),
        UNVERIFIED,
    )
    _, grant, request = deployment_step_binding(step, catalog)
    receipt, attachment, _ = checked_deployment_opening(catalog, step, grant, request)
    stopped = observed_stop_receipt(
        catalog, evidence['stop_operation_id'], row['environment_id'], physical['target']['run_id']
    )
    require(
        stopped['start_operation_id'] == identifier
        and stopped['runtime_policy_sha256'] == receipt['runtime']['sha256']
        and digest(canonical(stopped)) == evidence['stop_receipt_sha256'],
        UNVERIFIED,
    )
    target = physical['target']
    selected = admitted_deployment(current, catalog, row, attachment, target, args, entry)
    require(
        selected == verified['management_entry']
        and digest(canonical(selected)) == evidence['management_entry_sha256'],
        UNVERIFIED,
    )
    projected = {
        **row,
        **{
            key: target[key] for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        },
        'configuration_ref': stored(attachment),
        'program_source': target['program_sha256'],
    }
    observed = observe_environment(native, catalog, projected, args.sha256, entry, workspace)
    require(
        observed['state'] == 'CLOSED'
        and observed['closed_reason'] == 'NORMAL_STOP'
        and observed['control_sha256'] == verified['closed_control_sha256']
        and observed['database_identity'] == verified['database_identity'],
        UNVERIFIED,
    )
    return observed, physical


def adopted_deployment_observations(
    native, current, args, entry, catalog, directory, subject, dispositions
):
    adoptions = {
        key: item['evidence']
        for key, item in dispositions.items()
        if item['outcome']['disposition'] == OPENED_DEPLOYMENT
    }
    if not adoptions:
        return {}, {}, {}
    environments, claims, steps = {}, {}, {}
    registrations = {
        row['environment_id']: row for row in inventory_rows(directory, 'environments.jsonl')
    }
    workspace = workspace_observer(args, catalog)
    for step in inventory_rows(directory, 'steps.jsonl'):
        identifier = step['operation_id']
        evidence = adoptions.get(identifier)
        if evidence is None:
            continue
        environment = step['environment_id']
        require(environment not in environments and identifier not in steps, UNVERIFIED)
        try:
            observed, physical = stopped_adoption(
                native,
                current,
                args,
                entry,
                catalog,
                registrations[environment],
                step,
                subject,
                evidence,
                workspace,
            )
        except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError):
            continue
        environments[environment] = observed
        steps[identifier] = physical
    for row in inventory_rows(directory, 'claims.jsonl'):
        if row['environment_id'] in environments:
            require(row['resource_id'] not in claims, UNVERIFIED)
            claims[row['resource_id']] = resource_observation(
                row, environments[row['environment_id']]
            )
    return environments, claims, steps


def adopted_host_rows(rows, overlays):
    environments, claims, _ = overlays
    for row in rows:
        if row['kind'] == 'ENVIRONMENT':
            yield environments.get(row['environment_id'], row)
        elif row['kind'] == 'RESOURCE_CLAIM' and row['resource_id'] in claims:
            result = claims[row['resource_id']]
            require(
                all(
                    row[key] == result[key]
                    for key in ('environment_id', 'operation_id', 'resource_kind')
                ),
                UNVERIFIED,
            )
            yield result
        else:
            yield row
