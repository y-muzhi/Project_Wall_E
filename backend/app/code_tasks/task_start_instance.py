"""The original business START_INSTANCE step and its durable instance allocation."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_hex

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.opencode_binary import VERSION
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .task_basis import TaskBasisUnavailable
from .task_budget import start_budget_versions
from .task_start import original_start_steps
from .task_start_basis import _active, _original_basis
from .task_start_conditions import _limits


@dataclass(frozen=True)
class StartInstanceClaim:
    instance_id: int
    operation_id: int
    nonce: str
    task_id: int
    generation: int
    state_version: int
    profile_id: int

    def reference(self):
        return canonical_input(
            {
                'instance_id': self.instance_id,
                'operation_id': self.operation_id,
                'nonce': self.nonce,
                'task_id': self.task_id,
                'control_generation': self.generation,
                'state_version': self.state_version,
                'effective_profile_version_id': self.profile_id,
            }
        )


@dataclass(frozen=True)
class StartInstanceInput:
    claim: StartInstanceClaim
    allocation: object
    workspace_receipt: str
    basis_binding: dict
    basis_seal: dict
    limits: dict


@dataclass(frozen=True)
class ReadyInstanceEvidence:
    process_identity: dict
    runtime_binding: dict
    connection_ref: str
    native_storage_ref: str

    @classmethod
    def from_running(cls, running, *, launch_input, profile, credential_ref, scope):
        native = running['process_identity']
        if (
            running['process_state'] != 'RUNNING'
            or running['job_ref'] != launch_input['job_ref']
            or running['job_ref'] != profile['job_ref']
            or credential_ref != launch_input['credential_ref']
            or native['is_appcontainer'] is not True
            or native['is_elevated'] is not False
            or native['is_lpac'] is False
        ):
            raise TaskExecutionError('ORIGINAL_INSTANCE_RUNTIME_EVIDENCE_DIFFERS')
        created = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=int(native['creation_time_hex'], 16) // 10
        )
        return cls(
            {
                'pid': native['pid'],
                'created_at': created.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                'ownership_ref': running['receipt_sha256'],
            },
            {
                'runtime_policy_version': 'WIN20-ISOLATION-1',
                'run_kind': 'TASK',
                'guard_run_ref': running['resource_ref'],
                'appcontainer_profile_ref': profile['profile_sha256'],
                'job_refs': [running['job_ref']],
                'manifest_ref': launch_input['file_evidence_sha256'],
            },
            credential_ref,
            scope.key,
        )


def _candidate(connection):
    return connection.execute(
        """SELECT o.id, instance.status AS step_status
           FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
           JOIN code_operation_steps conditions ON conditions.operation_id=o.id AND conditions.step_no=3
           JOIN code_operation_steps instance ON instance.operation_id=o.id AND instance.step_no=4
           WHERE o.resource_kind='TASK' AND o.operation_type='START' AND o.status='RUNNING'
           AND conditions.status='SUCCEEDED'
           AND (instance.status='RUNNING' OR (instance.status='PENDING'
             AND t.status='PENDING' AND t.phase='PREPARING' AND t.stop_requested_at IS NULL))
           ORDER BY (instance.status='RUNNING') DESC,o.id LIMIT 1"""
    ).fetchone()


def _inputs(connection, parent, operation_id, step_status):
    original = _original_basis(connection, operation_id)
    try:
        _active(original, parent, step_status='SUCCEEDED')
    except TaskBasisUnavailable as error:
        raise TaskExecutionError('ORIGINAL_INSTANCE_STEP_FENCED') from error
    operation, task, basis, allocation = original
    _, steps = original_start_steps(connection, operation)
    conditions = strict_json_object(steps[2]['result_ref'])
    instance = steps[3]
    if (
        steps[2]['status'] != 'SUCCEEDED'
        or conditions.get('fixed_content_verified') is not True
        or conditions.get('capability_codes') != []
        or conditions.get('runtime_launch_admission') is not True
        or instance['status'] != step_status
        or not start_budget_versions(connection, task, operation, offset=2)
        or any(step['status'] != 'PENDING' for step in steps[4:])
    ):
        raise TaskExecutionError('ORIGINAL_INSTANCE_STEP_FENCED')
    return operation, task, basis, allocation, steps


def _claim(connection, parent, operation_id):
    operation, task, basis, allocation, steps = _inputs(connection, parent, operation_id, 'PENDING')
    instance = steps[3]
    if any(
        instance[key] is not None
        for key in ('external_identity', 'result_ref', 'started_at', 'ended_at', 'last_observed_at')
    ):
        raise StorageUnavailable('Original pending START_INSTANCE already has evidence')
    allocated = entity_id(connection, EntityKind.MANAGED_INSTANCE)
    claim = StartInstanceClaim(
        allocated,
        operation_id,
        token_hex(16),
        task['id'],
        task['control_generation'],
        operation['expected_state_version'] + 2,
        task['execution_profile_version_id'],
    )
    now = max(operation_time(None), task['updated_at'], steps[2]['ended_at'])
    connection.execute(
        """INSERT INTO code_instances(id,task_id,workspace_id,executor_version,control_generation,
           effective_profile_version_id,status,created_at) VALUES(?,?,?,?,?,?,'STARTING',?)""",
        (
            allocated,
            claim.task_id,
            allocation.workspace_id,
            VERSION,
            claim.generation,
            claim.profile_id,
            now,
        ),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='RUNNING',external_identity=?,started_at=?,
           last_observed_at=? WHERE operation_id=? AND step_no=4""",
        (claim.reference(), now, now, operation['id']),
    )
    return StartInstanceInput(
        claim,
        allocation,
        steps[0]['result_ref'],
        strict_json_object(basis['external_identity']),
        strict_json_object(basis['result_ref'])['seal'],
        _limits(connection, claim.profile_id),
    )


