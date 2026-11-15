"""Short, owner-scoped changes to a fixed Testing task's assets or model budget."""

from backend.app.code_tasks.coding_model_ledger import budget_facts
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.costs import parse_money
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Success, canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.command_execution import execute_idempotent, operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER

from .assets import NOT_FOUND
from .task_run import run_reason
from .task_views import task_view
from .tasks import (
    ASSET_FIELDS,
    grant_rejection,
    matching_product_assets,
    materials_for,
    read_task_row,
    task_conflict,
)

ATTACH = 'ATTACH_ASSETS'
BUDGET = 'INCREASE_TEST_BUDGET'


def _save_audit(connection, request, original, action, new_version, at):
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    fixed = canonical_input(request.business_input())
    result = canonical_input({'state_version': new_version})
    connection.execute(
        """INSERT INTO code_operations(id,testing_task_id,resource_kind,resource_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,
           started_at,ended_at) VALUES(?,?,'TESTING_TASK',?,?,?,?,?,?,'SUCCEEDED',?,?,?)""",
        (
            operation,
            original['id'],
            original['id'],
            action,
            request.idempotency_key,
            original['state_version'],
            fixed,
            original['control_generation'],
            at,
            at,
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input,result_ref,
           started_at,ended_at,last_observed_at) VALUES(?,?,?,'SUCCEEDED',?,?,?,?,?)""",
        [
            (operation, number, step, fixed, result, at, at, at)
            for number, step in enumerate(operation_steps('TESTING', action), 1)
        ],
    )
    return operation


def _save_assets(connection, request, task, *, catalog, runtime_resources):
    if (
        task['kind'] != 'PRODUCT'
        or task['status'] not in ('DRAFT', 'READY', 'WAITING')
        or task['active_operation_id'] is not None
        or task['current_verification_id'] is not None
    ):
        return task_conflict('INVALID_STATE', task)
    if task['status'] == 'WAITING':
        waiting = connection.execute(
            "SELECT kind,source_kind,resume_phase FROM code_waiting_items WHERE testing_task_id=? AND status='OPEN'",
            (task['id'],),
        ).fetchall()
        if not waiting or any(
            row['source_kind'] != 'OPERATION'
            or row['kind'] not in ('CONFIGURATION', 'CHECK_ENVIRONMENT', 'PREPARATION')
            or row['resume_phase'] not in ('PLAN', 'PREPARE')
            for row in waiting
        ):
            return task_conflict('INVALID_STATE', task)
    current = tuple(task[key] for key in ASSET_FIELDS)
    chosen = tuple(request.data[key] for key in ASSET_FIELDS)
    if current != (None, None) and current != chosen:
        return task_conflict('INVALID_STATE', task)
    authorization = connection.execute(
        """SELECT id FROM testing_authorizations WHERE id=? AND testing_task_id=?
           AND profile_version_id=? AND scope_kind='TASK' AND status='EFFECTIVE'""",
        (task['authorization_id'], task['id'], task['profile_version_id']),
    ).fetchone()
    if authorization is None:
        return grant_rejection(task['authorization_id'])
    invalid = matching_product_assets(
        connection,
        {
            **dict(task),
            **request.data,
            'material_refs': materials_for(connection, task['id']),
        },
    )
    if invalid is not None:
        return invalid
    reason = run_reason(
        connection,
        catalog,
        task,
        runtime_resources,
        assets={key: request.data[key] for key in ASSET_FIELDS},
    )
    if reason is None:
        status, phase = 'READY', 'PREPARE'
    elif task['status'] == 'WAITING':
        status, phase = 'WAITING', task['phase']
    else:
        status, phase = 'DRAFT', 'PLAN'
    if current == chosen and (status, phase) == (task['status'], task['phase']):
        return None
    version = increment(task['state_version'])
    written = connection.execute(
        """UPDATE testing_tasks SET plan_version_id=?,test_pack_version_id=?,status=?,phase=?,
           state_version=? WHERE id=? AND state_version=?""",
        (*chosen, status, phase, version, task['id'], task['state_version']),
    )
    if written.rowcount != 1:
        raise StorageUnavailable('Original Testing asset version changed before commit')
    at = max(operation_time(None), task['created_at'])
    operation = _save_audit(connection, request, task, ATTACH, version, at)
    if task['status'] == 'WAITING' and status == 'READY':
        connection.execute(
            """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
               WHERE testing_task_id=? AND status='OPEN'""",
            (at, canonical_input({'operation_id': operation}), task['id']),
        )
    return None


def _save_budget(connection, request, task):
    if task['kind'] != 'PRODUCT' or task['status'] not in (
        'DRAFT',
        'PLANNING',
        'READY',
        'RUNNING',
        'WAITING',
    ):
        return task_conflict('INVALID_STATE', task)
    current = parse_money(task['budget_limit_cny'])
    amount = parse_money(request.data['new_budget_limit_cny'])
    if amount <= current:
        return Rejection(
            'BUDGET_NOT_INCREASED',
            {'field_errors': [{'field': 'new_budget_limit_cny', 'reason': 'RANGE'}]},
        )
    original = connection.execute(
        """SELECT * FROM testing_authorizations WHERE id=? AND scope_kind='TASK'
           AND testing_task_id=? AND profile_version_id=? AND status='EFFECTIVE'""",
        (task['authorization_id'], task['id'], task['profile_version_id']),
    ).fetchone()
    replacement = connection.execute(
        """SELECT * FROM testing_authorizations WHERE id=? AND scope_kind='TASK'
           AND testing_task_id IS NULL AND validation_id IS NULL
           AND profile_version_id=? AND status='APPROVED_UNBOUND'""",
        (request.data['authorization_id'], task['profile_version_id']),
    ).fetchone()
    facts = budget_facts(connection, task['id'], current, owner='TESTING')
    if (
        original is None
        or replacement is None
        or parse_money(replacement['budget_limit_cny']) < amount
        or amount < facts.settled + facts.reserved
    ):
        return grant_rejection(request.data['authorization_id'])
    version = increment(task['state_version'])
    connection.execute(
        "UPDATE testing_authorizations SET status='EFFECTIVE',testing_task_id=? WHERE id=?",
        (task['id'], replacement['id']),
    )
    written = connection.execute(
        """UPDATE testing_tasks SET authorization_id=?,budget_limit_cny=?,state_version=?
           WHERE id=? AND state_version=? AND authorization_id=?""",
        (
            replacement['id'],
            request.data['new_budget_limit_cny'],
            version,
            task['id'],
            task['state_version'],
            original['id'],
        ),
    )
    if written.rowcount != 1:
        raise StorageUnavailable('Original Testing budget or authorization changed before commit')
    connection.execute(
        "UPDATE testing_authorizations SET status='RETIRED' WHERE id=?", (original['id'],)
    )
    _save_audit(
        connection,
        request,
        task,
        BUDGET,
        version,
        max(operation_time(None), replacement['approved_at']),
    )
    return None


def _apply(runtime, request, update, *, attached=False):
    require_schema(runtime)

    def save(connection):
        task = read_task_row(connection, request.identity)
        if task is None:
            return NOT_FOUND
        if task['status'] in ('COMPLETED', 'TERMINATED'):
            return task_conflict('TASK_ENDED', task)
        if task['state_version'] != request.expected:
            return task_conflict('VERSION_CONFLICT', task)
        if task['state_version'] == MAX_SAFE_INTEGER:
            return task_conflict('INVALID_STATE', task)
        rejected = update(connection, request, task)
        if rejected is not None:
            return rejected
        saved = read_task_row(connection, request.identity)
        reason = None if attached and saved['status'] == 'READY' else 'EXECUTION_NOT_READY'
        result = task_view(connection, saved, run_reason=reason)
        return Success({'code': 'UPDATED', 'data': result, 'details': None}, 200)

    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        save,
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset(),
    )


def attach_assets(runtime, request, *, runtime_resources=None):
    return _apply(
        runtime,
        request,
        lambda connection, parsed, task: _save_assets(
            connection, parsed, task, catalog=runtime.catalog, runtime_resources=runtime_resources
        ),
        attached=True,
    )


def increase_budget(runtime, request):
    return _apply(runtime, request, _save_budget)
