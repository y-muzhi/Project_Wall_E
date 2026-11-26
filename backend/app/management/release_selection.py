"""Select the managed release only after the original held source and backup are verified."""

import os

from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.environment_release_preflight import (
    CANDIDATE_PROOF,
    LOCAL_PREFLIGHT,
    OFFHOST_PREFLIGHT,
    read_reference,
)
from backend.app.infrastructure.environment_release_switch import POLICY as SWITCH_POLICY

from .attachment_observation import invoke_observer
from .operation_contract import INVALID, RESOURCE, UNAVAILABLE, path_reference
from .release_configuration import CHANGED, compatibility_reference
from .release_execution import (
    HOLD_RECEIPT,
    RETIREMENT,
    RETIREMENT_INTENT,
    admitted_release,
    environment_command,
    known_maintenance,
    optional_fact,
    release_execution,
    write_fact,
)

PREFLIGHT_RECEIPT = 'release-preflight-confirmed.v1.json'
SELECTED = 'release-selected.v1.json'
RESULT_FIELDS = (
    'status',
    'operation_id',
    'environment_id',
    'data_generation',
    'deployment_id',
    'configuration_sha256',
    'control_revision',
    'control_sha256',
    'transition_sha256',
)


def check_preflight_request(args, admitted):
    reference = {
        'path': str(args.release_preflight_policy),
        'sha256': args.release_preflight_policy_sha256,
    }
    grant = admitted.grant
    registered = admitted.configuration
    previous = registered.rollback_source
    offhost = grant['recovery_requirement'] == 'OFFHOST_VERIFIED'
    names = OFFHOST_PREFLIGHT if offhost else LOCAL_PREFLIGHT
    policy = read_reference(reference, name=names[registered.deployment_mode])
    require(
        registered.recovery['minimum_verification'] == grant['recovery_requirement']
        and policy['format_version'] == (2 if offhost else 1),
        CHANGED,
    )
    if offhost:
        verify_preflight_authority(policy, registered)
    candidate = read_reference(policy['candidate_proof'], name=CANDIDATE_PROOF)
    require(
        policy['operation_id'] == grant['operation_id']
        and policy['installation_sha256'] == grant['source']['installation_sha256']
        and policy['target_manifest'] == registered.manifest_reference
        and policy['compatibility_ref'] == compatibility_reference(registered)
        and (previous is None or all(policy[key] == value for key, value in previous.items()))
        and (
            registered.target_access_sha256 is None
            or policy.get('target_access_sha256') == registered.target_access_sha256
        )
        and candidate['candidate_sha256'] == grant['release_candidate_sha256']
        and candidate['manifest_sha256'] == grant['release_manifest_sha256'],
        CHANGED,
    )
    return reference


def verify_preflight_authority(policy, configuration):
    require(
        'offhost_authority' in configuration.recovery
        and policy.get('offhost_authority') == configuration.recovery['offhost_authority'],
        CHANGED,
    )
    _, pin = path_reference(policy.get('offhost_verification'))
    return pin


def preflight_offhost_pin(reference, admitted):
    if admitted.grant['recovery_requirement'] == 'LOCAL_VERIFIED':
        return None
    return verify_preflight_authority(read_reference(reference), admitted.configuration)


def check_preflight_receipt(receipt, admitted, hold, preflight_sha, offhost_pin=None):
    grant = admitted.grant
    source = grant['source']
    expected = {
        'format_version': 1,
        'status': 'CLOSED_RELEASE_PRECONDITIONS_VERIFIED',
        'mode': admitted.configuration.deployment_mode,
        'preflight_policy_sha256': preflight_sha,
        'operation_id': grant['operation_id'],
        'maintenance_plan_sha256': hold['maintenance_policy_sha256'],
        'source_environment_id': grant['environment_id'],
        'source_data_generation': source['data_generation'],
        'source_deployment_id': source['deployment_id'],
        'source_control_revision': hold['control_revision'],
        'source_configuration_sha256': source['configuration_sha256'],
        'target_release_id': grant['release_ref'],
        'target_release_manifest_sha256': grant['release_manifest_sha256'],
        'target_program_snapshot_sha256': grant['target']['program_sha256'],
        'schema_contract_sha256': grant['schema_contract_sha256'],
        'compatibility_id': admitted.configuration.compatibility_reference['ref'],
    }
    require(
        (admitted.grant['recovery_requirement'] == 'OFFHOST_VERIFIED') == sha_value(offhost_pin),
        RESOURCE,
    )
    if offhost_pin is not None:
        expected['backup_offhost_verification_sha256'] = offhost_pin
    previous = admitted.configuration.rollback_source
    if previous is not None:
        anchor, pin = path_reference(previous['previous_installation'])
        require(uuid_value(anchor.parent.name), RESOURCE)
        expected.update(
            previous_fixed_deployment_id=anchor.parent.name, previous_installation_sha256=pin
        )
    if admitted.configuration.target_access_sha256 is not None:
        expected['target_access_sha256'] = admitted.configuration.target_access_sha256
    exact(
        receipt,
        (
            *expected,
            'backup_id',
            'backup_manifest_sha256',
            'backup_local_verification_sha256',
            'release_preflight_sha256',
        ),
        RESOURCE,
    )
    require(
        all(canonical(receipt[key]) == canonical(value) for key, value in expected.items())
        and uuid_value(receipt['backup_id'])
        and all(
            sha_value(receipt[key])
            for key in ('backup_manifest_sha256', 'backup_local_verification_sha256')
        )
        and receipt['release_preflight_sha256']
        == digest(
            canonical(
                {key: value for key, value in receipt.items() if key != 'release_preflight_sha256'}
            )
        ),
        RESOURCE,
    )


