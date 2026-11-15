"""Read the original private candidate under its exact task and content seal."""

import re
from dataclasses import dataclass
from time import monotonic

from fastapi import APIRouter, Request

from backend.app.infrastructure.content_manifest import CONTENT_POLICY, git_oid
from backend.app.infrastructure.content_package import verify_candidate_package
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.http_boundary import handle_http
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import MAX_PAGE, PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import decimal_integer, strict_enum, strict_integer

from .configuration_identities import require_schema
from .repository_operations import _time
from .repository_reads import ERRORS
from .task_candidate_commit import check_stored_candidate_seal, read_stored_candidate_package
from .task_read_query import read_task_query

PATH = '/api/v1/code-tasks/{task_id}/candidates'
FIELDS = (
    'id',
    'task_id',
    'base_snapshot_id',
    'capture_operation_id',
    'content_tree_oid',
    'parent_candidate_id',
    'role',
    'control_generation',
    'content_policy_version',
    'manifest_sha256',
    'captured_at',
    'published_for_testing_at',
    'publication_operation_id',
    'file_count',
    'byte_count',
    'created_at',
)
NOT_FOUND = {'code': 'NOT_FOUND', 'data': None, 'details': None}
NOT_READY = {'code': 'CONTENT_NOT_READY', 'data': None, 'details': empty_conflict()}
candidate_read_router = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class ListCandidatesRequest:
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
class ReadCandidateRequest:
    task_id: int
    candidate_id: int

    @classmethod
    def parse(cls, request):
        read_task_query(request)
        return cls(
            decimal_integer(request.path_params['task_id'], 'task_id'),
            decimal_integer(request.path_params['candidate_id'], 'candidate_id'),
        )


def _project(value, task_id):
    row = exact(value, FIELDS)
    for key in ('id', 'task_id', 'base_snapshot_id', 'capture_operation_id', 'control_generation'):
        strict_integer(row[key], key)
    for key in ('parent_candidate_id', 'publication_operation_id'):
        if row[key] is not None:
            strict_integer(row[key], key)
    for key in ('file_count', 'byte_count'):
        strict_integer(row[key], key, minimum=0)
    if row['task_id'] != task_id or row['id'] == row['parent_candidate_id']:
        raise ValueError('Candidate identity differs')
    if type(row['content_tree_oid']) is not str:
        raise ValueError('Original candidate tree identity differs')
    git_oid(row['content_tree_oid'], 'sha1' if len(row['content_tree_oid']) == 40 else 'sha256')
    strict_enum(row['role'], 'role', ('BACKEND', 'FRONTEND', 'INTEGRATION'))
    strict_enum(row['content_policy_version'], 'content_policy_version', (CONTENT_POLICY,))
    if (
        type(row['manifest_sha256']) is not str
        or re.fullmatch('[0-9a-f]{64}', row['manifest_sha256']) is None
    ):
        raise ValueError('Candidate manifest digest differs')
    for key in ('captured_at', 'created_at'):
        _time(row[key], nullable=False)
    published = row['published_for_testing_at']
    _time(published)
    if (
        row['captured_at'] > row['created_at']
        or (published is None) != (row['publication_operation_id'] is None)
        or (published is not None and published < row['created_at'])
    ):
        raise ValueError('Candidate chronology differs')
    return row


def _saved(connection, row):
    try:
        package = read_stored_candidate_package(connection, row)
        projected = _project({key: row[key] for key in FIELDS}, row['task_id'])
    except (KeyError, TypeError, ValueError) as error:
        raise StorageUnavailable('Original candidate row differs') from error
    return projected, package


def _verify_package(original, *, consume_file=None, active=lambda: None):
    identity = original.directory
    with PrivatePackageGuard(identity.canonical_path) as package:
        if (
            package.path.name != original.binding.package_name(staged=False)
            or package.verify() != identity
        ):
            raise StorageUnavailable('Original candidate package identity differs')
        sealed = verify_candidate_package(
            package,
            original.binding,
            limits=original.limits,
            git_limits=original.git_limits,
            started_at=monotonic(),
            active=active,
            consume_file=consume_file,
        )
        check_stored_candidate_seal(original, sealed)
    return sealed


def _available(original):
    try:
        _verify_package(original)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def list_candidates(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute('SELECT 1 FROM code_tasks WHERE id=?', (request.task_id,)).fetchone()
            is None
        ):
            return NOT_FOUND
        total = connection.execute(
            'SELECT count(*) FROM code_candidates WHERE task_id=?', (request.task_id,)
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM code_candidates WHERE task_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
            (request.task_id, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        records = [_saved(connection, row) for row in rows]
    if any(not _available(original) for _, original in records):
        return NOT_READY
    data = {**page_metadata(request.page, total), 'items': [row for row, _ in records]}
    return {'code': 'READ_OK', 'data': data, 'details': None}


def read_candidate(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
            (request.candidate_id, request.task_id),
        ).fetchone()
        if row is None:
            return NOT_FOUND
        data, original = _saved(connection, row)
    if not _available(original):
        return NOT_READY
    return {'code': 'READ_OK', 'data': data, 'details': None}


class CandidateListResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        return page(data, lambda item: _project(item, request.task_id), request.page)


class CandidateResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        result = _project(data, request.task_id)
        if result['id'] != request.candidate_id:
            raise ValueError('Original candidate id differs')
        return result, None


@candidate_read_router.get(PATH)
async def list_candidates_http(request: Request):
    return await handle_http(request, ListCandidatesRequest, CandidateListResponse, list_candidates)


@candidate_read_router.get(PATH + '/{candidate_id}')
async def read_candidate_http(request: Request):
    return await handle_http(request, ReadCandidateRequest, CandidateResponse, read_candidate)
