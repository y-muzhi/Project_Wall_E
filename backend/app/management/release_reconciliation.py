"""Adopt one durably opened fixed deployment into its original management transaction."""

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    canonical,
    require,
)

from .operation_contract import (
    DENIED,
    RECONFIGURE,
    RESOURCE,
    ROLLBACK_CODE,
    UNAVAILABLE,
    VERSION,
    installed_record,
    path_reference,
)
from .operation_store import decoded, stored
from .release_configuration import CHANGED
from .release_execution import EXECUTIONS, operation_record
from .release_open_admission import TARGET, check_selected_record
from .release_operations import row_for_release
from .release_runtime import DISPATCH, OPENED, RUNTIME_POLICY, confirmed_opening
from .runtime_capacity import verify_reserved_binding
from .runtime_observation import load_policy


def opened_evidence(catalog, grant, request):
    root = catalog.directory / EXECUTIONS / request['operation_id']
    try:
        receipt = installed_record(root / OPENED)
    except FileNotFoundError:
        return None
    selected = check_selected_record(catalog, grant, request)
    return verify_opened_evidence(
        catalog, root, request, selected, grant['target_attachment'], receipt
    )


def verify_opened_evidence(catalog, root, request, selected, attachment, receipt):
    dispatch = installed_record(root / DISPATCH)
    unit = f'walle-env-{request["environment_id"]}-{request["operation_id"]}.service'
    require(
        canonical(dispatch) == canonical({'format_version': 1, 'request': request, 'unit': unit})
        and receipt
        == confirmed_opening(
            receipt['opening'], receipt['runtime'], receipt['observation'], request, selected
        ),
        RESOURCE,
    )
    path, pin = path_reference(receipt['runtime'])
    require(
        path
        == catalog.directory
        / 'observations'
        / ('start-runtime-' + request['operation_id'])
        / RUNTIME_POLICY,
        RESOURCE,
    )
    runtime = load_policy(path, pin, catalog)
    require(
        all(runtime[key] == request[key] for key in ('operation_id', 'run_id', 'boot_id'))
        and runtime['candidate_ref'] == attachment['candidate_ref']
        and runtime['candidate_sha256'] == attachment['sha256']
        and runtime.get('release_open_policy', {}).get('sha256') == request['open_policy_sha256']
        and runtime['memory_bytes'] == request['limits']['memory_bytes']
        and runtime['tasks'] == request['limits']['tasks']
        and runtime['cpu_quota_usec'] == request['limits']['cpu_percent'] * 1000
        and runtime['cpu_period_usec'] == 100_000,
        RESOURCE,
    )
    return receipt


def projected_opened_registration(
    connection, operation, row, grant, request, receipt, *, recovery=None, business_entry=None
):
    target = grant['target']
    source = grant['source']
    work = decoded(row['work_package_json'])
    require(
        work['deployment_id'] == source['deployment_id']
        and work['data_generation'] == source['data_generation']
        and (source['data_generation'] != target['data_generation']) == (recovery is not None)
        and row['configuration_sha256'] == source['configuration_sha256']
        and decoded(row['configuration_ref']) == grant['source_attachment']
        and row['program_source'] == source['program_sha256'],
        CHANGED,
    )
    verify_reserved_binding(
        connection,
        operation['operation_id'],
        row['environment_id'],
        request['limits'],
        stored(
            {
                'policy_sha256': request['capacity_sha256'],
                'profile_ref': row['profile_ref'],
                'configuration_sha256': target['configuration_sha256'],
            }
        ),
    )
    require(row['record_version'] < MAX_REVISION and operation['revision'] < MAX_REVISION, VERSION)
    next_version = row['record_version'] + 1
    opened = receipt['opening']
    outcome = {
        **{key: opened[key] for key in (*TARGET, 'run_id', 'opened_at', 'control_revision')},
        'release_ref': grant['release_ref'],
        'release_manifest_sha256': grant['release_manifest_sha256'],
        'proof_id': receipt['observation']['proof_id'],
        'record_version': next_version,
        'assignment_generation': row['assignment_generation'],
        **(recovery or {}),
    }
    work = {
        **work,
        'data_generation': target['data_generation'],
        'deployment_id': target['deployment_id'],
    }
    if business_entry is not None:
        work['restored_business_entry'] = {
            'origin': business_entry,
            **{key: target[key] for key in TARGET[1:]},
        }
    return work, outcome