def switch_policy(admitted, preflight_reference, preflight):
    return {
        'format_version': 1,
        'operation_id': admitted.grant['operation_id'],
        'source_installation_sha256': admitted.grant['source']['installation_sha256'],
        'target_installation': admitted.configuration.target['installation'],
        'target_project': str(admitted.pair.target.project),
        'preflight_policy': preflight_reference,
        'release_preflight_sha256': preflight['release_preflight_sha256'],
    }


def selection_result(facts, admitted, hold, preflight, policy_pin):
    exact(facts, RESULT_FIELDS, RESOURCE)
    target = admitted.grant['target']
    require(
        facts['status'] == 'RELEASE_DEPLOYMENT_SELECTED_CLOSED'
        and facts['operation_id'] == admitted.grant['operation_id']
        and facts['environment_id'] == admitted.grant['environment_id']
        and all(
            facts[key] == target[key]
            for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        )
        and facts['control_revision'] == hold['control_revision'] + 1
        and all(sha_value(facts[key]) for key in ('control_sha256', 'transition_sha256')),
        RESOURCE,
    )
    return {
        **facts,
        'format_version': 1,
        'status': 'MANAGED_RELEASE_SELECTION_RECORDED',
        'plan_sha256': admitted.grant['plan_sha256'],
        'grant_sha256': digest(canonical(admitted.grant)),
        'maintenance_receipt_sha256': digest(canonical(hold)),
        'switch_policy_sha256': policy_pin,
        'release_preflight_sha256': preflight['release_preflight_sha256'],
    }


def read_selection(fd, admitted):
    selected = optional_fact(fd, SELECTED)
    if selected is None:
        return None
    hold = known_maintenance(fd, admitted)
    require(hold is not None, RESOURCE)
    proof = optional_fact(fd, PREFLIGHT_RECEIPT)
    policy = optional_fact(fd, SWITCH_POLICY)
    require(proof is not None and policy is not None, RESOURCE)
    preflight_reference = policy['preflight_policy']
    offhost_pin = preflight_offhost_pin(preflight_reference, admitted)
    check_preflight_receipt(proof, admitted, hold, preflight_reference['sha256'], offhost_pin)
    require(policy == switch_policy(admitted, policy['preflight_policy'], proof), RESOURCE)
    measured = {
        key: ('RELEASE_DEPLOYMENT_SELECTED_CLOSED' if key == 'status' else selected[key])
        for key in RESULT_FIELDS
    }
    require(
        canonical(selected)
        == canonical(selection_result(measured, admitted, hold, proof, digest(canonical(policy)))),
        RESOURCE,
    )
    return selected


def select_managed_release(catalog, registry, args, entry, launcher):
    require(os.geteuid() == 0 and uuid_value(args.release_operation_id), INVALID)
    with release_execution(catalog, args.release_operation_id) as (root, fd):
        require(
            optional_fact(fd, RETIREMENT_INTENT) is None and optional_fact(fd, RETIREMENT) is None,
            UNAVAILABLE,
        )
        require(optional_fact(fd, HOLD_RECEIPT) is not None, RESOURCE)
        admitted = admitted_release(catalog, registry, args, entry, launcher)
        hold = known_maintenance(fd, admitted)
        preflight_reference = check_preflight_request(args, admitted)
        existing_policy = optional_fact(fd, SWITCH_POLICY)
        if existing_policy is not None:
            require(existing_policy['preflight_policy'] == preflight_reference, CHANGED)
        selected = read_selection(fd, admitted)
        if selected is not None:
            os.fsync(fd)
            return selected
        source = admitted.pair.source
        area = catalog.directory / 'observations'
        preflight = optional_fact(fd, PREFLIGHT_RECEIPT)
        if preflight is None:
            require(existing_policy is None, RESOURCE)
            preflight = invoke_observer(
                source.maintenance_uid,
                source.group,
                environment_command(
                    'check-release-preflight',
                    args,
                    launcher,
                    source,
                    '--release-preflight-policy',
                    args.release_preflight_policy,
                    '--release-preflight-policy-sha256',
                    preflight_reference['sha256'],
                ),
                area,
            )
        offhost_pin = preflight_offhost_pin(preflight_reference, admitted)
        check_preflight_receipt(
            preflight, admitted, hold, preflight_reference['sha256'], offhost_pin
        )
        write_fact(fd, PREFLIGHT_RECEIPT, preflight)
        policy = switch_policy(admitted, preflight_reference, preflight)
        pin = write_fact(fd, SWITCH_POLICY, policy)
        outcome = invoke_observer(
            source.maintenance_uid,
            source.group,
            environment_command(
                'select-release-deployment',
                args,
                launcher,
                source,
                '--release-switch-policy',
                root / SWITCH_POLICY,
                '--release-switch-policy-sha256',
                pin,
            ),
            area,
        )
        recorded = selection_result(outcome, admitted, hold, preflight, pin)
        write_fact(fd, SELECTED, recorded)
        require(read_selection(fd, admitted) == recorded, RESOURCE)
        return recorded
