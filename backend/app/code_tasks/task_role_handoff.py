"""Advance the original automatic Coding handoff on the backend owner thread."""

from dataclasses import dataclass
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
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_loads, strict_json_object

from .authorizations import project_grant
from .task_basis import read_task_basis
from .task_candidate_reads import _available, _saved
from .task_capture_quiescence import current_capture_owner
from .task_instance_driver import CaptureTurnEvidence
from .task_model_ingress import ModelWindow
from .task_records import record_native_turn
from .task_role_chain import (
    HANDOFF,
    ROLES,
    STEPS,
    RoleChainUnavailable,
    _check_saved_verification,
    _fixed,
    current_role_chain,
)
from .task_start_session import InitialContext, _window, handoff_session_scope
from .task_verification_reads import _saved as saved_verification

_EXECUTABLE = ('PENDING', 'RUNNING')


@dataclass(frozen=True)
class RoleHandoff:
    operation: dict
    task: dict
    source: dict
    steps: tuple[dict, ...]
    fixed: dict
    previous_window: ModelWindow

    @property
    def id(self):
        return self.operation['id']

    @property
    def generation(self):
        return self.operation['control_generation']

    @property
    def step(self):
        return next(row for row in self.steps if row['status'] != 'SUCCEEDED')


def _role_operations(connection, task_id):
    return connection.execute(
        """SELECT id FROM code_operations WHERE task_id=? AND operation_type=?
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
        (task_id, HANDOFF),
    ).fetchall()


def _read(connection, operation_id, *, allow_unknown=False):
    operation = connection.execute(
        "SELECT * FROM code_operations WHERE id=? AND resource_kind='TASK' AND operation_type=?",
        (operation_id, HANDOFF),
    ).fetchone()
    allowed = (*_EXECUTABLE, 'UNKNOWN') if allow_unknown else _EXECUTABLE
    if operation is None or operation['status'] not in allowed:
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')
    fixed = _fixed(operation)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    source = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (operation['session_id'], operation['task_id']),
    ).fetchone()
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no', (operation_id,)
    ).fetchall()
    if (
        task is None
        or source is None
        or tuple((row['step_no'], row['step_type']) for row in steps) != tuple(enumerate(STEPS, 1))
        or any(row['fixed_input'] != operation['fixed_input'] for row in steps)
        or operation['resource_id'] != task['id']
        or source['role'] not in ROLES[:2]
        or fixed['target_role'] != ROLES[ROLES.index(source['role']) + 1]
        or source['control_generation'] != operation['control_generation']
    ):
        raise StorageUnavailable('Original role handoff record differs')
    revoked = steps[1]['status'] == 'SUCCEEDED'
    if (
        task['status'] != ('WAITING' if operation['status'] == 'UNKNOWN' else 'VERIFYING')
        or task['phase'] != source['role']
        or task['state_version'] <= fixed['expected_state_version']
        or task['stop_requested_at'] is not None
        or task['control_generation'] != operation['control_generation'] + int(revoked)
        or task['active_session_id'] != (None if revoked else source['id'])
        or task['current_candidate_id'] != fixed['candidate_id']
        or task['current_verification_id'] != fixed['verification_id']
        or source['status'] != ('RETIRED' if revoked else 'ACTIVE')
    ):
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')
    if [row['id'] for row in _role_operations(connection, task['id'])] != [operation_id]:
        raise StorageUnavailable('Original role handoff is not the unique transition')
    model = strict_json_object(source['model_window'])
    if model['state'] != ('RETIRED' if revoked else 'CLOSED'):
        raise TaskExecutionError('ORIGINAL_ROLE_SOURCE_MODEL_WINDOW_UNVERIFIED')
    window = ModelWindow(
        task['id'],
        source['instance_id'],
        source['control_generation'],
        source['id'],
        source['native_session_id'],
        model['operation_id'],
        model['native_trigger_message_id'],
    )
    return RoleHandoff(
        dict(operation), dict(task), dict(source), tuple(map(dict, steps)), fixed, window
    )


def _original_source(connection, scope):
    session, owner, saved, window = current_capture_owner(connection, scope.task, scope.id)
    if (
        window != scope.previous_window
        or saved['state'] != 'CLOSED'
        or session['id'] != scope.source['id']
    ):
        raise TaskExecutionError('ORIGINAL_ROLE_SOURCE_NOT_QUIESCENT')
    instance = connection.execute(
        "SELECT runtime_binding,process_identity FROM code_instances WHERE id=? AND task_id=? AND status='READY' AND stopped_at IS NULL",
        (owner.instance_id, scope.task['id']),
    ).fetchone()
    if instance is None:
        raise TaskExecutionError('ORIGINAL_ROLE_HOST_NOT_READY')
    return (
        owner,
        strict_json_object(instance['runtime_binding'])['guard_run_ref'],
        strict_json_object(instance['process_identity'])['ownership_ref'],
    )


def _accept(connection, runtime, driver, admissions, observed):
    require_write_transaction(connection)
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (observed['id'],)).fetchone()
    if task is None or dict(task) != observed or _role_operations(connection, task['id']):
        return False
    try:
        chain = current_role_chain(connection, task)
        session, owner, model, _ = current_capture_owner(connection, task)
    except (RoleChainUnavailable, TaskExecutionError):
        return False
    if (
        chain.role == 'INTEGRATION'
        or model['state'] != 'CLOSED'
        or not driver.session_available(owner.operation_id)
    ):
        return False
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (task['current_candidate_id'], task['id']),
    ).fetchone()
    verification = connection.execute(
        "SELECT * FROM code_verifications WHERE id=? AND task_id=? AND owner_kind='CODING'",
        (task['current_verification_id'], task['id']),
    ).fetchone()
    if (
        candidate is None
        or verification is None
        or candidate['control_generation'] != task['control_generation']
        or candidate['role'] != chain.role
        or not saved_verification(connection, runtime.catalog, admissions, task, verification)[
            'eligible'
        ]
    ):
        return False
    # A failed or uncertain original transition is never silently replaced.
    if (
        connection.execute(
            """SELECT 1 FROM code_operations WHERE task_id=? AND operation_type=?
           AND json_extract(fixed_input,'$.source_session_id')=?
           AND json_extract(fixed_input,'$.verification_id')=? LIMIT 1""",
            (task['id'], HANDOFF, session['id'], verification['id']),
        ).fetchone()
        is not None
    ):
        return False
    operation = entity_id(connection, EntityKind.OPERATION_RECORD)
    at = max(operation_time(None), task['updated_at'])
    fixed = canonical_input(
        {
            'source_session_id': session['id'],
            'candidate_id': candidate['id'],
            'verification_id': verification['id'],
            'target_role': ROLES[len(chain.stages)],
            'expected_state_version': task['state_version'],
        }
    )
    changed = connection.execute(
        """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
           AND stop_requested_at IS NULL AND status='VERIFYING' AND active_session_id=?""",
        (increment(task['state_version']), at, task['id'], task['state_version'], session['id']),
    )
    if changed.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')
    connection.execute(
        """INSERT INTO code_operations(id,task_id,resource_kind,resource_id,session_id,
           operation_type,idempotency_key,expected_state_version,fixed_input,control_generation,status,created_at)
           VALUES(?,?,'TASK',?,?,?,?,?,?,?,'PENDING',?)""",
        (
            operation,
            task['id'],
            task['id'],
            session['id'],
            HANDOFF,
            str(uuid4()),
            task['state_version'],
            fixed,
            task['control_generation'],
            at,
        ),
    )
    connection.executemany(
        """INSERT INTO code_operation_steps(operation_id,step_no,step_type,status,fixed_input)
           VALUES(?,?,?,'PENDING',?)""",
        [(operation, number, kind, fixed) for number, kind in enumerate(STEPS, 1)],
    )
    return True


def _at(scope):
    observed = [
        row['last_observed_at'] for row in scope.steps if row['last_observed_at'] is not None
    ]
    return max(
        operation_time(None), scope.task['updated_at'], scope.operation['created_at'], *observed
    )


def _complete(connection, scope, result, at, *, reconcile=False):
    step = scope.step
    changed = connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',started_at=COALESCE(started_at,?),
           ended_at=?,last_observed_at=?,result_ref=? WHERE operation_id=? AND step_no=?
           AND (status IN ('PENDING','RUNNING') OR (? AND status='UNKNOWN'))""",
        (at, at, at, canonical_input(result), scope.id, step['step_no'], int(reconcile)),
    )
    if changed.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')
    connection.execute(
        "UPDATE code_operations SET status='RUNNING',failure_code=NULL,started_at=COALESCE(started_at,?) WHERE id=?",
        (at, scope.id),
    )


