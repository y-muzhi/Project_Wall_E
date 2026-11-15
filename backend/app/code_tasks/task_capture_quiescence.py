"""Bind Coding's original capture QUIESCE to its closed write scope."""

import hashlib
from dataclasses import dataclass

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.infrastructure.opencode_instance_control import NativeTurnCompletion
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .operation_protocol import operation_steps
from .repository_operations import _time
from .task_cancelled_repair import read_cancelled_repair
from .task_instance_driver import CaptureTurnEvidence
from .task_model_ingress import ModelWindow
from .task_records import record_native_turn
from .task_start_session import (
    StartSessionScope,
    SuccessorSessionScope,
    original_active_session_scope,
)

_ACTIVE = ('PENDING', 'RUNNING', 'UNKNOWN')


@dataclass(frozen=True)
class CaptureQuiescence:
    operation_id: int
    task_version: int
    native_owner: StartSessionScope
    window: ModelWindow
    credential_ref: str
    model_window_json: str
    runtime_binding_ref: str
    guard_receipt_sha256: str
    observed_after: str


def _unsettled_inputs(
    connection, task_id, operation_id, instance_id, *, completed_capture_git=False
):
    return connection.execute(
        """SELECT
           EXISTS(SELECT 1 FROM code_operations o WHERE o.task_id=? AND o.id<>?
              AND o.status IN ('PENDING','RUNNING','UNKNOWN')
              AND NOT (o.operation_type='REPAIR' AND o.status='RUNNING' AND EXISTS(
                 SELECT 1 FROM code_operation_steps capture
                 JOIN code_repairs repair ON repair.operation_id=o.id AND repair.task_id=o.task_id
                 WHERE capture.operation_id=o.id AND capture.step_no=4
                   AND capture.status='RUNNING'
                   AND json_extract(capture.external_identity,'$.capture_operation_id')=?)))
           OR EXISTS(SELECT 1 FROM code_waiting_items w WHERE w.task_id=? AND w.status='OPEN'
              AND NOT (w.kind='OPERATION_RESULT' AND w.source_kind='OPERATION' AND w.source_id=?
                 AND EXISTS(SELECT 1 FROM code_repairs r WHERE r.task_id=w.task_id AND r.operation_id=w.source_id)))
           OR EXISTS(SELECT 1 FROM code_task_reservations WHERE task_id=?
              AND status IN ('RESERVED','UNKNOWN','DISPUTED'))
           OR EXISTS(SELECT 1 FROM code_commands c WHERE c.task_id=? AND NOT (
              (c.purpose='CONTROL_GIT' AND c.command_ref='GIT20-CONTENT-PACKAGE-1'
                 AND c.ended_at IS NOT NULL AND c.process_identity IS NOT NULL
                 AND COALESCE(json_extract(c.runtime_binding,'$.run_kind')='CONTROL_GIT',0)
                 AND ((? AND c.operation_id=? AND c.status='SUCCEEDED' AND c.exit_code=0)
                      OR (c.status IN ('SUCCEEDED','FAILED') AND EXISTS (
                         SELECT 1 FROM code_operations old WHERE old.id=c.operation_id
                           AND old.task_id=c.task_id AND old.operation_type IN ('CAPTURE_AND_CHECK','PREPARE_DELIVERY')
                           AND old.status IN ('SUCCEEDED','FAILED','CANCELLED')))))
              OR (c.purpose='CHECK' AND c.ended_at IS NOT NULL
                  AND c.status IN ('SUCCEEDED','FAILED','CANCELLED') AND EXISTS(
                     SELECT 1 FROM code_verification_items i
                     JOIN code_verifications v ON v.id=i.verification_id
                     WHERE i.id=c.verification_item_id AND i.command_execution_id=c.id
                       AND v.task_id=c.task_id AND v.operation_id=c.operation_id
                       AND v.owner_kind='CODING' AND v.stop_status='VERIFIED'
                       AND v.cleanup_status='VERIFIED'))))
           OR EXISTS(SELECT 1 FROM code_instances WHERE task_id=? AND id<>?)
           OR EXISTS(SELECT 1 FROM code_questions WHERE task_id=?
              AND status IN ('OPEN','ANSWERING','UNKNOWN'))
           OR EXISTS(SELECT 1 FROM code_permissions WHERE task_id=?
              AND status IN ('OPEN','ANSWERING','UNKNOWN'))""",
        (
            task_id,
            operation_id,
            operation_id,
            task_id,
            operation_id,
            task_id,
            task_id,
            int(completed_capture_git),
            operation_id,
            task_id,
            instance_id,
            task_id,
            task_id,
        ),
    ).fetchone()[0]


