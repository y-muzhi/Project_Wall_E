"""Retire a verified recovery hold and resume management for its new registry."""

import os

from backend.app.infrastructure.environment_backup_package import read_policy
from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    decode,
    digest,
    persisted_write,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .registry_dispatch import (
    DISPATCH_OPENED,
    HOLD_NAME,
    OPEN_INTENT,
    OPEN_INTENT_STATUS,
    PAUSED,
    RETIRED_HOLD,
    dispatch_generation,
    dispatch_lock,
    hold_bytes,
    hold_receipt,
    hold_scope,
    protected_dispatch_fact,
    require_current_dispatch_anchor,
    require_dispatch_open_locked,
    selected_dispatch_intent,
    verified_retired_hold,
)
from .registry_recovery_dispatch_review import READY, review_receipt
from .registry_recovery_history import source_installation
from .registry_recovery_reobserve import locked_selected_observation_inputs

POLICY = 'registry-recovery-dispatch-open-policy.v1.json'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_OPEN_UNVERIFIED'
POLICY_FIELDS = (
    'operation_id',
    'registry_generation',
    'registry_anchor_sha256',
    'selection_receipt_sha256',
    'review_sha256',
)
CONTEXT_PINS = (
    'selection_receipt_sha256',
    'inventory_receipt_sha256',
    'observation_receipt_sha256',
    'entry_admission_receipt_sha256',
)


def observe_active_registry_dispatch(installation, operation, runtime_sha):
    scope = hold_scope(installation, operation)
    with dispatch_lock(installation, exclusive=False) as root:
        require_current_dispatch_anchor(root, installation)
        raw = hold_bytes(root, installation)
        if raw is None:
            require_dispatch_open_locked(root, installation)
            return {'status': 'MANAGEMENT_DISPATCH_OPEN', **scope}
        record = decode(raw, UNVERIFIED)
        if record.get('registry_generation') == installation.registry_generation:
            return hold_receipt(raw, scope)
        require(installation.generation_root_facts is not None, UNVERIFIED)
        original, selected = source_installation(installation, runtime_sha, installer=True)
        receipt = hold_receipt(raw, hold_scope(original, operation))
        require(
            selected['operation_id'] == operation
            and selected['dispatch_hold_sha256'] == receipt['hold_sha256'],
            UNVERIFIED,
        )
        return {
            'status': PAUSED,
            **scope,
            'paused_at': receipt['paused_at'],
            'hold_sha256': receipt['hold_sha256'],
            'paused_registry_generation': original.registry_generation,
            'paused_registry_anchor_sha256': original.sha256,
        }


def approved_dispatch_scope(installation, args):
    expected = args.registry_dispatch_open_policy_sha256
    policy = read_policy(args.registry_dispatch_open_policy, expected, POLICY, POLICY_FIELDS)
    supplied = {name: getattr(args, 'registry_' + name) for name in CONTEXT_PINS}
    require(
        installation.generation_root_facts is not None
        and policy['registry_generation'] == installation.registry_generation
        and policy['registry_anchor_sha256'] == installation.sha256
        and policy['selection_receipt_sha256'] == supplied['selection_receipt_sha256']
        and uuid_value(policy['operation_id'])
        and sha_value(policy['review_sha256'])
        and all(sha_value(pin) for pin in supplied.values()),
        UNVERIFIED,
    )
    return {
        **hold_scope(installation, policy['operation_id']),
        **supplied,
        'review_sha256': policy['review_sha256'],
        'open_policy_sha256': expected,
        'status': OPEN_INTENT_STATUS,
    }


def completed_open(installation, generation, scope):
    receipt, pin = selected_dispatch_intent(generation, installation)
    require(all(receipt[key] == expected for key, expected in scope.items()), UNVERIFIED)
    verified_retired_hold(generation, installation, receipt)
    return {**receipt, 'status': DISPATCH_OPENED, 'open_receipt_sha256': pin}


def retire_active_hold(installation, root, generation, lock, raw, scope):
    original = decode(raw, UNVERIFIED)
    intent = canonical(
        {
            **scope,
            'source_registry_generation': original['registry_generation'],
            'source_registry_anchor_sha256': original['registry_anchor_sha256'],
            'dispatch_hold_sha256': digest(raw),
        }
    )
    previous = protected_dispatch_fact(generation, OPEN_INTENT, installation)
    require(previous is None or previous == intent, UNVERIFIED)
    require(protected_dispatch_fact(generation, RETIRED_HOLD, installation) is None, UNVERIFIED)
    if previous is None:
        persisted_write(generation, OPEN_INTENT, intent, mode=0o440)
    selected_dispatch_intent(generation, installation)
    lock.assert_owned()
    require(hold_bytes(root, installation) == raw, UNVERIFIED)
    try:
        publish_directory(
            installation.anchor.parent / HOLD_NAME, installation.directory_root / RETIRED_HOLD
        )
        os.fsync(generation)
        os.fsync(root)
        require(hold_bytes(root, installation) is None, UNVERIFIED)
        require_current_dispatch_anchor(root, installation)
        result = completed_open(installation, generation, scope)
        lock.assert_owned()
        return result
    except (EnvironmentFailure, OSError) as error:
        if hold_bytes(root, installation) is None:
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        raise


def open_registry_recovery_dispatch(native, installation, args, entry):
    scope = approved_dispatch_scope(installation, args)
    with (
        dispatch_lock(installation, exclusive=True) as root,
        installation.lock(native) as lock,
        dispatch_generation(installation) as generation,
    ):
        require_current_dispatch_anchor(root, installation)
        raw = hold_bytes(root, installation)
        if raw is None:
            return completed_open(installation, generation, scope)
        with locked_selected_observation_inputs(native, installation, args, lock) as (
            current,
            catalog,
            directory,
            subject,
            verify_source,
        ):
            review = review_receipt(
                native, current, args, entry, catalog, directory, subject, verify_source
            )
            require(subject['operation_id'] == scope['operation_id'], UNVERIFIED)
            if review['status'] != READY:
                return review
            require(review['review_sha256'] == scope['review_sha256'], UNVERIFIED)
            return retire_active_hold(current, root, generation, lock, raw, scope)
