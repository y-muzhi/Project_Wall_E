"""Testing plan identity, fixed design revisions, and manual draft lifecycle."""

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.code_tasks.repository_operations import _time
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    ordinary_text,
    reject,
    strict_enum,
    strict_integer,
    strict_json_loads,
)

from .asset_invalidation import invalidate_bound_tasks
from .pack_compile import CompileError, case_targets
from .plan_content import (
    BASIS_FIELDS,
    PLAN_FIELDS,
    invalid_basis,
    parse_plan_content,
    publication_gap,
)

PLAN_VIEW = ('id', 'name', 'created_at', 'versions_count')
VERSION_VIEW = (
    'id',
    'plan_id',
    'version',
    *PLAN_FIELDS,
    'status',
    'state_version',
    'created_at',
    'published_at',
    'revoked_at',
    'revocation_reason',
)
_EDITABLE = PLAN_FIELDS[4:]
_ABSENT = Rejection('NOT_FOUND', None)
_PLAN_SELECT = """SELECT p.*, (SELECT COUNT(*) FROM testing_plan_versions v WHERE v.plan_id=p.id)
                  AS versions_count FROM testing_plans p"""


def plan_name(value):
    name = ordinary_text(value, 'name', 1, 200)
    if '\0' in name:
        reject('name', 'INVALID_FORMAT', '计划名称不能包含空字符')
    return name


def project_plan(value):
    result = exact(value, PLAN_VIEW)
    strict_integer(result['id'], 'id')
    strict_integer(result['versions_count'], 'versions_count', minimum=0)
    _time(result['created_at'], nullable=False)
    if plan_name(result['name']) != result['name']:
        raise ValueError('Stored Testing plan name differs')
    return result


def project_version(value):
    result = exact(value, VERSION_VIEW)
    for key in ('id', 'plan_id', 'version', 'state_version'):
        strict_integer(result[key], key)
    status = strict_enum(result['status'], 'status', ('DRAFT', 'PUBLISHED', 'REVOKED'))
    created = result['created_at']
    published = result['published_at']
    revoked = result['revoked_at']
    _time(created, nullable=False)
    _time(published)
    _time(revoked)
    reason = result['revocation_reason']
    if (
        (status == 'DRAFT') != (published is None)
        or (status == 'REVOKED') != (revoked is not None)
        or (revoked is None) != (reason is None)
        or published is not None
        and published < created
        or revoked is not None
        and revoked < published
        or reason is not None
        and ordinary_text(reason, 'reason', 1, 2000) != reason
    ):
        raise ValueError('Stored Testing plan lifecycle differs')
    content = {key: result[key] for key in PLAN_FIELDS}
    if parse_plan_content(content) != content:
        raise ValueError('Stored Testing plan draft is not canonical')
    return result


def _stored(connection, row):
    value = dict(row)
    try:
        for field in _EDITABLE:
            value[field] = strict_json_loads(value[field], field)
        value['material_refs'] = [
            dict(ref)
            for ref in connection.execute(
                'SELECT document_id,revision_id FROM testing_plan_materials WHERE plan_version_id=? ORDER BY document_id',
                (value['id'],),
            )
        ]
        return project_version(value)
    except (TypeError, ValueError, KeyError) as error:
        raise StorageUnavailable('Stored Testing plan version is unreadable') from error


def _execute(runtime, request, apply):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        apply,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def _outcome(result, code, status):
    return Success({'code': code, 'data': result, 'details': None}, status)


def _read(result):
    return {'code': 'READ_OK', 'data': result, 'details': None}


def _input_error(code, field):
    return Rejection(code, {'field_errors': [{'field': field, 'reason': 'RELATION'}]})


def _conflict(code, version):
    return Rejection(
        code,
        {
            **empty_conflict(),
            'current_state_version': version['state_version'],
            'related_entity_kind': 'PLAN',
            'related_entity_id': version['plan_id'],
        },
    )


def create_plan(runtime, request):
    def apply(connection):
        plan_id = entity_id(connection, EntityKind.TEST_PLAN)
        connection.execute(
            'INSERT INTO testing_plans(id,name,created_at) VALUES(?,?,?)',
            (plan_id, request.name, operation_time(None)),
        )
        return _outcome({'plan_id': plan_id}, 'CREATED', 201)

    return _execute(runtime, request, apply)


