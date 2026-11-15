"""Independent Testing policy versions and explicit unbound approvals."""

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.costs import format_money, parse_money
from backend.app.code_tasks.repository_operations import _time
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    current_operator_sid,
)
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    strict_enum,
    strict_integer,
    strict_json_loads,
)

from .policy_content import PROFILE_FIELDS, parse_profile, profile_resource_facts, resource_snapshot

PROFILE_VIEW_FIELDS = ('id', 'version', 'created_at', *PROFILE_FIELDS, 'ready', 'reason_codes')
AUTHORIZATION_VIEW_FIELDS = (
    'id',
    'testing_task_id',
    'profile_version_id',
    'scope_kind',
    'validation_id',
    'status',
    'budget_limit_cny',
    'actor_ref',
    'approved_at',
    'ready',
    'reason_codes',
)
_JSON_FIELDS = tuple(field for field in PROFILE_FIELDS if field != 'name')
_SCOPES = ('TASK', 'PACK_VALIDATION')
_AUTH_STATUSES = ('APPROVED_UNBOUND', 'EFFECTIVE', 'RETIRED')
NOT_FOUND = {'code': 'NOT_FOUND', 'data': None, 'details': None}


def _invalid(field, reason='RELATION'):
    return Rejection(
        'CHECK_CONFIGURATION_INVALID', {'field_errors': [{'field': field, 'reason': reason}]}
    )


def _ready_flags(value):
    flags = value['reason_codes']
    if (
        type(flags) is not list
        or any(type(flag) is not str or not flag for flag in flags)
        or flags != sorted(set(flags))
        or type(value['ready']) is not bool
        or value['ready'] != (not flags)
    ):
        raise ValueError('Original Testing readiness differs')


def project_profile_view(value):
    data = exact(value, PROFILE_VIEW_FIELDS)
    for key in ('id', 'version'):
        strict_integer(data[key], key)
    _time(data['created_at'], nullable=False)
    _ready_flags(data)
    fixed = {field: data[field] for field in PROFILE_FIELDS}
    if parse_profile(fixed) != fixed:
        raise ValueError('Original Testing profile is not canonical')
    return data


def project_authorization_view(value):
    data = exact(value, AUTHORIZATION_VIEW_FIELDS)
    for key in ('id', 'profile_version_id'):
        strict_integer(data[key], key)
    scope = strict_enum(data['scope_kind'], 'scope_kind', _SCOPES)
    status = strict_enum(data['status'], 'status', _AUTH_STATUSES)
    task = data['testing_task_id']
    validation = data['validation_id']
    for name, identity in (('testing_task_id', task), ('validation_id', validation)):
        if identity is not None:
            strict_integer(identity, name)
    limit = parse_money(data['budget_limit_cny'], 'budget_limit_cny')
    if (
        format_money(limit) != data['budget_limit_cny']
        or scope == 'PACK_VALIDATION'
        and (task is not None or limit != 0)
        or scope == 'TASK'
        and validation is not None
        or status == 'APPROVED_UNBOUND'
        and (task is not None or validation is not None)
        or status == 'EFFECTIVE'
        and task is None
        and validation is None
        or type(data['actor_ref']) is not str
        or not data['actor_ref']
        or status == 'RETIRED'
        and data['ready']
    ):
        raise ValueError('Original Testing authorization differs')
    _time(data['approved_at'], nullable=False)
    _ready_flags(data)
    return data


def _profile(connection, snapshot, row):
    data = dict(row)
    try:
        for field in _JSON_FIELDS:
            if field == 'model_binding' and data[field] is None:
                continue
            data[field] = strict_json_loads(data[field], field)
        content = {field: data[field] for field in PROFILE_FIELDS}
        _, readiness = profile_resource_facts(connection, content, snapshot)
        return project_profile_view({**data, **readiness})
    except (ValueError, TypeError, KeyError) as error:
        raise StorageUnavailable('Stored Testing profile is invalid') from error


def _authorization(connection, catalog, row):
    profile = connection.execute(
        'SELECT * FROM testing_profile_versions WHERE id=?', (row['profile_version_id'],)
    ).fetchone()
    if profile is None:
        raise StorageUnavailable('Original Testing authorization profile is missing')
    view = _profile(connection, resource_snapshot(catalog), profile)
    reasons = set(view['reason_codes'])
    if row['status'] == 'RETIRED':
        reasons.add('AUTHORIZATION_NOT_APPLICABLE')
    return project_authorization_view(
        {**dict(row), 'ready': not reasons, 'reason_codes': sorted(reasons)}
    )


