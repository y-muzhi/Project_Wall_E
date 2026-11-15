"""Read exact candidate content and fixed Git comparisons under the original scope."""

from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.content_manifest import ContentEntry
from backend.app.infrastructure.content_paths import (
    ContentPathError,
    content_file_mode,
    relative_content_path,
)
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.command_execution import ConfigurationNotReady
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    decimal_integer,
    reject,
    strict_boolean,
    strict_enum,
    strict_integer,
)

from .configuration_identities import require_schema
from .repository_baseline_query import BaselineQueryResult, BaselineSnapshotMissing
from .repository_baseline_validation import read_registered_baseline
from .repository_reads import ERRORS
from .repository_registration_worker import RepositoryRegistrationWorker
from .repository_snapshot_reads import GUARD_ERRORS, SOURCE_ERRORS, with_repository_request
from .task_candidate_reads import NOT_FOUND, NOT_READY, PATH, _saved, _verify_package
from .task_read_query import read_task_query

DETAIL = PATH + '/{candidate_id}'
_MAX_CHUNK = 65536
_CHUNK_FIELDS = (
    'candidate_id',
    'path',
    'offset',
    'length',
    'total_bytes',
    'content_base64',
    'next_offset',
)
_DIFF_FIELDS = (
    'path',
    'change',
    'before_size',
    'after_size',
    'before_mode',
    'after_mode',
    'binary',
)
_SIDES = ('BEFORE', 'AFTER')
candidate_content_router = APIRouter(redirect_slashes=False)


def _ids(request):
    return (
        decimal_integer(request.path_params['task_id'], 'task_id'),
        decimal_integer(request.path_params['candidate_id'], 'candidate_id'),
    )


@dataclass(frozen=True)
class DiffRequest:
    task_id: int
    candidate_id: int
    page: int

    @classmethod
    def parse(cls, request):
        query = read_task_query(request, singles=('page',))
        return cls(*_ids(request), decimal_integer(query.get('page', '1'), 'page', MAX_PAGE))


@dataclass(frozen=True)
class ChunkRequest:
    task_id: int
    candidate_id: int
    path: str
    offset: int
    length: int
    side: str | None

    @classmethod
    def parse(cls, request):
        return cls._parse(request, comparison=False)

    @classmethod
    def _parse(cls, request, *, comparison):
        fields = (
            ('path', 'offset', 'length', 'side') if comparison else ('path', 'offset', 'length')
        )
        query = read_task_query(request, singles=fields)
        try:
            path = relative_content_path(query.get('path'))
            if len(path) > 4096:
                raise ContentPathError('CONTENT_PATH_TOO_LONG')
        except ContentPathError:
            reject('path', 'INVALID_FORMAT', '必须使用原清单中的精确相对路径')
        offset = query.get('offset', '0')
        return cls(
            *_ids(request),
            path,
            0 if offset == '0' else decimal_integer(offset, 'offset'),
            decimal_integer(query.get('length', str(_MAX_CHUNK)), 'length', _MAX_CHUNK),
            strict_enum(query.get('side'), 'side', _SIDES) if comparison else None,
        )


class ComparisonRequest(ChunkRequest):
    @classmethod
    def parse(cls, request):
        return cls._parse(request, comparison=True)


def _ready(data):
    return {'code': 'READ_OK', 'data': data, 'details': None}


def _missing_capability(*codes):
    return {'code': 'CONFIG_NOT_READY', 'data': None, 'details': {'capability_codes': list(codes)}}


def _binary(raw):
    if b'\0' in raw:
        return True
    try:
        raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        return True
    return False


@dataclass(frozen=True)
class _File:
    entry: ContentEntry
    binary: bool
    chunk: bytes | None


class _Files:
    def __init__(self, request, side, *, all_paths):
        self.files = {}
        self.request, self.side, self.all_paths = request, side, all_paths

    def observe(self, entry, raw):
        request = self.request
        selected = isinstance(request, ChunkRequest) and request.path == entry.path
        if not self.all_paths and not selected:
            return
        chunk = None
        if selected and request.side in (None, self.side):
            chunk = raw[request.offset : request.offset + request.length]
        self.files[entry.path] = _File(
            entry,
            _binary(raw) if type(request) is DiffRequest else False,
            chunk,
        )


