"""Capture durable pending requests from a single original Coding session."""

import json

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.shared.command_execution import operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_json_object

from .native_permission_objects import permission_object_refs
from .task_start_session import original_active_session_scope

ISSUE_STATUSES = ('OPEN', 'ANSWERING', 'RESOLVED', 'REJECTED', 'UNKNOWN', 'OBSOLETE')
QUESTION_FIELDS = ('native_question_id', 'questions')
PERMISSION_FIELDS = (
    'native_permission_id',
    'tool_name',
    'patterns',
    'object_refs',
    'requested_action',
    'tool_ref',
)
_COMMON = {'id', 'sessionID', 'tool'}


def _text(value, *, nonempty=False):
    if type(value) is not str or (nonempty and not value):
        raise TaskExecutionError('ORIGINAL_NATIVE_ISSUE_TEXT_INVALID')
    return value


def _list(value):
    if type(value) is not list:
        raise TaskExecutionError('ORIGINAL_NATIVE_ISSUE_LIST_INVALID')
    return value


def _encoded_array(value):
    result = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
    )
    result.encode('utf-8', errors='strict')
    return result


def _tool(value):
    if value is None:
        return None
    row = exact(value, ('messageID', 'callID'))
    return {
        'messageID': _identifier(row['messageID'], 'msg'),
        'callID': _text(row['callID'], nonempty=True),
    }


def normalize_question(row):
    if row.keys() - (_COMMON | {'questions'}):
        raise TaskExecutionError('ORIGINAL_NATIVE_QUESTION_SHAPE_INVALID')
    _tool(row.get('tool'))
    questions = []
    for index, raw in enumerate(_list(row.get('questions'))):
        if type(raw) is not dict or raw.keys() - {
            'header',
            'question',
            'options',
            'multiple',
            'custom',
        }:
            raise TaskExecutionError('ORIGINAL_NATIVE_QUESTION_SHAPE_INVALID')
        multiple, custom = raw.get('multiple', False), raw.get('custom', True)
        if type(multiple) is not bool or type(custom) is not bool:
            raise TaskExecutionError('ORIGINAL_NATIVE_QUESTION_SHAPE_INVALID')
        options = []
        for option in _list(raw.get('options')):
            value = exact(option, ('label', 'description'))
            options.append(
                {
                    'label': _text(value['label'], nonempty=True),
                    'description': _text(value['description']),
                }
            )
        questions.append(
            {
                'index': index,
                'header': _text(raw.get('header'), nonempty=True),
                'text': _text(raw.get('question'), nonempty=True),
                'options': options,
                'multiple': multiple,
                'custom': custom,
            }
        )
    if not questions:
        raise TaskExecutionError('ORIGINAL_NATIVE_QUESTION_EMPTY')
    return {
        'native_question_id': _identifier(row['id'], 'que'),
        'questions': _encoded_array(questions),
    }


def normalize_permission(row):
    if (
        row.keys() - (_COMMON | {'permission', 'patterns', 'metadata', 'always'})
        or type(row.get('metadata')) is not dict
    ):
        raise TaskExecutionError('ORIGINAL_NATIVE_PERMISSION_SHAPE_INVALID')
    tool = _tool(row.get('tool'))
    name = _text(row.get('permission'), nonempty=True)
    patterns = [_text(value) for value in _list(row.get('patterns'))]
    for value in _list(row.get('always')):
        _text(value)
    # Only classify known native permission names. Scope remains unknown until
    # the actual object and effective grant can be verified at the action gate.
    action = {
        'read': 'READ',
        'glob': 'READ',
        'grep': 'READ',
        'list': 'READ',
        'edit': 'WRITE',
        'bash': 'EXECUTE',
        'webfetch': 'NETWORK',
        'websearch': 'NETWORK',
    }.get(name, 'UNKNOWN')
    return {
        'native_permission_id': _identifier(row['id'], 'per'),
        'tool_name': name,
        'patterns': _encoded_array(patterns),
        'object_refs': _encoded_array(permission_object_refs(row)),
        'requested_action': action,
        'tool_ref': None if tool is None else canonical_input(tool),
    }


