"""Fence management dispatch while the stable registry is recovered offline."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import stat

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.shared.time import utc_milliseconds

from .registry_installation import ANCHOR_NAME

HOLD_NAME = 'registry-dispatch-hold.v1.json'
PAUSED = 'MANAGEMENT_DISPATCH_PAUSED'
BUSY = 'MANAGEMENT_DISPATCH_BUSY'
UNVERIFIED = 'MANAGEMENT_DISPATCH_HOLD_UNVERIFIED'

OPEN_INTENT = 'registry-dispatch-open-intent.v1.json'
RETIRED_HOLD = 'registry-dispatch-prior-hold.v1.json'
OPEN_INTENT_STATUS = 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_OPEN_INTENT'
DISPATCH_OPENED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_OPENED'
OPEN_PINS = (
    'source_registry_anchor_sha256',
    'dispatch_hold_sha256',
    'selection_receipt_sha256',
    'inventory_receipt_sha256',
    'observation_receipt_sha256',
    'entry_admission_receipt_sha256',
    'open_policy_sha256',
    'review_sha256',
)


@contextmanager
def dispatch_directory(installation):
    with protected_directory(installation.anchor.parent) as root:
        meta = os.fstat(root)
        require(
            identity(meta) == installation.root_facts
            and meta.st_gid == installation.gid
            and stat.S_IMODE(meta.st_mode) == 0o2750,
            UNVERIFIED,
        )
        check_ext4(root)
        yield root


@contextmanager
def dispatch_lock(installation, *, exclusive):
    import fcntl

    with dispatch_directory(installation) as root:
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(root, mode | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnvironmentFailure(BUSY) from error
        try:
            yield root
        finally:
            fcntl.flock(root, fcntl.LOCK_UN)


def hold_scope(installation, operation):
    require(uuid_value(operation), UNVERIFIED)
    return {
        'format_version': 1,
        'manager_id': installation.manager_id,
        'host_id': installation.host_id,
        'registry_generation': installation.registry_generation,
        'registry_anchor_sha256': installation.sha256,
        'operation_id': operation,
    }


def hold_bytes(root, installation):
    try:
        return read_entry(root, HOLD_NAME, owner=0, group=installation.gid, reject_writers=0o337)
    except FileNotFoundError:
        return None


def require_current_dispatch_anchor(root, installation):
    raw = protected_dispatch_fact(root, ANCHOR_NAME, installation)
    require(raw is not None and digest(raw) == installation.sha256, PAUSED)


@contextmanager
def dispatch_generation(installation):
    with protected_directory(installation.directory_root) as directory:
        meta = os.fstat(directory)
        require(
            installation.generation_root_facts is not None
            and identity(meta) == installation.generation_root_facts
            and meta.st_gid == installation.gid
            and stat.S_IMODE(meta.st_mode) == 0o2750,
            UNVERIFIED,
        )
        check_ext4(directory)
        yield directory


def protected_dispatch_fact(directory, name, installation):
    try:
        return read_entry(directory, name, owner=0, group=installation.gid, reject_writers=0o337)
    except FileNotFoundError:
        return None


def selected_dispatch_intent(directory, installation):
    raw = protected_dispatch_fact(directory, OPEN_INTENT, installation)
    require(raw is not None, PAUSED)
    receipt = decode(raw, UNVERIFIED)
    scope = hold_scope(installation, receipt.get('operation_id'))
    exact(receipt, (*scope, 'status', 'source_registry_generation', *OPEN_PINS), UNVERIFIED)
    require(
        all(canonical(receipt[key]) == canonical(item) for key, item in scope.items())
        and receipt['status'] == OPEN_INTENT_STATUS
        and uuid_value(receipt['source_registry_generation'])
        and receipt['source_registry_generation'] != installation.registry_generation
        and receipt['source_registry_anchor_sha256'] != installation.sha256
        and all(sha_value(receipt[key]) for key in OPEN_PINS),
        UNVERIFIED,
    )
    return receipt, digest(raw)


def verified_retired_hold(directory, installation, receipt):
    raw = protected_dispatch_fact(directory, RETIRED_HOLD, installation)
    require(raw is not None and digest(raw) == receipt['dispatch_hold_sha256'], PAUSED)
    original_scope = {
        **hold_scope(installation, receipt['operation_id']),
        'registry_generation': receipt['source_registry_generation'],
        'registry_anchor_sha256': receipt['source_registry_anchor_sha256'],
    }
    hold_receipt(raw, original_scope)


def require_dispatch_open_locked(root, installation):
    require(hold_bytes(root, installation) is None, PAUSED)
    require_current_dispatch_anchor(root, installation)
    if installation.generation_root_facts is not None:
        with dispatch_generation(installation) as directory:
            receipt, _ = selected_dispatch_intent(directory, installation)
            verified_retired_hold(directory, installation, receipt)


def require_dispatch_open(installation):
    with dispatch_directory(installation) as root:
        require_dispatch_open_locked(root, installation)


@contextmanager
def host_dispatch(installation):
    with dispatch_lock(installation, exclusive=False) as root:
        require_dispatch_open_locked(root, installation)
        yield


def hold_receipt(raw, scope):
    value = exact(decode(raw, UNVERIFIED), (*scope, 'paused_at'), UNVERIFIED)
    timestamp = value['paused_at']
    require(type(timestamp) is str, UNVERIFIED)
    try:
        valid_timestamp = utc_milliseconds(datetime.fromisoformat(timestamp)) == timestamp
    except (ValueError, OverflowError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
    require(
        valid_timestamp
        and all(canonical(value[key]) == canonical(item) for key, item in scope.items()),
        UNVERIFIED,
    )
    return {'status': PAUSED, **value, 'hold_sha256': digest(raw)}


def pause_dispatch(native, installation, operation):
    scope = hold_scope(installation, operation)
    with dispatch_lock(installation, exclusive=True) as root, installation.lock(native) as lock:
        require_current_dispatch_anchor(root, installation)
        raw = hold_bytes(root, installation)
        if raw is None:
            raw = canonical({**scope, 'paused_at': utc_milliseconds(datetime.now(timezone.utc))})
            lock.assert_owned()
            persisted_write(root, HOLD_NAME, raw, mode=0o440)
        observed = hold_bytes(root, installation)
        require(observed == raw, UNVERIFIED)
        os.fsync(root)
        lock.assert_owned()
        return hold_receipt(raw, scope)


def observe_dispatch(installation, operation, *, current_only=False):
    scope = hold_scope(installation, operation)
    with dispatch_directory(installation) as root:
        if current_only:
            require_current_dispatch_anchor(root, installation)
        raw = hold_bytes(root, installation)
        if raw is None:
            require_dispatch_open_locked(root, installation)
            return {'status': 'MANAGEMENT_DISPATCH_OPEN', **scope}
        return hold_receipt(raw, scope)
