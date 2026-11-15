"""Read original C39 facts and preserve initial preparation and live progress."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .command_registry import registered_command
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .task_configuration_apply import BODY, PATH, STEPS, TYPE, configuration_receipt


def staged_configuration(connection, task_id):
    rows = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type='APPLY_CONFIGURATION' AND session_id IS NULL
           ORDER BY id LIMIT 2""",
        (task_id,),
    ).fetchall()
    if len(rows) > 1:
        raise StorageUnavailable('Multiple original unstarted configuration applications')
    if not rows:
        return None
    return rows[0]


def _fixed(operation):
    value = exact(strict_json_object(operation['fixed_input']), ('task_id', *BODY))
    for field in ('task_id', *BODY[:-1]):
        strict_integer(value[field], field)
    if (
        canonical_input(value) != operation['fixed_input']
        or value['task_id'] != operation['task_id']
        or value['expected_state_version'] != operation['expected_state_version']
        or type(value['reason']) is not str
        or not value['reason'].strip()
    ):
        raise StorageUnavailable('Original configuration input differs')
    return value


def configuration_records(connection, operation):
    fixed = _fixed(operation)
    task_id = fixed['task_id']
    command = registered_command('POST', PATH.format(task_id=task_id), operation['idempotency_key'])
    receipt = connection.execute(
        """SELECT business_input_json,success_result_json,http_status,status FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    if (
        receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['business_input_json'] != operation['fixed_input']
    ):
        raise StorageUnavailable('Original configuration acceptance is missing')
    result = strict_json_object(receipt['success_result_json'])
    Success(result, receipt['http_status']).encoded()
    data = configuration_receipt(command, result['data'], receipt['http_status'])
    if (
        result['code'] != 'OPERATION_ACCEPTED'
        or data['operation_id'] != operation['id']
        or data['state_version'] != operation['expected_state_version'] + 1
    ):
        raise StorageUnavailable('Original configuration acceptance differs')
    application = connection.execute(
        """SELECT a.*,g.profile_version_id AS grant_profile_version_id,g.status AS grant_status
           FROM code_configuration_applications a JOIN code_authorizations g
             ON g.id=a.authorization_id AND g.task_id=a.task_id
           WHERE a.operation_id=? AND a.task_id=?""",
        (operation['id'], task_id),
    ).fetchall()
    if len(application) != 1:
        raise StorageUnavailable('Original configuration application is missing')
    (application,) = application
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if (
        application['authorization_id'] != fixed['authorization_id']
        or application['new_profile_version_id'] != fixed['execution_profile_version_id']
        or application['grant_profile_version_id'] != application['new_profile_version_id']
        or application['created_at'] != operation['created_at']
        or [(step['step_no'], step['step_type']) for step in steps] != list(enumerate(STEPS, 1))
        or any(step['fixed_input'] != operation['fixed_input'] for step in steps)
    ):
        raise StorageUnavailable('Original configuration application differs')
    return fixed, application, steps


def project_configuration_operation(value, identity):
    if value.get('session_id') is not None:
        from .task_configuration_live_records import project_live_configuration_operation

        return project_live_configuration_operation(value, identity)
    row = exact(value, OPERATION_FIELDS)
    task_id = strict_integer(row['task_id'], 'task_id')
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    strict_integer(row['control_generation'], 'control_generation')
    fixed = exact(row['fixed_input'], ('task_id', *BODY))
    for field in ('task_id', *BODY[:-1]):
        strict_integer(fixed[field], field)
    if (
        row['id'] != identity
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != task_id
        or row['operation_type'] != TYPE
        or fixed['task_id'] != task_id
        or fixed['expected_state_version'] != version
        or type(fixed['reason']) is not str
        or not fixed['reason'].strip()
        or row['status'] not in ('RUNNING', 'UNKNOWN', 'SUCCEEDED', 'CANCELLED')
        or any(
            row[field] is not None for field in ('session_id', 'testing_task_id', 'content_capture')
        )
        or row['failure_code']
        != {
            'RUNNING': None,
            'UNKNOWN': 'EXTERNAL_RESULT_UNKNOWN',
            'SUCCEEDED': None,
            'CANCELLED': 'TASK_ENDED',
        }[row['status']]
    ):
        raise ValueError('Original configuration operation differs')
    registered_command('POST', PATH.format(task_id=task_id), row['idempotency_key'])
    at = row['created_at']
    _time(at, nullable=False)
    if row['started_at'] != at:
        raise ValueError('Original configuration operation chronology differs')
    ended = row['ended_at']
    _time(ended)
    status = row['status']
    if (ended is None) != (status in ('RUNNING', 'UNKNOWN')) or (ended is not None and ended < at):
        raise ValueError('Original configuration operation completion differs')
    steps = row['steps']
    if type(steps) is not list or len(steps) != len(STEPS):
        raise ValueError('Original configuration operation step count differs')
    application_id = strict_integer(
        exact(steps[2]['result_ref'], ('configuration_application_id',))[
            'configuration_application_id'
        ],
        'configuration_application_id',
    )
    results = (
        {'state_version': version + 1},
        {'scope': 'NO_INSTANCE'},
        {'configuration_application_id': application_id},
    )
    for number, (entry, kind) in enumerate(zip(steps, STEPS, strict=True), 1):
        step = exact(entry, STEP_FIELDS)
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != kind
            or step['external_identity'] is not None
            or step['fixed_input'] != fixed
        ):
            raise ValueError('Original configuration operation step identity differs')
        if number < 4:
            if (
                step['status'] != 'SUCCEEDED'
                or step['result_ref'] != results[number - 1]
                or any(
                    step[field] != at for field in ('started_at', 'ended_at', 'last_observed_at')
                )
            ):
                raise ValueError('Original prepared configuration step differs')
            continue
        expected = 'PENDING' if status == 'RUNNING' else status
        observed = step['last_observed_at']
        started = step['started_at']
        _time(observed)
        _time(started)
        if (
            step['status'] != expected
            or step['ended_at'] != ended
            or (started is None) != (expected == 'PENDING')
            or (observed is None) != (expected == 'PENDING')
            or (started is not None and not at <= started <= observed)
            or (ended is not None and observed != ended)
        ):
            raise ValueError('Original effective configuration chronology differs')
        if status == 'SUCCEEDED':
            result = exact(
                step['result_ref'], ('configuration_application_id', 'start_operation_id')
            )
            if result['configuration_application_id'] != application_id:
                raise ValueError('Original effective configuration reference differs')
            strict_integer(result['start_operation_id'], 'start_operation_id')
        elif step['result_ref'] is not None:
            raise ValueError('Original configuration has premature effect evidence')
    return row


def public_configuration_operation(connection, operation):
    if operation['session_id'] is not None:
        from .task_configuration_live_records import public_live_configuration_operation

        return public_live_configuration_operation(connection, operation)
    fixed, application, steps = configuration_records(connection, operation)
    status = operation['status']
    if (
        application['status']
        != {
            'RUNNING': 'PENDING',
            'UNKNOWN': 'UNKNOWN',
            'SUCCEEDED': 'APPLIED',
            'CANCELLED': 'FAILED',
        }.get(status)
        or (
            status in ('RUNNING', 'UNKNOWN')
            and application['grant_status'] != 'BOUND_PENDING_APPLY'
        )
        or (application['applied_at'] is not None) != (status == 'SUCCEEDED')
        or (application['effective_evidence'] is not None) != (status == 'SUCCEEDED')
        or strict_json_object(steps[2]['result_ref'])
        != {'configuration_application_id': application['id']}
    ):
        raise StorageUnavailable('Original configuration application lifecycle differs')
    if status == 'SUCCEEDED':
        evidence = strict_json_object(application['effective_evidence'])
        start_id = strict_json_object(steps[3]['result_ref'])['start_operation_id']
        start = connection.execute(
            """SELECT n.instance_id,i.runtime_binding FROM code_operations o
               JOIN code_operation_steps s ON s.operation_id=o.id
               JOIN code_sessions n ON n.id=o.session_id AND n.task_id=o.task_id
               JOIN code_instances i ON i.id=n.instance_id AND i.task_id=o.task_id
               WHERE o.id=? AND o.task_id=? AND o.operation_type='START'
               AND o.control_generation=? AND n.control_generation=o.control_generation
               AND i.control_generation=o.control_generation
               AND s.step_no=5 AND s.status='SUCCEEDED'
               AND json_extract(s.result_ref,'$.session_id')=n.id""",
            (start_id, operation['task_id'], operation['control_generation']),
        ).fetchone()
        if (
            application['applied_at'] != operation['ended_at']
            or application['grant_status'] not in ('EFFECTIVE', 'RETIRED')
            or evidence['result'] != 'VERIFIED'
            or evidence['observed_at'] != application['applied_at']
            or start is None
            or start['instance_id'] != evidence['instance_id']
            or evidence['control_generation'] != operation['control_generation']
            or evidence['source_refs']
            != ['sha256:' + strict_json_object(start['runtime_binding'])['manifest_ref']]
        ):
            raise StorageUnavailable('Original effective configuration evidence differs')
    result = {
        **dict(operation),
        'fixed_input': fixed,
        'content_capture': None,
        'steps': [
            {
                **dict(step),
                'fixed_input': fixed,
                'result_ref': None
                if step['result_ref'] is None
                else strict_json_object(step['result_ref']),
            }
            for step in steps
        ],
    }
    return project_configuration_operation(result, operation['id'])


def pending_configuration(connection, task):
    original = staged_configuration(connection, task['id'])
    if original is None or original['status'] != 'RUNNING':
        return None
    result = public_configuration_operation(connection, original)
    if (
        result['fixed_input']['execution_profile_version_id']
        != task['execution_profile_version_id']
        or result['fixed_input']['authorization_id'] != task['authorization_id']
        or result['control_generation'] != task['control_generation']
        or result['fixed_input']['expected_state_version'] >= task['state_version']
        or connection.execute(
            'SELECT COUNT(*) FROM code_configuration_applications WHERE task_id=?', (task['id'],)
        ).fetchone()[0]
        != 1
    ):
        raise StorageUnavailable(
            'Current prepared configuration differs from the original selection'
        )
    return original


def finish_staged_configuration(connection, scope, evidence, at):
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (scope.task_id,)).fetchone()
    original = pending_configuration(connection, task)
    if original is None:
        return False
    application_id = strict_json_object(
        connection.execute(
            'SELECT result_ref FROM code_operation_steps WHERE operation_id=? AND step_no=3',
            (original['id'],),
        ).fetchone()[0]
    )['configuration_application_id']
    result = {
        'configuration_application_id': application_id,
        'start_operation_id': scope.operation_id,
    }
    updated = connection.execute(
        """UPDATE code_configuration_applications SET status='APPLIED',applied_at=?,effective_evidence=?
           WHERE id=? AND status='PENDING' AND authorization_id=? AND new_profile_version_id=?""",
        (at, canonical_input(evidence), application_id, scope.authorization_id, scope.profile_id),
    )
    effective = connection.execute(
        "UPDATE code_authorizations SET status='EFFECTIVE' WHERE id=? AND task_id=? AND status='BOUND_PENDING_APPLY'",
        (scope.authorization_id, scope.task_id),
    )
    if updated.rowcount != 1 or effective.rowcount != 1:
        raise StorageUnavailable('Original verified configuration binding changed')
    _finish_step(connection, original['id'], 'SUCCEEDED', at, result=result)
    return True


def _finish_step(connection, identity, status, at, *, result=None):
    ended = None if status == 'UNKNOWN' else at
    code = {'SUCCEEDED': None, 'UNKNOWN': 'EXTERNAL_RESULT_UNKNOWN', 'CANCELLED': 'TASK_ENDED'}[
        status
    ]
    step = connection.execute(
        """UPDATE code_operation_steps SET status=?,started_at=?,ended_at=?,last_observed_at=?,result_ref=?
           WHERE operation_id=? AND step_no=4 AND status='PENDING'""",
        (status, at, ended, at, None if result is None else canonical_input(result), identity),
    )
    operation = connection.execute(
        """UPDATE code_operations SET status=?,ended_at=?,failure_code=?
           WHERE id=? AND status='RUNNING'""",
        (status, ended, code, identity),
    )
    if step.rowcount != 1 or operation.rowcount != 1:
        raise StorageUnavailable('Original configuration verification state changed')


def interrupt_staged_configuration(connection, task_id, at, *, uncertain):
    original = staged_configuration(connection, task_id)
    if original is None or original['status'] != 'RUNNING':
        return
    public_configuration_operation(connection, original)
    status, application = ('UNKNOWN', 'UNKNOWN') if uncertain else ('CANCELLED', 'FAILED')
    saved = connection.execute(
        """UPDATE code_configuration_applications SET status=?
           WHERE operation_id=? AND task_id=? AND status='PENDING'""",
        (application, original['id'], task_id),
    )
    if saved.rowcount != 1:
        raise StorageUnavailable('Original configuration interruption differs')
    _finish_step(connection, original['id'], status, at)
