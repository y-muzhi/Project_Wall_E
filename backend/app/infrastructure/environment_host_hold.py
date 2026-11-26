"""Serialize host recovery fencing with the final opening of ordinary environments."""

from contextlib import contextmanager
import os

from .environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    identity,
    persisted_write,
    protected_directory,
    read_entry,
    read_protected,
    require,
)
from .environment_installation import HOLD_NAME, identity_record, sha_value, uuid_value

POLICY = 'host-recovery-policy.v1.json'
HELD = 'HOST_RECOVERY_HELD'
HOLD = 'HOST_RECOVERY_HOLD'
BUSY = 'HOST_RECOVERY_CONTROL_BUSY'
UNVERIFIED = 'HOST_RECOVERY_CONTROL_UNVERIFIED'
TUPLE_FIELDS = ('environment_id', 'data_generation', 'deployment_id')
GRANT_FIELDS = ('installation_sha256', 'authorization_policy_sha256', 'release_open_policy_sha256')


def host_hold_record(raw, root_identity):
    record = decode(raw, HOLD)
    common = ('format_version', 'recovery_hold', 'allowed_deployments')
    version = record.get('format_version')
    require(type(version) is int and version in (1, 2), HOLD)
    if version == 1:
        exact(record, common, HOLD)
    else:
        exact(record, (*common, 'operation_id', 'policy_sha256', 'host_root_identity'), HOLD)
        require(
            record['recovery_hold'] is True
            and uuid_value(record['operation_id'])
            and sha_value(record['policy_sha256'])
            and record['host_root_identity'] == root_identity,
            HOLD,
        )
    require(
        type(record['recovery_hold']) is bool and type(record['allowed_deployments']) is list,
        HOLD,
    )
    seen = set()
    for item in record['allowed_deployments']:
        exact(item, TUPLE_FIELDS if version == 1 else (*TUPLE_FIELDS, *GRANT_FIELDS), HOLD)
        values = tuple(item[field] for field in TUPLE_FIELDS)
        token = values if version == 1 else item['environment_id']
        require(
            all(uuid_value(value) for value in values)
            and token not in seen
            and (version == 1 or all(sha_value(item[field]) for field in GRANT_FIELDS)),
            HOLD,
        )
        seen.add(token)
    return record


def enforce_host_hold(record, installation, *, offline=False):
    if offline or not record['recovery_hold']:
        return
    target = {field: getattr(installation, field) for field in TUPLE_FIELDS}
    if record['format_version'] == 2:
        target['installation_sha256'] = installation.anchor_sha256
    require(
        any(
            all(item[key] == value for key, value in target.items())
            for item in record['allowed_deployments']
        ),
        HOLD,
    )


def host_hold_bytes(directory):
    try:
        return read_entry(directory, HOLD_NAME, owner=0)
    except FileNotFoundError:
        return None


@contextmanager
def host_control_lock(directory, *, exclusive):
    import fcntl

    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(directory, mode | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise EnvironmentFailure(BUSY) from error
    try:
        yield
    finally:
        fcntl.flock(directory, fcntl.LOCK_UN)


@contextmanager
def ordinary_host_admission(installation):
    root = installation.environment_root.parent
    with protected_directory(root) as directory:
        check_ext4(directory)
        with host_control_lock(directory, exclusive=False):
            raw = host_hold_bytes(directory)
            require(raw is not None, HOLD)
            root_identity = identity(os.fstat(directory))
            enforce_host_hold(host_hold_record(raw, root_identity), installation)
            yield


def host_recovery_inputs(args):
    path, pin = args.anchor, args.anchor_sha256
    require(path.name == POLICY and sha_value(pin), UNVERIFIED)
    raw = read_protected(path)
    require(digest(raw) == pin, UNVERIFIED)
    policy = exact(
        decode(raw, UNVERIFIED),
        (
            'format_version',
            'operation_id',
            'host_root',
            'host_root_identity',
            'expected_hold_sha256',
        ),
        UNVERIFIED,
    )
    require(
        type(policy['format_version']) is int
        and policy['format_version'] == 1
        and uuid_value(policy['operation_id'])
        and (policy['expected_hold_sha256'] is None or sha_value(policy['expected_hold_sha256'])),
        UNVERIFIED,
    )
    identity_record(policy['host_root_identity'], UNVERIFIED)
    root = absolute(policy['host_root'], UNVERIFIED)
    scope = {
        'format_version': 2,
        'operation_id': policy['operation_id'],
        'policy_sha256': pin,
        'host_root_identity': policy['host_root_identity'],
        'recovery_hold': True,
    }
    return root, scope, policy['expected_hold_sha256']


def current_host_receipt(directory, scope, before):
    root_identity = identity(os.fstat(directory))
    require(root_identity == scope['host_root_identity'], UNVERIFIED)
    raw = host_hold_bytes(directory)
    if raw is not None:
        record = host_hold_record(raw, root_identity)
        pin = digest(raw)
        if record['format_version'] == 2:
            require(all(record[field] == value for field, value in scope.items()), UNVERIFIED)
            return {'status': HELD, **record, 'hold_sha256': pin}
    else:
        pin = None
    require(pin == before, UNVERIFIED)
    return {'status': 'HOST_RECOVERY_NOT_ENTERED', 'operation_id': scope['operation_id']}


def enter_host_recovery(args):
    from .environment_provision import installer_lock

    root, scope, before = host_recovery_inputs(args)
    with (
        installer_lock(root, expected_identity=scope['host_root_identity']) as directory,
        host_control_lock(directory, exclusive=True),
    ):
        observed = current_host_receipt(directory, scope, before)
        if observed['status'] != HELD:
            persisted_write(
                directory,
                HOLD_NAME,
                canonical({**scope, 'allowed_deployments': []}),
                mode=0o444,
                replace=before is not None,
            )
        os.fsync(directory)
        result = current_host_receipt(directory, scope, before)
        require(result['status'] == HELD, UNVERIFIED)
    return result


def observe_host_recovery(args):
    root, scope, before = host_recovery_inputs(args)
    with protected_directory(root) as directory:
        check_ext4(directory)
        return current_host_receipt(directory, scope, before)
