"""Independent Testing task identity, fixed inputs and owner-scoped authorization."""

from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.costs import format_money, parse_money
from backend.app.code_tasks.repository_baseline_validation import read_registered_baseline
from backend.app.code_tasks.task_candidate_reads import _available as candidate_available
from backend.app.code_tasks.task_candidate_reads import _saved as saved_candidate
from backend.app.code_tasks.task_testing_publication import read_candidate_publication
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.shared.code_errors import empty_conflict
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.validation import (
    object_fields,
    reject,
    strict_enum,
    strict_integer,
)

from .assets import NOT_FOUND, sealed_pack_facts
from .plan_content import BASIS_FIELDS, invalid_fixed_basis, parse_fixed_basis
from .plans import _version

TARGETS = ('CANDIDATE', 'SNAPSHOT')
PURPOSES = ('DIAGNOSTIC', 'ACCEPTANCE', 'PACK_VALIDATION')
STATUSES = (
    'DRAFT',
    'PLANNING',
    'READY',
    'RUNNING',
    'WAITING',
    'STOPPING',
    'COMPLETED',
    'TERMINATED',
)
PHASES = ('PLAN', 'PREPARE', 'EXECUTE', 'REPORT', 'FINISHED')
CREATE_FIELDS = (
    *BASIS_FIELDS,
    'target_kind',
    'candidate_id',
    'snapshot_id',
    'purpose',
    'profile_version_id',
    'authorization_id',
    'budget_limit_cny',
    'plan_version_id',
    'test_pack_version_id',
    'previous_testing_task_id',
)
ASSET_FIELDS = ('plan_version_id', 'test_pack_version_id')
TASK_TABLE_FIELDS = (
    'id',
    'kind',
    *CREATE_FIELDS,
    'status',
    'phase',
    'state_version',
    'control_generation',
    'current_verification_id',
    'draft_plan_operation_id',
    'active_operation_id',
    'report_id',
    'validation_id',
    'stop_requested_at',
    'stopped_at',
    'created_at',
    'ended_at',
)


def optional_id(value, field):
    return None if value is None else strict_integer(value, field)


def parse_create_task(value):
    body = object_fields(value, 'body', CREATE_FIELDS, CREATE_FIELDS)
    result = parse_fixed_basis(body)
    for field in ('profile_version_id', 'authorization_id'):
        result[field] = strict_integer(body[field], field)
    for field in ('candidate_id', 'snapshot_id', *ASSET_FIELDS, 'previous_testing_task_id'):
        result[field] = optional_id(body[field], field)
    result['target_kind'] = strict_enum(body['target_kind'], 'target_kind', TARGETS)
    result['purpose'] = strict_enum(body['purpose'], 'purpose', PURPOSES[:2])
    result['budget_limit_cny'] = format_money(
        parse_money(body['budget_limit_cny'], 'budget_limit_cny')
    )
    if (result['candidate_id'] is not None) != (result['target_kind'] == 'CANDIDATE'):
        reject('candidate_id', 'INVALID_FORMAT', '固定候选与目标种类不一致')
    if (result['snapshot_id'] is not None) != (result['target_kind'] == 'SNAPSHOT'):
        reject('snapshot_id', 'INVALID_FORMAT', '固定快照与目标种类不一致')
    if (result['plan_version_id'] is None) != (result['test_pack_version_id'] is None):
        reject('test_pack_version_id', 'INVALID_FORMAT', '计划和测试包须一并选择')
    return result


def basis_failure(field):
    return Rejection(
        'BASIS_REF_INVALID', {'field_errors': [{'field': field, 'reason': 'RELATION'}]}
    )


def task_conflict(code, task=None, *, entity=None, identity=None):
    return Rejection(
        code,
        {
            **empty_conflict(),
            'current_state_version': None if task is None else task['state_version'],
            'related_entity_kind': entity,
            'related_entity_id': identity,
        },
    )


def grant_rejection(identity):
    return Rejection(
        'AUTHORIZATION_NOT_APPLICABLE', {'task_id': None, 'authorization_id': identity}
    )


def materials_for(connection, identity, *, module='TESTING'):
    table, column = {
        'CODING': ('code_task_materials', 'task_id'),
        'TESTING': ('testing_task_materials', 'testing_task_id'),
    }[module]
    return [
        dict(row)
        for row in connection.execute(
            f'SELECT document_id,revision_id FROM {table} WHERE {column}=? ORDER BY document_id',
            (identity,),
        )
    ]


def read_task_row(connection, identity):
    return connection.execute('SELECT * FROM testing_tasks WHERE id=?', (identity,)).fetchone()


def _same_basis(connection, original, given, *, module):
    return (
        all(original[key] == given[key] for key in BASIS_FIELDS[:3])
        and materials_for(connection, original['id'], module=module) == given['material_refs']
    )


def _fixed_target(connection, data):
    if data['target_kind'] == 'SNAPSHOT':
        snapshot = read_registered_baseline(connection, data['snapshot_id'])
        if snapshot is None:
            return NOT_FOUND
        # Original Git registration is required at CREATE. Live retention and
        # runtime readiness are separate and checked on explicit execution.
        return None
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=?', (data['candidate_id'],)
    ).fetchone()
    if candidate is None:
        return NOT_FOUND
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (candidate['task_id'],)
    ).fetchone()
    if task is None:
        raise StorageUnavailable('Original Coding candidate owner is missing')
    if not _same_basis(connection, task, data, module='CODING'):
        return task_conflict('TEST_SOURCE_MISMATCH', entity='CANDIDATE', identity=candidate['id'])
    if data['purpose'] == 'ACCEPTANCE':
        if candidate['publication_operation_id'] is None:
            return task_conflict(
                'TEST_SOURCE_MISMATCH', entity='CANDIDATE', identity=candidate['id']
            )
        read_candidate_publication(connection, candidate)
    _, original = saved_candidate(connection, candidate)
    if not candidate_available(original):
        return task_conflict('CONTENT_NOT_READY', entity='CANDIDATE', identity=candidate['id'])
    return None


