"""Original Coding LLMUse, response frames, and reservation transactions."""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from secrets import token_hex

from backend.app.infrastructure.audit_data import sanitize_audit
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .coding_model_admission import EffectiveCodingBinding, effective_coding_binding
from .coding_model_listener import CodingGatewayError
from .coding_model_request import ALIASES, REQUEST_BYTES, CodingModelRequest
from .coding_model_wait import hold_coding_model
from .costs import (
    available_balance,
    final_usage_cost,
    format_balance,
    format_money,
    parse_money,
    reserve_cost,
)
from .task_model_ingress import ModelIngressProof, ModelWindow, read_original_open_window
from .usage import UsageState

_EVIDENCE = re.compile(r'[0-9a-f]{64}')
FRAME_BYTES = 1024 * 1024
RESPONSE_BYTES = 16 * 1024 * 1024
_HELD_RESERVATION = ('RESERVED', 'UNKNOWN', 'DISPUTED')


@dataclass(frozen=True)
class BudgetFacts:
    limit: int
    settled: int
    reserved: int
    unresolved: int
    requests: int

    @property
    def available(self):
        return available_balance(self.limit, self.settled, self.reserved)

    def public(self):
        return {
            'limit_cny': format_money(self.limit),
            'settled_cny': format_money(self.settled),
            'reserved_cny': format_money(self.reserved),
            'available_cny': format_balance(self.available),
            'unresolved_call_count': self.unresolved,
        }


def budget_facts(connection, task_id, limit, *, owner='CODING'):
    owner_column = {'CODING': 'task_id', 'TESTING': 'testing_task_id'}[owner]
    settled = reserved = unresolved = requests = 0
    rows = connection.execute(
        f'SELECT status,reserved_cny,settled_cny FROM code_task_reservations WHERE {owner_column}=?',
        (task_id,),
    )
    for row in rows:
        status = row['status']
        if status != 'RELEASED_UNSENT':
            requests += 1
        if row['settled_cny'] is not None:
            settled += parse_money(row['settled_cny'])
        elif status in _HELD_RESERVATION:
            reserved += parse_money(row['reserved_cny'])
        if status in ('UNKNOWN', 'DISPUTED'):
            unresolved += 1
    return BudgetFacts(limit, settled, reserved, unresolved, requests)


@dataclass(frozen=True)
class CodingAuditRequest:
    encoded: str
    capture_status: str


def prepare_audit_request(proof, request, binding, credential_values):
    snapshot = {
        'native_request': request.native,
        'supplier_request': request.supplier,
        'model': {
            'profile_ref': binding.admission.model.profile_id,
            'snapshot_ref': binding.admission.model_snapshot_ref,
            'model_name': binding.admission.model.model_name,
            'model_version': binding.admission.model.model_version,
            'admission_ref': binding.admission.evidence_ref,
            'price_version_id': binding.price_version_id,
            'input_cap_tokens': binding.contract.input_cap,
            'context_cap_tokens': binding.contract.context_cap,
            'output_cap_tokens': request.output_cap,
        },
        'window': {
            'task_id': proof.window.task_id,
            'execution_session_id': proof.window.execution_session_id,
            'operation_id': proof.window.operation_id,
            'control_generation': proof.window.generation,
            'instance_id': proof.window.instance_id,
            'source_evidence_ref': proof.source_evidence_ref,
        },
    }
    clean = sanitize_audit(snapshot, credentials=credential_values)
    encoded = canonical_input(clean)
    if len(encoded.encode('utf-8')) > REQUEST_BYTES:
        raise CodingGatewayError('protocol')
    return CodingAuditRequest(encoded, 'FULL' if clean == snapshot else 'REDACTED')


@dataclass(frozen=True)
class CodingCall:
    llm_use_id: int
    reservation_id: int
    gateway_request_id: str
    window: ModelWindow
    credential_ref: str
    source_evidence_ref: str
    connection_sha256: str
    binding: EffectiveCodingBinding
    started_at: str
    reserved_micro: int


def _check_open(connection, window, credential_ref):
    if read_original_open_window(connection, window, credential_ref) != window:
        raise CodingGatewayError('hold')