def _candidate(connection, request):
    row = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (request.candidate_id, request.task_id),
    ).fetchone()
    return None if row is None else _saved(connection, row)


def _check_cancelled(cancelled):
    if cancelled():
        raise StorageUnavailable('Original candidate read was cancelled')


def _read_after(original, files, cancelled):
    try:
        _verify_package(
            original,
            consume_file=files.observe,
            active=lambda: _check_cancelled(cancelled),
        )
    except (OSError, RuntimeError, ValueError):
        return NOT_READY
    return None


def _read_before(worker, snapshot, files, cancelled):
    if type(worker) is not RepositoryRegistrationWorker:
        return _missing_capability('Q20-WINDOWS', 'Q20-GIT')
    try:
        result = worker.read_snapshot(
            snapshot['id'], cancelled=cancelled, consume_file=files.observe
        )
    except (BaselineSnapshotMissing, *SOURCE_ERRORS):
        return NOT_READY
    except ConfigurationNotReady as error:
        return {'code': 'CONFIG_NOT_READY', 'data': None, 'details': error.details}
    except ConfigInvalid:
        return _missing_capability('Q20-CONTENT')
    except GUARD_ERRORS:
        return _missing_capability('Q20-WINDOWS', 'Q20-GIT')
    if (
        type(result) is not BaselineQueryResult
        or result.snapshot != snapshot
        or {path: file.entry for path, file in files.files.items()}
        != {entry.path: entry for entry in result.entries}
    ):
        raise StorageUnavailable('Original candidate comparison source differs')
    return None


def _changed(left, right):
    if left is None:
        return 'ADD'
    if right is None:
        return 'DELETE'
    if (left.entry.byte_count, left.entry.sha256) != (right.entry.byte_count, right.entry.sha256):
        return 'MODIFY'
    if left.entry.mode != right.entry.mode:
        return 'MODE'
    return None


def _diff(path, change, left, right):
    return {
        'path': path,
        'change': change,
        'before_size': None if left is None else left.entry.byte_count,
        'after_size': None if right is None else right.entry.byte_count,
        'before_mode': None if left is None else left.entry.mode,
        'after_mode': None if right is None else right.entry.mode,
        'binary': (left is not None and left.binary) or (right is not None and right.binary),
    }


def _chunk(request, member):
    raw = None if member is None else member.chunk
    if member is not None and raw is None:
        raise StorageUnavailable('Original candidate chunk was not observed')
    total = None if member is None else member.entry.byte_count
    length = 0 if raw is None else len(raw)
    following = request.offset + length
    return {
        'candidate_id': request.candidate_id,
        'path': request.path,
        'offset': request.offset,
        'length': length,
        'total_bytes': total,
        'content_base64': None if raw is None else b64encode(raw).decode('ascii'),
        'next_offset': following if total is not None and following < total else None,
    }


