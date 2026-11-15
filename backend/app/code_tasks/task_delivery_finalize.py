"""Close the original Coding owners after verified local delivery."""

from hashlib import sha256

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import increment
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .coding_job_evidence import read_closed_candidate_job_ids
from .coding_model_wait import read_task_waits
from .task_delivery_write import load_original_delivery
from .task_native_issues import retire_native_issues
from .task_resume import original_resume_steps
from .task_resume_runtime import _operation, _step
from .task_runtime_stop import (
    _cleanup_guard_ref,
    _observation,
    _original_scope,
    _proof_ref,
    _read_observation,
    _verified_stop,
)


def _scope(connection, original, *, pending_resume_id=None, require_idle=True):
    task, operation, delivery = original.task, original.operation, original.delivery
    if (
        task['status'] not in ('WAITING', 'COMPLETED')
        or task['stop_requested_at'] is not None
        or task['current_delivery_id'] != delivery['id']
        or delivery['status'] != 'SUCCEEDED'
        or delivery['git_write_status'] != 'CONFIRMED'
        or delivery['postcheck_status'] != 'VERIFIED'
        or any(step['status'] != 'SUCCEEDED' for step in original.steps[:7])
    ):
        return None
    generation = increment(operation['control_generation'])
    if task['control_generation'] not in (operation['control_generation'], generation):
        raise StorageUnavailable('Original delivery finalization generation differs')
    jobs = read_closed_candidate_job_ids(connection, task['id'])
    if jobs is None:
        return None
    if require_idle:
        active = connection.execute(
            """SELECT 1 FROM code_operations WHERE task_id=? AND id<>?
               AND id IS NOT ? AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1""",
            (task['id'], operation['id'], pending_resume_id),
        ).fetchone()
        if active is not None:
            return None
    scoped = {**dict(operation), 'control_generation': generation}
    owner = _original_scope(
        connection,
        {**dict(task), 'active_session_id': operation['session_id']},
        scoped,
    )
    if owner is None:
        return None
    fixed = {
        'delivery_id': delivery['id'],
        'fence_generation': generation,
        'runtime': owner.scope(),
        'closed_command_ids': list(jobs),
    }
    return owner, scoped, fixed


def _retire_windows(connection, task, at):
    sessions = connection.execute(
        'SELECT id,model_window FROM code_sessions WHERE task_id=? ORDER BY id', (task['id'],)
    ).fetchall()
    for row in sessions:
        raw = row['model_window']
        if raw is not None:
            window = strict_json_object(raw)
            if window.get('state') not in ('CLOSED', 'RETIRED'):
                raise StorageUnavailable('Original Coding execution still has an open model window')
            window['state'] = 'RETIRED'
            raw = canonical_input(window)
        connection.execute(
            "UPDATE code_sessions SET status='RETIRED',model_window=?,last_observed_at=? WHERE id=?",
            (raw, at, row['id']),
        )


def _matching_result(connection, current, owner, scoped, fixed):
    step = current.steps[7]
    if step['external_identity'] != canonical_input(fixed):
        raise StorageUnavailable('Original delivery finalization scope differs')
    if current.task['control_generation'] != fixed['fence_generation']:
        raise StorageUnavailable('Original delivery execution fence changed')
    result = {} if step['result_ref'] is None else strict_json_object(step['result_ref'])
    stop = result.get('stop')
    cleanup = result.get('cleanup')
    if set(result) - {'stop', 'cleanup'} or (cleanup is not None and stop is None):
        raise StorageUnavailable('Original delivery finalization evidence differs')
    for kind, saved in (('STOP', stop), ('CLEANUP', cleanup)):
        if saved is not None:
            _read_observation(
                connection,
                scoped,
                owner,
                {
                    'status': 'SUCCEEDED',
                    'step_no': 8,
                    'ended_at': saved['observed_at'],
                    'result_ref': canonical_input(saved['evidence']),
                },
                kind,
            )
    return result


