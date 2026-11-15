"""Keep a cancelled repair's actual quiet scope usable for a later explicit action."""

import re
from hashlib import sha256

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id, require_write_transaction
from backend.app.infrastructure.opencode_instance_control import NativeTurnCompletion, _identifier
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_local_paths import FileIdentity, local_absolute_path
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .task_instance_driver import CaptureTurnEvidence
from .task_session_replacement import repair_execution


def _instance_scope(connection, task, session):
    instance = connection.execute(
        "SELECT * FROM code_instances WHERE id=? AND task_id=? AND status='READY' AND stopped_at IS NULL",
        (session['instance_id'], task['id']),
    ).fetchone()
    if instance is None or instance['control_generation'] > task['control_generation']:
        raise StorageUnavailable('Original cancelled repair instance differs')
    binding = strict_json_object(instance['runtime_binding'])
    process = strict_json_object(instance['process_identity'])
    if binding.get('run_kind') != 'TASK' or not binding.get('guard_run_ref'):
        raise StorageUnavailable('Original cancelled repair binding differs')
    return binding['guard_run_ref'], process.get('ownership_ref')


def _proof(value, session, window, receipt):
    exact(value, ('turn', 'guard_receipt_sha256', 'active_process_count', 'workspace'))
    turn = exact(
        value['turn'], ('session_id', 'trigger_message_id', 'assistant_message_id', 'outcome')
    )
    workspace = exact(
        value['workspace'],
        ('canonical_path', 'volume_serial', 'file_id', 'is_directory', 'filesystem'),
    )
    if (
        turn['session_id'] != session['native_session_id']
        or turn['trigger_message_id'] != window['native_trigger_message_id']
        or turn['outcome'] != 'CANCELLED'
        or not _identifier(turn['assistant_message_id'], 'msg')
        or type(value['active_process_count']) is not int
        or value['active_process_count'] != 1
        or type(receipt) is not str
        or len(receipt) != 64
        or any(character not in '0123456789abcdef' for character in receipt)
        or value['guard_receipt_sha256'] != receipt
        or workspace['is_directory'] is not True
        or workspace['filesystem'] != 'NTFS'
    ):
        raise StorageUnavailable('Original cancelled repair quiet proof differs')
    local_absolute_path(workspace['canonical_path'])
    for field, count in (('volume_serial', 16), ('file_id', 32)):
        if (
            type(workspace[field]) is not str
            or re.fullmatch('[0-9a-f]{' + str(count) + '}', workspace[field]) is None
        ):
            raise StorageUnavailable('Original cancelled repair workspace differs')
    return value


def record_cancelled_repair(connection, task, operation, session, proof, at):
    require_write_transaction(connection)
    window = strict_json_object(session['model_window'])
    if (
        type(proof) is not CaptureTurnEvidence
        or type(proof.turn) is not NativeTurnCompletion
        or type(proof.workspace) is not FileIdentity
        or window['state'] != 'OPEN'
        or window['operation_id'] != operation['id']
    ):
        raise TaskExecutionError('ORIGINAL_CANCELLED_REPAIR_QUIET_UNVERIFIED')
    binding, receipt = _instance_scope(connection, task, session)
    value = _proof(proof.scope_proof(), session, window, receipt)
    reference = f'sqlite:code_operation_steps/{operation["id"]}/3#sha256={sha256(canonical_input(value).encode()).hexdigest()}'
    identity = entity_id(connection, EntityKind.RUNTIME_OBSERVATION)
    connection.execute(
        """INSERT INTO code_runtime_observations(id,task_id,instance_id,operation_id,control_generation,
           runtime_binding_ref,kind,result,reason_codes,active_process_count,observed_at,evidence_ref)
           VALUES(?,?,?,?,?,?,'QUIESCE','VERIFIED','[]',1,?,?)""",
        (
            identity,
            task['id'],
            session['instance_id'],
            operation['id'],
            session['control_generation'],
            binding,
            at,
            reference,
        ),
    )
    return {'quiesce_observation_id': identity, 'proof': value}


