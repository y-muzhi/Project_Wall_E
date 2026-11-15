"""Project the original capture operation without private paths or Git receipts."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .command_registry import registered_command
from .operation_protocol import operation_steps
from .repository_operations import _time
from .task_candidate_commit import load_candidate_capture
from .task_start_view import OPERATION_FIELDS, STEP_FIELDS

TYPE = 'CAPTURE_AND_CHECK'
STEPS = operation_steps('CODING', TYPE)
_STATUSES = ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED')
_RESULT_KEYS = ('quiesce_observation_id', None, 'candidate_id', 'verification_id')


def _capture_projection(status, steps, captured_at):
    flags = [row['status'] for row in steps]
    if status == 'UNKNOWN' or 'UNKNOWN' in flags:
        state, issue = 'UNKNOWN', {'path': None, 'reason_code': 'RESULT_UNKNOWN'}
    else:
        issue = None
        if status in ('FAILED', 'CANCELLED') or 'FAILED' in flags:
            state = 'FAILED'
        elif flags[3] == 'SUCCEEDED' and status == 'SUCCEEDED':
            state = 'READY'
        elif flags[2] == 'SUCCEEDED':
            state = 'VERIFYING'
        elif flags[1] == 'SUCCEEDED':
            state = 'PUBLISHING'
        elif flags[1] == 'RUNNING':
            state = 'READING'
        else:
            state = 'PREPARING'
    return {
        'state': state,
        'content_policy_version': 'CONTENT20-STORE-1',
        'captured_at': captured_at,
        'issue': issue,
    }


def public_capture_operation(connection, operation):
    prepared, _, original, stored = load_candidate_capture(connection, operation['id'])
    if dict(operation) != dict(original):
        raise StorageUnavailable('Original capture operation differs')
    fixed = strict_json_object(operation['fixed_input'])
    public_steps = []
    captured_at = None
    for step, key in zip(stored, _RESULT_KEYS, strict=True):
        result = None
        if step['status'] == 'SUCCEEDED':
            private = strict_json_object(step['result_ref'])
            if key is not None:
                result = {key: private[key]}
            else:
                captured_at = private['captured_at']
        public_steps.append(
            {
                **dict(step),
                'fixed_input': fixed,
                'external_identity': None,
                'result_ref': result,
            }
        )
    if public_steps[2]['result_ref'] is not None:
        candidate = connection.execute(
            'SELECT id,captured_at FROM code_candidates WHERE capture_operation_id=? AND task_id=?',
            (operation['id'], prepared.task_id),
        ).fetchone()
        if (
            candidate is None
            or candidate['captured_at'] != captured_at
            or candidate['id'] != prepared.binding.candidate_id
            or public_steps[2]['result_ref'] != {'candidate_id': candidate['id']}
        ):
            raise StorageUnavailable('Original published candidate differs')
    if public_steps[3]['result_ref'] is not None:
        verification_id = public_steps[3]['result_ref']['verification_id']
        if (
            connection.execute(
                """SELECT 1 FROM code_verifications WHERE id=? AND task_id=? AND operation_id=?
               AND candidate_id=? AND owner_kind='CODING' AND purpose='HANDOFF'""",
                (verification_id, prepared.task_id, operation['id'], prepared.binding.candidate_id),
            ).fetchone()
            is None
        ):
            raise StorageUnavailable('Original candidate verification differs')
    return project_capture_operation(
        {
            **dict(operation),
            'fixed_input': fixed,
            'steps': public_steps,
            'content_capture': _capture_projection(operation['status'], public_steps, captured_at),
        },
        operation['id'],
    )


def project_capture_operation(value, identity):
    operation = exact(value, OPERATION_FIELDS)
    fixed = exact(operation['fixed_input'], ('expected_state_version', 'purpose'))
    task_id = strict_integer(operation['task_id'], 'task_id')
    strict_integer(operation['session_id'], 'session_id')
    strict_integer(operation['control_generation'], 'control_generation')
    expected = strict_integer(fixed['expected_state_version'], 'expected_state_version')
    registered_command(
        'POST', f'/api/v1/code-tasks/{task_id}/candidates', operation['idempotency_key']
    )
    if (
        operation['id'] != identity
        or operation['operation_type'] != TYPE
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != task_id
        or operation['testing_task_id'] is not None
        or operation['expected_state_version'] != expected
        or operation['status'] not in _STATUSES
        or fixed['purpose'] != 'HANDOFF'
        or type(operation['steps']) is not list
        or len(operation['steps']) != len(STEPS)
    ):
        raise ValueError('Original capture operation projection differs')
    _time(operation['created_at'], nullable=False)
    _time(operation['started_at'])
    _time(operation['ended_at'])
    complete = True
    for index, (source, name, key) in enumerate(
        zip(operation['steps'], STEPS, _RESULT_KEYS, strict=True), 1
    ):
        step = exact(source, STEP_FIELDS)
        if (
            step['operation_id'] != identity
            or step['step_no'] != index
            or step['step_type'] != name
            or step['status'] not in _STATUSES
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
            or (not complete and step['status'] not in ('PENDING', 'CANCELLED'))
        ):
            raise ValueError('Original capture step projection differs')
        for field in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[field])
        complete = step['status'] == 'SUCCEEDED'
        if complete and key is not None:
            result = exact(step['result_ref'], (key,))
            strict_integer(result[key], key)
        elif step['result_ref'] is not None:
            raise ValueError('Unregistered capture result data')
    captured_at = operation['content_capture']['captured_at']
    _time(captured_at)
    if (captured_at is not None) != (operation['steps'][1]['status'] == 'SUCCEEDED') or operation[
        'content_capture'
    ] != _capture_projection(operation['status'], operation['steps'], captured_at):
        raise ValueError('Original capture progress differs')
    return operation
