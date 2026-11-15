"""Create one same-role session inside the original repair recovery step."""

from hashlib import sha256
from uuid import uuid4

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import (
    EntityKind,
    entity_id,
    increment,
    require_write_transaction,
)
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_integer, strict_json_object

from .task_model_ingress import ModelWindow
from .task_resume_runtime import Continuation, _intent, _model_capacity_available, _step, _window
from .task_session_replacement import read_session_replacement
from .task_start_session import fixed_execution_context, successor_session_scope


def reserve_repair_session(connection, current, session, evidence, restored, archived_at, at):
    require_write_transaction(connection)
    task, operation, _, fixed, steps = current
    strict_integer(archived_at, 'archived_at')
    if steps[0]['external_identity'] is not None or steps[1]['external_identity'] is not None:
        raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_ALREADY_FIXED')
    instance = connection.execute(
        "SELECT runtime_binding,process_identity FROM code_instances WHERE id=? AND task_id=? AND status='READY' AND stopped_at IS NULL",
        (session['instance_id'], task['id']),
    ).fetchone()
    if instance is None:
        raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_HOST_UNAVAILABLE')
    proof = evidence.scope_proof()
    binding = strict_json_object(instance['runtime_binding'])
    receipt = strict_json_object(instance['process_identity']).get('ownership_ref')
    if proof['guard_receipt_sha256'] != receipt:
        raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_GUARD_DIFFERS')
    target = entity_id(connection, EntityKind.EXECUTION_SESSION)
    observation = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    generation = increment(task['control_generation'])
    original_window = strict_json_object(session['model_window'])
    intent = {
        'source_session_id': session['id'],
        'target_session_id': target,
        'instance_id': session['instance_id'],
        'source_generation': task['control_generation'],
        'target_generation': generation,
        'role': session['role'],
        'candidate_id': fixed['candidate_id'],
        'nonce': uuid4().hex,
        'archived_at': archived_at,
        'source_window': original_window,
        'quiet': {'quiesce_observation_id': observation, 'proof': proof},
        'source_evidence': restored,
    }
    digest = sha256(canonical_input(proof).encode()).hexdigest()
    connection.execute(
        """INSERT INTO code_runtime_observations(id,task_id,instance_id,operation_id,control_generation,
           runtime_binding_ref,kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
           VALUES(?,?,?,?,?,?,'QUIESCE','VERIFIED','[]',1,?,?)""",
        (
            observation,
            task['id'],
            session['instance_id'],
            operation['id'],
            task['control_generation'],
            binding['guard_run_ref'],
            at,
            f'sqlite:code_operation_steps/{operation["id"]}/1#sha256={digest}',
        ),
    )
    connection.execute(
        """INSERT INTO code_sessions(id,task_id,instance_id,role,control_generation,status,created_at)
           VALUES(?,?,?,?,?,'PREPARING',?)""",
        (target, task['id'], session['instance_id'], session['role'], generation, at),
    )
    retired = {**original_window, 'state': 'RETIRED'}
    source = connection.execute(
        "UPDATE code_sessions SET status='RETIRED',model_window=?,last_observed_at=? WHERE id=? AND status='ACTIVE' AND model_window=?",
        (canonical_input(retired), at, session['id'], session['model_window']),
    )
    changed = connection.execute(
        """UPDATE code_tasks SET active_session_id=?,control_generation=?,state_version=state_version+1,
           updated_at=?,last_observed_at=? WHERE id=? AND active_session_id=? AND control_generation=?
           AND state_version=? AND status='WAITING' AND stop_requested_at IS NULL""",
        (
            target,
            generation,
            at,
            at,
            task['id'],
            session['id'],
            task['control_generation'],
            task['state_version'],
        ),
    )
    if source.rowcount != 1 or changed.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_FENCED')
    _step(connection, operation['id'], 1, 'RUNNING', at, intent={'replacement': intent})
    connection.execute(
        "UPDATE code_operations SET status='RUNNING',started_at=coalesce(started_at,?) WHERE id=?",
        (at, operation['id']),
    )
    connection.execute(
        "UPDATE code_repairs SET status='RUNNING' WHERE operation_id=? AND task_id=?",
        (operation['id'], task['id']),
    )
    read_session_replacement(connection, operation, ready=False)