def _same(connection, scope):
    current = _read(connection, scope.id, allow_unknown=scope.operation['status'] == 'UNKNOWN')
    task_fields = (
        'id',
        'status',
        'phase',
        'control_generation',
        'workspace_id',
        'active_session_id',
        'current_candidate_id',
        'current_verification_id',
        'stop_requested_at',
        'execution_profile_version_id',
        'authorization_id',
        'design_revision_id',
    )
    if (
        current.operation != scope.operation
        or current.source != scope.source
        or current.steps != scope.steps
        or any(current.task[field] != scope.task[field] for field in task_fields)
    ):
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')
    return current


def _record_quiet(connection, scope, binding, receipt, evidence):
    scope = _same(connection, scope)
    window = scope.previous_window
    if (
        type(evidence) is not CaptureTurnEvidence
        or evidence.turn.session_id != window.native_session_id
        or evidence.turn.trigger_message_id != window.trigger_message_id
        or evidence.turn.outcome not in ('COMPLETED', 'CANCELLED')
        or evidence.guard_receipt_sha256 != receipt
        or evidence.active_process_count != 1
        or not evidence.workspace.is_directory
        or evidence.workspace.filesystem != 'NTFS'
    ):
        raise TaskExecutionError('ORIGINAL_ROLE_QUIESCENCE_UNVERIFIED')
    at = _at(scope)
    observation = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    proof = evidence.scope_proof()
    digest = sha256(canonical_input(proof).encode('utf-8')).hexdigest()
    connection.execute(
        """INSERT INTO code_runtime_observations(id,task_id,instance_id,operation_id,control_generation,
           runtime_binding_ref,kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
           VALUES(?,?,?,?,?,?,'QUIESCE','VERIFIED','[]',1,?,?)""",
        (
            observation,
            window.task_id,
            window.instance_id,
            scope.id,
            window.generation,
            binding,
            at,
            f'sqlite:code_operation_steps/{scope.id}/1#sha256={digest}',
        ),
    )
    _complete(connection, scope, {'quiesce_observation_id': observation, 'proof': proof}, at)
    record_native_turn(connection, window, evidence.turn, at)


