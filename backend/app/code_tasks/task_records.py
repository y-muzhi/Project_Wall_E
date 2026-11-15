"""Persist confirmed Coding observations and read the original record page."""

import re
from dataclasses import dataclass, replace

from fastapi import APIRouter, Request

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.execution_display_text import (
    UNAVAILABLE_EXECUTION_TEXT,
    execution_display_text,
)
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.infrastructure.opencode_instance_control import (
    NativeTurnCompletion,
    NativeTurnRecord,
)
from backend.app.shared.http_boundary import handle_http, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    raw_text,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .coding_model_gateway import _check_credentials
from .coding_model_request import CodingModelProtocolError
from .configuration_identities import require_schema
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_question_answers import EVIDENCE

PATH = '/api/v1/code-tasks/{task_id}/records'
KINDS = ('MESSAGE', 'TOOL', 'COMMAND_OUTPUT', 'CONTROL', 'ERROR')
SOURCES = {
    **{kind: query for kind, query in EVIDENCE.items() if kind != 'VERIFICATION_ITEM'},
    'PERMISSION': 'SELECT status FROM code_permissions WHERE task_id=? AND id=?',
}
FIELDS = (
    'id',
    'task_id',
    'instance_id',
    'control_generation',
    'kind',
    'text',
    'observed_at',
    'session_id',
    'native_event_id',
    'source_kind',
    'source_id',
)
NOT_FOUND = {'code': 'NOT_FOUND', 'data': None, 'details': None}
records_router = APIRouter(redirect_slashes=False)


_NATIVE_EVENT = re.compile(r'(?:prt_[A-Za-z0-9]{1,96}|(?:limit|error):msg_[A-Za-z0-9]{1,96})')
_RECORD_MAX_BYTES = 32 * 1024


def safe_native_records(turn, credentials):
    """Retain event identity when source text cannot safely be exposed."""
    records = []
    for record in turn.records:
        value = execution_display_text(record.text, max_bytes=_RECORD_MAX_BYTES)
        try:
            if value != UNAVAILABLE_EXECUTION_TEXT:
                _check_credentials(value, tuple(secret for secret in credentials if secret))
        except CodingModelProtocolError:
            value = UNAVAILABLE_EXECUTION_TEXT
        records.append(replace(record, text=value))
    return replace(turn, records=tuple(records))


def _verify_cancelled_record_owner(connection, window):
    from .task_cancelled_repair import read_cancelled_repair

    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (window.task_id,)).fetchone()
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (window.execution_session_id, window.task_id),
    ).fetchone()
    if task is None or session is None or session['model_window'] is None:
        raise StorageUnavailable('Cancelled native record owner disappeared')
    closed = strict_json_object(session['model_window'])
    if read_cancelled_repair(connection, task, session, closed) is None:
        raise StorageUnavailable('Cancelled native record has no original quiet observation')


