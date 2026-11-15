"""Advance CREATE_SESSION and SEND_INITIAL on the original Coding START."""

import hashlib
from dataclasses import asdict, dataclass

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown, _bytes
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .authorizations import project_grant
from .task_basis import TaskBasisUnavailable, read_task_basis
from .task_budget import start_budget_versions
from .task_initial_configuration import InitialNativeSession, record_initial_configuration
from .task_records import record_confirmed_control
from .task_role_chain import RoleChainUnavailable, current_role_chain
from .task_start import original_start_steps
from .task_start_basis import _active, _original_basis

CREATE_SESSION = 5
SEND_INITIAL = 6


@dataclass(frozen=True)
class StartSessionScope:
    operation_id: int
    task_id: int
    instance_id: int
    session_id: int
    control_generation: int
    state_version: int
    profile_id: int
    authorization_id: int
    nonce: str
    workspace_id: int
    query_timeout_seconds: int
    send_timeout_seconds: int

    @property
    def launch_generation(self):
        return self.control_generation

    def metadata(self):
        return {
            'walle': {
                'task_id': self.task_id,
                'execution_session_id': self.session_id,
                'instance_id': self.instance_id,
                'operation_id': self.operation_id,
                'control_generation': self.control_generation,
                'nonce': self.nonce,
            }
        }


@dataclass(frozen=True)
class SuccessorSessionScope(StartSessionScope):
    role: str
    transition_operation_id: int
    transition_nonce: str
    original_launch_generation: int
    transition_kind: str = 'HANDOFF_ROLE'
    transition_step_no: int = 4

    def __post_init__(self):
        expected = {'HANDOFF_ROLE': 4, 'REPAIR': 1}
        if (
            self.transition_kind not in expected
            or self.transition_step_no != expected[self.transition_kind]
            or self.role not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
            or (self.transition_kind == 'HANDOFF_ROLE' and self.role == 'BACKEND')
            or type(self.original_launch_generation) is not int
            or not 1
            <= self.original_launch_generation
            < self.control_generation
            <= MAX_SAFE_INTEGER
            or type(self.transition_operation_id) is not int
            or not 1 <= self.transition_operation_id <= MAX_SAFE_INTEGER
            or self.transition_operation_id == self.operation_id
            or type(self.transition_nonce) is not str
            or len(self.transition_nonce) != 32
            or any(character not in '0123456789abcdef' for character in self.transition_nonce)
        ):
            raise StorageUnavailable('Original successor session scope differs')

    @property
    def launch_generation(self):
        return self.original_launch_generation

    def metadata(self):
        identity = super().metadata()
        identity['walle'].update(
            operation_id=self.transition_operation_id, nonce=self.transition_nonce
        )
        return identity


@dataclass(frozen=True)
class InitialContext:
    native_session_id: str
    documents: tuple[tuple[int, int], ...]
    check_set_version_id: int
    scope: dict


def _candidate(connection):
    return connection.execute(
        """SELECT o.id,s.step_no,s.status FROM code_operations o
           JOIN code_tasks t ON t.id=o.task_id
           JOIN code_operation_steps instance ON instance.operation_id=o.id AND instance.step_no=4
           JOIN code_operation_steps native ON native.operation_id=o.id AND native.step_no=5
           JOIN code_operation_steps s ON s.operation_id=o.id
             AND s.step_no=CASE WHEN native.status='SUCCEEDED' THEN 6 ELSE 5 END
           WHERE o.resource_kind='TASK' AND o.operation_type='START' AND o.status='RUNNING'
           AND instance.status='SUCCEEDED'
           AND (s.status='RUNNING' OR (s.status='PENDING' AND t.status='PENDING'
             AND t.phase='PREPARING' AND t.stop_requested_at IS NULL))
           ORDER BY (s.status='RUNNING') DESC,o.id LIMIT 1"""
    ).fetchone()


