"""Select the original managed restore while its ordinary admission is closed."""

import os
from pathlib import Path
from types import SimpleNamespace

from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import (
    ANCHOR_NAME,
    DEPLOYMENTS,
    RESTORE_MODE,
    sha_value,
    uuid_value,
)
from backend.app.infrastructure.environment_release_deployment import prepare_deployment
from backend.app.infrastructure.environment_release_preflight import read_reference
from backend.app.infrastructure.environment_release_switch import RESTORE_SWITCH_POLICY
from backend.app.infrastructure.environment_restore_preflight import (
    restore_authorization,
    restore_plan,
)
from backend.app.infrastructure.environment_restore_readiness import POLICY as READINESS_POLICY

from .attachment_observation import candidate_environment, invoke_observer
from .operation_contract import (
    INVALID,
    RESOURCE,
    RESTORE_ATTACHMENT,
    RESTORE_ATTACHMENTS,
    UNAVAILABLE,
    candidate_record,
)
from .release_configuration import CHANGED
from .release_execution import environment_command, execution_directory, optional_fact, write_fact
from .release_selection import RESULT_FIELDS
from .restore_execution import (
    EXECUTIONS,
    HOLD_RECEIPT,
    RETIREMENT,
    admitted_restore,
    known_restore_maintenance,
)

SELECTED = 'restore-selected.v1.json'
PREFLIGHT_RECEIPT = 'restore-preflight-confirmed.v1.json'
TARGET_ATTACHMENT = 'restore-target-attachment.v1.json'
SELECTED_STATUS = 'MANAGED_RESTORE_SELECTION_RECORDED'
TARGET_KEYS = ('data_generation', 'deployment_id', 'configuration_sha256')


def restore_switch_references(args, admitted):
    preflight = {
        'path': str(args.restore_preflight_policy),
        'sha256': args.restore_preflight_policy_sha256,
    }
    readiness = {
        'path': str(args.restore_readiness_policy),
        'sha256': args.restore_readiness_policy_sha256,
    }
    plan = restore_plan(args.restore_preflight_policy, preflight['sha256'])
    require(
        restore_authorization(plan)
        == admitted.grant['confirmation']['restore_authorization_sha256'],
        CHANGED,
    )
    evidence = read_reference(readiness, name=READINESS_POLICY)
    return preflight, readiness, evidence


def check_restore_preflight(receipt, preview, hold, preflight, readiness):
    point = preview['backup']
    source = preview['source']
    target = preview['target']
    expected = {
        'format_version': 1,
        'status': 'CLOSED_RESTORE_PRECONDITIONS_VERIFIED',
        'restore_preflight_policy_sha256': preflight['sha256'],
        'operation_id': preview['operation_id'],
        'maintenance_plan_sha256': hold['restore_authorization_sha256'],
        'environment_id': preview['environment_id'],
        'source_data_generation': source['data_generation'],
        'source_deployment_id': source['deployment_id'],
        'source_control_revision': hold['control_revision'],
        'source_configuration_sha256': source['configuration_sha256'],
        'preserved_backup_id': preview['preserved_backup_id'],
        'selected_backup_id': point['backup_id'],
        'selected_source_data_generation': point['source_data_generation'],
        'selected_source_deployment_id': point['source_deployment_id'],
        'selected_backup_manifest_sha256': point['backup_manifest_sha256'],
        'selected_logical_content_sha256': point['logical_content_sha256'],
        'selected_backup_cutoff_at': point['cutoff_at'],
        'data_handling': preview['data_handling'],
        'target_release_id': preview['target_release_ref'],
        'target_release_manifest_sha256': preview['release_manifest_sha256'],
        'target_program_snapshot_sha256': target['program_sha256'],
        'target_data_generation': target['data_generation'],
        'target_deployment_id': target['deployment_id'],
        'target_configuration_sha256': target['configuration_sha256'],
        'schema_contract_sha256': preview['schema_contract_sha256'],
        'outbound_hold_required': True,
    }
    if preview['recovery_requirement'] == 'OFFHOST_VERIFIED':
        expected['selected_offhost_verification_sha256'] = preview['offhost_recovery'][
            'verification_sha256'
        ]
    else:
        require('selected_offhost_verification_sha256' not in receipt, CHANGED)
    observed = {key: value for key, value in receipt.items() if key != 'restore_preflight_sha256'}
    require(
        all(canonical(receipt.get(key)) == canonical(value) for key, value in expected.items())
        and digest(canonical(receipt['source_database_identity']))
        == source['database_identity_sha256']
        and receipt['restore_preflight_sha256']
        == digest(canonical(observed))
        == readiness['restore_preflight_sha256'],
        CHANGED,
    )