def record_native_turn(connection, window, turn, at):
    """Append original settled events once, using their exact session and trigger."""
    if type(turn) is not NativeTurnCompletion or not turn.records:
        return
    require_write_transaction(connection)
    _time(at, nullable=False)
    owner = connection.execute(
        """SELECT o.status AS operation_status FROM code_sessions s JOIN code_operations o ON o.id=? AND o.task_id=s.task_id
           WHERE s.id=? AND s.task_id=? AND s.instance_id=? AND s.control_generation=?
           AND s.native_session_id=? AND s.status='ACTIVE' AND s.created_at<=?
           AND json_extract(s.model_window,'$.operation_id')=o.id
           AND json_extract(s.model_window,'$.native_trigger_message_id')=?
           AND o.resource_kind='TASK' AND o.resource_id=s.task_id
           AND (o.status IN ('RUNNING','SUCCEEDED') OR (o.operation_type='REPAIR' AND o.status='CANCELLED'))
           AND (
               (o.operation_type='REPAIR' AND o.control_generation+1=s.control_generation
                  AND EXISTS(SELECT 1 FROM code_operation_steps restore WHERE restore.operation_id=o.id
                      AND restore.step_no=1 AND restore.status='SUCCEEDED'
                      AND json_extract(restore.external_identity,'$.replacement.target_session_id')=s.id
                      AND json_extract(restore.result_ref,'$.native_session_id')=s.native_session_id))
               OR (o.operation_type IN ('START','RESUME','REPAIR') AND o.session_id=s.id
                AND o.control_generation=s.control_generation)
               OR (o.operation_type='HANDOFF_ROLE' AND o.control_generation+1=s.control_generation
                   AND EXISTS(SELECT 1 FROM code_operation_steps creation WHERE creation.operation_id=o.id
                       AND creation.step_no=4 AND creation.step_type='CREATE_SESSION' AND creation.status='SUCCEEDED'
                       AND json_extract(creation.result_ref,'$.session_id')=s.id
                       AND json_extract(creation.result_ref,'$.native_session_id')=s.native_session_id))
           )""",
        (
            window.operation_id,
            window.execution_session_id,
            window.task_id,
            window.instance_id,
            window.generation,
            window.native_session_id,
            at,
            window.trigger_message_id,
        ),
    ).fetchone()
    if (
        owner is None
        or turn.session_id != window.native_session_id
        or turn.trigger_message_id != window.trigger_message_id
        or len(turn.records) > 257
    ):
        raise StorageUnavailable('Original native execution records cross session scope')
    from .task_session_replacement import replacement_for_session

    replacement = replacement_for_session(connection, window.task_id, window.execution_session_id)
    if (
        replacement is not None
        and replacement.operation['id'] == window.operation_id
        and replacement.target['control_generation'] != window.generation
    ):
        raise StorageUnavailable('Original replaced native record generation differs')
    if owner['operation_status'] == 'CANCELLED':
        _verify_cancelled_record_owner(connection, window)
    prefix = (window.task_id, window.instance_id, window.generation, window.execution_session_id)
    event_ids = set()
    for record in turn.records:
        if (
            type(record) is not NativeTurnRecord
            or type(record.event_id) is not str
            or _NATIVE_EVENT.fullmatch(record.event_id) is None
            or record.kind not in ('MESSAGE', 'TOOL', 'CONTROL', 'ERROR')
            or record.event_id in event_ids
        ):
            raise StorageUnavailable('Original native execution record identity differs')
        event_ids.add(record.event_id)
    placeholders = ','.join('?' for _ in event_ids)
    existing = {}
    for row in connection.execute(
        f"""SELECT native_event_id,kind,source_kind,source_id FROM code_execution_records
           WHERE task_id=? AND instance_id=? AND control_generation=? AND session_id=?
           AND native_event_id IN ({placeholders})""",
        (*prefix, *event_ids),
    ):
        identity = row['native_event_id']
        if identity in existing:
            raise StorageUnavailable('Original native execution record is not unique')
        existing[identity] = (row['kind'], row['source_kind'], row['source_id'])
    for record in safe_native_records(turn, ()).records:
        prior = existing.get(record.event_id)
        if prior is not None:
            if prior != (record.kind, 'OPERATION', window.operation_id):
                raise StorageUnavailable('Original native execution record was already bound')
            continue
        connection.execute(
            """INSERT INTO code_execution_records(id,task_id,instance_id,control_generation,session_id,
               native_event_id,kind,text,observed_at,source_kind,source_id)
               VALUES(?,?,?,?,?,?,?,?,?,'OPERATION',?)""",
            (
                entity_id(connection, EntityKind.EXECUTION_RECORD),
                *prefix,
                record.event_id,
                record.kind,
                record.text,
                at,
                window.operation_id,
            ),
        )


def record_project_output(connection, task_id, command_id, records, at):
    if not records:
        return
    require_write_transaction(connection)
    _time(at, nullable=False)
    owner = connection.execute(
        """SELECT s.id,s.instance_id,s.control_generation FROM code_commands c
           JOIN code_sessions s ON s.id=c.session_id AND s.task_id=c.task_id
           JOIN code_operations o ON o.id=c.operation_id AND o.task_id=c.task_id
           WHERE c.id=? AND c.task_id=? AND c.purpose='CHECK' AND c.ended_at=?
           AND c.process_identity IS NOT NULL AND c.runtime_binding IS NOT NULL
           AND o.operation_type IN ('CAPTURE_AND_CHECK','VERIFY_CANDIDATE')
           AND o.session_id=s.id AND o.control_generation=s.control_generation""",
        (command_id, task_id, at),
    ).fetchone()
    if owner is None:
        raise StorageUnavailable('Original project output has no confirmed command owner')
    names = {'STDOUT': '标准输出', 'STDERR': '标准错误', 'UNAVAILABLE': '命令输出'}
    for record in records:
        text = execution_display_text(record.text, max_bytes=2048)
        connection.execute(
            """INSERT INTO code_execution_records(id,task_id,instance_id,control_generation,
               session_id,kind,text,observed_at,source_kind,source_id)
               VALUES(?,?,?,?,?,'COMMAND_OUTPUT',?,?,'COMMAND',?)""",
            (
                entity_id(connection, EntityKind.EXECUTION_RECORD),
                task_id,
                owner['instance_id'],
                owner['control_generation'],
                owner['id'],
                names[record.stream] + '\n' + text,
                at,
                command_id,
            ),
        )


