"""Reserve installed runtime capacity for the selected deployment of one original release."""

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import machine_clock
from .operation_contract import DENIED, INVALID, RESOURCE, UNAVAILABLE, VERSION, installed_record
from .operation_store import decoded, mutation, stored
from .release_configuration import CHANGED
from .release_execution import EXECUTIONS, operation_record
from .release_operations import row_for_release
from .release_selection import RESULT_FIELDS, SELECTED
from .runtime_capacity import check_capacity, load_capacity, reserve_capacity, verify_reservation

TARGET = ('environment_id', 'data_generation', 'deployment_id', 'configuration_sha256')
PINS = ('open_policy_sha256', 'selection_receipt_sha256', 'launch_policy_sha256', 'capacity_sha256')
OPEN_AUTHORIZED = 'RELEASE_OPEN_AUTHORIZED'
OPEN_BLOCKED = 'RELEASE_OPEN_CAPACITY_BLOCKED'


def check_open_request(request):
    exact(request, ('operation_id', 'run_id', 'boot_id', 'limits', *TARGET, *PINS), INVALID)
    require(
        all(uuid_value(request[key]) for key in ('operation_id', 'run_id', 'boot_id', *TARGET[:3]))
        and request['run_id'] != request['operation_id']
        and all(sha_value(request[key]) for key in ('configuration_sha256', *PINS))
        and request['boot_id'] == machine_clock()[0],
        INVALID,
    )


def check_selected_record(catalog, grant, request):
    path = catalog.directory / EXECUTIONS / request['operation_id'] / SELECTED
    try:
        selected = installed_record(path, request['selection_receipt_sha256'], code=RESOURCE)
    except FileNotFoundError as error:
        raise EnvironmentFailure(RESOURCE) from error
    exact(
        selected,
        (
            *RESULT_FIELDS,
            'format_version',
            'plan_sha256',
            'grant_sha256',
            'maintenance_receipt_sha256',
            'switch_policy_sha256',
            'release_preflight_sha256',
        ),
        RESOURCE,
    )
    require(
        type(selected['format_version']) is int
        and selected['format_version'] == 1
        and selected['status'] == 'MANAGED_RELEASE_SELECTION_RECORDED'
        and selected['operation_id'] == grant['operation_id'] == request['operation_id']
        and selected['plan_sha256'] == grant['plan_sha256']
        and selected['grant_sha256'] == digest(canonical(grant))
        and selected['control_revision'] == grant['source']['control_revision'] + 2
        and selected['environment_id'] == grant['environment_id'] == request['environment_id']
        and all(selected[key] == grant['target'][key] == request[key] for key in TARGET[1:])
        and all(
            sha_value(selected[key])
            for key in (
                'control_sha256',
                'transition_sha256',
                'maintenance_receipt_sha256',
                'switch_policy_sha256',
                'release_preflight_sha256',
            )
        ),
        CHANGED,
    )
    return selected


def admit_release_open(connection, lock, catalog, request):
    check_open_request(request)
    with mutation(connection, lock):
        operation, step = operation_record(connection, catalog, request['operation_id'])
        principal = catalog.access(operation['principal'])
        require(principal.role == 'MANAGER', DENIED)
        require(
            operation['status'] == 'RUNNING'
            and step['status'] == 'DISPATCHING'
            and step['external_identity_json'] is not None
            and not operation['cancel_requested'],
            UNAVAILABLE,
        )
        state = decoded(step['external_identity_json'])
        grant = state['maintenance']
        check_selected_record(catalog, grant, request)
        source = row_for_release(connection, principal, decoded(operation['intent_json']))
        require(
            source['configuration_sha256'] == grant['source']['configuration_sha256']
            and decoded(source['configuration_ref']) == grant['source_attachment']
            and all(grant[key] == value for key, value in catalog.scope.items()),
            CHANGED,
        )
        return reserve_selected_opening(
            connection, catalog, operation, state, source, grant['target'], request
        )


def reserve_selected_opening(connection, catalog, operation, state, source, selected, request):
    target = {**dict(source), 'configuration_sha256': selected['configuration_sha256']}
    capacity = load_capacity(catalog)
    require(
        request['capacity_sha256'] == capacity.sha256
        and canonical(request['limits']) == canonical(capacity.profile(target)),
        CHANGED,
    )
    authorized = {'status': OPEN_AUTHORIZED, 'request': request}
    previous = state.get('opening')
    if previous is not None:
        require(canonical(previous) == canonical(request), CHANGED)
        verify_reservation(connection, operation['operation_id'], capacity, target, stored)
        return authorized
    missing = check_capacity(connection, capacity, target)
    if missing is not None:
        return {'status': OPEN_BLOCKED, 'missing': missing['missing']}
    require(operation['revision'] < MAX_REVISION, VERSION)
    reserve_capacity(connection, operation['operation_id'], capacity, target, stored)
    reserved = connection.execute(
        'UPDATE management_steps SET external_identity_json=? '
        "WHERE operation_id=? AND ordinal=1 AND status='DISPATCHING'",
        (stored({**state, 'opening': request}), operation['operation_id']),
    )
    advanced = connection.execute(
        'UPDATE management_operations SET revision=revision+1 WHERE operation_id=? '
        "AND status='RUNNING' AND revision=?",
        (operation['operation_id'], operation['revision']),
    )
    require(reserved.rowcount == advanced.rowcount == 1, VERSION)
    return authorized
