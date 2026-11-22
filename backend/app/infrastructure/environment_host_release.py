"""Authorize one verified ordinary deployment during a host recovery hold."""

from types import SimpleNamespace
import os

from .environment_backup_package import read_policy
from .environment_command import admission_inputs
from .environment_files import (
    canonical,
    digest,
    identity,
    persisted_write,
    protected_directory,
    require,
)
from .environment_host_hold import (
    TUPLE_FIELDS,
    host_control_lock,
    host_hold_bytes,
    host_hold_record,
)
from .environment_installation import (
    ANCHOR_NAME,
    HOLD_NAME,
    RESTORE_MODE,
    identity_record,
    sha_value,
    uuid_value,
)
from .environment_lock import LIBRARY_REF, NativeEnvironmentFiles
from .environment_provision import installer_lock
from .environment_recovery_installation import checked_ref
from .environment_release_open import POLICY as OPEN_POLICY, open_inputs, opening_evidence
from .environment_release_verify import checked_selected_state

POLICY = 'host-recovery-authorization.v1.json'
AUTHORIZED = 'HOST_RECOVERY_DEPLOYMENT_AUTHORIZED'
UNVERIFIED = 'HOST_RECOVERY_AUTHORIZATION_UNVERIFIED'


def authorization_inputs(args):
    policy = read_policy(
        args.anchor,
        args.anchor_sha256,
        POLICY,
        (
            'host_recovery_operation_id',
            'host_root_identity',
            'expected_host_hold_sha256',
            'installation',
            'release_operation_id',
            'release_open_policy',
        ),
    )
    identity_record(policy['host_root_identity'], UNVERIFIED)
    require(
        all(
            uuid_value(policy[key])
            for key in ('host_recovery_operation_id', 'release_operation_id')
        )
        and sha_value(policy['expected_host_hold_sha256']),
        UNVERIFIED,
    )
    anchor, pin = checked_ref(policy['installation'], ANCHOR_NAME)
    path, open_sha = checked_ref(policy['release_open_policy'], OPEN_POLICY)
    installation, _ = admission_inputs(
        SimpleNamespace(anchor=anchor, anchor_sha256=pin, project=args.project),
        SimpleNamespace(runtime_manifest_sha256=args.sha256),
        args.program_sha256,
        offline=True,
    )
    require(
        installation.description.get('deployment_slot', {}).get('authorization_mode')
        == RESTORE_MODE
        and sha_value(installation.restore_generation_sha256)
        and installation.description['model_permission_ref'] is None,
        UNVERIFIED,
    )
    launch = open_inputs(installation, policy['release_operation_id'], path, open_sha)
    grant = {
        **{key: getattr(installation, key) for key in TUPLE_FIELDS},
        'installation_sha256': pin,
        'authorization_policy_sha256': args.anchor_sha256,
        'release_open_policy_sha256': open_sha,
    }
    return installation, policy, launch, grant


def authorization_state(directory, policy, grant):
    physical = identity(os.fstat(directory))
    require(physical == policy['host_root_identity'], UNVERIFIED)
    raw = host_hold_bytes(directory)
    require(raw is not None, UNVERIFIED)
    record = host_hold_record(raw, physical)
    require(
        record['format_version'] == 2
        and record['operation_id'] == policy['host_recovery_operation_id'],
        UNVERIFIED,
    )
    for item in record['allowed_deployments']:
        if item['environment_id'] == grant['environment_id']:
            require(item == grant, UNVERIFIED)
            return record, True
    require(digest(raw) == policy['expected_host_hold_sha256'], UNVERIFIED)
    return record, False


def authorization_receipt(grant, policy):
    return {
        'status': AUTHORIZED,
        'host_recovery_operation_id': policy['host_recovery_operation_id'],
        'release_operation_id': policy['release_operation_id'],
        **grant,
        'authorization_sha256': digest(canonical(grant)),
    }


def authorize_host_recovery(args, entry, runtime_hosts):
    installation, policy, launch, grant = authorization_inputs(args)
    root = installation.environment_root.parent
    with protected_directory(root) as directory:
        _, original = authorization_state(directory, policy, grant)
    if original:
        return authorization_receipt(grant, policy)

    native = NativeEnvironmentFiles(args.root)
    entry['validate_mappings'](args.root, (args.root / LIBRARY_REF,), runtime_hosts)
    with (
        installation.lock(native) as environment_lock,
        installer_lock(root, expected_identity=policy['host_root_identity']) as directory,
        host_control_lock(directory, exclusive=True),
    ):
        record, original = authorization_state(directory, policy, grant)
        if not original:
            before = checked_selected_state(installation, native, launch, environment_lock)
            control, transition, _ = before
            require(
                control['outbound_hold'] is True
                and control['model_access']['active_permit_ref'] is None
                and transition['before']['outbound_hold'] is True,
                UNVERIFIED,
            )
            opening_evidence(launch, installation, transition)
            require(
                checked_selected_state(installation, native, launch, environment_lock) == before,
                UNVERIFIED,
            )
            environment_lock.assert_owned()
            authorized = {**record, 'allowed_deployments': [*record['allowed_deployments'], grant]}
            persisted_write(directory, HOLD_NAME, canonical(authorized), mode=0o444, replace=True)
            require(authorization_state(directory, policy, grant) == (authorized, True), UNVERIFIED)
    return authorization_receipt(grant, policy)