def _execute(runtime, request, save):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def create_profile(runtime, request):
    def save(connection):
        content = request.content
        missing, readiness = profile_resource_facts(
            connection, content, resource_snapshot(runtime.catalog)
        )
        if missing is None:
            raise StorageUnavailable('Testing resource catalogue cannot be verified')
        if missing:
            return _invalid(missing[0])
        previous = connection.execute(
            'SELECT MAX(version) FROM testing_profile_versions WHERE name=?',
            (content['name'],),
        ).fetchone()[0]
        if previous == MAX_SAFE_INTEGER:
            return _invalid('name', 'RANGE')
        data = {
            'id': entity_id(connection, EntityKind.TESTING_PROFILE_VERSION),
            'version': 1 if previous is None else increment(previous),
            'created_at': operation_time(None),
            **content,
        }
        columns = ('id', 'version', 'created_at', *PROFILE_FIELDS)
        values = {
            **data,
            **{field: compact(data[field]) for field in _JSON_FIELDS if data[field] is not None},
        }
        connection.execute(
            'INSERT INTO testing_profile_versions('
            + ','.join(columns)
            + ') VALUES('
            + ','.join('?' for _ in columns)
            + ')',
            tuple(values[field] for field in columns),
        )
        return Success(
            {
                'code': 'CREATED',
                'data': project_profile_view({**data, **readiness}),
                'details': None,
            },
            201,
        )

    return _execute(runtime, request, save)


def create_authorization(runtime, request):
    def save(connection):
        profile = connection.execute(
            'SELECT * FROM testing_profile_versions WHERE id=?', (request.profile_version_id,)
        ).fetchone()
        if profile is None:
            return Rejection('NOT_FOUND', None)
        view = _profile(connection, resource_snapshot(runtime.catalog), profile)
        try:
            actor = current_operator_sid()
        except PackageSecurityError as error:
            raise StorageUnavailable('Trusted Testing approval identity unavailable') from error
        limit = parse_money(request.budget_limit_cny, 'budget_limit_cny')
        if request.scope_kind == 'PACK_VALIDATION' and limit != 0:
            return Rejection(
                'AUTHORIZATION_NOT_APPLICABLE',
                {
                    'task_id': None,
                    'authorization_id': None,
                },
            )
        data = {
            'id': entity_id(connection, EntityKind.TESTING_AUTHORIZATION),
            'profile_version_id': profile['id'],
            'scope_kind': request.scope_kind,
            'budget_limit_cny': format_money(limit),
            'actor_ref': actor,
            'approved_at': operation_time(None),
            'status': 'APPROVED_UNBOUND',
            'testing_task_id': None,
            'validation_id': None,
        }
        connection.execute(
            """INSERT INTO testing_authorizations(id,profile_version_id,scope_kind,budget_limit_cny,actor_ref,approved_at,status)
               VALUES(:id,:profile_version_id,:scope_kind,:budget_limit_cny,:actor_ref,:approved_at,:status)""",
            data,
        )
        return Success(
            {
                'code': 'CREATED',
                'data': project_authorization_view(
                    {**data, 'ready': view['ready'], 'reason_codes': view['reason_codes']}
                ),
                'details': None,
            },
            201,
        )

    return _execute(runtime, request, save)


def _success(value):
    return {'code': 'READ_OK', 'data': value, 'details': None}


def read_profile(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM testing_profile_versions WHERE id=?', (request.identity,)
        ).fetchone()
        return (
            NOT_FOUND
            if row is None
            else _success(_profile(connection, resource_snapshot(runtime.catalog), row))
        )


def list_profiles(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        where = ' WHERE name=?' if request.name is not None else ''
        values = () if request.name is None else (request.name,)
        total = connection.execute(
            'SELECT COUNT(*) FROM testing_profile_versions' + where, values
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM testing_profile_versions' + where + ' ORDER BY id LIMIT ? OFFSET ?',
            (*values, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        snapshot = resource_snapshot(runtime.catalog) if rows else None
        return _success(
            {
                **page_metadata(request.page, total),
                'items': [_profile(connection, snapshot, row) for row in rows],
            }
        )


def read_authorization(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM testing_authorizations WHERE id=?', (request.identity,)
        ).fetchone()
        return (
            NOT_FOUND if row is None else _success(_authorization(connection, runtime.catalog, row))
        )
