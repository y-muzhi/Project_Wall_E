"""Select the confirmed fixed deployment while its stable environment remains closed."""

from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace

from .environment_backup_coverage import locked_coverage
from .environment_backup_package import read_policy
from .environment_command import admission_inputs
from .environment_control import (
    CONTROL_NAME,
    control_bytes,
    read_control,
    read_release_transition,
    release_transition_name,
    selected_release_control,
)
from .environment_files import (
    EnvironmentFailure,
    MAX_REVISION,
    absolute,
    canonical,
    digest,
    persisted_write,
    require,
)
from .environment_installation import (
    ANCHOR_NAME,
    DEPLOYMENTS,
    RESTORE_MODE,
    Installation,
    sha_value,
    uuid_value,
)
from .environment_maintenance import write_fact
from .environment_recovery_installation import checked_ref
from .environment_release_preflight import (
    POLICY as PREFLIGHT_POLICY,
    ROLLBACK_POLICY,
    preflight_inputs,
)
from .environment_restore_preflight import POLICY as RESTORE_PREFLIGHT_POLICY
from .environment_restore_readiness import POLICY as RESTORE_READINESS_POLICY

POLICY = 'release-switch-policy.v1.json'
RESTORE_SWITCH_POLICY = 'restore-switch-policy.v1.json'
INVALID = 'RELEASE_SWITCH_INTENT_MISMATCH'
UNVERIFIED = 'RELEASE_SWITCH_UNVERIFIED'
DIFFERENT = 'RELEASE_SWITCH_REPLAN_REQUIRED'


@dataclass(frozen=True)
class ReleaseSelection:
    policy_sha256: str
    operation_id: str
    source: Installation
    target: Installation
    preflight: SimpleNamespace
    preflight_sha256: str
    restore_readiness: tuple[Path, str] | None = None


def selection_inputs(active, args, entry):
    policy = args.release_switch_policy.name
    require(policy in (POLICY, RESTORE_SWITCH_POLICY), INVALID)
    restore = policy == RESTORE_SWITCH_POLICY
    preflight_digest = 'restore_preflight_sha256' if restore else 'release_preflight_sha256'
    plan = read_policy(
        args.release_switch_policy,
        args.release_switch_policy_sha256,
        policy,
        (
            'operation_id',
            'source_installation_sha256',
            'target_installation',
            'target_project',
            'preflight_policy',
            preflight_digest,
            *(('readiness_policy',) if restore else ()),
        ),
    )
    require(
        uuid_value(plan['operation_id'])
        and plan['source_installation_sha256'] == args.anchor_sha256
        and sha_value(plan[preflight_digest]),
        INVALID,
    )
    source, _ = admission_inputs(args, active, args.program_sha256)
    source.check_identity(maintenance=True)
    target_anchor, target_pin = checked_ref(plan['target_installation'], ANCHOR_NAME)
    target_project = absolute(plan['target_project'], INVALID)
    target_program = entry['verify_program'](target_project)
    target, _ = admission_inputs(
        SimpleNamespace(anchor=target_anchor, anchor_sha256=target_pin, project=target_project),
        active,
        target_program,
    )
    binding = target.description.get('deployment_slot')
    require(
        binding is not None
        and 'recovery_replica' not in source.description
        and target.anchor.parent == source.environment_root / DEPLOYMENTS / target.deployment_id
        and binding['source_deployment_id'] == source.deployment_id
        and binding['source_configuration_sha256'] == source.configuration_sha256
        and target.environment_id == source.environment_id
        and target.lock_identity == source.lock_identity
        and target.roots['control'] == source.roots['control'],
        INVALID,
    )
    name = Path(plan['preflight_policy']['path']).name
    readiness = None
    if restore:
        require(
            name == RESTORE_PREFLIGHT_POLICY
            and binding['authorization_mode'] == RESTORE_MODE
            and target.data_generation != source.data_generation
            and target.roots['data'] != source.roots['data'],
            INVALID,
        )
        readiness = checked_ref(plan['readiness_policy'], RESTORE_READINESS_POLICY)
    else:
        require(
            name in (PREFLIGHT_POLICY, ROLLBACK_POLICY)
            and binding['authorization_mode']
            == ('ROLLBACK_CODE' if name == ROLLBACK_POLICY else 'SAME_SCHEMA')
            and target.data_generation == source.data_generation
            and target.roots['data'] == source.roots['data']
            and target.restore_generation_sha256 == source.restore_generation_sha256,
            INVALID,
        )
    preflight_path, preflight_pin = checked_ref(plan['preflight_policy'], name)
    preflight = SimpleNamespace(
        anchor=args.anchor,
        anchor_sha256=args.anchor_sha256,
        root=args.root,
        project=args.project,
        home=args.home,
        temporary=args.temporary,
        release_preflight_policy=preflight_path,
        release_preflight_policy_sha256=preflight_pin,
    )
    if restore:
        preflight.restore_preflight_policy = preflight_path
        preflight.restore_preflight_policy_sha256 = preflight_pin
    return ReleaseSelection(
        args.release_switch_policy_sha256,
        plan['operation_id'],
        source,
        target,
        preflight,
        plan[preflight_digest],
        readiness,
    )


