"""APP-GUIDE-CMD-C09: deterministic recovery under the actual OS process lock."""
from datetime import datetime, timedelta
import sqlite3
from backend.app.documents.guards import active_manual_draft, assert_idle
from backend.app.documents.snapshot import _time
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.shared.validation import InvalidInput
from .contracts import recover_runs_input, recover_runs_result
from .contracts import cancel_guide_run_input, cancel_guide_run_result
from .contracts import fail_guide_run_input, fail_guide_run_result

RECOVERY_ERRORS = {'INTERRUPTED': '运行因进程中断而结束', 'EXECUTION_TIMEOUT': '运行连续15分钟没有进展'}
TERMINAL_RUNS = frozenset({'COMPLETED', 'FAILED', 'CANCELLED'})


def _pending_batches(connection, requirement_id):
    rows = connection.execute("SELECT b.id,b.requirement_id,b.guide_run_id,b.source_type,b.source_id,b.created_at,g.requirement_id AS run_requirement_id,g.action_type,g.status AS run_status,g.source_type AS run_source_type,g.source_id AS run_source_id FROM suggestion_batches b LEFT JOIN guide_runs g ON g.id=b.guide_run_id WHERE b.requirement_id=? AND b.status='PENDING' ORDER BY b.id", (requirement_id,)).fetchall()
    for row in rows:
        if row['run_requirement_id'] != requirement_id or row['action_type'] != 'MODIFY' or row['run_status'] != 'COMPLETED' or row['source_type'] != row['run_source_type'] or row['source_id'] != row['run_source_id'] or connection.execute('SELECT 1 FROM suggestions WHERE batch_id=? LIMIT 1', (row['id'],)).fetchone() is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
        _time(row['created_at'])
    if len(rows) > 1:
        raise Rejected('WORK_STATE_INCONSISTENT')
    return rows


def _recover_root(connection, repository, root, at):
    state, identity = root['document_work_state'], root['active_operation_id']
    if state == 'IDLE':
        assert_idle(connection, root, remaining_conflicts=frozenset())
        return False
    if state == 'MANUAL_EDITING':
        active_manual_draft(connection, root)
        return False
    if state == 'GUIDE_ACTIVE':
        run = connection.execute('SELECT id,requirement_id,status FROM guide_runs WHERE id=?', (identity,)).fetchone()
        if run is None or run['requirement_id'] != root['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        if run['status'] in ('RUNNING', 'WAITING_USER'):
            try:
                assert_idle(connection, root, remaining_conflicts=frozenset())
            except Rejected as error:
                if error.code != 'WORK_STATE_CONFLICT':
                    raise
                return False
            raise Rejected('WORK_STATE_INCONSISTENT')
        if run['status'] not in TERMINAL_RUNS:
            raise Rejected('WORK_STATE_INCONSISTENT')
        batches = _pending_batches(connection, root['id'])
        if batches and batches[0]['guide_run_id'] != run['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
    elif state == 'SUGGESTION_REVIEWING':
        batch = connection.execute('SELECT b.requirement_id,b.guide_run_id,b.status,g.requirement_id AS run_requirement_id FROM suggestion_batches b LEFT JOIN guide_runs g ON g.id=b.guide_run_id WHERE b.id=?', (identity,)).fetchone()
        if batch is None or batch['requirement_id'] != root['id'] or batch['run_requirement_id'] != root['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        batches = _pending_batches(connection, root['id'])
        if batch['status'] == 'PENDING':
            if not batches or batches[0]['id'] != identity:
                raise Rejected('WORK_STATE_INCONSISTENT')
            try:
                assert_idle(connection, root, remaining_conflicts=frozenset())
            except Rejected as error:
                if error.code != 'WORK_STATE_CONFLICT':
                    raise
                return False
            raise Rejected('WORK_STATE_INCONSISTENT')
        if batch['status'] not in ('COMPLETED', 'DISCARDED') or batches:
            raise Rejected('WORK_STATE_INCONSISTENT')
    else:
        raise Rejected('WORK_STATE_INCONSISTENT')
    # A terminal pointer alone cannot prove ownership of another live activity.
    if connection.execute("SELECT 1 FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT'", (root['id'],)).fetchone() or connection.execute("SELECT 1 FROM guide_runs WHERE requirement_id=? AND status IN ('RUNNING','WAITING_USER')", (root['id'],)).fetchone():
        raise Rejected('WORK_STATE_INCONSISTENT')
    candidate = batches[0] if batches else None
    repository.recover_occupancy(root, None if candidate is None else candidate['id'], None if candidate is None else candidate['created_at'], at)
    return True


def recover_runs(database: Database, payload: object, *, process_lock: ProcessLock) -> dict:
    try:
        request = recover_runs_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path:
            raise RuntimeError('Recovery lock must own the same actual database')
        with database.transaction(write=True) as connection:
            guides, requirements = GuideRepository(connection), RequirementRepository(connection)
            recovered, repaired, unchanged = [], [], []
            now = datetime.fromisoformat(request.operation_time[:-1] + '+00:00')
            for run in guides.running():
                created, updated = _time(run['created_at']), _time(run['updated_at'])
                if created > updated or updated > request.operation_time:
                    raise ValueError('Persisted run progress clock is invalid')
                interrupted = request.recovery_reason == 'STARTUP' and run['id'] not in request.live_run_ids
                timed_out = request.recovery_reason == 'NO_PROGRESS' and now - datetime.fromisoformat(updated[:-1] + '+00:00') >= timedelta(minutes=15)
                if interrupted or timed_out:
                    if requirements.get(run['requirement_id']) is None:
                        raise Rejected('WORK_STATE_INCONSISTENT')
                    code = 'INTERRUPTED' if interrupted else 'EXECUTION_TIMEOUT'
                    guides.recover_failed(run['id'], code, RECOVERY_ERRORS[code], request.operation_time)
                    recovered.append(run['id'])
            for root in requirements.all_roots():
                if root['updated_at'] > request.operation_time:
                    raise ValueError('Recovery cannot precede persisted requirement activity')
                (repaired if _recover_root(connection, requirements, root, request.operation_time) else unchanged).append(root['id'])
            result = recover_runs_result(request, recovered, repaired, unchanged)
        return result
    except Rejected:
        code = 'WORK_STATE_INCONSISTENT'
    except (StorageUnavailable, sqlite3.Error):
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}


def cancel_guide_run(executor: Idempotency, payload: object, *, clock=None) -> dict:
    """C03 atomic logical cancellation; no network I/O in the transaction."""
    try:
        request = cancel_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        guides = GuideRepository(connection)
        run = guides.get_status(request.guide_run_id)
        if run is None:
            raise Rejected('NOT_FOUND')
        if run['status'] == 'CANCELLED':
            # A new cancellation key still observes the original result; the
            # requirement may legitimately own a newer operation by now.
            return Success(cancel_guide_run_result(run), 200)
        if run['status'] not in ('RUNNING', 'WAITING_USER') or run['current_step'] == 'PERSISTING':
            raise Rejected('STATE_CONFLICT')
        requirements = RequirementRepository(connection)
        root = requirements.get(run['requirement_id'])
        if root is None or root['document_work_state'] != 'GUIDE_ACTIVE' or root['active_operation_type'] != 'GUIDE_RUN' or root['active_operation_id'] != run['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        try:
            assert_idle(connection, root, remaining_conflicts=frozenset())
        except Rejected as error:
            if error.code != 'WORK_STATE_CONFLICT':
                raise
        else:
            raise Rejected('WORK_STATE_INCONSISTENT')
        at = operation_time(clock)
        if _time(run['created_at']) > _time(run['updated_at']) or run['updated_at'] > at or root['updated_at'] > at:
            raise ValueError('Cancellation cannot precede persisted activity')
        cancelled = guides.cancel(run['id'], at)
        requirements.recover_occupancy(root, None, None, at)
        return Success(cancel_guide_run_result(cancelled), 200)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C03', request, operation,
        target_identity=f'GuideRun:{request.guide_run_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_INCONSISTENT'}))


