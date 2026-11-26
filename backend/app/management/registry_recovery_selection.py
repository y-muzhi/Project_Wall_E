"""Atomically select a recovered registry while its original dispatch remains paused."""

from collections import Counter
from types import SimpleNamespace
import os

from backend.app.infrastructure.environment_backup_package import read_policy
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import now, require_fresh
from .registry import is_timestamp, verify_file
from .registry_dispatch import dispatch_lock
from .registry_installation import ANCHOR_NAME, load_installation, read_registry_anchor
from .registry_recovery import recovery_scope, verify_pause
from .registry_recovery_effects import unit_observation
from .registry_recovery_installation import HOST_OBSERVATIONS, SELECTION_RECEIPT, SOURCE_ANCHOR
from .registry_recovery_inventory import (
    DIRECTORY as INVENTORY,
    inventory_readiness,
    inventory_scope,
    read_inventory,
)
from .registry_recovery_observation import (
    OBSERVATIONS,
    inventory_rows,
    observation_scope,
    protected_observations,
    read_observation,
)
from .registry_recovery_readiness import READY, prepared_slot, verify_initialization
from .registry_snapshot import snapshot_directory
from .runtime_observation import SYSTEMCTL, trusted_executable

POLICY = 'registry-recovery-selection-policy.v1.json'
SELECTED = 'MANAGEMENT_REGISTRY_RECOVERY_SELECTED_CLOSED'
INTENT = 'MANAGEMENT_REGISTRY_RECOVERY_SELECTION_INTENT'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_SELECTION_UNVERIFIED'
BUSY = 'MANAGEMENT_RECOVERY_HELPER_STILL_ACTIVE'
SHA_FIELDS = (
    'source_registry_anchor_sha256',
    'target_anchor_sha256',
    'dispatch_hold_sha256',
    'recovery_preparation_sha256',
    'placement_receipt_sha256',
    'readiness_receipt_sha256',
    'inventory_receipt_sha256',
    'observation_receipt_sha256',
    'systemctl_sha256',
)
OPERATIONS = (
    'operation_id',
    'source_registry_generation',
    'target_registry_generation',
    'observation_id',
)


def selection_policy(args):
    policy = read_policy(
        args.registry_selection_policy,
        args.registry_selection_policy_sha256,
        POLICY,
        (*OPERATIONS, *SHA_FIELDS),
    )
    require(
        all(uuid_value(policy[key]) for key in OPERATIONS)
        and all(sha_value(policy[key]) for key in SHA_FIELDS)
        and policy['source_registry_anchor_sha256'] == args.anchor_sha256
        and policy['source_registry_anchor_sha256'] != policy['target_anchor_sha256']
        and policy['source_registry_generation'] != policy['target_registry_generation'],
        UNVERIFIED,
    )
    return policy


def stage_inputs(args, policy):
    return SimpleNamespace(
        sha256=args.sha256,
        registry_recovery_policy=args.registry_recovery_policy,
        registry_recovery_policy_sha256=args.registry_recovery_policy_sha256,
        registry_recovery_receipt_sha256=policy['recovery_preparation_sha256'],
        registry_placement_receipt_sha256=policy['placement_receipt_sha256'],
    )


def receipt_scope(args, policy, target, observed):
    return {
        **policy,
        'status': INTENT,
        'selection_policy_sha256': args.registry_selection_policy_sha256,
        'recovery_policy_sha256': args.registry_recovery_policy_sha256,
        'manager_id': target.manager_id,
        'host_id': target.host_id,
        'observed_records': observed,
    }


def protected_fact(directory, name, group):
    try:
        return read_entry(directory, name, owner=0, group=group, reject_writers=0o337)
    except FileNotFoundError:
        return None


def preserve_fact(directory, name, group, expected):
    actual = protected_fact(directory, name, group)
    if actual is None:
        persisted_write(directory, name, expected, mode=0o440)
        actual = protected_fact(directory, name, group)
    require(actual == expected, UNVERIFIED)


def original_receipt(directory, args, policy, target, observed=None):
    raw = protected_fact(directory, SELECTION_RECEIPT, target.gid)
    if raw is None:
        return None
    record = decode(raw, UNVERIFIED)
    counts = record.get('observed_records')
    require(
        type(counts) is dict
        and all(
            type(key) is str and type(value) is int and value >= 0 for key, value in counts.items()
        )
        and (observed is None or observed == counts),
        UNVERIFIED,
    )
    expected = receipt_scope(args, policy, target, counts)
    require(
        exact(record, (*expected, 'selected_at'), UNVERIFIED)
        == {**expected, 'selected_at': record['selected_at']}
        and is_timestamp(record['selected_at']),
        UNVERIFIED,
    )
    return {**record, 'selection_receipt_sha256': digest(raw)}


