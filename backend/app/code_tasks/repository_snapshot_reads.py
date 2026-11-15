"""Public projections of a registered baseline and its live, fixed Git contents."""

import asyncio
import re
from contextlib import suppress
from dataclasses import dataclass
from threading import Event

from fastapi import APIRouter, Request

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.content_paths import relative_content_path
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_baseline_ref_guard import BaselineRefConflict
from backend.app.infrastructure.git_config_command import ConfigCommandError
from backend.app.infrastructure.git_local_config import GitConfigError
from backend.app.infrastructure.git_ref_metadata import RefMetadataError
from backend.app.infrastructure.git_ref_protocol import RefProtocolError
from backend.app.infrastructure.git_repository_location import RepositoryLocationError
from backend.app.infrastructure.git_repository_metadata import MetadataTreeError
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_guard_pipe import GuardPipeError
from backend.app.infrastructure.windows_guard_pipe_io import PipeIOError
from backend.app.infrastructure.windows_guard_service import GuardServiceError
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadError
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import ConfigurationNotReady
from backend.app.shared.http_boundary import handle_http, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.validation import decimal_integer, reject, strict_enum, strict_integer

from .configuration_identities import require_schema
from .repository_baseline_query import BaselineQueryResult, BaselineSnapshotMissing
from .repository_baseline_validation import read_registered_baseline
from .repository_git_runner import BASELINE_INPUT_ERRORS
from .repository_operations import _time
from .repository_reads import ERRORS
from .repository_registration_worker import RepositoryRegistrationWorker, SnapshotQueryUnavailable

PATH = '/code-snapshots'
PAGE_SIZE = 20
SNAPSHOT_FIELDS = (
    'id',
    'repository_id',
    'registration_operation_id',
    'content_profile_version_id',
    'commit_oid',
    'content_tree_oid',
    'content_policy_version',
    'registered_at',
    'created_at',
)
FILE_FIELDS = ('path', 'mode', 'blob_oid', 'byte_count')
SOURCE_ERRORS = (
    BaselineRefConflict,
    ConfigCommandError,
    ConfigReadError,
    GitConfigError,
    MetadataTreeError,
    PathBoundaryError,
    RefMetadataError,
    RefProtocolError,
    RepositoryLocationError,
    WorktreeHeadError,
    *BASELINE_INPUT_ERRORS,
)
GUARD_ERRORS = (
    GuardPipeError,
    GuardServiceError,
    LaunchOutcomeUnknown,
    PipeIOError,
    SnapshotQueryUnavailable,
)

repository_snapshot_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_repository_snapshot_path(path):
    return re.fullmatch(r'/api/v1/code-snapshots/[^/]+(?:/files)?', path) is not None


def _project_snapshot(value):
    data = exact(value, (*SNAPSHOT_FIELDS, 'ready', 'reason_codes'))
    for field in SNAPSHOT_FIELDS[:4]:
        strict_integer(data[field], field)
    oid = data['commit_oid']
    if type(oid) is not str:
        raise ValueError('Original snapshot commit is invalid')
    format = 'sha1' if len(oid) == 40 else 'sha256'
    for field in ('commit_oid', 'content_tree_oid'):
        git_oid(data[field], format)
        if set(data[field]) == {'0'}:
            raise ValueError('Original snapshot object is zero')
    strict_enum(data['content_policy_version'], 'content_policy_version', ('GIT20-BASELINE-1',))
    for field in ('registered_at', 'created_at'):
        _time(data[field], nullable=False)
    if data['created_at'] < data['registered_at'] or type(data['ready']) is not bool:
        raise ValueError('Original snapshot times or readiness differ')
    if data['reason_codes'] != ([] if data['ready'] else ['CONTENT_NOT_READY']):
        raise ValueError('Original snapshot readiness causes differ')
    return data


def _project_file(value):
    data = exact(value, FILE_FIELDS)
    relative_content_path(data['path'])
    strict_enum(data['mode'], 'mode', ('100644', '100755'))
    oid = data['blob_oid']
    if type(oid) is not str:
        raise ValueError('Original snapshot blob is invalid')
    git_oid(oid, 'sha1' if len(oid) == 40 else 'sha256')
    if set(oid) == {'0'}:
        raise ValueError('Original snapshot blob is zero')
    strict_integer(data['byte_count'], 'byte_count', minimum=0)
    return data


