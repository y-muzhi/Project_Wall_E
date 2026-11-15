"""Public handoff history excludes native message IDs, paths, and credentials."""

from uuid import UUID

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .task_role_chain import HANDOFF, STEPS, _fixed

_RESULTS = (
    ('quiesce_observation_id',),
    ('session_id', 'control_generation'),
    ('verification_id',),
    ('session_id',),
    ('session_id',),
)
_STATES = ('PENDING', 'RUNNING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED')


def public_role_operation(connection, operation):
    fixed = _fixed(operation)
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(STEPS):
        raise StorageUnavailable('Original role operation steps differ')
    output = []
    for row, fields in zip(steps, _RESULTS, strict=True):
        result = None
        if row['status'] == 'SUCCEEDED':
            original = strict_json_object(row['result_ref'])
            result = {field: original[field] for field in fields}
        if row['fixed_input'] != operation['fixed_input']:
            raise StorageUnavailable('Original role operation intent differs')
        output.append(
            {
                **dict(row),
                'fixed_input': fixed,
                'external_identity': None,
                'result_ref': result,
            }
        )
    return project_role_operation(
        {**dict(operation), 'fixed_input': fixed, 'steps': output, 'content_capture': None},
        operation['id'],
    )


def project_role_operation(data, operation_id):
    row = exact(data, OPERATION_FIELDS)
    fixed = _fixed({**row, 'fixed_input': canonical_input(row['fixed_input'])})
    key = UUID(row['idempotency_key'])
    for field in ('task_id', 'session_id', 'control_generation'):
        strict_integer(row[field], field)
    if (
        row['id'] != operation_id
        or row['operation_type'] != HANDOFF
        or row['resource_kind'] != 'TASK'
        or row['resource_id'] != row['task_id']
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
        or row['status'] not in _STATES
        or key.version != 4
        or str(key) != row['idempotency_key']
        or type(row['steps']) is not list
        or len(row['steps']) != len(STEPS)
    ):
        raise ValueError('Original role operation projection differs')
    _time(row['created_at'], nullable=False)
    _time(row['started_at'])
    _time(row['ended_at'])
    previous = True
    target = None
    for number, (step, kind, fields) in enumerate(
        zip(row['steps'], STEPS, _RESULTS, strict=True), 1
    ):
        step = exact(step, STEP_FIELDS)
        if (
            step['operation_id'] != operation_id
            or step['step_no'] != number
            or step['step_type'] != kind
            or step['status'] not in _STATES
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
            or not previous
            and step['status'] not in ('PENDING', 'CANCELLED')
        ):
            raise ValueError('Original role operation step projection differs')
        for field in ('started_at', 'ended_at', 'last_observed_at'):
            _time(step[field])
        previous = step['status'] == 'SUCCEEDED'
        if previous:
            result = exact(step['result_ref'], fields)
            for field in fields:
                strict_integer(result[field], field)
            if (
                kind == 'REVOKE'
                and (
                    result['session_id'] != row['session_id']
                    or result['control_generation'] != row['control_generation'] + 1
                )
                or kind == 'CHECK'
                and result['verification_id'] != fixed['verification_id']
                or kind == 'CREATE_SESSION'
                and result['session_id'] == row['session_id']
                or kind == 'SEND_HANDOFF'
                and result['session_id'] != target
            ):
                raise ValueError('Original role operation result scope differs')
            if kind == 'CREATE_SESSION':
                target = result['session_id']
        elif step['result_ref'] is not None:
            raise ValueError('Original role operation premature result')
    if row['status'] == 'SUCCEEDED' and not previous:
        raise ValueError('Original role operation is incomplete')
    return row