def verified_records(path, target, scope, policy):
    result = read_observation(path, target, scope, expected=policy['observation_receipt_sha256'])
    require_fresh(result)
    counts = Counter()
    with protected_observations(path, target) as directory:
        for record in inventory_rows(directory, OBSERVATIONS):
            kind, state = record['kind'], record['state']
            require(type(kind) is str and type(state) is str, UNVERIFIED)
            counts[kind + ':' + state] += 1
            if kind == 'ORIGINAL_HELPER_STEP':
                require(
                    all(uuid_value(record[key]) for key in ('environment_id', 'operation_id')),
                    UNVERIFIED,
                )
                helper = f'walle-prep-{record["environment_id"]}-{record["operation_id"]}.service'
                for member in record['units']:
                    if member['unit'] == helper:
                        current = unit_observation(helper)
                        require(
                            current['state'] != 'UNKNOWN'
                            and current['cgroup_empty']
                            and current['main_pid'] == 0,
                            BUSY,
                        )
    require(
        sum(counts.values()) == result['artifact']['records']
        and read_observation(path, target, scope, expected=policy['observation_receipt_sha256'])
        == result,
        UNVERIFIED,
    )
    require_fresh(result)
    return dict(counts)


def validate_selection_evidence(native, target, placement, recovery, policy):
    with (
        target.private_directory(native, 'proof') as proof,
        snapshot_directory(native, target, proof, INVENTORY) as directory,
    ):
        ready = inventory_readiness(
            native, target, proof, placement, policy['readiness_receipt_sha256']
        )
        scope = inventory_scope(recovery, ready)
        index = read_inventory(
            directory, target, scope, expected=policy['inventory_receipt_sha256']
        )
        location = target.directory_root / HOST_OBSERVATIONS / policy['observation_id']
        scope = observation_scope(index, policy['observation_id'], policy['systemctl_sha256'])
        return verified_records(location, target, scope, policy)


def read_selected(native, target, args, policy):
    require(
        target.registry_generation == policy['target_registry_generation']
        and target.sha256 == policy['target_anchor_sha256'],
        UNVERIFIED,
    )
    with protected_directory(target.directory_root) as directory:
        archived = protected_fact(directory, SOURCE_ANCHOR, target.gid)
        receipt = original_receipt(directory, args, policy, target)
        require(
            archived is not None
            and digest(archived) == policy['source_registry_anchor_sha256']
            and receipt is not None,
            UNVERIFIED,
        )
        require(
            protected_fact(directory, ANCHOR_NAME, target.gid) == read_active_bytes(target.anchor),
            UNVERIFIED,
        )
    with target.private_directory(native, 'proof') as proof:
        raw = read_entry(proof, READY, owner=target.uid, group=target.gid, reject_writers=0o377)
        require(digest(raw) == policy['readiness_receipt_sha256'], UNVERIFIED)
        verify_initialization(proof, target, decode(raw, UNVERIFIED))
    with target.private_directory(native, 'data') as data:
        verify_file(native, target, data)
    return {**receipt, 'status': SELECTED}


def read_active_bytes(path):
    with protected_directory(path.parent) as directory:
        _, raw = read_registry_anchor(directory, path.name)
    return raw


def commit_selection(native, prior, args, policy, root, before, lock):
    slot_args = stage_inputs(args, policy)
    recovery = recovery_scope(prior, slot_args)
    require(
        recovery['operation_id'] == policy['operation_id']
        and recovery['registry_generation'] == policy['source_registry_generation']
        and recovery['target_registry_generation'] == policy['target_registry_generation']
        and recovery['dispatch_hold_sha256'] == policy['dispatch_hold_sha256'],
        UNVERIFIED,
    )
    verify_pause(prior, recovery)
    trusted_executable(SYSTEMCTL, policy['systemctl_sha256'])
    with prepared_slot(native, prior, slot_args, recovery, installer=True) as (
        placement,
        target,
        _,
    ):
        require(target.sha256 == policy['target_anchor_sha256'], UNVERIFIED)
        observed = validate_selection_evidence(native, target, placement, recovery, policy)
        with protected_directory(target.directory_root) as directory:
            after = protected_fact(directory, ANCHOR_NAME, target.gid)
            require(after is not None and digest(after) == target.sha256, UNVERIFIED)
            preserve_fact(directory, SOURCE_ANCHOR, target.gid, before)
            previous = original_receipt(directory, args, policy, target, observed)
            if previous is None:
                planned = {**receipt_scope(args, policy, target, observed), 'selected_at': now()}
                preserve_fact(directory, SELECTION_RECEIPT, target.gid, canonical(planned))
            os.fsync(directory)
        lock.assert_owned()
        verify_pause(prior, recovery)
        require(read_active_bytes(prior.anchor) == before, UNVERIFIED)
        persisted_write(root, ANCHOR_NAME, after, mode=0o440, replace=True)
        try:
            active = load_installation(prior.anchor, target.sha256, args.sha256, installer=True)
            require(active == target, UNVERIFIED)
            result = read_selected(native, active, args, policy)
            lock.assert_owned()
            return result
        except (EnvironmentFailure, OSError, ValueError) as error:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error


def select_registry_recovery(native, args):
    require(args.anchor.name == ANCHOR_NAME, UNVERIFIED)
    policy = selection_policy(args)
    live = read_active_bytes(args.anchor)
    anchor = digest(live)
    require(
        anchor in (policy['source_registry_anchor_sha256'], policy['target_anchor_sha256']),
        UNVERIFIED,
    )
    installed = load_installation(args.anchor, anchor, args.sha256, installer=True)
    with dispatch_lock(installed, exclusive=True) as root, installed.lock(native) as lock:
        require(read_active_bytes(args.anchor) == live, UNVERIFIED)
        if anchor == policy['target_anchor_sha256']:
            return read_selected(native, installed, args, policy)
        return commit_selection(native, installed, args, policy, root, live, lock)