def _record_revocation(connection, scope):
    scope = _same(connection, scope)
    at = _at(scope)
    generation = increment(scope.generation)
    window = strict_json_object(scope.source['model_window'])
    window['state'] = 'RETIRED'
    changed = connection.execute(
        """UPDATE code_sessions SET status='RETIRED',model_window=?,last_observed_at=?
           WHERE id=? AND status='ACTIVE' AND model_window=?""",
        (canonical_input(window), at, scope.source['id'], scope.source['model_window']),
    )
    task = connection.execute(
        """UPDATE code_tasks SET active_session_id=NULL,control_generation=?,state_version=?,
           updated_at=?,last_observed_at=? WHERE id=? AND active_session_id=? AND state_version=?
           AND control_generation=? AND stop_requested_at IS NULL""",
        (
            generation,
            increment(scope.task['state_version']),
            at,
            at,
            scope.task['id'],
            scope.source['id'],
            scope.task['state_version'],
            scope.generation,
        ),
    )
    if changed.rowcount != 1 or task.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')
    _complete(
        connection, scope, {'session_id': scope.source['id'], 'control_generation': generation}, at
    )


def _check_prior(connection, scope):
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (scope.fixed['candidate_id'], scope.task['id']),
    ).fetchone()
    if candidate is None:
        raise StorageUnavailable('Original role candidate is missing')
    previous = tuple(
        row[0]
        for row in connection.execute(
            """SELECT id FROM code_operations WHERE task_id=? AND operation_type=?
               AND status='SUCCEEDED' ORDER BY id""",
            (scope.task['id'], HANDOFF),
        )
    )
    stages = ROLES[: ROLES.index(scope.source['role']) + 1]
    if len(previous) != len(stages) - 1:
        raise TaskExecutionError('ORIGINAL_ROLE_CHAIN_DIFFERS')
    _check_saved_verification(
        connection, scope.operation, candidate, scope.fixed['verification_id'], stages, previous
    )
    _complete(connection, scope, {'verification_id': scope.fixed['verification_id']}, _at(scope))


