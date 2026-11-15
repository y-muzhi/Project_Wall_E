"""Read the original Coding LLMUse and retained audit within its task snapshot."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.audit_data import sanitize_audit
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .coding_model_ledger import FRAME_BYTES, REQUEST_BYTES, RESPONSE_BYTES
from .configuration_identities import require_schema
from .costs import parse_money
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_read_query import read_task_query

LIST_PATH = '/api/v1/code-tasks/{task_id}/model-calls'
DETAIL_PATH = LIST_PATH + '/{llm_use_id}'
coding_model_read_router = APIRouter(redirect_slashes=False)
_FIELDS = (
    'id',
    'execution_session_id',
    'operation_id',
    'call_no',
    'attempt_no',
    'model_name',
    'protocol_version',
    'call_purpose',
    'call_status',
    'transport_status',
    'capture_status',
    'started_at',
    'ended_at',
    'input_tokens',
    'output_tokens',
    'cached_tokens',
    'duration_ms',
    'usage_status',
)
_DETAIL = (
    'task_id',
    'retry_of_llm_use_id',
    'request_snapshot',
    'response_snapshot',
    'finish_reason',
    'provider_request_id',
    'error_code',
    'reservation_id',
    'reservation_status',
    'reserved_cny',
    'settled_cny',
    'settlement_basis',
)
_TRANSPORT = ('NOT_SENT', 'SENDING', 'SENT', 'COMPLETE', 'INTERRUPTED', 'UNKNOWN')
_CAPTURE = ('FULL', 'REDACTED', 'INCOMPLETE')
_USAGE = ('NOT_REPORTED', 'PARTIAL', 'FINAL', 'DISPUTED')
_RESERVATIONS = ('RESERVED', 'SETTLED', 'RELEASED_UNSENT', 'UNKNOWN', 'DISPUTED')
_OWNER = 'FROM llm_uses u JOIN code_sessions s ON s.id=u.execution_session_id WHERE s.task_id=?'
_JOINS = """
    FROM llm_uses u JOIN code_sessions s ON s.id=u.execution_session_id
    LEFT JOIN code_operations o ON o.id=u.operation_id AND o.task_id=s.task_id AND o.resource_kind='TASK'
    LEFT JOIN code_task_reservations r ON r.llm_use_id=u.id AND r.task_id=s.task_id
    WHERE s.task_id=? AND u.guide_run_id IS NULL AND u.testing_task_id IS NULL
