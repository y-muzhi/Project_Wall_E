"""Close one original model window and record the reason in its task transaction."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.shared.command_execution import operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_enum, strict_integer, strict_json_object

from .repository_operations import _time
from .task_model_ingress import read_original_open_window

_FIELDS = (
    'id',
    'task_id',
    'testing_task_id',
    'kind',
    'source_kind',
    'source_id',
    'resume_phase',
    'status',
    'created_at',
    'resolved_at',
    'resolution_ref',
)


def hold_coding_model(connection, window, credential_ref, *, kind, llm_use_id=None):
    require_write_transaction(connection)
    if read_original_open_window(connection, window, credential_ref) != window:
        return
    if kind not in ('BUDGET', 'MODEL_RESULT') or (kind == 'MODEL_RESULT' and llm_use_id is None):
        raise StorageUnavailable('Original model wait kind differs')
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (window.task_id,)).fetchone()
    if (
        task['status'] != 'RUNNING'
        or task['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
        or task['stop_requested_at'] is not None
    ):
        raise StorageUnavailable('Original model wait task differs')
    session = connection.execute(
        'SELECT model_window FROM code_sessions WHERE id=?', (window.execution_session_id,)
    ).fetchone()
    value = strict_json_object(session['model_window'])
    value['state'] = 'HELD'
    at = max(operation_time(None), task['updated_at'])
    source_kind = 'OPERATION' if llm_use_id is None else 'LLM_USE'
    source_id = window.operation_id if llm_use_id is None else llm_use_id
    waiting = entity_id(connection, EntityKind.WAITING_ITEM)
    connection.execute(
        """INSERT INTO code_waiting_items(id,task_id,kind,source_kind,source_id,resume_phase,status,created_at)
           VALUES(?,?,?,?,?,?,'OPEN',?)""",
        (waiting, window.task_id, kind, source_kind, source_id, task['phase'], at),
    )
    connection.execute(
        'UPDATE code_sessions SET model_window=?,last_observed_at=? WHERE id=?',
        (canonical_input(value), at, window.execution_session_id),
    )
    if (
        connection.execute(
            """UPDATE code_tasks SET status='WAITING',resume_phase=phase,state_version=?,
           updated_at=?,last_observed_at=? WHERE id=? AND status='RUNNING' AND control_generation=?
           AND state_version=? AND stop_requested_at IS NULL""",
            (
                increment(task['state_version']),
                at,
                at,
                window.task_id,
                window.generation,
                task['state_version'],
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original model wait lost the task fence')


def read_task_waits(connection, task_id):
    rows = connection.execute(
        """SELECT w.*,o.id AS operation_owner,u.id AS call_owner,q.id AS question_owner,p.id AS permission_owner,d.id AS delivery_owner
           FROM code_waiting_items w
           LEFT JOIN code_operations o ON w.source_kind='OPERATION' AND o.id=w.source_id AND o.task_id=w.task_id
           LEFT JOIN llm_uses u ON w.source_kind='LLM_USE' AND u.id=w.source_id
             AND EXISTS(SELECT 1 FROM code_sessions s WHERE s.id=u.execution_session_id AND s.task_id=w.task_id)
           LEFT JOIN code_questions q ON w.source_kind='QUESTION' AND q.id=w.source_id AND q.task_id=w.task_id
           LEFT JOIN code_permissions p ON w.source_kind='PERMISSION' AND p.id=w.source_id AND p.task_id=w.task_id
           LEFT JOIN code_deliveries d ON w.source_kind='DELIVERY' AND d.id=w.source_id AND d.task_id=w.task_id
           WHERE w.task_id=? AND w.status='OPEN' ORDER BY w.created_at,w.id""",
        (task_id,),
    ).fetchall()
    result = []
    for row in rows:
        if row['source_id'] not in (
            row['operation_owner'],
            row['call_owner'],
            row['question_owner'],
            row['permission_owner'],
            row['delivery_owner'],
        ):
            raise StorageUnavailable('Original model wait source differs')
        result.append(project_task_wait({key: row[key] for key in _FIELDS}, task_id))
    return result


def project_task_wait(value, task_id):
    row = exact(value, _FIELDS)
    strict_integer(row['id'], 'waiting_item_id')
    strict_integer(row['source_id'], 'waiting_source_id')
    strict_enum(
        row['kind'],
        'kind',
        (
            'BUDGET',
            'MODEL_RESULT',
            'QUESTION',
            'PERMISSION',
            'OPERATION_RESULT',
            'DELIVERY_RESULT',
            'CONFIGURATION',
        ),
    )
    strict_enum(
        row['source_kind'],
        'source_kind',
        ('OPERATION', 'LLM_USE', 'QUESTION', 'PERMISSION', 'DELIVERY'),
    )
    _time(row['created_at'], nullable=False)
    if (
        row['task_id'] != task_id
        or row['testing_task_id'] is not None
        or row['resume_phase']
        not in (
            ('DELIVERY',)
            if row['kind'] == 'DELIVERY_RESULT'
            else ('BACKEND', 'FRONTEND', 'INTEGRATION')
        )
        or row['status'] != 'OPEN'
        or row['resolved_at'] is not None
        or row['resolution_ref'] is not None
        or row['source_kind']
        not in {
            'MODEL_RESULT': ('LLM_USE',),
            'OPERATION_RESULT': ('OPERATION',),
            'CONFIGURATION': ('OPERATION',),
            'BUDGET': ('LLM_USE', 'OPERATION'),
            'QUESTION': ('QUESTION',),
            'PERMISSION': ('PERMISSION',),
            'DELIVERY_RESULT': ('DELIVERY',),
        }[row['kind']]
    ):
        raise ValueError('Original model wait projection differs')
    return row


def close_task_waits_after_stop(connection, task_id, operation_id, at):
    # Completion retires the task block, while any separate cost dispute stays recorded.
    read_task_waits(connection, task_id)
    connection.execute(
        """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
           WHERE task_id=? AND status='OPEN'""",
        (
            at,
            canonical_input({'operation_id': operation_id, 'outcome': 'TASK_TERMINATED'}),
            task_id,
        ),
    )
