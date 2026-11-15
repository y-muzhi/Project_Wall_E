"""Public delivery wait and natural completion backed by their original records."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_enum, strict_integer

from .coding_model_wait import project_task_wait, read_task_waits
from .costs import parse_balance, parse_money
from .initial_task_view import _validate_fixed_view, initial_task_view
from .repository_operations import _time
from .task_delivery_finalize import (
    _matching_result,
    _natural_stop_observation,
    _scope,
    read_finalized_delivery,
)
from .task_delivery_write import load_original_delivery


def delivery_task_view(connection, task, materials, differences, budget):
    identity = connection.execute(
        'SELECT operation_id FROM code_deliveries WHERE id=? AND task_id=?',
        (task['current_delivery_id'], task['id']),
    ).fetchone()
    if identity is None:
        raise StorageUnavailable('Original task delivery is missing')
    original = load_original_delivery(connection, identity[0])
    if (
        task['current_candidate_id'] != original.fixed['candidate_id']
        or task['current_test_report_id'] != original.fixed['test_report_id']
        or task['current_delivery_plan_id'] != original.plan['id']
        or task['current_verification_id'] is None
    ):
        raise StorageUnavailable('Original task delivery references differ')
    completed = task['status'] == 'COMPLETED'
    stopped = False
    cleanup_unknown = False
    if completed:
        read_finalized_delivery(connection, original)
        stopped = True
    else:
        if original.operation['status'] not in ('RUNNING', 'UNKNOWN'):
            raise StorageUnavailable('Original task delivery wait has no active operation')
        final = original.steps[7]
        cleanup_unknown = final['status'] == 'UNKNOWN'
        if final['external_identity'] is not None:
            scope = _scope(connection, original, require_idle=False)
            if scope is not None:
                _matching_result(connection, original, *scope)
                stopped = _natural_stop_observation(connection, scope[1], scope[0]) is not None
    data = initial_task_view(task, materials, differences, False)
    data['budget'] = budget
    data['current_refs'] = {
        'verification_id': task['current_verification_id'],
        'test_report_id': original.fixed['test_report_id'],
        'delivery_plan_id': original.plan['id'],
        'delivery_id': original.delivery['id'],
    }
    data['waiting_items'] = read_task_waits(connection, task['id'])
    if not completed:
        data['active_operations'] = [
            {key: original.operation[key] for key in ('id', 'operation_type', 'status')}
        ]
    data['available_actions'] = [
        {
            **item,
            'enabled': item['action'] == 'TERMINATE' and not completed,
            'reason_code': 'TASK_ENDED'
            if completed
            else None
            if item['action'] == 'TERMINATE'
            else 'INVALID_STATE',
        }
        for item in data['available_actions']
    ]
    data['runtime'].update(
        environment_status='UNKNOWN',
        activity_status='UNKNOWN',
        stop_status='VERIFIED' if stopped else 'NONE',
        cleanup_status='VERIFIED' if completed else 'UNKNOWN' if cleanup_unknown else 'NOT_STARTED',
        active_process_count=0 if stopped else None,
        observed_at=task['last_observed_at'],
    )
    return data


def validate_delivery_task_view(data, task_id):
    if data['id'] != task_id:
        raise ValueError('Original delivery task owner differs')
    limit, _, _ = _validate_fixed_view(data, data['document_id'])
    for key in (
        'id',
        'workspace_id',
        'current_candidate_id',
        'control_generation',
        'state_version',
    ):
        strict_integer(data[key], key)
    refs = exact(
        data['current_refs'],
        ('verification_id', 'test_report_id', 'delivery_plan_id', 'delivery_id'),
    )
    for name, value in refs.items():
        strict_integer(value, name)
    for key in ('started_at', 'last_observed_at'):
        _time(data[key], nullable=False)
    completed = data['status'] == 'COMPLETED'
    if (
        data['phase'] != ('FINISHED' if completed else 'DELIVERY')
        or data['resume_phase'] != (None if completed else 'DELIVERY')
        or data['termination_operation_id'] is not None
        or data['stop_requested_at'] is not None
        or data['stopped_at'] is not None
        or not data['created_at']
        <= data['started_at']
        <= data['last_observed_at']
        <= data['updated_at']
    ):
        raise ValueError('Original delivery task state differs')
    runtime = data['runtime']
    stopped = runtime['stop_status'] == 'VERIFIED'
    if (
        runtime['isolation_mode'] != 'WINDOWS_LPAC'
        or runtime['environment_status'] != 'UNKNOWN'
        or runtime['activity_status'] != 'UNKNOWN'
        or runtime['stop_status'] not in ('NONE', 'VERIFIED')
        or runtime['cleanup_status']
        not in (('VERIFIED',) if completed else ('NOT_STARTED', 'UNKNOWN'))
        or runtime['active_process_count'] != (0 if stopped else None)
        or runtime['observed_at'] != data['last_observed_at']
        or runtime['reason_codes']
    ):
        raise ValueError('Original delivery task runtime differs')
    if completed:
        if (
            not stopped
            or data['ended_at'] != data['last_observed_at']
            or data['active_session_id'] is not None
            or data['active_operations']
            or data['waiting_items']
        ):
            raise ValueError('Original delivery natural completion differs')
    else:
        strict_integer(data['active_session_id'], 'active_session_id')
        active = data['active_operations']
        waits = [project_task_wait(item, task_id) for item in data['waiting_items']]
        if (
            data['ended_at'] is not None
            or len(active) != 1
            or len(waits) != 1
            or waits[0]['kind'] != 'DELIVERY_RESULT'
            or waits[0]['source_id'] != refs['delivery_id']
        ):
            raise ValueError('Original delivery wait differs')
        operation = exact(active[0], ('id', 'operation_type', 'status'))
        strict_integer(operation['id'], 'operation_id')
        strict_enum(operation['status'], 'status', ('RUNNING', 'UNKNOWN'))
        if operation['operation_type'] != 'DELIVER':
            raise ValueError('Original delivery active operation differs')
    budget = exact(
        data['budget'],
        ('limit_cny', 'settled_cny', 'reserved_cny', 'available_cny', 'unresolved_call_count'),
    )
    strict_integer(budget['unresolved_call_count'], 'unresolved_call_count', minimum=0)
    if parse_balance(budget['available_cny']) != (
        parse_money(limit)
        - parse_money(budget['settled_cny'])
        - parse_money(budget['reserved_cny'])
    ):
        raise ValueError('Original delivery budget differs')
