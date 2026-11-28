"""Refresh retained host observations after selecting the recovered registry."""

from contextlib import contextmanager
import os

from backend.app.infrastructure.environment_files import (
    decode,
    digest,
    identity,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value

from .operation_contract import CATALOG_NAME, RESOURCE, catalog_from_record
from .registry import verify_file
from .registry_dispatch import dispatch_lock
from .registry_installation import load_installation
from .registry_recovery import recovery_scope, verify_pause
from .registry_recovery_history import original_snapshot_catalog, source_installation
from .registry_recovery_inventory import DIRECTORY as INVENTORY, inventory_scope, read_inventory
from .registry_recovery_observation import (
    UNVERIFIED,
    check_observation_args,
    capture_observation,
    observation_scope,
)
from .registry_recovery_readiness import read_selected_readiness
from .registry_snapshot import snapshot_directory


def original_catalog(native, source, selection, args):
    path, expected = args.catalog, args.catalog_sha256
    require(path.is_absolute() and path.name == CATALOG_NAME, UNVERIFIED)
    with protected_directory(path.parent) as parent:
        directory = identity(os.fstat(parent))
        try:
            raw = read_entry(parent, path.name, owner=0)
            basis = 'INSTALLED'
        except FileNotFoundError:
            raw = original_snapshot_catalog(native, source, selection, args.sha256, expected)
            basis = 'ARCHIVED'
        require(digest(raw) == expected, RESOURCE)
        catalog = catalog_from_record(decode(raw, RESOURCE), path.parent, source)
    return catalog, basis, directory


@contextmanager
def locked_selected_observation_inputs(native, installation, args, lock):
    selection_pin = args.registry_selection_receipt_sha256
    require(sha_value(selection_pin), UNVERIFIED)
    current = load_installation(
        installation.anchor, installation.sha256, args.sha256, installer=True
    )
    require(current == installation, UNVERIFIED)
    source, selected = source_installation(
        current, args.sha256, expected=selection_pin, installer=True
    )
    recovery = recovery_scope(source, args)
    require(
        selected['operation_id'] == recovery['operation_id']
        and selected['recovery_policy_sha256'] == args.registry_recovery_policy_sha256
        and selected['recovery_preparation_sha256'] == args.registry_recovery_receipt_sha256
        and selected['placement_receipt_sha256'] == args.registry_placement_receipt_sha256
        and selected['readiness_receipt_sha256'] == args.registry_readiness_receipt_sha256
        and selected['inventory_receipt_sha256'] == args.registry_inventory_receipt_sha256
        and selected['systemctl_sha256'] == args.registry_systemctl_sha256
        and selected['observation_id'] != args.registry_observation_id
        and selected['dispatch_hold_sha256'] == recovery['dispatch_hold_sha256']
        and current.registry_generation == recovery['target_registry_generation'],
        UNVERIFIED,
    )
    verify_pause(source, recovery)
    check_observation_args(args, recovery)
    catalog, basis, catalog_directory = original_catalog(native, source, selected, args)
    with (
        current.private_directory(native, 'proof') as proof,
        current.private_directory(native, 'data') as data,
        snapshot_directory(native, current, proof, INVENTORY) as directory,
    ):
        verify_file(native, current, data)
        ready = read_selected_readiness(proof, current, selected['readiness_receipt_sha256'])
        scope = inventory_scope(recovery, ready)
        index = read_inventory(
            directory, current, scope, expected=args.registry_inventory_receipt_sha256
        )
        subject = {
            **observation_scope(
                index, args.registry_observation_id, args.registry_systemctl_sha256
            ),
            'selection_receipt_sha256': selection_pin,
            'original_catalog_source': basis,
            'original_catalog_directory_identity': catalog_directory,
        }

        def verify_source():
            require(
                read_inventory(
                    directory, current, scope, expected=args.registry_inventory_receipt_sha256
                )
                == index
                and load_installation(current.anchor, current.sha256, args.sha256, installer=True)
                == current
                and original_catalog(native, source, selected, args)
                == (catalog, basis, catalog_directory),
                UNVERIFIED,
            )
            verify_file(native, current, data)
            lock.assert_owned()
            verify_pause(source, recovery)

        yield current, catalog, directory, subject, verify_source


@contextmanager
def selected_observation_inputs(native, installation, args):
    with (
        dispatch_lock(installation, exclusive=True),
        installation.lock(native) as lock,
        locked_selected_observation_inputs(native, installation, args, lock) as inputs,
    ):
        yield inputs


def refresh_registry_recovery_observation(native, installation, args, entry):
    with selected_observation_inputs(native, installation, args) as (
        current,
        catalog,
        directory,
        subject,
        verify_source,
    ):
        return capture_observation(
            native, current, args, entry, catalog, directory, subject, verify_source
        )