def _check_claim(connection, parent, original):
    claim = original.claim
    operation, _, basis, allocation, steps = _inputs(
        connection, parent, claim.operation_id, 'RUNNING'
    )
    row = connection.execute(
        'SELECT * FROM code_instances WHERE id=?', (claim.instance_id,)
    ).fetchone()
    if (
        steps[3]['external_identity'] != claim.reference()
        or row is None
        or row['status'] != 'STARTING'
        or row['task_id'] != claim.task_id
        or row['workspace_id'] != allocation.workspace_id
        or row['control_generation'] != claim.generation
        or row['effective_profile_version_id'] != claim.profile_id
        or operation['expected_state_version'] + 2 != claim.state_version
        or allocation != original.allocation
        or steps[0]['result_ref'] != original.workspace_receipt
        or strict_json_object(basis['external_identity']) != original.basis_binding
        or strict_json_object(basis['result_ref'])['seal'] != original.basis_seal
    ):
        raise TaskExecutionError('ORIGINAL_INSTANCE_CLAIM_DIFFERS')
    return steps[3]


def _ready(connection, parent, original, evidence):
    step = _check_claim(connection, parent, original)
    if type(evidence) is not ReadyInstanceEvidence:
        raise TaskExecutionError('ORIGINAL_INSTANCE_RUNTIME_EVIDENCE_REQUIRED')
    claim = original.claim
    now = max(operation_time(None), step['last_observed_at'])
    connection.execute(
        """UPDATE code_instances SET status='READY',process_identity=?,runtime_binding=?,
           connection_ref=?,native_storage_ref=?,ready_at=? WHERE id=?""",
        (
            canonical_input(evidence.process_identity),
            canonical_input(evidence.runtime_binding),
            evidence.connection_ref,
            evidence.native_storage_ref,
            now,
            claim.instance_id,
        ),
    )
    connection.execute(
        """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,
           last_observed_at=? WHERE operation_id=? AND step_no=4""",
        (canonical_input({'instance_id': claim.instance_id}), now, now, claim.operation_id),
    )


def _unknown(connection, operation_id):
    row = connection.execute(
        """SELECT s.external_identity,s.last_observed_at,o.task_id,o.control_generation
           FROM code_operation_steps s JOIN code_operations o ON o.id=s.operation_id
           WHERE s.operation_id=? AND s.step_no=4 AND s.status='RUNNING' AND o.status='RUNNING'""",
        (operation_id,),
    ).fetchone()
    if row is None:
        return
    reference = strict_json_object(row['external_identity'])
    if (
        reference['operation_id'] != operation_id
        or reference['task_id'] != row['task_id']
        or reference['control_generation'] != row['control_generation']
        or connection.execute(
            """UPDATE code_instances SET status='UNKNOWN'
               WHERE id=? AND task_id=? AND control_generation=? AND status='STARTING'""",
            (reference['instance_id'], row['task_id'], row['control_generation']),
        ).rowcount
        != 1
    ):
        raise StorageUnavailable('Original START_INSTANCE allocation differs')
    now = max(operation_time(None), row['last_observed_at'])
    connection.execute(
        """UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=?
           WHERE operation_id=? AND step_no=4""",
        (now, operation_id),
    )
    connection.execute(
        "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
        (operation_id,),
    )


def advance_start_instance(runtime, parent, *, cancelled, driver=None):
    if cancelled():
        return False
    runtime.commands()._owned()
    with runtime.database.transaction(write=True) as connection:
        candidate = _candidate(connection)
        if candidate is None:
            return False
        operation_id = candidate['id']
        if candidate['step_status'] == 'RUNNING':
            _unknown(connection, operation_id)
            return True
        if driver is None:
            return False
        original = _claim(connection, parent, operation_id)

    def checkpoint():
        if cancelled():
            raise TaskExecutionError('ORIGINAL_INSTANCE_START_CANCELLED')
        with runtime.database.transaction() as connection:
            _check_claim(connection, parent, original)

    try:
        checkpoint()
        evidence = driver.start(original, checkpoint, cancelled=cancelled)
        checkpoint()
        with runtime.database.transaction(write=True) as connection:
            _ready(connection, parent, original, evidence)
    except Exception as error:
        retained = getattr(error, 'retained_owner', None)
        try:
            with runtime.database.transaction(write=True) as connection:
                _unknown(connection, operation_id)
        finally:
            if retained is None:
                driver.fence_failed(operation_id)
        if retained is not None or not isinstance(error, (LaunchOutcomeUnknown, OSError)):
            raise
    return True