def _failure(code, details=None):
    return {'code': code, 'data': None, 'details': details}


def _snapshot(runtime, request, worker, cancelled):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = read_registered_baseline(connection, request.snapshot_id)
    if row is None:
        return _failure('NOT_FOUND')
    if type(worker) is not RepositoryRegistrationWorker:
        return _failure('CONFIG_NOT_READY', {'capability_codes': ['Q20-WINDOWS', 'Q20-GIT']})
    try:
        queried = worker.read_snapshot(request.snapshot_id, cancelled=cancelled)
        if type(queried) is not BaselineQueryResult or queried.snapshot != dict(row):
            raise StorageUnavailable('Original queried baseline differs')
        entries = queried.entries
    except BaselineSnapshotMissing:
        return _failure('NOT_FOUND')
    except ConfigurationNotReady as error:
        return _failure('CONFIG_NOT_READY', error.details)
    except ConfigInvalid:
        return _failure('CONFIG_NOT_READY', {'capability_codes': ['Q20-CONTENT']})
    except GUARD_ERRORS:
        return _failure('CONFIG_NOT_READY', {'capability_codes': ['Q20-WINDOWS', 'Q20-GIT']})
    except SOURCE_ERRORS:
        entries = None
    if type(request) is SnapshotRequest:
        data = {field: row[field] for field in SNAPSHOT_FIELDS}
        data['ready'] = entries is not None
        data['reason_codes'] = [] if data['ready'] else ['CONTENT_NOT_READY']
    else:
        if entries is None:
            return _failure(
                'CONTENT_NOT_READY',
                {
                    **empty_conflict(),
                    'related_entity_kind': 'SNAPSHOT',
                    'related_entity_id': row['id'],
                },
            )
        total = len(entries)
        start = (request.page - 1) * PAGE_SIZE
        data = {
            'items': [
                {field: getattr(entry, field) for field in FILE_FIELDS}
                for entry in entries[start : start + PAGE_SIZE]
            ],
            'page': request.page,
            'page_size': PAGE_SIZE,
            'total': total,
            'total_pages': (total + PAGE_SIZE - 1) // PAGE_SIZE,
        }
    return {'code': 'READ_OK', 'data': data, 'details': None}


def _query(request, *, singles=()):
    if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
        reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取基线不接收幂等请求头')
    return request_query(request, singles=singles)


@dataclass(frozen=True)
class SnapshotRequest:
    snapshot_id: int

    @classmethod
    def parse(cls, request):
        _query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


@dataclass(frozen=True)
class SnapshotFilesRequest:
    snapshot_id: int
    page: int

    @classmethod
    def parse(cls, request):
        query = _query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['snapshot_id'], 'snapshot_id'),
            decimal_integer(query.get('page', '1'), 'page', 100000),
        )


class SnapshotResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        data = _project_snapshot(value)
        if data['id'] != request.snapshot_id:
            raise ValueError('Original snapshot identity differs')
        return data, None


class SnapshotFilesResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(value, request):
        data, pagination = page(value, _project_file, request.page)
        paths = [item['path'].encode('utf-8') for item in data['items']]
        if paths != sorted(set(paths)):
            raise ValueError('Original snapshot file ordering differs')
        return data, pagination


async def with_repository_request(request, operation):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    started, cancelled = Event(), Event()

    async def watch_disconnect():
        # The shared boundary consumes the request body before invoking the worker.
        while not started.is_set():
            await asyncio.sleep(0.05)
        while not await request.is_disconnected():
            await asyncio.sleep(0.05)
        cancelled.set()

    watcher = asyncio.create_task(watch_disconnect())
    try:
        return await operation(started, cancelled, worker)
    finally:
        cancelled.set()
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


async def _read(request, request_type, response_type):
    async def operation(started, cancelled, worker):
        def invoke(runtime, parsed):
            started.set()
            return _snapshot(runtime, parsed, worker, cancelled)

        return await handle_http(request, request_type, response_type, invoke)

    return await with_repository_request(request, operation)


@repository_snapshot_router.get(PATH + '/{id}')
async def snapshot_http(request: Request):
    return await _read(request, SnapshotRequest, SnapshotResponse)


@repository_snapshot_router.get(PATH + '/{snapshot_id}/files')
async def snapshot_files_http(request: Request):
    return await _read(request, SnapshotFilesRequest, SnapshotFilesResponse)
