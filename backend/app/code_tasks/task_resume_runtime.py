"""Advance the accepted model continuation with a durable one-send boundary."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .coding_job_evidence import read_closed_candidate_job_ids
from .coding_model_admission import effective_coding_binding
from .coding_model_ledger import _consecutive_failures, budget_facts
from .coding_model_listener import CodingGatewayError
from .coding_model_wait import read_task_waits
from .costs import reserve_cost
from .task_model_ingress import ModelWindow, read_original_window_state
from .task_resume import ACTIVE, model_resume_window, model_waits_cleared, original_resume_steps
from .task_start_session import StartSessionScope, original_active_session_scope


@dataclass(frozen=True)
class Continuation:
    scope: StartSessionScope
    previous: ModelWindow
    credential_ref: str
    native_session_id: str | None = None

    def __post_init__(self):
        if self.native_session_id is not None:
            from backend.app.infrastructure.opencode_instance_control import _identifier

            from .task_start_session import SuccessorSessionScope

            _identifier(self.native_session_id, 'ses')

            if (
                type(self.scope) is not SuccessorSessionScope
                or self.scope.transition_kind != 'REPAIR'
                or self.previous.task_id != self.scope.task_id
                or self.previous.instance_id != self.scope.instance_id
                or self.previous.generation + 1 != self.scope.control_generation
                or self.previous.execution_session_id == self.scope.session_id
                or self.previous.native_session_id == self.native_session_id
            ):
                raise TaskExecutionError('ORIGINAL_REPAIR_MESSAGE_SOURCE_DIFFERS')

    def window(self, operation_id, message_id):
        return ModelWindow(
            self.scope.task_id,
            self.scope.instance_id,
            self.scope.control_generation,
            self.scope.session_id,
            self.native_session_id or self.previous.native_session_id,
            operation_id,
            message_id,
        )


def _current(connection, operation_id):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
    ).fetchone()
    if operation is None or operation['status'] not in ACTIVE:
        return None
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    if (
        task is None
        or task['status'] != 'WAITING'
        or task['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
        or task['resume_phase'] != task['phase']
        or task['stop_requested_at'] is not None
        or task['control_generation'] != operation['control_generation']
        or task['active_session_id'] != operation['session_id']
        or task['state_version'] <= operation['expected_state_version']
    ):
        return None
    fixed, steps = original_resume_steps(connection, operation)
    if (
        connection.execute(
            """SELECT 1 FROM code_operations WHERE task_id=? AND id<>?
           AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1""",
            (task['id'], operation_id),
        ).fetchone()
        or read_closed_candidate_job_ids(connection, task['id']) is None
    ):
        raise StorageUnavailable('Original continuation has another possible writer')
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (operation['session_id'], task['id']),
    ).fetchone()
    if session is None:
        raise StorageUnavailable('Original continuation session is missing')
    durable = steps[2]['external_identity']
    if durable is None:
        held = model_resume_window(connection, task)
        if held is None or held[0].operation_id != fixed['operation_id']:
            raise StorageUnavailable('Original continuation held window differs')
        previous, _ = held
        intent = None
    else:
        intent = strict_json_object(durable)
        previous = ModelWindow(
            task['id'],
            session['instance_id'],
            task['control_generation'],
            session['id'],
            session['native_session_id'],
            fixed['operation_id'],
            intent['previous_message_id'],
        )
    waits = read_task_waits(connection, task['id'])
    if {item['id'] for item in waits} != set(fixed['waiting_item_ids']):
        raise StorageUnavailable('Original continuation waiting scope differs')
    scope = Continuation(
        original_active_session_scope(connection, task, session),
        previous,
        session['gateway_credential_ref'],
    )
    if intent is not None:
        window = scope.window(operation_id, intent['payload']['messageID'])
        if (
            intent != _intent(scope, intent['payload'])
            or steps[2]['status'] not in ('RUNNING', 'UNKNOWN')
            or read_original_window_state(connection, window, scope.credential_ref) != 'QUEUED'
        ):
            raise StorageUnavailable('Original continuation dispatch identity differs')
    return task, operation, steps, scope, waits, intent


def _intent(scope, payload):
    return {
        'session_id': scope.scope.session_id,
        'instance_id': scope.scope.instance_id,
        'generation': scope.scope.control_generation,
        'original_operation_id': scope.previous.operation_id,
        'previous_message_id': scope.previous.trigger_message_id,
        'payload_sha256': hashlib.sha256(_bytes(payload)).hexdigest(),
        'payload': payload,
    }


def _model_admissible(connection, catalog, admissions, scope, waits, at):
    previous = scope.previous
    return model_waits_cleared(connection, previous, waits) and _model_capacity_available(
        connection, catalog, admissions, previous, at
    )


def _model_capacity_available(connection, catalog, admissions, previous, at):
    try:
        binding = effective_coding_binding(
            connection, catalog, admissions, previous, 'walle-code', at
        )
    except CodingGatewayError:
        return False
    budget = budget_facts(connection, previous.task_id, binding.budget_micro)
    prices = binding.prices
    required = reserve_cost(
        binding.contract.input_cap,
        binding.contract.permitted_output,
        max([prices.input_micro, *(item.price_micro for item in prices.cache)]),
        prices.output_micro,
    )
    return (
        budget.requests < binding.max_requests
        and budget.available >= required
        and _consecutive_failures(connection, previous.task_id, binding.max_consecutive_failures)
        < binding.max_consecutive_failures
    )


def _step(connection, identity, number, status, at, *, result=None, intent=None):
    connection.execute(
        """UPDATE code_operation_steps SET status=?,started_at=coalesce(started_at,?),
           ended_at=?,last_observed_at=?,result_ref=?,external_identity=coalesce(external_identity,?)
           WHERE operation_id=? AND step_no=?""",
        (
            status,
            at,
            at if status in ('SUCCEEDED', 'FAILED', 'CANCELLED') else None,
            at,
            None if result is None else canonical_input(result),
            None if intent is None else canonical_input(intent),
            identity,
            number,
        ),
    )


def _operation(connection, identity, status, at, code=None):
    connection.execute(
        """UPDATE code_operations SET status=?,started_at=coalesce(started_at,?),ended_at=?,failure_code=?
           WHERE id=?""",
        (status, at, at if status in ('SUCCEEDED', 'FAILED') else None, code, identity),
    )


def _window(connection, window, status, at):
    value = {
        'operation_id': window.operation_id,
        'native_trigger_message_id': window.trigger_message_id,
        'state': status,
        'opened_at': at if status == 'OPEN' else None,
        'closed_at': None,
    }
    if (
        connection.execute(
            """UPDATE code_sessions SET model_window=?,last_observed_at=?
           WHERE id=? AND task_id=? AND status='ACTIVE' AND control_generation=?""",
            (
                canonical_input(value),
                at,
                window.execution_session_id,
                window.task_id,
                window.generation,
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original continuation window changed')


def _finish(connection, task, operation, scope, waits, window, at):
    identity = operation['id']
    _window(connection, window, 'OPEN', at)
    resolution = canonical_input({'operation_id': identity, 'outcome': 'MODEL_RESUMED'})
    for wait in waits:
        if (
            connection.execute(
                """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
               WHERE id=? AND task_id=? AND status='OPEN'""",
                (at, resolution, wait['id'], task['id']),
            ).rowcount
            != 1
        ):
            raise StorageUnavailable('Original continuation waiting item changed')
    if (
        connection.execute(
            """UPDATE code_tasks SET status='RUNNING',resume_phase=NULL,state_version=state_version+1,
           updated_at=?,last_observed_at=? WHERE id=? AND status='WAITING' AND phase IN ('BACKEND','FRONTEND','INTEGRATION')
           AND control_generation=? AND state_version=? AND stop_requested_at IS NULL""",
            (at, at, task['id'], task['control_generation'], task['state_version']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original continuation completion fence differs')
    _step(connection, identity, 3, 'SUCCEEDED', at, result={'session_id': scope.scope.session_id})
    _operation(connection, identity, 'SUCCEEDED', at)


def _next_operation(connection):
    now = datetime.fromisoformat(operation_time(None))
    retry_before = (
        (now - timedelta(seconds=3)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    )
    return connection.execute(
        """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
           JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_no=3
           WHERE o.operation_type='RESUME' AND o.resource_kind='TASK'
           AND json_extract(o.fixed_input,'$.repository_quiescent_confirmed') IS NULL
           AND t.status='WAITING' AND t.phase IN ('BACKEND','FRONTEND','INTEGRATION')
           AND t.stop_requested_at IS NULL AND t.control_generation=o.control_generation
           AND (o.status IN ('PENDING','RUNNING') OR (o.status='UNKNOWN' AND s.last_observed_at<=?))
           ORDER BY (o.status='UNKNOWN'),o.id LIMIT 1""",
        (retry_before,),
    ).fetchone()


def advance_model_resumes(runtime, driver, admissions, *, cancelled):
    if cancelled():
        return False
    db = runtime.database
    with db.transaction() as connection:
        row = _next_operation(connection)
        current = None if row is None else _current(connection, row['id'])
    if current is None:
        return False
    task, operation, _, scope, _, intent = current
    identity = operation['id']

    def checkpoint():
        if cancelled():
            raise TaskExecutionError('ORIGINAL_CONTINUATION_CANCELLED')
        with db.transaction() as connection:
            value = _current(connection, identity)
            if value is None or value[3] != scope:
                raise TaskExecutionError('ORIGINAL_CONTINUATION_FENCED')

    if intent is None:
        code = None
        payload = None
        if driver.session_available(scope.scope.operation_id):
            try:
                payload = driver.continuation_payload(
                    scope.scope, scope.previous, scope.credential_ref, checkpoint
                )
            except (TaskExecutionError, LaunchOutcomeUnknown, OSError):
                code = 'EXECUTION_NOT_STOPPED'
        else:
            code = 'CONFIG_NOT_READY'
        with db.transaction(write=True) as connection:
            current = _current(connection, identity)
            if current is None or current[3] != scope or current[5] is not None or cancelled():
                return False
            task, _, _, _, waits, _ = current
            at = max(operation_time(None), task['updated_at'])
            if code is not None:
                _step(connection, identity, 1, 'FAILED', at)
                _operation(connection, identity, 'FAILED', at, code)
                return True
            _step(
                connection,
                identity,
                1,
                'SUCCEEDED',
                at,
                result={'operation_id': scope.previous.operation_id},
            )
            if task['state_version'] >= MAX_SAFE_INTEGER - 1 or not _model_admissible(
                connection, runtime.catalog, admissions, scope, waits, at
            ):
                _step(connection, identity, 2, 'FAILED', at)
                _operation(connection, identity, 'FAILED', at, 'CONFIG_NOT_READY')
                return True
            window = scope.window(identity, payload['messageID'])
            if window.trigger_message_id == scope.previous.trigger_message_id:
                raise StorageUnavailable('Original continuation cannot reuse its trigger message')
            intent = _intent(scope, payload)
            _step(connection, identity, 2, 'SUCCEEDED', at)
            _step(connection, identity, 3, 'RUNNING', at, intent=intent)
            _operation(connection, identity, 'RUNNING', at)
            _window(connection, window, 'QUEUED', at)
        try:
            checkpoint()
            driver.dispatch_continuation(
                scope.scope, scope.previous, window, scope.credential_ref, payload, checkpoint
            )
        except (TaskExecutionError, LaunchOutcomeUnknown, OSError):
            # The durable intent may already have crossed the native boundary.
            # Only the exact fixed native message is eligible for observation.
            pass

    payload = intent['payload']
    window = scope.window(identity, payload['messageID'])
    confirmed = False
    try:
        checkpoint()
        confirmed = (
            driver.observe_continuation(
                scope.scope, window, scope.credential_ref, payload, checkpoint
            )
            == window.trigger_message_id
        )
    except (TaskExecutionError, LaunchOutcomeUnknown, OSError):
        pass
    with db.transaction(write=True) as connection:
        current = _current(connection, identity)
        if current is None or current[3] != scope or current[5] != intent or cancelled():
            return False
        task, operation, _, _, waits, _ = current
        at = max(operation_time(None), task['updated_at'])
        if confirmed and model_waits_cleared(connection, scope.previous, waits):
            _finish(connection, task, operation, scope, waits, window, at)
        else:
            _step(connection, identity, 3, 'UNKNOWN', at)
            _operation(connection, identity, 'UNKNOWN', at, 'EXTERNAL_RESULT_UNKNOWN')
    return True
