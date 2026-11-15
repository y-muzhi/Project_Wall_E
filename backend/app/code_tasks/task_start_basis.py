"""Prepare the original START basis on the same serial owner as its workspace."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_integer, strict_json_object

from .task_basis import TaskBasisUnavailable, read_task_basis
from .task_basis_package import (
    basis_digest,
    basis_source,
    observe_basis_seal,
    publish_basis_package,
    read_basis_package,
)
from .task_start import original_start_steps
from .task_start_workspace import _original_rows, workspace_allocation


def _candidate(connection):
    return connection.execute(
        """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
           JOIN code_operation_steps first ON first.operation_id=o.id AND first.step_no=1
           JOIN code_operation_steps basis ON basis.operation_id=o.id AND basis.step_no=2
           WHERE o.resource_kind='TASK' AND o.operation_type='START' AND o.status='RUNNING'
           AND first.status='SUCCEEDED' AND (basis.status='RUNNING' OR
             (basis.status='PENDING' AND t.status='PENDING' AND t.stop_requested_at IS NULL))
           ORDER BY (basis.status='RUNNING') DESC,o.id LIMIT 1"""
    ).fetchone()


def _original_basis(connection, operation_id):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (operation_id,)
    ).fetchone()
    if operation is None:
        raise TaskBasisUnavailable('Original basis operation is unavailable')
    _, steps = original_start_steps(connection, operation)
    if steps[0]['status'] != 'SUCCEEDED':
        raise TaskBasisUnavailable('Original workspace has no verified publication')
    allocation = workspace_allocation(operation, steps[0])
    _, task, workspace, _ = _original_rows(connection, allocation)
    if workspace['status'] != 'READY' or task['workspace_id'] != allocation.workspace_id:
        raise TaskBasisUnavailable('Original basis workspace binding differs')
    return operation, task, steps[1], allocation


def _active(original, parent, *, step_status):
    operation, task, step, allocation = original
    if (
        operation['status'] != 'RUNNING'
        or step['status'] != step_status
        or task['status'] != 'PENDING'
        or task['phase'] != 'PREPARING'
        or task['control_generation'] != allocation.generation
        or task['stop_requested_at'] is not None
        or parent.verify() != allocation.parent
    ):
        raise TaskBasisUnavailable('Original basis preparation is fenced')


def _binding(original, originals):
    allocation = original[3]
    return {
        'operation_id': allocation.operation_id,
        'task_id': allocation.task_id,
        'generation': allocation.generation,
        'workspace_id': allocation.workspace_id,
        'nonce': allocation.nonce,
        'source_sha256': basis_digest(basis_source(originals)),
        'document_count': len(originals),
    }


def _end_unready(runtime, operation_id, *, known_missing=False):
    with runtime.database.transaction(write=True) as connection:
        operation, task, step, _ = _original_basis(connection, operation_id)
        expected = 'PENDING' if known_missing else 'RUNNING'
        if operation['status'] != 'RUNNING' or step['status'] != expected:
            return
        now = max(
            operation_time(None),
            task['updated_at'],
            step['last_observed_at'] or operation['started_at'],
        )
        if known_missing:
            connection.execute(
                """UPDATE code_operation_steps SET status='FAILED',started_at=?,ended_at=?,
                   last_observed_at=? WHERE operation_id=? AND step_no=2""",
                (now, now, now, operation_id),
            )
            connection.execute(
                """UPDATE code_operations SET status='FAILED',failure_code='CONTENT_NOT_READY',
                   ended_at=? WHERE id=?""",
                (now, operation_id),
            )
        else:
            connection.execute(
                """UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=?
                   WHERE operation_id=? AND step_no=2""",
                (now, operation_id),
            )
            connection.execute(
                "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
                (operation_id,),
            )


def advance_start_basis(runtime, parent, *, cancelled):
    """Return whether one original step was considered. Never resend an interrupted write."""
    if cancelled():
        return False
    runtime.commands()._owned()
    with runtime.database.transaction() as connection:
        candidate = _candidate(connection)
        if candidate is None:
            return False
        operation_id = candidate['id']
        original = _original_basis(connection, operation_id)
        previous = original[2]['status']
        try:
            _active(original, parent, step_status=previous)
        except TaskBasisUnavailable:
            active = False
        else:
            active = True
        originals = None
        if active:
            try:
                _, design = read_task_basis(connection, original[1], include_originals=True)
                originals = design.originals
            except TaskBasisUnavailable:
                pass
    if not active or originals is None:
        _end_unready(runtime, operation_id, known_missing=previous == 'PENDING')
        return True

    binding = _binding(original, originals)
    encoded = canonical_input(binding)
    if previous == 'PENDING':
        with runtime.database.transaction(write=True) as connection:
            current = _original_basis(connection, operation_id)
            _active(current, parent, step_status='PENDING')
            if current[2]['external_identity'] is not None:
                raise StorageUnavailable('Original pending basis already has an allocation')
            now = max(operation_time(None), current[0]['started_at'], current[1]['updated_at'])
            connection.execute(
                """UPDATE code_operation_steps SET status='RUNNING',external_identity=?,
                   started_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2""",
                (encoded, now, now, operation_id),
            )

    def check_active():
        if cancelled():
            raise TaskBasisUnavailable('Original basis preparation was interrupted')
        with runtime.database.transaction() as connection:
            current = _original_basis(connection, operation_id)
            _active(current, parent, step_status='RUNNING')
            if current[2]['external_identity'] != encoded:
                raise TaskBasisUnavailable('Original basis source no longer matches its allocation')

    try:
        check_active()
        seal = (
            publish_basis_package(parent, binding, originals, check_active)
            if previous == 'PENDING'
            else observe_basis_seal(parent, binding)
        )
        read_basis_package(parent, binding, seal, check_active)
        with runtime.database.transaction(write=True) as connection:
            current = _original_basis(connection, operation_id)
            _active(current, parent, step_status='RUNNING')
            if current[2]['external_identity'] != encoded or cancelled():
                raise TaskBasisUnavailable('Original basis publication is fenced')
            now = max(operation_time(None), current[2]['started_at'])
            connection.execute(
                """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,
                   ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=2""",
                (
                    canonical_input({'seal': seal, 'document_count': len(originals)}),
                    now,
                    now,
                    operation_id,
                ),
            )
    except (TypeError, ValueError, KeyError) as error:
        _end_unready(runtime, operation_id)
        raise TaskBasisUnavailable('Original basis package metadata is unavailable') from error
    except Exception:
        _end_unready(runtime, operation_id)
        raise
    return True


def read_prepared_basis_document(runtime, parent, operation_id, document_id):
    """Private read for the current original execution owner, never a public file endpoint."""
    strict_integer(operation_id, 'operation_id')
    strict_integer(document_id, 'document_id')
    runtime.commands()._owned()

    def state():
        with runtime.database.transaction() as connection:
            original = _original_basis(connection, operation_id)
            _active(original, parent, step_status='SUCCEEDED')
            step = original[2]
            return step['external_identity'], step['result_ref']

    binding, result = state()

    def check_active():
        if state() != (binding, result):
            raise TaskBasisUnavailable('Original prepared basis changed')

    return read_basis_package(
        parent,
        strict_json_object(binding),
        strict_json_object(result)['seal'],
        check_active,
        document_id=document_id,
    )
