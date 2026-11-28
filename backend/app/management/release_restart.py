"""Verify the exact stopped release before an independent ordinary start supersedes its run."""

from backend.app.infrastructure.environment_control import initial_control, normal_stop
from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .operation_contract import CONFLICT, RESOURCE, installed_record, path_reference
from .release_execution import EXECUTIONS
from .release_open_admission import TARGET
from .release_runtime import DISPATCH, OPENED, RUNTIME_POLICY, confirmed_opening
from .release_selection import SELECTED
from .runtime_observation import controlled, load_policy
from .runtime_stop import stop_record


def verify_release_stop(catalog, fd, environment, plan, stop_id, stop):
    operation = stop.get('start_operation_id')
    require(uuid_value(operation), RESOURCE)
    execution = catalog.directory / EXECUTIONS / operation
    try:
        opened = installed_record(execution / OPENED)
    except FileNotFoundError:
        return False
    dispatch = installed_record(execution / DISPATCH)
    selected = installed_record(execution / SELECTED)
    exact(dispatch, ('format_version', 'request', 'unit'), RESOURCE)
    request = dispatch['request']
    scope = {key: getattr(environment, key) for key in TARGET}
    unit = f'walle-env-{environment.environment_id}-{operation}.service'
    require(
        dispatch['format_version'] == 1
        and dispatch['unit'] == unit
        and request['operation_id'] == selected['operation_id'] == operation
        and operation != plan['start_operation_id']
        and request['selection_receipt_sha256'] == digest(canonical(selected))
        and all(request[key] == selected[key] == value for key, value in scope.items())
        and opened
        == confirmed_opening(
            opened['opening'], opened['runtime'], opened['observation'], request, selected
        ),
        CONFLICT,
    )
    path, pin = path_reference(opened['runtime'])
    require(
        path == catalog.directory / 'observations' / ('start-runtime-' + operation) / RUNTIME_POLICY
        and sha_value(stop.get('stop_policy_sha256')),
        RESOURCE,
    )
    runtime = load_policy(path, pin, catalog)
    require(
        runtime['operation_id'] == operation
        and runtime['run_id'] == request['run_id']
        and runtime['boot_id'] == request['boot_id']
        and runtime['candidate_ref'] == plan['candidate_ref']
        and runtime['candidate_sha256'] == plan['candidate_sha256']
        and runtime.get('release_open_policy', {}).get('sha256') == request['open_policy_sha256'],
        CONFLICT,
    )
    expected = {
        'format_version': 1,
        **catalog.scope,
        'stop_operation_id': stop_id,
        'environment_id': environment.environment_id,
        'run_id': request['run_id'],
        'start_operation_id': operation,
        'stop_policy_sha256': stop['stop_policy_sha256'],
        'runtime_policy_sha256': pin,
    }
    observed = stop_record(fd, 'stop-' + stop_id + '.v1.json', expected)
    require(observed is not None and observed['state'] == 'STOPPED', CONFLICT)
    control, prepared_revision = controlled(environment, runtime)
    require(
        normal_stop(control)
        and control['outbound_hold'] is initial_control(environment, operation)['outbound_hold']
        and control['operation_id'] == operation
        and control['control_revision'] == prepared_revision + 3
        and prepared_revision == selected['control_revision']
        and control['open_receipt_ref'] == f'open-{request["run_id"]}.v1.json',
        CONFLICT,
    )
    return True