def record_confirmed_control(connection, scope, operation_id, text, at):
    """Call inside the original operation's successful native-confirmation transaction."""
    require_write_transaction(connection)
    known = connection.execute(
        """SELECT 1 FROM code_operations WHERE id=? AND task_id=? AND (session_id=? OR (operation_type='REPAIR' AND EXISTS(
               SELECT 1 FROM code_operation_steps restore WHERE restore.operation_id=code_operations.id
                   AND restore.step_no=1 AND restore.status='SUCCEEDED'
                   AND json_extract(restore.external_identity,'$.replacement.target_session_id')=?)))
           AND status='SUCCEEDED' AND ended_at=? AND (
               control_generation=? OR (operation_type='REPAIR' AND control_generation+1=? AND EXISTS(
                   SELECT 1 FROM code_operation_steps restore WHERE restore.operation_id=code_operations.id
                       AND restore.step_no=1 AND restore.status='SUCCEEDED'
                       AND json_extract(restore.external_identity,'$.replacement.target_session_id')=?)))""",
        (
            operation_id,
            scope.task_id,
            scope.session_id,
            scope.session_id,
            at,
            scope.control_generation,
            scope.control_generation,
            scope.session_id,
        ),
    ).fetchone()
    if known is None:
        raise StorageUnavailable('Original confirmed Coding operation is missing')
    connection.execute(
        """INSERT INTO code_execution_records(id,task_id,instance_id,control_generation,kind,text,
           observed_at,session_id,source_kind,source_id) VALUES(?,?,?,?,'CONTROL',?,?,?,'OPERATION',?)""",
        (
            entity_id(connection, EntityKind.EXECUTION_RECORD),
            scope.task_id,
            scope.instance_id,
            scope.control_generation,
            text,
            at,
            scope.session_id,
            operation_id,
        ),
    )


@dataclass(frozen=True)
class RecordsRequest:
    task_id: int
    page: int
    session_id: int | None

    @classmethod
    def parse(cls, request):
        query = request_query(request, singles=('page', 'session_id'))
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(query.get('page', '1'), 'page', maximum=MAX_PAGE),
            None
            if 'session_id' not in query
            else decimal_integer(query['session_id'], 'session_id'),
        )


def _project(value, request):
    row = exact(value, FIELDS)
    for key in ('id', 'task_id', 'instance_id', 'control_generation'):
        strict_integer(row[key], key)
    if row['task_id'] != request.task_id or (
        request.session_id is not None and request.session_id != row['session_id']
    ):
        raise ValueError('Original Coding execution record crosses scope')
    for key in ('session_id', 'source_id'):
        if row[key] is not None:
            strict_integer(row[key], key)
    strict_enum(row['kind'], 'kind', KINDS)
    raw_text(row['text'], 'text', 1, 4 * 1024 * 1024)
    if row['native_event_id'] is not None:
        raw_text(row['native_event_id'], 'native_event_id', 1, 1024)
    _time(row['observed_at'], nullable=False)
    if (row['source_id'] is None) != (row['source_kind'] is None):
        raise ValueError('Original Coding execution record source is incomplete')
    if row['source_kind'] is not None:
        strict_enum(row['source_kind'], 'source_kind', SOURCES)
    return row


def _saved(connection, source, request):
    row = _project(dict(source), request)
    if (
        connection.execute(
            'SELECT 1 FROM code_instances WHERE id=? AND task_id=?',
            (row['instance_id'], row['task_id']),
        ).fetchone()
        is None
    ):
        raise StorageUnavailable('Original Coding execution record instance is missing')
    if (
        row['session_id'] is not None
        and connection.execute(
            """SELECT 1 FROM code_sessions WHERE id=? AND task_id=? AND instance_id=?
           AND control_generation=? AND created_at<=?""",
            (
                row['session_id'],
                row['task_id'],
                row['instance_id'],
                row['control_generation'],
                row['observed_at'],
            ),
        ).fetchone()
        is None
    ):
        raise StorageUnavailable('Original Coding execution record session is missing')
    if (
        row['source_kind'] is not None
        and connection.execute(
            SOURCES[row['source_kind']],
            (row['task_id'], row['source_id']),
        ).fetchone()
        is None
    ):
        raise StorageUnavailable('Original Coding execution record source is missing')
    return {**row, 'text': execution_display_text(row['text'], max_bytes=_RECORD_MAX_BYTES)}


def read_records(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute('SELECT 1 FROM code_tasks WHERE id=?', (request.task_id,)).fetchone()
            is None
        ):
            return NOT_FOUND
        where, params = 'task_id=?', (request.task_id,)
        if request.session_id is not None:
            if (
                connection.execute(
                    'SELECT 1 FROM code_sessions WHERE id=? AND task_id=?',
                    (request.session_id, request.task_id),
                ).fetchone()
                is None
            ):
                return NOT_FOUND
            where, params = where + ' AND session_id=?', (*params, request.session_id)
        count = connection.execute(
            f'SELECT count(*) FROM code_execution_records WHERE {where}',
            params,
        ).fetchone()[0]
        rows = connection.execute(
            f'SELECT * FROM code_execution_records WHERE {where} ORDER BY id LIMIT ? OFFSET ?',
            (*params, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        try:
            items = [_saved(connection, row, request) for row in rows]
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailable('Original Coding execution record is unreadable') from error
    return {
        'code': 'READ_OK',
        'data': {**page_metadata(request.page, count), 'items': items},
        'details': None,
    }


class RecordsRead:
    error_contract = 'code'
    status = 200
    success_code = 'READ_OK'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        return page(value, lambda row: _project(row, request), request.page)


@records_router.get(PATH)
async def read_records_http(request: Request):
    return await handle_http(request, RecordsRequest, RecordsRead, read_records)