def _consecutive_failures(connection, task_id, limit):
    calls = connection.execute(
        """SELECT u.call_status,r.status AS reservation_status FROM llm_uses u
           JOIN code_task_reservations r ON r.llm_use_id=u.id
           WHERE r.task_id=? AND r.status<>'RELEASED_UNSENT' ORDER BY u.id DESC LIMIT ?""",
        (task_id, limit),
    )
    failures = 0
    for row in calls:
        if row['call_status'] not in ('FAILED', 'CANCELLED') and row['reservation_status'] not in (
            'UNKNOWN',
            'DISPUTED',
        ):
            break
        failures += 1
    return failures


def reserve_call(connection, catalog, admissions, credential_ref, proof, request, binding, audit):
    require_write_transaction(connection)
    if (
        type(proof) is not ModelIngressProof
        or type(request) is not CodingModelRequest
        or type(binding) is not EffectiveCodingBinding
        or type(audit) is not CodingAuditRequest
        or any(
            type(ref) is not str or not _EVIDENCE.fullmatch(ref)
            for ref in (proof.source_evidence_ref, proof.connection_sha256)
        )
    ):
        raise CodingGatewayError('source')
    window = proof.window
    _check_open(connection, window, credential_ref)
    now = operation_time(None)
    alias = request.native['model']
    if effective_coding_binding(connection, catalog, admissions, window, alias, now) != binding:
        raise CodingGatewayError('hold')
    budget = budget_facts(connection, window.task_id, binding.budget_micro)
    if (
        budget.unresolved
        or connection.execute(
            """SELECT 1 FROM llm_uses u JOIN code_task_reservations r ON r.llm_use_id=u.id
           WHERE u.execution_session_id=? AND r.status='RESERVED' LIMIT 1""",
            (window.execution_session_id,),
        ).fetchone()
    ):
        raise CodingGatewayError('hold')
    if (
        _consecutive_failures(connection, window.task_id, binding.max_consecutive_failures)
        >= binding.max_consecutive_failures
    ):
        raise CodingGatewayError('hold')
    prices = binding.prices
    reserved = reserve_cost(
        binding.contract.input_cap,
        request.output_cap,
        max([prices.input_micro, *(item.price_micro for item in prices.cache)]),
        prices.output_micro,
    )
    if budget.requests >= binding.max_requests:
        hold_coding_model(connection, window, credential_ref, kind='BUDGET')
        return None
    latest = connection.execute(
        'SELECT MAX(call_no) FROM llm_uses WHERE execution_session_id=?',
        (window.execution_session_id,),
    ).fetchone()[0]
    call_no = 1 if latest is None else latest + 1
    if call_no > MAX_SAFE_INTEGER:
        raise CodingGatewayError('hold')
    use = entity_id(connection, EntityKind.LLM_USE)
    reservation = entity_id(connection, EntityKind.CODE_TASK_RESERVATION)
    request_id = token_hex(16)
    model = binding.admission.model
    purpose = ALIASES[alias]
    prompt = 'CP20-1.0' if purpose == 'CODE' else 'OPENCODE-COMPACTION-810c0eba'
    context = canonical_input(
        {
            'kind': 'CODING_NATIVE',
            'execution_profile_version_id': binding.profile_version_id,
            'request_sha256': hashlib.sha256(request.supplier_body).hexdigest(),
        }
    )
    connection.execute(
        """INSERT INTO llm_uses(id,execution_session_id,operation_id,gateway_request_id,call_no,
           attempt_no,provider,model_name,model_version,function_type,prompt_config,request_snapshot_json,
           input_summary,context_manifest_json,parse_status,validation_status,call_status,started_at,
           protocol_version,call_purpose,transport_status,usage_status,capture_status,source_evidence_ref)
           VALUES(?,?,?,?,?,1,'volcengine',?,?,'CODE_EXECUTION',?,?,?,?,'NOT_APPLICABLE','NOT_APPLICABLE',
                  'RUNNING',?,'OC20-MODEL-1',?,'NOT_SENT','NOT_REPORTED',?,?)""",
        (
            use,
            window.execution_session_id,
            window.operation_id,
            request_id,
            call_no,
            model.model_name,
            model.model_version,
            prompt,
            audit.encoded,
            purpose,
            context,
            now,
            purpose,
            audit.capture_status,
            proof.source_evidence_ref,
        ),
    )
    connection.execute(
        """INSERT INTO code_task_reservations(id,task_id,llm_use_id,price_version_id,reserved_cny,status,created_at)
           VALUES(?,?,?,?,?,'RESERVED',?)""",
        (reservation, window.task_id, use, binding.price_version_id, format_money(reserved), now),
    )
    return CodingCall(
        use,
        reservation,
        request_id,
        window,
        credential_ref,
        proof.source_evidence_ref,
        proof.connection_sha256,
        binding,
        now,
        reserved,
    )