def observe_permission(row):
    return {
        **normalize_permission(row),
        'native_observation': canonical_input(
            {'metadata': row['metadata'], 'always': row['always']}
        ),
    }


def _current(connection, task_id):
    task = connection.execute(
        """SELECT * FROM code_tasks WHERE id=? AND status IN ('RUNNING','WAITING')
           AND phase IN ('BACKEND','FRONTEND','INTEGRATION') AND stop_requested_at IS NULL""",
        (task_id,),
    ).fetchone()
    if task is None:
        return None
    session = connection.execute(
        """SELECT s.* FROM code_sessions s JOIN code_instances i ON i.id=s.instance_id AND i.task_id=s.task_id
           WHERE s.id=? AND s.task_id=? AND s.control_generation=? AND i.control_generation<=s.control_generation
           AND s.role=? AND s.status='ACTIVE' AND i.status='READY'
           AND i.workspace_id=?""",
        (
            task['active_session_id'],
            task_id,
            task['control_generation'],
            task['phase'],
            task['workspace_id'],
        ),
    ).fetchone()
    if session is None or session['model_window'] is None:
        return None
    saved = strict_json_object(session['model_window'])
    if saved['state'] not in ('OPEN', 'HELD'):
        return None
    return (
        task,
        original_active_session_scope(connection, task, session),
        session['native_session_id'],
    )


def _has_response_intent(connection, task_id, response, issue_id):
    if response == 'ANSWER_QUESTION':
        return (
            connection.execute(
                """SELECT 1 FROM code_operations WHERE task_id=? AND operation_type=?
               AND json_extract(fixed_input,'$.question_id')=? LIMIT 1""",
                (task_id, response, issue_id),
            ).fetchone()
            is not None
        )
    return (
        connection.execute(
            """SELECT 1 FROM code_operations o
           JOIN code_operation_steps read ON read.operation_id=o.id AND read.step_no=1
           JOIN code_operation_steps send ON send.operation_id=o.id AND send.step_no=2
           JOIN json_each(read.result_ref,'$.items') item
           WHERE o.task_id=? AND o.operation_type=? AND send.external_identity IS NOT NULL
           AND json_extract(item.value,'$.permission_id')=? LIMIT 1""",
            (task_id, response, issue_id),
        ).fetchone()
        is not None
    )


def _capture(connection, task, scope, rows, kind, at):
    if kind == 'QUESTION':
        table, fields, entity = 'code_questions', QUESTION_FIELDS, EntityKind.NATIVE_QUESTION
        response = 'ANSWER_QUESTION'
    else:
        table = 'code_permissions'
        fields = PERMISSION_FIELDS + ('native_observation',)
        entity = EntityKind.NATIVE_PERMISSION
        response = 'DECIDE_PERMISSION'
    previous = connection.execute(
        f'SELECT * FROM {table} WHERE task_id=? AND instance_id=? AND session_id=? AND control_generation=?',
        (task['id'], scope.instance_id, scope.session_id, scope.control_generation),
    )
    known = {row[fields[0]]: row for row in previous}
    observed = set()
    inserted = 0
    for row in rows:
        native_id = row[fields[0]]
        if native_id in observed:
            raise StorageUnavailable('Original native issue list repeats an identity')
        observed.add(native_id)
        prior = known.get(native_id)
        if prior is not None:
            comparable = fields
            if kind == 'PERMISSION' and prior['object_refs'] == '[]':
                # Earlier reads may have saved the raw pattern without its typed object.
                # Those records remain read-only for ALLOW_ONCE.
                comparable = tuple(name for name in fields if name != 'object_refs')
            if kind == 'PERMISSION' and prior['native_observation'] is None:
                comparable = tuple(name for name in comparable if name != 'native_observation')
            if any(prior[name] != row[name] for name in comparable):
                raise StorageUnavailable('Original native issue payload changed')
            if prior['status'] == 'UNKNOWN' and not _has_response_intent(
                connection, task['id'], response, prior['id']
            ):
                connection.execute(
                    f"UPDATE {table} SET status='OPEN' WHERE id=? AND status='UNKNOWN'",
                    (prior['id'],),
                )
            continue
        issue_id = entity_id(connection, entity)
        waiting_id = entity_id(connection, EntityKind.WAITING_ITEM)
        columns = ','.join(fields)
        values = ','.join('?' for _ in fields)
        connection.execute(
            f"""INSERT INTO {table}(id,task_id,session_id,instance_id,control_generation,{columns},status,observed_at)
                VALUES(?,?,?,?,?,{values},'OPEN',?)""",
            (
                issue_id,
                task['id'],
                scope.session_id,
                scope.instance_id,
                scope.control_generation,
                *(row[field] for field in fields),
                at,
            ),
        )
        connection.execute(
            """INSERT INTO code_waiting_items(id,task_id,kind,source_kind,source_id,resume_phase,status,created_at)
               VALUES(?,?,?,?,?,?,'OPEN',?)""",
            (waiting_id, task['id'], kind, kind, issue_id, task['phase'], at),
        )
        inserted += 1
    for native_id, prior in known.items():
        if prior['status'] == 'OPEN' and native_id not in observed:
            connection.execute(
                f"UPDATE {table} SET status='UNKNOWN' WHERE id=? AND status='OPEN'", (prior['id'],)
            )
    return inserted


