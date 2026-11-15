"""API46 accepts and dispatches one durable reply to the original native question."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    decimal_integer,
    object_fields,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .coding_model_wait import read_task_waits
from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .task_native_issues import _current as current_native_scope
from .task_native_issues import capture_native_issues, normalize_question, observe_permission
from .task_question_answers import parse_answers, render_answers
from .task_records import record_confirmed_control
from .task_resume_runtime import _operation, _step
from .task_start import start_conflict

PATH = '/api/v1/code-tasks/{task_id}/questions/{question_id}/responses'
CAPABILITY = 'APP-CODE-CMD-C46'
KIND = 'ANSWER_QUESTION'
STEPS = operation_steps('CODING', KIND)
question_response_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class QuestionResponseRequest:
    task_id: int
    question_id: int
    expected_state_version: int
    session_id: int
    answers: list
    command: RegisteredCommand

    body_fields = ('expected_state_version', 'session_id', 'answers')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {
            'task_id': self.task_id,
            'question_id': self.question_id,
            'expected_state_version': self.expected_state_version,
            'session_id': self.session_id,
            'answers': self.answers,
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task = decimal_integer(request.path_params['task_id'], 'task_id')
        question = decimal_integer(request.path_params['question_id'], 'question_id')
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        command = registered_command(
            'POST',
            PATH.format(task_id=task, question_id=question),
            idempotency_header(request, lowercase=True),
        )
        return cls(
            task,
            question,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            strict_integer(fields['session_id'], 'session_id'),
            parse_answers(fields['answers']),
            command,
        )


def _question(connection, task_id, question_id):
    return connection.execute(
        'SELECT * FROM code_questions WHERE task_id=? AND id=?',
        (task_id, question_id),
    ).fetchone()


def _owned(question, scope):
    return (
        question['session_id'] == scope.session_id
        and question['instance_id'] == scope.instance_id
        and question['control_generation'] == scope.control_generation
    )


def _waiting(connection, task_id, question_id):
    waits = read_task_waits(connection, task_id)
    selected = [
        row for row in waits if row['kind'] == 'QUESTION' and row['source_id'] == question_id
    ]
    if len(selected) != 1:
        raise StorageUnavailable('Original question waiting item differs')
    return selected[0]['id']


def active_native_response(connection, task_id):
    rows = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type IN ('ANSWER_QUESTION','DECIDE_PERMISSION')
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
        (task_id,),
    ).fetchall()
    if len(rows) > 1:
        raise StorageUnavailable('Multiple active native responses')
    return rows[0] if rows else None


def _accept(connection, task, question, request, answers, waiting_id):
    identity = entity_id(connection, EntityKind.OPERATION_RECORD)
    at = max(operation_time(None), task['updated_at'])
    version = increment(task['state_version'])
    public_input = request.business_input()
    fixed = canonical_input(
        {
            **public_input,
            'native_answers': answers,
            'native_question_id': question['native_question_id'],
            'instance_id': question['instance_id'],
            'waiting_item_id': waiting_id,
            'actor': 'USER',
        }
    )
    if (
        connection.execute(
            """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
           AND control_generation=? AND stop_requested_at IS NULL""",
            (version, at, task['id'], task['state_version'], task['control_generation']),
        ).rowcount
        != 1
        or connection.execute(
            "UPDATE code_questions SET status='ANSWERING' WHERE id=? AND task_id=? AND status='OPEN'",
            (question['id'], task['id']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original question acceptance fence changed')
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,'ANSWER_QUESTION',?,?,?,?,'PENDING',?)""",
        (
            identity,
            task['id'],
            task['id'],
            request.session_id,
            request.idempotency_key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [(identity, number, name, fixed) for number, name in enumerate(STEPS, 1)],
    )
    return Success(
        {
            'code': 'OPERATION_ACCEPTED',
            'data': {
                'task_id': task['id'],
                'operation_id': identity,
                'operation_status': 'PENDING',
                'task_status': task['status'],
                'state_version': version,
            },
            'details': None,
        },
        202,
    )


