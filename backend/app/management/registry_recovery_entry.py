"""Prepare a fixed management entry for the selected registry with dispatch held."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory

from backend.app.infrastructure.environment_backup_package import read_policy
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
from backend.app.infrastructure.schema_v22_publish import publish_directory

from .management_gateway import render_gateway
from .operation_contract import CATALOG_NAME, load_catalog
from .registry import verify_file
from .registry_dispatch import dispatch_lock
from .registry_installation import load_installation
from .registry_recovery import verify_pause
from .registry_recovery_history import source_installation
from .registry_recovery_installation import ENTRY_INPUTS, RECOVERY_ENTRY
from .registry_recovery_observation import asset_observations
from .registry_recovery_readiness import read_selected_readiness
from .web_installation import WEB_POLICY, load_web

POLICY = 'registry-recovery-entry-policy.v1.json'
ACCOUNT_HASHES = 'management-web-hashes.v1.json'
RECEIPT = 'registry-recovery-entry.v1.json'
ROUTE = 'Caddyfile'
PREPARED = 'MANAGEMENT_REGISTRY_RECOVERY_ENTRY_PREPARED_CLOSED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_ENTRY_UNVERIFIED'
SHA_FIELDS = (
    'registry_anchor_sha256',
    'selection_receipt_sha256',
    'catalog_sha256',
    'web_sha256',
    'accounts_sha256',
)
ID_FIELDS = ('entry_id', 'registry_generation', 'operation_id')


def entry_policy(installation, path, expected):
    require(isinstance(path, Path), UNVERIFIED)
    policy = read_policy(path, expected, POLICY, (*ID_FIELDS, *SHA_FIELDS))
    require(
        all(uuid_value(policy[key]) for key in ID_FIELDS)
        and all(sha_value(policy[key]) for key in SHA_FIELDS)
        and path == installation.directory_root / ENTRY_INPUTS / policy['entry_id'] / POLICY
        and policy['registry_generation'] == installation.registry_generation
        and policy['registry_anchor_sha256'] == installation.sha256
        and installation.generation_root_facts is not None,
        UNVERIFIED,
    )
    return policy


def verify_selection(native, installation, policy, runtime_sha):
    source, selected = source_installation(
        installation, runtime_sha, expected=policy['selection_receipt_sha256'], installer=True
    )
    require(selected['operation_id'] == policy['operation_id'], UNVERIFIED)
    verify_pause(source, selected)
    with installation.private_directory(native, 'proof') as proof:
        read_selected_readiness(proof, installation, selected['readiness_receipt_sha256'])
    with installation.private_directory(native, 'data') as data:
        verify_file(native, installation, data)


def prepared_inputs(installation, directory, policy, *, require_vacant):
    catalog = load_catalog(directory / CATALOG_NAME, policy['catalog_sha256'], installation)
    web = load_web(directory / WEB_POLICY, policy['web_sha256'], catalog, installation)
    require(web.socket_directory.name == policy['entry_id'], UNVERIFIED)
    if require_vacant:
        require_socket_vacant(web)
    count = 0
    for asset in asset_observations(catalog):
        require(asset['state'] == 'VERIFIED', UNVERIFIED)
        count += 1
    with protected_directory(directory) as current:
        raw = read_entry(current, ACCOUNT_HASHES, owner=0, reject_writers=0o377)
    require(digest(raw) == policy['accounts_sha256'], UNVERIFIED)
    route = render_gateway(web, installation, decode(raw, UNVERIFIED))
    return route, count, web


def require_socket_vacant(web):
    try:
        web.socket_path.lstat()
    except FileNotFoundError:
        return
    require(False, UNVERIFIED)


@contextmanager
def protected_entry_directory(path):
    with protected_directory(path) as directory:
        require(stat.S_IMODE(os.fstat(directory).st_mode) == 0o700, UNVERIFIED)
        check_ext4(directory)
        yield directory


def read_candidate(directory, expected):
    with protected_entry_directory(directory) as fd:
        require(set(os.listdir(fd)) == {RECEIPT, ROUTE}, UNVERIFIED)
        raw = read_entry(fd, RECEIPT, owner=0, reject_writers=0o377)
        record = exact(decode(raw, UNVERIFIED), expected, UNVERIFIED)
        route = read_entry(fd, ROUTE, owner=0, reject_writers=0o377)
        require(
            raw == canonical(expected) and digest(route) == expected['route_sha256'], UNVERIFIED
        )
    return {**record, 'entry_receipt_sha256': digest(raw)}


def ensure_entry_store(installation):
    location = installation.directory_root / RECOVERY_ENTRY
    with protected_directory(installation.directory_root) as root:
        require(identity(os.fstat(root)) == installation.generation_root_facts, UNVERIFIED)
        if RECOVERY_ENTRY not in os.listdir(root):
            os.mkdir(RECOVERY_ENTRY, mode=0o700, dir_fd=root)
        os.fsync(root)
    return location


def publish_entry(path, receipt, route):
    if os.path.lexists(path):
        with protected_entry_directory(path.parent) as store:
            os.fsync(store)
        return read_candidate(path, receipt)

    try:
        with TemporaryDirectory(prefix='.walle-management-entry-', dir=path.parent) as temporary:
            stage = Path(temporary)
            with protected_entry_directory(stage) as directory:
                persisted_write(directory, RECEIPT, canonical(receipt), mode=0o400)
                persisted_write(directory, ROUTE, route, mode=0o400)
            publish_directory(stage, path)
        with protected_entry_directory(path.parent) as store:
            os.fsync(store)
        return read_candidate(path, receipt)
    except (EnvironmentFailure, OSError) as error:
        if os.path.lexists(path):
            raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
        raise


@contextmanager
def entry_assembly(native, installation, args, policy, *, require_vacant=True):
    path = args.registry_entry_policy
    expected = args.registry_entry_policy_sha256
    with dispatch_lock(installation, exclusive=True), installation.lock(native) as lock:
        active = load_installation(
            installation.anchor, installation.sha256, args.sha256, installer=True
        )
        require(active == installation, UNVERIFIED)
        verify_selection(native, active, policy, args.sha256)
        route, assets, web = prepared_inputs(
            active, path.parent, policy, require_vacant=require_vacant
        )
        scope = {key: policy[key] for key in (*ID_FIELDS, *SHA_FIELDS) if key != 'accounts_sha256'}
        receipt = {
            'format_version': 1,
            **scope,
            'status': PREPARED,
            'host_id': active.host_id,
            'manager_id': active.manager_id,
            'runtime_manifest_sha256': args.sha256,
            'entry_policy_sha256': expected,
            'route_sha256': digest(route),
            'catalog_assets': assets,
        }
        yield active, lock, receipt, route, web


def prepare_registry_recovery_entry(native, installation, args):
    policy = entry_policy(
        installation, args.registry_entry_policy, args.registry_entry_policy_sha256
    )
    with entry_assembly(native, installation, args, policy) as (active, lock, receipt, route, _):
        location = ensure_entry_store(active) / policy['entry_id']
        lock.assert_owned()
        result = publish_entry(location, receipt, route)
        lock.assert_owned()
        return result
