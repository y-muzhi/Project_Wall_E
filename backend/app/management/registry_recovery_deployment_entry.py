"""Verify that the selected management entry resolves one exactly stopped deployment."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    require,
)

from .attachment_observation import candidate_environment, public_facts
from .operation_contract import CATALOG_NAME, load_catalog
from .registry_recovery_deployment_stop import require_deployment_state, stop_subject
from .registry_recovery_entry_admission import verify_admitted_gateway
from .registry_recovery_installation import ENTRY_INPUTS
from .registry_recovery_reobserve import selected_observation_inputs
from .registry_recovery_stop import observed_stop_receipt
from .runtime_capacity import load_capacity

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_ENTRY_UNVERIFIED'
VERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_ENTRY_VERIFIED'


def admitted_deployment(installation, original, row, attachment, target, args, entry):
    receipt = verify_admitted_gateway(
        installation, args.sha256, args.registry_entry_admission_receipt_sha256
    )
    inputs = installation.directory_root / ENTRY_INPUTS / receipt['entry_id']
    catalog = load_catalog(inputs / CATALOG_NAME, receipt['catalog_sha256'], installation)
    require(
        row['host_id'] == catalog.scope['host_id']
        and row['registration_state'] == 'ACTIVE'
        and row['preparation_state'] == 'PREPARED'
        and row['assignment_control_state'] == 'OPEN'
        and any(member.role == 'MANAGER' for member in catalog.principals.values()),
        UNVERIFIED,
    )
    reference, pin = attachment['candidate_ref'], attachment['sha256']
    candidate = catalog.candidate(reference, pin)
    environment = candidate_environment(candidate, args.sha256)
    expected = {
        **{key: target[key] for key in public_facts(environment) if key != 'purpose'},
        'purpose': row['purpose'],
    }
    require(
        candidate == original.candidate(reference, pin)
        and candidate['profile_ref'] == row['profile_ref']
        and public_facts(environment) == expected
        and entry['verify_program'](environment.project) == expected['program_sha256'],
        UNVERIFIED,
    )
    business = catalog.business_entries.get(row['environment_id'])
    prior = original.business_entries.get(row['environment_id'])
    require(
        business is not None
        and prior is not None
        and prior['origin'] == business['origin']
        and all(
            business[key] == target[key]
            for key in ('data_generation', 'deployment_id', 'configuration_sha256')
        ),
        UNVERIFIED,
    )
    capacity = load_capacity(catalog)
    require(capacity.sha256 == catalog.capacity_policy_sha256, UNVERIFIED)
    return {
        'entry_id': receipt['entry_id'],
        'catalog_sha256': receipt['catalog_sha256'],
        'candidate_sha256': pin,
        'business_entry_sha256': digest(canonical(business)),
        'capacity_policy_sha256': capacity.sha256,
        'capacity_limits': capacity.profile(row),
    }


def stopped_deployment_readout(native, catalog, row, step, receipt, plan, args, entry):
    opened_pin = digest(canonical(receipt))
    observed = require_deployment_state(
        native, catalog, row, step, opened_pin, args, entry, ('OPENED_STOPPED',)
    )
    stopped = observed_stop_receipt(
        catalog,
        plan['stop_operation_id'],
        row['environment_id'],
        plan['run_id'],
        {
            'start_operation_id': step['operation_id'],
            'run_id': plan['run_id'],
            'policy_sha256': args.stop_policy_sha256,
        },
    )
    require(stopped['runtime_policy_sha256'] == receipt['runtime']['sha256'], UNVERIFIED)
    return {
        'environment_id': row['environment_id'],
        'target': observed['target'],
        'closed_control_sha256': observed['closed_control_sha256'],
        'database_identity': observed['database_identity'],
        'opened_receipt_sha256': opened_pin,
        'stop_operation_id': plan['stop_operation_id'],
        'stop_receipt_sha256': digest(canonical(stopped)),
    }


def verified_deployment_entry(native, args, entry, inputs):
    current, catalog, directory, subject, verify_source = inputs
    row, step, receipt, attachment, plan = stop_subject(directory, catalog, args)
    verify_source()
    stopped = stopped_deployment_readout(native, catalog, row, step, receipt, plan, args, entry)
    adoption = admitted_deployment(
        current, catalog, row, attachment, stopped['target'], args, entry
    )
    require(
        stopped_deployment_readout(native, catalog, row, step, receipt, plan, args, entry)
        == stopped
        and admitted_deployment(current, catalog, row, attachment, stopped['target'], args, entry)
        == adoption,
        UNVERIFIED,
    )
    verify_source()
    result = {
        'status': VERIFIED,
        'recovery_operation_id': subject['operation_id'],
        'source_registry_generation': subject['source_registry_generation'],
        'registry_generation': subject['target_registry_generation'],
        'selection_receipt_sha256': subject['selection_receipt_sha256'],
        'inventory_receipt_sha256': args.registry_inventory_receipt_sha256,
        'entry_admission_receipt_sha256': args.registry_entry_admission_receipt_sha256,
        'deployment_operation_id': step['operation_id'],
        **stopped,
        'management_entry': adoption,
    }
    return {**result, 'verification_sha256': digest(canonical(result))}


def verify_recovered_deployment_entry(native, installation, args, entry):
    try:
        with selected_observation_inputs(native, installation, args) as inputs:
            return verified_deployment_entry(native, args, entry, inputs)
    except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
