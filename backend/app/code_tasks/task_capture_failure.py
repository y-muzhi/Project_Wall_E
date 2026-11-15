"""Close a fresh, unsealed local capacity failure only after owned calls ended."""

from backend.app.infrastructure.content_manifest import ContentManifestError
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.identifiers import increment, require_write_transaction
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_task_workspace_lease import WorkspaceWriteError
from backend.app.shared.command_execution import operation_time

from .task_candidate_commit import capture_task_current, load_candidate_capture

_MANIFEST_CAPACITY = frozenset(
    (
        'CONTENT_FILE_LIMIT_EXCEEDED',
        'CONTENT_TOTAL_BYTES_EXCEEDED',
        'CONTENT_FILE_COUNT_EXCEEDED',
        'CONTENT_MANIFEST_BYTES_EXCEEDED',
    )
)


def local_capacity_failure(error):
    seen = set()
    known_capacity = False
    while error is not None:
        if id(error) in seen or getattr(error, 'retained_owner', None) is not None:
            return False
        seen.add(id(error))
        manifest_limit = (
            isinstance(error, ContentManifestError) and error.reason in _MANIFEST_CAPACITY
        )
        file_limit = (
            isinstance(error, ConfigReadError) and error.reason == 'CONFIG_READ_BYTES_EXCEEDED'
        )
        tree_limit = (
            isinstance(error, WorkspaceWriteError)
            and str(error) == 'ORIGINAL_WORKSPACE_TREE_LIMIT_EXCEEDED'
        )
        known_capacity = known_capacity or manifest_limit or file_limit or tree_limit
        error = error.__cause__ or error.__context__
    return known_capacity


def fail_unsealed_capture(connection, operation_id):
    require_write_transaction(connection)
    prepared, task, operation, steps = load_candidate_capture(connection, operation_id)
    if (
        operation['status'] not in ('PENDING', 'RUNNING')
        or not capture_task_current(prepared, task)
        or steps[0]['status'] != 'SUCCEEDED'
        or steps[1]['status'] != 'RUNNING'
        or steps[1]['started_at'] is None
        or steps[1]['result_ref'] is not None
        or any(step['status'] != 'PENDING' or step['result_ref'] is not None for step in steps[2:])
        or connection.execute(
            'SELECT 1 FROM code_candidates WHERE capture_operation_id=?',
            (operation_id,),
        ).fetchone()
        is not None
        or connection.execute(
            """SELECT 1 FROM code_commands WHERE task_id=? AND
               (status IN ('PENDING','RUNNING','UNKNOWN') OR
                (operation_id=? AND ended_at IS NULL)) LIMIT 1""",
            (task['id'], operation_id),
        ).fetchone()
        is not None
    ):
        return False
    at = max(operation_time(None), task['updated_at'], steps[1]['started_at'])
    connection.execute(
        """UPDATE code_operation_steps SET status='FAILED',ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no=2 AND status='RUNNING'""",
        (at, at, operation_id),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='CANCELLED',ended_at=?,last_observed_at=?
           WHERE operation_id=? AND step_no IN (3,4) AND status='PENDING'""",
        (at, at, operation_id),
    )
    connection.execute(
        """UPDATE code_operations SET status='FAILED',failure_code='CONTENT_NOT_READY',
           ended_at=? WHERE id=?""",
        (at, operation_id),
    )
    changed = connection.execute(
        """UPDATE code_tasks SET state_version=?,updated_at=? WHERE id=? AND state_version=?
           AND control_generation=? AND stop_requested_at IS NULL""",
        (
            increment(task['state_version']),
            at,
            task['id'],
            task['state_version'],
            prepared.binding.control_generation,
        ),
    )
    if changed.rowcount != 1:
        raise StorageUnavailable('Original capacity failure was fenced')
    return True