def selection_subject(selection):
    return {
        'operation_id': selection.operation_id,
        'switch_policy_sha256': selection.policy_sha256,
        'preflight_policy_sha256': selection.preflight.release_preflight_policy_sha256,
        'release_preflight_sha256': selection.preflight_sha256,
        'source_installation_sha256': selection.source.anchor_sha256,
        'target_installation_sha256': selection.target.anchor_sha256,
    }


def original_transition(fd, selection):
    try:
        current = read_release_transition(fd, selection.target, selection.operation_id)
    except FileNotFoundError:
        return None
    require(
        all(current[key] == value for key, value in selection_subject(selection).items())
        and current['before']['data_generation'] == selection.source.data_generation
        and current['before']['data_root_ref'] == str(selection.source.path('data')),
        DIFFERENT,
    )
    return current


def selected_receipt(fd, selection, transition):
    try:
        require(read_control(fd, selection.target) == transition['after'], UNVERIFIED)
        os.fsync(fd)
    except (OSError, RuntimeError) as error:
        raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
    return {
        'status': 'RELEASE_DEPLOYMENT_SELECTED_CLOSED',
        'operation_id': selection.operation_id,
        'environment_id': selection.target.environment_id,
        'data_generation': selection.target.data_generation,
        'deployment_id': selection.target.deployment_id,
        'configuration_sha256': selection.target.configuration_sha256,
        'control_revision': transition['after']['control_revision'],
        'control_sha256': transition['after_sha256'],
        'transition_sha256': digest(canonical(transition)),
    }


def commit_selection(selection, before, fd, lock, **evidence):
    target = selection.target
    source = selection.source
    target.check_hold()
    after = selected_release_control(before, target)
    transition = {
        'format_version': 1,
        **selection_subject(selection),
        **evidence,
        'before_sha256': digest(canonical(before)),
        'before': before,
        'after_sha256': digest(canonical(after)),
        'after': after,
    }
    write_fact(fd, source, release_transition_name(selection.operation_id), transition, create=True)
    require(original_transition(fd, selection) == transition, UNVERIFIED)
    lock.assert_owned()
    require(read_control(fd, source) == before, DIFFERENT)
    persisted_write(fd, CONTROL_NAME, canonical(after), mode=0o640, replace=True)
    return selected_receipt(fd, selection, transition)


def select_release_deployment(native, active, args, entry):
    selection = selection_inputs(active, args, entry)
    source = selection.source
    target = selection.target
    # A lost acknowledgement is reconciled before re-reading obsolete source data.
    with source.lock(native), source.directory(native, 'control') as fd:
        previous = original_transition(fd, selection)
        if previous is not None:
            _, raw = control_bytes(fd, source)
            if raw == canonical(previous['after']):
                return selected_receipt(fd, selection, previous)
            require(raw == canonical(previous['before']), DIFFERENT)

    if selection.restore_readiness is not None:
        from .environment_restore_switch import select_restore_deployment

        return select_restore_deployment(native, active, selection, entry)

    planned = preflight_inputs(active, selection.preflight, entry)
    observed = planned.receipt
    binding = target.description['deployment_slot']
    require(
        observed['release_preflight_sha256'] == selection.preflight_sha256
        and observed['operation_id'] == selection.operation_id
        and observed['mode'] == binding['authorization_mode']
        and observed['target_release_id'] == binding['release_id']
        and observed['target_release_manifest_sha256'] == binding['manifest_sha256']
        and observed['target_program_snapshot_sha256']
        == target.description['program_source']['sha256'],
        DIFFERENT,
    )
    with locked_coverage(native, active, planned.capture_arguments, entry) as checked:
        before = checked.control
        fd = checked.control_fd
        require(
            checked.installation == source
            and checked.facts == planned.coverage
            and before['operation_id'] == before['maintenance_id'] == selection.operation_id
            and before['plan_sha256'] == observed['maintenance_plan_sha256']
            and (before['admission'], before['closed_reason'], before['outbound_hold'])
            == ('CLOSED', 'MAINTENANCE', True)
            and 1 <= before['control_revision'] < MAX_REVISION - 3,
            DIFFERENT,
        )
        return commit_selection(
            selection,
            before,
            fd,
            checked.lock,
            backup_manifest_sha256=observed['backup_manifest_sha256'],
            logical_content_sha256=checked.facts['logical_content_sha256'],
            database_identity=checked.database_identity,
        )