def create_version(runtime, request):
    def apply(connection):
        plan = connection.execute(
            'SELECT id FROM testing_plans WHERE id=?', (request.identity,)
        ).fetchone()
        if plan is None:
            return _ABSENT
        content = request.content
        bad = invalid_basis(connection, content)
        if bad:
            return _input_error('BASIS_REF_INVALID', bad)
        previous = connection.execute(
            'SELECT MAX(version) FROM testing_plan_versions WHERE plan_id=?', (request.identity,)
        ).fetchone()[0]
        if previous == MAX_SAFE_INTEGER:
            return _input_error('INVALID_INPUT', 'plan_id')
        number = 1 if previous is None else increment(previous)
        value = insert_draft_version(
            connection, content, request.identity, number, operation_time(None)
        )
        return _outcome(project_version(value), 'CREATED', 201)

    return _execute(runtime, request, apply)


def insert_draft_version(connection, content, plan_id, number, at):
    value = {
        **content,
        'id': entity_id(connection, EntityKind.TEST_PLAN_VERSION),
        'plan_id': plan_id,
        'version': number,
        'created_at': at,
        'status': 'DRAFT',
        'state_version': 1,
        'published_at': None,
        'revoked_at': None,
        'revocation_reason': None,
    }
    connection.execute(
        """INSERT INTO testing_plan_versions(id,plan_id,version,requirement_id,document_id,design_revision_id,
           behaviors,cases,unresolved_questions,status,state_version,created_at)
           VALUES(:id,:plan_id,:version,:requirement_id,:document_id,:design_revision_id,
           :behaviors,:cases,:unresolved_questions,:status,:state_version,:created_at)""",
        {**value, **{field: compact(value[field]) for field in _EDITABLE}},
    )
    connection.executemany(
        'INSERT INTO testing_plan_materials(plan_version_id,document_id,revision_id) VALUES(?,?,?)',
        [
            (value['id'], item['document_id'], item['revision_id'])
            for item in value['material_refs']
        ],
    )
    return value


def _version(connection, identity):
    row = connection.execute(
        'SELECT * FROM testing_plan_versions WHERE id=?', (identity,)
    ).fetchone()
    return None if row is None else _stored(connection, row)


def _mutate(runtime, request, required_status, action):
    def apply(connection):
        current = _version(connection, request.identity)
        if current is None:
            return _ABSENT
        if current['state_version'] != request.expected:
            return _conflict('VERSION_CONFLICT', current)
        if current['status'] != required_status or current['state_version'] == MAX_SAFE_INTEGER:
            return _conflict('INVALID_STATE', current)
        result = action(connection, request, current)
        return (
            result
            if isinstance(result, Rejection)
            else _outcome(project_version(result), 'UPDATED', 200)
        )

    return _execute(runtime, request, apply)


def _save_draft(connection, request, current):
    content = request.content
    changed_basis = next((key for key in BASIS_FIELDS if current[key] != content[key]), None)
    if changed_basis is not None:
        return _input_error('BASIS_REF_INVALID', changed_basis)
    bad = invalid_basis(connection, content)
    if bad:
        return _input_error('BASIS_REF_INVALID', bad)
    version = increment(current['state_version'])
    saved = connection.execute(
        """UPDATE testing_plan_versions SET behaviors=?,cases=?,unresolved_questions=?,state_version=?
           WHERE id=? AND status='DRAFT' AND state_version=?""",
        (
            *[compact(content[key]) for key in _EDITABLE],
            version,
            current['id'],
            current['state_version'],
        ),
    )
    if saved.rowcount != 1:
        raise StorageUnavailable('Original draft changed before commit')
    return {**current, **content, 'state_version': version}


def save_draft(runtime, request):
    return _mutate(runtime, request, 'DRAFT', _save_draft)