def active_candidate_check(connection, task_id):
    rows = connection.execute(
        """SELECT id,operation_type,status FROM code_operations WHERE task_id=?
           AND operation_type IN ('CAPTURE_AND_CHECK','VERIFY_CANDIDATE')
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id LIMIT 2""",
        (task_id,),
    ).fetchall()
    if len(rows) > 1:
        raise StorageUnavailable('More than one original candidate check is active')
    return rows[0] if rows else None


def capture_steps(connection, operation_id):
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no', (operation_id,)
    ).fetchall()
    expected = operation_steps('CODING', 'CAPTURE_AND_CHECK')
    if tuple((row['step_no'], row['step_type']) for row in steps) != tuple(enumerate(expected, 1)):
        raise StorageUnavailable('Original capture steps differ')
    return steps


def current_capture_owner(connection, task, operation_id=0):
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (task['active_session_id'], task['id']),
    ).fetchone()
    if session is None or session['role'] != task['phase']:
        raise StorageUnavailable('Original capture session differs')
    owner = original_active_session_scope(
        connection, task, session, original_handoff_id=operation_id
    )
    if _unsettled_inputs(connection, task['id'], operation_id, session['instance_id']):
        raise TaskExecutionError('ORIGINAL_CAPTURE_WRITERS_UNRESOLVED')

    saved = strict_json_object(session['model_window'])
    if (
        set(saved)
        != {'operation_id', 'native_trigger_message_id', 'state', 'opened_at', 'closed_at'}
        or saved['state'] not in ('OPEN', 'CLOSED')
        or (saved['state'] == 'CLOSED') != (saved['closed_at'] is not None)
        or not saved['opened_at']
        or not session['gateway_credential_ref']
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_MODEL_WINDOW_UNVERIFIED')
    _time(saved['opened_at'], nullable=False)
    cancelled = None
    if saved['state'] == 'CLOSED':
        _time(saved['closed_at'], nullable=False)
        cancelled = read_cancelled_repair(connection, task, session, saved)
        if (
            task['status'] != 'VERIFYING'
            or task['current_candidate_id'] is None
            or saved['closed_at'] < saved['opened_at']
            or connection.execute(
                """SELECT 1 FROM code_candidates c JOIN code_runtime_observations q
                   ON q.operation_id=c.capture_operation_id AND q.task_id=c.task_id
                   WHERE c.id=? AND c.task_id=? AND c.control_generation=?
                     AND q.kind='QUIESCE' AND q.result='VERIFIED' LIMIT 1""",
                (task['current_candidate_id'], task['id'], task['control_generation']),
            ).fetchone()
            is None
            and cancelled is None
        ):
            raise TaskExecutionError('ORIGINAL_CAPTURE_MODEL_WINDOW_UNVERIFIED')
    role_trigger = (
        type(owner) is SuccessorSessionScope
        and owner.transition_kind == 'HANDOFF_ROLE'
        and saved['operation_id'] == owner.transition_operation_id
    )
    if not role_trigger:
        model = connection.execute(
            """SELECT 1 FROM code_operations WHERE id=? AND task_id=? AND session_id=?
               AND control_generation=? AND (
                   (status='SUCCEEDED' AND operation_type IN ('START','RESUME','REPAIR'))
                   OR (status='RUNNING' AND operation_type='REPAIR' AND EXISTS(
                       SELECT 1 FROM code_operation_steps capture WHERE capture.operation_id=code_operations.id
                       AND capture.step_no=4 AND capture.status='RUNNING'
                       AND json_extract(capture.external_identity,'$.capture_operation_id')=?)))""",
            (
                saved['operation_id'],
                task['id'],
                session['id'],
                task['control_generation'],
                operation_id,
            ),
        ).fetchone()
        if model is None:
            from .task_session_replacement import read_session_replacement

            repaired = connection.execute(
                "SELECT * FROM code_operations WHERE id=? AND task_id=? AND operation_type='REPAIR' AND status IN ('RUNNING','SUCCEEDED')",
                (saved['operation_id'], task['id']),
            ).fetchone()
            if repaired is not None:
                replacement = read_session_replacement(connection, repaired)
                if (
                    replacement is not None
                    and replacement.target['id'] == session['id']
                    and replacement.target['control_generation'] == task['control_generation']
                ):
                    model = repaired
        if model is None and cancelled is None:
            raise StorageUnavailable('Original capture trigger operation differs')
    window = ModelWindow(
        task['id'],
        session['instance_id'],
        task['control_generation'],
        session['id'],
        session['native_session_id'],
        saved['operation_id'],
        saved['native_trigger_message_id'],
    )
    return session, owner, saved, window


def read_capture_quiescence(connection, operation_id):
    operation = connection.execute(
        """SELECT o.*,t.phase,t.status AS task_status,t.state_version,t.stop_requested_at,
                  t.control_generation AS task_generation,t.active_session_id,t.updated_at AS task_updated_at
           FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
           WHERE o.id=? AND o.resource_kind='TASK' AND o.resource_id=t.id
           AND o.operation_type='CAPTURE_AND_CHECK'""",
        (operation_id,),
    ).fetchone()
    if (
        operation is None
        or operation['status'] not in _ACTIVE
        or operation['stop_requested_at'] is not None
        or operation['control_generation'] != operation['task_generation']
        or type(operation['expected_state_version']) is not int
        or operation['session_id'] is None
        or operation['session_id'] != operation['active_session_id']
        or operation['state_version'] != operation['expected_state_version'] + 1
        or operation['phase'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
        or operation['task_status'] not in ('RUNNING', 'VERIFYING')
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_PHASE_FENCED')
    fixed = strict_json_object(operation['fixed_input'])
    if fixed != {
        'expected_state_version': operation['expected_state_version'],
        'purpose': 'HANDOFF',
    }:
        raise StorageUnavailable('Original capture input differs')
    steps = capture_steps(connection, operation_id)
    if (
        steps[0]['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN')
        or steps[0]['result_ref'] is not None
        or steps[0]['fixed_input'] != operation['fixed_input']
        or any(row['status'] != 'PENDING' for row in steps[1:])
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_QUIESCE_NOT_CURRENT')

    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    session, owner, saved, window = current_capture_owner(connection, task, operation_id)
    instance = connection.execute(
        """SELECT * FROM code_instances WHERE id=? AND task_id=? AND control_generation=?
           AND status='READY' AND stopped_at IS NULL""",
        (owner.instance_id, task['id'], owner.launch_generation),
    ).fetchone()
    if instance is None or not instance['runtime_binding'] or not instance['process_identity']:
        raise StorageUnavailable('Original capture runtime binding differs')
    binding = strict_json_object(instance['runtime_binding'])
    process = strict_json_object(instance['process_identity'])
    if (
        binding.get('run_kind') != 'TASK'
        or not binding.get('guard_run_ref')
        or not process.get('ownership_ref')
    ):
        raise StorageUnavailable('Original capture runtime binding differs')
    _time(saved['opened_at'], nullable=False)
    return CaptureQuiescence(
        operation_id,
        task['state_version'],
        owner,
        window,
        session['gateway_credential_ref'],
        session['model_window'],
        binding['guard_run_ref'],
        process['ownership_ref'],
        max(
            operation['created_at'],
            operation['task_updated_at'],
            saved['closed_at'] or saved['opened_at'],
        ),
    )


def record_capture_quiescence(connection, scope, evidence, *, at):
    require_write_transaction(connection)
    if type(scope) is not CaptureQuiescence:
        raise TaskExecutionError('ORIGINAL_CAPTURE_SCOPE_REQUIRED')
    _time(at, nullable=False)
    current = read_capture_quiescence(connection, scope.operation_id)
    if (
        current != scope
        or at < scope.observed_after
        or type(evidence) is not CaptureTurnEvidence
        or type(evidence.turn) is not NativeTurnCompletion
        or evidence.turn.session_id != scope.window.native_session_id
        or evidence.turn.trigger_message_id != scope.window.trigger_message_id
        or evidence.turn.outcome not in ('COMPLETED', 'CANCELLED')
        or type(evidence.active_process_count) is not int
        or evidence.active_process_count != 1
        or type(evidence.workspace) is not FileIdentity
        or not evidence.workspace.is_directory
        or evidence.workspace.filesystem != 'NTFS'
        or evidence.guard_receipt_sha256 != scope.guard_receipt_sha256
        or type(evidence.guard_receipt_sha256) is not str
        or len(evidence.guard_receipt_sha256) != 64
        or any(char not in '0123456789abcdef' for char in evidence.guard_receipt_sha256)
    ):
        raise TaskExecutionError('ORIGINAL_CAPTURE_QUIESCE_EVIDENCE_DIFFERS')
    window = strict_json_object(scope.model_window_json)
    if window['state'] == 'OPEN':
        window['state'], window['closed_at'] = 'CLOSED', at
    if (
        connection.execute(
            """UPDATE code_sessions SET model_window=?,last_observed_at=?
           WHERE id=? AND task_id=? AND control_generation=? AND model_window=? AND status='ACTIVE'""",
            (
                canonical_input(window),
                at,
                scope.window.execution_session_id,
                scope.window.task_id,
                scope.window.generation,
                scope.model_window_json,
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original capture model fence changed')
    identity = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    proof = canonical_input(evidence.scope_proof())
    ref = f'sqlite:code_operation_steps/{scope.operation_id}/1#sha256={hashlib.sha256(proof.encode()).hexdigest()}'
    connection.execute(
        """INSERT INTO code_runtime_observations(id,task_id,instance_id,operation_id,
           control_generation,runtime_binding_ref,kind,result,reason_codes,active_process_count,
           observed_at,evidence_ref) VALUES(?,?,?,?,?,?,'QUIESCE','VERIFIED','[]',1,?,?)""",
        (
            identity,
            scope.window.task_id,
            scope.window.instance_id,
            scope.operation_id,
            scope.window.generation,
            scope.runtime_binding_ref,
            at,
            ref,
        ),
    )
    if (
        connection.execute(
            """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,
           started_at=coalesce(started_at,?),ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=1 AND status IN ('PENDING','RUNNING','UNKNOWN')""",
            (
                canonical_input(
                    {'quiesce_observation_id': identity, 'proof': strict_json_object(proof)}
                ),
                at,
                at,
                at,
                scope.operation_id,
            ),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original capture QUIESCE step changed')
    connection.execute(
        """UPDATE code_operations SET status='RUNNING',started_at=coalesce(started_at,?),
           failure_code=NULL WHERE id=?""",
        (at, scope.operation_id),
    )
    connection.execute(
        'UPDATE code_tasks SET updated_at=?,last_observed_at=? WHERE id=?',
        (at, at, scope.window.task_id),
    )
    record_native_turn(connection, scope.window, evidence.turn, at)
    return identity


def observe_capture_quiescence(runtime, driver, operation_id, *, cancelled):
    def current_scope():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_CAPTURE_CANCELLED')
        with runtime.database.transaction() as connection:
            return read_capture_quiescence(connection, operation_id)

    original = current_scope()

    def checkpoint():
        if current_scope() != original:
            raise TaskExecutionError('ORIGINAL_CAPTURE_PHASE_FENCED')

    evidence = driver.observe_capture_turn(
        original.native_owner, original.window, original.credential_ref, checkpoint
    )
    checkpoint()
    with runtime.database.transaction(write=True) as connection:
        at = max(operation_time(None), original.observed_after)
        return record_capture_quiescence(connection, original, evidence, at=at)