def _original(connection, parent, operation_id, number, status):
    original = _original_basis(connection, operation_id)
    try:
        _active(original, parent, step_status='SUCCEEDED')
    except TaskBasisUnavailable as error:
        raise TaskExecutionError('ORIGINAL_NATIVE_START_FENCED') from error
    operation, task, _, allocation = original
    _, steps = original_start_steps(connection, operation)
    instance_step = steps[3]
    if (
        instance_step['status'] != 'SUCCEEDED'
        or steps[number - 1]['status'] != status
        or not start_budget_versions(connection, task, operation, offset=2)
        or task['active_session_id'] is not None
        or task['started_at'] is not None
    ):
        raise TaskExecutionError('ORIGINAL_NATIVE_START_FENCED')
    identity = strict_json_object(instance_step['external_identity'])
    instance_id = identity['instance_id']
    instance = connection.execute(
        'SELECT * FROM code_instances WHERE id=?', (instance_id,)
    ).fetchone()
    if (
        identity['task_id'] != task['id']
        or identity['operation_id'] != operation_id
        or identity['control_generation'] != task['control_generation']
        or identity['state_version'] != operation['expected_state_version'] + 2
        or identity['effective_profile_version_id'] != task['execution_profile_version_id']
        or strict_json_object(instance_step['result_ref']) != {'instance_id': instance_id}
        or instance is None
        or instance['task_id'] != task['id']
        or instance['workspace_id'] != allocation.workspace_id
        or instance['control_generation'] != task['control_generation']
        or instance['effective_profile_version_id'] != task['execution_profile_version_id']
        or instance['status'] != 'READY'
        or instance['ready_at'] != instance_step['ended_at']
        or not instance['runtime_binding']
    ):
        raise StorageUnavailable('Original native instance binding differs')
    grant_row = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?', (task['authorization_id'],)
    ).fetchone()
    if (
        grant_row is None
        or grant_row['task_id'] != task['id']
        or grant_row['profile_version_id'] != instance['effective_profile_version_id']
        or grant_row['status'] not in ('BOUND_PENDING_APPLY', 'EFFECTIVE')
    ):
        raise TaskExecutionError('ORIGINAL_NATIVE_START_GRANT_DIFFERS')
    return operation, task, steps, identity, grant_row


def _scope(operation, task, identity, session_id, grant):
    limits = project_grant(grant)['scope']['limits']
    return StartSessionScope(
        operation['id'],
        task['id'],
        identity['instance_id'],
        session_id,
        task['control_generation'],
        identity['state_version'],
        identity['effective_profile_version_id'],
        task['authorization_id'],
        identity['nonce'],
        task['workspace_id'],
        limits['query_timeout_seconds'],
        limits['send_timeout_seconds'],
    )


def _original_ready_host(connection, task, session):
    start = connection.execute(
        """SELECT o.* FROM code_operations o JOIN code_operation_steps launch
           ON launch.operation_id=o.id AND launch.step_no=4
           WHERE o.task_id=? AND o.operation_type='START' AND o.status='SUCCEEDED'
           AND json_extract(launch.result_ref,'$.instance_id')=?""",
        (task['id'], session['instance_id']),
    ).fetchall()
    grant = connection.execute(
        'SELECT * FROM code_authorizations WHERE id=?', (task['authorization_id'],)
    ).fetchone()
    workspace = connection.execute(
        "SELECT 1 FROM code_workspaces WHERE id=? AND task_id=? AND status='READY'",
        (task['workspace_id'], task['id']),
    ).fetchone()
    if len(start) != 1 or grant is None or workspace is None:
        raise StorageUnavailable('Original active Coding session owner missing')
    original = start[0]
    _, steps = original_start_steps(connection, original)
    identity = strict_json_object(steps[3]['external_identity'])
    if (
        any(step['status'] != 'SUCCEEDED' for step in steps)
        or identity['instance_id'] != session['instance_id']
        or identity['task_id'] != task['id']
        or identity['operation_id'] != original['id']
        or identity['control_generation'] != original['control_generation']
        or identity['state_version'] != original['expected_state_version'] + 2
        or strict_json_object(steps[0]['result_ref'])['workspace_id'] != task['workspace_id']
        or grant['status'] != 'EFFECTIVE'
        or grant['task_id'] != task['id']
        or grant['profile_version_id'] != task['execution_profile_version_id']
    ):
        raise StorageUnavailable('Original active Coding session owner differs')
    from .task_configuration_effective import effective_control_application

    effective_control_application(
        connection,
        task,
        instance_id=session['instance_id'],
        launch_profile_id=identity['effective_profile_version_id'],
    )
    return original, identity, grant


