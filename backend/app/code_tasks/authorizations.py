"""Approved-unbound grants; actual task binding and application are separate."""

from datetime import datetime

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    current_operator_sid,
)
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    InvalidInput,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .authorization_scope import (
    STATUSES,
    parse_authorization_scope,
    profile_scope_error,
    resource_scope_error,
)
from .check_set_content import _text
from .check_set_versions import _invalid
from .configuration_identities import require_schema
from .execution_profile_versions import _project as project_profile

FIELDS = ('id', 'task_id', 'profile_version_id', 'scope', 'status', 'approved_at', 'actor_ref')


def approve_authorization(runtime, request):
    require_schema(runtime)
    unavailable = None

    def save(connection):
        nonlocal unavailable
        require_write_transaction(connection)
        row = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?',
            (request.profile_version_id,),
        ).fetchone()
        if row is None:
            return Rejection('NOT_FOUND', None)
        scope = request.scope.value()
        try:
            snapshots = {}
            profile = project_profile(row, connection, runtime.catalog, snapshots)
            missing = profile_scope_error(scope, profile) or resource_scope_error(
                scope, snapshots['execution']
            )
        except ConfigInvalid as error:
            unavailable = 'Q20-CONFIG'
            raise StorageUnavailable('Authorization resource catalogue unavailable') from error
        if missing is not None:
            return _invalid(missing)
        high_water = connection.execute(
            "SELECT last_value FROM sequences WHERE entity_kind='AuthorizationGrant'"
        ).fetchone()
        if high_water is not None and high_water[0] == MAX_SAFE_INTEGER:
            return Rejection('PRECONDITION_FAILED', empty_conflict())
        try:
            # Existing native identity reader rejects impersonation/AppContainer.
            # It only queries the current operator; no privilege or ACL changes.
            actor = current_operator_sid()
        except PackageSecurityError as error:
            unavailable = 'Q20-WINDOWS'
            raise StorageUnavailable('Trusted approval identity unavailable') from error
        identity = entity_id(connection, EntityKind.AUTHORIZATION_GRANT)
        connection.execute(
            "INSERT INTO code_authorizations(id,task_id,profile_version_id,scope,status,approved_at,actor_ref) VALUES(?,NULL,?,?,'APPROVED_UNBOUND',?,?)",
            (identity, request.profile_version_id, compact(scope), operation_time(None), actor),
        )
        return Success(
            {
                'code': 'CREATED',
                'data': {'resource_kind': 'AUTHORIZATION', 'resource_id': identity},
                'details': None,
            },
            201,
        )

    result = execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )
    if unavailable is not None and result['code'] == 'STORAGE_UNAVAILABLE':
        result['details'] = {'capability_codes': [unavailable]}
    return result


def project_grant(row):
    data = dict(row)
    try:
        for key in ('id', 'profile_version_id'):
            strict_integer(data[key], key)
        if data['task_id'] is not None:
            strict_integer(data['task_id'], 'task_id')
        strict_enum(data['status'], 'status', STATUSES)
        if data['status'] == 'APPROVED_UNBOUND' and data['task_id'] is not None:
            raise ValueError('Unbound grant cannot have a task')
        if data['status'] not in ('APPROVED_UNBOUND', 'RETIRED') and data['task_id'] is None:
            raise ValueError('Bound grant must have its original task')
        if type(data['scope']) is not str or len(data['scope']) > HTTP_REQUEST_BYTES:
            raise ValueError('Stored scope exceeds capacity')
        raw = strict_json_object(data['scope'])
        scope = parse_authorization_scope(raw, max_input_bytes=HTTP_REQUEST_BYTES).value()
        if scope != raw:
            raise ValueError('Stored scope must not be normalized')
        data['scope'] = scope
        _text(data['actor_ref'], 'actor_ref', HTTP_REQUEST_BYTES)
        if (
            datetime.fromisoformat(data['approved_at'])
            .isoformat(timespec='milliseconds')
            .replace('+00:00', 'Z')
            != data['approved_at']
        ):
            raise ValueError('Invalid authorization timestamp')
    except (InvalidInput, ValueError, TypeError, KeyError) as error:
        raise StorageUnavailable('Stored authorization is invalid') from error
    return data


def _project(row, connection, catalog, snapshots):
    data = project_grant(row)
    identity = data['profile_version_id']
    profiles = snapshots.setdefault('profiles', {})
    if identity not in profiles:
        profile = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?', (identity,)
        ).fetchone()
        if profile is None:
            raise StorageUnavailable('Authorization profile is missing')
        profiles[identity] = project_profile(
            profile, connection, catalog, snapshots.setdefault('resources', {})
        )
    if profile_scope_error(data['scope'], profiles[identity]) is not None:
        raise StorageUnavailable('Stored grant exceeds original profile')
    return data


def read_authorization(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM code_authorizations WHERE id=?', (request.authorization_id,)
        ).fetchone()
        if row is None:
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        try:
            data = _project(row, connection, runtime.catalog, {})
        except ConfigInvalid:
            return {
                'code': 'CONFIG_NOT_READY',
                'data': None,
                'details': {'capability_codes': ['Q20-CONFIG']},
            }
    return {'code': 'READ_OK', 'data': data, 'details': None}


def list_authorizations(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            request.task_id is not None
            and connection.execute(
                'SELECT 1 FROM code_tasks WHERE id=?', (request.task_id,)
            ).fetchone()
            is None
        ):
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        clauses = []
        parameters = []
        for field, value in (('task_id', request.task_id), ('status', request.status)):
            if value is not None:
                clauses.append(field + '=?')
                parameters.append(value)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        total = connection.execute(
            'SELECT count(*) FROM code_authorizations' + where, parameters
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM code_authorizations'
            + where
            + ' ORDER BY approved_at DESC,id DESC LIMIT 20 OFFSET ?',
            (*parameters, (request.page - 1) * 20),
        ).fetchall()
        try:
            snapshots = {}
            items = [_project(row, connection, runtime.catalog, snapshots) for row in rows]
        except ConfigInvalid:
            return {
                'code': 'CONFIG_NOT_READY',
                'data': None,
                'details': {'capability_codes': ['Q20-CONFIG']},
            }
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
