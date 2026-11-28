"""Reconcile retained facts before any reopening of management dispatch."""

from collections import Counter
from itertools import islice, zip_longest

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value

from .attachment_observation import require_fresh
from .registry_recovery_disposition_receipts import (
    confirms_original_operation,
    disposition_manifest,
    permitted_dispositions,
)
from .registry_recovery_effects import DEPLOYMENT_STEPS, START_STEP, current_runtime_unit
from .registry_recovery_entry_admission import verify_admitted_gateway
from .registry_recovery_history import (
    retained_snapshot_metadata,
    snapshot_matches_selection_pause,
    source_installation,
)
from .registry_recovery_installation import HOST_OBSERVATIONS
from .registry_recovery_observation import (
    OBSERVATIONS,
    host_observations,
    inventory_rows,
    protected_observations,
    read_observation,
)
from .registry_recovery_opened_review import adopted_deployment_observations, adopted_host_rows
from .registry_recovery_outcome import (
    BACKUP_COMPLETED,
    EFFECT_DISPOSITIONS,
    OPENED_DEPLOYMENT,
    RELEASE_RETIRED,
    RESTORE_RETIRED,
    matching_original,
)
from .registry_recovery_reobserve import selected_observation_inputs
from .registry_recovery_stop import stopped_runtime_unit

READY = 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_READY'
BLOCKED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_BLOCKED'
UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_UNVERIFIED'


CATALOG_ASSET = 'ORIGINAL_CATALOG_ASSET_UNVERIFIED'
ENVIRONMENT = 'ORIGINAL_ENVIRONMENT_UNVERIFIED'
RESOURCE = 'ORIGINAL_RESOURCE_UNVERIFIED'
STEP = 'ORIGINAL_STEP_UNRESOLVED'
PREPARATION = 'ORIGINAL_PREPARATION_ACTIVE'
RUNTIME = 'ORIGINAL_RUNTIME_UNVERIFIED'
OPERATION = 'ORIGINAL_OPERATION_UNRESOLVED'
HOST_CHANGED = 'HOST_CHANGED_SINCE_OBSERVATION'
SOURCE_COVERAGE = 'ORIGINAL_SOURCE_COVERAGE_UNVERIFIED'
INSPECTED = 'MANAGEMENT_REGISTRY_RECOVERY_DISPATCH_INSPECTED'
BLOCKER_CODES = (
    CATALOG_ASSET,
    ENVIRONMENT,
    RESOURCE,
    STEP,
    PREPARATION,
    RUNTIME,
    OPERATION,
    HOST_CHANGED,
    SOURCE_COVERAGE,
)
INSPECTION_PAGE_SIZE = 25


def completed_effect_blocker(row, receipt):
    evidence = receipt['evidence']
    require(
        row['ordinal'] == 1
        and row['environment_id'] == evidence['environment_id']
        and row['step_kind'] == evidence['step_kind']
        and row['original_status'] == evidence['step_status'],
        UNVERIFIED,
    )
    units = row['units']
    if evidence['disposition'] in (BACKUP_COMPLETED, RESTORE_RETIRED, RELEASE_RETIRED):
        require(row['state'] == 'UNKNOWN' and units == [], UNVERIFIED)
        return None
    name = stopped_runtime_unit(row['environment_id'], evidence['start_operation_id'])
    require(len(units) == 1 and units[0]['unit'] == name, UNVERIFIED)
    unit = units[0]
    if (
        row['state'] == 'OBSERVED'
        and unit['state'] in ('ABSENT_OBSERVED', 'QUIET_OBSERVED')
        and type(unit.get('main_pid')) is int
        and unit['main_pid'] == 0
        and unit.get('cgroup_empty') is True
    ):
        return None
    reason = RUNTIME if unit['state'] == 'PRESENT_OBSERVED' else STEP
    return {'reason_code': reason, 'unit': name}


def runtime_unit_matches(row, unit, current):
    step = row['step_kind']
    if step in DEPLOYMENT_STEPS:
        program = row.get('opening_binding', {}).get('program_sha256')
        if not sha_value(program) or current.get('binding', {}).get('program_sha256') != program:
            return False
    elif step == START_STEP and row.get('original_operation_status') != 'CANCELLED':
        attachment = row.get('runtime_authority', {}).get('configuration_attachment')
        if attachment is None or current.get('configuration_attachment') != attachment:
            return False
    else:
        return False
    return current_runtime_unit(row, unit, current)