def _natural_stop_observation(connection, operation, owner):
    rows = connection.execute(
        """SELECT * FROM code_runtime_observations WHERE operation_id=? AND kind='STOP' ORDER BY id""",
        (operation['id'],),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise StorageUnavailable('Original delivery has multiple STOP observations')
    row = rows[0]
    prefix = f'sqlite:code_operation_steps/{operation["id"]}/8#sha256='
    if (
        row['task_id'] != owner.claim.task_id
        or row['instance_id'] != owner.claim.instance_id
        or row['control_generation'] != operation['control_generation']
        or row['result'] != 'VERIFIED'
        or row['active_process_count'] != 0
        or row['runtime_binding_ref'] != owner.runtime_binding_ref
        or not row['evidence_ref'].startswith(prefix)
        or len(row['evidence_ref']) != len(prefix) + 64
    ):
        raise StorageUnavailable('Original delivery STOP observation differs')
    return row


def _private_stop_proof(parent, identity, owner, proof=None):
    filename = (
        sha256(f'DELIVERY-STOP:{identity}'.encode('ascii')).hexdigest()[:32] + '.delivery-stop.json'
    )
    raw = _read_original(parent, filename, 16384)
    if raw is None:
        if proof is None:
            raise StorageUnavailable('Original delivery STOP proof is missing')
        raw = canonical_input(
            {'operation_id': identity, 'scope': owner.scope(), 'proof': proof}
        ).encode('utf-8')
        _publish_original(parent, filename, raw, 16384)
        if _read_original(parent, filename, 16384) != raw:
            raise StorageUnavailable('Original delivery STOP proof publication differs')
    data = strict_json_object(raw)
    if (
        set(data) != {'operation_id', 'scope', 'proof'}
        or data['operation_id'] != identity
        or data['scope'] != owner.scope()
        or canonical_input(data).encode('utf-8') != raw
    ):
        raise StorageUnavailable('Original delivery private STOP proof differs')
    return _verified_stop(data['proof'], owner)


def read_finalized_delivery(connection, original):
    scoped = _scope(connection, original)
    if scoped is None:
        raise StorageUnavailable('Original natural delivery scope is missing')
    owner, operation, fixed = scoped
    result = _matching_result(connection, original, owner, operation, fixed)
    task = original.task
    step = original.steps[7]
    if (
        task['status'] != 'COMPLETED'
        or original.operation['status'] != 'SUCCEEDED'
        or step['status'] != 'SUCCEEDED'
        or set(result) != {'stop', 'cleanup'}
        or task['stop_requested_at'] is not None
        or task['stopped_at'] is not None
        or task['active_session_id'] is not None
        or not task['ended_at'] == original.operation['ended_at'] == step['ended_at']
    ):
        raise StorageUnavailable('Original natural delivery completion is unverified')
    return result


def resumable_finalization(connection, task, operation_id, *, pending_resume_id=None):
    if task['status'] != 'WAITING' or task['phase'] != 'DELIVERY':
        return None
    original = load_original_delivery(connection, operation_id)
    step = original.steps[7]
    if (
        original.task != task
        or original.operation['status'] not in ('RUNNING', 'UNKNOWN')
        or task['active_session_id'] != original.operation['session_id']
        or step['status'] != 'UNKNOWN'
        or step['external_identity'] is None
    ):
        return None
    scope = _scope(connection, original, pending_resume_id=pending_resume_id)
    if scope is None:
        return None
    owner, scoped, fixed = scope
    _matching_result(connection, original, owner, scoped, fixed)
    _natural_stop_observation(connection, scoped, owner)
    waits = read_task_waits(connection, task['id'])
    if (
        len(waits) != 1
        or waits[0]['kind'] != 'DELIVERY_RESULT'
        or waits[0]['source_kind'] != 'DELIVERY'
        or waits[0]['source_id'] != original.delivery['id']
    ):
        return None
    return original, waits[0]


def advance_delivery_finalization_resume(runtime):
    """Apply an explicit continuation to the original fenced cleanup only."""
    runtime.commands().process_lock.assert_owned()
    with runtime.database.transaction(write=True) as connection:
        resume = connection.execute(
            """SELECT r.* FROM code_operations r JOIN code_tasks t ON t.id=r.task_id
               JOIN code_operations source ON source.id=json_extract(r.fixed_input,'$.operation_id')
                   AND source.task_id=r.task_id AND source.operation_type='DELIVER'
               WHERE r.operation_type='RESUME' AND r.status='PENDING' AND t.stop_requested_at IS NULL
               AND json_extract(r.fixed_input,'$.repository_quiescent_confirmed') IS NULL
               ORDER BY r.id LIMIT 1"""
        ).fetchone()
        if resume is None:
            return False
        fixed, steps = original_resume_steps(connection, resume)
        if any(
            step['status'] != 'PENDING'
            or step['external_identity'] is not None
            or step['result_ref'] is not None
            for step in steps
        ):
            raise StorageUnavailable('Original cleanup continuation is not pending')
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (resume['task_id'],)
        ).fetchone()
        if (
            task is None
            or task['control_generation'] != resume['control_generation']
            or task['active_session_id'] != resume['session_id']
            or task['state_version'] <= resume['expected_state_version']
        ):
            raise StorageUnavailable('Original cleanup continuation is fenced')
        at = max(operation_time(None), task['updated_at'])
        ready = resumable_finalization(
            connection, task, fixed['operation_id'], pending_resume_id=resume['id']
        )
        if ready is None or fixed['waiting_item_ids'] != [ready[1]['id']]:
            _step(connection, resume['id'], 1, 'FAILED', at)
            _operation(connection, resume['id'], 'FAILED', at, 'CONFIG_NOT_READY')
            return True
        original, _ = ready
        result = original.steps[7]['result_ref']
        _step(
            connection,
            original.operation['id'],
            8,
            'RUNNING',
            at,
            result=None if result is None else strict_json_object(result),
        )
        _step(
            connection,
            resume['id'],
            1,
            'SUCCEEDED',
            at,
            result={'operation_id': original.operation['id']},
        )
        _step(connection, resume['id'], 2, 'SUCCEEDED', at)
        _step(
            connection,
            resume['id'],
            3,
            'SUCCEEDED',
            at,
            result={'delivery_id': original.delivery['id']},
        )
        _operation(connection, resume['id'], 'SUCCEEDED', at)
        return True


