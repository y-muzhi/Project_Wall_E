"""Stop the exact originally opened managed deployment while registry dispatch remains paused."""

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    require,
)

from .operation_contract import path_reference
from .registry_recovery_effects import (
    DEPLOYMENT_STEPS,
    checked_deployment_opening,
    deployment_step_binding,
)
from .registry_recovery_observation import inventory_rows, pending_deployment_observation
from .registry_recovery_reobserve import selected_observation_inputs
from .runtime_observation import load_policy
from .runtime_stop import stop_policy, stop_runtime

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_STOP_UNVERIFIED'
STOPPED = 'MANAGEMENT_REGISTRY_RECOVERY_DEPLOYMENT_STOPPED'


def stop_subject(directory, catalog, args):
    plan, path, pin = stop_policy(catalog, args.stop_policy, args.stop_policy_sha256)
    runtime = load_policy(path, pin, catalog)
    steps = [
        item
        for item in inventory_rows(directory, 'steps.jsonl')
        if item['operation_id'] == runtime['operation_id']
    ]
    require(len(steps) == 1, UNVERIFIED)
    step = steps[0]
    require(
        step['step_kind'] in DEPLOYMENT_STEPS
        and step['status'] == 'DISPATCHING'
        and step['original_operation_status'] == 'RUNNING'
        and step['cancel_requested'] == 0
        and step['result_json'] is None
        and step['environment_id'] == plan['environment_id']
        and plan['stop_operation_id'] != step['operation_id'],
        UNVERIFIED,
    )
    rows = [
        item
        for item in inventory_rows(directory, 'environments.jsonl')
        if item['environment_id'] == plan['environment_id']
    ]
    require(len(rows) == 1, UNVERIFIED)
    original = deployment_step_binding(step, catalog)
    require(original is not None, UNVERIFIED)
    binding, grant, request = original
    verified = checked_deployment_opening(catalog, step, grant, request)
    require(verified is not None, UNVERIFIED)
    receipt, attachment, expected_policy = verified
    require(
        path_reference(receipt['runtime']) == (path, pin)
        and runtime == expected_policy
        and plan['run_id'] == binding['run_id'] == runtime['run_id']
        and runtime['systemctl_sha256'] == args.registry_systemctl_sha256,
        UNVERIFIED,
    )
    return rows[0], step, receipt, attachment, plan


def require_deployment_state(native, catalog, row, step, opened_pin, args, entry, states):
    result = pending_deployment_observation(native, catalog, row, step, args.sha256, entry)
    require(
        result['state'] in states and result['opened_receipt_sha256'] == opened_pin,
        UNVERIFIED,
    )
    return result


def stop_recovered_deployment(native, installation, args, entry):
    try:
        with selected_observation_inputs(native, installation, args) as (
            _,
            catalog,
            directory,
            subject,
            verify_source,
        ):
            row, step, receipt, _, _ = stop_subject(directory, catalog, args)
            opened_pin = digest(canonical(receipt))

            def verified_state(*states):
                verify_source()
                result = require_deployment_state(
                    native, catalog, row, step, opened_pin, args, entry, states
                )
                verify_source()
                return result

            def admit_new_stop():
                verified_state('OPENED_RUNNING', 'OPENED_STOPPED')

            verify_source()
            stopped = stop_runtime(catalog, args, entry, admit_new_stop=admit_new_stop)
            try:
                result = verified_state('OPENED_STOPPED')
            except (EnvironmentFailure, OSError, KeyError, TypeError, ValueError) as error:
                raise EnvironmentFailure(UNVERIFIED, uncertain=True) from error
            return {
                'status': STOPPED,
                'recovery_operation_id': subject['operation_id'],
                'selection_receipt_sha256': subject['selection_receipt_sha256'],
                'source_registry_generation': subject['source_registry_generation'],
                'registry_generation': subject['target_registry_generation'],
                'deployment_operation_id': step['operation_id'],
                'environment_id': row['environment_id'],
                'run_id': result['target']['run_id'],
                'opened_receipt_sha256': opened_pin,
                'stop_operation_id': stopped['stop_operation_id'],
                'dispatch': stopped['dispatch'],
                'stop_receipt_sha256': digest(canonical(stopped)),
            }
    except EnvironmentFailure:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(UNVERIFIED) from error