def handoff_session_scope(connection, task, session, operation_id, nonce):
    original, identity, grant = _original_ready_host(connection, task, session)
    base = _scope(original, task, identity, session['id'], grant)
    if (
        session['task_id'] != task['id']
        or session['control_generation'] != task['control_generation']
        or base.control_generation <= original['control_generation']
        or session['role'] not in ('FRONTEND', 'INTEGRATION')
        or type(nonce) is not str
        or len(nonce) != 32
        or any(char not in '0123456789abcdef' for char in nonce)
    ):
        raise StorageUnavailable('Original role session action scope differs')
    return SuccessorSessionScope(
        **asdict(base),
        role=session['role'],
        transition_operation_id=operation_id,
        transition_nonce=nonce,
        original_launch_generation=original['control_generation'],
    )


def successor_session_scope(connection, task, replacement):
    original, identity, grant = _original_ready_host(connection, task, replacement.target)
    base = _scope(original, task, identity, replacement.target['id'], grant)
    return SuccessorSessionScope(
        **asdict(base),
        role=replacement.target['role'],
        transition_operation_id=replacement.operation['id'],
        transition_nonce=replacement.intent['nonce'],
        original_launch_generation=original['control_generation'],
        transition_kind='REPAIR',
        transition_step_no=1,
    )


def original_active_session_scope(connection, task, session, *, original_handoff_id=0):
    if (
        session['id'] != task['active_session_id']
        or session['task_id'] != task['id']
        or session['status'] != 'ACTIVE'
        or session['control_generation'] != task['control_generation']
    ):
        raise StorageUnavailable('Original active Coding session owner missing')
    from .task_session_replacement import replacement_for_session

    replacement = replacement_for_session(connection, task['id'], session['id'])
    if replacement is not None:
        # The role chain validates the original handoffs separately from replacements.
        current_role_chain(connection, task, original_handoff_id=original_handoff_id)
        return successor_session_scope(connection, task, replacement)
    if session['role'] == 'BACKEND':
        start, identity, grant = _original_ready_host(connection, task, session)
        if (
            start['session_id'] != session['id']
            or start['control_generation'] != task['control_generation']
        ):
            raise StorageUnavailable('Original BACKEND session owner differs')
        return _scope(start, task, identity, session['id'], grant)
    try:
        chain = current_role_chain(connection, task, original_handoff_id=original_handoff_id)
    except RoleChainUnavailable as error:
        raise StorageUnavailable('Original role session lineage differs') from error
    operation_id = chain.operations[-1]
    row = connection.execute(
        """SELECT external_identity FROM code_operation_steps
           WHERE operation_id=? AND step_no=4 AND step_type='CREATE_SESSION' AND status='SUCCEEDED'""",
        (operation_id,),
    ).fetchone()
    native = strict_json_object(row['external_identity'])
    if native != {
        'session_id': session['id'],
        'instance_id': session['instance_id'],
        'control_generation': session['control_generation'],
        'nonce': native.get('nonce'),
    }:
        raise StorageUnavailable('Original role session creation identity differs')
    return handoff_session_scope(connection, task, session, operation_id, native['nonce'])


def _session(connection, scope):
    row = connection.execute(
        'SELECT * FROM code_sessions WHERE id=?', (scope.session_id,)
    ).fetchone()
    if (
        row is None
        or row['task_id'] != scope.task_id
        or row['instance_id'] != scope.instance_id
        or row['control_generation'] != scope.control_generation
        or row['role'] != 'BACKEND'
        or row['status'] != 'PREPARING'
    ):
        raise StorageUnavailable('Original native session binding differs')
    return row


