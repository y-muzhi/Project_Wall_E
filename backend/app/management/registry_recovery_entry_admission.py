"""Admit the offline management candidate and pin the restored serving entry."""

from contextlib import contextmanager
import os
import stat

from backend.app.infrastructure.environment_backup_package import read_policy
from backend.app.infrastructure.environment_files import (
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    persisted_write,
    protected_directory,
    require,
    check_ext4,
)
from backend.app.infrastructure.environment_installation import (
    identity_record,
    sha_value,
    uuid_value,
)

from .operation_contract import CATALOG_NAME
from .registry_recovery_entry import (
    ROUTE,
    entry_assembly,
    entry_policy,
    read_candidate,
    require_socket_vacant,
)
from .registry_recovery_installation import (
    ENTRY_INPUTS,
    ENTRY_INTENT,
    ENTRY_ADMISSION,
    RECOVERY_ENTRY,
)
from .registry_recovery_selection import preserve_fact, protected_fact
from .web_installation import WEB_POLICY

POLICY = 'registry-recovery-entry-admission-policy.v1.json'
INTENT = 'MANAGEMENT_REGISTRY_RECOVERY_ENTRY_ADMISSION_INTENT'
ADMITTED = 'MANAGEMENT_REGISTRY_RECOVERY_ENTRY_ADMITTED_CLOSED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_ENTRY_ADMISSION_UNVERIFIED'
FIELDS = (
    'entry_id',
    'registry_anchor_sha256',
    'entry_policy_sha256',
    'entry_receipt_sha256',
    'gateway_directory',
    'gateway_identity',
    'gateway_group',
)
RECEIPT_FIELDS = (
    *FIELDS,
    'format_version',
    'status',
    'registry_generation',
    'manager_id',
    'host_id',
    'runtime_manifest_sha256',
    'entry_admission_policy_sha256',
    'route_sha256',
    'catalog_sha256',
    'web_sha256',
)


def admission_policy(installation, args, entry):
    path, pin = args.registry_entry_admission_policy, args.registry_entry_admission_policy_sha256
    policy = read_policy(path, pin, POLICY, FIELDS)
    require(
        policy['entry_id'] == entry['entry_id']
        and path == args.registry_entry_policy.parent / POLICY
        and policy['registry_anchor_sha256'] == installation.sha256
        and policy['entry_policy_sha256'] == args.registry_entry_policy_sha256
        and sha_value(policy['entry_receipt_sha256'])
        and type(policy['gateway_group']) is int
        and 1 <= policy['gateway_group'] < 2**31
        and policy['gateway_group'] != installation.gid,
        UNVERIFIED,
    )
    identity_record(policy['gateway_identity'], UNVERIFIED)
    root = absolute(policy['gateway_directory'], UNVERIFIED)
    require(
        root.name == policy['entry_id']
        and not root.is_relative_to(installation.anchor.parent)
        and not installation.anchor.parent.is_relative_to(root),
        UNVERIFIED,
    )
    return policy, root


@contextmanager
def gateway_directory(root, policy):
    with protected_directory(root) as directory:
        current = os.fstat(directory)
        require(
            identity(current) == policy['gateway_identity']
            and current.st_gid == policy['gateway_group']
            and stat.S_IMODE(current.st_mode) == 0o2750,
            UNVERIFIED,
        )
        check_ext4(directory)
        yield directory


def place_gateway(directory, policy, route):
    previous = protected_fact(directory, ROUTE, policy['gateway_group'])
    require(previous is None or previous == route, UNVERIFIED)
    if previous is None:
        persisted_write(directory, ROUTE, route, mode=0o440)
    require(protected_fact(directory, ROUTE, policy['gateway_group']) == route, UNVERIFIED)
    os.fsync(directory)


