"""Saved repository reads, with a narrow settings-only path projection."""

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.windows_local_paths import PathBoundaryError, local_absolute_path
from backend.app.shared.http_boundary import handle_http, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.validation import (
    decimal_integer,
    normalize_text,
    reject,
    strict_enum,
    strict_integer,
)

from .configuration_identities import require_schema
from .repository_operations import _time

PATH = '/code-repositories'
FIELDS = ('id', 'name', 'object_format', 'created_at', 'root_path', 'latest_observation')
ERRORS = frozenset(
    {
        'INVALID_INPUT',
        'NOT_FOUND',
        'CONTENT_NOT_READY',
        'CONFIG_NOT_READY',
        'STORAGE_UNAVAILABLE',
        'INTERNAL_ERROR',
    }
)
VIEW = """
SELECT r.id,r.name,r.object_format,r.created_at,
       CASE WHEN ? THEN r.canonical_root ELSE NULL END AS root_path,
       o.id AS observation_id,o.status AS observation_status,o.observed_at,
       op.resource_kind AS owner_kind,op.resource_id AS owner_id,
       op.operation_type,op.task_id,op.testing_task_id
FROM code_repositories AS r
LEFT JOIN code_repository_observations AS o ON o.id=(
    SELECT recent.id FROM code_repository_observations AS recent
    WHERE recent.repository_id=r.id
    ORDER BY recent.observed_at DESC,recent.id DESC LIMIT 1
)
LEFT JOIN code_operations AS op ON op.id=o.operation_id
"""

repository_read_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_repository_read_path(path):
    return re.fullmatch(r'/api/v1/code-repositories(?:/[^/]+)?', path) is not None


def project_repository(value, *, settings_detail):
    data = exact(value, FIELDS)
    strict_integer(data['id'], 'id')
    name = data['name']
    if type(name) is not str or not name or '\0' in name or normalize_text(name) != name:
        raise ValueError('Original repository name required')
    strict_enum(data['object_format'], 'object_format', ('sha1', 'sha256'))
    _time(data['created_at'], nullable=False)
    path = data['root_path']
    if settings_detail:
        if type(path) is not str or str(local_absolute_path(path)) != path:
            raise ValueError('Original repository root required')
    elif path is not None:
        raise ValueError('Repository list must not disclose a root path')
    if data['latest_observation'] is not None:
        latest = exact(data['latest_observation'], ('id', 'status', 'observed_at'))
        strict_integer(latest['id'], 'latest_observation.id')
        strict_enum(latest['status'], 'status', ('READABLE', 'UNAVAILABLE', 'UNKNOWN'))
        _time(latest['observed_at'], nullable=False)
        data['latest_observation'] = latest
    return data


def _read_row(row, *, settings_detail):
    latest = None
    if row['observation_id'] is not None:
        if (
            row['owner_kind'] != 'REPOSITORY'
            or row['owner_id'] != row['id']
            or row['operation_type'] != 'REFRESH_REPOSITORY'
            or row['task_id'] is not None
            or row['testing_task_id'] is not None
        ):
            raise StorageUnavailable('Stored latest observation owner is invalid')
        latest = {
            'id': row['observation_id'],
            'status': row['observation_status'],
            'observed_at': row['observed_at'],
        }
    try:
        return project_repository(
            {**{field: row[field] for field in FIELDS[:-1]}, 'latest_observation': latest},
            settings_detail=settings_detail,
        )
    except (ValueError, TypeError, UnicodeError, PathBoundaryError) as error:
        raise StorageUnavailable('Stored repository view is invalid') from error


def list_repositories(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        total = connection.execute('SELECT count(*) FROM code_repositories').fetchone()[0]
        rows = connection.execute(
            VIEW + 'ORDER BY r.created_at DESC,r.id DESC LIMIT 20 OFFSET ?',
            (False, (request.page - 1) * 20),
        ).fetchall()
        items = [_read_row(row, settings_detail=False) for row in rows]
    return {
        'code': 'READ_OK',
        'data': {
            'items': items,
            'page': request.page,
            'page_size': 20,
            'total': total,
            'total_pages': (total + 19) // 20,
        },
        'details': None,
    }


def read_repository(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(VIEW + 'WHERE r.id=?', (True, request.repository_id)).fetchone()
        if row is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        return {'code': 'READ_OK', 'data': _read_row(row, settings_detail=True), 'details': None}


def _query(request, *, singles=()):
    if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
        reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取仓库不接收幂等请求头')
    return request_query(request, singles=singles)


@dataclass(frozen=True)
class ListRepositoriesRequest:
    page: int

    @classmethod
    def parse(cls, request):
        query = _query(request, singles=('page',))
        return cls(decimal_integer(query.get('page', '1'), 'page', 100000))


@dataclass(frozen=True)
class ReadRepositoryRequest:
    repository_id: int

    @classmethod
    def parse(cls, request):
        _query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


class RepositoryListResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        return page(
            data, lambda item: project_repository(item, settings_detail=False), request.page
        )


class RepositoryResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        result = project_repository(data, settings_detail=True)
        if result['id'] != request.repository_id:
            raise ValueError('Original repository identity differs')
        return result, None


@repository_read_router.get(PATH)
async def repositories_http(request: Request):
    return await handle_http(
        request, ListRepositoriesRequest, RepositoryListResponse, list_repositories
    )


@repository_read_router.get(PATH + '/{id}')
async def repository_http(request: Request):
    return await handle_http(request, ReadRepositoryRequest, RepositoryResponse, read_repository)