def restore_target_attachment(catalog, args, entry, admitted):
    source = admitted.source
    preview = admitted.grant['confirmation']
    deployment = admitted.configuration['deployment_policy']
    policy = SimpleNamespace(
        root=args.root,
        sha256=args.sha256,
        anchor=source.anchor,
        anchor_sha256=source.anchor_sha256,
        project=source.project,
        program_sha256=source.description['program_source']['sha256'],
        release_deployment_policy=Path(deployment['path']),
        release_deployment_policy_sha256=deployment['sha256'],
    )
    placed = prepare_deployment(policy, entry)
    anchor = (
        source.environment_root / DEPLOYMENTS / preview['target']['deployment_id'] / ANCHOR_NAME
    )
    expected = {
        'status': 'RELEASE_DEPLOYMENT_PREPARED',
        'anchor': str(anchor),
        'environment_id': preview['environment_id'],
        **{key: preview['target'][key] for key in TARGET_KEYS},
        'preparation_policy_sha256': deployment['sha256'],
        'release_id': preview['target_release_ref'],
        'manifest_sha256': preview['release_manifest_sha256'],
    }
    exact(placed, (*expected, 'anchor_sha256'), RESOURCE)
    require(
        all(placed[key] == value for key, value in expected.items())
        and sha_value(placed['anchor_sha256']),
        RESOURCE,
    )
    original = preview['source_attachment']
    attachment = {
        **catalog.candidate(original['candidate_ref'], original['sha256']),
        'candidate_ref': preview['target_attachment_ref'],
        'installation': {'path': str(anchor), 'sha256': placed['anchor_sha256']},
    }
    return candidate_record(attachment, preview['target_attachment_ref'])


def checked_target(admitted, attachment, runtime_sha):
    preview = admitted.grant['confirmation']
    candidate_record(attachment, preview['target_attachment_ref'])
    target = candidate_environment(attachment, runtime_sha)
    binding = target.description.get('deployment_slot')
    require(
        target.environment_id == preview['environment_id']
        and all(getattr(target, key) == preview['target'][key] for key in TARGET_KEYS)
        and target.description['program_source']['sha256'] == preview['target']['program_sha256']
        and target.lock_identity == admitted.source.lock_identity
        and target.roots['control'] == admitted.source.roots['control']
        and binding is not None
        and binding['authorization_mode'] == RESTORE_MODE
        and binding['release_id'] == preview['target_release_ref']
        and binding['manifest_sha256'] == preview['release_manifest_sha256']
        and target.restore_generation_sha256 is not None,
        RESOURCE,
    )
    return target


def selection_receipt(facts, grant, hold, policy, attachment):
    exact(facts, RESULT_FIELDS, RESOURCE)
    preview = grant['confirmation']
    require(
        facts['status'] == 'RELEASE_DEPLOYMENT_SELECTED_CLOSED'
        and facts['operation_id'] == preview['operation_id']
        and facts['environment_id'] == preview['environment_id']
        and all(facts[key] == preview['target'][key] for key in TARGET_KEYS)
        and facts['control_revision'] == hold['control_revision'] + 1
        and all(sha_value(facts[key]) for key in ('control_sha256', 'transition_sha256')),
        RESOURCE,
    )
    return {
        **facts,
        'format_version': 1,
        'status': SELECTED_STATUS,
        'plan_sha256': grant['plan_sha256'],
        'grant_sha256': digest(canonical(grant)),
        'maintenance_receipt_sha256': digest(canonical(hold)),
        'switch_policy_sha256': digest(canonical(policy)),
        'restore_preflight_sha256': policy['restore_preflight_sha256'],
        'restore_readiness_policy_sha256': policy['readiness_policy']['sha256'],
        'target_attachment': {
            'candidate_ref': attachment['candidate_ref'],
            'sha256': digest(canonical(attachment)),
        },
    }