def _start_step(connection, scope, identity, at):
    step = scope.step
    changed = connection.execute(
        """UPDATE code_operation_steps SET status='RUNNING',started_at=?,last_observed_at=?,external_identity=?
           WHERE operation_id=? AND step_no=? AND status='PENDING' AND external_identity IS NULL""",
        (at, at, canonical_input(identity), scope.id, step['step_no']),
    )
    if changed.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')


def _new_session(connection, scope):
    at = _at(scope)
    identity = {
        'session_id': entity_id(connection, EntityKind.EXECUTION_SESSION),
        'instance_id': scope.source['instance_id'],
        'control_generation': scope.task['control_generation'],
        'nonce': uuid4().hex,
    }
    connection.execute(
        """INSERT INTO code_sessions(id,task_id,instance_id,role,control_generation,status,created_at)
           VALUES(?,?,?,?,?,'PREPARING',?)""",
        (
            identity['session_id'],
            scope.task['id'],
            identity['instance_id'],
            scope.fixed['target_role'],
            identity['control_generation'],
            at,
        ),
    )
    _start_step(connection, scope, identity, at)


def _target(connection, scope):
    original = strict_json_object(scope.steps[3]['external_identity'])
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (original['session_id'], scope.task['id']),
    ).fetchone()
    if (
        session is None
        or session['status'] != 'PREPARING'
        or session['role'] != scope.fixed['target_role']
        or session['instance_id'] != scope.source['instance_id']
        or original['instance_id'] != session['instance_id']
        or original['control_generation'] != session['control_generation']
    ):
        raise TaskExecutionError('ORIGINAL_ROLE_TARGET_SESSION_DIFFERS')
    return session, handoff_session_scope(
        connection, scope.task, session, scope.id, original['nonce']
    )


def _record_session(connection, scope, native, *, reconcile=False):
    scope = _same(connection, scope)
    session, _ = _target(connection, scope)
    if session['native_session_id'] is not None or native == scope.source['native_session_id']:
        raise TaskExecutionError('ORIGINAL_ROLE_TARGET_SESSION_DIFFERS')
    at = _at(scope)
    connection.execute(
        'UPDATE code_sessions SET native_session_id=?,last_observed_at=? WHERE id=?',
        (_identifier(native, 'ses'), at, session['id']),
    )
    _complete(
        connection,
        scope,
        {'session_id': session['id'], 'native_session_id': native},
        at,
        reconcile=reconcile,
    )