def _original_call(connection, call):
    row = connection.execute(
        """SELECT u.transport_status,u.ended_at,u.raw_response_json,u.capture_status,u.call_status,
                  r.status AS reservation_status FROM llm_uses u
           JOIN code_task_reservations r ON r.llm_use_id=u.id AND r.task_id=?
           WHERE u.id=? AND r.id=? AND u.execution_session_id=? AND u.operation_id=?
           AND u.gateway_request_id=? AND u.source_evidence_ref=?""",
        (
            call.window.task_id,
            call.llm_use_id,
            call.reservation_id,
            call.window.execution_session_id,
            call.window.operation_id,
            call.gateway_request_id,
            call.source_evidence_ref,
        ),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original Coding model call differs')
    return row


def mark_sending(connection, call, proof):
    require_write_transaction(connection)
    if (
        type(proof) is not ModelIngressProof
        or proof.window != call.window
        or proof.source_evidence_ref != call.source_evidence_ref
        or proof.connection_sha256 != call.connection_sha256
    ):
        raise CodingGatewayError('source')
    _check_open(connection, call.window, call.credential_ref)
    row = _original_call(connection, call)
    if (
        row['reservation_status'] != 'RESERVED'
        or row['transport_status'] != 'NOT_SENT'
        or row['ended_at'] is not None
    ):
        raise CodingGatewayError('hold')
    connection.execute(
        "UPDATE llm_uses SET transport_status='SENDING' WHERE id=?", (call.llm_use_id,)
    )


def mark_sent(connection, call, provider_request_id):
    require_write_transaction(connection)
    row = _original_call(connection, call)
    if row['transport_status'] != 'SENDING' or row['ended_at'] is not None:
        raise StorageUnavailable('Original Coding send is not current')
    connection.execute(
        "UPDATE llm_uses SET transport_status='SENT',provider_request_id=? WHERE id=?",
        (provider_request_id, call.llm_use_id),
    )


def _frame_summary(count, size, complete=False):
    return canonical_input(
        {
            'kind': 'SSE_FRAMES',
            'frame_count': count,
            'captured_bytes': size,
            'complete': complete,
        }
    )


def append_frame(connection, call, number, frame, credentials, usage):
    require_write_transaction(connection)
    row = _original_call(connection, call)
    if (
        row['transport_status'] != 'SENT'
        or row['ended_at'] is not None
        or type(usage) is not UsageState
        or usage.response_ref != call.gateway_request_id
    ):
        raise StorageUnavailable('Original Coding frame owner is not active')
    clean = sanitize_audit(frame, credentials=credentials)
    encoded = canonical_input(clean)
    size = len(encoded.encode('utf-8'))
    if size > FRAME_BYTES:
        raise StorageUnavailable('Original Coding frame audit exceeds its limit')
    previous = {'frame_count': 0, 'captured_bytes': 0}
    if row['raw_response_json'] is not None:
        previous = strict_json_object(row['raw_response_json'])
    if previous['frame_count'] + 1 != number or previous['captured_bytes'] + size > RESPONSE_BYTES:
        raise StorageUnavailable('Original Coding frame audit sequence exceeds its limit')
    capture = 'FULL' if clean == frame else 'REDACTED'
    connection.execute(
        """INSERT INTO code_model_response_frames(llm_use_id,seq,received_at,frame_json,capture_status)
           VALUES(?,?,?,?,?)""",
        (call.llm_use_id, number, max(operation_time(None), call.started_at), encoded, capture),
    )
    reported = dict(usage.latest)
    cache = {key: reported[key] for key in ('cached_tokens', 'reasoning_tokens') if key in reported}
    connection.execute(
        """UPDATE llm_uses SET raw_response_json=?,capture_status=?,usage_status=?,
           input_tokens=?,output_tokens=?,cache_info_json=? WHERE id=?""",
        (
            _frame_summary(number, previous['captured_bytes'] + size),
            'REDACTED' if capture == 'REDACTED' or row['capture_status'] == 'REDACTED' else 'FULL',
            'PARTIAL' if usage.status == 'FINAL' else usage.status,
            reported.get('input_tokens'),
            reported.get('output_tokens'),
            canonical_input(cache) if cache else None,
            call.llm_use_id,
        ),
    )


def release_unsent(connection, call):
    """The current sender has proven transport was never entered."""
    require_write_transaction(connection)
    row = _original_call(connection, call)
    if (
        row['reservation_status'] != 'RESERVED'
        or row['transport_status'] not in ('NOT_SENT', 'SENDING')
        or row['ended_at'] is not None
    ):
        raise StorageUnavailable('Original Coding reservation cannot be released')
    now = max(operation_time(None), call.started_at)
    _release(connection, call.llm_use_id, call.reservation_id, now)


def _release(connection, use, reservation, now):
    connection.execute(
        """UPDATE llm_uses SET transport_status='NOT_SENT',call_status='CANCELLED',ended_at=?,
           error_code='MODEL_NOT_SENT' WHERE id=?""",
        (now, use),
    )
    connection.execute(
        "UPDATE code_task_reservations SET status='RELEASED_UNSENT' WHERE id=?",
        (reservation,),
    )


def finish_call(connection, call, usage, *, complete, finish_reason, duration_ms, cancelled):
    require_write_transaction(connection)
    row = _original_call(connection, call)
    if (
        row['reservation_status'] != 'RESERVED'
        or row['transport_status'] not in ('SENDING', 'SENT')
        or row['ended_at'] is not None
        or type(usage) is not UsageState
        or usage.response_ref != call.gateway_request_id
    ):
        raise StorageUnavailable('Original Coding call completion differs')
    captured = connection.execute(
        """SELECT COUNT(*),COALESCE(SUM(length(CAST(frame_json AS BLOB))),0),
                  MAX(capture_status<>'FULL') FROM code_model_response_frames WHERE llm_use_id=?""",
        (call.llm_use_id,),
    ).fetchone()
    last = connection.execute(
        'SELECT frame_json FROM code_model_response_frames WHERE llm_use_id=? ORDER BY seq DESC LIMIT 1',
        (call.llm_use_id,),
    ).fetchone()
    now = max(operation_time(None), call.started_at)
    captured_complete = (
        complete
        and last is not None
        and strict_json_object(last['frame_json'])['kind'] == 'DONE'
        and finish_reason in ('stop', 'tool_calls', 'length', 'content_filter')
    )
    capture = 'INCOMPLETE'
    if captured_complete:
        capture = 'REDACTED' if captured[2] or row['capture_status'] == 'REDACTED' else 'FULL'
    summary = _frame_summary(captured[0], captured[1], captured_complete)
    observed = dict(usage.latest)
    settlement = None
    reservation = 'DISPUTED' if usage.status == 'DISPUTED' else 'UNKNOWN'
    elapsed = (
        datetime.fromisoformat(now) - datetime.fromisoformat(call.started_at)
    ).total_seconds()
    if (
        captured_complete
        and usage.settlement_usage is not None
        and elapsed <= call.binding.admission.max_duration_seconds
    ):
        observed = usage.settlement_usage
        settlement = final_usage_cost(usage, call.binding.prices)
        reservation = 'SETTLED'
    usage_status = usage.status
    if usage_status == 'FINAL' and not captured_complete:
        usage_status = 'PARTIAL'
    cache = {
        name: observed[name] for name in ('cached_tokens', 'reasoning_tokens') if name in observed
    }
    transport = (
        'COMPLETE'
        if captured_complete
        else 'INTERRUPTED'
        if row['transport_status'] == 'SENT'
        else 'UNKNOWN'
    )
    window_open = (
        read_original_open_window(connection, call.window, call.credential_ref) == call.window
    )
    status = (
        'CANCELLED'
        if cancelled or not window_open or row['call_status'] == 'CANCELLED'
        else 'SUCCEEDED'
        if captured_complete
        else 'FAILED'
    )
    connection.execute(
        """UPDATE llm_uses SET transport_status=?,usage_status=?,capture_status=?,raw_response_json=?,
           finish_reason=?,call_status=?,input_tokens=?,output_tokens=?,cache_info_json=?,
           ended_at=?,duration_ms=?,cost=?,cost_currency=?,error_code=? WHERE id=?""",
        (
            transport,
            usage_status,
            capture,
            summary,
            finish_reason,
            status,
            observed.get('input_tokens'),
            observed.get('output_tokens'),
            canonical_input(cache) if cache else None,
            now,
            duration_ms,
            None if settlement is None else format_money(settlement),
            None if settlement is None else 'CNY',
            None if captured_complete else 'MODEL_RESULT_UNKNOWN',
            call.llm_use_id,
        ),
    )
    connection.execute(
        """UPDATE code_task_reservations SET status=?,settled_cny=?,settled_at=?,settlement_basis=?
           WHERE id=?""",
        (
            reservation,
            None if settlement is None else format_money(settlement),
            None if settlement is None else now,
            None if settlement is None else 'VERIFIED_USAGE',
            call.reservation_id,
        ),
    )
    if settlement is None:
        hold_coding_model(
            connection,
            call.window,
            call.credential_ref,
            kind='MODEL_RESULT',
            llm_use_id=call.llm_use_id,
        )
    return status != 'CANCELLED'


def recover_interrupted_calls(connection):
    """Before listening, retire exact prior reservations without re-sending."""
    require_write_transaction(connection)
    rows = connection.execute(
        """SELECT u.id,u.operation_id,u.transport_status,u.started_at,u.raw_response_json,r.id AS reservation_id,
                  s.id AS session_id,s.native_session_id,s.native_message_id,s.gateway_credential_ref,
                  s.control_generation,s.instance_id,s.task_id,t.status AS task_status
           FROM llm_uses u JOIN code_task_reservations r ON r.llm_use_id=u.id
           JOIN code_sessions s ON s.id=u.execution_session_id AND s.task_id=r.task_id
           JOIN code_tasks t ON t.id=s.task_id
           WHERE r.status='RESERVED' AND u.ended_at IS NULL AND u.protocol_version='OC20-MODEL-1'
           ORDER BY u.id"""
    ).fetchall()
    for row in rows:
        now = max(operation_time(None), row['started_at'])
        if row['transport_status'] == 'NOT_SENT':
            _release(connection, row['id'], row['reservation_id'], now)
            continue
        if row['transport_status'] not in ('SENDING', 'SENT'):
            raise StorageUnavailable('Invalid retained Coding transport state')
        summary = row['raw_response_json'] or _frame_summary(0, 0)
        connection.execute(
            """UPDATE llm_uses SET transport_status='UNKNOWN',call_status=?,
               ended_at=?,capture_status='INCOMPLETE',raw_response_json=?,error_code='MODEL_RESULT_UNKNOWN'
               WHERE id=?""",
            (
                'CANCELLED' if row['task_status'] in ('STOPPING', 'TERMINATED') else 'FAILED',
                now,
                summary,
                row['id'],
            ),
        )
        connection.execute(
            "UPDATE code_task_reservations SET status='UNKNOWN' WHERE id=?",
            (row['reservation_id'],),
        )
        window = ModelWindow(
            row['task_id'],
            row['instance_id'],
            row['control_generation'],
            row['session_id'],
            row['native_session_id'],
            row['operation_id'],
            row['native_message_id'],
        )
        hold_coding_model(
            connection,
            window,
            row['gateway_credential_ref'],
            kind='MODEL_RESULT',
            llm_use_id=row['id'],
        )
    return len(rows)
