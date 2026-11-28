"""Durable idempotent controls for an original ordinary-runtime operation."""

from backend.app.infrastructure.environment_files import MAX_REVISION, digest, exact, require
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import now
from .lifecycle_operations import (
    authorized,
    expected_versions,
    reconcile_original,
    startup_capacity,
)
from .operation_contract import (
    CONFLICT,
    DENIED,
    INVALID,
    MISSING,
    RELEASE_ACTIONS,
    RESOURCE,
    UNAVAILABLE,
    VERSION,
    installed_record,
    version,
)
from .operation_store import (
    KEY_CONFLICT,
    decoded,
    may_read_operation,
    mutation,
    operation_result,
    reject_historical_key,
    stored,
)
from .runtime_capacity import cancel_reservation, reserve_capacity
from .runtime_observation import project_runtime

COMMANDS = ('CONTINUE', 'CANCEL', 'RECONCILE')


def control_input(raw):
    changing = raw['action'] == 'CONTROL'
    fields = ('action', 'operation_id')
    if changing:
        fields += ('command', 'expected_revision')
    exact(raw, fields, INVALID)
    require(uuid_value(raw['operation_id']), INVALID)
    if changing:
        require(raw['command'] in COMMANDS and version(raw['expected_revision']), INVALID)


def original(connection, catalog, principal, operation_id):
    row = connection.execute(
        'SELECT * FROM management_operations WHERE operation_id=? AND registry_generation=?',
        (operation_id, catalog.scope['registry_generation']),
    ).fetchone()
    require(row is not None, MISSING)
    require(may_read_operation(connection, principal, row), DENIED)
    return row


def previous_control(connection, catalog, key):
    return connection.execute(
        'SELECT * FROM management_controls WHERE registry_generation=? AND control_key=?',
        (catalog.scope['registry_generation'], key),
    ).fetchone()


def controlled_result(connection, operation, receipt):
    return {**operation_result(connection, operation), 'control_receipt': receipt}


def lookup_control(connection, catalog, principal, key, raw):
    operation = original(connection, catalog, principal, raw['operation_id'])
    previous = previous_control(connection, catalog, key)
    require(previous is not None and previous['operation_id'] == operation['operation_id'], MISSING)
    require(previous['principal'] == principal.id or principal.role == 'MANAGER', DENIED)
    return controlled_result(connection, operation, decoded(previous['receipt_json']))


def update_original(connection, operation, status, *, cancel_requested=False):
    require(operation['revision'] < MAX_REVISION, VERSION)
    change = connection.execute(
        'UPDATE management_operations SET status=?, cancel_requested=?, revision=revision+1 '
        'WHERE operation_id=? AND revision=?',
        (status, int(cancel_requested), operation['operation_id'], operation['revision']),
    )
    require(change.rowcount == 1, VERSION)


def continue_start(connection, catalog, operation, row, intent, step):
    require(
        operation['status'] == 'WAITING_CAPACITY'
        and not operation['cancel_requested']
        and step['status'] == 'PLANNED'
        and step['external_identity_json'] is None,
        UNAVAILABLE,
    )
    projected = project_runtime(catalog, row, decoded(row['work_package_json']))
    policy, waiting = startup_capacity(connection, catalog, row, intent, projected)
    status = 'WAITING_CAPACITY' if waiting else 'ACCEPTED'
    update_original(connection, operation, status)
    connection.execute(
        'UPDATE management_steps SET result_json=? WHERE operation_id=? AND ordinal=1',
        (stored(waiting) if waiting else None, operation['operation_id']),
    )
    if waiting is None:
        reserve_capacity(connection, operation['operation_id'], policy, row, stored)
    return status


def has_host_record(catalog, operation):
    name = 'start-' + operation['operation_id'] + '.v1.json'
    try:
        installed_record(catalog.directory / 'observations' / name)
    except FileNotFoundError:
        return False
    return True


def cancel_start(connection, catalog, operation, step, key):
    status = operation['status']
    require(
        status in ('WAITING_CAPACITY', 'ACCEPTED', 'RUNNING', 'UNKNOWN', 'CANCELLED'), UNAVAILABLE
    )
    require(not operation['cancel_requested'], CONFLICT)
    if status in ('WAITING_CAPACITY', 'ACCEPTED'):
        require(step['status'] == 'PLANNED' and step['external_identity_json'] is None, RESOURCE)
        if not has_host_record(catalog, operation):
            cancel_reservation(connection, operation, key, stored)
            update_original(connection, operation, 'CANCELLED', cancel_requested=True)
            connection.execute(
                "UPDATE management_steps SET status='SKIPPED',result_json=NULL "
                'WHERE operation_id=? AND ordinal=1',
                (operation['operation_id'],),
            )
            return 'CANCELLED'
    update_original(connection, operation, status, cancel_requested=True)
    return 'CANCELLATION_REQUESTED'


def cancel_unstarted_maintenance(connection, principal, operation):
    require(principal.role == 'MANAGER', DENIED)
    environment = authorized(connection, principal, operation['environment_id'])
    expected_versions(environment, decoded(operation['intent_json']))
    require(operation['status'] == 'ACCEPTED' and not operation['cancel_requested'], UNAVAILABLE)
    retired = connection.execute(
        "UPDATE management_steps SET status='SKIPPED' WHERE operation_id=? AND ordinal=1 "
        "AND status='PLANNED' AND executor_ref IS NULL AND external_identity_json IS NULL "
        'AND result_json IS NULL',
        (operation['operation_id'],),
    )
    require(retired.rowcount == 1, RESOURCE)
    update_original(connection, operation, 'CANCELLED', cancel_requested=True)
    return 'CANCELLED'


