"""Advance the original RESTORE_WORKSPACE on the existing native owner thread."""

from dataclasses import asdict, dataclass, field
from uuid import uuid4

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .task_budget import start_budget_versions
from .task_start import _check_start_readiness, original_start_steps
from .workspace_materialization import PublishedWorkspace, WorkspaceMaterializationError, _same_file


@dataclass(frozen=True)
class WorkspaceAllocation:
    operation_id: int
    task_id: int
    generation: int
    snapshot_id: int
    workspace_id: int
    nonce: str = field(repr=False)
    parent: FileIdentity = field(repr=False)

    @property
    def key(self):
        return 'working-' + self.nonce

    @property
    def stage_record(self):
        return self.nonce + '.workspace-stage.json'

    def external_identity(self):
        return canonical_input(
            {
                'workspace_id': self.workspace_id,
                'snapshot_id': self.snapshot_id,
                'nonce': self.nonce,
                'parent': asdict(self.parent),
                'stage_record': self.stage_record,
            }
        )


def _queued(connection):
    return connection.execute(
        """SELECT o.* FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
           WHERE o.operation_type='START' AND o.status='PENDING' AND t.status='PENDING'
             AND t.stop_requested_at IS NULL ORDER BY o.id LIMIT 1"""
    ).fetchone()


def workspace_start_pending(runtime):
    with runtime.database.transaction() as connection:
        return _queued(connection) is not None


def reserve_workspace(runtime, parent):
    runtime.commands()._owned()
    root = parent.verify()
    with runtime.database.transaction(write=True) as connection:
        operation = _queued(connection)
        if operation is None:
            return None
        _, steps = original_start_steps(connection, operation)
        task = connection.execute(
            'SELECT * FROM code_tasks WHERE id=?', (operation['task_id'],)
        ).fetchone()
        if (
            task['control_generation'] != operation['control_generation']
            or not start_budget_versions(connection, task, operation, offset=1)
            or task['phase'] != 'PREPARING'
            or task['workspace_id'] is not None
            or task['active_session_id'] is not None
            or task['started_at'] is not None
            or operation['started_at'] is not None
            or operation['ended_at'] is not None
            or any(
                step['status'] != 'PENDING'
                or any(
                    step[key] is not None
                    for key in (
                        'external_identity',
                        'result_ref',
                        'started_at',
                        'ended_at',
                        'last_observed_at',
                    )
                )
                for step in steps
            )
        ):
            raise StorageUnavailable('Original pending workspace scope differs')
        _check_start_readiness(connection, runtime.catalog, task, True)
        identity = entity_id(connection, EntityKind.CODE_WORKSPACE)
        allocation = WorkspaceAllocation(
            operation['id'],
            task['id'],
            task['control_generation'],
            task['base_snapshot_id'],
            identity,
            uuid4().hex,
            root,
        )
        now = operation_time(None)
        if now < task['updated_at']:
            raise StorageUnavailable('Workspace allocation clock is behind the task')
        connection.execute(
            """INSERT INTO code_workspaces(
               id,task_id,base_snapshot_id,private_location_key,status,created_at)
               VALUES(?,?,?,?,'PREPARING',?)""",
            (identity, task['id'], task['base_snapshot_id'], allocation.key, now),
        )
        connection.execute(
            "UPDATE code_operations SET status='RUNNING',started_at=? WHERE id=?",
            (now, operation['id']),
        )
        connection.execute(
            """UPDATE code_operation_steps SET status='RUNNING',external_identity=?,
               started_at=?,last_observed_at=? WHERE operation_id=? AND step_no=1""",
            (allocation.external_identity(), now, now, operation['id']),
        )
        return allocation


def _original_rows(connection, allocation):
    operation = connection.execute(
        'SELECT * FROM code_operations WHERE id=?', (allocation.operation_id,)
    ).fetchone()
    task = connection.execute(
        'SELECT * FROM code_tasks WHERE id=?', (allocation.task_id,)
    ).fetchone()
    workspace = connection.execute(
        'SELECT * FROM code_workspaces WHERE id=?', (allocation.workspace_id,)
    ).fetchone()
    step = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? AND step_no=1',
        (allocation.operation_id,),
    ).fetchone()
    if (
        any(row is None for row in (operation, task, workspace, step))
        or operation['task_id'] != allocation.task_id
        or operation['operation_type'] != 'START'
        or operation['control_generation'] != allocation.generation
        or task['base_snapshot_id'] != allocation.snapshot_id
        or workspace['task_id'] != allocation.task_id
        or workspace['base_snapshot_id'] != allocation.snapshot_id
        or workspace['private_location_key'] != allocation.key
        or step['external_identity'] != allocation.external_identity()
    ):
        raise StorageUnavailable('Original allocated workspace differs')
    return operation, task, workspace, step


def _require_active(rows, allocation):
    operation, task, workspace, step = rows
    if (
        operation['status'] != 'RUNNING'
        or step['status'] != 'RUNNING'
        or workspace['status'] != 'PREPARING'
        or task['status'] != 'PENDING'
        or task['phase'] != 'PREPARING'
        or task['control_generation'] != allocation.generation
        or task['stop_requested_at'] is not None
        or task['workspace_id'] is not None
        or task['active_session_id'] is not None
        or task['started_at'] is not None
    ):
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_START_FENCED')