def blocked_subjects(rows, operations, expected_count, dispositions=None, *, adopted_steps=None):
    dispositions = {} if dispositions is None else dispositions
    adopted_steps = {} if adopted_steps is None else adopted_steps
    environments = {}
    verified_adoptions = set()
    verified_effect_steps = set()
    count = 0
    for row in rows:
        count += 1
        kind, state = row['kind'], row['state']
        if kind == 'CATALOG_ASSET':
            if state != 'VERIFIED':
                yield {
                    'reason_code': CATALOG_ASSET,
                    'kind': kind,
                    'state': state,
                    'asset_kind': row['asset_kind'],
                    'reference': row['reference'],
                }
        elif kind == 'ENVIRONMENT':
            environment = row['environment_id']
            require(environment not in environments, UNVERIFIED)
            environments[environment] = {
                key: row.get(key)
                for key in (
                    'state',
                    'binding',
                    'configuration_attachment',
                    'run_id',
                    'policy_sha256',
                    'lock_pid',
                )
                if key in row
            }
            if state not in ('CLOSED', 'RUNNING_OBSERVED'):
                yield {
                    'reason_code': ENVIRONMENT,
                    'kind': kind,
                    'state': state,
                    'environment_id': environment,
                }
        elif kind == 'RESOURCE_CLAIM':
            if state not in ('BOUND', 'PRESERVED'):
                yield {
                    'reason_code': RESOURCE,
                    'kind': kind,
                    'state': state,
                    'environment_id': row['environment_id'],
                    'operation_id': row['operation_id'],
                    'resource_id': row['resource_id'],
                    'resource_kind': row['resource_kind'],
                }
        elif kind == 'ORIGINAL_HELPER_STEP':
            subject = {
                'kind': kind,
                'state': state,
                'original_status': row['original_status'],
                'environment_id': row['environment_id'],
                'operation_id': row['operation_id'],
                'ordinal': row['ordinal'],
                'step_kind': row['step_kind'],
            }
            if 'external_deployment' in row:
                subject['external_deployment'] = row['external_deployment']
            identifier = row['operation_id']
            receipt = dispositions.get(identifier)
            if receipt is not None and receipt['outcome']['disposition'] in EFFECT_DISPOSITIONS:
                require(identifier not in verified_effect_steps, UNVERIFIED)
                verified_effect_steps.add(identifier)
                blocker = completed_effect_blocker(row, receipt)
                if blocker is not None:
                    yield {**subject, **blocker}
                continue
            if (
                receipt is not None
                and receipt['outcome']['disposition'] == OPENED_DEPLOYMENT
                and identifier in adopted_steps
                and row.get('external_deployment') == adopted_steps[identifier]
            ):
                units = row['units']
                unit = stopped_runtime_unit(row['environment_id'], identifier)
                require(
                    identifier not in verified_adoptions
                    and row['ordinal'] == 1
                    and row['original_status'] == 'DISPATCHING'
                    and row['step_kind'] in DEPLOYMENT_STEPS
                    and state == 'OBSERVED'
                    and len(units) == 1
                    and units[0]['unit'] == unit
                    and units[0]['state'] in ('ABSENT_OBSERVED', 'QUIET_OBSERVED')
                    and units[0]['cgroup_empty'] is True
                    and type(units[0]['main_pid']) is int
                    and units[0]['main_pid'] == 0,
                    UNVERIFIED,
                )
                verified_adoptions.add(identifier)
                continue
            if row['original_status'] in ('DISPATCHING', 'UNKNOWN') or state != 'OBSERVED':
                yield {**subject, 'reason_code': STEP}
            for unit in row['units']:
                if unit['state'] != 'PRESENT_OBSERVED':
                    continue
                if unit['unit'].startswith('walle-prep-'):
                    yield {**subject, 'reason_code': PREPARATION, 'unit': unit['unit']}
                elif not runtime_unit_matches(
                    row, unit, environments.get(row['environment_id'], {})
                ):
                    yield {**subject, 'reason_code': RUNTIME, 'unit': unit['unit']}
        else:
            require(False, UNVERIFIED)
    require(count == expected_count, UNVERIFIED)
    confirmed = set()
    for operation in operations:
        require(
            operation['status'] in ('WAITING_CAPACITY', 'ACCEPTED', 'RUNNING', 'UNKNOWN')
            or any(
                matching_original(disposition, operation['action'], operation['status'])
                for disposition in EFFECT_DISPOSITIONS
            ),
            UNVERIFIED,
        )
        identifier = operation['operation_id']
        if identifier in dispositions:
            confirms_original_operation(dispositions[identifier], operation)
            confirmed.add(identifier)
            continue
        yield {
            'reason_code': OPERATION,
            'kind': 'ORIGINAL_OPERATION',
            'state': operation['status'],
            'environment_id': operation['environment_id'],
            'operation_id': operation['operation_id'],
            'registry_generation': operation['registry_generation'],
            'action': operation['action'],
            'source_revision': operation['revision'],
            'source_intent_sha256': operation['intent_sha256'],
        }
    expected_effect_steps = {
        identifier
        for identifier, receipt in dispositions.items()
        if receipt['outcome']['disposition'] in EFFECT_DISPOSITIONS
    }
    require(
        confirmed == set(dispositions)
        and verified_effect_steps == expected_effect_steps
        and set(adopted_steps).issubset(confirmed),
        UNVERIFIED,
    )