def read_cancelled_repair(connection, task, session, window):
    """A CLOSED flag or failed operation alone never grants a new writer."""
    if window.get('state') != 'CLOSED' or window.get('closed_at') is None:
        return None
    operation = connection.execute(
        """SELECT * FROM code_operations WHERE id=? AND task_id=? AND operation_type='REPAIR' AND status='CANCELLED'
           AND failure_code IS NULL""",
        (window['operation_id'], task['id']),
    ).fetchone()
    if operation is None or repair_execution(connection, operation) != (
        session['id'],
        task['control_generation'],
    ):
        return None
    # The repair reader already owns the immutable command/defect association.
    # Import when reading to retain the existing intake/capture dependency.
    from .task_repairs import read_repair_operation

    repair, fixed, steps = read_repair_operation(connection, operation)
    if (
        repair['result_candidate_id'] is not None
        or tuple(step['status'] for step in steps)
        != ('SUCCEEDED', 'SUCCEEDED', 'CANCELLED', 'CANCELLED')
        or steps[2]['result_ref'] is None
        or steps[3]['external_identity'] is not None
        or session['status'] != 'ACTIVE'
        or session['control_generation'] != task['control_generation']
        or session['id'] != task['active_session_id']
        or operation['ended_at'] != window['closed_at']
        or operation['ended_at'] != steps[2]['ended_at']
    ):
        return None
    original_send = strict_json_object(steps[1]['external_identity'])
    payload = original_send.get('payload')
    candidate = connection.execute(
        'SELECT manifest_sha256 FROM code_candidates WHERE id=? AND task_id=?',
        (fixed['candidate_id'], task['id']),
    ).fetchone()
    source = strict_json_object(steps[0]['result_ref'])
    if (
        type(payload) is not dict
        or original_send.get('session_id') != session['id']
        or original_send.get('instance_id') != session['instance_id']
        or original_send.get('generation') != task['control_generation']
        or payload.get('messageID') != window['native_trigger_message_id']
        or original_send.get('payload_sha256') != sha256(_bytes(payload)).hexdigest()
        or candidate is None
        or source.get('candidate_id') != fixed['candidate_id']
        or source.get('manifest_sha256') != candidate['manifest_sha256']
    ):
        raise StorageUnavailable('Original cancelled repair dispatch differs')
    result = strict_json_object(steps[2]['result_ref'])
    exact(result, ('quiesce_observation_id', 'proof'))
    identity = strict_integer(result['quiesce_observation_id'], 'quiesce_observation_id')
    binding, receipt = _instance_scope(connection, task, session)
    value = _proof(result['proof'], session, window, receipt)
    reference = f'sqlite:code_operation_steps/{operation["id"]}/3#sha256={sha256(canonical_input(value).encode()).hexdigest()}'
    row = connection.execute(
        """SELECT * FROM code_runtime_observations WHERE id=? AND task_id=? AND instance_id=?
           AND operation_id=? AND control_generation=? AND runtime_binding_ref=?
           AND kind='QUIESCE' AND result='VERIFIED' AND reason_codes='[]'
           AND active_process_count=1 AND observed_at=? AND evidence_ref=?""",
        (
            identity,
            task['id'],
            session['instance_id'],
            operation['id'],
            task['control_generation'],
            binding,
            window['closed_at'],
            reference,
        ),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original cancelled repair observation differs')
    if task['current_candidate_id'] == fixed['candidate_id']:
        return row
    return _recaptured_observation(connection, task, session, operation, value)


def _recaptured_observation(connection, task, session, cancelled, proof):
    from .task_candidate_commit import load_candidate_capture, verify_capture_quiescence_record

    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (task['current_candidate_id'], task['id']),
    ).fetchone()
    if candidate is None:
        raise StorageUnavailable('Cancelled repair current candidate differs')
    prepared, _, operation, steps = load_candidate_capture(
        connection, candidate['capture_operation_id']
    )
    captured = verify_capture_quiescence_record(connection, prepared, steps[0])
    if (
        prepared.binding.candidate_id != candidate['id']
        or prepared.binding.control_generation != task['control_generation']
        or prepared.session_id != session['id']
        or prepared.role != session['role']
        or operation['created_at'] < cancelled['ended_at']
        or candidate['created_at'] < cancelled['ended_at']
        or captured != proof
    ):
        raise StorageUnavailable('Cancelled repair recapture scope differs')
    result = strict_json_object(steps[0]['result_ref'])
    observation = connection.execute(
        """SELECT * FROM code_runtime_observations WHERE id=? AND operation_id=? AND task_id=?
           AND instance_id=? AND control_generation=? AND kind='QUIESCE' AND result='VERIFIED'
           AND active_process_count=1 AND observed_at=?""",
        (
            result['quiesce_observation_id'],
            operation['id'],
            task['id'],
            session['instance_id'],
            task['control_generation'],
            steps[0]['ended_at'],
        ),
    ).fetchone()
    if observation is None:
        raise StorageUnavailable('Cancelled repair recapture observation differs')
    return observation