def _mark_unknown(connection, operation_id, workspace_id):
    at = operation_time(None)
    connection.execute(
        "UPDATE code_workspaces SET status='UNKNOWN' WHERE id=? AND status='PREPARING'",
        (workspace_id,),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=MAX(last_observed_at,?)
           WHERE operation_id=? AND step_no=1 AND status='RUNNING'""",
        (at, operation_id),
    )
    connection.execute(
        """UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN'
           WHERE id=? AND status='RUNNING'""",
        (operation_id,),
    )


def workspace_allocation(operation, step):
    binding = strict_json_object(step['external_identity'])
    return WorkspaceAllocation(
        operation['id'],
        operation['task_id'],
        operation['control_generation'],
        binding['snapshot_id'],
        binding['workspace_id'],
        binding['nonce'],
        FileIdentity(**binding['parent']),
    )


def recover_workspace_starts(runtime):
    """A retired dispatcher cannot recreate or publish an uncertain original allocation."""
    runtime.commands()._owned()
    with runtime.database.transaction(write=True) as connection:
        rows = connection.execute(
            """SELECT o.* FROM code_operations o
               JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_no=1
               WHERE o.resource_kind='TASK' AND o.operation_type='START'
               AND o.status='RUNNING' AND s.status='RUNNING'"""
        ).fetchall()
        for operation in rows:
            _, steps = original_start_steps(connection, operation)
            allocation = workspace_allocation(operation, steps[0])
            _original_rows(connection, allocation)
            _mark_unknown(connection, operation['id'], allocation.workspace_id)


def _save_ready(runtime, parent, allocation, stage, published, check_active):
    if (
        type(published) is not PublishedWorkspace
        or stage is None
        or published.snapshot_id != allocation.snapshot_id
        or published.location_key != allocation.key
        or not _same_file(published.directory, stage)
    ):
        raise StorageUnavailable('Original workspace publication differs')
    manifest = canonical_input({'entries': [asdict(entry) for entry in published.entries]}).encode(
        'utf-8'
    )
    check_active()
    with PrivateRecordAppend(
        parent, allocation.nonce + '.workspace-tree.json', manifest, max_record_bytes=len(manifest)
    ) as record:
        check_active()
        tree = record.publish()
    with runtime.database.transaction(write=True) as connection:
        rows = _original_rows(connection, allocation)
        _require_active(rows, allocation)
        task = rows[1]
        now = operation_time(None)
        if (
            now < max(task['updated_at'], rows[3]['started_at'])
            or task['state_version'] >= MAX_SAFE_INTEGER - 2
        ):
            raise StorageUnavailable('Workspace publication chronology or capacity differs')
        result = canonical_input(
            {
                'workspace_id': allocation.workspace_id,
                'directory': asdict(published.directory),
                'content_sha256': tree.sha256,
                'tree_record': asdict(tree),
            }
        )
        connection.execute(
            "UPDATE code_workspaces SET status='READY',ready_at=? WHERE id=?",
            (now, allocation.workspace_id),
        )
        connection.execute(
            """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,
               last_observed_at=? WHERE operation_id=? AND step_no=1""",
            (result, now, now, allocation.operation_id),
        )
        connection.execute(
            'UPDATE code_tasks SET workspace_id=?,state_version=state_version+1,updated_at=? WHERE id=?',
            (allocation.workspace_id, now, allocation.task_id),
        )


def advance_workspace_start(runtime, actor, frames, parent, *, cancelled):
    if cancelled():
        return
    allocation = reserve_workspace(runtime, parent)
    if allocation is None:
        return
    stage = None

    def check_active():
        if cancelled():
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_START_CANCELLED')
        with runtime.database.transaction() as connection:
            _require_active(_original_rows(connection, allocation), allocation)

    def record_stage(identity, query_id):
        nonlocal stage
        check_active()
        raw = canonical_input(
            {
                'operation_id': allocation.operation_id,
                'task_id': allocation.task_id,
                'generation': allocation.generation,
                'workspace_id': allocation.workspace_id,
                'nonce': allocation.nonce,
                'baseline_query_id': query_id,
                'directory': asdict(identity),
            }
        ).encode('utf-8')
        receipt = PrivateRecordAppend(parent, allocation.stage_record, raw, max_record_bytes=4096)
        try:
            receipt.publish()
        finally:
            receipt.close()
        stage = identity

    try:
        check_active()
        published = actor.restore_snapshot(
            allocation.snapshot_id,
            frames,
            parent=parent,
            nonce=allocation.nonce,
            check_active=check_active,
            cancelled=cancelled,
            record_stage=record_stage,
        )
        _save_ready(runtime, parent, allocation, stage, published, check_active)
    except Exception:
        with runtime.database.transaction(write=True) as connection:
            operation, _, _, step = _original_rows(connection, allocation)
            # If a commit acknowledgement was lost, keep the actual saved fact.
            if operation['status'] == 'RUNNING' and step['status'] == 'RUNNING':
                _mark_unknown(connection, allocation.operation_id, allocation.workspace_id)
        raise
