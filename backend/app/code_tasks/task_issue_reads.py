"""Read the original persisted question and permission observations (API44/45)."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    strict_enum,
    strict_integer,
    strict_json_loads,
)

from .configuration_identities import require_schema
from .repository_operations import _time
from .repository_reads import ERRORS
from .native_permission_objects import usable_workspace_refs
from .task_permission_response import permission_granted
from .task_native_issues import ISSUE_STATUSES, PERMISSION_FIELDS, QUESTION_FIELDS
from .task_read_query import read_task_query

BASE = '/api/v1/code-tasks/{task_id}'
issue_read_router = APIRouter(redirect_slashes=False)
COMMON = (
    'id',
    'task_id',
    'session_id',
    'instance_id',
    'control_generation',
    'status',
    'observed_at',
    'resolved_at',
)
ACTIONS = {
    'QUESTION': ('ANSWER_QUESTION', 'PREPARE_HANDOFF'),
    'PERMISSION': ('ALLOW_ONCE', 'DENY'),
}


@dataclass(frozen=True)
class IssuePage:
    task_id: int
    page: int
    status: str | None

    @classmethod
    def parse(cls, request):
        query = read_task_query(request, singles=('page', 'status'))
        status = query.get('status')
        if status is not None:
            strict_enum(status, 'status', ISSUE_STATUSES)
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(query.get('page', '1'), 'page', maximum=MAX_PAGE),
            status,
        )


def _reason(row, task):
    if task['status'] == 'TERMINATED' or task['status'] == 'COMPLETED':
        return 'TASK_ENDED'
    if task['status'] == 'STOPPING':
        return 'INVALID_STATE'
    if (
        row['session_id'] != task['active_session_id']
        or row['control_generation'] != task['control_generation']
    ):
        return 'SESSION_NOT_CURRENT'
    if row['status'] in ('UNKNOWN', 'ANSWERING'):
        return 'EXTERNAL_RESULT_UNKNOWN'
    if row['status'] != 'OPEN':
        return 'QUESTION_NOT_OPEN'
    # Response acceptance and explicit user authority are separate capabilities.
    return 'CONFIG_NOT_READY'


def _rows(connection, task, request, kind, *, answer_ready):
    table = 'code_questions' if kind == 'QUESTION' else 'code_permissions'
    args = (request.task_id,)
    where = f'FROM {table} WHERE task_id=?'
    if request.status is not None:
        where += ' AND status=?'
        args += (request.status,)
    count = connection.execute('SELECT count(*) ' + where, args).fetchone()[0]
    active = connection.execute(
        "SELECT 1 FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1",
        (task['id'],),
    ).fetchone()
    output = []
    for row in connection.execute(
        'SELECT * ' + where + ' ORDER BY observed_at DESC,id DESC LIMIT ? OFFSET ?',
        (*args, PAGE_SIZE, page_offset(request.page)),
    ):
        output.append(
            project_stored_issue(
                connection,
                task,
                row,
                kind,
                answer_ready=answer_ready,
                control_busy=active is not None,
            )
        )
    return {**page_metadata(request.page, count), 'items': output}


def project_stored_issue(connection, task, row, kind, *, answer_ready, control_busy=None):
    if control_busy is None:
        control_busy = (
            connection.execute(
                "SELECT 1 FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1",
                (task['id'],),
            ).fetchone()
            is not None
        )
    session = connection.execute(
        """SELECT s.task_id,s.instance_id,s.control_generation FROM code_sessions s
           JOIN code_instances i ON i.id=s.instance_id AND i.task_id=s.task_id
           AND i.control_generation<=s.control_generation WHERE s.id=?""",
        (row['session_id'],),
    ).fetchone()
    if session is None or any(
        session[key] != row[key] for key in ('task_id', 'instance_id', 'control_generation')
    ):
        raise StorageUnavailable('Original native issue owner differs')
    fields = QUESTION_FIELDS if kind == 'QUESTION' else PERMISSION_FIELDS
    result = {key: row[key] for key in COMMON + fields}
    json_fields = ('questions',) if kind == 'QUESTION' else ('patterns', 'object_refs', 'tool_ref')
    for key in json_fields:
        result[key] = None if result[key] is None else strict_json_loads(result[key])
    if kind == 'QUESTION':
        result['handoffs'] = [
            dict(handoff)
            for handoff in connection.execute(
                """SELECT h.id,h.target_document_id,h.created_at FROM code_question_handoffs h
                   JOIN requirement_documents d ON d.id=h.target_document_id AND d.requirement_id=?
                   WHERE h.question_id=? AND h.task_id=? ORDER BY h.created_at,h.id""",
                (task['requirement_id'], row['id'], task['id']),
            )
        ]
    reason = _reason(row, task)
    result['available_actions'] = []
    for action in ACTIONS[kind]:
        disabled = reason
        if reason == 'CONFIG_NOT_READY' and (answer_ready or action == 'PREPARE_HANDOFF'):
            if control_busy:
                disabled = 'OPERATION_IN_PROGRESS'
            elif action == 'ALLOW_ONCE' and not permission_granted(connection, task, row):
                disabled = 'PERMISSION_NOT_GRANTED'
            else:
                disabled = None
        result['available_actions'].append(
            {
                'action': action,
                'enabled': disabled is None,
                'reason_code': disabled,
                'related_id': row['id'],
            }
        )
    return result


def _read(runtime, request, kind, *, answer_ready=False):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        return {
            'code': 'READ_OK',
            'data': _rows(connection, task, request, kind, answer_ready=answer_ready),
            'details': None,
        }


def _text(value, *, nonempty=False):
    if type(value) is not str or (nonempty and not value):
        raise ValueError('Original native issue text differs')


def _project(value, request, kind):
    fields = QUESTION_FIELDS + ('handoffs',) if kind == 'QUESTION' else PERMISSION_FIELDS
    row = exact(value, COMMON + fields + ('available_actions',))
    for field in ('id', 'task_id', 'session_id', 'instance_id', 'control_generation'):
        strict_integer(row[field], field)
    strict_enum(row['status'], 'status', ISSUE_STATUSES)
    _time(row['observed_at'], nullable=False)
    _time(row['resolved_at'])
    if (
        row['task_id'] != request.task_id
        or (request.status is not None and row['status'] != request.status)
        or (row['resolved_at'] is not None and row['resolved_at'] < row['observed_at'])
    ):
        raise ValueError('Original native issue projection differs')
    if kind == 'QUESTION':
        _identifier(row['native_question_id'], 'que')
        if (
            type(row['questions']) is not list
            or not row['questions']
            or type(row['handoffs']) is not list
        ):
            raise ValueError('Original native question is unavailable')
        for index, item in enumerate(row['questions']):
            question = exact(item, ('index', 'header', 'text', 'options', 'multiple', 'custom'))
            if (
                type(question['index']) is not int
                or question['index'] != index
                or type(question['options']) is not list
            ):
                raise ValueError('Original native question item differs')
            if any(type(question[key]) is not bool for key in ('multiple', 'custom')):
                raise ValueError('Original native question flags differ')
            _text(question['header'], nonempty=True)
            _text(question['text'], nonempty=True)
            for item in question['options']:
                option = exact(item, ('label', 'description'))
                _text(option['label'], nonempty=True)
                _text(option['description'])
        for value in row['handoffs']:
            handoff = exact(value, ('id', 'target_document_id', 'created_at'))
            strict_integer(handoff['id'], 'handoff_id')
            strict_integer(handoff['target_document_id'], 'target_document_id')
            _time(handoff['created_at'], nullable=False)
    else:
        _identifier(row['native_permission_id'], 'per')
        _text(row['tool_name'], nonempty=True)
        strict_enum(
            row['requested_action'],
            'requested_action',
            ('READ', 'WRITE', 'EXECUTE', 'NETWORK', 'UNKNOWN'),
        )
        if type(row['patterns']) is not list or (
            row['object_refs'] != [] and not usable_workspace_refs(row['object_refs'])
        ):
            raise ValueError('Original native permission scope differs')
        for pattern in row['patterns']:
            _text(pattern)
        if row['tool_ref'] is not None:
            tool = exact(row['tool_ref'], ('messageID', 'callID'))
            _identifier(tool['messageID'], 'msg')
            _text(tool['callID'], nonempty=True)
    actions = row['available_actions']
    if type(actions) is not list or len(actions) != len(ACTIONS[kind]):
        raise ValueError('Original native issue actions differ')
    for raw, name in zip(actions, ACTIONS[kind]):
        action = exact(raw, ('action', 'enabled', 'reason_code', 'related_id'))
        if (
            action['action'] != name
            or type(action['enabled']) is not bool
            or action['enabled'] != (action['reason_code'] is None)
            or (action['enabled'] and row['status'] != 'OPEN')
            or action['related_id'] != row['id']
            or action['reason_code']
            not in (
                'TASK_ENDED',
                'INVALID_STATE',
                'SESSION_NOT_CURRENT',
                'EXTERNAL_RESULT_UNKNOWN',
                'QUESTION_NOT_OPEN',
                'CONFIG_NOT_READY',
                'OPERATION_IN_PROGRESS',
                'PERMISSION_NOT_GRANTED',
                None,
            )
        ):
            raise ValueError('Original native issue action differs')
    return row


class QuestionPage:
    error_contract = 'code'
    errors = ERRORS
    kind = 'QUESTION'

    @classmethod
    def project(cls, data, request):
        result, metadata = page(data, lambda row: _project(row, request, cls.kind), request.page)
        keys = [(row['observed_at'], row['id']) for row in result['items']]
        if any(left <= right for left, right in zip(keys, keys[1:])):
            raise ValueError('Original native issue history order differs')
        return result, metadata


class PermissionPage(QuestionPage):
    kind = 'PERMISSION'


@issue_read_router.get(BASE + '/questions')
async def questions_http(request: Request):
    from .repository_registration_worker import RepositoryRegistrationWorker

    worker = getattr(request.app.state, 'walle_repository_registration', None)
    ready = isinstance(worker, RepositoryRegistrationWorker) and worker.accepts_native_responses
    return await handle_http(
        request,
        IssuePage,
        QuestionPage,
        lambda runtime, parsed: _read(runtime, parsed, 'QUESTION', answer_ready=ready),
    )


@issue_read_router.get(BASE + '/permissions')
async def permissions_http(request: Request):
    from .repository_registration_worker import RepositoryRegistrationWorker

    worker = getattr(request.app.state, 'walle_repository_registration', None)
    ready = isinstance(worker, RepositoryRegistrationWorker) and worker.accepts_native_responses
    return await handle_http(
        request,
        IssuePage,
        PermissionPage,
        lambda runtime, parsed: _read(runtime, parsed, 'PERMISSION', answer_ready=ready),
    )
