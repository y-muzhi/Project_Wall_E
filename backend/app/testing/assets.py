"""Independent Testing pack identities and nonsecret projections."""

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.repository_operations import _time
from backend.app.infrastructure.check_runner_bundle import valid_sha256
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.http_projection import exact
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import (
    MAX_SAFE_INTEGER,
    ordinary_text,
    strict_enum,
    strict_integer,
    strict_json_object,
)

from .plan_content import invalid_basis
from .plans import _version

PACK_FIELDS = (
    'id',
    'plan_version_id',
    'version',
    'check_set_version_id',
    'sha256',
    'status',
    'validation_id',
    'state_version',
    'created_at',
    'published_at',
    'revoked_at',
    'revocation_reason',
    'ready',
    'reason_codes',
)
PACK_STATUSES = ('DRAFT', 'SEALED', 'PUBLISHED', 'REVOKED')
PACK_REASONS = (
    'PACK_NOT_SEALED',
    'PACK_NOT_PUBLISHED',
    'TEST_ASSET_REVOKED',
    'REFERENCE_SET_NOT_REGISTERED',
    'Q20-CHECKS',
)
NOT_FOUND = Rejection('NOT_FOUND', None)


def project_pack(data):
    result = exact(data, PACK_FIELDS)
    for field in ('id', 'plan_version_id', 'version', 'state_version'):
        strict_integer(result[field], field)
    for field in ('check_set_version_id', 'validation_id'):
        if result[field] is not None:
            strict_integer(result[field], field)
    status = strict_enum(result['status'], 'status', PACK_STATUSES)
    sealed = result['check_set_version_id'] is not None
    published = result['published_at'] is not None
    revoked = result['revoked_at'] is not None
    _time(result['created_at'], nullable=False)
    _time(result['published_at'])
    _time(result['revoked_at'])
    reason = result['revocation_reason']
    if (
        sealed != (result['sha256'] is not None)
        or sealed
        and not valid_sha256(result['sha256'])
        or status in ('SEALED', 'PUBLISHED')
        and not sealed
        or status == 'DRAFT'
        and sealed
        or status == 'PUBLISHED'
        and not published
        or status in ('DRAFT', 'SEALED')
        and published
        or published
        and (
            not sealed
            or result['validation_id'] is None
            or result['published_at'] < result['created_at']
        )
        or not published
        and result['validation_id'] is not None
        or revoked != (status == 'REVOKED')
        or revoked != (reason is not None)
        or revoked
        and result['revoked_at'] < (result['published_at'] or result['created_at'])
        or reason is not None
        and ordinary_text(reason, 'reason', 1, 2000) != reason
    ):
        raise ValueError('Original pack lifecycle differs')
    reasons = result['reason_codes']
    if (
        type(reasons) is not list
        or any(code not in PACK_REASONS for code in reasons)
        or len(set(reasons)) != len(reasons)
        or type(result['ready']) is not bool
        or result['ready'] != (not reasons)
        or status != 'PUBLISHED'
        and result['ready']
    ):
        raise ValueError('Original pack readiness differs')
    return result


def sealed_pack_facts(connection, row):
    operations = connection.execute(
        """SELECT o.id,o.fixed_input,s.result_ref
           FROM code_operations o JOIN code_operation_steps s ON s.operation_id=o.id
           WHERE o.resource_kind='TEST_PACK_VERSION' AND o.resource_id=? AND o.operation_type='SEAL_PACK'
             AND o.status='SUCCEEDED' AND o.task_id IS NULL AND o.testing_task_id IS NULL
             AND s.step_type='SEAL' AND s.status='SUCCEEDED'""",
        (row['id'],),
    ).fetchall()
    if len(operations) != 1:
        raise StorageUnavailable('Original pack has no unique completed seal')
    operation = operations[0]
    try:
        fixed = strict_json_object(operation['fixed_input'])
        sealed = strict_json_object(operation['result_ref'])
        if (
            sealed != {'sha256': row['sha256']}
            or fixed['plan_version_id'] != row['plan_version_id']
            or fixed['pack_version'] != row['version']
            or not valid_sha256(fixed['basis_fingerprint'])
        ):
            raise ValueError('Original sealed pack closure differs')
        return operation['id'], fixed
    except (KeyError, TypeError, ValueError) as error:
        raise StorageUnavailable('Original sealed pack facts are unreadable') from error