def review_host_rows(rows, operations, expected_count, dispositions=None, *, adopted_steps=None):
    return dict(
        Counter(
            item['reason_code']
            for item in blocked_subjects(
                rows, operations, expected_count, dispositions, adopted_steps=adopted_steps
            )
        )
    )


def selected_source_coverage(native, current, args, subject):
    try:
        source, selected = source_installation(
            current, args.sha256, expected=subject['selection_receipt_sha256'], installer=True
        )
        with retained_snapshot_metadata(native, source, selected, args.sha256) as (_, receipt):
            covered = (
                snapshot_matches_selection_pause(receipt, selected)
                and selected['operation_id'] == subject['operation_id']
                and selected['dispatch_hold_sha256'] == subject['dispatch_hold_sha256']
                and receipt['catalog_sha256'] == subject['catalog_sha256']
            )
            return {
                'status': 'PAUSED_SOURCE_VERIFIED' if covered else SOURCE_COVERAGE,
                'snapshot_receipt_sha256': receipt['receipt_sha256'],
            }
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError):
        return {'status': SOURCE_COVERAGE, 'snapshot_receipt_sha256': None}


def review_dispositions(native, current, subject, coverage):
    snapshot = (
        coverage['snapshot_receipt_sha256']
        if coverage['status'] == 'PAUSED_SOURCE_VERIFIED'
        else None
    )
    return permitted_dispositions(native, current, subject, snapshot)


def review_receipt(native, current, args, entry, catalog, directory, subject, verify_source):
    observed_pin = args.registry_observation_receipt_sha256
    admission_pin = args.registry_entry_admission_receipt_sha256
    require(sha_value(observed_pin) and sha_value(admission_pin), UNVERIFIED)
    gateway = verify_admitted_gateway(current, args.sha256, admission_pin)
    path = current.directory_root / HOST_OBSERVATIONS / subject['observation_id']
    observed = read_observation(path, current, subject, expected=observed_pin)
    require_fresh(observed)
    coverage = selected_source_coverage(native, current, args, subject)
    dispositions = review_dispositions(native, current, subject, coverage)
    overlays = adopted_deployment_observations(
        native, current, args, entry, catalog, directory, subject, dispositions
    )
    with protected_observations(path, current) as stored:
        blockers = review_host_rows(
            adopted_host_rows(inventory_rows(stored, OBSERVATIONS), overlays),
            inventory_rows(directory, 'operations.jsonl'),
            observed['artifact']['records'],
            dispositions,
            adopted_steps=overlays[2],
        )
        if coverage['status'] == SOURCE_COVERAGE:
            blockers[SOURCE_COVERAGE] = 1
        if not blockers:
            now = host_observations(directory, native, catalog, args, entry)
            rows = inventory_rows(stored, OBSERVATIONS)
            if (
                any(recorded != actual for recorded, actual in zip_longest(rows, now))
                or adopted_deployment_observations(
                    native, current, args, entry, catalog, directory, subject, dispositions
                )
                != overlays
            ):
                blockers[HOST_CHANGED] = 1
    require(read_observation(path, current, subject, expected=observed_pin) == observed, UNVERIFIED)
    require_fresh(observed)
    verify_source()
    result = {
        'status': BLOCKED if blockers else READY,
        'registry_generation': current.registry_generation,
        'registry_anchor_sha256': current.sha256,
        'operation_id': subject['operation_id'],
        'selection_receipt_sha256': subject['selection_receipt_sha256'],
        'inventory_receipt_sha256': subject['inventory_receipt_sha256'],
        'observation_receipt_sha256': observed_pin,
        'entry_admission_receipt_sha256': admission_pin,
        'route_sha256': gateway['route_sha256'],
        'source_coverage': coverage,
        'verified_dispositions': disposition_manifest(dispositions),
        'blockers': blockers,
    }
    return {**result, 'review_sha256': digest(canonical(result))}


