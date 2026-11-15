"""Run the confirmed repair in the original role and capture its new candidate."""

from dataclasses import asdict
from datetime import datetime, timedelta
from time import monotonic
from uuid import uuid4

from backend.app.infrastructure.content_package import ContentPackageError, verify_candidate_package
from backend.app.infrastructure.content_paths import ContentPathEntry
from backend.app.infrastructure.content_secret_policy import load_secret_policy
from backend.app.infrastructure.content_selection import ContentSelection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    PrivatePackageGuard,
)
from backend.app.infrastructure.windows_private_record import PrivateRecordError
from backend.app.infrastructure.windows_task_repair_archive import (
    archive_changed_candidate_file,
    observe_changed_candidate_archive,
)
from backend.app.infrastructure.windows_task_repair_file import (
    create_missing_candidate_directory,
    publish_missing_candidate_file,
)
from backend.app.infrastructure.windows_task_workspace_tree import (
    CandidateWorkspaceError,
    CandidateWorkspaceLimits,
    hold_candidate_workspace,
)
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .command_registry import registered_command
from .task_basis import TaskBasisUnavailable
from .task_cancelled_repair import read_cancelled_repair, record_cancelled_repair
from .task_candidate_commit import check_stored_candidate_seal, read_stored_candidate_package
from .task_capture_quiescence import _unsettled_inputs
from .task_check_api import CAPTURE, CaptureCheckRequest, _accept_candidate_check
from .task_model_ingress import ModelWindow, read_original_window_state
from .task_records import record_confirmed_control, record_native_turn
from .task_repair_session import (
    advance_repair_session,
    replacement_continuation,
    reserve_repair_session,
)
from .task_repair_source_plan import RepairSourcePlan
from .task_repairs import _defects, read_repair_operation
from .task_resume_runtime import Continuation, _intent, _model_capacity_available, _step, _window
from .task_session_replacement import read_session_replacement, repair_execution
from .task_start import original_start_steps
from .task_start_session import (
    fixed_execution_context,
    original_active_session_scope,
    successor_session_scope,
)
from .task_start_workspace import workspace_allocation
from .workspace_materialization import WorkspaceMaterializationError, read_workspace_manifest

_ACTIVE = ('PENDING', 'RUNNING', 'UNKNOWN')
_OBSERVE_RECHECK_SECONDS = 2
_BOUNDARY_ERRORS = (TaskExecutionError, LaunchOutcomeUnknown, OSError)
_SOURCE_ERRORS = (
    ContentPackageError,
    PathBoundaryError,
    PackageSecurityError,
    PrivateRecordError,
    WorkspaceMaterializationError,
    ValueError,
)


class RepairSourceChanged(TaskExecutionError):
    """The actual original workspace does not match the fixed repair candidate."""


class RepairWriterUnverified(TaskExecutionError):
    """Original writer or native owner must be rechecked before any repair send."""


def _current(connection, identity):
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND operation_type='REPAIR'
           AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (identity,),
    ).fetchone()
    if operation is None:
        return None
    repair, fixed, steps = read_repair_operation(connection, operation)
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
    ).fetchone()
    if (
        task is None
        or task['stop_requested_at'] is not None
        or (task['active_session_id'], task['control_generation'])
        != repair_execution(connection, operation)
    ):
        return None
    return task, operation, repair, fixed, steps


def _owner(connection, current):
    task, operation, _, fixed, steps = current
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (task['active_session_id'], task['id']),
    ).fetchone()
    if (
        session is None
        or task['phase'] != session['role']
        or task['current_candidate_id'] != fixed['candidate_id']
        or task['state_version'] < operation['expected_state_version'] + 1
    ):
        raise TaskExecutionError('ORIGINAL_REPAIR_SESSION_FENCED')
    if steps[0]['external_identity'] is not None:
        active, continuation = replacement_continuation(connection, task, operation)
        if active['id'] != session['id']:
            raise StorageUnavailable('Original repair replacement current owner differs')
        if steps[1]['external_identity'] is not None:
            intent = strict_json_object(steps[1]['external_identity'])
            if _intent(continuation, intent['payload']) != intent:
                raise StorageUnavailable('Original replacement message intent differs')
        return active, continuation
    scope = original_active_session_scope(connection, task, session)
    previous = strict_json_object(session['model_window'])
    if steps[1]['external_identity'] is not None:
        intent = strict_json_object(steps[1]['external_identity'])
        before = intent['original_operation_id'], intent['previous_message_id']
    else:
        if previous['state'] != 'CLOSED' or task['status'] != 'WAITING':
            raise TaskExecutionError('ORIGINAL_REPAIR_SOURCE_WINDOW_NOT_CLOSED')
        before = previous['operation_id'], previous['native_trigger_message_id']
    window = ModelWindow(
        task['id'],
        session['instance_id'],
        task['control_generation'],
        session['id'],
        session['native_session_id'],
        *before,
    )
    continuation = Continuation(scope, window, session['gateway_credential_ref'])
    if (
        steps[1]['external_identity'] is not None
        and _intent(continuation, intent['payload']) != intent
    ):
        raise StorageUnavailable('Original repair message intent differs')
    return session, continuation