def public_pack(connection, row, *, installation):
    data = dict(row)
    private_ref = data.pop('content_ref')
    if (private_ref is not None) != (data['check_set_version_id'] is not None):
        raise StorageUnavailable('Original pack seal is inconsistent')
    parent = connection.execute(
        'SELECT status FROM testing_plan_versions WHERE id=?',
        (data['plan_version_id'],),
    ).fetchone()
    if parent is None:
        raise StorageUnavailable('Original Testing plan is missing')
    sealed = None
    if data['check_set_version_id'] is not None:
        checks = connection.execute(
            'SELECT owner_module FROM code_check_set_versions WHERE id=?',
            (data['check_set_version_id'],),
        ).fetchone()
        if checks is None or checks['owner_module'] != 'TESTING':
            raise StorageUnavailable('Original pack CheckSet owner differs')
        _, sealed = sealed_pack_facts(connection, data)
    if parent['status'] == 'REVOKED' or data['status'] == 'REVOKED':
        reason = 'TEST_ASSET_REVOKED'
    elif data['status'] == 'DRAFT':
        reason = 'PACK_NOT_SEALED'
    elif data['status'] == 'SEALED':
        reason = 'PACK_NOT_PUBLISHED'
    else:
        reason = 'Q20-CHECKS'
    reasons = [reason]
    if reason == 'PACK_NOT_SEALED' and (installation is None or not installation.targets):
        reasons.append('Q20-CHECKS')
    if (
        reason != 'TEST_ASSET_REVOKED'
        and sealed is not None
        and (
            installation is None
            or not any(
                entry.reference.basis_fingerprint == sealed['basis_fingerprint']
                for entry in installation.reference_sets
            )
        )
    ):
        reasons.append('REFERENCE_SET_NOT_REGISTERED')
    try:
        return project_pack({**data, 'ready': False, 'reason_codes': reasons})
    except (TypeError, ValueError, KeyError) as error:
        raise StorageUnavailable('Original pack facts are unreadable') from error


def pack_conflict(code, plan_version, state_version):
    return Rejection(
        code,
        {
            **empty_conflict(),
            'related_entity_kind': 'PLAN',
            'related_entity_id': plan_version,
            'current_state_version': state_version,
        },
    )


def create_pack(runtime, request):
    require_schema(runtime)

    def save(connection):
        version = _version(connection, request.identity)
        if version is None:
            return NOT_FOUND
        if version['status'] == 'REVOKED':
            return pack_conflict('TEST_ASSET_REVOKED', version['id'], version['state_version'])
        if version['status'] != 'PUBLISHED':
            return pack_conflict('INVALID_STATE', version['id'], version['state_version'])
        invalid = invalid_basis(connection, version, require_confirmed=True)
        if invalid is not None:
            return Rejection(
                'BASIS_REF_INVALID', {'field_errors': [{'field': invalid, 'reason': 'RELATION'}]}
            )
        previous = connection.execute(
            'SELECT MAX(version) FROM testing_pack_versions WHERE plan_version_id=?',
            (version['id'],),
        ).fetchone()[0]
        if previous == MAX_SAFE_INTEGER:
            return pack_conflict('INVALID_STATE', version['id'], version['state_version'])
        identity = entity_id(connection, EntityKind.TEST_PACK_VERSION)
        connection.execute(
            """INSERT INTO testing_pack_versions(id,plan_version_id,version,status,state_version,created_at)
               VALUES(?,?,?,'DRAFT',1,?)""",
            (
                identity,
                version['id'],
                1 if previous is None else increment(previous),
                max(operation_time(None), version['published_at']),
            ),
        )
        return Success(
            {'code': 'CREATED', 'data': {'test_pack_version_id': identity}, 'details': None}, 201
        )

    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def _read(value):
    return {'code': 'READ_OK', 'data': value, 'details': None}


def read_pack(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        row = connection.execute(
            'SELECT * FROM testing_pack_versions WHERE id=?', (request.identity,)
        ).fetchone()
        if row is None:
            return NOT_FOUND.result
        return _read(
            public_pack(
                connection,
                row,
                installation=getattr(runtime.catalog, 'testing_assets', None),
            )
        )


def list_packs(runtime, request):
    require_schema(runtime)
    with runtime.database.transaction() as connection:
        if (
            connection.execute(
                'SELECT id FROM testing_plan_versions WHERE id=?', (request.identity,)
            ).fetchone()
            is None
        ):
            return NOT_FOUND.result
        total = connection.execute(
            'SELECT count(*) FROM testing_pack_versions WHERE plan_version_id=?',
            (request.identity,),
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM testing_pack_versions WHERE plan_version_id=? ORDER BY id LIMIT ? OFFSET ?',
            (request.identity, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        return _read(
            {
                **page_metadata(request.page, total),
                'items': [
                    public_pack(
                        connection,
                        row,
                        installation=getattr(runtime.catalog, 'testing_assets', None),
                    )
                    for row in rows
                ],
            }
        )