def apply_control(connection, catalog, principal, operation, command, key):
    if command == 'CANCEL' and operation['action'] in (
        *RELEASE_ACTIONS,
        'BACKUP',
        'RESTORE',
        'ARCHIVE',
    ):
        return cancel_unstarted_maintenance(connection, principal, operation)
    if operation['action'] == 'BACKUP':
        from .backup_reconciliation import reconcile_backup

        require(command == 'RECONCILE', UNAVAILABLE)
        reconcile_backup(connection, catalog, principal, operation)
        return 'RECONCILED'
    if operation['action'] in RELEASE_ACTIONS:
        from .release_reconciliation import reconcile_release

        require(command == 'RECONCILE', UNAVAILABLE)
        reconcile_release(connection, catalog, principal, operation)
        return 'RECONCILED'
    if operation['action'] == 'RESTORE':
        from .restore_reconciliation import reconcile_restore

        require(command == 'RECONCILE', UNAVAILABLE)
        reconcile_restore(connection, catalog, principal, operation)
        return 'RECONCILED'
    row = authorized(connection, principal, operation['environment_id'])
    intent = decoded(operation['intent_json'])
    expected_versions(row, intent)
    if command == 'RECONCILE':
        require(operation['action'] in ('START', 'STOP'), UNAVAILABLE)
        if operation['status'] not in ('FAILED', 'CANCELLED', 'SUCCEEDED'):
            reconcile_original(connection, catalog, principal, operation)
        return 'RECONCILED'
    require(operation['action'] == 'START', UNAVAILABLE)
    step = connection.execute(
        'SELECT status,external_identity_json FROM management_steps WHERE operation_id=? '
        "AND ordinal=1 AND step_kind='RUNTIME_STARTED'",
        (operation['operation_id'],),
    ).fetchone()
    require(step is not None, RESOURCE)
    if command == 'CONTINUE':
        return continue_start(connection, catalog, operation, row, intent, step)
    return cancel_start(connection, catalog, operation, step, key)


def control_operation(connection, lock, catalog, principal, key, raw):
    with mutation(connection, lock):
        operation = original(connection, catalog, principal, raw['operation_id'])
        previous = previous_control(connection, catalog, key)
        command = raw['command']
        checksum = digest(stored(raw).encode('utf-8'))
        if previous is not None:
            require(previous['principal'] == principal.id, DENIED)
            require(
                previous['operation_id'] == operation['operation_id']
                and previous['intent_sha256'] == checksum,
                KEY_CONFLICT,
            )
            return controlled_result(connection, operation, decoded(previous['receipt_json'])), True
        require(principal.role in ('DEVELOPER', 'MANAGER'), DENIED)
        reject_historical_key(connection, catalog.scope['registry_generation'], key, control=True)
        require(operation['revision'] == raw['expected_revision'], VERSION)
        result = apply_control(connection, catalog, principal, operation, command, key)
        operation = original(connection, catalog, principal, raw['operation_id'])
        receipt = {
            'control_key': key,
            'operation_id': operation['operation_id'],
            'command': command,
            'revision': 1,
            'operation_revision': operation['revision'],
            'result': result,
            'recorded_at': now(),
        }
        connection.execute(
            'INSERT INTO management_controls VALUES (?,?,?,?,?,?,?)',
            (
                catalog.scope['registry_generation'],
                key,
                operation['operation_id'],
                principal.id,
                command,
                checksum,
                stored(receipt),
            ),
        )
        return controlled_result(connection, operation, receipt), False


def authorize_cancel(connection, catalog, request):
    exact(
        request,
        (
            'start_operation_id',
            'control_key',
            'environment_id',
            'start_policy_sha256',
            'run_id',
            'boot_id',
        ),
        INVALID,
    )
    require(
        all(
            uuid_value(request[key])
            for key in ('start_operation_id', 'control_key', 'environment_id', 'boot_id')
        )
        and sha_value(request['start_policy_sha256'])
        and (request['run_id'] is None or uuid_value(request['run_id'])),
        INVALID,
    )
    control = previous_control(connection, catalog, request['control_key'])
    require(
        control is not None
        and control['operation_id'] == request['start_operation_id']
        and control['command'] == 'CANCEL'
        and decoded(control['receipt_json'])['result'] == 'CANCELLATION_REQUESTED',
        RESOURCE,
    )
    principal = catalog.access(control['principal'])
    operation = original(connection, catalog, principal, request['start_operation_id'])
    require(
        operation['action'] == 'START'
        and operation['environment_id'] == request['environment_id']
        and operation['cancel_requested']
        and operation['status'] in ('RUNNING', 'UNKNOWN', 'CANCELLED'),
        RESOURCE,
    )
    row = authorized(connection, principal, operation['environment_id'])
    expected_versions(row, decoded(operation['intent_json']))
    step = connection.execute(
        'SELECT external_identity_json FROM management_steps WHERE operation_id=? AND ordinal=1',
        (operation['operation_id'],),
    ).fetchone()
    require(step is not None and step[0] is not None, RESOURCE)
    external = decoded(step[0])
    grant = external.get('dispatch')
    require(
        grant is not None
        and grant['start_policy_sha256'] == request['start_policy_sha256']
        and grant['boot_id'] == request['boot_id']
        and external.get('run_id', request['run_id']) == request['run_id'],
        RESOURCE,
    )
    return {'admission': request, 'dispatch_allowed': operation['status'] != 'CANCELLED'}