def _delivery_context(connection, scope, session):
    materials, _ = read_task_basis(connection, scope.task)
    documents = (
        (scope.task['document_id'], scope.task['design_revision_id']),
        *((item['document_id'], item['revision_id']) for item in materials),
    )
    profile = connection.execute(
        'SELECT check_set_version_id FROM code_execution_profile_versions WHERE id=?',
        (scope.task['execution_profile_version_id'],),
    ).fetchone()
    grant = connection.execute(
        "SELECT * FROM code_authorizations WHERE id=? AND task_id=? AND status='EFFECTIVE'",
        (scope.task['authorization_id'], scope.task['id']),
    ).fetchone()
    verification = connection.execute(
        'SELECT selected_check_ids,scope_stages FROM code_verifications WHERE id=? AND task_id=?',
        (scope.fixed['verification_id'], scope.task['id']),
    ).fetchone()
    if profile is None or grant is None or verification is None:
        raise TaskExecutionError('ORIGINAL_ROLE_DELIVERY_CONTEXT_UNAVAILABLE')
    return (
        InitialContext(
            session['native_session_id'],
            documents,
            profile['check_set_version_id'],
            project_grant(grant)['scope'],
        ),
        {
            'source_role': scope.source['role'],
            'candidate_id': scope.fixed['candidate_id'],
            'verification_id': scope.fixed['verification_id'],
            'scope_stages': strict_json_loads(verification['scope_stages']),
            'selected_check_ids': strict_json_loads(verification['selected_check_ids']),
            'uncovered': '后续角色及独立 Testing 的实际结果尚未形成。按固定设计核对剩余范围。',
        },
    )


def _queue_delivery(connection, scope, native, payload, credential):
    scope = _same(connection, scope)
    session, _ = _target(connection, scope)
    if (
        not credential
        or session['native_session_id'] != native
        or session['model_window'] is not None
    ):
        raise TaskExecutionError('ORIGINAL_ROLE_DELIVERY_DIFFERS')
    at = _at(scope)
    original = {
        'session_id': session['id'],
        'native_session_id': native,
        'native_message_id': _identifier(payload['messageID'], 'msg'),
        'gateway_credential_ref': credential,
        'payload_sha256': sha256(_bytes(payload)).hexdigest(),
    }
    connection.execute(
        """UPDATE code_sessions SET native_message_id=?,gateway_credential_ref=?,model_window=?,last_observed_at=?
           WHERE id=? AND status='PREPARING'""",
        (
            original['native_message_id'],
            credential,
            _window(scope.id, original['native_message_id'], 'QUEUED'),
            at,
            session['id'],
        ),
    )
    _start_step(connection, scope, original, at)


def _finish_delivery(connection, scope, message, *, reconcile=False):
    scope = _same(connection, scope)
    session, _ = _target(connection, scope)
    original = strict_json_object(scope.step['external_identity'])
    if message != original['native_message_id'] or message != session['native_message_id']:
        raise TaskExecutionError('ORIGINAL_ROLE_MESSAGE_UNCONFIRMED')
    at = _at(scope)
    if reconcile:
        waits = connection.execute(
            """SELECT * FROM code_waiting_items WHERE task_id=? AND status='OPEN'""",
            (scope.task['id'],),
        ).fetchall()
        if (
            len(waits) != 1
            or waits[0]['kind'] != 'OPERATION_RESULT'
            or waits[0]['source_kind'] != 'OPERATION'
            or waits[0]['source_id'] != scope.id
        ):
            raise TaskExecutionError('ORIGINAL_ROLE_WAIT_SCOPE_DIFFERS')
        connection.execute(
            "UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=? WHERE id=?",
            (
                at,
                canonical_input({'operation_id': scope.id, 'outcome': 'NATIVE_MESSAGE_OBSERVED'}),
                waits[0]['id'],
            ),
        )
    connection.execute(
        """UPDATE code_sessions SET status='ACTIVE',model_window=?,last_observed_at=? WHERE id=? AND status='PREPARING'""",
        (_window(scope.id, message, 'OPEN', opened=at), at, session['id']),
    )
    _complete(
        connection,
        scope,
        {'session_id': session['id'], 'native_message_id': message},
        at,
        reconcile=reconcile,
    )
    changed = connection.execute(
        """UPDATE code_tasks SET active_session_id=?,state_version=?,phase=?,status='RUNNING',resume_phase=NULL,
           updated_at=?,last_observed_at=? WHERE id=? AND active_session_id IS NULL AND state_version=?
           AND control_generation=? AND status=? AND stop_requested_at IS NULL""",
        (
            session['id'],
            increment(scope.task['state_version']),
            session['role'],
            at,
            at,
            scope.task['id'],
            scope.task['state_version'],
            scope.task['control_generation'],
            'WAITING' if reconcile else 'VERIFYING',
        ),
    )
    if changed.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_ROLE_OPERATION_FENCED')
    connection.execute(
        "UPDATE code_operations SET status='SUCCEEDED',failure_code=NULL,ended_at=? WHERE id=?",
        (at, scope.id),
    )
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (scope.task['id'],)).fetchone()
    if current_role_chain(connection, task).session_id != session['id']:
        raise TaskExecutionError('ORIGINAL_ROLE_CHAIN_DIFFERS')


