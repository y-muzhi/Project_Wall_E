"""Allow the first ordinary start to use a preserved stop across registry generations."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import public_facts
from .operation_contract import INVALID
from .registry_dispatch import dispatch_generation, require_dispatch_open, selected_dispatch_intent
from .registry_recovery_deployment_authorization import authorized_deployment
from .registry_recovery_disposition import RECEIPTS, receipt_bytes
from .registry_recovery_disposition_receipts import read_permitted_receipt
from .registry_recovery_effects import unit_observation
from .registry_recovery_entry_admission import verify_admitted_gateway
from .registry_recovery_history import (
    retained_snapshot_metadata,
    snapshot_matches_selection_pause,
    source_installation,
)
from .registry_recovery_installation import ENTRY_INPUTS
from .registry_recovery_observation import observed_stopped
from .registry_recovery_outcome import OPENED_DEPLOYMENT
from .registry_recovery_stop import stopped_runtime_unit
from .registry_snapshot import snapshot_directory

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_RESTART_UNVERIFIED'


def recovery_predecessor(plan):
    predecessor = exact(
        plan['previous_registry_adoption'],
        ('deployment_operation_id', 'authorization_sha256', 'settlement_receipt_sha256'),
        INVALID,
    )
    require(
        uuid_value(plan['previous_stop_operation_id'])
        and 'previous_cancel_control_key' not in plan
        and uuid_value(predecessor['deployment_operation_id'])
        and predecessor['deployment_operation_id']
        not in (plan['start_operation_id'], plan['previous_stop_operation_id'])
        and all(
            sha_value(predecessor[key])
            for key in ('authorization_sha256', 'settlement_receipt_sha256')
        ),
        INVALID,
    )
    return predecessor


def settled_predecessor(native, installation, args, predecessor, opened):
    identifier = predecessor['deployment_operation_id']
    authorization = authorized_deployment(
        installation, identifier, predecessor['authorization_sha256']
    )
    verified = authorization['verification']
    source, selection = source_installation(
        installation, args.sha256, expected=opened['selection_receipt_sha256'], installer=True
    )
    require(
        source.registry_generation == opened['source_registry_generation']
        and source.sha256 == opened['source_registry_anchor_sha256']
        and selection['operation_id'] == verified['recovery_operation_id'] == opened['operation_id']
        and all(
            verified[key] == opened[key]
            for key in (
                'source_registry_generation',
                'selection_receipt_sha256',
                'inventory_receipt_sha256',
                'entry_admission_receipt_sha256',
            )
        ),
        UNVERIFIED,
    )
    with retained_snapshot_metadata(native, source, selection, args.sha256) as (_, snapshot):
        require(snapshot_matches_selection_pause(snapshot, selection), UNVERIFIED)
        pin = snapshot['receipt_sha256']
    with (
        installation.private_directory(native, 'proof') as proof,
        snapshot_directory(native, installation, proof, RECEIPTS) as directory,
    ):
        raw = receipt_bytes(directory, identifier, installation)
        require(
            raw is not None and digest(raw) == predecessor['settlement_receipt_sha256'], UNVERIFIED
        )
        adopted = read_permitted_receipt(raw, identifier, installation, opened, pin)

    evidence = adopted['evidence']
    require(
        evidence['disposition'] == OPENED_DEPLOYMENT
        and evidence['authorization_sha256'] == predecessor['authorization_sha256']
        and evidence['assessment_sha256'] == authorization['assessment_sha256']
        and all(
            evidence[key] == verified[key]
            for key in (
                'target',
                'opened_receipt_sha256',
                'stop_receipt_sha256',
                'stop_operation_id',
            )
        )
        and evidence['management_entry_sha256'] == digest(canonical(verified['management_entry'])),
        UNVERIFIED,
    )
    return verified


def verify_adopted_restart(native, installation, args, catalog, environment, plan):
    try:
        predecessor = recovery_predecessor(plan)
        require_dispatch_open(installation)
        with dispatch_generation(installation) as generation:
            opened, _ = selected_dispatch_intent(generation, installation)
        verified = settled_predecessor(native, installation, args, predecessor, opened)
        entry = verify_admitted_gateway(
            installation, args.sha256, verified['entry_admission_receipt_sha256']
        )
        active = verified['management_entry']
        target = {key: value for key, value in verified['target'].items() if key != 'run_id'}
        actual = public_facts(environment)
        actual.pop('purpose')
        require(
            catalog.directory == installation.directory_root / ENTRY_INPUTS / active['entry_id']
            and args.catalog_sha256 == entry['catalog_sha256'] == active['catalog_sha256']
            and entry['entry_id'] == active['entry_id']
            and plan['candidate_sha256'] == active['candidate_sha256']
            and plan['previous_stop_operation_id'] == verified['stop_operation_id']
            and actual == target,
            UNVERIFIED,
        )
        unit = stopped_runtime_unit(
            environment.environment_id, predecessor['deployment_operation_id']
        )
        with environment.lock(native) as lock:
            before = unit_observation(unit)
            physical = observed_stopped(native, environment, lock)
            require(
                before['state'] in ('ABSENT_OBSERVED', 'QUIET_OBSERVED')
                and before['main_pid'] == 0
                and before['cgroup_empty'] is True
                and physical['closed_reason'] == 'NORMAL_STOP'
                and physical['control_sha256'] == verified['closed_control_sha256']
                and physical['database_identity'] == verified['database_identity']
                and unit_observation(unit) == before,
                UNVERIFIED,
            )
            lock.assert_owned()
        require_dispatch_open(installation)
    except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