def admit_registry_recovery_entry(native, installation, args):
    entry = entry_policy(
        installation, args.registry_entry_policy, args.registry_entry_policy_sha256
    )
    policy, gateway = admission_policy(installation, args, entry)
    with (
        entry_assembly(native, installation, args, entry, require_vacant=False) as (
            current,
            lock,
            receipt,
            route,
            web,
        ),
        protected_directory(current.directory_root) as generation,
        gateway_directory(gateway, policy) as destination,
    ):
        require(policy['gateway_group'] != web.ingress_group, UNVERIFIED)
        candidate = current.directory_root / RECOVERY_ENTRY / policy['entry_id']
        verified = read_candidate(candidate, receipt)
        require(verified['entry_receipt_sha256'] == policy['entry_receipt_sha256'], UNVERIFIED)
        scope = {
            **policy,
            'registry_generation': current.registry_generation,
            'manager_id': current.manager_id,
            'host_id': current.host_id,
            'runtime_manifest_sha256': args.sha256,
            'entry_admission_policy_sha256': args.registry_entry_admission_policy_sha256,
            'route_sha256': verified['route_sha256'],
            'catalog_sha256': verified['catalog_sha256'],
            'web_sha256': verified['web_sha256'],
        }
        original = protected_fact(generation, ENTRY_ADMISSION, current.gid)
        complete = canonical({**scope, 'status': ADMITTED})
        require(original is None or original == complete, UNVERIFIED)
        if original is None:
            require_socket_vacant(web)
        previous = protected_fact(destination, ROUTE, policy['gateway_group'])
        require(previous is None or previous == route, UNVERIFIED)
        lock.assert_owned()
        preserve_fact(generation, ENTRY_INTENT, current.gid, canonical({**scope, 'status': INTENT}))
        if original is None:
            place_gateway(destination, policy, route)
            preserve_fact(generation, ENTRY_ADMISSION, current.gid, complete)
        else:
            require(previous == route, UNVERIFIED)
        lock.assert_owned()
        return {
            'status': ADMITTED,
            'registry_generation': current.registry_generation,
            'entry_id': policy['entry_id'],
            'entry_admission_receipt_sha256': digest(complete),
            'route_sha256': verified['route_sha256'],
        }


def installed_admission(installation, runtime_sha, pin):
    require(installation.generation_root_facts is not None and sha_value(pin), UNVERIFIED)
    with protected_directory(installation.directory_root) as generation:
        require(identity(os.fstat(generation)) == installation.generation_root_facts, UNVERIFIED)
        raw = protected_fact(generation, ENTRY_ADMISSION, installation.gid)
        require(raw is not None and digest(raw) == pin, UNVERIFIED)
        receipt = exact(decode(raw, UNVERIFIED), RECEIPT_FIELDS, UNVERIFIED)
    require(
        type(receipt['format_version']) is int
        and receipt['format_version'] == 1
        and uuid_value(receipt['entry_id'])
        and receipt['status'] == ADMITTED
        and receipt['registry_anchor_sha256'] == installation.sha256
        and receipt['registry_generation'] == installation.registry_generation
        and receipt['manager_id'] == installation.manager_id
        and receipt['host_id'] == installation.host_id
        and receipt['runtime_manifest_sha256'] == runtime_sha,
        UNVERIFIED,
    )
    return receipt


def verify_admitted_gateway(installation, runtime_sha, pin):
    receipt = installed_admission(installation, runtime_sha, pin)
    root = absolute(receipt['gateway_directory'], UNVERIFIED)
    with gateway_directory(root, receipt) as fd:
        route = protected_fact(fd, ROUTE, receipt['gateway_group'])
        require(route is not None and digest(route) == receipt['route_sha256'], UNVERIFIED)
    return receipt


def verify_serving_entry(installation, args):
    pin = args.registry_entry_admission_receipt_sha256
    if installation.generation_root_facts is None:
        require(pin is None, UNVERIFIED)
        return
    receipt = installed_admission(installation, args.sha256, pin)
    inputs = installation.directory_root / ENTRY_INPUTS / receipt['entry_id']
    require(
        args.catalog == inputs / CATALOG_NAME
        and args.catalog_sha256 == receipt['catalog_sha256']
        and args.web == inputs / WEB_POLICY
        and args.web_sha256 == receipt['web_sha256'],
        UNVERIFIED,
    )