def _unknown(connection, scope):
    current = _read(connection, scope.id)
    if current.step['step_no'] != scope.step['step_no']:
        return
    at = _at(current)
    connection.execute(
        """UPDATE code_operation_steps SET status='UNKNOWN',started_at=COALESCE(started_at,?),last_observed_at=?
           WHERE operation_id=? AND step_no=? AND status IN ('PENDING','RUNNING')""",
        (at, at, scope.id, current.step['step_no']),
    )
    connection.execute(
        """UPDATE code_operations SET status='UNKNOWN',started_at=COALESCE(started_at,?),
           failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?""",
        (at, scope.id),
    )
    connection.execute(
        """INSERT INTO code_waiting_items(id,task_id,kind,source_kind,source_id,resume_phase,status,created_at)
           VALUES(?,?,'OPERATION_RESULT','OPERATION',?,?,'OPEN',?)""",
        (
            entity_id(connection, EntityKind.WAITING_ITEM),
            scope.task['id'],
            scope.id,
            scope.source['role'],
            at,
        ),
    )
    connection.execute(
        """UPDATE code_tasks SET status='WAITING',resume_phase=?,state_version=?,updated_at=?,last_observed_at=?
           WHERE id=? AND state_version=? AND stop_requested_at IS NULL""",
        (
            scope.source['role'],
            increment(current.task['state_version']),
            at,
            at,
            current.task['id'],
            current.task['state_version'],
        ),
    )


def _advance(runtime, driver, scope, cancelled):
    step = scope.step['step_no']

    def checkpoint():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_ROLE_WORKER_STOPPED')
        with runtime.database.transaction() as connection:
            _same(connection, scope)

    checkpoint()
    if step in (1, 2):
        with runtime.database.transaction() as connection:
            owner, binding, receipt = _original_source(connection, scope)
        if step == 1:
            evidence = driver.observe_capture_turn(
                owner,
                scope.previous_window,
                scope.source['gateway_credential_ref'],
                checkpoint,
            )
            with runtime.database.transaction(write=True) as connection:
                _record_quiet(connection, scope, binding, receipt, evidence)
        else:
            driver.revoke_session_source(
                owner,
                scope.previous_window,
                scope.source['gateway_credential_ref'],
                checkpoint,
            )
            with runtime.database.transaction(write=True) as connection:
                _record_revocation(connection, scope)
        return
    if step == 3:
        with runtime.database.transaction(write=True) as connection:
            _check_prior(connection, _same(connection, scope))
        return
    if step == 4 and scope.step['status'] == 'PENDING':
        with runtime.database.transaction(write=True) as connection:
            _new_session(connection, _same(connection, scope))
        return
    with runtime.database.transaction() as connection:
        target, owner = _target(connection, _same(connection, scope))
        delivery = None if step == 4 else _delivery_context(connection, scope, target)
    if step == 4:
        observed = driver.create_session(owner, checkpoint)
        with runtime.database.transaction(write=True) as connection:
            _record_session(connection, scope, observed.native_id)
        return
    context, handoff = delivery
    payload = driver.role_payload(owner, context, handoff, checkpoint)
    if scope.step['status'] == 'PENDING':
        credential = driver.gateway_reference(owner)
        with runtime.database.transaction(write=True) as connection:
            _queue_delivery(connection, scope, target['native_session_id'], payload, credential)
        return
    original = strict_json_object(scope.step['external_identity'])
    message = driver.send_successor(owner, scope.previous_window, original, payload, checkpoint)
    with runtime.database.transaction(write=True) as connection:
        _finish_delivery(connection, scope, message)


