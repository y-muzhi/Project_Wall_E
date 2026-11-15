"""Prove the Coding role prefix from the original handoff operations and facts."""

from dataclasses import dataclass
from hashlib import sha256

from backend.app.infrastructure.check_runner_bundle import valid_sha256
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import CapacityExhausted, increment
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import (
    strict_enum,
    strict_integer,
    strict_json_loads,
    strict_json_object,
)

from .operation_protocol import operation_steps
from .repository_operations import _time
from .task_session_replacement import replacement_origin

ROLES = ('BACKEND', 'FRONTEND', 'INTEGRATION')
HANDOFF = 'HANDOFF_ROLE'
STEPS = operation_steps('CODING', HANDOFF)
_UNRESOLVED = ('PENDING', 'RUNNING', 'UNKNOWN')


class RoleChainUnavailable(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RoleChain:
    session_id: int
    stages: tuple[str, ...]
    operations: tuple[int, ...]

    @property
    def role(self):
        return self.stages[-1]

    @property
    def backend_handoff(self):
        return self.operations[0] if self.operations else None

    @property
    def frontend_handoff(self):
        return self.operations[1] if len(self.operations) == 2 else None


def _session(connection, task_id, session_id):
    return connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (session_id, task_id),
    ).fetchone()


def _fixed(operation):
    value = exact(
        strict_json_object(operation['fixed_input']),
        (
            'source_session_id',
            'candidate_id',
            'verification_id',
            'target_role',
            'expected_state_version',
        ),
    )
    for field in ('source_session_id', 'candidate_id', 'verification_id', 'expected_state_version'):
        strict_integer(value[field], field)
    strict_enum(value['target_role'], 'target_role', ROLES[1:])
    if (
        operation['fixed_input'] != canonical_input(value)
        or operation['expected_state_version'] != value['expected_state_version']
        or operation['session_id'] != value['source_session_id']
    ):
        raise ValueError('Original role handoff intent differs')
    return value


def _results(connection, operation):
    steps = connection.execute(
        'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
        (operation['id'],),
    ).fetchall()
    created, start, end = (operation[key] for key in ('created_at', 'started_at', 'ended_at'))
    for instant in (created, start, end):
        _time(instant, nullable=False)
    if (
        created > start
        or start > end
        or tuple((row['step_no'], row['step_type']) for row in steps) != tuple(enumerate(STEPS, 1))
    ):
        raise ValueError('Original role handoff operation chronology differs')
    values = []
    previous = start
    for step in steps:
        first, last = step['started_at'], step['ended_at']
        _time(first, nullable=False)
        _time(last, nullable=False)
        if (
            step['status'] != 'SUCCEEDED'
            or step['fixed_input'] != operation['fixed_input']
            or not previous <= first <= last <= end
        ):
            raise ValueError('Original role handoff step differs')
        values.append(strict_json_object(step['result_ref']))
        previous = last
    return values


def _check_saved_verification(connection, operation, candidate, verification_id, stages, previous):
    verification = connection.execute(
        """SELECT v.*,o.status AS operation_status,o.operation_type AS origin_type,
                  o.control_generation AS origin_generation,
                  s.status AS check_status,s.result_ref AS check_result
           FROM code_verifications v JOIN code_operations o ON o.id=v.operation_id AND o.task_id=v.task_id
           JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_type='CHECK'
           WHERE v.id=? AND v.task_id=? AND v.candidate_id=? AND v.owner_kind='CODING'""",
        (verification_id, operation['task_id'], candidate['id']),
    ).fetchone()
    if (
        verification is None
        or verification['purpose'] != 'HANDOFF'
        or verification['role'] != stages[-1]
        or tuple(strict_json_loads(verification['scope_stages'])) != stages
        or verification['backend_handoff_operation_id'] != (previous[0] if previous else None)
        or verification['frontend_handoff_operation_id'] is not None
        or verification['status'] != 'FINISHED'
        or any(
            verification[field] != 'VERIFIED'
            for field in ('stop_status', 'cleanup_status', 'source_integrity_status')
        )
        or verification['origin_type'] not in ('CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE')
        or verification['operation_status'] != 'SUCCEEDED'
        or verification['check_status'] != 'SUCCEEDED'
        or strict_json_object(verification['check_result']) != {'verification_id': verification_id}
        or verification['origin_generation'] != operation['control_generation']
        or not verification['ended_at']
        or verification['ended_at'] > operation['created_at']
    ):
        raise ValueError('Original role handoff verification differs')
    _time(verification['ended_at'], nullable=False)
    items = connection.execute(
        'SELECT check_id,required,result,evidence_kind FROM code_verification_items WHERE verification_id=? ORDER BY id',
        (verification_id,),
    ).fetchall()
    if (
        not items
        or [row['check_id'] for row in items]
        != strict_json_loads(verification['selected_check_ids'])
        or any(row['required'] and row['result'] != 'PASSED' for row in items)
        or not any(row['required'] and row['evidence_kind'] == 'CONTENT_INTEGRITY' for row in items)
    ):
        raise ValueError('Original role handoff required evidence differs')


