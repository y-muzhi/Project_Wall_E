"""Original repository OperationView reads; GET never dispatches or scans Git.

Other operation families acquire their own projections when their producers are
implemented. No arbitrary stored JSON, private launch identity or source handle
is passed through this resource projection.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Request

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.http_boundary import handle_http, request_query
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    decimal_integer,
    reject,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .command_registry import REPOSITORY_OPERATIONS, registered_command
from .configuration_identities import require_schema
from .error_codes import ERROR_HTTP
from .operation_protocol import operation_steps
from .repository_acceptance import verify_saved_repository_acceptance
from .repository_baseline_input import BASELINE_INPUT_FIELDS
from .repository_baseline_validation import BaselineValidationProof, read_registered_baseline

STATES = ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED')
OPERATION_FIELDS = (
    'id',
    'task_id',
    'testing_task_id',
    'resource_kind',
    'resource_id',
    'session_id',
    'operation_type',
    'idempotency_key',
    'expected_state_version',
    'fixed_input',
    'control_generation',
    'status',
    'created_at',
    'started_at',
    'ended_at',
    'failure_code',
    'steps',
    'content_capture',
)
STEP_FIELDS = (
    'operation_id',
    'step_no',
    'step_type',
    'status',
    'external_identity',
    'fixed_input',
    'result_ref',
    'started_at',
    'ended_at',
    'last_observed_at',
)
PUBLIC_INPUT_FIELDS = {
    'REGISTER_REPOSITORY': ('name',),
    'REFRESH_REPOSITORY': ('repository_id',),
    'REGISTER_BASE': BASELINE_INPUT_FIELDS,
}
RESULT_FIELDS = {
    'REGISTER_REPOSITORY': 'repository_id',
    'REFRESH_REPOSITORY': 'observation_id',
    'REGISTER_BASE': 'snapshot_id',
}
repository_operation_router = APIRouter(prefix='/api/v1', redirect_slashes=False)


def is_repository_operation_path(path):
    return re.fullmatch(r'/api/v1/code-operations/[^/]+', path) is not None


def _time(value, *, nullable=True):
    if value is None and nullable:
        return
    if (
        type(value) is not str
        or datetime.fromisoformat(value).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        != value
    ):
        raise ValueError('Original UTC millisecond instant required')


def project_repository_operation(value):
    data = exact(value, OPERATION_FIELDS)
    for key in ('id', 'resource_id'):
        strict_integer(data[key], key)
    if data['resource_kind'] != 'REPOSITORY' or any(
        data[key] is not None
        for key in (
            'task_id',
            'testing_task_id',
            'session_id',
            'expected_state_version',
            'control_generation',
            'content_capture',
        )
    ):
        raise ValueError('Original repository operation owner differs')
    action = strict_enum(data['operation_type'], 'operation_type', tuple(PUBLIC_INPUT_FIELDS))
    path = '/api/v1/code-repositories'
    if action != 'REGISTER_REPOSITORY':
        suffix = 'snapshots' if action == 'REGISTER_BASE' else 'refresh'
        path += f'/{data["resource_id"]}/{suffix}'
    registered_command('POST', path, data['idempotency_key'])
    strict_enum(data['status'], 'status', STATES)
    _time(data['created_at'], nullable=False)
    for key in ('started_at', 'ended_at'):
        _time(data[key])
    if data['failure_code'] is not None and data['failure_code'] not in ERROR_HTTP:
        raise ValueError('Unregistered operation failure code')
    fixed = exact(data['fixed_input'], PUBLIC_INPUT_FIELDS[action])
    if action == 'REGISTER_REPOSITORY':
        if type(fixed['name']) is not str or not fixed['name'].strip() or '\0' in fixed['name']:
            raise ValueError('Original repository label required')
    elif strict_integer(fixed['repository_id'], 'repository_id') != data['resource_id']:
        raise ValueError('Original repository resource differs')
    if action == 'REGISTER_BASE':
        oid = fixed['commit_oid']
        if (
            type(oid) is not str
            or re.fullmatch('(?:[0-9a-f]{40}|[0-9a-f]{64})', oid) is None
            or set(oid) == {'0'}
        ):
            raise ValueError('Original fixed baseline commit differs')
        strict_integer(fixed['execution_profile_version_id'], 'execution_profile_version_id')
    expected = operation_steps('RESOURCE', action)
    if type(data['steps']) is not list or len(data['steps']) != len(expected):
        raise ValueError('Original complete steps required')
    result_key = RESULT_FIELDS[action]
    for number, (step_value, step_type) in enumerate(zip(data['steps'], expected, strict=True), 1):
        row = exact(step_value, STEP_FIELDS)
        if (
            row['operation_id'] != data['id']
            or row['step_no'] != number
            or row['step_type'] != step_type
        ):
            raise ValueError('Original step identity differs')
        strict_integer(row['operation_id'], 'operation_id')
        strict_integer(row['step_no'], 'step_no')
        strict_enum(row['status'], 'status', STATES)
        if row['fixed_input'] != fixed or row['external_identity'] not in (None, {}):
            raise ValueError('Private original input or identity leaked')
        for key in ('started_at', 'ended_at', 'last_observed_at'):
            _time(row[key])
        if row['result_ref'] is not None:
            result = exact(row['result_ref'], (result_key,))
            strict_integer(result[result_key], result_key)
            if number != len(expected) or row['status'] != 'SUCCEEDED':
                raise ValueError('Original result belongs to final successful step only')
            if action == 'REGISTER_REPOSITORY' and result[result_key] != data['resource_id']:
                raise ValueError('Original saved repository differs')
    if data['status'] == 'SUCCEEDED' and (
        any(row['status'] != 'SUCCEEDED' for row in data['steps'])
        or data['steps'][-1]['result_ref'] is None
    ):
        raise ValueError('Successful original operation has no complete result')
    return data


def _baseline_step_result(connection, operation, step, fixed, repository, result):
    if step['status'] != 'SUCCEEDED':
        raise ValueError('Unfinished baseline step cannot report a result')
    if step['step_no'] in (1, 3):
        proof = exact(result, tuple(BaselineValidationProof.__dataclass_fields__))
        if proof['commit_oid'] != fixed['commit_oid']:
            raise ValueError('Original validated commit differs')
        git_oid(proof['tree_oid'], repository['object_format'])
        if set(proof['tree_oid']) == {'0'}:
            raise ValueError('Original baseline tree differs')
        for key in ('repository_sha256', 'closure_sha256', 'content_sha256'):
            if type(proof[key]) is not str or re.fullmatch('[0-9a-f]{64}', proof[key]) is None:
                raise ValueError('Original baseline validation proof differs')
        return None
    if step['step_no'] == 2:
        evidence = exact(result, ('process', 'prepared', 'dispatch', 'committed', 'ref'))
        if any(type(value) is not dict for value in evidence.values()):
            raise ValueError('Original baseline pin evidence differs')
        return None
    if (
        step['step_no'] != len(operation_steps('RESOURCE', 'REGISTER_BASE'))
        or operation['status'] != 'SUCCEEDED'
    ):
        raise ValueError('Original baseline step has no registered public result')
    reference = exact(result, ('snapshot_id',))
    snapshot_id = strict_integer(reference['snapshot_id'], 'snapshot_id')
    found = read_registered_baseline(connection, snapshot_id)
    if (
        snapshot_id != fixed['snapshot_id']
        or found is None
        or found['registration_operation_id'] != operation['id']
    ):
        raise ValueError('Original saved baseline differs')
    return reference


def read_repository_operation(runtime, request):
    require_schema(runtime)
    try:
        with runtime.database.transaction() as connection:
            row = connection.execute(
                'SELECT * FROM code_operations WHERE id=?', (request.operation_id,)
            ).fetchone()
            if row is None:
                return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            if row['resource_kind'] == 'TASK':
                from .task_operation_reads import TASK_OPERATION_TYPES, public_task_operation

                if row['operation_type'] in TASK_OPERATION_TYPES:
                    return {
                        'code': 'READ_OK',
                        'data': public_task_operation(connection, row),
                        'details': None,
                    }
            if (
                row['resource_kind'] != 'REPOSITORY'
                or row['operation_type'] not in REPOSITORY_OPERATIONS.values()
            ):
                return {
                    'code': 'CONFIG_NOT_READY',
                    'data': None,
                    'details': {'capability_codes': ['Q20-GIT']},
                }
            action = row['operation_type']
            registration = action == 'REGISTER_REPOSITORY'
            verify_saved_repository_acceptance(connection, row)
            fixed = strict_json_object(row['fixed_input'])
            if action != 'REGISTER_BASE':
                expected_fields = {'name', 'root_path'} if registration else {'repository_id'}
                if set(fixed) != expected_fields:
                    raise ValueError('Original stored input fields differ')
            # No local path, preallocated snapshot identity or retained-ref name.
            public_input = {field: fixed[field] for field in PUBLIC_INPUT_FIELDS[action]}
            repository = connection.execute(
                'SELECT * FROM code_repositories WHERE id=?', (row['resource_id'],)
            ).fetchone()
            if (not registration or row['status'] == 'SUCCEEDED') and repository is None:
                raise ValueError('Original repository is missing')
            steps = []
            for step in connection.execute(
                'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                (row['id'],),
            ):
                if step['fixed_input'] != row['fixed_input']:
                    raise ValueError('Original frozen step input differs')
                result = (
                    None if step['result_ref'] is None else strict_json_object(step['result_ref'])
                )
                if (
                    action == 'REGISTER_BASE'
                    and step['step_no'] in (1, 2, 3)
                    and step['status'] == 'SUCCEEDED'
                    and result is None
                ):
                    raise ValueError('Original baseline step proof is missing')
                if result is not None:
                    if registration:
                        if repository is None or repository['name'] != fixed['name']:
                            raise ValueError('Original final repository differs')
                    elif action == 'REGISTER_BASE':
                        result = _baseline_step_result(
                            connection, row, step, fixed, repository, result
                        )
                    else:
                        reference = exact(result, ('observation_id',))
                        found = connection.execute(
                            'SELECT 1 FROM code_repository_observations WHERE id=? AND operation_id=? AND repository_id=?',
                            (reference['observation_id'], row['id'], row['resource_id']),
                        ).fetchone()
                        if found is None:
                            raise ValueError('Original final observation differs')
                # External launch and metadata identities are private; only progress is public.
                if step['external_identity'] is not None:
                    strict_json_object(step['external_identity'])
                steps.append(
                    {
                        **dict(step),
                        'external_identity': None if step['external_identity'] is None else {},
                        'fixed_input': public_input,
                        'result_ref': result,
                    }
                )
            data = project_repository_operation(
                {
                    **dict(row),
                    'fixed_input': public_input,
                    'steps': steps,
                    'content_capture': None,
                }
            )
            return {'code': 'READ_OK', 'data': data, 'details': None}
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise StorageUnavailable('Original repository operation storage is invalid') from error


@dataclass(frozen=True)
class ReadOperationRequest:
    operation_id: int

    @classmethod
    def parse(cls, request):
        request_query(request)
        if any(name.lower() == b'idempotency-key' for name, _ in request.scope.get('headers', [])):
            reject('Idempotency-Key', 'UNKNOWN_FIELD', '读取原操作不接收幂等请求头')
        return cls(decimal_integer(request.path_params['id'], 'id'))


class OperationResponse:
    error_contract = 'code'
    errors = frozenset(
        ('INVALID_INPUT', 'NOT_FOUND', 'CONFIG_NOT_READY', 'STORAGE_UNAVAILABLE', 'INTERNAL_ERROR')
    )

    @staticmethod
    def project(data, request):
        if data.get('resource_kind') == 'TASK':
            from .task_operation_reads import project_task_operation

            return project_task_operation(data, request.operation_id), None
        result = project_repository_operation(data)
        if result['id'] != request.operation_id:
            raise ValueError('Original operation identity differs')
        return result, None


@repository_operation_router.get('/code-operations/{id}')
async def repository_operation_http(request: Request):
    return await handle_http(
        request, ReadOperationRequest, OperationResponse, read_repository_operation
    )
