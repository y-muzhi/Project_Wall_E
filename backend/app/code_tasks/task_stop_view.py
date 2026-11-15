"""Public stop facts for an original Coding task with a materialized workspace."""

from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer

from .coding_model_wait import project_task_wait
from .costs import parse_balance, parse_money
from .initial_task_view import _validate_fixed_view, stopping_task_view
from .repository_operations import _time


def owned_stop_stages(steps, status, *, stopped):
    """Describe only the steps saved by the original owned stop operation."""
    if status == 'SUCCEEDED':
        return 'VERIFIED', 'VERIFIED'
    if stopped:
        cleanup = (
            'UNKNOWN'
            if status == 'UNKNOWN'
            else 'CLEANING'
            if steps[5]['status'] == 'RUNNING'
            else 'NOT_STARTED'
        )
        return 'VERIFIED', cleanup
    if status == 'UNKNOWN':
        return 'UNKNOWN', 'UNKNOWN'
    if steps[3]['status'] == 'RUNNING':
        return 'TERMINATING', 'NOT_STARTED'
    if steps[2]['status'] in ('RUNNING', 'SUCCEEDED'):
        return 'ABORTING', 'NOT_STARTED'
    return 'REQUESTED', 'NOT_STARTED'


def owned_stop_view(task, materials, differences, stop, *, stages, budget, waits=()):
    data = stopping_task_view(task, materials, differences, stop[0], stop[1])
    stop_stage, cleanup_stage = stages
    data['budget'] = budget
    data['waiting_items'] = list(waits)
    data['runtime'].update(
        environment_status='UNKNOWN',
        activity_status='UNKNOWN',
        stop_status=stop_stage,
        cleanup_status=cleanup_stage,
        active_process_count=0 if stop_stage == 'VERIFIED' else None,
    )
    return data


def validate_owned_stop_view(data, task_id):
    if strict_integer(data['id'], 'task_id') != task_id:
        raise ValueError('Original Coding stop task differs')
    limit, materials, differences = _validate_fixed_view(data, data['document_id'])
    strict_integer(data['workspace_id'], 'workspace_id')
    strict_integer(data['state_version'], 'state_version', minimum=4)
    strict_integer(data['control_generation'], 'control_generation', minimum=2)
    identity = strict_integer(data['termination_operation_id'], 'stop_operation_id')
    status = data['status']
    terminal = status == 'TERMINATED'
    if data['current_candidate_id'] is not None:
        strict_integer(data['current_candidate_id'], 'current_candidate_id')
    if (
        status not in ('STOPPING', 'TERMINATED')
        or data['phase']
        not in (
            ('FINISHED',)
            if terminal
            else (
                'PREPARING',
                'BACKEND',
                'FRONTEND',
                'INTEGRATION',
                'TESTING',
                'ACCEPTANCE',
                'DELIVERY',
            )
        )
        or data['resume_phase'] is not None
    ):
        raise ValueError('Original Coding stop task state differs')
    requested = data['stop_requested_at']
    started, observed = data['started_at'], data['last_observed_at']
    _time(requested, nullable=False)
    _time(started, nullable=True)
    _time(observed, nullable=True)
    if (
        not data['created_at'] <= requested <= data['updated_at']
        or (started is not None and not data['created_at'] <= started <= requested)
        or (observed is not None and not data['created_at'] <= observed <= data['updated_at'])
    ):
        raise ValueError('Original Coding stop chronology differs')
    if data['active_session_id'] is not None:
        strict_integer(data['active_session_id'], 'active_session_id')
    waits = [project_task_wait(row, task_id) for row in data['waiting_items']]
    if terminal and waits:
        raise ValueError('Original terminal task retains open model waits')
    stages = data['runtime']['stop_status'], data['runtime']['cleanup_status']
    stopped = stages[0] == 'VERIFIED'
    if stopped and (observed is None or observed < requested):
        raise ValueError('Original Coding stop observation chronology differs')
    if terminal:
        _time(data['ended_at'], nullable=False)
        if (
            data['active_operations']
            or data['active_session_id'] is not None
            or not stopped
            or not data['ended_at'] == data['stopped_at'] == observed
        ):
            raise ValueError('Original Coding terminal task differs')
        operation_status = 'SUCCEEDED'
        if stages != ('VERIFIED', 'VERIFIED'):
            raise ValueError('Original Coding terminal cleanup differs')
    else:
        if data['ended_at'] is not None or data['stopped_at'] is not None:
            raise ValueError('Original Coding active stop cannot claim completion')
        if type(data['active_operations']) is not list or len(data['active_operations']) != 1:
            raise ValueError('Original Coding stop operation missing')
        operation = exact(data['active_operations'][0], ('id', 'operation_type', 'status'))
        operation_status = operation['status']
        if (
            operation['id'] != identity
            or operation['operation_type'] != 'TERMINATE'
            or operation_status not in ('PENDING', 'RUNNING', 'UNKNOWN')
            or (stopped and operation_status == 'PENDING')
        ):
            raise ValueError('Original Coding active stop differs')
        allowed = {
            'PENDING': {('REQUESTED', 'NOT_STARTED')},
            'RUNNING': {
                ('REQUESTED', 'NOT_STARTED'),
                ('ABORTING', 'NOT_STARTED'),
                ('TERMINATING', 'NOT_STARTED'),
                ('VERIFIED', 'NOT_STARTED'),
                ('VERIFIED', 'CLEANING'),
            },
            'UNKNOWN': {('UNKNOWN', 'UNKNOWN'), ('VERIFIED', 'UNKNOWN')},
        }
        if stages not in allowed[operation_status]:
            raise ValueError('Original Coding active stop stages differ')
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
        raise ValueError('Original Coding stop budget differs')
    expected = owned_stop_view(
        {**data, 'budget_limit_cny': limit},
        materials,
        differences,
        (identity, operation_status),
        stages=stages,
        budget=budget,
        waits=waits,
    )
    if data != expected:
        raise ValueError('Original Coding stop projection differs')
