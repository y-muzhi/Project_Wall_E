"""Read one immutable original repository observation; no Git or disk scanning."""

import re
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Request

from backend.app.infrastructure.content_manifest import git_oid, object_format
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_ref_protocol import branch_namespace, branch_ref
from backend.app.infrastructure.windows_local_paths import PathBoundaryError, local_absolute_path
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES, handle_http, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    InvalidInput,
    decimal_integer,
    object_fields,
    reject,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .configuration_identities import require_schema

FIELDS = (
    'id',
    'repository_id',
    'operation_id',
    'head_commit',
    'local_branches',
    'worktrees',
    'observed_at',
    'status',
)
ERRORS = frozenset(('INVALID_INPUT', 'NOT_FOUND', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR'))
repository_observation_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_repository_observation_path(path):
    return re.fullmatch(r'/api/v1/code-repositories/[^/]+/observations/[^/]+', path) is not None


def _array(value):
    if type(value) is str:
        if len(value.encode('utf-8', errors='strict')) > HTTP_REQUEST_BYTES:
            raise ValueError('Stored observation exceeds capacity')
        value = strict_json_object('{"items":' + value + '}')['items']
    if type(value) is not list:
        raise ValueError('Observation array required')
    return value


def _oid(value, format, widths):
    if value is None:
        return None
    current = (
        format
        if format is not None
        else 'sha1'
        if type(value) is str and len(value) == 40
        else 'sha256'
    )
    git_oid(value, current)
    if set(value) == {'0'}:
        raise ValueError('Observation OID must not be zero')
    widths.add(len(value))
    return value


def project_observation(value, format=None):
    try:
        if format is not None:
            object_format(format)
        data = dict(object_fields(dict(value), 'observation', FIELDS, FIELDS))
        for key in ('id', 'repository_id', 'operation_id'):
            strict_integer(data[key], key)
        strict_enum(data['status'], 'status', ('READABLE', 'UNAVAILABLE', 'UNKNOWN'))
        moment = data['observed_at']
        if (
            type(moment) is not str
            or datetime.fromisoformat(moment)
            .isoformat(timespec='milliseconds')
            .replace('+00:00', 'Z')
            != moment
        ):
            raise ValueError('Observation time must be original UTC')
        widths = set()
        data['head_commit'] = _oid(data['head_commit'], format, widths)
        branches = []
        for item in _array(data['local_branches']):
            row = object_fields(
                item, 'branch', ('full_ref', 'commit_oid'), ('full_ref', 'commit_oid')
            )
            oid = _oid(row['commit_oid'], format, widths)
            if oid is None:
                raise ValueError('Branch commit required')
            branches.append({'full_ref': branch_ref(row['full_ref']), 'commit_oid': oid})
        names = branch_namespace(tuple(row['full_ref'] for row in branches))
        if len(set(names)) != len(names):
            raise ValueError('Duplicate observation branch')
        data['local_branches'] = branches
        paths, trees = set(), []
        for item in _array(data['worktrees']):
            row = object_fields(
                item,
                'worktree',
                ('canonical_path', 'head_commit', 'branch_ref'),
                ('canonical_path', 'head_commit', 'branch_ref'),
            )
            path = row['canonical_path']
            if (
                type(path) is not str
                or str(local_absolute_path(path)) != path
                or path.casefold() in paths
            ):
                raise ValueError('Original canonical worktree path required')
            paths.add(path.casefold())
            branch = None if row['branch_ref'] is None else branch_ref(row['branch_ref'])
            trees.append(
                {
                    'canonical_path': path,
                    'head_commit': _oid(row['head_commit'], format, widths),
                    'branch_ref': branch,
                }
            )
        if len(widths) > 1:
            raise ValueError('Mixed observation object formats')
        if data['status'] == 'READABLE':
            by_name = {row['full_ref']: row['commit_oid'] for row in branches}
            for tree in trees:
                if tree['branch_ref'] is not None and (
                    tree['branch_ref'] not in by_name
                    or by_name[tree['branch_ref']] != tree['head_commit']
                ):
                    raise ValueError('Readable worktree branch differs from original branches')
        data['worktrees'] = trees
        return data
    except (
        InvalidInput,
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        PathBoundaryError,
    ) as error:
        raise StorageUnavailable('Stored repository observation is invalid') from error


def read_repository_observation(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM code_repository_observations WHERE repository_id=? AND id=?',
            (request.repository_id, request.observation_id),
        ).fetchone()
        if row is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        repository = connection.execute(
            'SELECT object_format FROM code_repositories WHERE id=?', (request.repository_id,)
        ).fetchone()
        operation = connection.execute(
            'SELECT resource_kind,resource_id,task_id,testing_task_id FROM code_operations WHERE id=?',
            (row['operation_id'],),
        ).fetchone()
        if (
            repository is None
            or operation is None
            or operation['resource_kind'] != 'REPOSITORY'
            or operation['resource_id'] != request.repository_id
            or operation['task_id'] is not None
            or operation['testing_task_id'] is not None
        ):
            raise StorageUnavailable('Stored observation owner is invalid')
        data = project_observation(row, repository['object_format'])
    return {'code': 'READ_OK', 'data': data, 'details': None}


@dataclass(frozen=True)
class ReadObservationRequest:
    repository_id: int
    observation_id: int

    @classmethod
    def parse(cls, request):
        if any(key.lower() == b'idempotency-key' for key, _ in request.scope.get('headers', [])):
            reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取观察记录不接收幂等请求头')
        request_query(request)
        return cls(
            decimal_integer(request.path_params['repository_id'], 'repository_id'),
            decimal_integer(request.path_params['observation_id'], 'observation_id'),
        )


class ObservationResponse:
    error_contract = 'code'
    errors = ERRORS

    @staticmethod
    def project(data, request):
        result = project_observation(exact(data, FIELDS))
        if (
            result['id'] != request.observation_id
            or result['repository_id'] != request.repository_id
        ):
            raise ValueError('Original observation identity differs')
        return result, None


@repository_observation_router.get(
    '/code-repositories/{repository_id}/observations/{observation_id}'
)
async def repository_observation_http(request: Request):
    return await handle_http(
        request, ReadObservationRequest, ObservationResponse, read_repository_observation
    )