def retire_native_issues(connection, task_id):
    for table in ('code_questions', 'code_permissions'):
        connection.execute(
            f"UPDATE {table} SET status='OBSOLETE' WHERE task_id=? AND status='OPEN'",
            (task_id,),
        )


def capture_native_issues(connection, task, scope, question_rows, permission_rows, at):
    new_questions = _capture(connection, task, scope, question_rows, 'QUESTION', at)
    new_permissions = _capture(connection, task, scope, permission_rows, 'PERMISSION', at)
    if not new_questions and not new_permissions:
        return
    changed = connection.execute(
        """UPDATE code_tasks SET status='WAITING',resume_phase=phase,state_version=?,
           updated_at=?,last_observed_at=? WHERE id=? AND control_generation=? AND state_version=?
           AND stop_requested_at IS NULL AND status IN ('RUNNING','WAITING')""",
        (
            increment(task['state_version']),
            at,
            at,
            task['id'],
            task['control_generation'],
            task['state_version'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original native issue task fence changed')


def advance_native_issue_observation(runtime, driver, cursor, *, cancelled):
    if cancelled():
        return cursor
    db = runtime.database
    with db.transaction() as connection:
        candidate = connection.execute(
            """SELECT id FROM code_tasks WHERE status IN ('RUNNING','WAITING') AND phase IN ('BACKEND','FRONTEND','INTEGRATION')
               AND active_session_id IS NOT NULL AND stop_requested_at IS NULL
               ORDER BY (id<=?),id LIMIT 1""",
            (cursor,),
        ).fetchone()
        if candidate is None:
            return 0
        identity = candidate['id']
        original = _current(connection, identity)
    if original is None:
        return identity
    _, scope, native = original
    if not driver.session_available(scope.operation_id):
        return identity

    def checkpoint():
        if cancelled():
            raise TaskExecutionError('ORIGINAL_TASK_ISSUE_OBSERVATION_CANCELLED')
        with db.transaction() as connection:
            current = _current(connection, identity)
            if current is None or current[1:] != (scope, native):
                raise TaskExecutionError('ORIGINAL_TASK_ISSUE_OBSERVATION_FENCED')

    try:
        questions, permissions = driver.observe_native_issues(
            scope,
            native,
            checkpoint,
        )
        question_rows = [normalize_question(row) for row in questions]
        permission_rows = [observe_permission(row) for row in permissions]
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError, ValueError, TypeError, KeyError):
        # Transport or shape failures cannot remove or resolve a prior request.
        return identity
    with db.transaction(write=True) as connection:
        current = _current(connection, identity)
        if current is None or current[1:] != (scope, native) or cancelled():
            return identity
        task, _, _ = current
        at = max(operation_time(None), task['updated_at'])
        capture_native_issues(connection, task, scope, question_rows, permission_rows, at)
    return identity