def opened_registration_row(row, grant, work, outcome):
    target = grant['target']
    return {
        **dict(row),
        'record_version': outcome['record_version'],
        'configuration_ref': stored(grant['target_attachment']),
        'configuration_sha256': target['configuration_sha256'],
        'program_source': target['program_sha256'],
        'work_package_json': stored(work),
    }


def update_opened_registration(connection, previous, target):
    updated = connection.execute(
        'UPDATE managed_environments SET record_version=?, configuration_ref=?, configuration_sha256=?, '
        'program_source=?, work_package_json=? WHERE environment_id=? AND record_version=? AND assignment_generation=?',
        (
            *(
                target[key]
                for key in (
                    'record_version',
                    'configuration_ref',
                    'configuration_sha256',
                    'program_source',
                    'work_package_json',
                )
            ),
            previous['environment_id'],
            previous['record_version'],
            previous['assignment_generation'],
        ),
    )
    require(updated.rowcount == 1, VERSION)


def adopt_opened_deployment(
    connection, operation, row, grant, request, receipt, *, recovery=None, business_entry=None
):
    work, outcome = projected_opened_registration(
        connection,
        operation,
        row,
        grant,
        request,
        receipt,
        recovery=recovery,
        business_entry=business_entry,
    )
    update_opened_registration(connection, row, opened_registration_row(row, grant, work, outcome))
    completed = connection.execute(
        "UPDATE management_operations SET status='SUCCEEDED',revision=revision+1 "
        "WHERE operation_id=? AND status='RUNNING' AND revision=?",
        (operation['operation_id'], operation['revision']),
    )
    recorded = connection.execute(
        "UPDATE management_steps SET status='SUCCEEDED',result_json=? "
        "WHERE operation_id=? AND ordinal=1 AND status='DISPATCHING'",
        (stored(outcome), operation['operation_id']),
    )
    require(completed.rowcount == recorded.rowcount == 1, VERSION)


def retained_business_origin(catalog, row, action):
    if action not in (ROLLBACK_CODE, RECONFIGURE):
        return None
    from .management_query import business_entry

    return business_entry(catalog, row, decoded(row['work_package_json']))


def reconcile_release(connection, catalog, principal, operation):
    require(principal.role == 'MANAGER', DENIED)
    if operation['status'] in ('SUCCEEDED', 'CANCELLED'):
        return
    row = row_for_release(connection, principal, decoded(operation['intent_json']))
    require(
        operation['status'] in ('ACCEPTED', 'RUNNING') and not operation['cancel_requested'],
        UNAVAILABLE,
    )
    if operation['status'] == 'ACCEPTED':
        return
    _, step = operation_record(connection, catalog, operation['operation_id'])
    require(
        step['status'] == 'DISPATCHING' and step['external_identity_json'] is not None, RESOURCE
    )
    external = decoded(step['external_identity_json'])
    grant = external['maintenance']
    require(grant['environment_id'] == row['environment_id'], CHANGED)
    request = external.get('opening')
    if request is None:
        from .release_retirement import original_retirement
        from .restore_retirement import record_retirement

        retired = original_retirement(catalog, grant)
        if retired is not None:
            record_retirement(connection, operation, external, retired)
        return
    receipt = opened_evidence(catalog, grant, request)
    if receipt is not None:
        adopt_opened_deployment(
            connection,
            operation,
            row,
            grant,
            request,
            receipt,
            business_entry=retained_business_origin(catalog, row, operation['action']),
        )
