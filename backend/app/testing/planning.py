"""Accept one explicit Testing draft request and fence its original model call."""

from dataclasses import dataclass
from hashlib import sha256

from backend.app.code_tasks.coding_model_ledger import budget_facts
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.code_tasks.costs import format_money, parse_money, reserve_cost
from backend.app.code_tasks.operation_protocol import operation_steps
from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.shared.command_execution import (
    ConfigurationNotReady,
    execute_idempotent,
    operation_time,
)
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .assets import NOT_FOUND
from .cli_plan import read_fixed_profile
from .planning_context import DraftContextUnavailable, FrozenDraft, freeze_draft
from .run_records import accepted_run
from .tasks import grant_rejection, read_task_row, task_conflict

DRAFT_PATH = '/testing-tasks/{testing_task_id}/draft-plan'
DRAFT_TYPE = 'DRAFT_PLAN'
STEPS = operation_steps('TESTING', DRAFT_TYPE)
CALL_STEP = STEPS.index('CALL_MODEL') + 1
SAVE_STEP = STEPS.index('SAVE_DRAFT') + 1


@dataclass(frozen=True)
class OriginalDraft:
    operation: object
    task: object
    use: object
    reservation: object
    fixed: dict


def _allowed_grant(connection, task):
    grant = connection.execute(
        """SELECT budget_limit_cny FROM testing_authorizations WHERE id=? AND profile_version_id=?
           AND testing_task_id=? AND scope_kind='TASK' AND status='EFFECTIVE'""",
        (task['authorization_id'], task['profile_version_id'], task['id']),
    ).fetchone()
    return grant is not None and (
        parse_money(task['budget_limit_cny']) <= parse_money(grant['budget_limit_cny'])
    )


def _reservation(frozen):
    prices = frozen.prices
    return reserve_cost(
        frozen.facts['input_cap'],
        frozen.facts['output_cap'],
        max(prices.input_micro, *(row.price_micro for row in prices.cache))
        if prices.cache
        else prices.input_micro,
        prices.output_micro,
    )


def draft_inputs(connection, catalog, task, at):
    if (
        task['kind'] != 'PRODUCT'
        or task['status'] != 'DRAFT'
        or task['active_operation_id'] is not None
        or task['plan_version_id'] is not None
        or task['test_pack_version_id'] is not None
        or task['current_verification_id'] is not None
        or task['stop_requested_at'] is not None
        or task['state_version'] >= MAX_SAFE_INTEGER - 1
    ):
        return None, 'TASK_STATE'
    if not _allowed_grant(connection, task):
        return None, 'AUTHORIZATION_NOT_READY'
    if (
        connection.execute(
            """SELECT 1 FROM code_waiting_items WHERE testing_task_id=? AND status='OPEN'""",
            (task['id'],),
        ).fetchone()
        is not None
    ):
        return None, 'MODEL_NOT_READY'
    profile = read_fixed_profile(connection, task['profile_version_id'])
    try:
        frozen = freeze_draft(connection, catalog, task, profile, at)
    except DraftContextUnavailable as error:
        return None, 'CONTENT_NOT_READY' if error.code == 'CONTENT_NOT_READY' else 'MODEL_NOT_READY'
    budget = budget_facts(
        connection, task['id'], parse_money(task['budget_limit_cny']), owner='TESTING'
    )
    held = connection.execute(
        """SELECT 1 FROM code_task_reservations WHERE testing_task_id=? AND status='RESERVED'""",
        (task['id'],),
    ).fetchone()
    if held is not None or budget.unresolved:
        return None, 'MODEL_NOT_READY'
    if budget.requests >= profile['limits'][
        'max_model_requests'
    ] or budget.available < _reservation(frozen):
        return None, 'BUDGET_NOT_READY'
    return frozen, None


