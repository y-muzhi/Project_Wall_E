"""TaskView for the original Coding candidate while development checks are pending."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .repository_operations import _time
from .task_cancelled_repair import read_cancelled_repair
from .task_candidate_commit import (
    load_candidate_capture,
    read_stored_candidate_package,
    verify_capture_quiescence_record,
)
from .task_capture_quiescence import active_candidate_check
from .task_start_view import started_task_view, validate_started_task


def project_published_activity(connection, task, data):
    """Project current activity from the exact candidate's saved native observation."""
    runtime = data['runtime']
    runtime.update(activity_status='UNKNOWN', active_process_count=None, observed_at=None)
    if (
        data['active_operations']
        or connection.execute(
            """SELECT 1 FROM code_commands WHERE task_id=?
           AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1""",
            (task['id'],),
        ).fetchone()
        is not None
    ):
        return

    original = connection.execute(
        """SELECT c.capture_operation_id,s.native_session_id,s.model_window
           FROM code_candidates c
           JOIN code_sessions s ON s.id=? AND s.task_id=c.task_id
           JOIN code_instances i ON i.id=s.instance_id AND i.task_id=s.task_id
           WHERE c.id=? AND c.task_id=? AND c.role='INTEGRATION'
           AND c.control_generation=? AND s.control_generation=c.control_generation
           AND s.role=c.role AND s.status='ACTIVE' AND i.status='READY'""",
        (
            task['active_session_id'],
            task['current_candidate_id'],
            task['id'],
            task['control_generation'],
        ),
    ).fetchone()
    if original is None or original['model_window'] is None:
        return
    window = strict_json_object(original['model_window'])
    if window['state'] != 'CLOSED':
        return
    prepared, _, operation, steps = load_candidate_capture(
        connection, original['capture_operation_id']
    )
    if (
        prepared.binding.candidate_id != task['current_candidate_id']
        or prepared.session_id != task['active_session_id']
        or operation['status'] != 'SUCCEEDED'
    ):
        return
    proof = verify_capture_quiescence_record(connection, prepared, steps[0])
    if (
        proof['turn']['session_id'] == original['native_session_id']
        and proof['turn']['trigger_message_id'] == window['native_trigger_message_id']
    ):
        runtime.update(
            activity_status='QUIESCENT',
            active_process_count=proof['active_process_count'],
            observed_at=steps[0]['ended_at'],
        )


def captured_task_view(connection, task, materials, differences, budget):
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (task['active_session_id'], task['id']),
    ).fetchone()
    cancelled = None
    if session is not None and session['model_window'] is not None:
        cancelled = read_cancelled_repair(
            connection, task, session, strict_json_object(session['model_window'])
        )
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (task['current_candidate_id'], task['id']),
    ).fetchone()
    if (
        candidate is None
        or candidate['role'] != task['phase']
        or (candidate['control_generation'] != task['control_generation'] and cancelled is None)
    ):
        raise StorageUnavailable('Original current candidate differs')
    read_stored_candidate_package(connection, candidate)
    operation = connection.execute(
        'SELECT status FROM code_operations WHERE id=? AND task_id=? AND control_generation=?',
        (candidate['capture_operation_id'], task['id'], candidate['control_generation']),
    ).fetchone()
    observation = connection.execute(
        """SELECT observed_at,active_process_count FROM code_runtime_observations
           WHERE operation_id=? AND task_id=? AND control_generation=? AND kind='QUIESCE'
           AND result='VERIFIED' ORDER BY id DESC LIMIT 1""",
        (candidate['capture_operation_id'], task['id'], candidate['control_generation']),
    ).fetchone()
    if operation is None or observation is None or observation['active_process_count'] != 1:
        raise StorageUnavailable('Original captured task runtime differs')

    verification = None
    if task['current_verification_id'] is not None:
        verification = connection.execute(
            """SELECT v.id,v.status,v.stop_status FROM code_verifications v
               JOIN code_operations o ON o.id=v.operation_id AND o.task_id=v.task_id
               WHERE v.id=? AND v.task_id=? AND v.candidate_id=? AND v.owner_kind='CODING'
               AND ((o.operation_type='CAPTURE_AND_CHECK' AND o.id=?) OR
                    (o.operation_type='VERIFY_CANDIDATE' AND json_extract(o.fixed_input,'$.candidate_id')=v.candidate_id))""",
            (
                task['current_verification_id'],
                task['id'],
                candidate['id'],
                candidate['capture_operation_id'],
            ),
        ).fetchone()
        if verification is None:
            raise StorageUnavailable('Original current candidate verification differs')
    if cancelled is not None:
        observation = cancelled
    data = started_task_view(task, materials, differences, budget=budget)
    if verification is not None:
        data['current_refs']['verification_id'] = verification['id']
    active = active_candidate_check(connection, task['id'])
    if active is not None:
        data['active_operations'] = [dict(active)]
    stopped = verification is None or verification['stop_status'] == 'VERIFIED'
    data['runtime'].update(
        activity_status='QUIESCENT' if stopped else 'UNKNOWN',
        active_process_count=1 if stopped else None,
        observed_at=observation['observed_at'],
    )
    for item in data['verification_purposes']:
        item['reason_code'] = 'RESOURCE_NOT_READY'
    return data


def validate_captured_task(data, task_id):
    strict_integer(data['current_candidate_id'], 'current_candidate_id')
    verification_id = data['current_refs']['verification_id']
    if verification_id is not None:
        strict_integer(verification_id, 'verification_id')
    runtime = data['runtime']
    observed = runtime['observed_at']
    _time(observed, nullable=False)
    if (
        data['status'] != 'VERIFYING'
        or (runtime['activity_status'], runtime['active_process_count'])
        not in (('QUIESCENT', 1), ('UNKNOWN', None))
        or (
            runtime['activity_status'] == 'QUIESCENT'
            and type(runtime['active_process_count']) is not int
        )
        or (verification_id is None and runtime['activity_status'] != 'QUIESCENT')
        or not data['started_at'] <= observed <= data['last_observed_at']
        or any(
            item['reason_code'] != 'RESOURCE_NOT_READY' for item in data['verification_purposes']
        )
        or len(data['active_operations']) > 1
    ):
        raise ValueError('Original captured task state differs')
    for value in data['active_operations']:
        original = exact(value, ('id', 'operation_type', 'status'))
        strict_integer(original['id'], 'operation_id')
        if original['operation_type'] not in ('CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE') or original[
            'status'
        ] not in (
            'PENDING',
            'RUNNING',
            'UNKNOWN',
        ):
            raise ValueError('Original candidate operation differs')
    validate_started_task(
        {
            **data,
            'status': 'RUNNING',
            'current_candidate_id': None,
            'current_refs': {**data['current_refs'], 'verification_id': None},
            'active_operations': [],
            'runtime': {
                **runtime,
                'activity_status': 'UNKNOWN',
                'active_process_count': None,
                'observed_at': data['last_observed_at'],
            },
            'verification_purposes': [
                {**item, 'reason_code': 'TASK_STATE'} for item in data['verification_purposes']
            ],
        },
        task_id,
    )