def replacement_continuation(connection, task, operation, *, ready=True):
    replacement = read_session_replacement(connection, operation, ready=ready)
    if replacement is None:
        raise StorageUnavailable('Original repair replacement missing')
    session = replacement.target
    scope = successor_session_scope(connection, task, replacement)
    original = replacement.intent['source_window']
    previous = ModelWindow(
        task['id'],
        replacement.source['instance_id'],
        replacement.source['control_generation'],
        replacement.source['id'],
        replacement.source['native_session_id'],
        original['operation_id'],
        original['native_trigger_message_id'],
    )
    return session, Continuation(
        scope, previous, session['gateway_credential_ref'], session['native_session_id']
    )


def advance_repair_session(
    runtime, driver, current, admissions, checkpoint, current_reader, prepare_source
):
    """Repeat only original reads once the private create intent may exist."""
    database = runtime.database
    task, operation, _, _, _ = current
    with database.transaction() as connection:
        replacement = read_session_replacement(connection, operation, ready=False)
        scope = successor_session_scope(connection, task, replacement)
    checkpoint()
    if replacement.target['native_session_id'] is None:
        native = driver.create_session(scope, checkpoint)
        checkpoint()
        with database.transaction(write=True) as connection:
            if current_reader(connection, operation['id']) != current:
                raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_FENCED')
            observed = _identifier(native.native_id, 'ses')
            if observed == replacement.source['native_session_id']:
                raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_NATIVE_DIFFERS')
            connection.execute(
                'UPDATE code_sessions SET native_session_id=?,last_observed_at=? WHERE id=? AND native_session_id IS NULL',
                (observed, max(operation_time(None), task['updated_at']), replacement.target['id']),
            )
        return None
    with database.transaction() as connection:
        grant = connection.execute(
            "SELECT * FROM code_authorizations WHERE id=? AND task_id=? AND status='EFFECTIVE'",
            (task['authorization_id'], task['id']),
        ).fetchone()
        if grant is None:
            raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_GRANT_MISSING')
        context = fixed_execution_context(
            connection, task, replacement.target['native_session_id'], grant
        )
        from .task_repairs import _defects

        candidate = connection.execute(
            'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
            (replacement.intent['candidate_id'], task['id']),
        ).fetchone()
        defects = _defects(
            connection, task, candidate, strict_json_object(operation['fixed_input'])['defect_ids']
        )
        if defects is None:
            raise StorageUnavailable('Original repair replacement defects missing')
    payload = driver.replacement_repair_payload(
        scope, context, replacement.intent['source_evidence'], defects, checkpoint
    )
    credential = driver.gateway_reference(scope)
    if not credential:
        raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_GATEWAY_MISSING')
    session = replacement.target
    previous = replacement.intent['source_window']
    window = ModelWindow(
        task['id'],
        session['instance_id'],
        session['control_generation'],
        session['id'],
        session['native_session_id'],
        operation['id'],
        payload['messageID'],
    )
    source_window = ModelWindow(
        task['id'],
        replacement.source['instance_id'],
        replacement.source['control_generation'],
        replacement.source['id'],
        replacement.source['native_session_id'],
        previous['operation_id'],
        previous['native_trigger_message_id'],
    )
    continuation = Continuation(scope, source_window, credential, session['native_session_id'])

    def queue_original(verify_locked_source):
        verify_locked_source()
        with database.transaction(write=True) as connection:
            if current_reader(connection, operation['id']) != current:
                raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_FENCED')
            at = max(operation_time(None), task['updated_at'])
            if not _model_capacity_available(connection, runtime.catalog, admissions, window, at):
                raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_CAPACITY_UNAVAILABLE')
            result = {
                **replacement.intent['source_evidence'],
                'replacement_session_id': session['id'],
                'native_session_id': session['native_session_id'],
            }
            _step(connection, operation['id'], 1, 'SUCCEEDED', at, result=result)
            connection.execute(
                "UPDATE code_sessions SET status='ACTIVE',gateway_credential_ref=?,native_message_id=?,last_observed_at=? WHERE id=? AND status='PREPARING'",
                (credential, payload['messageID'], at, session['id']),
            )
            _step(
                connection, operation['id'], 2, 'RUNNING', at, intent=_intent(continuation, payload)
            )
            _window(connection, window, 'QUEUED', at)

    prepare_source(scope, replacement, queue_original)
    original = {
        'session_id': session['id'],
        'native_session_id': session['native_session_id'],
        'native_message_id': payload['messageID'],
        'gateway_credential_ref': credential,
        'payload_sha256': sha256(_bytes(payload)).hexdigest(),
    }
    return scope, source_window, original, payload