def verify_selection(selected, grant, hold, policy, attachment):
    candidate_record(attachment, grant['confirmation']['target_attachment_ref'])
    facts = {
        **{key: selected[key] for key in RESULT_FIELDS},
        'status': 'RELEASE_DEPLOYMENT_SELECTED_CLOSED',
    }
    require(
        policy['target_installation'] == attachment['installation']
        and selected == selection_receipt(facts, grant, hold, policy, attachment),
        RESOURCE,
    )
    return selected


def select_managed_restore(catalog, registry, args, entry, launcher):
    require(os.geteuid() == 0 and uuid_value(args.release_operation_id), INVALID)
    with execution_directory(catalog, EXECUTIONS, args.release_operation_id) as (root, fd):
        require(optional_fact(fd, HOLD_RECEIPT) is not None, RESOURCE)
        require(optional_fact(fd, RETIREMENT) is None, UNAVAILABLE)
        admitted = admitted_restore(catalog, registry, args, launcher)
        hold = known_restore_maintenance(fd, admitted)
        preflight, readiness, evidence = restore_switch_references(args, admitted)
        previous = optional_fact(fd, RESTORE_SWITCH_POLICY)
        if previous is not None:
            require(
                previous['preflight_policy'] == preflight
                and previous['readiness_policy'] == readiness,
                CHANGED,
            )
        selected = optional_fact(fd, SELECTED)
        attachment = optional_fact(fd, TARGET_ATTACHMENT)
        if selected is not None:
            require(previous is not None and attachment is not None, RESOURCE)
            verified = verify_selection(selected, admitted.grant, hold, previous, attachment)
            os.fsync(fd)
            return verified
        source = admitted.source
        area = catalog.directory / 'observations'
        proof = optional_fact(fd, PREFLIGHT_RECEIPT)
        if proof is None:
            require(previous is None, RESOURCE)
            proof = invoke_observer(
                source.maintenance_uid,
                source.group,
                environment_command(
                    'check-restore-preflight',
                    args,
                    launcher,
                    source,
                    '--restore-preflight-policy',
                    args.restore_preflight_policy,
                    '--restore-preflight-policy-sha256',
                    preflight['sha256'],
                ),
                area,
            )
        check_restore_preflight(proof, admitted.grant['confirmation'], hold, preflight, evidence)
        write_fact(fd, PREFLIGHT_RECEIPT, proof)
        if attachment is None:
            require(previous is None, RESOURCE)
            attachment = restore_target_attachment(catalog, args, entry, admitted)
        target = checked_target(admitted, attachment, args.sha256)
        write_fact(fd, TARGET_ATTACHMENT, attachment)
        reference = attachment['candidate_ref']
        require(reference not in catalog.candidates, RESOURCE)
        with execution_directory(catalog, RESTORE_ATTACHMENTS, reference, create=True) as (
            _,
            installed,
        ):
            write_fact(installed, RESTORE_ATTACHMENT, attachment)
        policy = {
            'format_version': 1,
            'operation_id': args.release_operation_id,
            'source_installation_sha256': source.anchor_sha256,
            'target_installation': attachment['installation'],
            'target_project': str(target.project),
            'preflight_policy': preflight,
            'restore_preflight_sha256': proof['restore_preflight_sha256'],
            'readiness_policy': readiness,
        }
        pin = write_fact(fd, RESTORE_SWITCH_POLICY, policy)
        outcome = invoke_observer(
            source.maintenance_uid,
            source.group,
            environment_command(
                'select-release-deployment',
                args,
                launcher,
                source,
                '--release-switch-policy',
                root / RESTORE_SWITCH_POLICY,
                '--release-switch-policy-sha256',
                pin,
            ),
            area,
        )
        recorded = selection_receipt(outcome, admitted.grant, hold, policy, attachment)
        write_fact(fd, SELECTED, recorded)
        return recorded