def read_file(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        candidate = _candidate(connection, request)
    if candidate is None:
        return NOT_FOUND
    _, original = candidate
    after = _Files(request, 'AFTER', all_paths=False)
    failure = _read_after(original, after, lambda: False)
    if failure is not None:
        return failure
    member = after.files.get(request.path)
    return NOT_FOUND if member is None else _ready(_chunk(request, member))


def read_comparison(runtime, request, worker, cancelled):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        candidate = _candidate(connection, request)
        if candidate is None:
            return NOT_FOUND
        row, original = candidate
        snapshot = read_registered_baseline(connection, row['base_snapshot_id'])
        if snapshot is None:
            raise StorageUnavailable('Original candidate baseline is missing')
        snapshot = dict(snapshot)
    before = _Files(request, 'BEFORE', all_paths=True)
    after = _Files(request, 'AFTER', all_paths=True)
    failure = _read_after(original, after, cancelled.is_set)
    if failure is None:
        failure = _read_before(worker, snapshot, before, cancelled)
    if failure is not None:
        return failure
    if isinstance(request, ChunkRequest):
        left = before.files.get(request.path)
        right = after.files.get(request.path)
        if left is None and right is None or _changed(left, right) is None:
            return NOT_FOUND
        selected = left if request.side == 'BEFORE' else right
        return _ready(
            {
                **_chunk(request, selected),
                'side': request.side,
                'exists': selected is not None,
                'delivery_plan_id': None,
            }
        )
    paths = sorted(before.files.keys() | after.files.keys(), key=lambda path: path.encode('utf-8'))
    items = []
    for path in paths:
        left, right = before.files.get(path), after.files.get(path)
        change = _changed(left, right)
        if change is not None:
            items.append(_diff(path, change, left, right))
    start = page_offset(request.page)
    return _ready(
        {**page_metadata(request.page, len(items)), 'items': items[start : start + PAGE_SIZE]}
    )


def _project_diff(value):
    item = exact(value, _DIFF_FIELDS)
    relative_content_path(item['path'])
    change = strict_enum(item['change'], 'change', ('ADD', 'MODIFY', 'DELETE', 'MODE'))
    strict_boolean(item['binary'], 'binary')
    for side, missing in (('before', change == 'ADD'), ('after', change == 'DELETE')):
        count, mode = item[side + '_size'], item[side + '_mode']
        if missing:
            if count is not None or mode is not None:
                raise ValueError('Missing original comparison side has content')
        else:
            strict_integer(count, side + '_size', minimum=0)
            content_file_mode(mode)
    if change == 'MODE' and (
        item['before_mode'] == item['after_mode'] or item['before_size'] != item['after_size']
    ):
        raise ValueError('Original comparison mode change differs')
    return item


def _project_chunk(value, request, *, delivery_plan_id=None):
    fields = _CHUNK_FIELDS
    if request.side is not None:
        fields = (*fields, 'side', 'exists', 'delivery_plan_id')
    item = exact(value, fields)
    if (
        strict_integer(item['candidate_id'], 'candidate_id') != request.candidate_id
        or relative_content_path(item['path']) != request.path
        or strict_integer(item['offset'], 'offset', minimum=0) != request.offset
    ):
        raise ValueError('Original candidate chunk scope differs')
    length = strict_integer(item['length'], 'length', minimum=0, maximum=request.length)
    if request.side is not None:
        if item['side'] != request.side or item['delivery_plan_id'] != delivery_plan_id:
            raise ValueError('Original comparison side differs')
        if not strict_boolean(item['exists'], 'exists'):
            if length or any(
                item[field] is not None
                for field in ('total_bytes', 'content_base64', 'next_offset')
            ):
                raise ValueError('Missing original comparison side has content')
            return item
    total = strict_integer(item['total_bytes'], 'total_bytes', minimum=0)
    encoded = item['content_base64']
    if type(encoded) is not str or len(encoded) > (_MAX_CHUNK + 2) // 3 * 4:
        raise ValueError('Original candidate chunk bytes differ')
    try:
        raw = b64decode(encoded, validate=True)
    except Base64Error as error:
        raise ValueError('Original candidate chunk bytes differ') from error
    following = request.offset + length
    if (
        b64encode(raw).decode('ascii') != encoded
        or len(raw) != length
        or length != min(max(0, total - request.offset), request.length)
        or item['next_offset'] != (following if following < total else None)
    ):
        raise ValueError('Original candidate chunk bounds differ')
    return item


class DiffResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        result, pagination = page(data, _project_diff, request.page)
        paths = [item['path'].encode('utf-8') for item in result['items']]
        if paths != sorted(set(paths)):
            raise ValueError('Original comparison paths differ')
        return result, pagination


class ChunkResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        return _project_chunk(data, request), None


async def _comparison(request, request_type, response_type):
    async def operation(started, cancelled, worker):
        def invoke(runtime, parsed):
            started.set()
            return read_comparison(runtime, parsed, worker, cancelled)

        return await handle_http(request, request_type, response_type, invoke)

    return await with_repository_request(request, operation)


@candidate_content_router.get(DETAIL + '/file')
async def candidate_file_http(request: Request):
    return await handle_http(request, ChunkRequest, ChunkResponse, read_file)


@candidate_content_router.get(DETAIL + '/diff')
async def candidate_diff_http(request: Request):
    return await _comparison(request, DiffRequest, DiffResponse)


@candidate_content_router.get(DETAIL + '/diff/file')
async def candidate_comparison_file_http(request: Request):
    return await _comparison(request, ComparisonRequest, ChunkResponse)
