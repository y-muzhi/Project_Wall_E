"""Immutable execution configuration versions on the original command transaction."""

from datetime import datetime

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    InvalidInput,
    strict_integer,
    strict_json_object,
)

from .check_set_versions import _invalid
from .check_set_versions import _project as project_check_set
from .configuration_identities import require_schema
from .execution_profile_content import FIELDS, parse_execution_profile_content
from .execution_profile_resources import readiness, reference_error, resource_snapshot

VERSION_FIELDS = (
    'id',
    'profile_id',
    'version',
    *FIELDS,
    'created_at',
    'ready',
    'unresolved_capability_codes',
)
JSON_FIELDS = tuple(field for field in FIELDS if field != 'check_set_version_id')


def publish_execution_profile_version(runtime, request):
    require_schema(runtime)
    catalogue_unavailable = False

    def save(connection):
        nonlocal catalogue_unavailable
        require_write_transaction(connection)
        if (
            connection.execute(
                'SELECT 1 FROM code_execution_profiles WHERE id=?', (request.profile_id,)
            ).fetchone()
            is None
        ):
            return Rejection('NOT_FOUND', None)
        content = request.content.value()
        try:
            snapshot = resource_snapshot(runtime.catalog)
            missing = reference_error(connection, content, snapshot)
            if missing is None:
                check = connection.execute(
                    'SELECT * FROM code_check_set_versions WHERE id=?',
                    (content['check_set_version_id'],),
                ).fetchone()
                project_check_set(check, connection, runtime.catalog, {})
        except ConfigInvalid as error:
            catalogue_unavailable = True
            raise StorageUnavailable('Execution resource catalogue unavailable') from error
        if missing is not None:
            return _invalid(missing)
        previous = connection.execute(
            'SELECT MAX(version) FROM code_execution_profile_versions WHERE profile_id=?',
            (request.profile_id,),
        ).fetchone()[0]
        high_water = connection.execute(
            "SELECT last_value FROM sequences WHERE entity_kind='ExecutionProfileVersion'"
        ).fetchone()
        if previous == MAX_SAFE_INTEGER or (
            high_water is not None and high_water[0] == MAX_SAFE_INTEGER
        ):
            return Rejection('PRECONDITION_FAILED', empty_conflict())
        version = 1 if previous is None else increment(previous)
        identity = entity_id(connection, EntityKind.EXECUTION_PROFILE_VERSION)
        values = {
            field: (None if content[field] is None else compact(content[field]))
            for field in JSON_FIELDS
        }
        values.update(
            id=identity,
            profile_id=request.profile_id,
            version=version,
            created_at=operation_time(None),
            check_set_version_id=content['check_set_version_id'],
        )
        # Column names are fixed module constants, never client-controlled identifiers.
        columns = ('id', 'profile_id', 'version', *FIELDS, 'created_at')
        connection.execute(
            'INSERT INTO code_execution_profile_versions('
            + ','.join(columns)
            + ') VALUES('
            + ','.join('?' for _ in columns)
            + ')',
            tuple(values[field] for field in columns),
        )
        return Success(
            {
                'code': 'CREATED',
                'data': {'resource_kind': 'EXECUTION_PROFILE_VERSION', 'resource_id': identity},
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
    if catalogue_unavailable and result['code'] == 'STORAGE_UNAVAILABLE':
        result['details'] = {'capability_codes': ['Q20-CONFIG']}
    return result


def _project(row, connection, catalog, snapshots):
    data = dict(row)
    raw = {'check_set_version_id': data['check_set_version_id']}
    try:
        for field in JSON_FIELDS:
            encoded = data[field]
            if field == 'delivery' and encoded is None:
                raw[field] = None
            else:
                if type(encoded) is not str or len(encoded) > HTTP_REQUEST_BYTES:
                    raise ValueError('Stored execution configuration exceeds capacity')
                raw[field] = strict_json_object('{"value":' + encoded + '}')['value']
        content = parse_execution_profile_content(raw, max_input_bytes=HTTP_REQUEST_BYTES).value()
        if content != raw:
            raise ValueError('Stored execution configuration must not be normalized')
        for field in ('id', 'profile_id', 'version'):
            strict_integer(data[field], field)
        if (
            datetime.fromisoformat(data['created_at'])
            .isoformat(timespec='milliseconds')
            .replace('+00:00', 'Z')
            != data['created_at']
        ):
            raise ValueError('Invalid execution configuration timestamp')
        check = connection.execute(
            'SELECT * FROM code_check_set_versions WHERE id=?', (content['check_set_version_id'],)
        ).fetchone()
        if check is None or check['owner_module'] != 'CODING':
            raise ValueError('Execution configuration check set differs')
    except (ValueError, TypeError, KeyError, InvalidInput) as error:
        raise StorageUnavailable('Stored execution configuration is invalid') from error
    if 'execution' not in snapshots:
        snapshots['execution'] = resource_snapshot(catalog)
    checks = project_check_set(check, connection, catalog, snapshots.setdefault('checks', {}))
    facts = readiness(content, snapshots['execution'], checks)
    if reference_error(connection, content, snapshots['execution']) is not None:
        facts['unresolved_capability_codes'] = sorted(
            set(facts['unresolved_capability_codes']) | {'Q20-CONFIG'}
        )
    data.update(content)
    data.update(facts)
    return data


def read_execution_profile_version(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?', (request.version_id,)
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


def list_execution_profile_versions(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute(
                'SELECT 1 FROM code_execution_profiles WHERE id=?', (request.profile_id,)
            ).fetchone()
            is None
        ):
            return {'code': 'NOT_FOUND', 'data': None, 'details': None}
        total = connection.execute(
            'SELECT COUNT(*) FROM code_execution_profile_versions WHERE profile_id=?',
            (request.profile_id,),
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE profile_id=? ORDER BY version DESC,id DESC LIMIT 20 OFFSET ?',
            (request.profile_id, (request.page - 1) * 20),
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