def advance_role_handoff(runtime, driver, admissions, *, cancelled):
    if cancelled():
        return False
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction() as connection:
        active = connection.execute(
            """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
               WHERE o.operation_type=? AND o.status IN ('PENDING','RUNNING')
               AND t.status='VERIFYING' AND t.stop_requested_at IS NULL ORDER BY o.id LIMIT 1""",
            (HANDOFF,),
        ).fetchone()
        scope = None if active is None else _read(connection, active['id'])
    if scope is not None:
        try:
            _advance(runtime, driver, scope, cancelled)
        except (
            TaskExecutionError,
            LaunchOutcomeUnknown,
            OSError,
            RoleChainUnavailable,
            ValueError,
        ):
            if cancelled():
                return False
            try:
                with runtime.database.transaction(write=True) as connection:
                    _unknown(connection, scope)
            except TaskExecutionError:
                # A concurrently accepted TERMINATE owns the original native activity.
                return False
        return True

    if not admissions:
        return False
    with runtime.database.transaction() as connection:
        tasks = connection.execute(
            """SELECT t.* FROM code_tasks t JOIN code_verifications v ON v.id=t.current_verification_id
               AND v.task_id=t.id AND v.candidate_id=t.current_candidate_id
               WHERE t.status='VERIFYING' AND t.phase IN ('BACKEND','FRONTEND')
               AND t.stop_requested_at IS NULL AND v.status='FINISHED'
               AND NOT EXISTS (SELECT 1 FROM code_operations o WHERE o.task_id=t.id AND
                 o.operation_type=? AND (o.status IN ('PENDING','RUNNING','UNKNOWN')
                 OR (o.session_id=t.active_session_id AND json_extract(o.fixed_input,'$.verification_id')=v.id)))
               ORDER BY t.id""",
            (HANDOFF,),
        ).fetchall()
        candidates = []
        for task in tasks:
            row = connection.execute(
                'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
                (task['current_candidate_id'], task['id']),
            ).fetchone()
            if row is not None:
                _, original = _saved(connection, row)
                candidates.append((dict(task), original))
    for task, original in candidates:
        if cancelled():
            return False
        if not _available(original):
            continue
        with runtime.database.transaction(write=True) as connection:
            if _accept(connection, runtime, driver, admissions, task):
                return True
    return False


def original_role_result_for_reconciliation(connection, operation_id):
    scope = _read(connection, operation_id, allow_unknown=True)
    if (
        scope.operation['status'] != 'UNKNOWN'
        or scope.step['step_type'] not in ('CREATE_SESSION', 'SEND_HANDOFF')
        or scope.step['status'] != 'UNKNOWN'
        or scope.step['external_identity'] is None
    ):
        raise TaskExecutionError('ORIGINAL_ROLE_RESULT_RECONCILIATION_UNAVAILABLE')
    _, owner = _target(connection, scope)
    return scope, owner, strict_json_object(scope.step['external_identity'])


def record_reconciled_role_creation(connection, scope, native):
    """Complete only the original creation and reopen the same handoff workflow."""
    _record_session(connection, scope, native, reconcile=True)
    at = _at(scope)
    changed = connection.execute(
        """UPDATE code_tasks SET status='VERIFYING',resume_phase=NULL,state_version=state_version+1,
           updated_at=?,last_observed_at=? WHERE id=? AND status='WAITING' AND stop_requested_at IS NULL
           AND control_generation=? AND active_session_id IS NULL""",
        (at, at, scope.task['id'], scope.task['control_generation']),
    )
    if changed.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_ROLE_RECONCILIATION_FENCED')
    waiting = connection.execute(
        """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
           WHERE task_id=? AND kind='OPERATION_RESULT' AND source_kind='OPERATION'
           AND source_id=? AND status='OPEN'""",
        (
            at,
            canonical_input({'operation_id': scope.id, 'outcome': 'NATIVE_SESSION_OBSERVED'}),
            scope.task['id'],
            scope.id,
        ),
    )
    if waiting.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_ROLE_WAIT_SCOPE_DIFFERS')