def _handoff_target(connection, operation, stages, previous, previous_session, previous_end):
    fixed = _fixed(operation)
    quiet, revoked, check, created, sent = _results(connection, operation)
    exact(quiet, ('quiesce_observation_id', 'proof'))
    observation_id = strict_integer(quiet['quiesce_observation_id'], 'quiesce_observation_id')
    proof = exact(
        quiet['proof'], ('turn', 'guard_receipt_sha256', 'active_process_count', 'workspace')
    )
    turn = exact(
        proof['turn'], ('session_id', 'trigger_message_id', 'assistant_message_id', 'outcome')
    )
    workspace = exact(
        proof['workspace'],
        ('canonical_path', 'volume_serial', 'file_id', 'is_directory', 'filesystem'),
    )
    digest = sha256(canonical_input(proof).encode('utf-8')).hexdigest()
    evidence_ref = f'sqlite:code_operation_steps/{operation["id"]}/1#sha256={digest}'
    task_id = operation['task_id']
    generation = operation['control_generation']
    source_id = fixed['source_session_id']
    source = _session(connection, task_id, source_id)
    target_id = strict_integer(created['session_id'], 'session_id')
    target = _session(connection, task_id, target_id)
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (fixed['candidate_id'], task_id),
    ).fetchone()
    source_origin = replacement_origin(connection, task_id, source_id)
    observed = connection.execute(
        """SELECT * FROM code_runtime_observations WHERE id=? AND task_id=? AND operation_id=?
           AND control_generation=? AND kind='QUIESCE' AND result='VERIFIED'""",
        (observation_id, task_id, operation['id'], generation),
    ).fetchone()
    if (
        source is None
        or target is None
        or source_id == target_id
        or (
            previous_session is not None
            and source_origin != replacement_origin(connection, task_id, previous_session)
        )
        or (previous_end is not None and operation['created_at'] < previous_end)
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != task_id
        or operation['testing_task_id'] is not None
        or source['status'] != 'RETIRED'
        or source['role'] != stages[-1]
        or source['control_generation'] != generation
        or source['instance_id'] != target['instance_id']
        or strict_json_object(source['model_window'])['state'] != 'RETIRED'
        or strict_json_object(source['model_window'])['native_trigger_message_id']
        != turn['trigger_message_id']
        or source['native_session_id'] != _identifier(turn['session_id'], 'ses')
        or not _identifier(turn['trigger_message_id'], 'msg')
        or not _identifier(turn['assistant_message_id'], 'msg')
        or turn['outcome'] not in ('COMPLETED', 'CANCELLED')
        or not valid_sha256(proof['guard_receipt_sha256'])
        or type(proof['active_process_count']) is not int
        or proof['active_process_count'] != 1
        or workspace['is_directory'] is not True
        or workspace['filesystem'] != 'NTFS'
        or target['role'] != fixed['target_role']
        or target['role'] != ROLES[len(stages)]
        or target['control_generation'] != increment(generation)
        or candidate is None
        or candidate['role'] != source['role']
        or candidate['control_generation'] != generation
        or candidate['created_at'] > operation['created_at']
        or observed is None
        or observed['instance_id'] != source['instance_id']
        or observed['evidence_ref'] != evidence_ref
        or not operation['started_at'] <= observed['observed_at'] <= operation['ended_at']
        or not operation['created_at'] <= target['created_at'] <= operation['ended_at']
        or revoked != {'session_id': source_id, 'control_generation': target['control_generation']}
        or check != {'verification_id': fixed['verification_id']}
    ):
        raise ValueError('Original role handoff scope differs')
    native_session_id = _identifier(created['native_session_id'], 'ses')
    native_message_id = _identifier(sent['native_message_id'], 'msg')
    if (
        created != {'session_id': target_id, 'native_session_id': native_session_id}
        or sent != {'session_id': target_id, 'native_message_id': native_message_id}
        or target['native_session_id'] != native_session_id
        or target['native_message_id'] != native_message_id
        or source['native_session_id'] == native_session_id
        or not target['gateway_credential_ref']
    ):
        raise ValueError('Original role handoff native acceptance differs')
    _check_saved_verification(
        connection, operation, candidate, fixed['verification_id'], stages, previous
    )
    return target


def current_role_chain(connection, task, *, original_handoff_id=0):
    session = _session(connection, task['id'], task['active_session_id'])
    if (
        session is None
        or session['status'] != 'ACTIVE'
        or session['role'] not in ROLES
        or session['role'] != task['phase']
        or session['control_generation'] != task['control_generation']
    ):
        raise RoleChainUnavailable('SESSION_NOT_CURRENT')
    operations = connection.execute(
        """SELECT * FROM code_operations WHERE task_id=? AND id<>? AND operation_type='HANDOFF_ROLE'
           AND status IN ('PENDING','RUNNING','UNKNOWN','SUCCEEDED') ORDER BY id""",
        (task['id'], original_handoff_id),
    ).fetchall()
    if any(row['status'] in _UNRESOLVED for row in operations):
        raise RoleChainUnavailable('ROLE_CHAIN_UNKNOWN')
    target_index = ROLES.index(session['role'])
    if len(operations) != target_index:
        raise RoleChainUnavailable('ROLE_CHAIN_INCOMPLETE')
    references = ()
    previous_session = None
    previous_end = None
    try:
        for index, operation in enumerate(operations, 1):
            target = _handoff_target(
                connection, operation, ROLES[:index], references, previous_session, previous_end
            )
            previous_session = target['id']
            previous_end = operation['ended_at']
            references = (*references, operation['id'])
        if previous_session is not None and previous_session != replacement_origin(
            connection, task['id'], session['id']
        ):
            raise ValueError('Original current role session lineage differs')
    except (TypeError, KeyError, ValueError, CapacityExhausted, TaskExecutionError) as error:
        raise RoleChainUnavailable('ROLE_CHAIN_INCOMPLETE') from error
    return RoleChain(session['id'], ROLES[: target_index + 1], references)