"""
_SELECT = ','.join('u.' + field for field in _FIELDS if field != 'cached_tokens')
_SELECT += ',u.cache_info_json,o.id AS owned_operation_id,r.id AS reservation_id'
_NOT_FOUND = {'code': 'NOT_FOUND', 'data': None, 'details': None}


@dataclass(frozen=True)
class CallListRequest:
    task_id: int
    page: int

    @classmethod
    def parse(cls, request):
        query = read_task_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
        )


@dataclass(frozen=True)
class CallDetailRequest:
    task_id: int
    llm_use_id: int

    @classmethod
    def parse(cls, request):
        read_task_query(request)
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['llm_use_id'], 'llm_use_id'),
        )


def _summary(row):
    if row['owned_operation_id'] != row['operation_id'] or row['reservation_id'] is None:
        raise StorageUnavailable('Original Coding call ownership is incomplete')
    cache = {} if row['cache_info_json'] is None else strict_json_object(row['cache_info_json'])
    return {
        field: cache.get('cached_tokens') if field == 'cached_tokens' else row[field]
        for field in _FIELDS
    }


def list_calls(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        task = connection.execute(
            'SELECT id FROM code_tasks WHERE id=?', (request.task_id,)
        ).fetchone()
        if task is None:
            return _NOT_FOUND
        total = connection.execute('SELECT count(*) ' + _OWNER, (request.task_id,)).fetchone()[0]
        rows = connection.execute(
            'SELECT ' + _SELECT + _JOINS + ' ORDER BY u.started_at DESC,u.id DESC LIMIT ? OFFSET ?',
            (request.task_id, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        items = [_summary(row) for row in rows]
    return {
        'code': 'READ_OK',
        'data': {'items': items, **page_metadata(request.page, total)},
        'details': None,
    }


def _response_snapshot(connection, row):
    use = row['id']
    totals = connection.execute(
        """SELECT count(*),COALESCE(SUM(length(CAST(frame_json AS BLOB))),0),
                  COALESCE(MAX(length(CAST(frame_json AS BLOB))),0)
           FROM code_model_response_frames WHERE llm_use_id=?""",
        (use,),
    ).fetchone()
    count, size, largest = totals
    if size > RESPONSE_BYTES or largest > FRAME_BYTES:
        raise StorageUnavailable('Original Coding response audit exceeds its capacity')
    if row['raw_response_json'] is None and count == 0:
        return None, row['capture_status']
    summary = (
        {} if row['raw_response_json'] is None else strict_json_object(row['raw_response_json'])
    )
    if summary and (
        set(summary) != {'kind', 'frame_count', 'captured_bytes', 'complete'}
        or summary['kind'] != 'SSE_FRAMES'
        or type(summary['complete']) is not bool
    ):
        raise StorageUnavailable('Original Coding response audit descriptor differs')
    frames = []
    for saved in connection.execute(
        """SELECT seq,received_at,frame_json,capture_status
           FROM code_model_response_frames WHERE llm_use_id=? ORDER BY seq""",
        (use,),
    ):
        raw = strict_json_object(saved['frame_json'])
        clean = sanitize_audit(raw)
        frames.append(
            {
                'seq': saved['seq'],
                'received_at': saved['received_at'],
                'frame_json': clean,
                'capture_status': 'REDACTED' if clean != raw else saved['capture_status'],
            }
        )
    consistent = (
        summary.get('frame_count') == count
        and summary.get('captured_bytes') == size
        and all(frame['seq'] == index for index, frame in enumerate(frames, 1))
    )
    complete = bool(
        consistent
        and summary.get('complete') is True
        and frames
        and frames[-1]['frame_json'].get('kind') == 'DONE'
        and not any(frame['capture_status'] == 'INCOMPLETE' for frame in frames)
        and row['capture_status'] != 'INCOMPLETE'
    )
    capture = row['capture_status']
    if (
        not consistent
        or (summary.get('complete') is True and not complete)
        or any(frame['capture_status'] == 'INCOMPLETE' for frame in frames)
    ):
        capture = 'INCOMPLETE'
    elif any(frame['capture_status'] == 'REDACTED' for frame in frames) and capture == 'FULL':
        capture = 'REDACTED'
    return {
        'frames': frames,
        'frame_count': count,
        'captured_bytes': size,
        'complete': complete,
    }, capture


def _request_snapshot(row, task_id):
    encoded = row['request_snapshot_json']
    if len(encoded.encode('utf-8')) > REQUEST_BYTES:
        raise StorageUnavailable('Original Coding request audit exceeds its capacity')
    saved = exact(
        strict_json_object(encoded), ('native_request', 'supplier_request', 'model', 'window')
    )
    window = saved['window']
    if (
        type(window) is not dict
        or window.get('task_id') != task_id
        or window.get('execution_session_id') != row['execution_session_id']
        or window.get('operation_id') != row['operation_id']
        or window.get('source_evidence_ref') != row['source_evidence_ref']
        or any(
            type(saved[key]) is not dict for key in ('native_request', 'supplier_request', 'model')
        )
        or saved['model'].get('price_version_id') != row['price_version_id']
    ):
        raise StorageUnavailable('Original Coding request audit owner differs')
    saved['window'] = {
        key: window[key]
        for key in (
            'task_id',
            'execution_session_id',
            'operation_id',
            'control_generation',
            'instance_id',
        )
    }
    saved['model'].pop('admission_ref', None)
    return sanitize_audit(saved)


def read_call(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT '
            + _SELECT
            + """,u.retry_of_llm_use_id,u.request_snapshot_json,u.raw_response_json,
            u.finish_reason,u.provider_request_id,u.error_code,u.source_evidence_ref,u.cost,u.cost_currency,
            r.price_version_id,r.status AS reservation_status,r.reserved_cny,r.settled_cny,r.settlement_basis
            """
            + _JOINS
            + ' AND u.id=?',
            (request.task_id, request.llm_use_id),
        ).fetchone()
        if row is None:
            return _NOT_FOUND
        data = _summary(row)
        retry = row['retry_of_llm_use_id']
        if (
            retry is not None
            and connection.execute(
                'SELECT u.id ' + _OWNER + ' AND u.id=? AND u.id<?',
                (request.task_id, retry, row['id']),
            ).fetchone()
            is None
        ):
            raise StorageUnavailable('Original Coding call retry owner differs')
        if row['cost'] != row['settled_cny'] or row['cost_currency'] != (
            None if row['settled_cny'] is None else 'CNY'
        ):
            raise StorageUnavailable('Original Coding settlement differs')
        response, capture = _response_snapshot(connection, row)
        data.update(
            capture_status=capture,
            task_id=request.task_id,
            request_snapshot=_request_snapshot(row, request.task_id),
            response_snapshot=response,
        )
        data.update(
            {
                key: row[key]
                for key in _DETAIL[1:]
                if key not in ('request_snapshot', 'response_snapshot')
            }
        )
    return {'code': 'READ_OK', 'data': data, 'details': None}


def project_summary(value):
    row = exact(value, _FIELDS)
    for key in ('id', 'execution_session_id', 'operation_id', 'call_no', 'attempt_no'):
        strict_integer(row[key], key)
    if row['attempt_no'] != 1 or type(row['model_name']) is not str or not row['model_name']:
        raise ValueError('Coding call identity differs')
    strict_enum(row['protocol_version'], 'protocol_version', ('OC20-MODEL-1',))
    strict_enum(row['call_purpose'], 'call_purpose', ('CODE', 'COMPACTION'))
    strict_enum(row['call_status'], 'call_status', ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'))
    strict_enum(row['transport_status'], 'transport_status', _TRANSPORT)
    strict_enum(row['capture_status'], 'capture_status', _CAPTURE)
    strict_enum(row['usage_status'], 'usage_status', _USAGE)
    _time(row['started_at'], nullable=False)
    _time(row['ended_at'])
    if row['ended_at'] is not None and row['ended_at'] < row['started_at']:
        raise ValueError('Coding call chronology differs')
    for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'duration_ms'):
        if row[key] is not None:
            strict_integer(row[key], key, minimum=0)
    if row['cached_tokens'] is not None and (
        row['input_tokens'] is None or row['cached_tokens'] > row['input_tokens']
    ):
        raise ValueError('Coding cache usage exceeds original input')
    return row


class CallListResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        data, metadata = page(value, project_summary, request.page)
        keys = [(row['started_at'], row['id']) for row in data['items']]
        if any(left <= right for left, right in zip(keys, keys[1:])):
            raise ValueError('Original Coding call list order differs')
        return data, metadata


class CallDetailResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        row = exact(value, _FIELDS + _DETAIL)
        project_summary({key: row[key] for key in _FIELDS})
        if row['id'] != request.llm_use_id or row['task_id'] != request.task_id:
            raise ValueError('Original Coding call scope differs')
        strict_integer(row['reservation_id'], 'reservation_id')
        if row['retry_of_llm_use_id'] is not None:
            strict_integer(row['retry_of_llm_use_id'], 'retry_of_llm_use_id')
        for key in ('finish_reason', 'provider_request_id', 'error_code'):
            if row[key] is not None and (type(row[key]) is not str or not row[key]):
                raise ValueError('Original Coding call text field differs')
        if row['provider_request_id'] is not None and len(row['provider_request_id']) > 1024:
            raise ValueError('Original Coding provider request ID exceeds its limit')
        strict_enum(row['reservation_status'], 'reservation_status', _RESERVATIONS)
        parse_money(row['reserved_cny'])
        if row['reservation_status'] == 'SETTLED':
            parse_money(row['settled_cny'])
            strict_enum(
                row['settlement_basis'], 'settlement_basis', ('VERIFIED_USAGE', 'PROVIDER_BILL')
            )
        elif row['settled_cny'] is not None or row['settlement_basis'] is not None:
            raise ValueError('Unresolved Coding fee cannot claim settlement')
        return row, None


@coding_model_read_router.get(LIST_PATH)
async def coding_model_calls_http(request: Request):
    return await handle_http(request, CallListRequest, CallListResponse, list_calls)


@coding_model_read_router.get(DETAIL_PATH)
async def coding_model_call_http(request: Request):
    return await handle_http(request, CallDetailRequest, CallDetailResponse, read_call)
