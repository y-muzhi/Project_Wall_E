"""Document handoff facts without modifying the source question or document."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    decimal_integer,
    object_fields,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .command_registry import RegisteredCommand, registered_command
from .configuration_identities import require_schema
from .operation_protocol import operation_steps
from .repository_operations import OPERATION_FIELDS, STEP_FIELDS, _time
from .repository_reads import ERRORS
from .task_basis import read_task_basis
from .task_issue_reads import _project as project_issue
from .task_issue_reads import project_stored_issue
from .task_question_answers import EVIDENCE, EVIDENCE_FIELDS, _refs
from .task_read_query import read_task_query
from .task_start import start_conflict

BASE = '/api/v1/code-tasks/{task_id}'
PREPARE = BASE + '/questions/{question_id}/handoff'
DETAIL = BASE + '/handoffs/{handoff_id}'
LINK = DETAIL + '/links'
KINDS = ('DISCUSSION_LINKED', 'REVISION_LINKED', 'ABANDONED')
TYPE = 'PREPARE_HANDOFF'
STEPS = operation_steps('CODING', TYPE)
EVENT_REFS = ('guide_run_id', 'message_id', 'revision_id')
HANDOFF_FIELDS = (
    'id',
    'task_id',
    'question_id',
    'target_document_id',
    'operation_id',
    'created_at',
)
EVENT_FIELDS = ('id', 'handoff_id', 'kind', *EVENT_REFS, 'created_at')
handoff_router = APIRouter(redirect_slashes=False)


def parse_evidence(value):
    rows = _refs(value, 'evidence_refs', EVIDENCE_FIELDS)
    for row in rows:
        strict_enum(row['kind'], 'evidence_refs.kind', EVIDENCE)
        strict_integer(row['id'], 'evidence_refs.id')
    return rows


def _path(request, name):
    return decimal_integer(request.path_params[name], name)


def _references(fields, kind):
    refs = tuple(
        strict_integer(fields[key], key) if fields[key] is not None else None for key in EVENT_REFS
    )
    run, message, revision = refs
    if (
        (kind == 'DISCUSSION_LINKED' and run is None and message is None)
        or (kind == 'REVISION_LINKED' and revision is None)
        or (kind in ('PREPARED', 'ABANDONED') and any(ref is not None for ref in refs))
    ):
        from backend.app.shared.validation import reject

        reject('kind', 'INVALID_FORMAT', '移交事件与已有结果引用不匹配')
    return refs


@dataclass(frozen=True)
class HandoffCommand:
    task_id: int
    subject_id: int
    expected_state_version: int
    fields: dict
    command: RegisteredCommand

    body_fields = (
        'expected_state_version',
        'target_document_id',
        'evidence_refs',
        'kind',
        *EVENT_REFS,
    )

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        subject = 'question_id' if self.command.path.endswith('/handoff') else 'handoff_id'
        return {
            'task_id': self.task_id,
            subject: self.subject_id,
            'expected_state_version': self.expected_state_version,
            **self.fields,
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        task = _path(request, 'task_id')
        if 'question_id' in request.path_params:
            subject = _path(request, 'question_id')
            path = PREPARE.format(task_id=task, question_id=subject)
            fields = ('expected_state_version', 'target_document_id', 'evidence_refs')
            raw = object_fields(body, 'body', fields, fields)
            value = {
                'target_document_id': strict_integer(
                    raw['target_document_id'], 'target_document_id'
                ),
                'evidence_refs': parse_evidence(raw['evidence_refs']),
            }
        else:
            subject = _path(request, 'handoff_id')
            path = LINK.format(task_id=task, handoff_id=subject)
            fields = ('expected_state_version', 'kind', *EVENT_REFS)
            raw = object_fields(body, 'body', fields, fields)
            kind = strict_enum(raw['kind'], 'kind', KINDS)
            value = {'kind': kind, **dict(zip(EVENT_REFS, _references(raw, kind), strict=True))}
        return cls(
            task,
            subject,
            strict_integer(raw['expected_state_version'], 'expected_state_version'),
            value,
            registered_command('POST', path, idempotency_header(request, lowercase=True)),
        )


def _invalid(field):
    return Rejection('INVALID_INPUT', {'field_errors': [{'field': field, 'reason': 'RELATION'}]})


def _task(connection, task_id):
    return connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()


def _document(connection, task, identity):
    return connection.execute(
        """SELECT * FROM requirement_documents WHERE id=? AND requirement_id=?
           AND document_type='CURRENT'""",
        (identity, task['requirement_id']),
    ).fetchone()


def _source(connection, task, identity):
    return connection.execute(
        'SELECT * FROM code_questions WHERE id=? AND task_id=?', (identity, task['id'])
    ).fetchone()


def _handoff(connection, task, identity):
    return connection.execute(
        'SELECT * FROM code_question_handoffs WHERE id=? AND task_id=?', (identity, task['id'])
    ).fetchone()


def _write_conflict(connection, task, request):
    if task['status'] in ('COMPLETED', 'TERMINATED'):
        return start_conflict('TASK_ENDED', task)
    if task['status'] == 'STOPPING' or task['stop_requested_at'] is not None:
        return start_conflict('INVALID_STATE', task)
    if task['state_version'] != request.expected_state_version:
        return start_conflict('VERSION_CONFLICT', task)
    if task['state_version'] == MAX_SAFE_INTEGER:
        return start_conflict('INVALID_STATE', task)
    pending = connection.execute(
        """SELECT id FROM code_operations WHERE task_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')
           ORDER BY id LIMIT 1""",
        (task['id'],),
    ).fetchone()
    return None if pending is None else start_conflict('OPERATION_CONFLICT', task, pending['id'])


def _version(connection, task, at):
    if (
        connection.execute(
            """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=?
           AND state_version=? AND control_generation=? AND stop_requested_at IS NULL""",
            (
                increment(task['state_version']),
                at,
                task['id'],
                task['state_version'],
                task['control_generation'],
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original handoff version changed')


def _event(connection, handoff, kind, refs, at):
    identity = entity_id(connection, EntityKind.QUESTION_HANDOFF_EVENT)
    connection.execute(
        """INSERT INTO code_question_handoff_events
           (id,handoff_id,kind,guide_run_id,message_id,revision_id,created_at) VALUES(?,?,?,?,?,?,?)""",
        (identity, handoff, kind, *refs, at),
    )
    return identity


def _created(data):
    return Success({'code': 'CREATED', 'data': data, 'details': None}, 201)


def _prepare(connection, task, request):
    question = _source(connection, task, request.subject_id)
    document = _document(connection, task, request.fields['target_document_id'])
    if question is None or document is None or document['archived_at'] is not None:
        return Rejection('NOT_FOUND', None)
    conflict = _write_conflict(connection, task, request)
    if conflict is not None:
        return conflict
    if task['status'] not in ('RUNNING', 'WAITING'):
        return start_conflict('INVALID_STATE', task)
    if (
        task['active_session_id'] != question['session_id']
        or task['control_generation'] != question['control_generation']
    ):
        return start_conflict('SESSION_NOT_CURRENT', task)
    if question['status'] != 'OPEN':
        return start_conflict('QUESTION_NOT_OPEN', task)
    for ref in request.fields['evidence_refs']:
        if connection.execute(EVIDENCE[ref['kind']], (task['id'], ref['id'])).fetchone() is None:
            return _invalid('evidence_refs')
    materials, _ = read_task_basis(connection, task)
    basis = [
        {'document_id': task['document_id'], 'revision_id': task['design_revision_id']},
        *materials,
    ]
    fixed = canonical_input({**request.business_input(), 'fixed_basis': basis})
    handoff = entity_id(connection, EntityKind.QUESTION_HANDOFF)
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    at = max(operation_time(None), task['updated_at'])
    _version(connection, task, at)
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at,ended_at)
           VALUES(?,?,'TASK',?,?,'PREPARE_HANDOFF',?,?,?,?,'SUCCEEDED',?,?,?)""",
        (
            operation,
            task['id'],
            task['id'],
            question['session_id'],
            request.idempotency_key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
            at,
            at,
        ),
    )
    connection.execute(
        """INSERT INTO code_question_handoffs(id,task_id,question_id,target_document_id,operation_id,created_at)
           VALUES(?,?,?,?,?,?)""",
        (handoff, task['id'], question['id'], document['id'], operation, at),
    )
    event = _event(connection, handoff, 'PREPARED', (None, None, None), at)
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,result_ref,
           started_at,ended_at,last_observed_at) VALUES(?,?,?,'SUCCEEDED',?,?,?,?,?)""",
        (
            (operation, number, step, fixed, canonical_input(result), at, at, at)
            for number, (step, result) in enumerate(
                zip(
                    STEPS,
                    (
                        {'question_id': question['id']},
                        {'handoff_id': handoff, 'handoff_event_id': event},
                    ),
                    strict=True,
                ),
                1,
            )
        ),
    )
    return _created(
        {
            'handoff_id': handoff,
            'task_id': task['id'],
            'question_id': question['id'],
            'target_document_id': document['id'],
        }
    )


def _owned_results(connection, task, handoff, fields):
    document = handoff['target_document_id']
    run = message = None
    tables = ('guide_runs', 'conversation_messages', 'revisions')
    for name, table in zip(EVENT_REFS, tables, strict=True):
        if fields[name] is None:
            continue
        item = connection.execute(
            f'SELECT * FROM {table} WHERE id=? AND document_id=? AND requirement_id=?',
            (fields[name], document, task['requirement_id']),
        ).fetchone()
        if item is None:
            return name
        if name == 'guide_run_id':
            run = item
        elif name == 'message_id':
            message = item
    if (
        run is not None
        and message is not None
        and (message['guide_run_id'] != run['id'] and run['trigger_message_id'] != message['id'])
    ):
        return 'message_id'
    return None


def _link(connection, task, request):
    handoff = _handoff(connection, task, request.subject_id)
    if handoff is None or _document(connection, task, handoff['target_document_id']) is None:
        return Rejection('NOT_FOUND', None)
    conflict = _write_conflict(connection, task, request)
    if conflict is not None:
        return conflict
    invalid = _owned_results(connection, task, handoff, request.fields)
    if invalid is not None:
        return _invalid(invalid)
    at = max(operation_time(None), task['updated_at'])
    _version(connection, task, at)
    event = _event(
        connection,
        handoff['id'],
        request.fields['kind'],
        tuple(request.fields[key] for key in EVENT_REFS),
        at,
    )
    return _created({'handoff_event_id': event, 'handoff_id': handoff['id']})


def write_handoff(runtime, request):
    require_schema(runtime)
    prepare = request.command.route.capability_id == 'APP-CODE-CMD-C48'

    def write(connection):
        task = _task(connection, request.task_id)
        if task is None:
            return Rejection('NOT_FOUND', None)
        return _prepare(connection, task, request) if prepare else _link(connection, task, request)

    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        write,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def validate_handoff_receipt(command, value, status):
    scope = command.route.match(command.path)
    if status != 201:
        raise ValueError('Original handoff receipt differs')
    prepare = command.route.capability_id == 'APP-CODE-CMD-C48'
    fields = (
        ('handoff_id', 'task_id', 'question_id', 'target_document_id')
        if prepare
        else (
            'handoff_event_id',
            'handoff_id',
        )
    )
    data = exact(value, fields)
    for name in fields:
        strict_integer(data[name], name)
    if (
        prepare
        and (data['task_id'] != scope['task_id'] or data['question_id'] != scope['question_id'])
    ) or (not prepare and data['handoff_id'] != scope['handoff_id']):
        raise ValueError('Original handoff receipt owner differs')
    return scope['task_id']


class HandoffReceipt:
    error_contract = 'code'
    success_code = 'CREATED'
    status = 201
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
            'PERMISSION_NOT_GRANTED',
            'STORAGE_UNAVAILABLE',
            'INTERNAL_ERROR',
        }
    )

    @staticmethod
    def project(data, request):
        validate_handoff_receipt(request.command, data, 201)
        if request.command.route.capability_id == 'APP-CODE-CMD-C48' and (
            data['target_document_id'] != request.fields['target_document_id']
        ):
            raise ValueError('Original handoff target differs')
        return data, None


@dataclass(frozen=True)
class HandoffPage:
    task_id: int
    handoff_id: int
    page: int
    status = None

    @classmethod
    def parse(cls, request):
        query = read_task_query(request, singles=('page',))
        return cls(
            _path(request, 'task_id'),
            _path(request, 'handoff_id'),
            decimal_integer(query.get('page', '1'), 'page', maximum=MAX_PAGE),
        )


def _event_view(value, handoff_id):
    data = exact(value, EVENT_FIELDS)
    strict_integer(data['id'], 'handoff_event_id')
    if data['handoff_id'] != handoff_id:
        raise ValueError('Original handoff event owner differs')
    _time(data['created_at'], nullable=False)
    kind = strict_enum(data['kind'], 'kind', ('PREPARED', *KINDS))
    _references(data, kind)
    return data


class HandoffView:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        data = exact(value, (*HANDOFF_FIELDS, 'source_question', 'evidence_refs', 'event_page'))
        for name in HANDOFF_FIELDS[:-1]:
            strict_integer(data[name], name)
        if data['id'] != request.handoff_id or data['task_id'] != request.task_id:
            raise ValueError('Original handoff scope differs')
        _time(data['created_at'], nullable=False)
        question = project_issue(data['source_question'], request, 'QUESTION')
        if question['id'] != data['question_id']:
            raise ValueError('Original handoff question differs')
        events, meta = page(
            data['event_page'], lambda item: _event_view(item, request.handoff_id), request.page
        )
        result = {name: data[name] for name in HANDOFF_FIELDS}
        result.update(
            source_question=question,
            evidence_refs=parse_evidence(data['evidence_refs']),
            events=events['items'],
        )
        return result, meta


def _original_operation(connection, handoff, operation):
    if (
        operation is None
        or operation['id'] != handoff['operation_id']
        or operation['operation_type'] != TYPE
        or operation['status'] != 'SUCCEEDED'
        or operation['task_id'] != handoff['task_id']
        or operation['resource_id'] != handoff['task_id']
        or operation['resource_kind'] != 'TASK'
        or operation['created_at'] != handoff['created_at']
    ):
        raise StorageUnavailable('Original handoff operation differs')
    fixed = strict_json_object(operation['fixed_input'])
    command = registered_command(
        'POST',
        PREPARE.format(task_id=handoff['task_id'], question_id=handoff['question_id']),
        operation['idempotency_key'],
    )
    original = connection.execute(
        """SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?""",
        command.scope.identity,
    ).fetchone()
    if original is None or original['status'] != 'SUCCEEDED':
        raise StorageUnavailable('Original handoff receipt missing')
    output = strict_json_object(original['success_result_json'])
    validate_handoff_receipt(command, output['data'], original['http_status'])
    if (
        output['code'] != 'CREATED'
        or output['data']['handoff_id'] != handoff['id']
        or output['data']['target_document_id'] != handoff['target_document_id']
        or fixed['target_document_id'] != handoff['target_document_id']
        or canonical_input({key: value for key, value in fixed.items() if key != 'fixed_basis'})
        != original['business_input_json']
    ):
        raise StorageUnavailable('Original handoff result differs')
    return fixed


def read_handoff(runtime, request, *, native_ready=False):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        task = _task(connection, request.task_id)
        handoff = None if task is None else _handoff(connection, task, request.handoff_id)
        if handoff is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        question = _source(connection, task, handoff['question_id'])
        if question is None or _document(connection, task, handoff['target_document_id']) is None:
            raise StorageUnavailable('Original handoff source or target missing')
        operation = connection.execute(
            'SELECT * FROM code_operations WHERE id=?', (handoff['operation_id'],)
        ).fetchone()
        fixed = _original_operation(connection, handoff, operation)
        total = connection.execute(
            'SELECT count(*) FROM code_question_handoff_events WHERE handoff_id=?', (handoff['id'],)
        ).fetchone()[0]
        events = connection.execute(
            """SELECT * FROM code_question_handoff_events WHERE handoff_id=?
               ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?""",
            (handoff['id'], PAGE_SIZE, page_offset(request.page)),
        )
        data = {
            **dict(handoff),
            'source_question': project_stored_issue(
                connection,
                task,
                question,
                'QUESTION',
                answer_ready=native_ready,
            ),
            'evidence_refs': fixed['evidence_refs'],
            'event_page': {
                **page_metadata(request.page, total),
                'items': [dict(row) for row in events],
            },
        }
        return {'code': 'READ_OK', 'data': data, 'details': None}


def public_handoff_operation(connection, operation):
    handoff = connection.execute(
        'SELECT * FROM code_question_handoffs WHERE task_id=? AND operation_id=?',
        (operation['task_id'], operation['id']),
    ).fetchone()
    if handoff is None:
        raise StorageUnavailable('Original handoff record missing')
    fixed = _original_operation(connection, handoff, operation)
    rows = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    )
    return project_handoff_operation(
        {
            **dict(operation),
            'fixed_input': fixed,
            'content_capture': None,
            'steps': [
                {
                    **dict(row),
                    'fixed_input': strict_json_object(row['fixed_input']),
                    'result_ref': strict_json_object(row['result_ref']),
                }
                for row in rows
            ],
        },
        operation['id'],
    )


def project_handoff_operation(value, identity):
    row = exact(value, OPERATION_FIELDS)
    fixed = exact(
        row['fixed_input'],
        (
            'task_id',
            'question_id',
            'expected_state_version',
            'target_document_id',
            'evidence_refs',
            'fixed_basis',
        ),
    )
    for field in ('task_id', 'question_id', 'expected_state_version', 'target_document_id'):
        strict_integer(fixed[field], field)
    parse_evidence(fixed['evidence_refs'])
    if type(fixed['fixed_basis']) is not list or not fixed['fixed_basis']:
        raise ValueError('Original handoff fixed basis missing')
    for item in fixed['fixed_basis']:
        reference = exact(item, ('document_id', 'revision_id'))
        for field in reference:
            strict_integer(reference[field], field)
    created = row['created_at']
    _time(created, nullable=False)
    strict_integer(row['session_id'], 'session_id')
    strict_integer(row['control_generation'], 'control_generation')
    registered_command(
        'POST',
        PREPARE.format(task_id=fixed['task_id'], question_id=fixed['question_id']),
        row['idempotency_key'],
    )
    if (
        row['id'] != identity
        or row['task_id'] != fixed['task_id']
        or row['resource_id'] != fixed['task_id']
        or row['resource_kind'] != 'TASK'
        or row['operation_type'] != TYPE
        or row['status'] != 'SUCCEEDED'
        or row['expected_state_version'] != fixed['expected_state_version']
        or any(
            row[name] is not None for name in ('testing_task_id', 'failure_code', 'content_capture')
        )
        or row['started_at'] != created
        or row['ended_at'] != created
        or type(row['steps']) is not list
        or len(row['steps']) != len(STEPS)
    ):
        raise ValueError('Original handoff operation projection differs')
    for number, (value, name) in enumerate(zip(row['steps'], STEPS, strict=True), 1):
        step = exact(value, STEP_FIELDS)
        if (
            step['operation_id'] != identity
            or step['step_no'] != number
            or step['step_type'] != name
            or step['status'] != 'SUCCEEDED'
            or step['fixed_input'] != fixed
            or step['external_identity'] is not None
            or any(step[key] != created for key in ('started_at', 'ended_at', 'last_observed_at'))
        ):
            raise ValueError('Original handoff step differs')
        if number == 1:
            if step['result_ref'] != {'question_id': fixed['question_id']}:
                raise ValueError('Original handoff validated question differs')
        else:
            result = exact(step['result_ref'], ('handoff_id', 'handoff_event_id'))
            for key in result:
                strict_integer(result[key], key)
    return row


@handoff_router.post(PREPARE)
@handoff_router.post(LINK)
async def handoff_write_http(request: Request):
    return await handle_http(request, HandoffCommand, HandoffReceipt, write_handoff)


@handoff_router.get(DETAIL)
async def handoff_read_http(request: Request):
    from .repository_registration_worker import RepositoryRegistrationWorker

    worker = getattr(request.app.state, 'walle_repository_registration', None)
    ready = isinstance(worker, RepositoryRegistrationWorker) and worker.accepts_native_responses
    return await handle_http(
        request,
        HandoffPage,
        HandoffView,
        lambda runtime, parsed: read_handoff(runtime, parsed, native_ready=ready),
    )
