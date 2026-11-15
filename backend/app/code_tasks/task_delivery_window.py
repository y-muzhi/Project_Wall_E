"""Explicitly renew an original delivery window before reference dispatch."""

from datetime import datetime, timedelta

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.command_execution import operation_time
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import strict_json_object

from .coding_model_wait import read_task_waits
from .task_delivery import _deliver_authorization
from .task_delivery_write import load_original_delivery, unwritten_delivery_stage
from .task_resume import original_resume_steps
from .task_resume_runtime import _operation, _step


def renewable_delivery(connection, task, operation_id):
    if (
        task['status'] != 'WAITING'
        or task['phase'] != 'DELIVERY'
        or task['stop_requested_at'] is not None
        or task['current_delivery_id'] is None
    ):
        return None
    row = connection.execute(
        'SELECT operation_id FROM code_deliveries WHERE id=? AND task_id=?',
        (task['current_delivery_id'], task['id']),
    ).fetchone()
    if row is None or row['operation_id'] != operation_id:
        return None
    current = load_original_delivery(connection, operation_id)
    if (
        current.operation['status'] != 'UNKNOWN'
        or current.operation['control_generation'] != task['control_generation']
        or current.operation['session_id'] != task['active_session_id']
        or unwritten_delivery_stage(connection, current) is None
    ):
        return None
    waits = read_task_waits(connection, task['id'])
    if (
        len(waits) != 1
        or waits[0]['kind'] != 'DELIVERY_RESULT'
        or waits[0]['source_id'] != current.delivery['id']
    ):
        return None
    return current, waits[0]


def advance_delivery_window_resume(runtime, epoch):
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        resume = connection.execute(
            """SELECT o.* FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
               WHERE o.operation_type='RESUME' AND o.status='PENDING' AND t.stop_requested_at IS NULL
               AND json_extract(o.fixed_input,'$.repository_quiescent_confirmed')=1 ORDER BY o.id LIMIT 1"""
        ).fetchone()
        if resume is None:
            return False
        fixed, steps = original_resume_steps(connection, resume)
        identity = resume['id']
        if any(step['status'] != 'PENDING' for step in steps) or any(
            step['external_identity'] is not None for step in steps[1:]
        ):
            raise StorageUnavailable('Original delivery window renewal steps differ')
        controller = strict_json_object(steps[0]['external_identity'])
        if set(controller) != {'controller_epoch'}:
            raise StorageUnavailable('Original delivery renewal controller differs')
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (resume['task_id'],)
        ).fetchone()
        if task is None or task['control_generation'] != resume['control_generation']:
            raise StorageUnavailable('Original delivery window renewal is fenced')
        at = max(operation_time(None), task['updated_at'])
        ready = renewable_delivery(connection, task, fixed['operation_id'])
        seconds = _deliver_authorization(connection, task)
        expires = (
            None
            if seconds is None
            else utc_milliseconds(
                datetime.fromisoformat(resume['created_at']) + timedelta(seconds=seconds)
            )
        )
        if (
            controller['controller_epoch'] != epoch
            or ready is None
            or fixed['waiting_item_ids'] != [ready[1]['id']]
            or expires is None
            or at >= expires
        ):
            _step(connection, identity, 1, 'FAILED', at)
            _operation(connection, identity, 'FAILED', at, 'CONFIG_NOT_READY')
            return True
        original, wait = ready
        window = entity_id(connection, EntityKind.DELIVERY_WINDOW)
        connection.execute(
            """INSERT INTO code_delivery_windows(id,delivery_id,operation_id,confirmed_at,expires_at,controller_epoch_ref)
               VALUES(?,?,?,?,?,?)""",
            (window, original.delivery['id'], identity, resume['created_at'], expires, epoch),
        )
        connection.execute(
            'UPDATE code_deliveries SET current_window_id=? WHERE id=?',
            (window, original.delivery['id']),
        )
        connection.execute(
            """UPDATE code_operations SET status='PENDING',ended_at=NULL,failure_code=NULL WHERE id=?""",
            (original.operation['id'],),
        )
        connection.execute(
            """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
               WHERE id=? AND status='OPEN'""",
            (
                at,
                canonical_input({'operation_id': identity, 'delivery_window_id': window}),
                wait['id'],
            ),
        )
        connection.execute(
            """UPDATE code_tasks SET status='AWAITING_ACCEPTANCE',phase='ACCEPTANCE',resume_phase=NULL,
               state_version=?,updated_at=?,last_observed_at=? WHERE id=?""",
            (increment(task['state_version']), at, at, task['id']),
        )
        _step(
            connection,
            identity,
            1,
            'SUCCEEDED',
            at,
            result={'operation_id': original.operation['id']},
        )
        _step(connection, identity, 2, 'SUCCEEDED', at)
        _step(connection, identity, 3, 'SUCCEEDED', at, result={'delivery_window_id': window})
        _operation(connection, identity, 'SUCCEEDED', at)
        return True