def _save_lifecycle(connection, request, current, action):
    operation_id = entity_id(connection, EntityKind.OPERATION_RECORD)
    at = max(operation_time(None), current['published_at'] or current['created_at'])
    version = increment(current['state_version'])
    fixed = canonical_input(request.business_input())
    connection.execute(
        """INSERT INTO code_operations(id,resource_kind,resource_id,operation_type,idempotency_key,
           expected_state_version,fixed_input,status,created_at,started_at,ended_at)
           VALUES(?,'TEST_PLAN_VERSION',?,?,?,?,?,'SUCCEEDED',?,?,?)""",
        (
            operation_id,
            current['id'],
            action,
            request.idempotency_key,
            current['state_version'],
            fixed,
            at,
            at,
            at,
        ),
    )
    status = 'PUBLISHED' if action == 'PUBLISH_PLAN' else 'REVOKED'
    result = canonical_input(
        {'plan_version_id': current['id'], 'state_version': version, 'status': status}
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,result_ref,
           started_at,ended_at,last_observed_at) VALUES(?,?,?,'SUCCEEDED',?,?,?,?,?)""",
        [
            (operation_id, i, step, fixed, result, at, at, at)
            for i, step in enumerate(operation_steps('RESOURCE', action), 1)
        ],
    )
    published = at if status == 'PUBLISHED' else current['published_at']
    revoked = at if status == 'REVOKED' else None
    reason = request.reason if status == 'REVOKED' else None
    saved = connection.execute(
        """UPDATE testing_plan_versions SET status=?,state_version=?,published_at=?,revoked_at=?,revocation_reason=?
           WHERE id=? AND status=? AND state_version=?""",
        (
            status,
            version,
            published,
            revoked,
            reason,
            current['id'],
            current['status'],
            current['state_version'],
        ),
    )
    if saved.rowcount != 1:
        raise StorageUnavailable('Original plan lifecycle changed before commit')
    if status == 'REVOKED':
        invalidate_bound_tasks(connection, plan_version=current['id'])
    return {
        **current,
        'status': status,
        'state_version': version,
        'published_at': published,
        'revoked_at': revoked,
        'revocation_reason': reason,
    }


def _publish(connection, request, current, installation):
    bad = invalid_basis(connection, current, require_confirmed=True)
    if bad:
        return _input_error('BASIS_REF_INVALID', bad)
    if current['unresolved_questions'] or not current['behaviors']:
        return _conflict('INVALID_STATE', current)
    gap = publication_gap(current)
    if gap is not None:
        return _input_error('CHECK_CONFIGURATION_INVALID', gap)
    if current['cases']:
        if installation is None:
            return _input_error('CHECK_CONFIGURATION_INVALID', 'cases')
        try:
            case_targets(current, installation.targets)
        except CompileError as error:
            return _input_error('CHECK_CONFIGURATION_INVALID', error.field)
    return _save_lifecycle(connection, request, current, 'PUBLISH_PLAN')


def publish_plan(runtime, request):
    installation = getattr(runtime.catalog, 'testing_assets', None)
    return _mutate(
        runtime,
        request,
        'DRAFT',
        lambda connection, original, current: _publish(connection, original, current, installation),
    )


def _revoke(connection, request, current):
    return _save_lifecycle(connection, request, current, 'REVOKE_PLAN')


def revoke_plan(runtime, request):
    return _mutate(runtime, request, 'PUBLISHED', _revoke)


def read_plan(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(_PLAN_SELECT + ' WHERE p.id=?', (request.identity,)).fetchone()
        return _ABSENT.result if row is None else _read(project_plan(dict(row)))


def list_plans(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        where = ''
        args = ()
        if request.requirement_id is not None:
            where = ' WHERE EXISTS(SELECT 1 FROM testing_plan_versions v WHERE v.plan_id=p.id AND v.requirement_id=?)'
            args = (request.requirement_id,)
        total = connection.execute('SELECT COUNT(*) FROM testing_plans p' + where, args).fetchone()[
            0
        ]
        rows = connection.execute(
            _PLAN_SELECT + where + ' ORDER BY p.id LIMIT ? OFFSET ?',
            (*args, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        return _read(
            {
                **page_metadata(request.page, total),
                'items': [project_plan(dict(row)) for row in rows],
            }
        )


def read_version(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = _version(connection, request.identity)
        return _ABSENT.result if row is None else _read(row)


def list_versions(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute(
                'SELECT id FROM testing_plans WHERE id=?', (request.identity,)
            ).fetchone()
            is None
        ):
            return _ABSENT.result
        total = connection.execute(
            'SELECT COUNT(*) FROM testing_plan_versions WHERE plan_id=?', (request.identity,)
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM testing_plan_versions WHERE plan_id=? ORDER BY id LIMIT ? OFFSET ?',
            (request.identity, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        return _read(
            {
                **page_metadata(request.page, total),
                'items': [_stored(connection, row) for row in rows],
            }
        )