def _reserve(connection, request, task, frozen, at):
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    use = entity_id(connection, EntityKind.LLM_USE)
    reservation = entity_id(connection, EntityKind.CODE_TASK_RESERVATION)
    latest = connection.execute(
        'SELECT max(call_no) FROM llm_uses WHERE testing_task_id=?', (task['id'],)
    ).fetchone()[0]
    call_no = 1 if latest is None else increment(latest)
    fixed = canonical_input(
        {
            'expected_state_version': request.expected,
            'facts': frozen.facts,
            'llm_use_id': use,
            'reservation_id': reservation,
        }
    )
    connection.execute(
        """INSERT INTO code_operations(id,testing_task_id,resource_kind,resource_id,operation_type,
           idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at,started_at)
           VALUES(?,?,'TESTING_TASK',?,'DRAFT_PLAN',?,?,?,?,'RUNNING',?,?)""",
        (
            operation,
            task['id'],
            task['id'],
            request.idempotency_key,
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
            at,
        ),
    )
    for number, step in enumerate(STEPS, 1):
        result = (
            {'context_sha256': frozen.facts['request_sha256']}
            if number == 1
            else {'llm_use_id': use}
            if number == 2
            else None
        )
        timestamp = at if result is not None else None
        connection.execute(
            """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,
               fixed_input,result_ref,started_at,last_observed_at,ended_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                operation,
                number,
                step,
                'SUCCEEDED' if result is not None else 'PENDING',
                fixed,
                None if result is None else canonical_input(result),
                timestamp,
                timestamp,
                timestamp,
            ),
        )
    model = frozen.admission.model
    body = model.testing_request(frozen.model_input, output_cap=frozen.model_input.output_cap)
    request_audit = audit_json(body, credentials=(model.api_key,))
    connection.execute(
        """INSERT INTO llm_uses(id,testing_task_id,operation_id,call_no,attempt_no,provider,
           model_name,model_version,function_type,prompt_config,request_snapshot_json,input_summary,
           context_manifest_json,parse_status,validation_status,call_status,started_at,
           protocol_version,call_purpose,transport_status,usage_status,capture_status,source_evidence_ref)
           VALUES(?,?,?,?,1,'volcengine',?,?,'TEST_PLAN_DRAFT',?,?,?,?,
           'PENDING','PENDING','RUNNING',?,'TEST20-PLAN-1','TEST_DESIGN','NOT_SENT','NOT_REPORTED',?,?)""",
        (
            use,
            task['id'],
            operation,
            call_no,
            model.model_name,
            model.model_version,
            'AI20-TEST-PLAN:sha256:' + frozen.facts['prompt_sha256'],
            request_audit,
            'TEST_DESIGN',
            canonical_input(frozen.facts),
            at,
            'FULL' if strict_json_object(request_audit) == body else 'REDACTED',
            'testing-plan:sha256:' + sha256(fixed.encode()).hexdigest(),
        ),
    )
    connection.execute(
        """INSERT INTO code_task_reservations(id,testing_task_id,llm_use_id,price_version_id,
           reserved_cny,status,created_at) VALUES(?,?,?,?,?,'RESERVED',?)""",
        (
            reservation,
            task['id'],
            use,
            frozen.facts['price_version_id'],
            format_money(_reservation(frozen)),
            at,
        ),
    )
    version = increment(task['state_version'])
    changed = connection.execute(
        """UPDATE testing_tasks SET status='PLANNING',phase='PLAN',draft_plan_operation_id=?,
           active_operation_id=?,state_version=? WHERE id=? AND status='DRAFT'
           AND active_operation_id IS NULL AND state_version=? AND control_generation=?""",
        (
            operation,
            operation,
            version,
            task['id'],
            task['state_version'],
            task['control_generation'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing draft task changed during acceptance')
    return accepted_run(task['id'], operation, version)


def _accept(connection, catalog, request):
    task = read_task_row(connection, request.identity)
    if task is None:
        return NOT_FOUND
    if task['status'] in ('COMPLETED', 'TERMINATED'):
        return task_conflict('TASK_ENDED', task)
    if task['state_version'] != request.expected:
        return task_conflict('VERSION_CONFLICT', task)
    at = max(operation_time(None), task['created_at'])
    frozen, reason = draft_inputs(connection, catalog, task, at)
    if reason == 'AUTHORIZATION_NOT_READY':
        return grant_rejection(task['authorization_id'])
    if reason == 'MODEL_NOT_READY':
        raise ConfigurationNotReady('Q20-MODEL')
    if reason == 'CONTENT_NOT_READY':
        return task_conflict('CONTENT_NOT_READY', task)
    if type(frozen) is not FrozenDraft:
        return task_conflict('INVALID_STATE', task)
    return _reserve(connection, request, task, frozen, at)


def accept_draft(runtime, request):
    require_schema(runtime)
    return execute_idempotent(
        runtime.commands(),
        request.command.route.capability_id,
        request,
        lambda connection: _accept(connection, runtime.catalog, request),
        target_identity=request.command.scope.target_identity,
        allowed_failures=frozenset({'CONFIG_NOT_READY'}),
    )


def read_original_draft(connection, operation):
    task = read_task_row(connection, operation['testing_task_id'])
    fixed = strict_json_object(operation['fixed_input'])
    if set(fixed) != {'expected_state_version', 'facts', 'llm_use_id', 'reservation_id'}:
        raise StorageUnavailable('Original Testing draft fixed ownership is missing')
    use = connection.execute(
        """SELECT * FROM llm_uses WHERE id=? AND testing_task_id=? AND operation_id=?
           AND guide_run_id IS NULL AND execution_session_id IS NULL AND gateway_request_id IS NULL
           AND protocol_version='TEST20-PLAN-1' AND function_type='TEST_PLAN_DRAFT'
           AND call_purpose='TEST_DESIGN' AND attempt_no=1""",
        (fixed['llm_use_id'], operation['testing_task_id'], operation['id']),
    ).fetchone()
    reservation = connection.execute(
        """SELECT * FROM code_task_reservations WHERE id=? AND llm_use_id=?
           AND testing_task_id=? AND task_id IS NULL AND price_version_id=?""",
        (
            fixed['reservation_id'],
            fixed['llm_use_id'],
            operation['testing_task_id'],
            fixed['facts']['price_version_id'],
        ),
    ).fetchone()
    if (
        task is None
        or use is None
        or reservation is None
        or operation['task_id'] is not None
        or operation['operation_type'] != DRAFT_TYPE
        or operation['resource_kind'] != 'TESTING_TASK'
        or operation['resource_id'] != task['id']
        or fixed['expected_state_version'] != operation['expected_state_version']
        or use['context_manifest_json'] != canonical_input(fixed['facts'])
        or use['source_evidence_ref']
        != 'testing-plan:sha256:' + sha256(operation['fixed_input'].encode()).hexdigest()
    ):
        raise StorageUnavailable('Original Testing draft call ownership differs')
    return OriginalDraft(operation, task, use, reservation, fixed)


def current_draft(original):
    task, operation = original.task, original.operation
    return (
        task['status'] == 'PLANNING'
        and task['stop_requested_at'] is None
        and task['draft_plan_operation_id'] == task['active_operation_id'] == operation['id']
        and task['control_generation'] == operation['control_generation']
        and operation['status'] == 'RUNNING'
        and operation['ended_at'] is None
    )
