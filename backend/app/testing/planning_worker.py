"""Dispatch and settle at most one complete-body call for an original draft."""

import asyncio
from dataclasses import dataclass

from backend.app.code_tasks.costs import final_usage_cost, format_money, parse_money
from backend.app.code_tasks.usage import UsageState, confirm_final_usage
from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.check_runner_bundle import CheckResourceError
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.shared.command_execution import operation_time

from .cli_plan import read_fixed_profile
from .planning import CALL_STEP, SAVE_STEP, _allowed_grant, current_draft, read_original_draft
from .planning_context import (
    DraftContextUnavailable,
    FrozenDraft,
    freeze_draft,
    parse_draft,
    validate_draft,
)
from .plans import insert_draft_version


@dataclass(frozen=True)
class DraftDispatch:
    operation_id: int
    use_id: int
    frozen: FrozenDraft
    gateway: ModelGateway


def _operation(connection, identity):
    return connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND task_id IS NULL
           AND testing_task_id=resource_id AND operation_type='DRAFT_PLAN'""",
        (identity,),
    ).fetchone()


def _step(connection, original, step, state, at, *, result=None):
    changed = connection.execute(
        """UPDATE code_operation_steps SET status=?,result_ref=?,started_at=COALESCE(started_at,?),
           ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=?
           AND status IN ('PENDING','RUNNING') AND ended_at IS NULL""",
        (
            state,
            None if result is None else canonical_input(result),
            at,
            at if state in ('SUCCEEDED', 'FAILED', 'CANCELLED') else None,
            at,
            original.operation['id'],
            step,
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing draft step was already settled')


def _task_result(connection, original, *, waiting, at):
    if not current_draft(original):
        return
    task = original.task
    if waiting:
        connection.execute(
            """INSERT INTO code_waiting_items(id,testing_task_id,kind,source_kind,source_id,
               resume_phase,status,created_at) VALUES(?,?,'MODEL_RESULT','LLM_USE',?,'PLAN','OPEN',?)""",
            (entity_id(connection, EntityKind.WAITING_ITEM), task['id'], original.use['id'], at),
        )
    changed = connection.execute(
        """UPDATE testing_tasks SET status=?,active_operation_id=?,state_version=? WHERE id=?
           AND status='PLANNING' AND active_operation_id=? AND control_generation=?""",
        (
            'WAITING' if waiting else 'DRAFT',
            original.operation['id'] if waiting else None,
            increment(task['state_version']),
            task['id'],
            original.operation['id'],
            task['control_generation'],
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Testing draft fence changed before save')


def _end_operation(connection, original, state, code, at):
    connection.execute(
        """UPDATE code_operations SET status=?,failure_code=?,ended_at=?
           WHERE id=? AND status='RUNNING' AND ended_at IS NULL""",
        (state, code, None if state == 'UNKNOWN' else at, original.operation['id']),
    )


def _release_unsent(connection, original, at, *, cancelled):
    if (
        original.use['transport_status'] != 'NOT_SENT'
        or original.reservation['status'] != 'RESERVED'
    ):
        raise StorageUnavailable('Original Testing reservation may have been sent')
    code = None if cancelled else 'CONFIG_NOT_READY'
    state = 'CANCELLED' if cancelled else 'FAILED'
    connection.execute(
        'UPDATE llm_uses SET call_status=?,ended_at=?,error_code=? WHERE id=?',
        (state, at, code, original.use['id']),
    )
    connection.execute(
        "UPDATE code_task_reservations SET status='RELEASED_UNSENT' WHERE id=?",
        (original.reservation['id'],),
    )
    _step(connection, original, CALL_STEP, state, at)
    _step(connection, original, SAVE_STEP, 'CANCELLED', at)
    _task_result(connection, original, waiting=False, at=at)
    _end_operation(connection, original, state, code, at)


def claim_draft(runtime):
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        operation = connection.execute(
            """SELECT o.* FROM code_operations o JOIN llm_uses u ON u.operation_id=o.id
               AND u.testing_task_id=o.testing_task_id WHERE o.testing_task_id=o.resource_id
               AND o.task_id IS NULL AND o.operation_type='DRAFT_PLAN' AND o.status='RUNNING'
               AND u.transport_status='NOT_SENT' AND u.ended_at IS NULL ORDER BY o.id LIMIT 1"""
        ).fetchone()
        if operation is None:
            return None
        original = read_original_draft(connection, operation)
        at = max(operation_time(None), operation['created_at'])
        if not current_draft(original):
            _release_unsent(connection, original, at, cancelled=True)
            return False
        task = original.task
        profile = read_fixed_profile(connection, task['profile_version_id'])
        try:
            frozen = freeze_draft(connection, runtime.catalog, task, profile, at)
        except DraftContextUnavailable:
            frozen = None
        if (
            frozen is None
            or frozen.facts != original.fixed['facts']
            or not _allowed_grant(connection, task)
        ):
            _release_unsent(connection, original, at, cancelled=False)
            return False
        changed = connection.execute(
            """UPDATE llm_uses SET transport_status='SENDING'
               WHERE id=? AND transport_status='NOT_SENT' AND ended_at IS NULL""",
            (original.use['id'],),
        )
        if changed.rowcount != 1:
            raise StorageUnavailable('Original Testing draft send intent differs')
        _step(connection, original, CALL_STEP, 'RUNNING', at)
        return DraftDispatch(
            operation['id'], original.use['id'], frozen, runtime.catalog.testing_planning.gateway
        )


def _usage(response, draft):
    initial = UsageState(f'testing-llm-use:{draft.use_id}')
    if response is None or response.raw_response_json is None:
        return initial, False
    body = response.raw_response
    complete = (
        response.succeeded
        and response.http_status is not None
        and 200 <= response.http_status < 300
        and body.get('model') == draft.frozen.admission.model.model_name
    )
    raw_usage = body.get('usage')
    if type(raw_usage) is not dict:
        return initial, complete
    prompt = raw_usage.get('prompt_tokens_details')
    generated = raw_usage.get('completion_tokens_details')
    values = {
        'input_tokens': raw_usage.get('prompt_tokens'),
        'output_tokens': raw_usage.get('completion_tokens'),
        'cached_tokens': prompt.get('cached_tokens') if type(prompt) is dict else None,
        'reasoning_tokens': generated.get('reasoning_tokens') if type(generated) is dict else None,
    }
    observed = confirm_final_usage(
        initial,
        values,
        response_ref=initial.response_ref,
        contract=draft.frozen.admission.usage,
        source='COMPLETE_BODY',
        complete=complete,
        audit_complete=complete,
    )
    return observed, complete


def _parse_result(connection, response, complete, frozen):
    if not complete or response.finish_reason != 'stop' or response.category is not None:
        return None, None
    body = response.raw_response
    choices = body.get('choices')
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        return None, None
    message = choices[0].get('message')
    if (
        type(message) is not dict
        or message.get('role') != 'assistant'
        or any(message.get(field) for field in ('tool_calls', 'function_call', 'refusal'))
        or type(message.get('content')) is not str
    ):
        return None, None
    try:
        parsed = parse_draft(message['content'])
    except (ValueError, TypeError, RecursionError):
        return None, None
    try:
        trusted = validate_draft(connection, parsed, frozen)
    except (CheckResourceError, ValueError, TypeError, RecursionError):
        return parsed, None
    return parsed, {key: trusted[key] for key in parsed}


def _save_draft(connection, original, frozen, trusted, at):
    plan = entity_id(connection, EntityKind.TEST_PLAN)
    connection.execute(
        'INSERT INTO testing_plans(id,name,created_at) VALUES(?,?,?)',
        (plan, f'独立测试计划（任务 {original.task["id"]}）', at),
    )
    version = insert_draft_version(connection, {**frozen.basis, **trusted}, plan, 1, at)
    return {'plan_id': plan, 'plan_version_id': version['id']}


def _end_unknown(connection, original, at):
    _step(connection, original, CALL_STEP, 'UNKNOWN', at)
    _task_result(connection, original, waiting=True, at=at)
    _end_operation(connection, original, 'UNKNOWN', 'EXTERNAL_RESULT_UNKNOWN', at)


def _save_call(connection, original, draft, response, *, at):
    state, complete = _usage(response, draft)
    usage = dict(state.latest)
    parsed, trusted = _parse_result(connection, response, complete, draft.frozen)
    credential = draft.frozen.admission.model.api_key
    parsed_audit = None if parsed is None else audit_json(parsed, credentials=(credential,))
    trusted_audit = None if trusted is None else audit_json(trusted, credentials=(credential,))
    raw = None if response is None else response.raw_response_json
    settlement = None
    usage_status = state.status
    if state.settlement_usage is not None:
        charged = final_usage_cost(state, draft.frozen.prices)
        if (
            usage['input_tokens'] <= draft.frozen.facts['input_cap']
            and usage['output_tokens'] <= draft.frozen.facts['output_cap']
            and charged <= parse_money(original.reservation['reserved_cny'])
        ):
            settlement = format_money(charged)
        else:
            usage_status = 'DISPUTED'
    reserved = (
        'SETTLED'
        if settlement is not None
        else 'DISPUTED'
        if usage_status == 'DISPUTED'
        else 'UNKNOWN'
    )
    open_draft = current_draft(original)
    call_status = 'CANCELLED' if not open_draft else 'SUCCEEDED' if complete else 'FAILED'
    error = (
        'MODEL_RESULT_UNKNOWN'
        if settlement is None
        else 'INVALID_OUTPUT'
        if trusted is None
        else None
    )
    capture = (
        'INCOMPLETE'
        if not complete
        else 'REDACTED'
        if original.use['capture_status'] == 'REDACTED' or '[REDACTED_' in raw
        else 'FULL'
    )
    cache = {
        key: value for key, value in usage.items() if key in ('cached_tokens', 'reasoning_tokens')
    }
    connection.execute(
        """UPDATE llm_uses SET transport_status=?,call_status=?,parse_status=?,validation_status=?,
           usage_status=?,capture_status=?,raw_response_json=?,parsed_output_json=?,trusted_output_json=?,
           input_tokens=?,output_tokens=?,cache_info_json=?,provider_request_id=?,finish_reason=?,
           cost=?,cost_currency=?,error_code=?,duration_ms=?,ended_at=? WHERE id=?""",
        (
            'COMPLETE' if complete else 'UNKNOWN',
            call_status,
            'FAILED' if parsed is None else 'SUCCEEDED',
            'PENDING' if parsed is None else 'FAILED' if trusted is None else 'SUCCEEDED',
            usage_status,
            capture,
            raw,
            parsed_audit,
            trusted_audit,
            usage.get('input_tokens'),
            usage.get('output_tokens'),
            canonical_input(cache) if cache else None,
            None if response is None else response.provider_request_id,
            None if response is None else response.finish_reason,
            settlement,
            None if settlement is None else 'CNY',
            error,
            None if response is None else response.duration_ms,
            at,
            original.use['id'],
        ),
    )
    connection.execute(
        """UPDATE code_task_reservations SET status=?,settled_cny=?,settled_at=?,settlement_basis=?
           WHERE id=? AND status='RESERVED'""",
        (
            reserved,
            settlement,
            None if settlement is None else at,
            None if settlement is None else 'VERIFIED_USAGE',
            original.reservation['id'],
        ),
    )
    if settlement is not None:
        connection.execute(
            """INSERT INTO model_usage_evidence(id,llm_use_id,external_evidence_id,source_ref,usage,
               received_at,status) VALUES(?,?,?,?,?,?,'VERIFIED')""",
            (
                entity_id(connection, EntityKind.MODEL_USAGE_EVIDENCE),
                original.use['id'],
                state.response_ref,
                'TEST20-PLAN-1:COMPLETE_BODY',
                canonical_input(usage),
                at,
            ),
        )
    return open_draft, settlement, trusted


def finish_draft(runtime, draft, response):
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        operation = _operation(connection, draft.operation_id)
        if operation is None:
            raise StorageUnavailable('Original Testing draft disappeared')
        original = read_original_draft(connection, operation)
        if original.use['ended_at'] is not None:
            return
        if (
            original.use['id'] != draft.use_id
            or original.use['transport_status'] != 'SENDING'
            or original.reservation['status'] != 'RESERVED'
            or draft.frozen.facts != original.fixed['facts']
        ):
            raise StorageUnavailable('Original Testing draft completion differs')
        at = max(operation_time(None), original.use['started_at'])
        open_draft, settlement, trusted = _save_call(connection, original, draft, response, at=at)
        if not open_draft:
            _step(connection, original, CALL_STEP, 'CANCELLED', at)
            _step(connection, original, SAVE_STEP, 'CANCELLED', at)
            _end_operation(connection, original, 'CANCELLED', None, at)
        elif settlement is None:
            _end_unknown(connection, original, at)
        else:
            _step(
                connection,
                original,
                CALL_STEP,
                'SUCCEEDED',
                at,
                result={'llm_use_id': draft.use_id},
            )
            refs = (
                None
                if trusted is None
                else _save_draft(connection, original, draft.frozen, trusted, at)
            )
            outcome = 'FAILED' if refs is None else 'SUCCEEDED'
            _step(connection, original, SAVE_STEP, outcome, at, result=refs)
            _task_result(connection, original, waiting=False, at=at)
            _end_operation(
                connection, original, outcome, None if refs else 'EVIDENCE_INCOMPLETE', at
            )


def recover_drafts(runtime):
    """An interrupted send is never put back into the dispatch queue."""
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        operations = connection.execute(
            """SELECT o.* FROM code_operations o JOIN llm_uses u ON u.operation_id=o.id
               AND u.testing_task_id=o.testing_task_id WHERE o.testing_task_id=o.resource_id
               AND o.task_id IS NULL AND o.operation_type='DRAFT_PLAN' AND o.status='RUNNING'
               AND u.transport_status='SENDING' AND u.ended_at IS NULL ORDER BY o.id"""
        ).fetchall()
        for operation in operations:
            original = read_original_draft(connection, operation)
            at = max(operation_time(None), original.use['started_at'])
            active = current_draft(original)
            connection.execute(
                """UPDATE llm_uses SET transport_status='UNKNOWN',call_status=?,capture_status='INCOMPLETE',
                   error_code='MODEL_RESULT_UNKNOWN',ended_at=? WHERE id=?""",
                ('FAILED' if active else 'CANCELLED', at, original.use['id']),
            )
            connection.execute(
                "UPDATE code_task_reservations SET status='UNKNOWN' WHERE id=? AND status='RESERVED'",
                (original.reservation['id'],),
            )
            if active:
                _end_unknown(connection, original, at)
            else:
                _step(connection, original, CALL_STEP, 'CANCELLED', at)
                _step(connection, original, SAVE_STEP, 'CANCELLED', at)
                _end_operation(connection, original, 'CANCELLED', None, at)


def _send_still_current(runtime, draft):
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction() as connection:
        operation = _operation(connection, draft.operation_id)
        if operation is None:
            return False
        original = read_original_draft(connection, operation)
        return (
            current_draft(original)
            and original.use['id'] == draft.use_id
            and original.use['transport_status'] == 'SENDING'
            and original.use['ended_at'] is None
        )


async def _wait_for_fence(runtime, draft, closing):
    while not closing.is_set():
        try:
            await asyncio.wait_for(closing.wait(), timeout=0.5)
        except TimeoutError:
            try:
                if not await asyncio.to_thread(_send_still_current, runtime, draft):
                    return
            except StorageUnavailable:
                return


async def _send(runtime, draft, closing):
    try:
        if closing.is_set() or not await asyncio.to_thread(_send_still_current, runtime, draft):
            return None
    except StorageUnavailable:
        return None
    call = asyncio.create_task(
        draft.gateway.send(
            draft.frozen.admission.model,
            draft.frozen.model_input,
            testing_limits=(
                draft.frozen.facts['output_cap'],
                draft.frozen.facts['query_timeout_seconds'],
                draft.frozen.timeout_seconds,
            ),
        )
    )
    shutdown = asyncio.create_task(_wait_for_fence(runtime, draft, closing))
    try:
        await asyncio.wait(
            (call, shutdown),
            timeout=draft.frozen.timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        return call.result() if call.done() else None
    finally:
        for pending in (call, shutdown):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(call, shutdown, return_exceptions=True)


async def serve_testing_plans(runtime, wake, closing):
    pending = None
    response = None
    while True:
        wake.clear()
        if pending is not None:
            try:
                await asyncio.to_thread(finish_draft, runtime, pending, response)
            except StorageUnavailable:
                if closing.is_set():
                    return
                await asyncio.sleep(0.1)
                continue
            pending, response = None, None
        if closing.is_set():
            return
        try:
            pending = await asyncio.to_thread(claim_draft, runtime)
        except StorageUnavailable:
            pending = None
        if pending is False:
            pending = None
            continue
        if pending is not None:
            response = await _send(runtime, pending, closing)
            continue
        try:
            await asyncio.wait_for(wake.wait(), timeout=1)
        except TimeoutError:
            pass