def _advance_step(connection, operation_id, number, evidence, now):
    if (
        connection.execute(
            """UPDATE code_operation_steps SET status='RUNNING',external_identity=?,started_at=?,
           last_observed_at=? WHERE operation_id=? AND step_no=? AND status='PENDING'
           AND external_identity IS NULL AND result_ref IS NULL AND started_at IS NULL
           AND last_observed_at IS NULL AND ended_at IS NULL""",
            (canonical_input(evidence), now, now, operation_id, number),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original pending native step has evidence')


def _complete_step(connection, scope, number, now):
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,
           last_observed_at=? WHERE operation_id=? AND step_no=?""",
        (canonical_input({'session_id': scope.session_id}), now, now, scope.operation_id, number),
    )


def _claim_session(connection, parent, operation_id):
    operation, task, steps, identity, grant = _original(
        connection, parent, operation_id, CREATE_SESSION, 'PENDING'
    )
    if operation['session_id'] is not None or steps[5]['status'] != 'PENDING':
        raise StorageUnavailable('Original START already owns a native session')
    session_id = entity_id(connection, EntityKind.EXECUTION_SESSION)
    scope = _scope(operation, task, identity, session_id, grant)
    now = max(operation_time(None), task['updated_at'], steps[3]['ended_at'])
    connection.execute(
        """INSERT INTO code_sessions(id,task_id,instance_id,role,control_generation,status,created_at)
           VALUES(?,?,?,'BACKEND',?,'PREPARING',?)""",
        (session_id, scope.task_id, scope.instance_id, scope.control_generation, now),
    )
    connection.execute(
        'UPDATE code_operations SET session_id=? WHERE id=?', (session_id, operation_id)
    )
    _advance_step(connection, operation_id, CREATE_SESSION, asdict(scope), now)
    return scope


def _checked_session(connection, parent, scope, number, status):
    operation, task, steps, identity, grant = _original(
        connection, parent, scope.operation_id, number, status
    )
    session = _session(connection, scope)
    if (
        _scope(operation, task, identity, scope.session_id, grant) != scope
        or operation['session_id'] != scope.session_id
        or steps[4]['external_identity'] != canonical_input(asdict(scope))
        or session['created_at'] != steps[4]['started_at']
    ):
        raise TaskExecutionError('ORIGINAL_NATIVE_START_SCOPE_DIFFERS')
    return task, steps, session, grant


def _ready_session(connection, parent, scope, observed):
    native = observed.native_id if type(observed) is InitialNativeSession else observed
    _identifier(native, 'ses')
    from .task_configuration_progress import pending_configuration

    task, steps, session, _ = _checked_session(connection, parent, scope, CREATE_SESSION, 'RUNNING')
    if type(observed) is not InitialNativeSession and pending_configuration(connection, task):
        raise TaskExecutionError('ORIGINAL_STAGED_CONFIGURATION_UNVERIFIED')
    if session['native_session_id'] is not None or session['model_window'] is not None:
        raise StorageUnavailable('Original native session was already bound')
    now = max(operation_time(None), steps[4]['started_at'])
    connection.execute(
        'UPDATE code_sessions SET native_session_id=?,last_observed_at=? WHERE id=?',
        (native, now, scope.session_id),
    )
    if type(observed) is InitialNativeSession:
        record_initial_configuration(connection, scope, observed.configuration, at=now)
    _complete_step(connection, scope, CREATE_SESSION, now)


def _initial_context(connection, parent, operation_id):
    operation, task, steps, identity, grant = _original(
        connection, parent, operation_id, SEND_INITIAL, 'PENDING'
    )
    scope = _scope(operation, task, identity, operation['session_id'], grant)
    _, _, session, _ = _checked_session(connection, parent, scope, SEND_INITIAL, 'PENDING')
    if (
        steps[4]['status'] != 'SUCCEEDED'
        or strict_json_object(steps[4]['result_ref']) != {'session_id': scope.session_id}
        or session['native_message_id'] is not None
        or session['model_window'] is not None
        or session['gateway_credential_ref'] is not None
    ):
        raise StorageUnavailable('Original initial message is already bound')
    if (
        connection.execute(
            'SELECT 1 FROM code_waiting_items WHERE task_id=? LIMIT 1', (scope.task_id,)
        ).fetchone()
        is not None
    ):
        raise StorageUnavailable(
            'Initial prompt already has waiting facts requiring reconciliation'
        )
    native = _identifier(session['native_session_id'], 'ses')
    return scope, fixed_execution_context(connection, task, native, grant)


def fixed_execution_context(connection, task, native_session_id, grant):
    materials, _ = read_task_basis(connection, task)
    documents = (
        (task['document_id'], task['design_revision_id']),
        *((row['document_id'], row['revision_id']) for row in materials),
    )
    profile = connection.execute(
        'SELECT check_set_version_id FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    if (
        profile is None
        or grant['id'] != task['authorization_id']
        or grant['task_id'] != task['id']
        or grant['profile_version_id'] != task['execution_profile_version_id']
    ):
        raise StorageUnavailable('Original prompt configuration and authorization differ')
    return InitialContext(native_session_id, documents, profile[0], project_grant(grant)['scope'])


def _window(operation_id, message_id, state, *, opened=None, closed=None):
    return canonical_input(
        {
            'operation_id': operation_id,
            'native_trigger_message_id': message_id,
            'state': state,
            'opened_at': opened,
            'closed_at': closed,
        }
    )


def _initial_binding(scope, native, message_id, digest, credential_ref):
    return {
        'session_id': scope.session_id,
        'native_session_id': native,
        'native_message_id': message_id,
        'payload_sha256': digest,
        'gateway_credential_ref': credential_ref,
    }


def _claim_initial(connection, parent, scope, context, payload, credential_ref):
    if _initial_context(connection, parent, scope.operation_id) != (scope, context):
        raise TaskExecutionError('ORIGINAL_INITIAL_CONTEXT_DIFFERS')
    message_id = _identifier(payload['messageID'], 'msg')
    if type(credential_ref) is not str or not credential_ref:
        raise TaskExecutionError('ORIGINAL_INITIAL_MODEL_GATEWAY_REQUIRED')
    digest = hashlib.sha256(_bytes(payload)).hexdigest()
    original = _initial_binding(
        scope, context.native_session_id, message_id, digest, credential_ref
    )
    task, steps, _, _ = _checked_session(connection, parent, scope, SEND_INITIAL, 'PENDING')
    now = max(operation_time(None), task['updated_at'], steps[4]['ended_at'])
    connection.execute(
        """UPDATE code_sessions SET native_message_id=?,gateway_credential_ref=?,model_window=?,
           last_observed_at=? WHERE id=?""",
        (
            message_id,
            credential_ref,
            _window(scope.operation_id, message_id, 'QUEUED'),
            now,
            scope.session_id,
        ),
    )
    _advance_step(connection, scope.operation_id, SEND_INITIAL, original, now)
    return original


def _check_initial(connection, parent, scope, original):
    task, steps, session, grant = _checked_session(
        connection, parent, scope, SEND_INITIAL, 'RUNNING'
    )
    if (
        steps[5]['external_identity'] != canonical_input(original)
        or session['native_session_id'] != original['native_session_id']
        or session['native_message_id'] != original['native_message_id']
        or session['gateway_credential_ref'] != original['gateway_credential_ref']
        or session['model_window']
        != _window(scope.operation_id, original['native_message_id'], 'QUEUED')
    ):
        raise TaskExecutionError('ORIGINAL_INITIAL_BINDING_DIFFERS')
    return task, steps[5], grant


def _finish_initial(connection, parent, scope, original, accepted):
    if accepted != original['native_message_id']:
        raise TaskExecutionError('ORIGINAL_INITIAL_MESSAGE_UNVERIFIED')
    task, step, grant = _check_initial(connection, parent, scope, original)
    now = max(operation_time(None), task['updated_at'], step['started_at'])
    if task['state_version'] >= MAX_SAFE_INTEGER:
        raise StorageUnavailable('Original START task version is exhausted')
    if grant['status'] == 'BOUND_PENDING_APPLY':
        connection.execute(
            "UPDATE code_authorizations SET status='EFFECTIVE' WHERE id=?",
            (scope.authorization_id,),
        )
    connection.execute(
        """UPDATE code_configuration_applications SET status='APPLIED',applied_at=?
           WHERE task_id=? AND new_profile_version_id=? AND authorization_id=?
             AND operation_id=? AND status='APPLYING'""",
        (now, scope.task_id, scope.profile_id, scope.authorization_id, scope.operation_id),
    )
    connection.execute(
        """UPDATE code_sessions SET status='ACTIVE',model_window=?,last_observed_at=?
           WHERE id=?""",
        (_window(scope.operation_id, accepted, 'OPEN', opened=now), now, scope.session_id),
    )
    _complete_step(connection, scope, SEND_INITIAL, now)
    if (
        connection.execute(
            """UPDATE code_tasks SET active_session_id=?,started_at=?,updated_at=?,last_observed_at=?,
           state_version=state_version+1,status='RUNNING',phase='BACKEND'
           WHERE id=? AND state_version=? AND control_generation=? AND stop_requested_at IS NULL
           AND status='PENDING' AND active_session_id IS NULL""",
            (
                scope.session_id,
                now,
                now,
                now,
                scope.task_id,
                task['state_version'],
                scope.control_generation,
            ),
        ).rowcount
        != 1
    ):
        raise TaskExecutionError('ORIGINAL_NATIVE_START_FENCED')
    connection.execute(
        "UPDATE code_operations SET status='SUCCEEDED',ended_at=? WHERE id=?",
        (now, scope.operation_id),
    )
    record_confirmed_control(
        connection, scope, scope.operation_id, '后端会话已接收首条执行消息。', now
    )


def _mark_unknown(connection, operation_id, number):
    row = connection.execute(
        """SELECT o.task_id,o.session_id,o.control_generation,t.stop_requested_at,t.control_generation
                  AS task_generation,s.external_identity,s.last_observed_at
           FROM code_operation_steps s JOIN code_operations o ON o.id=s.operation_id
           JOIN code_tasks t ON t.id=o.task_id
           WHERE s.operation_id=? AND s.step_no=? AND s.status='RUNNING' AND o.status='RUNNING'""",
        (operation_id, number),
    ).fetchone()
    if row is None:
        return
    identity = strict_json_object(row['external_identity'])
    if identity['session_id'] != row['session_id']:
        raise StorageUnavailable('Original uncertain native session differs')
    now = max(operation_time(None), row['last_observed_at'])
    window = None
    if number == CREATE_SESSION:
        from .task_configuration_progress import interrupt_staged_configuration

        interrupt_staged_configuration(connection, row['task_id'], now, uncertain=True)
    if number == SEND_INITIAL:
        connection.execute(
            """UPDATE code_configuration_applications SET status='UNKNOWN'
               WHERE task_id=? AND operation_id=? AND status='APPLYING'""",
            (row['task_id'], operation_id),
        )
        closed = (
            row['stop_requested_at'] is not None
            or row['task_generation'] != row['control_generation']
        )
        window = _window(
            operation_id,
            identity['native_message_id'],
            'CLOSED' if closed else 'HELD',
            closed=now if closed else None,
        )
    if (
        connection.execute(
            """UPDATE code_sessions SET status='UNKNOWN',model_window=?,last_observed_at=?
           WHERE id=? AND task_id=? AND control_generation=? AND status='PREPARING'""",
            (window, now, row['session_id'], row['task_id'], row['control_generation']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original uncertain native session differs')
    connection.execute(
        "UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=? WHERE operation_id=? AND step_no=?",
        (now, operation_id, number),
    )
    connection.execute(
        "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
        (operation_id,),
    )


def advance_start_session(runtime, parent, *, cancelled, driver=None):
    if cancelled():
        return False
    runtime.commands()._owned()
    with runtime.database.transaction() as connection:
        candidate = _candidate(connection)
    if candidate is None:
        return False
    operation_id, number = candidate['id'], candidate['step_no']
    if candidate['status'] == 'RUNNING':
        with runtime.database.transaction(write=True) as connection:
            _mark_unknown(connection, operation_id, number)
        return True
    if driver is None or not driver.session_available(operation_id):
        return False

    original = payload = None
    if number == CREATE_SESSION:
        with runtime.database.transaction(write=True) as connection:
            scope = _claim_session(connection, parent, operation_id)
    else:
        with runtime.database.transaction() as connection:
            scope, context = _initial_context(connection, parent, operation_id)
        credential = driver.gateway_reference(scope)
        if credential is None:
            return False
        payload = driver.initial_payload(scope, context)
        with runtime.database.transaction(write=True) as connection:
            original = _claim_initial(connection, parent, scope, context, payload, credential)

    def checkpoint():
        if cancelled():
            raise TaskExecutionError('ORIGINAL_NATIVE_START_CANCELLED')
        with runtime.database.transaction() as connection:
            if number == CREATE_SESSION:
                _checked_session(connection, parent, scope, number, 'RUNNING')
            else:
                _check_initial(connection, parent, scope, original)

    try:
        checkpoint()
        if number == CREATE_SESSION:
            native = driver.create_session(scope, checkpoint)
            with runtime.database.transaction(write=True) as connection:
                _ready_session(connection, parent, scope, native)
        else:
            message = driver.send_initial(scope, original, payload, checkpoint)
            with runtime.database.transaction(write=True) as connection:
                _finish_initial(connection, parent, scope, original, message)
    except Exception as error:
        with runtime.database.transaction(write=True) as connection:
            _mark_unknown(connection, operation_id, number)
        if getattr(error, 'retained_owner', None) is not None:
            raise
        if not isinstance(error, (LaunchOutcomeUnknown, OSError)):
            raise
    return True