def _next_natural_delivery(connection):
    return connection.execute(
        """SELECT d.operation_id FROM code_deliveries d JOIN code_tasks t ON t.id=d.task_id
           JOIN code_operations o ON o.id=d.operation_id
           JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_no=8
           WHERE d.status='SUCCEEDED' AND d.postcheck_status='VERIFIED' AND t.status='WAITING'
           AND t.phase='DELIVERY' AND t.stop_requested_at IS NULL AND o.status IN ('RUNNING','UNKNOWN')
           AND s.status IN ('PENDING','RUNNING')
           ORDER BY o.id LIMIT 1"""
    ).fetchone()


def advance_owned_delivery_finalization(runtime, driver, parent, *, cancelled):
    if cancelled():
        return False
    runtime.commands().process_lock.assert_owned()
    database = runtime.database
    with database.transaction(write=True) as connection:
        row = _next_natural_delivery(connection)
        if row is None:
            return False
        identity = row['operation_id']
        current = load_original_delivery(connection, identity)
        scope = _scope(connection, current)
        if scope is None:
            return False
        owner, scoped, fixed = scope
        step = current.steps[7]
        task = current.task
        at = max(operation_time(None), task['updated_at'])
        if step['status'] == 'PENDING':
            if task['control_generation'] != current.operation['control_generation']:
                raise StorageUnavailable('Original delivery execution was already fenced')
            _retire_windows(connection, task, at)
            retire_native_issues(connection, task['id'])
            _step(connection, identity, 8, 'RUNNING', at, intent=fixed)
            connection.execute(
                """UPDATE code_tasks SET control_generation=?,state_version=?,updated_at=?
                   WHERE id=?""",
                (fixed['fence_generation'], increment(task['state_version']), at, task['id']),
            )
            return True
        _matching_result(connection, current, owner, scoped, fixed)
        previous = _natural_stop_observation(connection, scoped, owner)

    def checkpoint():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_DELIVERY_FINALIZATION_CANCELLED')
        with database.transaction() as connection:
            saved = load_original_delivery(connection, identity)
            if (
                saved.task['stop_requested_at'] is not None
                or saved.task['status'] != 'WAITING'
                or saved.steps[7]['external_identity'] != canonical_input(fixed)
                or saved.task['control_generation'] != fixed['fence_generation']
            ):
                raise TaskExecutionError('ORIGINAL_DELIVERY_FINALIZATION_FENCED')

    timeout = min(30000, owner.force_seconds * 1000)
    try:
        checkpoint()
        if previous is None:
            proof = _verified_stop(
                driver.stop_original(owner, timeout_ms=timeout, cancelled=cancelled), owner
            )
            proof = _private_stop_proof(parent, identity, owner, proof)
            with database.transaction(write=True) as connection:
                saved = load_original_delivery(connection, identity)
                if saved.task['stop_requested_at'] is not None:
                    return True
                at = max(operation_time(None), saved.task['updated_at'])
                _observation(connection, scoped, owner, 'STOP', at, _proof_ref(identity, 8, proof))
                connection.execute(
                    "UPDATE code_instances SET status='STOPPED',stopped_at=coalesce(stopped_at,?) WHERE id=?",
                    (at, owner.claim.instance_id),
                )
            return True

        stop_proof = _private_stop_proof(parent, identity, owner)
        if previous['evidence_ref'] != _proof_ref(identity, 8, stop_proof):
            raise StorageUnavailable('Original delivery STOP proof digest differs')
        driver.revoke_original_gateway(owner)
        guard = driver.release_original(owner, timeout_ms=timeout, cancelled=cancelled)
        guard_ref = _cleanup_guard_ref(guard, owner)
        workspace_ref = driver.release_workspace_original(owner, identity, guard_ref, checkpoint)
        checkpoint()
        driver.retire_original(owner)
        with database.transaction(write=True) as connection:
            saved = load_original_delivery(connection, identity)
            if saved.task['stop_requested_at'] is not None:
                return True
            at = max(operation_time(None), saved.task['updated_at'])
            _matching_result(connection, saved, owner, scoped, fixed)
            result = {
                'stop': {
                    'observed_at': previous['observed_at'],
                    'evidence': {'stop_observation_id': previous['id'], 'proof': stop_proof},
                }
            }
            proof = {'guard': guard, 'workspace_release_sha256': workspace_ref}
            evidence_id = _observation(
                connection, scoped, owner, 'CLEANUP', at, _proof_ref(identity, 8, proof)
            )
            result['cleanup'] = {
                'observed_at': at,
                'evidence': {'cleanup_observation_id': evidence_id, 'proof': proof},
            }
            _step(connection, identity, 8, 'SUCCEEDED', at, result=result)
            connection.execute(
                "UPDATE code_workspaces SET status='RELEASED' WHERE id=? AND status='READY'",
                (owner.workspace_id,),
            )
            connection.execute(
                """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
                   WHERE task_id=? AND status='OPEN' AND source_kind='DELIVERY' AND source_id=?""",
                (
                    at,
                    canonical_input({'operation_id': identity, 'outcome': 'DELIVERY_COMPLETED'}),
                    task['id'],
                    saved.delivery['id'],
                ),
            )
            _operation(connection, identity, 'SUCCEEDED', at)
            connection.execute(
                """UPDATE code_tasks SET status='COMPLETED',phase='FINISHED',resume_phase=NULL,
                   active_session_id=NULL,state_version=?,ended_at=?,updated_at=?,last_observed_at=? WHERE id=?""",
                (increment(saved.task['state_version']), at, at, at, task['id']),
            )
        return True
    except (LaunchOutcomeUnknown, TaskExecutionError, OSError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        with database.transaction(write=True) as connection:
            saved = load_original_delivery(connection, identity)
            if saved.task['stop_requested_at'] is None:
                at = max(operation_time(None), saved.task['updated_at'])
                result = (
                    None
                    if saved.steps[7]['result_ref'] is None
                    else strict_json_object(saved.steps[7]['result_ref'])
                )
                _step(connection, identity, 8, 'UNKNOWN', at, result=result)
        return False
