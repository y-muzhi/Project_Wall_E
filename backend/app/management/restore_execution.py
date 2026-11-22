"""Dispatch an original confirmed restore to the fixed ordinary maintenance entry."""

import os
from dataclasses import dataclass

from backend.app.infrastructure.environment_control import normal_stop
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import (
    WORKSPACE_PURPOSES,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.environment_maintenance import ACTIVE, POLICY as MAINTENANCE_POLICY

from .attachment_observation import candidate_environment, invoke_observer
from .lifecycle_operations import authorized, expected_versions
from .operation_contract import DENIED, INVALID, RESOURCE, UNAVAILABLE, VERSION
from .operation_store import decoded, mutation, stored
from .release_configuration import CHANGED
from .release_execution import (
    SOURCE_KEYS,
    environment_command,
    execution_directory,
    maintenance_policy,
    manager_command,
    operation_record,
    optional_fact,
    write_fact,
)
from .release_maintenance_view import confirmed_current_control
from .release_observation import deployment_subject
from .release_operations import no_live_reservation, raw_plan
from .restore_operations import ACTION, STEP, confirmed_restore, registered_restore, restore_input

EXECUTIONS = 'restore-executions'
HOLD_RECEIPT = 'restore-maintenance-closed.v1.json'
RETIREMENT = 'restore-maintenance-retired.v1.json'
HOLD_EXECUTOR = 'NATIVE_RESTORE_MAINTENANCE'


@dataclass(frozen=True)
class AdmittedRestore:
    grant: dict
    configuration: dict
    source: object


def restore_operation(connection, catalog, operation):
    return operation_record(connection, catalog, operation, action=ACTION, kind=STEP)


def original_restore_grant(connection, catalog, operation):
    principal = catalog.access(operation['principal'])
    require(principal.role == 'MANAGER', DENIED)
    intent = decoded(operation['intent_json'])
    restore_input(intent, confirmed=True)
    plan = raw_plan(connection, intent['plan_id'])
    preview = confirmed_restore(plan, principal.id, intent)
    require(
        plan['execution_operation_id'] == operation['operation_id'] == preview['operation_id'],
        CHANGED,
    )
    return (
        principal,
        intent,
        {
            'format_version': 1,
            **catalog.scope,
            'plan_sha256': intent['plan_sha256'],
            'confirmation': preview,
        },
    )


def checked_restore_configuration(catalog, grant):
    preview = grant['confirmation']
    record, pin = registered_restore(catalog, preview['target_configuration_ref'])
    require(
        pin == preview['configuration_record_sha256']
        and record['source_attachment'] == preview['source_attachment']
        and record['target_attachment_ref'] == preview['target_attachment_ref']
        and record['source_control_sha256'] == preview['source']['control_sha256']
        and record['source_database_identity_sha256']
        == preview['source']['database_identity_sha256']
        and record['environment_id'] == preview['environment_id']
        and record['release_ref'] == preview['target_release_ref']
        and record['release_candidate_sha256'] == preview['release_candidate_sha256']
        and record['recovery_policy']['sha256'] == preview['recovery_policy_sha256'],
        CHANGED,
    )
    return record


def claim_restore_maintenance(connection, lock, catalog, request):
    exact(request, ('operation_id',), INVALID)
    with mutation(connection, lock):
        operation, step = restore_operation(connection, catalog, request['operation_id'])
        principal, intent, grant = original_restore_grant(connection, catalog, operation)
        checked_restore_configuration(catalog, grant)
        if step['external_identity_json'] is not None:
            external = decoded(step['external_identity_json'])
            continuing = (
                operation['status'] in ('RUNNING', 'UNKNOWN', 'SUCCEEDED')
                and not operation['cancel_requested']
            )
            retired = (
                operation['status'] == 'CANCELLED'
                and operation['cancel_requested']
                and step['status'] == 'SKIPPED'
                and sha_value(external.get('retirement_sha256'))
            )
            require(
                (continuing or retired)
                and step['executor_ref'] == HOLD_EXECUTOR
                and external['maintenance'] == grant,
                RESOURCE,
            )
            return grant
        require(
            operation['status'] == 'ACCEPTED'
            and operation['revision'] < MAX_REVISION
            and not operation['cancel_requested']
            and step['status'] == 'PLANNED'
            and step['executor_ref'] is None,
            UNAVAILABLE,
        )
        row = authorized(connection, principal, intent['environment_id'])
        expected_versions(row, intent)
        no_live_reservation(connection, intent['environment_id'])
        preview = grant['confirmation']
        current = confirmed_current_control(catalog, row)
        require(
            decoded(row['configuration_ref']) == preview['source_attachment']
            and current is not None
            and normal_stop(current)
            and digest(canonical(current)) == preview['source']['control_observation_sha256'],
            CHANGED,
        )
        changed = connection.execute(
            "UPDATE management_operations SET status='RUNNING',revision=revision+1 "
            "WHERE operation_id=? AND status='ACCEPTED' AND revision=?",
            (operation['operation_id'], operation['revision']),
        )
        recorded = connection.execute(
            "UPDATE management_steps SET status='DISPATCHING',executor_ref=?,external_identity_json=? "
            "WHERE operation_id=? AND ordinal=1 AND status='PLANNED' AND executor_ref IS NULL",
            (HOLD_EXECUTOR, stored({'maintenance': grant}), operation['operation_id']),
        )
        require(changed.rowcount == recorded.rowcount == 1, VERSION)
        return grant


def admitted_restore(catalog, registry, args, launcher):
    operation = args.release_operation_id
    grant = invoke_observer(
        registry.uid,
        registry.gid,
        manager_command('_claim-restore-maintenance', args, launcher),
        catalog.directory / 'observations',
        input_bytes=canonical({'operation_id': operation}),
    )
    preview = grant['confirmation']
    require(
        preview['operation_id'] == operation
        and all(grant[key] == value for key, value in catalog.scope.items()),
        RESOURCE,
    )
    configuration = checked_restore_configuration(catalog, grant)
    attachment = preview['source_attachment']
    source = candidate_environment(
        catalog.candidate(attachment['candidate_ref'], attachment['sha256']), args.sha256
    )
    require(
        source.environment_id == preview['environment_id']
        and source.description['purpose'] in WORKSPACE_PURPOSES
        and 'recovery_replica' not in source.description
        and all(
            preview['source'][key] == value for key, value in deployment_subject(source).items()
        ),
        CHANGED,
    )
    return AdmittedRestore(grant, configuration, source)


def restore_maintenance_policy(admitted):
    preview = admitted.grant['confirmation']
    return {
        **maintenance_policy(
            {
                'operation_id': preview['operation_id'],
                'source': preview['source'],
                'source_database_identity_sha256': preview['source']['database_identity_sha256'],
            },
            admitted.source,
        ),
        'restore_plan': admitted.configuration['preflight_template'],
    }


def restore_maintenance_receipt(admitted, policy, pin, facts):
    exact(
        facts, ('status', 'operation_id', *SOURCE_KEYS, 'plan_sha256', 'control_revision'), RESOURCE
    )
    preview = admitted.grant['confirmation']
    require(
        facts['status'] == ACTIVE
        and facts['operation_id'] == policy['operation_id']
        and all(facts[key] == policy[key] for key in SOURCE_KEYS)
        and facts['plan_sha256'] == preview['restore_authorization_sha256']
        and facts['control_revision'] == policy['expected_control_revision'] + 1,
        RESOURCE,
    )
    return {
        'format_version': 1,
        'status': 'MANAGED_RESTORE_MAINTENANCE_CLOSED',
        'operation_id': facts['operation_id'],
        'plan_sha256': admitted.grant['plan_sha256'],
        'restore_authorization_sha256': facts['plan_sha256'],
        'grant_sha256': digest(canonical(admitted.grant)),
        'maintenance_policy_sha256': pin,
        **{key: facts[key] for key in SOURCE_KEYS},
        'control_revision': facts['control_revision'],
    }


def known_restore_maintenance(fd, admitted):
    receipt = optional_fact(fd, HOLD_RECEIPT)
    if receipt is None:
        return None
    policy = restore_maintenance_policy(admitted)
    raw = canonical(policy)
    require(canonical(optional_fact(fd, MAINTENANCE_POLICY)) == raw, RESOURCE)
    facts = {
        'status': ACTIVE,
        'operation_id': receipt['operation_id'],
        **{key: receipt[key] for key in SOURCE_KEYS},
        'plan_sha256': receipt['restore_authorization_sha256'],
        'control_revision': receipt['control_revision'],
    }
    require(receipt == restore_maintenance_receipt(admitted, policy, digest(raw), facts), RESOURCE)
    return receipt


def enter_managed_restore(catalog, registry, args, launcher):
    require(os.geteuid() == 0 and uuid_value(args.release_operation_id), INVALID)
    with execution_directory(catalog, EXECUTIONS, args.release_operation_id, create=True) as (
        root,
        fd,
    ):
        require(optional_fact(fd, RETIREMENT) is None, UNAVAILABLE)
        admitted = admitted_restore(catalog, registry, args, launcher)
        known = known_restore_maintenance(fd, admitted)
        if known is not None:
            os.fsync(fd)
            return known
        policy = restore_maintenance_policy(admitted)
        pin = write_fact(fd, MAINTENANCE_POLICY, policy)
        source = admitted.source
        facts = invoke_observer(
            source.maintenance_uid,
            source.group,
            environment_command(
                'environment-maintenance',
                args,
                launcher,
                source,
                '--maintenance-policy',
                root / MAINTENANCE_POLICY,
                '--maintenance-policy-sha256',
                pin,
                '--maintenance-action',
                'enter',
            ),
            catalog.directory / 'observations',
        )
        receipt = restore_maintenance_receipt(admitted, policy, pin, facts)
        write_fact(fd, HOLD_RECEIPT, receipt)
        return receipt