def fail_guide_run(database: Database, payload: object, *, process_lock: ProcessLock, clock=None) -> dict:
    """C08 trusted failure summary; a late failure never overwrites a result."""
    try:
        request = fail_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path:
            raise RuntimeError('Failure writer must own the same actual database')
        with database.transaction(write=True) as connection:
            guides, requirements = GuideRepository(connection), RequirementRepository(connection)
            run = guides.get_status(request.guide_run_id)
            if run is None:
                raise Rejected('NOT_FOUND')
            # P01 requires RUNNING. A committed WAITING_USER result is also
            # protected from a delayed attempt failure, just like terminal runs.
            if run['status'] != 'RUNNING':
                result = fail_guide_run_result(run, False, unchanged=True)
            else:
                root = requirements.get(run['requirement_id'])
                if root is None:
                    raise Rejected('WORK_STATE_INCONSISTENT')
                owns = root['document_work_state'] == 'GUIDE_ACTIVE' and root['active_operation_type'] == 'GUIDE_RUN' and root['active_operation_id'] == run['id']
                if owns:
                    try:
                        assert_idle(connection, root, remaining_conflicts=frozenset())
                    except Rejected as error:
                        if error.code != 'WORK_STATE_CONFLICT':
                            raise
                    else:
                        raise Rejected('WORK_STATE_INCONSISTENT')
                at = operation_time(clock)
                if _time(run['created_at']) > _time(run['updated_at']) or run['updated_at'] > at or (owns and root['updated_at'] > at):
                    raise ValueError('Failure cannot precede persisted activity')
                guides.recover_failed(run['id'], request.error_code, request.safe_message, at)
                if owns:
                    requirements.recover_occupancy(root, None, None, at)
                result = fail_guide_run_result(guides.get_status(run['id']), owns, unchanged=False)
        return result
    except Rejected as error:
        code = error.code if error.code in ('NOT_FOUND', 'WORK_STATE_INCONSISTENT') else 'INTERNAL_ERROR'
    except (StorageUnavailable, sqlite3.Error):
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}
