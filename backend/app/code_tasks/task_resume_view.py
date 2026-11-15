"""Public facts for a model continuation and its original waiting action."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .command_registry import registered_command
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .task_resume import (
    ACTIVE,
    RESUME_PATH,
    RESUME_STEPS,
    active_resume,
    model_resume_window,
    model_waits_cleared,
    original_resume_steps,
)


def resume_action_state(connection, task, waits):
    if task['status'] != 'WAITING':
        return None
    active = active_resume(connection, task['id'])
    if active is not None:
        original_resume_steps(connection, active)
        reason = (
            'EXTERNAL_RESULT_UNKNOWN' if active['status'] == 'UNKNOWN' else 'OPERATION_IN_PROGRESS'
        )
        return (active['id'], reason, active['status'])
    model = model_resume_window(connection, task)
    if model is None:
        return None
    window, _ = model
    reason = None if model_waits_cleared(connection, window, waits) else 'EXTERNAL_RESULT_UNKNOWN'
    return (window.operation_id, reason, None)


def public_resume_operation(connection, operation):
    fixed, steps = original_resume_steps(connection, operation)
    original = connection.execute(
        """SELECT operation_type,status,session_id,control_generation FROM code_operations
           WHERE id=? AND task_id=?""",
        (fixed['operation_id'], operation['task_id']),
    ).fetchone()
    renewal = fixed.get('repository_quiescent_confirmed') is True
    delivery_source = original is not None and original['operation_type'] == 'DELIVER'
    cleanup = delivery_source and not renewal
    if (
        original is None
        or renewal
        and not delivery_source
        or not delivery_source
        and (
            original['operation_type'] not in ('START', 'RESUME')
            or original['status'] != 'SUCCEEDED'
        )
        or original['session_id'] != operation['session_id']
        or original['control_generation'] + int(cleanup) != operation['control_generation']
    ):
        raise StorageUnavailable('Original continuation source differs')
    refs = {1: {'operation_id': fixed['operation_id']}}
    if cleanup:
        delivery = connection.execute(
            """SELECT id,status,git_write_status FROM code_deliveries WHERE operation_id=? AND task_id=?""",
            (fixed['operation_id'], operation['task_id']),
        ).fetchone()
        if delivery is None or (delivery['status'], delivery['git_write_status']) != (
            'SUCCEEDED',
            'CONFIRMED',
        ):
            raise StorageUnavailable('Original cleanup continuation has no verified Git result')
        refs[3] = {'delivery_id': delivery['id']}
    elif not renewal:
        refs[3] = {'session_id': operation['session_id']}
    elif operation['status'] == 'SUCCEEDED':
        window = connection.execute(
            """SELECT w.id FROM code_delivery_windows w JOIN code_deliveries d ON d.id=w.delivery_id
               WHERE w.operation_id=? AND d.operation_id=? AND d.task_id=?""",
            (operation['id'], fixed['operation_id'], operation['task_id']),
        ).fetchone()
        if window is None:
            raise StorageUnavailable('Original delivery renewal window is missing')
        refs[3] = {'delivery_window_id': window['id']}
    projected = []
    for step in steps:
        result = refs.get(step['step_no']) if step['status'] == 'SUCCEEDED' else None
        stored_result = (
            None if step['result_ref'] is None else strict_json_object(step['result_ref'])
        )
        if result != stored_result:
            raise StorageUnavailable('Original continuation public result differs')
        projected.append(
            {
                **dict(step),
                'fixed_input': fixed,
                'result_ref': result,
                'external_identity': None
                if renewal or cleanup or step['external_identity'] is None
                else {},
            }
        )
    return project_resume_operation(
        {
            **dict(operation),
            'fixed_input': fixed,
            'content_capture': None,
            'steps': projected,
        },
        operation['id'],
    )


def project_resume_operation(data, operation_id):
    row = exact(data, OPERATION_FIELDS)
    task_id = strict_integer(row['task_id'], 'task_id')
    version = strict_integer(row['expected_state_version'], 'expected_state_version')
    session = strict_integer(row['session_id'], 'session_id')
    strict_integer(row['control_generation'], 'control_generation')
    fixed = row['fixed_input']
    fields = ('task_id', 'expected_state_version', 'operation_id', 'waiting_item_ids')
    renewal = fixed.get('repository_quiescent_confirmed') is True
    exact(fixed, (*fields, 'repository_quiescent_confirmed') if renewal else fields)
    original = strict_integer(fixed['operation_id'], 'original_operation_id')
    waits = fixed['waiting_item_ids']
    if (
        row['id'] != operation_id
        or row['resource_id'] != task_id
        or row['resource_kind'] != 'TASK'
        or row['operation_type'] != 'RESUME'
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or fixed['task_id'] != task_id
        or fixed['expected_state_version'] != version
        or original == operation_id
        or type(waits) is not list
        or not waits
        or len({strict_integer(value, 'waiting_item_id') for value in waits}) != len(waits)
    ):
        raise ValueError('Original continuation public identity differs')
    registered_command('POST', RESUME_PATH.format(task_id=task_id), row['idempotency_key'])
    created = row['created_at']
    _time(created, nullable=False)
    status = row['status']
    terminal = status not in ACTIVE
    untouched = status in ('PENDING', 'CANCELLED')
    started, ended = row['started_at'], row['ended_at']
    _time(started, nullable=untouched)
    _time(ended, nullable=not terminal)
    code = row['failure_code']
    states = {
        'PENDING': {('PENDING', 'PENDING', 'PENDING')},
        'RUNNING': {('SUCCEEDED', 'SUCCEEDED', 'RUNNING')},
        'UNKNOWN': {('SUCCEEDED', 'SUCCEEDED', 'UNKNOWN')},
        'SUCCEEDED': {('SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED')},
        'FAILED': {('FAILED', 'PENDING', 'PENDING'), ('SUCCEEDED', 'FAILED', 'PENDING')},
        'CANCELLED': {('PENDING', 'PENDING', 'PENDING')},
    }
    allowed_codes = {
        'FAILED': ('EXECUTION_NOT_STOPPED', 'CONFIG_NOT_READY'),
        'UNKNOWN': ('EXTERNAL_RESULT_UNKNOWN',),
        'CANCELLED': ('TASK_ENDED',),
    }
    if (
        status not in states
        or code not in allowed_codes.get(status, (None,))
        or (ended is not None) != terminal
        or (started is None) != untouched
        or not created <= (started or created) <= (ended or started or created)
        or type(row['steps']) is not list
        or len(row['steps']) != len(RESUME_STEPS)
    ):
        raise ValueError('Original continuation public status differs')
    final_ref = row['steps'][-1]['result_ref']
    cleanup = not renewal and type(final_ref) is dict and 'delivery_id' in final_ref
    observed_states = []
    for number, (raw, kind) in enumerate(zip(row['steps'], RESUME_STEPS), 1):
        step = exact(raw, STEP_FIELDS)
        observed = step['status']
        observed_states.append(observed)
        no_activity = observed == 'PENDING'
        complete = observed in ('FAILED', 'SUCCEEDED')
        begin, finish, seen = (step[key] for key in ('started_at', 'ended_at', 'last_observed_at'))
        _time(begin, nullable=no_activity)
        _time(finish, nullable=not complete)
        _time(seen, nullable=no_activity)
        ref = {1: {'operation_id': original}, 3: {'session_id': session}}.get(number)
        if renewal and number == 3 and observed == 'SUCCEEDED':
            window = exact(step['result_ref'], ('delivery_window_id',))
            strict_integer(window['delivery_window_id'], 'delivery_window_id')
            ref = window
        if cleanup and number == 3:
            ref = exact(step['result_ref'], ('delivery_id',))
            strict_integer(ref['delivery_id'], 'delivery_id')
        dispatched = not (renewal or cleanup) and number == 3 and not no_activity
        if (
            step['operation_id'] != operation_id
            or step['step_no'] != number
            or step['step_type'] != kind
            or step['fixed_input'] != fixed
            or step['external_identity'] != ({} if dispatched else None)
            or step['result_ref'] != (ref if observed == 'SUCCEEDED' else None)
            or (begin is None) != no_activity
            or (seen is None) != no_activity
            or (finish is not None) != complete
            or not created <= (begin or created) <= (finish or seen or created) <= (seen or created)
        ):
            raise ValueError('Original continuation public step differs')
    if tuple(observed_states) not in states[status]:
        raise ValueError('Original continuation public progression differs')
    return row
