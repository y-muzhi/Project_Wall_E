"""Drive one original Coding termination with its allocated native instance."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_task_basis_protocol import _hex
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_local_paths import FileIdentity, PathBoundaryError
from backend.app.infrastructure.windows_private_package import PackageSecurityError
from backend.app.infrastructure.windows_private_record import PrivateRecordError
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_integer, strict_json_object

from .coding_job_evidence import read_closed_candidate_job_ids
from .coding_model_wait import close_task_waits_after_stop
from .task_capture_quiescence import capture_steps
from .task_native_issues import retire_native_issues
from .task_permission_response import retire_permission_responses
from .task_question_response import retire_question_responses
from .task_resume import original_resume_steps
from .task_role_chain import HANDOFF, ROLES, STEPS, _handoff_target
from .task_role_chain import _fixed as _fixed_role
from .task_session_replacement import read_session_replacement
from .task_start import original_start_steps
from .task_start_instance import StartInstanceClaim
from .task_start_workspace import workspace_allocation
from .task_stop import _stop_steps, original_stop_result
from .task_verify_candidate import load_candidate_verification

POLICY = 'CODE20-OWNED-STOP-1'
UNVERIFIED = 'EXECUTION_NOT_STOPPED'


@dataclass(frozen=True)
class OwnedStop:
    claim: StartInstanceClaim
    workspace_id: int
    workspace_key: str
    workspace_parent: FileIdentity
    workspace_root: FileIdentity
    session_id: int | None
    native_session_id: str | None
    runtime_binding_ref: str | None
    process_receipt: str | None
    graceful_seconds: int
    force_seconds: int
    send_seconds: int

    def scope(self):
        return {
            'policy': POLICY,
            'task_id': self.claim.task_id,
            'start_operation_id': self.claim.operation_id,
            'instance_id': self.claim.instance_id,
            'original_generation': self.claim.generation,
            'workspace_id': self.workspace_id,
            'session_id': self.session_id,
        }


def _single(connection, table, task_id):
    rows = connection.execute(
        f'SELECT * FROM {table} WHERE task_id=? LIMIT 2', (task_id,)
    ).fetchall()
    if len(rows) > 1:
        raise StorageUnavailable('Original Coding stop contains additional activity')
    return rows[0] if rows else None


def _role_stop_rows(connection, task_id):
    return connection.execute(
        'SELECT * FROM code_operations WHERE task_id=? AND operation_type=? ORDER BY id',
        (task_id, HANDOFF),
    ).fetchall()


def _stop_sessions(connection, task, operation, start, instance):
    sessions = {
        row['id']: row
        for row in connection.execute(
            'SELECT * FROM code_sessions WHERE task_id=? ORDER BY control_generation,id',
            (task['id'],),
        )
    }
    records = _role_stop_rows(connection, task['id'])
    source = sessions.get(start['session_id'])
    if (
        not records
        and not sessions
        and start['session_id'] is None
        and operation['session_id'] is None
    ):
        if start['control_generation'] + 1 != operation['control_generation']:
            raise StorageUnavailable('Original Coding stop generation differs')
        return sessions, None
    if (
        source is None
        or source['role'] != 'BACKEND'
        or source['control_generation'] != start['control_generation']
        or any(row['instance_id'] != instance['id'] for row in sessions.values())
    ):
        raise StorageUnavailable('Original Coding stop session differs')
    expected = {source['id']}
    references = ()
    earlier_end = None
    generation = source['control_generation']
    pending = None
    replacements = connection.execute(
        """SELECT o.* FROM code_operations o JOIN code_operation_steps s ON s.operation_id=o.id
           WHERE o.task_id=? AND o.operation_type='REPAIR' AND s.step_no=1
           AND json_type(s.external_identity,'$.replacement')='object' ORDER BY o.id""",
        (task['id'],),
    ).fetchall()
    consumed = set()

    def follow_replacements(session, before=None):
        while True:
            next_rows = [
                row
                for row in replacements
                if row['id'] not in consumed
                and row['session_id'] == session['id']
                and (before is None or row['id'] < before)
            ]
            if not next_rows:
                return session
            if len(next_rows) != 1:
                raise StorageUnavailable('Original stop same-role lineage is ambiguous')
            original = read_session_replacement(connection, next_rows[0], ready=before is not None)
            if original is None:
                raise StorageUnavailable('Original stop same-role proof missing')
            consumed.add(original.operation['id'])
            session = original.target
            expected.add(session['id'])

    try:
        for handoff in records:
            source = follow_replacements(source, handoff['id'])
            generation = source['control_generation']
            if pending is not None or handoff['session_id'] != source['id']:
                raise ValueError('Original stop handoff source differs')
            if handoff['status'] == 'SUCCEEDED':
                if len(references) == 2:
                    raise ValueError('Original stop handoff exceeds Coding roles')
                source = _handoff_target(
                    connection,
                    handoff,
                    ROLES[: len(references) + 1],
                    references,
                    source['id'],
                    earlier_end,
                )
                expected.add(source['id'])
                references = (*references, handoff['id'])
                earlier_end = handoff['ended_at']
                generation = source['control_generation']
            else:
                pending = handoff
        if pending is None:
            source = follow_replacements(source)
            generation = source['control_generation']
        if consumed != {row['id'] for row in replacements}:
            raise ValueError('Original stop has an unrelated same-role creation')
        active = source
        native = source
        if pending is not None:
            fixed = _fixed_role(pending)
            steps = connection.execute(
                'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                (pending['id'],),
            ).fetchall()
            if (
                len(references) == 2
                or pending['control_generation'] != generation
                or fixed['target_role'] != ROLES[len(references) + 1]
                or tuple((row['step_no'], row['step_type']) for row in steps)
                != tuple(enumerate(STEPS, 1))
                or any(row['fixed_input'] != pending['fixed_input'] for row in steps)
            ):
                raise ValueError('Original unfinished handoff scope differs')
            if steps[1]['status'] == 'SUCCEEDED':
                generation += 1
                active = native = None
                if source['status'] != 'RETIRED':
                    raise ValueError('Original handoff source is not retired')
                if steps[3]['external_identity'] is not None:
                    identity = strict_json_object(steps[3]['external_identity'])
                    native = sessions.get(identity['session_id'])
                    if (
                        native is None
                        or native['role'] != fixed['target_role']
                        or native['control_generation'] != generation
                        or identity['instance_id'] != instance['id']
                        or identity['control_generation'] != generation
                    ):
                        raise ValueError('Original unfinished handoff target differs')
                    expected.add(native['id'])
            elif steps[3]['external_identity'] is not None:
                raise ValueError('Original handoff target allocated before retirement')
        if (
            set(sessions) != expected
            or generation + 1 != operation['control_generation']
            or operation['session_id'] not in (None, None if active is None else active['id'])
            or task['active_session_id']
            != (None if active is None or task['status'] == 'TERMINATED' else active['id'])
            or any(
                row['model_window'] is not None
                and strict_json_object(row['model_window']).get('state')
                not in ('CLOSED', 'RETIRED')
                for row in sessions.values()
            )
        ):
            raise ValueError('Original Coding stop session fence differs')
    except (KeyError, TypeError, ValueError, TaskExecutionError) as error:
        raise StorageUnavailable('Original Coding stop session chain differs') from error
    return sessions, native


def _retire_original_responses(connection, task_id, sessions, original_generation, *, at=None):
    scopes = tuple((session['id'], session['control_generation']) for session in sessions.values())
    retire_question_responses(
        connection, task_id, None, original_generation, at=at, session_scopes=scopes or None
    )
    retire_permission_responses(
        connection, task_id, None, original_generation, at=at, session_scopes=scopes or None
    )


def _natural_delivery_predecessor(connection, task, stop):
    if stop['operation_type'] != 'TERMINATE' or task['current_delivery_id'] is None:
        return None
    row = connection.execute(
        """SELECT d.operation_id,d.git_write_status,d.postcheck_status,o.control_generation,
           s.external_identity,s.result_ref FROM code_deliveries d
           JOIN code_operations o ON o.id=d.operation_id
           JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_no=8
           WHERE d.id=? AND d.task_id=?""",
        (task['current_delivery_id'], task['id']),
    ).fetchone()
    if row is None or row['external_identity'] is None:
        return None
    facts = strict_json_object(row['external_identity'])
    if (
        facts['delivery_id'] != task['current_delivery_id']
        or facts['fence_generation'] != row['control_generation'] + 1
        or facts['fence_generation'] + 1 != stop['control_generation']
        or row['git_write_status'] != 'CONFIRMED'
        or row['postcheck_status'] not in ('VERIFIED', 'CONFLICT', 'UNKNOWN')
    ):
        raise StorageUnavailable('Original natural delivery and user stop fence differ')
    return row, facts


def _previous_native_stop(connection, task, operation, original):
    natural = _natural_delivery_predecessor(connection, task, operation)
    if natural is None:
        return None
    row, facts = natural
    if row['result_ref'] is None:
        from .task_delivery_finalize import _natural_stop_observation

        if facts['runtime'] != original.scope():
            raise StorageUnavailable('Original natural STOP owner differs')
        observed = _natural_stop_observation(
            connection,
            {'id': row['operation_id'], 'control_generation': facts['fence_generation']},
            original,
        )
        return None if observed is None else observed['observed_at']
    result = strict_json_object(row['result_ref'])
    saved = result.get('stop')
    if not result:
        return None
    if saved is None or facts['runtime'] != original.scope():
        raise StorageUnavailable('Original natural stop proof differs')
    _read_observation(
        connection,
        {'id': row['operation_id'], 'control_generation': facts['fence_generation']},
        original,
        {
            'status': 'SUCCEEDED',
            'step_no': 8,
            'ended_at': saved['observed_at'],
            'result_ref': canonical_input(saved['evidence']),
        },
        'STOP',
    )
    return saved['observed_at']


def _original_scope(connection, task, operation):
    if (
        connection.execute(
            "SELECT 1 FROM code_operations WHERE task_id=? AND operation_type NOT IN ('START','RESUME','TERMINATE','ANSWER_QUESTION','DECIDE_PERMISSION','PREPARE_HANDOFF','APPLY_CONFIGURATION','CAPTURE_AND_CHECK','VERIFY_CANDIDATE','HANDOFF_ROLE','SUBMIT_FOR_TESTING','LINK_TEST_REPORT','REPAIR','PREPARE_DELIVERY','DELIVER','RECONCILE') LIMIT 1",
            (task['id'],),
        ).fetchone()
        is not None
        or read_closed_candidate_job_ids(connection, task['id']) is None
    ):
        return None
    start = connection.execute(
        "SELECT * FROM code_operations WHERE task_id=? AND operation_type='START'", (task['id'],)
    ).fetchone()
    instance = _single(connection, 'code_instances', task['id'])
    if start is None or instance is None:
        return None
    _, steps = original_start_steps(connection, start)
    workspace_step, _, _, instance_step = steps[:4]
    if workspace_step['status'] != 'SUCCEEDED' or instance_step['external_identity'] is None:
        return None
    allocation = workspace_allocation(start, workspace_step)
    workspace = _single(connection, 'code_workspaces', task['id'])
    binding = strict_json_object(instance_step['external_identity'])
    claim = StartInstanceClaim(
        instance['id'],
        start['id'],
        binding['nonce'],
        task['id'],
        start['control_generation'],
        start['expected_state_version'] + 2,
        instance['effective_profile_version_id'],
    )
    if (
        not _hex(claim.nonce, 32)
        or claim.reference() != instance_step['external_identity']
        or instance['control_generation'] != claim.generation
        or instance['workspace_id'] != allocation.workspace_id
        or workspace is None
        or workspace['id'] != allocation.workspace_id
        or workspace['private_location_key'] != allocation.key
        or workspace['status'] not in ('READY', 'RELEASED')
        or task['workspace_id'] != workspace['id']
    ):
        raise StorageUnavailable('Original Coding stop allocation differs')
    published = strict_json_object(workspace_step['result_ref'])
    if published.get('workspace_id') != allocation.workspace_id:
        raise StorageUnavailable('Original Coding stop workspace proof differs')
    root = FileIdentity(**published['directory'])
    natural = _natural_delivery_predecessor(connection, task, operation)
    session_scope = (
        operation
        if natural is None
        else {**dict(operation), 'control_generation': natural[1]['fence_generation']}
    )
    sessions, session = _stop_sessions(connection, task, session_scope, start, instance)
    native = None
    if session is not None and session['native_session_id'] is not None:
        native = _identifier(session['native_session_id'], 'ses')
    for resume in _resume_history(connection, task['id']):
        owner = sessions.get(resume['session_id'])
        if owner is None:
            raise StorageUnavailable('Original continuation crosses Coding stop scope')
        fixed, _ = original_resume_steps(connection, resume)
        if resume['control_generation'] == owner['control_generation']:
            continue
        # Natural cleanup is fenced one generation beyond the retired session.
        # A cleanup-only C36 cannot extend or replace that session's write scope.
        from .task_delivery_write import load_original_delivery
        from .task_resume_view import public_resume_operation

        if (
            resume['control_generation'] != owner['control_generation'] + 1
            or 'repository_quiescent_confirmed' in fixed
        ):
            raise StorageUnavailable('Original continuation crosses Coding stop scope')
        delivery = load_original_delivery(connection, fixed['operation_id'])
        evidence = strict_json_object(delivery.steps[7]['external_identity'])
        if (
            delivery.task['id'] != task['id']
            or delivery.operation['session_id'] != owner['id']
            or delivery.operation['control_generation'] != owner['control_generation']
            or evidence['fence_generation'] != resume['control_generation']
        ):
            raise StorageUnavailable('Original cleanup continuation crosses Coding stop scope')
        public_resume_operation(connection, resume)
    _retire_original_responses(connection, task['id'], sessions, claim.generation)
    profile = connection.execute(
        'SELECT limits FROM code_execution_profile_versions WHERE id=?', (claim.profile_id,)
    ).fetchone()
    if profile is None:
        raise StorageUnavailable('Original Coding stop profile is missing')
    limits = strict_json_object(profile['limits'])
    runtime = instance['runtime_binding']
    process = instance['process_identity']
    return OwnedStop(
        claim,
        workspace['id'],
        allocation.key,
        allocation.parent,
        root,
        None if session is None else session['id'],
        native,
        None if runtime is None else strict_json_object(runtime)['guard_run_ref'],
        None if process is None else strict_json_object(process)['ownership_ref'],
        strict_integer(limits['graceful_stop_seconds'], 'graceful_stop_seconds'),
        strict_integer(limits['force_stop_wait_seconds'], 'force_stop_wait_seconds'),
        strict_integer(limits['send_timeout_seconds'], 'send_timeout_seconds'),
    )


def _current(connection, operation_id):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
    ).fetchone()
    if operation is None or operation['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN'):
        return None
    original_stop_result(connection, operation)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    if (
        task is None
        or task['status'] != 'STOPPING'
        or task['state_version'] != operation['expected_state_version'] + 1
        or task['control_generation'] != operation['control_generation']
        or task['stop_requested_at'] != operation['created_at']
    ):
        raise StorageUnavailable('Original Coding stop fence differs')
    scope = _original_scope(connection, task, operation)
    if scope is None:
        return None
    steps = _stop_steps(connection, operation)
    if (
        steps[0]['status'] != 'PENDING'
        and strict_json_object(steps[0]['result_ref']) != scope.scope()
    ):
        raise StorageUnavailable('Original Coding stop frozen scope differs')
    return task, operation, steps, scope


def _observed_at(task, steps):
    now = max(operation_time(None), task['updated_at'])
    return max(now, *(step['last_observed_at'] or now for step in steps))


def _step(connection, operation, number, at, result, *, status='SUCCEEDED'):
    changed = connection.execute(
        """UPDATE code_operation_steps SET status=?,started_at=COALESCE(started_at,?),
           ended_at=?,last_observed_at=?,result_ref=? WHERE operation_id=? AND step_no=?
           AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (
            status,
            at,
            at if status == 'SUCCEEDED' else None,
            at,
            None if result is None else canonical_input(result),
            operation['id'],
            number,
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original Coding stop step advanced concurrently')


def _operation(connection, operation, at, *, status):
    if operation['status'] == status and operation['started_at'] is not None:
        return
    connection.execute(
        """UPDATE code_operations SET status=?,started_at=COALESCE(started_at,?),
           failure_code=? WHERE id=?""",
        (status, at, UNVERIFIED if status == 'UNKNOWN' else None, operation['id']),
    )


def _checkpoint(runtime, operation_id, original, cancelled):
    if cancelled():
        raise TaskExecutionError('ORIGINAL_TASK_STOP_INTERRUPTED')
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction() as connection:
        current = _current(connection, operation_id)
        if current is None or current[3] != original:
            raise TaskExecutionError('ORIGINAL_TASK_STOP_FENCED')


def _abort_result(step):
    if step['status'] == 'RUNNING':
        return 'DISPATCH_UNVERIFIED'
    raise StorageUnavailable('Original Coding abort checkpoint differs')


def _verified_stop(result, original):
    native = result.get('resource') or {}
    job = result.get('job_activity') or {}
    ack = result.get('acknowledgement') or {}
    fence = result.get('fence') or {}
    scope = fence.get('scope') or {}
    if (
        result.get('observed_action') != 'STOP'
        or result.get('action_phase') != 'ACKNOWLEDGED'
        or not _hex(result.get('input_sha256'), 64)
        or not _hex(result.get('binding_ref'), 32)
        or fence.get('stop_closed') is not True
        or scope.get('operation_id') != original.claim.operation_id
        or scope.get('step_no') != 4
        or scope.get('nonce') != original.claim.nonce
        or native.get('fence') != fence
        or native.get('process_state') not in ('NOT_CREATED', 'EXITED')
        or (
            original.process_receipt is not None
            and (
                native.get('process_state') != 'EXITED'
                or native.get('receipt_sha256') != original.process_receipt
            )
        )
        or (
            original.runtime_binding_ref is not None
            and native.get('resource_ref') != original.runtime_binding_ref
        )
        or native.get('job_ref') != result['binding_ref']
        or ack.get('binding_ref') != result['binding_ref']
        or ack.get('native') != native
        or job.get('complete') is not True
        or job.get('process_ids') != []
    ):
        raise TaskExecutionError('ORIGINAL_TASK_STOP_PROOF_UNVERIFIED')
    return result


def _proof_ref(operation_id, step, proof):
    digest = hashlib.sha256(canonical_input(proof).encode('utf-8')).hexdigest()
    return f'sqlite:code_operation_steps/{operation_id}/{step}#sha256={digest}'


def _observation(connection, operation, scope, kind, at, evidence_ref):
    identity = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    connection.execute(
        """INSERT INTO code_runtime_observations(
           id,task_id,instance_id,operation_id,control_generation,runtime_binding_ref,
           kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
           VALUES(?,?,?,?,?,?,?,'VERIFIED','[]',0,?,?)""",
        (
            identity,
            scope.claim.task_id,
            scope.claim.instance_id,
            operation['id'],
            operation['control_generation'],
            scope.runtime_binding_ref,
            kind,
            at,
            evidence_ref,
        ),
    )
    return identity


def _save_stop(connection, task, operation, original, result, at):
    proof = _verified_stop(result, original)
    reference = _proof_ref(operation['id'], 4, proof)
    identity = _observation(connection, operation, original, 'STOP', at, reference)
    _step(connection, operation, 4, at, {'stop_observation_id': identity, 'proof': proof})
    prior_stop = _previous_native_stop(connection, task, operation, original)
    if prior_stop is None:
        if (
            connection.execute(
                "UPDATE code_instances SET status='STOPPED',stopped_at=? WHERE id=? AND stopped_at IS NULL",
                (at, original.claim.instance_id),
            ).rowcount
            != 1
        ):
            raise StorageUnavailable('Original Coding instance stop chronology changed')
    else:
        instance = _single(connection, 'code_instances', task['id'])
        if instance['stopped_at'] != prior_stop or instance['status'] != 'STOPPED':
            raise StorageUnavailable('Original Coding natural instance stop chronology changed')
    connection.execute(
        'UPDATE code_tasks SET last_observed_at=?,updated_at=? WHERE id=?', (at, at, task['id'])
    )
    _operation(connection, operation, at, status='RUNNING')


def _resume_history(connection, task_id):
    return connection.execute(
        "SELECT * FROM code_operations WHERE task_id=? AND operation_type='RESUME' ORDER BY id",
        (task_id,),
    ).fetchall()


def _reconcile_writes(connection, task, operation, original, at):
    # The only current supported writer is this one launch Job. The task/stop generation
    # barrier is enforced before each START dispatch. Other command/Git histories require
    # their original verifiers and remain out of this restricted scope.
    if _original_scope(connection, task, operation) != original:
        raise StorageUnavailable('Original Coding write scope changed')
    for resume in _resume_history(connection, task['id']):
        if resume['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN'):
            continue
        _, steps = original_resume_steps(connection, resume)
        if steps[2]['external_identity'] is None:
            connection.execute(
                "UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED' WHERE id=?",
                (at, resume['id']),
            )
        else:
            # The native message can have been stored before stop. Retain its
            # uncertain acceptance without retaining any execution authority.
            connection.execute(
                """UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=?
                   WHERE operation_id=? AND step_no=3""",
                (at, resume['id']),
            )
            connection.execute(
                "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
                (resume['id'],),
            )
    sessions = {
        row['id']: row
        for row in connection.execute('SELECT * FROM code_sessions WHERE task_id=?', (task['id'],))
    }
    _retire_original_responses(connection, task['id'], sessions, original.claim.generation, at=at)
    for handoff in _role_stop_rows(connection, task['id']):
        if handoff['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN'):
            continue
        step = connection.execute(
            """SELECT * FROM code_operation_steps WHERE operation_id=? AND step_no IN (4,5)
               AND status IN ('RUNNING','UNKNOWN') AND external_identity IS NOT NULL ORDER BY step_no DESC LIMIT 1""",
            (handoff['id'],),
        ).fetchone()
        if step is not None:
            connection.execute(
                "UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=? WHERE operation_id=? AND step_no=?",
                (at, handoff['id'], step['step_no']),
            )
            connection.execute(
                "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
                (handoff['id'],),
            )
        else:
            connection.execute(
                """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
                   WHERE operation_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')""",
                (at, at, handoff['id']),
            )
            connection.execute(
                "UPDATE code_operations SET status='CANCELLED',failure_code='TASK_ENDED',ended_at=? WHERE id=?",
                (at, handoff['id']),
            )
    reads = connection.execute(
        "SELECT id FROM code_operations WHERE task_id=? AND operation_type='RECONCILE' AND status='PENDING'",
        (task['id'],),
    ).fetchall()
    for read in reads:
        if (
            connection.execute(
                "SELECT 1 FROM code_operation_steps WHERE operation_id=? AND (status<>'PENDING' OR external_identity IS NOT NULL)",
                (read['id'],),
            ).fetchone()
            is not None
        ):
            raise StorageUnavailable(
                'Original reconciliation is not a read-only pending observation'
            )
        connection.execute(
            "UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=? WHERE operation_id=?",
            (at, at, read['id']),
        )
        connection.execute(
            "UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED' WHERE id=?",
            (at, read['id']),
        )
    jobs = read_closed_candidate_job_ids(connection, task['id'])
    if jobs is None:
        raise StorageUnavailable('Original candidate Git activity remains unverified')
    capture = connection.execute(
        """SELECT id FROM code_operations WHERE task_id=? AND operation_type='CAPTURE_AND_CHECK'
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
        (task['id'],),
    ).fetchall()
    for row in capture:
        steps = capture_steps(connection, row['id'])
        if steps[3]['status'] not in ('PENDING', 'CANCELLED'):
            raise StorageUnavailable('Original candidate check activity remains unverified')
        # Published content and old candidate facts survive stop. A claimed
        # capture without a seal may still have a retained private package.
        if steps[1]['status'] in ('RUNNING', 'UNKNOWN'):
            connection.execute(
                """UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=?
                   WHERE operation_id=? AND step_no=2""",
                (at, row['id']),
            )
            connection.execute(
                """UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN'
                   WHERE id=?""",
                (row['id'],),
            )
        else:
            connection.execute(
                """UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED'
                   WHERE id=?""",
                (at, row['id']),
            )
    verifications = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type='VERIFY_CANDIDATE'
           AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
        (task['id'],),
    ).fetchall()
    for verify in verifications:
        _, _, steps = load_candidate_verification(connection, verify)
        if verify['status'] != 'PENDING' or any(
            step['status'] != 'PENDING' or step['external_identity'] is not None for step in steps
        ):
            raise StorageUnavailable('Original fixed-candidate activity remains unverified')
        connection.execute(
            "UPDATE code_operation_steps SET status='CANCELLED',ended_at=? WHERE operation_id=?",
            (at, verify['id']),
        )
        connection.execute(
            "UPDATE code_operations SET status='CANCELLED',ended_at=?,failure_code='TASK_ENDED' WHERE id=?",
            (at, verify['id']),
        )
    from .task_configuration_progress import interrupt_staged_configuration
    from .task_delivery import close_stopped_pending_delivery
    from .task_live_configuration import interrupt_live_configurations
    from .task_repair_runtime import reconcile_stopped_repairs

    interrupt_staged_configuration(connection, task['id'], at, uncertain=False)
    interrupt_live_configurations(connection, task['id'], at)
    close_stopped_pending_delivery(connection, task, at)

    reconcile_stopped_repairs(connection, task, at)
    result = {'scope': original.scope(), 'other_writers': 0}
    if jobs:
        result['stopped_capture_command_ids'] = list(jobs)
    _step(connection, operation, 5, at, result)


def _abort_deadline(step, original):
    # Native timeouts are limited by the installation transport. A longer configured
    # grace is still honored in full, without blocking the serial owner loop.
    at = datetime.fromisoformat(step['ended_at'])
    return (
        (at + timedelta(seconds=original.graceful_seconds))
        .isoformat(timespec='milliseconds')
        .replace('+00:00', 'Z')
    )


def _persist(runtime, identity, original, update):
    with runtime.database.transaction(write=True) as connection:
        current = _current(connection, identity)
        if current is None or current[3] != original:
            raise TaskExecutionError('ORIGINAL_TASK_STOP_FENCED')
        update(connection, *current)


def advance_owned_stops(runtime, driver, *, cancelled):
    if cancelled():
        return False
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        candidates = connection.execute(
            """SELECT o.id FROM code_operations o WHERE o.resource_kind='TASK'
               AND o.operation_type='TERMINATE' AND o.status IN ('PENDING','RUNNING','UNKNOWN')
               AND EXISTS(SELECT 1 FROM code_instances i WHERE i.task_id=o.task_id)
               ORDER BY o.id"""
        ).fetchall()
        current = None
        for row in candidates:
            found = _current(connection, row['id'])
            if found is None:
                continue
            task, operation, steps, original = found
            at = _observed_at(task, steps)
            if steps[2]['status'] == 'SUCCEEDED' and steps[3]['status'] != 'SUCCEEDED':
                try:
                    deadline = _abort_deadline(steps[2], original)
                except OverflowError:
                    continue
                if at < deadline:
                    continue
            current = found
            break
        if current is None:
            return False
        task, operation, steps, original = current
        identity = operation['id']
        if steps[0]['status'] == 'PENDING':
            _step(connection, operation, 1, at, original.scope())
            _operation(connection, operation, at, status='RUNNING')
            return True
        if steps[4]['status'] == 'PENDING' and steps[3]['status'] == 'SUCCEEDED':
            _reconcile_writes(connection, task, operation, original, at)
            return True
        first_abort = steps[1]['status'] == 'SUCCEEDED' and steps[2]['status'] == 'PENDING'
        if first_abort:
            _step(connection, operation, 3, at, None, status='RUNNING')
        elif steps[2]['status'] == 'SUCCEEDED' and steps[3]['status'] == 'PENDING':
            _step(connection, operation, 4, at, None, status='RUNNING')
        elif steps[4]['status'] == 'SUCCEEDED' and steps[5]['status'] == 'PENDING':
            _step(connection, operation, 6, at, None, status='RUNNING')

    def checked():
        _checkpoint(runtime, identity, original, cancelled)

    if steps[1]['status'] == 'PENDING':
        checked()
        driver.revoke_original_gateway(original)
        _persist(
            runtime,
            identity,
            original,
            lambda db, task, op, steps, scope: _step(
                db, op, 2, _observed_at(task, steps), {'window_state': 'CLOSED'}
            ),
        )
        return True
    if steps[2]['status'] != 'SUCCEEDED':
        result = _abort_result(steps[2]) if not first_abort else 'DISPATCH_UNVERIFIED'
        if first_abort:
            try:
                checked()
                result = driver.abort_original(
                    original, checked, timeout_ms=min(30000, original.send_seconds * 1000)
                )
            except (LaunchOutcomeUnknown, TaskExecutionError, OSError) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    raise
        _persist(
            runtime,
            identity,
            original,
            lambda db, task, op, steps, scope: _step(
                db, op, 3, _observed_at(task, steps), {'result': result}
            ),
        )
        return True
    try:
        checked()
        if steps[3]['status'] != 'SUCCEEDED':
            result = driver.stop_original(
                original, timeout_ms=min(30000, original.force_seconds * 1000), cancelled=cancelled
            )
            _persist(
                runtime,
                identity,
                original,
                lambda db, task, op, steps, scope: _save_stop(
                    db, task, op, scope, result, _observed_at(task, steps)
                ),
            )
            return True
        return advance_owned_cleanup(runtime, driver, identity, original, checked, cancelled)
    except (
        LaunchOutcomeUnknown,
        TaskExecutionError,
        ConfigReadError,
        PackageSecurityError,
        PrivateRecordError,
        PathBoundaryError,
        OSError,
    ) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        _persist(
            runtime,
            identity,
            original,
            lambda db, task, op, steps, scope: _operation(
                db, op, _observed_at(task, steps), status='UNKNOWN'
            ),
        )
        return False


def advance_owned_cleanup(runtime, driver, identity, original, checkpoint, cancelled):
    checkpoint()
    result = driver.release_original(
        original, timeout_ms=min(30000, original.force_seconds * 1000), cancelled=cancelled
    )
    guard_ref = _cleanup_guard_ref(result, original)
    with runtime.database.transaction() as connection:
        current = _current(connection, identity)
        if current is None:
            raise StorageUnavailable('Original Coding stop no longer owns cleanup')
        natural = _natural_delivery_predecessor(connection, current[0], current[1])
    workspace_owner = identity if natural is None else natural[0]['operation_id']
    workspace_ref = driver.release_workspace_original(
        original, workspace_owner, guard_ref, checkpoint
    )
    if not _hex(workspace_ref, 64):
        raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_UNVERIFIED')
    driver.retire_original(original)
    _persist(
        runtime,
        identity,
        original,
        lambda db, task, op, steps, scope: _save_cleanup(
            db, task, op, steps, scope, result, workspace_ref
        ),
    )
    return True


def _cleanup_guard_ref(result, original):
    ack = result.get('acknowledgement') or {}
    fence = result.get('fence') or {}
    scope = fence.get('scope') or {}
    native = result.get('resource') or {}
    if (
        result.get('observed_action') != 'RELEASE'
        or result.get('action_phase') != 'ACKNOWLEDGED'
        or (result.get('preparation') or {}).get('cleanup_state') != 'COMPLETE'
        or not _hex(result.get('input_sha256'), 64)
        or not _hex(ack.get('cleanup_ref'), 64)
        or not _hex(result.get('binding_ref'), 32)
        or ack.get('binding_ref') != result['binding_ref']
        or fence.get('stop_closed') is not True
        or scope.get('operation_id') != original.claim.operation_id
        or scope.get('step_no') != 4
        or scope.get('nonce') != original.claim.nonce
        or ack.get('native') != native
        or native.get('fence') != fence
        or native.get('process_state') not in ('NOT_CREATED', 'EXITED')
        or native.get('job_ref') != result['binding_ref']
        or (
            original.runtime_binding_ref is not None
            and native.get('resource_ref') != original.runtime_binding_ref
        )
        or (
            original.process_receipt is not None
            and native.get('receipt_sha256') != original.process_receipt
        )
        or (result.get('job_activity') or {}).get('process_ids') != []
        or (result.get('job_activity') or {}).get('complete') is not True
    ):
        raise TaskExecutionError('ORIGINAL_TASK_CLEANUP_UNVERIFIED')
    return ack['cleanup_ref']


def _save_cleanup(connection, task, operation, steps, original, result, workspace_ref):
    if any(step['status'] != 'SUCCEEDED' for step in steps[:5]):
        raise StorageUnavailable('Original Coding cleanup prerequisites changed')
    at = _observed_at(task, steps)
    proof = {'guard': result, 'workspace_release_sha256': workspace_ref}
    identity = _observation(
        connection, operation, original, 'CLEANUP', at, _proof_ref(operation['id'], 6, proof)
    )
    _step(connection, operation, 6, at, {'cleanup_observation_id': identity, 'proof': proof})
    if (
        connection.execute(
            "UPDATE code_workspaces SET status='RELEASED' WHERE id=? AND status='READY'",
            (original.workspace_id,),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original Coding workspace changed before retirement')
    for session in connection.execute(
        "SELECT id,model_window FROM code_sessions WHERE task_id=? AND status<>'RETIRED'",
        (task['id'],),
    ).fetchall():
        window = session['model_window']
        if window is not None:
            value = strict_json_object(window)
            if value['state'] not in ('CLOSED', 'RETIRED'):
                raise StorageUnavailable('Original Coding model window reopened')
            value.update(state='RETIRED')
            window = canonical_input(value)
        connection.execute(
            "UPDATE code_sessions SET status='RETIRED',model_window=?,last_observed_at=? WHERE id=?",
            (window, at, session['id']),
        )
    retire_native_issues(connection, task['id'])
    close_task_waits_after_stop(connection, task['id'], operation['id'], at)
    connection.execute(
        "UPDATE code_operations SET status='SUCCEEDED',failure_code=NULL,ended_at=? WHERE id=?",
        (at, operation['id']),
    )
    if (
        connection.execute(
            """UPDATE code_tasks SET status='TERMINATED',phase='FINISHED',active_session_id=NULL,
           resume_phase=NULL,state_version=state_version+1,stopped_at=?,ended_at=?,updated_at=?,
           last_observed_at=? WHERE id=? AND status='STOPPING' AND control_generation=? AND state_version=?""",
            (at, at, at, at, task['id'], task['control_generation'], task['state_version']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original Coding task changed before retirement')


def _read_observation(connection, operation, original, step, kind):
    if step['status'] != 'SUCCEEDED':
        return None
    saved = strict_json_object(step['result_ref'])
    key = kind.lower() + '_observation_id'
    if set(saved) != {key, 'proof'}:
        raise StorageUnavailable('Original Coding observation reference differs')
    identity = strict_integer(saved[key], key)
    proof = saved['proof']
    try:
        if kind == 'STOP':
            _verified_stop(proof, original)
        elif not _hex(proof.get('workspace_release_sha256'), 64):
            raise TaskExecutionError('ORIGINAL_TASK_WORKSPACE_RELEASE_UNVERIFIED')
        else:
            _cleanup_guard_ref(proof['guard'], original)
    except (TaskExecutionError, TypeError, KeyError, AttributeError) as error:
        raise StorageUnavailable('Original Coding observation proof differs') from error
    record = connection.execute(
        'SELECT * FROM code_runtime_observations WHERE id=?', (identity,)
    ).fetchone()
    expected = {
        'id': identity,
        'task_id': original.claim.task_id,
        'testing_task_id': None,
        'instance_id': original.claim.instance_id,
        'command_id': None,
        'operation_id': operation['id'],
        'control_generation': operation['control_generation'],
        'runtime_binding_ref': original.runtime_binding_ref,
        'kind': kind,
        'result': 'VERIFIED',
        'reason_codes': '[]',
        'active_process_count': 0,
        'observed_at': step['ended_at'],
        'evidence_ref': _proof_ref(operation['id'], step['step_no'], proof),
    }
    if record is None or dict(record) != expected:
        raise StorageUnavailable('Original Coding observation row differs')
    return identity


def read_owned_progress(connection, task, operation, steps):
    original = _original_scope(connection, task, operation)
    if original is None or strict_json_object(steps[0]['result_ref']) != original.scope():
        raise StorageUnavailable('Original Coding stop scope differs')
    stopped = _read_observation(connection, operation, original, steps[3], 'STOP')
    cleaned = _read_observation(connection, operation, original, steps[5], 'CLEANUP')
    completed = operation['status'] == 'SUCCEEDED'
    if completed:
        workspace = _single(connection, 'code_workspaces', task['id'])
        instance = _single(connection, 'code_instances', task['id'])
        pending_session = connection.execute(
            "SELECT 1 FROM code_sessions WHERE task_id=? AND status<>'RETIRED' LIMIT 1",
            (task['id'],),
        ).fetchone()
        previous_stopped_at = _previous_native_stop(connection, task, operation, original)
        if (
            stopped is None
            or cleaned is None
            or stopped == cleaned
            or any(step['status'] != 'SUCCEEDED' for step in steps)
            or instance['status'] != 'STOPPED'
            or instance['stopped_at'] != (previous_stopped_at or steps[3]['ended_at'])
            or workspace['status'] != 'RELEASED'
            or pending_session is not None
            or task['active_session_id'] is not None
            or task['state_version'] != operation['expected_state_version'] + 2
            or not operation['ended_at'] == task['stopped_at'] == task['ended_at']
            or task['ended_at'] != steps[5]['ended_at']
        ):
            raise StorageUnavailable('Original Coding terminal stop proof differs')
    elif cleaned is not None:
        raise StorageUnavailable('Original Coding cleanup predates terminal state')
    return {
        'stop_observation_id': stopped,
        'cleanup_observation_id': cleaned,
    }