def check_registry_recovery_dispatch(native, installation, args, entry):
    with selected_observation_inputs(native, installation, args) as (
        current,
        catalog,
        directory,
        subject,
        verify_source,
    ):
        return review_receipt(
            native, current, args, entry, catalog, directory, subject, verify_source
        )


def inspect_registry_recovery_dispatch(native, installation, args, entry):
    reason = args.registry_dispatch_blocker
    offset = args.registry_dispatch_blocker_offset
    if offset is None:
        offset = 0
    require(reason in BLOCKER_CODES and type(offset) is int and offset >= 0, UNVERIFIED)
    with selected_observation_inputs(native, installation, args) as (
        current,
        catalog,
        directory,
        subject,
        verify_source,
    ):
        review = review_receipt(
            native, current, args, entry, catalog, directory, subject, verify_source
        )
        total = review['blockers'].get(reason, 0)
        require(offset <= total, UNVERIFIED)
        if reason == HOST_CHANGED:
            items = (
                [{'reason_code': reason, 'kind': 'HOST_OBSERVATION'}]
                if total and offset == 0
                else []
            )
        elif reason == SOURCE_COVERAGE:
            items = (
                [
                    {
                        'reason_code': reason,
                        'kind': 'ORIGINAL_SOURCE_SNAPSHOT',
                        **review['source_coverage'],
                    }
                ]
                if total and offset == 0
                else []
            )
        else:
            dispositions = review_dispositions(native, current, subject, review['source_coverage'])
            require(
                disposition_manifest(dispositions) == review['verified_dispositions'], UNVERIFIED
            )
            overlays = adopted_deployment_observations(
                native, current, args, entry, catalog, directory, subject, dispositions
            )
            items = inspect_blockers(
                current, directory, subject, review, reason, offset, dispositions, overlays=overlays
            )
        next_offset = offset + len(items)
        require(next_offset == min(total, offset + INSPECTION_PAGE_SIZE), UNVERIFIED)
        verify_source()
        return {
            'status': INSPECTED,
            'registry_generation': current.registry_generation,
            'observation_receipt_sha256': review['observation_receipt_sha256'],
            'review_sha256': review['review_sha256'],
            'reason_code': reason,
            'matched': total,
            'offset': offset,
            'next_offset': next_offset if next_offset < total else None,
            'items': items,
        }


def inspect_blockers(
    current, directory, subject, review, reason, offset, dispositions, *, overlays=None
):
    if overlays is None:
        overlays = ({}, {}, {})
    path = current.directory_root / HOST_OBSERVATIONS / subject['observation_id']
    observed = read_observation(
        path, current, subject, expected=review['observation_receipt_sha256']
    )
    require_fresh(observed)
    with protected_observations(path, current) as stored:
        blockers = blocked_subjects(
            adopted_host_rows(inventory_rows(stored, OBSERVATIONS), overlays),
            inventory_rows(directory, 'operations.jsonl'),
            observed['artifact']['records'],
            dispositions,
            adopted_steps=overlays[2],
        )
        matches = (item for item in blockers if item['reason_code'] == reason)
        items = list(islice(matches, offset, offset + INSPECTION_PAGE_SIZE))
    require(
        read_observation(path, current, subject, expected=review['observation_receipt_sha256'])
        == observed,
        UNVERIFIED,
    )
    require_fresh(observed)
    return items