def matching_product_assets(connection, data):
    """The same fixed-asset gate is used by CREATE and ATTACH."""
    plan_id, pack_id = (data[key] for key in ASSET_FIELDS)
    if plan_id is None:
        return None
    plan = _version(connection, plan_id)
    pack = connection.execute(
        'SELECT * FROM testing_pack_versions WHERE id=?', (pack_id,)
    ).fetchone()
    if plan is None or pack is None:
        return NOT_FOUND
    if pack['plan_version_id'] != plan_id or any(plan[key] != data[key] for key in BASIS_FIELDS):
        return task_conflict('TEST_SOURCE_MISMATCH', entity='PLAN', identity=plan_id)
    if plan['status'] == 'REVOKED' or pack['status'] == 'REVOKED':
        return task_conflict('TEST_ASSET_REVOKED', entity='PLAN', identity=plan_id)
    if plan['status'] != 'PUBLISHED' or pack['status'] != 'PUBLISHED':
        return task_conflict('INVALID_STATE', entity='PLAN', identity=plan_id)
    if pack['sha256'] is None or pack['validation_id'] is None:
        raise StorageUnavailable('Published Testing pack has no sealed and validated provenance')
    sealed_pack_facts(connection, pack)
    validation = connection.execute(
        'SELECT result FROM testing_pack_validations WHERE id=? AND test_pack_version_id=?',
        (pack['validation_id'], pack_id),
    ).fetchone()
    if validation is None or validation['result'] != 'PASSED':
        raise StorageUnavailable('Original published Testing validation is missing')
    return None


def insert_task(connection, identity, data, *, at, validation_id=None, ready=False):
    columns = (
        'id',
        'kind',
        *(field for field in CREATE_FIELDS if field != 'material_refs'),
        'status',
        'phase',
        'state_version',
        'control_generation',
        'validation_id',
        'created_at',
    )
    values = {
        **data,
        'id': identity,
        'kind': 'PRODUCT' if validation_id is None else 'PACK_VALIDATION',
        'status': 'READY' if ready else 'DRAFT',
        'phase': 'PREPARE' if ready else 'PLAN',
        'state_version': 1,
        'control_generation': 1,
        'validation_id': validation_id,
        'created_at': at,
    }
    connection.execute(
        'INSERT INTO testing_tasks('
        + ','.join(columns)
        + ') VALUES('
        + ','.join('?' for _ in columns)
        + ')',
        tuple(values[field] for field in columns),
    )
    connection.executemany(
        'INSERT INTO testing_task_materials(testing_task_id,document_id,revision_id) VALUES(?,?,?)',
        [(identity, row['document_id'], row['revision_id']) for row in data['material_refs']],
    )
    return identity


def _create(connection, data, *, catalog, runtime_resources):
    invalid = invalid_fixed_basis(connection, data, require_confirmed=True)
    if invalid is not None:
        return basis_failure(invalid)
    target_error = _fixed_target(connection, data)
    if target_error is not None:
        return target_error
    previous = data['previous_testing_task_id']
    if previous is not None:
        source = read_task_row(connection, previous)
        if source is None:
            return NOT_FOUND
        if source['kind'] != 'PRODUCT' or not _same_basis(
            connection, source, data, module='TESTING'
        ):
            return task_conflict('TEST_SOURCE_MISMATCH')
    grant = connection.execute(
        'SELECT * FROM testing_authorizations WHERE id=?', (data['authorization_id'],)
    ).fetchone()
    if (
        grant is None
        or grant['scope_kind'] != 'TASK'
        or grant['status'] != 'APPROVED_UNBOUND'
        or grant['testing_task_id'] is not None
        or grant['validation_id'] is not None
        or grant['profile_version_id'] != data['profile_version_id']
        or parse_money(grant['budget_limit_cny']) < parse_money(data['budget_limit_cny'])
    ):
        return grant_rejection(data['authorization_id'])
    asset_error = matching_product_assets(connection, data)
    if asset_error is not None:
        return asset_error
    identity = entity_id(connection, EntityKind.TESTING_TASK)
    updated = connection.execute(
        """UPDATE testing_authorizations SET status='EFFECTIVE',testing_task_id=?
           WHERE id=? AND scope_kind='TASK' AND status='APPROVED_UNBOUND'
           AND testing_task_id IS NULL AND validation_id IS NULL""",
        (identity, grant['id']),
    )
    if updated.rowcount != 1:
        raise StorageUnavailable('Original Testing approval changed during creation')
    insert_task(connection, identity, data, at=max(operation_time(None), grant['approved_at']))
    if runtime_resources is not None and data['plan_version_id'] is not None:
        from .task_run import run_reason

        task = read_task_row(connection, identity)
        assets = {key: data[key] for key in ASSET_FIELDS}
        if run_reason(connection, catalog, task, runtime_resources, assets=assets) is None:
            connection.execute(
                "UPDATE testing_tasks SET status='READY',phase='PREPARE' WHERE id=?",
                (identity,),
            )
    return Success(
        {
            'code': 'CREATED',
            'data': {'testing_task_id': identity, 'state_version': 1},
            'details': None,
        },
        201,
    )


def create_task(runtime, request, *, runtime_resources=None):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _create(
            connection, request.data, catalog=runtime.catalog, runtime_resources=runtime_resources
        ),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )
