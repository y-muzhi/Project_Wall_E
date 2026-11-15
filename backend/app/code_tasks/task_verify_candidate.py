"""Keep the original VERIFY_CANDIDATE receipt, candidate and copy stages together."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import increment
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .command_registry import registered_command
from .operation_protocol import operation_steps
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time

TYPE = 'VERIFY_CANDIDATE'
VERIFY = '/api/v1/code-tasks/{task_id}/candidates/{candidate_id}/verifications'
STEPS = operation_steps('CODING', TYPE)
STATUSES = ('PENDING', 'RUNNING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED')


def _fixed(raw):
    value = exact(raw, ('candidate_id', 'expected_state_version', 'purpose'))
    strict_integer(value['candidate_id'], 'candidate_id')
    strict_integer(value['expected_state_version'], 'expected_state_version')
    if value['purpose'] != 'HANDOFF':
        raise ValueError('Original fixed-candidate purpose differs')
    return value


def load_candidate_verification(connection, operation):
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    fixed = _fixed(strict_json_object(operation['fixed_input']))
    command = registered_command(
        'POST',
        VERIFY.format(task_id=operation['task_id'], candidate_id=fixed['candidate_id']),
        operation['idempotency_key'],
    )
    receipt = connection.execute(
        """SELECT status,business_input_json,http_status,success_result_json FROM idempotency_records
           WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (fixed['candidate_id'], operation['task_id']),
    ).fetchone()
    session = connection.execute(
        'SELECT role,control_generation FROM code_sessions WHERE id=? AND task_id=?',
        (operation['session_id'], operation['task_id']),
    ).fetchone()
    if (
        operation['operation_type'] != TYPE
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != operation['task_id']
        or operation['testing_task_id'] is not None
        or operation['expected_state_version'] != fixed['expected_state_version']
        or operation['fixed_input'] != canonical_input(fixed)
        or task is None
        or candidate is None
        or session is None
        or not candidate['control_generation']
        == session['control_generation']
        == operation['control_generation']
        or candidate['role'] != session['role']
        or tuple((step['step_no'], step['step_type']) for step in steps)
        != tuple(enumerate(STEPS, 1))
        or any(step['fixed_input'] != operation['fixed_input'] for step in steps)
        or receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['business_input_json'] != operation['fixed_input']
        or receipt['http_status'] != 202
    ):
        raise StorageUnavailable('Original fixed-candidate operation differs')
    result = strict_json_object(receipt['success_result_json'])
    if result != {
        'code': 'OPERATION_ACCEPTED',
        'data': {
            'task_id': task['id'],
            'operation_id': operation['id'],
            'operation_status': 'PENDING',
            'task_status': 'VERIFYING',
            'state_version': increment(operation['expected_state_version']),
        },
        'details': None,
    }:
        raise StorageUnavailable('Original fixed-candidate acceptance receipt differs')
    return task, candidate, steps


def public_verify_candidate(connection, operation):
    task, candidate, steps = load_candidate_verification(connection, operation)
    projected = []
    for step in steps:
        result = None
        if step['status'] == 'SUCCEEDED':
            saved = strict_json_object(step['result_ref'])
            if step['step_type'] in ('CHECK_CONDITIONS', 'RESTORE_CHECK_COPY'):
                if saved['candidate_id'] != candidate['id']:
                    raise StorageUnavailable('Original fixed-candidate copy result differs')
                result = {'candidate_id': saved['candidate_id']}
            else:
                verification_id = strict_integer(saved['verification_id'], 'verification_id')
                if (
                    connection.execute(
                        """SELECT 1 FROM code_verifications WHERE id=? AND task_id=? AND operation_id=?
                       AND candidate_id=? AND owner_kind='CODING' """,
                        (verification_id, task['id'], operation['id'], candidate['id']),
                    ).fetchone()
                    is None
                ):
                    raise StorageUnavailable('Original fixed-candidate verification differs')
                result = {'verification_id': verification_id}
        projected.append(
            {
                **dict(step),
                'fixed_input': strict_json_object(step['fixed_input']),
                'external_identity': None,
                'result_ref': result,
            }
        )
    return project_verify_candidate(
        {
            **dict(operation),
            'fixed_input': strict_json_object(operation['fixed_input']),
            'content_capture': None,
            'steps': projected,
        },
        operation['id'],
    )


def project_verify_candidate(data, operation_id):
    row = exact(data, OPERATION_FIELDS)
    fixed = _fixed(row['fixed_input'])
    for field in ('task_id', 'session_id', 'control_generation'):
        strict_integer(row[field], field)
    if (
        row['id'] != operation_id
        or row['operation_type'] != TYPE
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != row['task_id']
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or row['expected_state_version'] != fixed['expected_state_version']
        or row['status'] not in STATUSES
        or type(row['steps']) is not list
        or len(row['steps']) != len(STEPS)
    ):
        raise ValueError('Original fixed-candidate operation projection differs')
    _time(row['created_at'], nullable=False)
    _time(row['started_at'])
    _time(row['ended_at'])
    previous = 'SUCCEEDED'
    for number, (step, kind) in enumerate(zip(row['steps'], STEPS, strict=True), 1):
        step = exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != operation_id
            or step['step_no'] != number
            or step['step_type'] != kind
            or step['status'] not in STATUSES
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
            or (previous != 'SUCCEEDED' and step['status'] not in ('PENDING', 'CANCELLED'))
        ):
            raise ValueError('Original fixed-candidate step differs')
        for field in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[field])
        previous = step['status']
        if previous == 'SUCCEEDED':
            key = 'verification_id' if kind == 'CHECK' else 'candidate_id'
            result = exact(step['result_ref'], (key,))
            strict_integer(result[key], key)
            if key == 'candidate_id' and result[key] != fixed[key]:
                raise ValueError('Original fixed-candidate step target differs')
        elif step['result_ref'] is not None:
            raise ValueError('Original fixed-candidate step has premature result')
    return row