def answer_question(runtime, request, *, available):
    require_schema(runtime)

    def accept(connection):
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        question = _question(connection, request.task_id, request.question_id)
        if task is None or question is None:
            return Rejection('NOT_FOUND', None)
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return start_conflict('TASK_ENDED', task)
        if task['status'] not in ('RUNNING', 'WAITING') or task['stop_requested_at'] is not None:
            return start_conflict('INVALID_STATE', task)
        if request.expected_state_version != task['state_version']:
            return start_conflict('VERSION_CONFLICT', task)
        if (
            request.session_id != task['active_session_id']
            or request.session_id != question['session_id']
            or question['control_generation'] != task['control_generation']
        ):
            return start_conflict('SESSION_NOT_CURRENT', task)
        previous = connection.execute(
            """SELECT id FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')
               ORDER BY id LIMIT 1""",
            (task['id'],),
        ).fetchone()
        if previous is not None:
            return start_conflict('OPERATION_CONFLICT', task, previous['id'])
        if question['status'] != 'OPEN':
            return start_conflict('QUESTION_NOT_OPEN', task)
        owner = current_native_scope(connection, task['id'])
        if owner is None or not _owned(question, owner[1]):
            return start_conflict('SESSION_NOT_CURRENT', task)
        if task['state_version'] >= MAX_SAFE_INTEGER - 3:
            return start_conflict('INVALID_STATE', task)
        if not available:
            raise ConfigurationNotReady('Q20-OC')
        original = strict_json_loads(question['questions'])
        answers = render_answers(connection, task, original, request.answers)
        if isinstance(answers, Rejection):
            return answers
        # Include the native wrapper in the same bounded control transport budget.
        if len(canonical_input({'answers': answers}).encode()) > 4 * 1024 * 1024:
            return Rejection(
                'INVALID_INPUT', {'field_errors': [{'field': 'answers', 'reason': 'RANGE'}]}
            )
        return _accept(
            connection,
            task,
            question,
            request,
            answers,
            _waiting(connection, task['id'], question['id']),
        )

    return execute_idempotent(
        runtime.commands(),
        CAPABILITY,
        request,
        accept,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def validate_question_receipt(command, data, status):
    row = exact(
        data, ('task_id', 'operation_id', 'operation_status', 'task_status', 'state_version')
    )
    for name in ('task_id', 'operation_id', 'state_version'):
        strict_integer(row[name], name)
    if (
        status != 202
        or row['task_id'] != command.route.match(command.path)['task_id']
        or row['operation_status'] != 'PENDING'
        or row['task_status'] not in ('RUNNING', 'WAITING')
    ):
        raise ValueError('Original question response receipt differs')
    return row['task_id']


def original_question_response(connection, operation):
    fixed = strict_json_object(operation['fixed_input'])
    public = {
        key: fixed[key]
        for key in ('task_id', 'question_id', 'expected_state_version', 'session_id', 'answers')
    }
    command = registered_command(
        'POST',
        PATH.format(task_id=public['task_id'], question_id=public['question_id']),
        operation['idempotency_key'],
    )
    receipt = connection.execute(
        """SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    question = _question(connection, public['task_id'], public['question_id'])
    native = fixed['native_answers']
    if (
        operation['operation_type'] != KIND
        or operation['resource_kind'] != 'TASK'
        or operation['task_id'] != public['task_id']
        or operation['resource_id'] != public['task_id']
        or operation['testing_task_id'] is not None
        or operation['session_id'] != public['session_id']
        or operation['expected_state_version'] != public['expected_state_version']
        or question is None
        or question['session_id'] != public['session_id']
        or question['control_generation'] != operation['control_generation']
        or fixed['instance_id'] != question['instance_id']
        or fixed['native_question_id'] != question['native_question_id']
        or fixed['actor'] != 'USER'
        or type(native) is not list
        or len(native) != len(public['answers'])
        or any(
            type(item) is not list or len(item) != 1 or type(item[0]) is not str or not item[0]
            for item in native
        )
        or receipt is None
        or receipt['status'] != 'SUCCEEDED'
        or receipt['business_input_json'] != canonical_input(public)
    ):
        raise StorageUnavailable('Original question response association differs')
    saved = strict_json_object(receipt['success_result_json'])
    Success(saved, receipt['http_status']).encoded()
    validate_question_receipt(command, saved['data'], receipt['http_status'])
    if (
        saved['code'] != 'OPERATION_ACCEPTED'
        or saved['data']['operation_id'] != operation['id']
        or saved['data']['state_version'] != operation['expected_state_version'] + 1
    ):
        raise StorageUnavailable('Original question response receipt differs')
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    if len(steps) != len(STEPS) or any(
        row['step_no'] != number
        or row['step_type'] != name
        or row['fixed_input'] != operation['fixed_input']
        for number, (row, name) in enumerate(zip(steps, STEPS), 1)
    ):
        raise StorageUnavailable('Original question response steps differ')
    return fixed, public, question, steps


def _current(connection, identity):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (identity,)
    ).fetchone()
    if operation is None or operation['status'] not in ('PENDING', 'RUNNING'):
        return None
    owner = current_native_scope(connection, operation['task_id'])
    if owner is None:
        return None
    fixed, _, question, steps = original_question_response(connection, operation)
    task, scope, native = owner
    if (
        not _owned(question, scope)
        or question['status'] != 'ANSWERING'
        or question['resolved_at'] is not None
        or task['state_version'] <= operation['expected_state_version']
        or _waiting(connection, task['id'], question['id']) != fixed['waiting_item_id']
    ):
        raise StorageUnavailable('Original question response fence differs')
    return task, scope, native, question, steps, fixed


def _unknown(connection, identity, question, at):
    _step(connection, identity, 2, 'UNKNOWN', at)
    _operation(connection, identity, 'UNKNOWN', at, 'EXTERNAL_RESULT_UNKNOWN')
    connection.execute(
        "UPDATE code_questions SET status='UNKNOWN' WHERE id=? AND status='ANSWERING'",
        (question['id'],),
    )


def _acknowledged(value):
    if value == {'source': 'HTTP_200'}:
        return True
    return (
        type(value) is dict
        and set(value) == {'source', 'event_id'}
        and value['source'] == 'NATIVE_EVENT'
        and type(value['event_id']) is str
        and re.fullmatch('[A-Za-z0-9_-]{1,256}', value['event_id']) is not None
    )


def _complete(connection, identity, current, at, evidence):
    task, scope, _, question, _, fixed = current
    if (
        connection.execute(
            "UPDATE code_questions SET status='RESOLVED',resolved_at=? WHERE id=? AND status='ANSWERING'",
            (at, question['id']),
        ).rowcount
        != 1
        or connection.execute(
            """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
           WHERE id=? AND task_id=? AND kind='QUESTION' AND source_id=? AND status='OPEN'""",
            (
                at,
                canonical_input({'operation_id': identity, 'outcome': 'QUESTION_ANSWERED'}),
                fixed['waiting_item_id'],
                task['id'],
                question['id'],
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original question wait changed')
    waiting = bool(read_task_waits(connection, task['id']))
    if (
        connection.execute(
            """UPDATE code_tasks SET status=?,resume_phase=?,state_version=?,updated_at=?,last_observed_at=?
           WHERE id=? AND state_version=? AND control_generation=? AND stop_requested_at IS NULL""",
            (
                'WAITING' if waiting else 'RUNNING',
                task['phase'] if waiting else None,
                increment(task['state_version']),
                at,
                at,
                task['id'],
                task['state_version'],
                task['control_generation'],
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original question completion fence changed')
    _step(connection, identity, 2, 'SUCCEEDED', at, result=evidence)
    _step(connection, identity, 3, 'SUCCEEDED', at, result={'question_id': question['id']})
    _operation(connection, identity, 'SUCCEEDED', at)
    record_confirmed_control(connection, scope, identity, '原执行会话已确认收到用户答复。', at)


def advance_question_responses(runtime, driver, *, cancelled):
    if cancelled():
        return False
    db = runtime.database
    with db.transaction() as connection:
        row = connection.execute(
            """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
               WHERE o.operation_type='ANSWER_QUESTION' AND o.status IN ('PENDING','RUNNING')
               AND t.control_generation=o.control_generation AND t.stop_requested_at IS NULL
               ORDER BY o.id LIMIT 1""",
        ).fetchone()
        current = None if row is None else _current(connection, row['id'])
    if current is None:
        return False
    identity = row['id']
    _, scope, native, question, steps, fixed = current
    if steps[1]['external_identity'] is not None:
        # A durable dispatch from a prior worker lifetime cannot be sent again.
        with db.transaction(write=True) as connection:
            current = _current(connection, identity)
            if current is None:
                return False
            _unknown(
                connection, identity, question, max(operation_time(None), current[0]['updated_at'])
            )
        return True

    def checkpoint():
        if cancelled():
            raise TaskExecutionError('ORIGINAL_QUESTION_RESPONSE_CANCELLED')
        with db.transaction() as connection:
            value = _current(connection, identity)
            if value is None or value[1] != scope:
                raise TaskExecutionError('ORIGINAL_QUESTION_RESPONSE_FENCED')

    failure = 'CONFIG_NOT_READY'
    observed = None
    try:
        if driver.session_available(scope.operation_id):
            questions, permissions = driver.observe_native_issues(scope, native, checkpoint)
            question_rows = [normalize_question(item) for item in questions]
            permission_rows = [observe_permission(item) for item in permissions]
            current_question = next(
                (
                    item
                    for item in question_rows
                    if item['native_question_id'] == question['native_question_id']
                ),
                None,
            )
            failure = (
                None
                if current_question and current_question['questions'] == question['questions']
                else 'QUESTION_NOT_OPEN'
            )
            if current_question is None or failure is None:
                observed = (question_rows, permission_rows)
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError, ValueError, TypeError, KeyError):
        pass
    with db.transaction(write=True) as connection:
        current = _current(connection, identity)
        if current is None or current[1] != scope or cancelled():
            return False
        at = max(operation_time(None), current[0]['updated_at'])
        if observed is not None:
            capture_native_issues(connection, current[0], scope, *observed, at)
        if failure is not None:
            connection.execute(
                "UPDATE code_questions SET status=? WHERE id=? AND status='ANSWERING'",
                ('UNKNOWN' if failure == 'QUESTION_NOT_OPEN' else 'OPEN', question['id']),
            )
            _step(connection, identity, 1, 'FAILED', at)
            _operation(connection, identity, 'FAILED', at, failure)
            return True
        _step(connection, identity, 1, 'SUCCEEDED', at, result={'question_id': question['id']})
        _step(
            connection,
            identity,
            2,
            'RUNNING',
            at,
            intent={'question_id': question['id'], 'session_id': scope.session_id},
        )
        _operation(connection, identity, 'RUNNING', at)
    try:
        checkpoint()
        evidence = driver.send_question_response(
            scope, native, fixed['native_question_id'], fixed['native_answers'], checkpoint
        )
        acknowledged = _acknowledged(evidence)
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError, ValueError, TypeError, KeyError):
        acknowledged = False
    with db.transaction(write=True) as connection:
        current = _current(connection, identity)
        if current is None or current[1] != scope or cancelled():
            return False
        at = max(operation_time(None), current[0]['updated_at'])
        if acknowledged:
            _complete(connection, identity, current, at, evidence)
        else:
            _unknown(connection, identity, question, at)
    return True


def retire_question_responses(
    connection, task_id, session_id, generation, *, at=None, session_scopes=None
):
    allowed = {(session_id, generation)} if session_scopes is None else set(session_scopes)
    rows = connection.execute(
        "SELECT * FROM code_operations WHERE task_id=? AND operation_type='ANSWER_QUESTION' ORDER BY id",
        (task_id,),
    ).fetchall()
    for operation in rows:
        _, _, question, steps = original_question_response(connection, operation)
        if (operation['session_id'], operation['control_generation']) not in allowed:
            raise StorageUnavailable('Original question response crosses stop scope')
        if at is None or operation['status'] not in ('PENDING', 'RUNNING'):
            continue
        if steps[1]['external_identity'] is not None:
            _unknown(connection, operation['id'], question, at)
        else:
            connection.execute(
                "UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED' WHERE id=?",
                (at, operation['id']),
            )
            connection.execute(
                "UPDATE code_questions SET status='OBSOLETE' WHERE id=? AND status='ANSWERING'",
                (question['id'],),
            )


def public_question_response(connection, operation):
    _, public, _, steps = original_question_response(connection, operation)
    sent = steps[1]
    if sent['status'] == 'SUCCEEDED' and not _acknowledged(strict_json_object(sent['result_ref'])):
        raise StorageUnavailable('Original native answer evidence differs')
    result = {
        **dict(operation),
        'fixed_input': public,
        'content_capture': None,
        'steps': [
            {
                **dict(row),
                'fixed_input': public,
                'external_identity': None if row['external_identity'] is None else {},
                'result_ref': None
                if row['step_no'] == 2 or row['result_ref'] is None
                else strict_json_object(row['result_ref']),
            }
            for row in steps
        ],
    }
    return project_question_response(result, operation['id'])


def project_question_response(value, identity):
    from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time

    row = exact(value, OPERATION_FIELDS)
    fixed = exact(
        row['fixed_input'],
        ('task_id', 'question_id', 'expected_state_version', 'session_id', 'answers'),
    )
    for name in ('task_id', 'question_id', 'expected_state_version', 'session_id'):
        strict_integer(fixed[name], name)
    parse_answers(fixed['answers'])
    strict_integer(row['control_generation'], 'control_generation')
    if (
        row['id'] != identity
        or row['resource_kind'] != 'TASK'
        or row['operation_type'] != KIND
        or row['resource_id'] != fixed['task_id']
        or row['task_id'] != fixed['task_id']
        or row['session_id'] != fixed['session_id']
        or row['expected_state_version'] != fixed['expected_state_version']
        or row['testing_task_id'] is not None
        or row['content_capture'] is not None
    ):
        raise ValueError('Original question operation projection differs')
    registered_command(
        'POST',
        PATH.format(task_id=row['task_id'], question_id=fixed['question_id']),
        row['idempotency_key'],
    )
    expected = {
        'PENDING': ('PENDING', 'PENDING', 'PENDING'),
        'RUNNING': ('SUCCEEDED', 'RUNNING', 'PENDING'),
        'UNKNOWN': ('SUCCEEDED', 'UNKNOWN', 'PENDING'),
        'FAILED': ('FAILED', 'PENDING', 'PENDING'),
        'CANCELLED': ('PENDING', 'PENDING', 'PENDING'),
        'SUCCEEDED': ('SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED'),
    }
    status = row['status']
    if status not in expected or type(row['steps']) is not list or len(row['steps']) != 3:
        raise ValueError('Original question steps differ')
    terminal = status in ('FAILED', 'CANCELLED', 'SUCCEEDED')
    untouched = status in ('PENDING', 'CANCELLED')
    created, started, ended = (row[name] for name in ('created_at', 'started_at', 'ended_at'))
    _time(created, nullable=False)
    _time(started, nullable=untouched)
    _time(ended, nullable=not terminal)
    failures = {
        'FAILED': ('QUESTION_NOT_OPEN', 'CONFIG_NOT_READY'),
        'CANCELLED': ('TASK_ENDED',),
        'UNKNOWN': ('EXTERNAL_RESULT_UNKNOWN',),
    }
    if (
        (started is None) != untouched
        or (ended is not None) != terminal
        or not created <= (started or created) <= (ended or started or created)
        or row['failure_code'] not in failures.get(status, (None,))
    ):
        raise ValueError('Original question status differs')
    for number, (raw, name, phase) in enumerate(
        zip(row['steps'], STEPS, expected[status], strict=True), 1
    ):
        step = exact(raw, STEP_FIELDS)
        complete = phase in ('SUCCEEDED', 'FAILED')
        step_started, step_ended, observed = (
            step[name] for name in ('started_at', 'ended_at', 'last_observed_at')
        )
        _time(step_started, nullable=phase == 'PENDING')
        _time(step_ended, nullable=not complete)
        _time(observed, nullable=phase == 'PENDING')
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != name
            or step['status'] != phase
            or step['fixed_input'] != fixed
            or step['external_identity'] != ({} if number == 2 and phase != 'PENDING' else None)
            or step['result_ref']
            != (
                {'question_id': fixed['question_id']}
                if phase == 'SUCCEEDED' and number != 2
                else None
            )
            or (step_started is None) != (phase == 'PENDING')
            or (observed is None) != (phase == 'PENDING')
            or (step_ended is not None) != complete
            or not created
            <= (step_started or created)
            <= (step_ended or observed or created)
            <= (observed or created)
        ):
            raise ValueError('Original question step projection differs')
    return row


class QuestionResponseReceipt:
    error_contract = 'code'
    status = 202
    success_code = 'OPERATION_ACCEPTED'
    errors = frozenset(
        {
            'INVALID_INPUT',
            'NOT_FOUND',
            'INVALID_STATE',
            'TASK_ENDED',
            'VERSION_CONFLICT',
            'OPERATION_CONFLICT',
            'OPERATION_IN_PROGRESS',
            'COMMAND_CLOSED',
            'QUESTION_NOT_OPEN',
            'SESSION_NOT_CURRENT',
            'BASIS_REF_INVALID',
            'PERMISSION_NOT_GRANTED',
            'CONFIG_NOT_READY',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        validate_question_receipt(request.command, data, 202)
        if data['state_version'] != request.expected_state_version + 1:
            raise ValueError('Original question response version differs')
        return data, None


@question_response_router.post(PATH)
async def question_response_http(request: Request):
    from .repository_registration_worker import RepositoryRegistrationWorker

    worker = getattr(request.app.state, 'walle_repository_registration', None)
    available = isinstance(worker, RepositoryRegistrationWorker) and worker.accepts_native_responses

    def invoke(runtime, parsed):
        return answer_question(runtime, parsed, available=available)

    result = await handle_http(request, QuestionResponseRequest, QuestionResponseReceipt, invoke)
    if result.status_code == 202 and available:
        worker.wake()
    return result
