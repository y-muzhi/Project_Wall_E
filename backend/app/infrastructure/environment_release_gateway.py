"""Verify both fixed frontend versions and the unchanged companion before staging HTTPS."""

import os
from types import SimpleNamespace

from backend.app.management.release_artifacts import index_entries, indexed_files, snapshot_file

from .environment_backup_package import read_policy
from .environment_command import admission_inputs
from .environment_files import absolute, decode, require
from .environment_installation import ANCHOR_NAME, RESTORE_MODE, read_installation_anchor, sha_value
from .environment_lock import NativeEnvironmentFiles
from .environment_recovery_installation import checked_ref
from .environment_release_preflight import read_reference
from .environment_release_verify import selected_state, verified_release_receipt

POLICY = 'release-gateway-policy.v1.json'
RECEIPT = 'release-gateway-staged.v1.json'
INVALID = 'RELEASE_GATEWAY_INTENT_MISMATCH'


def load_site(ref, runtime, entry):
    anchor, expected = checked_ref(ref, ANCHOR_NAME)
    record = read_installation_anchor(anchor, expected)
    project = absolute(record['project'], INVALID)
    program = entry['verify_program'](project)
    installed, _ = admission_inputs(
        SimpleNamespace(anchor=anchor, anchor_sha256=expected, project=project), runtime, program
    )
    return installed


def static_entries(root, anchor, expected):
    checked, raw = snapshot_file(anchor, 0o444, capture=True)
    require(checked == expected, INVALID)
    index = decode(raw, INVALID)
    indexed_files(index, root, 'frontend')
    return index_entries(index, 'frontend')[0]


def same_previous_installation(previous, transition):
    before = transition['before']
    return (
        transition['source_installation_sha256'] == previous.anchor_sha256
        and before['environment_id'] == previous.environment_id
        and before['data_generation'] == previous.data_generation
        and before['data_root_ref'] == str(previous.path('data'))
        and before['deployment_id'] == previous.deployment_id
        and before['configuration_sha256'] == previous.configuration_sha256
    )


def gateway_release(args, entry):
    require(os.geteuid() == 0, INVALID)
    plan = read_policy(
        args.release_stage_policy,
        args.release_stage_policy_sha256,
        POLICY,
        (
            'previous_installation',
            'target_installation',
            'companion_installation',
            'previous_frontend_index',
            'target_verification',
            'transition_sha256',
            'control_sha256',
        ),
    )
    require(all(sha_value(plan[key]) for key in ('transition_sha256', 'control_sha256')), INVALID)
    entry['verify_runtime'](args.runtime_root, args.runtime_sha256)
    active = SimpleNamespace(runtime_manifest_sha256=args.runtime_sha256)
    previous = load_site(plan['previous_installation'], active, entry)
    target = load_site(plan['target_installation'], active, entry)
    companion = load_site(plan['companion_installation'], active, entry)
    binding = target.description.get('deployment_slot')
    require(
        binding is not None
        and binding['source_deployment_id'] == previous.deployment_id
        and binding['source_configuration_sha256'] == previous.configuration_sha256
        and previous.environment_root == target.environment_root
        and previous.environment_id == target.environment_id != companion.environment_id
        and (previous.data_generation != target.data_generation)
        == (binding['authorization_mode'] == RESTORE_MODE)
        and previous.lock_identity == target.lock_identity
        and previous.path('frontend') != target.path('frontend')
        and previous.ingress_group == target.ingress_group != companion.ingress_group
        and {target.description['purpose'], companion.description['purpose']}
        == {'DEVELOPMENT', 'INTEGRATION'}
        and all(
            'recovery_replica' not in item.description for item in (previous, target, companion)
        )
        and all(
            not args.output.parent.is_relative_to(boundary)
            and not boundary.is_relative_to(args.output.parent)
            for boundary in (
                target.environment_root,
                companion.environment_root,
                target.project,
                companion.project,
                args.runtime_root,
            )
        ),
        INVALID,
    )
    old_index, old_pin = checked_ref(plan['previous_frontend_index'], 'frontend-index.v1.json')
    old_binding = previous.description.get('deployment_slot')
    require(old_binding is None or old_binding['frontend_index_sha256'] == old_pin, INVALID)
    old = static_entries(previous.path('frontend'), old_index, old_pin)
    current = static_entries(
        target.path('frontend'),
        target.project.parent / 'frontend-index.v1.json',
        binding['frontend_index_sha256'],
    )
    require(
        all(
            old[path][1:] == current[path][1:]
            for path in set(old).intersection(current)
            if path.startswith('assets/')
        ),
        INVALID,
    )
    verification = plan['target_verification']
    proof_path = absolute(verification['path'], INVALID)
    require(not proof_path.is_relative_to(args.output.parent), INVALID)
    proof = read_reference(verification)
    _, transition, _ = selected_state(
        target,
        NativeEnvironmentFiles(args.runtime_root),
        {
            'operation_id': proof['operation_id'],
            'transition_sha256': plan['transition_sha256'],
            'control_sha256': plan['control_sha256'],
        },
    )
    require(same_previous_installation(previous, transition), INVALID)
    verified = verified_release_receipt(verification, target, transition)
    stage = {
        'format_version': 1,
        'status': 'RELEASE_GATEWAY_STAGED',
        'policy_sha256': args.release_stage_policy_sha256,
        'operation_id': verified['operation_id'],
        'target_installation_sha256': target.anchor_sha256,
        'target_environment_id': target.environment_id,
        'target_data_generation': target.data_generation,
        'target_deployment_id': target.deployment_id,
        'target_configuration_sha256': target.configuration_sha256,
        'target_frontend_index_sha256': binding['frontend_index_sha256'],
        'companion_installation_sha256': companion.anchor_sha256,
        'previous_frontend_index_sha256': old_pin,
        'transition_sha256': plan['transition_sha256'],
        'control_sha256': plan['control_sha256'],
        'target_verification_sha256': verification['sha256'],
    }
    return (target, companion), previous.path('frontend'), stage