def _source(connection, current, owner):
    task, operation, _, fixed, _ = current
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (task['active_session_id'], task['id']),
    ).fetchone()
    if session is None:
        raise StorageUnavailable('Original repair source session disappeared')
    if _unsettled_inputs(connection, task['id'], operation['id'], owner.scope.instance_id):
        raise RepairWriterUnverified('ORIGINAL_REPAIR_WRITERS_UNRESOLVED')
    row = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (fixed['candidate_id'], task['id']),
    ).fetchone()
    replacement = read_session_replacement(connection, operation, ready=False)
    replacement_source = (
        replacement is not None and replacement.intent['candidate_id'] == fixed['candidate_id']
    )
    cancelled_source = False
    if (
        row is not None
        and row['control_generation'] != task['control_generation']
        and not replacement_source
        and session['model_window'] is not None
    ):
        cancelled_source = (
            read_cancelled_repair(
                connection, task, session, strict_json_object(session['model_window'])
            )
            is not None
        )
    if (
        row is None
        or row['role'] != task['phase']
        or (
            row['control_generation'] != task['control_generation']
            and not replacement_source
            and not cancelled_source
        )
    ):
        raise StorageUnavailable('Original repair candidate differs')
    original = read_stored_candidate_package(connection, row)
    defects = _defects(connection, task, row, fixed['defect_ids'])
    if defects is None:
        raise StorageUnavailable('Original repair defects disappeared')
    start = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (owner.scope.operation_id,)
    ).fetchone()
    _, steps = original_start_steps(connection, start)
    allocation = workspace_allocation(start, steps[0])
    profile = connection.execute(
        'SELECT capture_rules FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    if profile is None or allocation.snapshot_id != task['base_snapshot_id']:
        raise StorageUnavailable('Original repair configuration differs')
    return (
        original,
        defects,
        allocation,
        steps[0]['result_ref'],
        strict_json_object(profile['capture_rules']),
    )


def _entry(entry):
    return entry.path, entry.mode, entry.byte_count, entry.sha256


def _verify_original_workspace(
    parent, source, driver, owner, checkpoint, publish=None, prepare=None, archive_scope=None
):
    """Restore sealed entries, retaining changed files and locking bytes through intent preparation."""
    original, _, allocation, receipt, rules = source
    started = monotonic()

    def observe():
        return driver.observe_capture_turn(
            owner.scope, owner.previous, owner.credential_ref, checkpoint
        )

    proof = observe()
    baseline = read_workspace_manifest(
        parent, allocation, receipt, checkpoint, asdict(original.limits)
    )
    selection = ContentSelection(
        product_include_paths=rules['product_include_paths'],
        nonproduct_exclude_paths=rules['nonproduct_exclude_paths'],
        new_file_mode=rules['new_file_mode'],
        baseline_entries=[ContentPathEntry(item.path, item.mode) for item in baseline.entries],
    )
    limits = CandidateWorkspaceLimits(
        original.limits, original.git_limits.max_edges, 4096, original.git_limits.max_seconds
    )
    secret_policy = load_secret_policy(rules['secret_policy_ref'])

    def check_owner():
        if observe() != proof:
            raise RepairWriterUnverified('ORIGINAL_REPAIR_WORKSPACE_OWNER_DIFFERS')

    def read_workspace(expected, *, allow_missing, sealed, restored_count=0):
        with hold_candidate_workspace(
            proof.workspace.canonical_path,
            proof.workspace,
            selection=selection,
            secret_policy=secret_policy,
            limits=limits,
            quiescent=checkpoint,
            started_at=started,
        ) as workspace:
            present = set()
            changed = []
            for entry in workspace.entries:
                fixed = expected.get(entry.path)
                if fixed is not None and fixed.mode != entry.mode:
                    raise RepairSourceChanged('ORIGINAL_REPAIR_WORKSPACE_DIFFERS')
                if fixed is None or _entry(fixed) != _entry(entry):
                    if archive_scope is None or not allow_missing:
                        raise RepairSourceChanged('ORIGINAL_REPAIR_WORKSPACE_DIFFERS')
                    changed.append((entry, workspace.file_identity(entry)))
                workspace.read(entry)
                present.add(entry.path)
            missing = expected.keys() - present
            if missing and not allow_missing:
                raise RepairSourceChanged('ORIGINAL_REPAIR_WORKSPACE_DIFFERS')
            directories = {}
            workspace.plan_retained_files([entry for entry, _ in changed])
            for path in missing:
                selected = selection.file(path)
                if selected is None or selected.mode != expected[path].mode:
                    raise RepairSourceChanged('ORIGINAL_REPAIR_DESTINATION_DIFFERS')
                secret_policy.check_path(path)
                directories.update(workspace.plan_missing_file(path, selected.mode))
            check_owner()
            if not missing and not changed and prepare is not None:
                if plan is not None:
                    plan.pending(retained, observed, changed)
                prepare(evidence(sealed, restored_count), workspace.finish_capture)
        return missing, directories, changed

    def evidence(sealed, restored_count):
        return {
            'candidate_id': original.binding.candidate_id,
            'manifest_sha256': sealed.manifest_sha256,
            'restored_file_count': restored_count,
        }

    with PrivatePackageGuard(original.directory.canonical_path) as package:
        if package.verify() != original.directory:
            raise TaskExecutionError('ORIGINAL_REPAIR_PACKAGE_LOCATION_DIFFERS')
        verification = {
            'limits': original.limits,
            'git_limits': original.git_limits,
            'started_at': started,
            'active': checkpoint,
        }
        sealed = verify_candidate_package(package, original.binding, **verification)
        check_stored_candidate_seal(original, sealed)
        expected = {entry.path: entry for entry in sealed.manifest.entries}
        plan = None
        retained = None
        observed = set()
        if archive_scope is not None:
            plan = RepairSourcePlan(
                parent,
                archive_scope,
                original.binding,
                sealed.manifest_sha256,
                max(32768, original.limits.max_manifest_bytes * 4),
            )
            retained = plan.read()
            if retained is not None:
                if proof.scratch is None:
                    raise RepairWriterUnverified('ORIGINAL_REPAIR_ARCHIVE_UNVERIFIED')
                for row in retained['files']:
                    path = row['entry']['path']
                    archived = observe_changed_candidate_archive(
                        parent,
                        proof.workspace,
                        proof.scratch,
                        path,
                        plan.archive_key(path),
                        checkpoint,
                        expected_source=row,
                    )
                    if archived is not None:
                        observed.add(path)
        missing, directories, changed = read_workspace(
            expected, allow_missing=publish is not None, sealed=sealed
        )
        if plan is not None:
            plan.pending(retained, observed, changed)
        if changed:
            if publish is None or proof.scratch is None:
                raise RepairWriterUnverified('ORIGINAL_REPAIR_ARCHIVE_UNVERIFIED')
            check_owner()
            retained = plan.fix(changed, retained)
            for entry, identity in changed:
                key = plan.archive_key(entry.path)
                archive_changed_candidate_file(
                    parent,
                    proof.workspace,
                    proof.scratch,
                    identity,
                    entry,
                    key,
                    checkpoint,
                    publish,
                )
                observed.add(entry.path)
            missing, directories, remaining = read_workspace(
                expected, allow_missing=True, sealed=sealed
            )
            if remaining:
                raise RepairSourceChanged('ORIGINAL_REPAIR_WORKSPACE_DIFFERS')
        if missing:
            if proof.scratch is None:
                raise RepairWriterUnverified('ORIGINAL_REPAIR_SCRATCH_UNVERIFIED')

            def restore(entry, raw):
                if entry.path not in missing:
                    return
                secret_policy.check_bytes(entry.path, raw)
                parts = entry.path.split('/')
                parent = directories['']
                for count in range(1, len(parts)):
                    relative = '/'.join(parts[:count])
                    directory = directories[relative]
                    if directory is None:
                        directory = create_missing_candidate_directory(
                            proof.workspace, parent, relative, checkpoint, publish
                        )
                        directories[relative] = directory
                    parent = directory
                publish_missing_candidate_file(
                    proof.workspace, proof.scratch, parent, entry.path, raw, checkpoint, publish
                )

            verify_candidate_package(
                package, original.binding, expected=sealed, consume_file=restore, **verification
            )
            read_workspace(
                expected, allow_missing=False, sealed=sealed, restored_count=len(missing)
            )
    return evidence(sealed, len(missing))


def _prompt_context(connection, task, owner):
    grant = connection.execute(
        "SELECT * FROM code_authorizations WHERE id=? AND task_id=? AND status='EFFECTIVE'",
        (task['authorization_id'], task['id']),
    ).fetchone()
    if grant is None:
        raise TaskExecutionError('ORIGINAL_REPAIR_AUTHORIZATION_UNAVAILABLE')
    try:
        return fixed_execution_context(connection, task, owner.previous.native_session_id, grant)
    except TaskBasisUnavailable as error:
        raise TaskExecutionError('ORIGINAL_REPAIR_BASIS_UNAVAILABLE') from error


def _state(connection, current, status, at, *, failure=None, candidate=None):
    _, operation, repair, _, _ = current
    ended = at if status in ('SUCCEEDED', 'FAILED', 'CANCELLED') else None
    connection.execute(
        """UPDATE code_operations SET status=?,started_at=COALESCE(started_at,?),ended_at=?,failure_code=?
           WHERE id=? AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (status, at, ended, failure, operation['id']),
    )
    connection.execute(
        """UPDATE code_repairs SET status=?,ended_at=?,failure_code=?,result_candidate_id=?
           WHERE id=? AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (status, ended, failure, candidate, repair['id']),
    )


def _resolve_repair_wait(connection, operation, at, outcome):
    connection.execute(
        """UPDATE code_waiting_items SET status='RESOLVED',resolved_at=?,resolution_ref=?
           WHERE task_id=? AND source_kind='OPERATION' AND source_id=? AND kind='OPERATION_RESULT' AND status='OPEN'""",
        (
            at,
            canonical_input({'operation_id': operation['id'], 'outcome': outcome}),
            operation['task_id'],
            operation['id'],
        ),
    )


def _fail(connection, current, step, at, reason):
    task, operation, _, _, _ = current
    _step(connection, operation['id'], step, 'FAILED', at)
    _state(connection, current, 'FAILED', at, failure=reason)
    _resolve_repair_wait(connection, operation, at, reason)
    if task['status'] == 'WAITING':
        connection.execute(
            """UPDATE code_tasks SET status='VERIFYING',resume_phase=NULL,updated_at=?,
               last_observed_at=?,state_version=state_version+1 WHERE id=? AND status='WAITING'""",
            (at, at, task['id']),
        )


def _record_message(connection, current, owner, window, at):
    task, operation, _, _, _ = current
    if read_original_window_state(connection, window, owner.credential_ref) != 'QUEUED':
        raise StorageUnavailable('Original repair window is no longer queued')
    _step(connection, operation['id'], 2, 'SUCCEEDED', at)
    _state(connection, current, 'RUNNING', at)
    _window(connection, window, 'OPEN', at)
    _resolve_repair_wait(connection, operation, at, 'MESSAGE_CONFIRMED')
    changed = connection.execute(
        """UPDATE code_tasks SET status='RUNNING',resume_phase=NULL,state_version=state_version+1,
           updated_at=?,last_observed_at=? WHERE id=? AND state_version=? AND status='WAITING'
           AND stop_requested_at IS NULL""",
        (at, at, task['id'], task['state_version']),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original repair was fenced before opening its model window')


def _capture(connection, current, session, window, proof, at):
    task, operation, _, _, _ = current
    identity = operation['id']
    record_native_turn(connection, window, proof.turn, at)
    if proof.turn.outcome != 'COMPLETED':
        quiet = record_cancelled_repair(connection, task, operation, session, proof, at)
        saved = strict_json_object(session['model_window'])
        saved.update(state='CLOSED', closed_at=at)
        connection.execute(
            'UPDATE code_sessions SET model_window=?,last_observed_at=? WHERE id=?',
            (canonical_input(saved), at, session['id']),
        )
        _step(connection, identity, 3, 'CANCELLED', at, result=quiet)
        cancelled = connection.execute(
            """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
               WHERE operation_id=? AND step_no=4 AND status='PENDING'
               AND external_identity IS NULL AND result_ref IS NULL AND started_at IS NULL""",
            (at, at, identity),
        )
        if cancelled.rowcount != 1:
            raise StorageUnavailable('Cancelled repair had already reserved a new capture')
        _state(connection, current, 'CANCELLED', at)
        _resolve_repair_wait(connection, operation, at, 'NATIVE_TURN_CANCELLED')
        connection.execute(
            """UPDATE code_tasks SET status='VERIFYING',state_version=state_version+1,
               updated_at=?,last_observed_at=? WHERE id=? AND status='RUNNING'""",
            (at, at, task['id']),
        )
        return
    request = CaptureCheckRequest(
        task['id'],
        task['state_version'],
        'HANDOFF',
        registered_command('POST', CAPTURE.format(task_id=task['id']), str(uuid4())),
        None,
    )
    accepted = _accept_candidate_check(
        connection, task, session, request, previous_status='RUNNING'
    )
    # The internal capture is owned by this original repair, not a second user command.
    if type(accepted.result) is not dict or accepted.result.get('code') != 'OPERATION_ACCEPTED':
        raise StorageUnavailable('Original repair capture could not be reserved')
    child = accepted.result['data']['operation_id']
    _step(connection, identity, 3, 'SUCCEEDED', at, result={'native_turn_observed': True})
    _step(connection, identity, 4, 'RUNNING', at, intent={'capture_operation_id': child})


def _finish_capture(connection, current, at):
    task, operation, _, fixed, steps = current
    capture_id = strict_json_object(steps[3]['external_identity'])['capture_operation_id']
    child = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND task_id=? AND session_id=?
           AND control_generation=? AND operation_type='CAPTURE_AND_CHECK'""",
        (capture_id, task['id'], task['active_session_id'], task['control_generation']),
    ).fetchone()
    if child is None:
        raise StorageUnavailable('Original repair capture disappeared')
    candidate = connection.execute(
        """SELECT * FROM code_candidates WHERE task_id=? AND capture_operation_id=?
           AND parent_candidate_id=? AND control_generation=?""",
        (task['id'], capture_id, fixed['candidate_id'], task['control_generation']),
    ).fetchone()
    if candidate is None:
        if child['status'] in ('FAILED', 'CANCELLED'):
            _fail(connection, current, 4, at, 'CONTENT_NOT_READY')
            return True
        return False
    if candidate['id'] != task['current_candidate_id']:
        raise StorageUnavailable('Original repair result is not the current candidate')
    _step(connection, operation['id'], 4, 'SUCCEEDED', at, result={'candidate_id': candidate['id']})
    _state(connection, current, 'SUCCEEDED', at, candidate=candidate['id'])
    session = connection.execute(
        'SELECT * FROM code_sessions WHERE id=?', (task['active_session_id'],)
    ).fetchone()
    scope = original_active_session_scope(connection, task, session)
    record_confirmed_control(
        connection, scope, operation['id'], '修复已生成新候选，需通过后续检查。', at
    )
    return True


def _single_repair_wait(connection, task, operation_id):
    waiting = connection.execute(
        """SELECT source_kind,source_id,kind,resume_phase FROM code_waiting_items
           WHERE task_id=? AND status='OPEN' ORDER BY id LIMIT 2""",
        (task['id'],),
    ).fetchall()
    return len(waiting) == 1 and tuple(waiting[0]) == (
        'OPERATION',
        operation_id,
        'OPERATION_RESULT',
        task['phase'],
    )


def repair_message_for_reconciliation(connection, task, operation_id):
    current = _current(connection, operation_id)
    if current is None or current[0] != task or task['status'] != 'WAITING':
        return None
    _, operation, _, _, steps = current
    if (
        operation['status'] != 'UNKNOWN'
        or operation['failure_code'] != 'EXTERNAL_RESULT_UNKNOWN'
        or steps[0]['status'] != 'SUCCEEDED'
        or steps[1]['status'] != 'UNKNOWN'
        or steps[1]['external_identity'] is None
        or steps[2]['status'] != 'PENDING'
        or steps[3]['status'] != 'PENDING'
        or steps[3]['external_identity'] is not None
    ):
        return None
    if not _single_repair_wait(connection, task, operation_id):
        return None
    _, owner = _owner(connection, current)
    payload = strict_json_object(steps[1]['external_identity'])['payload']
    window = owner.window(operation_id, payload['messageID'])
    if read_original_window_state(connection, window, owner.credential_ref) != 'QUEUED':
        return None
    return current, owner, window, payload


def repair_creation_for_reconciliation(connection, task, operation_id):
    current = _current(connection, operation_id)
    if current is None or current[0] != task or task['status'] != 'WAITING':
        return None
    _, operation, _, _, steps = current
    if (
        operation['status'] != 'UNKNOWN'
        or operation['failure_code'] != 'EXTERNAL_RESULT_UNKNOWN'
        or steps[0]['status'] != 'UNKNOWN'
        or steps[0]['external_identity'] is None
        or steps[0]['result_ref'] is not None
        or any(
            step['status'] != 'PENDING'
            or step['external_identity'] is not None
            or step['result_ref'] is not None
            for step in steps[1:]
        )
        or not _single_repair_wait(connection, task, operation_id)
    ):
        return None
    replacement = read_session_replacement(connection, operation, ready=False)
    if (
        replacement is None
        or replacement.target['native_session_id'] is not None
        or replacement.target['status'] != 'PREPARING'
    ):
        return None
    return current, successor_session_scope(connection, task, replacement), replacement


def record_reconciled_repair_creation(connection, observation, native, at):
    from backend.app.infrastructure.opencode_instance_control import _identifier

    current, scope, replacement = observation
    task, operation, _, _, _ = current
    if (
        _current(connection, operation['id']) != current
        or _identifier(native, 'ses') == replacement.source['native_session_id']
    ):
        raise TaskExecutionError('ORIGINAL_REPAIR_CREATION_RECONCILIATION_FENCED')
    changed = connection.execute(
        "UPDATE code_sessions SET native_session_id=?,last_observed_at=? WHERE id=? AND task_id=? AND status='PREPARING' AND native_session_id IS NULL",
        (native, at, scope.session_id, task['id']),
    )
    if changed.rowcount != 1:
        raise TaskExecutionError('ORIGINAL_REPAIR_CREATION_RECONCILIATION_FENCED')
    _step(connection, operation['id'], 1, 'RUNNING', at)
    _state(connection, current, 'RUNNING', at)
    connection.execute(
        'UPDATE code_tasks SET updated_at=?,last_observed_at=? WHERE id=?',
        (at, at, task['id']),
    )


def record_reconciled_repair_message(connection, observation, at):
    current, owner, window, _ = observation
    _record_message(connection, current, owner, window, at)


def advance_repairs(runtime, driver, parent, admissions, *, cancelled):
    if cancelled():
        return False
    database = runtime.database
    retry_before = (
        (datetime.fromisoformat(operation_time(None)) - timedelta(seconds=_OBSERVE_RECHECK_SECONDS))
        .isoformat(timespec='milliseconds')
        .replace('+00:00', 'Z')
    )
    with database.transaction() as connection:
        row = connection.execute(
            """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
               JOIN code_operation_steps observation ON observation.operation_id=o.id AND observation.step_no=3
               WHERE o.operation_type='REPAIR' AND o.status IN ('PENDING','RUNNING','UNKNOWN')
               AND t.stop_requested_at IS NULL AND (
                   t.control_generation=o.control_generation OR EXISTS(
                       SELECT 1 FROM code_operation_steps restore WHERE restore.operation_id=o.id
                       AND restore.step_no=1 AND json_extract(restore.external_identity,'$.replacement.target_generation')=t.control_generation
                       AND json_extract(restore.external_identity,'$.replacement.target_session_id')=t.active_session_id))
               AND (observation.last_observed_at IS NULL OR observation.last_observed_at<=?)
               AND NOT EXISTS(SELECT 1 FROM code_operations r WHERE r.task_id=o.task_id
                   AND r.operation_type='RECONCILE' AND r.status='PENDING'
                   AND json_extract(r.fixed_input,'$.operation_id')=o.id)
               ORDER BY o.id LIMIT 1""",
            (retry_before,),
        ).fetchone()
        current = None if row is None else _current(connection, row['id'])
    if current is None:
        return False
    task, operation, _, _, steps = current
    identity = operation['id']

    def checkpoint():
        runtime.commands().process_lock.assert_owned()
        if cancelled():
            raise TaskExecutionError('ORIGINAL_REPAIR_INTERRUPTED')
        with database.transaction() as connection:
            if _current(connection, identity) != current:
                raise TaskExecutionError('ORIGINAL_REPAIR_FENCED')

    def require_original_writer(connection):
        if cancelled() or _current(connection, identity) != current:
            raise TaskExecutionError('ORIGINAL_REPAIR_FENCED')
        _, active_owner = _owner(connection, current)
        if active_owner != owner or _unsettled_inputs(
            connection, task['id'], identity, owner.scope.instance_id
        ):
            raise RepairWriterUnverified('ORIGINAL_REPAIR_WRITERS_UNRESOLVED')

    def publish_original(write_source):
        runtime.commands().process_lock.assert_owned()
        with database.transaction(write=True) as connection:
            require_original_writer(connection)
            write_source()

    def time():
        return max(operation_time(None), task['updated_at'])

    def recheck_replacement_source(scope, replacement, queue_original):
        expected = replacement.intent['quiet']['proof']
        credential = replacement.source['gateway_credential_ref']

        class OriginalSourceObserver:
            def observe_capture_turn(self, _scope, _window, _ref, active):
                return driver.observe_replacement_source(scope, expected, credential, active)

        source_owner = Continuation(
            scope,
            ModelWindow(
                task['id'],
                replacement.source['instance_id'],
                replacement.source['control_generation'],
                replacement.source['id'],
                replacement.source['native_session_id'],
                replacement.intent['source_window']['operation_id'],
                replacement.intent['source_window']['native_trigger_message_id'],
            ),
            credential,
        )
        with database.transaction() as connection:
            source = _source(connection, current, source_owner)

        def publish_locked(write_source):
            runtime.commands().process_lock.assert_owned()
            with database.transaction(write=True) as connection:
                if cancelled() or _current(connection, identity) != current:
                    raise TaskExecutionError('ORIGINAL_REPAIR_REPLACEMENT_FENCED')
                write_source()

        def prepare_locked(proof, verify_locked):
            if (proof['candidate_id'], proof['manifest_sha256']) != (
                replacement.intent['source_evidence']['candidate_id'],
                replacement.intent['source_evidence']['manifest_sha256'],
            ):
                raise RepairSourceChanged('ORIGINAL_REPAIR_REPLACEMENT_SOURCE_DIFFERS')
            queue_original(verify_locked)

        _verify_original_workspace(
            parent,
            source,
            OriginalSourceObserver(),
            source_owner,
            checkpoint,
            publish_locked,
            prepare_locked,
            identity,
        )

    if steps[0]['external_identity'] is not None and steps[1]['external_identity'] is None:
        try:
            dispatch = advance_repair_session(
                runtime,
                driver,
                current,
                admissions,
                checkpoint,
                _current,
                recheck_replacement_source,
            )
        except (*_BOUNDARY_ERRORS, *_SOURCE_ERRORS, CandidateWorkspaceError) as error:
            reason = 'EXTERNAL_RESULT_UNKNOWN'
            if isinstance(error, RepairSourceChanged) or (
                isinstance(error, CandidateWorkspaceError) and error.code == 'SOURCE_CHANGED'
            ):
                reason = 'SOURCE_CHANGED'
            elif isinstance(error, RepairWriterUnverified) or (
                isinstance(error, CandidateWorkspaceError) and error.code == 'WRITER_ACTIVE'
            ):
                reason = 'EXECUTION_NOT_STOPPED'
            elif isinstance(error, _SOURCE_ERRORS) and not isinstance(error, _BOUNDARY_ERRORS):
                reason = 'CONTENT_NOT_READY'
            with database.transaction(write=True) as connection:
                if not cancelled() and _current(connection, identity) == current:
                    _step(connection, identity, 1, 'UNKNOWN', time())
                    connection.execute(
                        'UPDATE code_operation_steps SET last_observed_at=? WHERE operation_id=? AND step_no=3',
                        (time(), identity),
                    )
                    _state(connection, current, 'UNKNOWN', time(), failure=reason)
            return True
        if dispatch is None:
            return True
        with database.transaction() as connection:
            current = _current(connection, identity)
        if current is None:
            return False
        task, operation, _, _, steps = current
        scope, previous, original, payload = dispatch
        try:
            driver.send_successor(scope, previous, original, payload, checkpoint)
        except _BOUNDARY_ERRORS:
            pass

    if steps[3]['external_identity'] is not None:
        with database.transaction(write=True) as connection:
            if _current(connection, identity) != current:
                return False
            return _finish_capture(connection, current, time())

    if steps[1]['external_identity'] is None:
        failure = None
        send = None

        def prepare_original(proof, verify_locked_source):
            nonlocal current, send
            archived_at = driver.repair_session_archived_at(
                owner.scope, owner.previous, owner.credential_ref, checkpoint
            )
            if archived_at is not None:
                quiet = driver.observe_capture_turn(
                    owner.scope, owner.previous, owner.credential_ref, checkpoint
                )
                verify_locked_source()
                driver.revoke_session_source(
                    owner.scope, owner.previous, owner.credential_ref, checkpoint
                )
                with database.transaction(write=True) as connection:
                    require_original_writer(connection)
                    reserve_repair_session(
                        connection, current, session, quiet, proof, archived_at, time()
                    )
                    next_current = _current(connection, identity)
                    if next_current is None:
                        raise StorageUnavailable('Original replacement reservation disappeared')
                current = next_current
                return
            payload = driver.repair_payload(
                owner.scope,
                owner.previous,
                owner.credential_ref,
                checkpoint,
                context=context,
                source=proof,
                defects=source[1],
            )
            verify_locked_source()
            window = owner.window(identity, payload['messageID'])
            if window.trigger_message_id == owner.previous.trigger_message_id:
                raise StorageUnavailable('Repair must have a new original message')
            with database.transaction(write=True) as connection:
                require_original_writer(connection)
                at = time()
                if not _model_capacity_available(
                    connection, runtime.catalog, admissions, owner.previous, at
                ):
                    _fail(connection, current, 1, at, 'CONFIG_NOT_READY')
                    return
                _step(connection, identity, 1, 'SUCCEEDED', at, result=proof)
                _step(connection, identity, 2, 'RUNNING', at, intent=_intent(owner, payload))
                _state(connection, current, 'RUNNING', at)
                _window(connection, window, 'QUEUED', at)
                next_current = _current(connection, identity)
                if next_current is None:
                    raise StorageUnavailable('Original repair send intent disappeared')
            current = next_current
            send = window, payload

        try:
            with database.transaction() as connection:
                session, owner = _owner(connection, current)
                source = _source(connection, current, owner)
                context = _prompt_context(connection, task, owner)
            if not driver.session_available(owner.scope.operation_id):
                raise RepairWriterUnverified('ORIGINAL_REPAIR_OWNER_NOT_AVAILABLE')
            _verify_original_workspace(
                parent,
                source,
                driver,
                owner,
                checkpoint,
                publish_original,
                prepare_original,
                identity,
            )
        except RepairSourceChanged:
            failure = 'SOURCE_CHANGED'
        except RepairWriterUnverified:
            failure = 'EXECUTION_NOT_STOPPED'
        except CandidateWorkspaceError as error:
            failure = {
                'SOURCE_CHANGED': 'SOURCE_CHANGED',
                'WRITER_ACTIVE': 'EXECUTION_NOT_STOPPED',
            }.get(error.code, 'CONTENT_NOT_READY')
        except (*_BOUNDARY_ERRORS, *_SOURCE_ERRORS):
            failure = 'CONTENT_NOT_READY'
        if send is None:
            if failure is not None:
                with database.transaction(write=True) as connection:
                    if not cancelled() and _current(connection, identity) == current:
                        _fail(connection, current, 1, time(), failure)
            return True
        if failure is None:
            window, payload = send
            try:
                checkpoint()
                driver.dispatch_continuation(
                    owner.scope, owner.previous, window, owner.credential_ref, payload, checkpoint
                )
            except _BOUNDARY_ERRORS:
                # The original send may have been applied. The next step is a read.
                pass
        # A custody failure after saving the intent also permits only observation.
        steps = current[4]
    else:
        with database.transaction() as connection:
            session, owner = _owner(connection, current)

    intent = strict_json_object(steps[1]['external_identity'])
    payload = intent['payload']
    window = owner.window(identity, payload['messageID'])
    if steps[1]['status'] in ('RUNNING', 'UNKNOWN'):
        try:
            checkpoint()
            seen = driver.observe_continuation(
                owner.scope, window, owner.credential_ref, payload, checkpoint
            )
        except _BOUNDARY_ERRORS:
            seen = None
        with database.transaction(write=True) as connection:
            if cancelled() or _current(connection, identity) != current:
                return False
            at = time()
            if seen == window.trigger_message_id:
                _record_message(connection, current, owner, window, at)
            else:
                _step(connection, identity, 2, 'UNKNOWN', at)
                connection.execute(
                    'UPDATE code_operation_steps SET last_observed_at=? WHERE operation_id=? AND step_no=3',
                    (at, identity),
                )
                _state(connection, current, 'UNKNOWN', at, failure='EXTERNAL_RESULT_UNKNOWN')
        return True

    try:
        checkpoint()
        proof = driver.observe_capture_turn(owner.scope, window, owner.credential_ref, checkpoint)
    except _BOUNDARY_ERRORS:
        proof = None
    with database.transaction(write=True) as connection:
        if cancelled() or _current(connection, identity) != current:
            return False
        at = time()
        if (
            proof is None
            or task['status'] != 'RUNNING'
            or _unsettled_inputs(connection, task['id'], identity, owner.scope.instance_id)
        ):
            _step(connection, identity, 3, 'RUNNING', at)
        else:
            _capture(connection, current, session, window, proof, at)
    return True


def reconcile_stopped_repairs(connection, task, at):
    rows = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND operation_type='REPAIR'
           AND status IN ('PENDING','RUNNING','UNKNOWN')""",
        (task['id'],),
    ).fetchall()
    for operation in rows:
        repair, fixed, steps = read_repair_operation(connection, operation)
        current = task, operation, repair, fixed, steps
        if steps[1]['external_identity'] is not None and steps[1]['status'] != 'SUCCEEDED':
            _step(connection, operation['id'], 2, 'UNKNOWN', at)
            _state(connection, current, 'UNKNOWN', at, failure='EXTERNAL_RESULT_UNKNOWN')
        else:
            connection.execute(
                """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
                   WHERE operation_id=? AND status IN ('PENDING','RUNNING','UNKNOWN')""",
                (at, at, operation['id']),
            )
            _state(connection, current, 'CANCELLED', at, failure='TASK_ENDED')
