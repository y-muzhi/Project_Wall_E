"""Read the immutable same-role successor without rewriting an original operation."""

import re
from dataclasses import dataclass
from hashlib import sha256

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.opencode_instance_control import _identifier
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_local_paths import local_absolute_path
from backend.app.shared.http_projection import exact
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_integer, strict_json_object

from .repository_operations import _time


@dataclass(frozen=True)
class SessionReplacement:
    operation: object
    source: object
    target: object
    intent: dict
    step: object


def _quiet(connection, operation, source, intent):
    saved = exact(intent['quiet'], ('quiesce_observation_id', 'proof'))
    identity = strict_integer(saved['quiesce_observation_id'], 'quiesce_observation_id')
    proof = exact(
        saved['proof'], ('turn', 'guard_receipt_sha256', 'active_process_count', 'workspace')
    )
    turn = exact(
        proof['turn'], ('session_id', 'trigger_message_id', 'assistant_message_id', 'outcome')
    )
    workspace = exact(
        proof['workspace'],
        ('canonical_path', 'volume_serial', 'file_id', 'is_directory', 'filesystem'),
    )
    original = exact(
        intent['source_window'],
        ('operation_id', 'native_trigger_message_id', 'state', 'opened_at', 'closed_at'),
    )
    strict_integer(original['operation_id'], 'source_window.operation_id')
    for value in (original['opened_at'], original['closed_at']):
        _time(value, nullable=False)
    if (
        original['state'] != 'CLOSED'
        or original['closed_at'] < original['opened_at']
        or turn['session_id'] != source['native_session_id']
        or turn['trigger_message_id'] != original['native_trigger_message_id']
        or not _identifier(turn['session_id'], 'ses')
        or not _identifier(turn['trigger_message_id'], 'msg')
        or not _identifier(turn['assistant_message_id'], 'msg')
        or turn['outcome'] not in ('COMPLETED', 'CANCELLED')
        or type(proof['active_process_count']) is not int
        or proof['active_process_count'] != 1
        or type(proof['guard_receipt_sha256']) is not str
        or re.fullmatch('[a-f0-9]{64}', proof['guard_receipt_sha256']) is None
        or workspace['is_directory'] is not True
        or workspace['filesystem'] != 'NTFS'
    ):
        raise StorageUnavailable('Original same-role quiet scope differs')
    local_absolute_path(workspace['canonical_path'])
    for field, length in (('volume_serial', 16), ('file_id', 32)):
        if (
            type(workspace[field]) is not str
            or re.fullmatch('[a-f0-9]{' + str(length) + '}', workspace[field]) is None
        ):
            raise StorageUnavailable('Original same-role workspace differs')
    retired = {**original, 'state': 'RETIRED'}
    if strict_json_object(source['model_window']) != retired:
        raise StorageUnavailable('Original same-role source window differs')
    digest = sha256(canonical_input(proof).encode()).hexdigest()
    row = connection.execute(
        """SELECT * FROM code_runtime_observations WHERE id=? AND task_id=? AND operation_id=?
           AND instance_id=? AND control_generation=? AND kind='QUIESCE' AND result='VERIFIED'
           AND reason_codes='[]' AND active_process_count=1 AND evidence_ref=?""",
        (
            identity,
            operation['task_id'],
            operation['id'],
            source['instance_id'],
            source['control_generation'],
            f'sqlite:code_operation_steps/{operation["id"]}/1#sha256={digest}',
        ),
    ).fetchone()
    if row is None:
        raise StorageUnavailable('Original same-role quiet observation missing')
    _time(row['observed_at'], nullable=False)
    if row['observed_at'] < operation['created_at']:
        raise StorageUnavailable('Original same-role quiet chronology differs')
    instance = connection.execute(
        'SELECT runtime_binding,process_identity FROM code_instances WHERE id=? AND task_id=?',
        (source['instance_id'], operation['task_id']),
    ).fetchone()
    if (
        instance is None
        or strict_json_object(instance['runtime_binding']).get('guard_run_ref')
        != row['runtime_binding_ref']
        or strict_json_object(instance['process_identity']).get('ownership_ref')
        != proof['guard_receipt_sha256']
    ):
        raise StorageUnavailable('Original same-role Guard binding differs')
    return row


def _candidate_follows_cancelled_replacement(connection, operation, source, candidate, intent):
    if candidate['control_generation'] == source['control_generation']:
        return True
    if candidate['control_generation'] > source['control_generation']:
        return False
    # A cancelled successor may still own the unchanged source candidate.
    prior = replacement_for_session(connection, operation['task_id'], source['id'])
    if prior is None or prior.intent['candidate_id'] != candidate['id']:
        return False
    closed = connection.execute(
        "SELECT * FROM code_operations WHERE id=? AND task_id=? AND operation_type='REPAIR' AND status='CANCELLED' AND failure_code IS NULL",
        (intent['source_window']['operation_id'], operation['task_id']),
    ).fetchone()
    if closed is None or repair_execution(connection, closed) != (
        source['id'],
        source['control_generation'],
    ):
        return False
    from .task_repairs import read_repair_operation

    repair, fixed, steps = read_repair_operation(connection, closed)
    if (
        fixed['candidate_id'] != candidate['id']
        or repair['result_candidate_id'] is not None
        or tuple(step['status'] for step in steps)
        != ('SUCCEEDED', 'SUCCEEDED', 'CANCELLED', 'CANCELLED')
        or steps[3]['external_identity'] is not None
        or closed['ended_at'] != intent['source_window']['closed_at']
        or steps[2]['ended_at'] != closed['ended_at']
    ):
        return False
    quiet = exact(strict_json_object(steps[2]['result_ref']), ('quiesce_observation_id', 'proof'))
    sent = strict_json_object(steps[1]['external_identity'])
    payload = sent.get('payload')
    if (
        quiet['proof'] != intent['quiet']['proof']
        or sent.get('session_id') != source['id']
        or sent.get('generation') != source['control_generation']
        or type(payload) is not dict
        or payload.get('messageID') != intent['source_window']['native_trigger_message_id']
        or sent.get('payload_sha256') != sha256(_bytes(payload)).hexdigest()
    ):
        return False
    digest = sha256(canonical_input(quiet['proof']).encode()).hexdigest()
    return (
        connection.execute(
            """SELECT 1 FROM code_runtime_observations WHERE id=? AND task_id=? AND operation_id=?
           AND instance_id=? AND control_generation=? AND kind='QUIESCE' AND result='VERIFIED'
           AND reason_codes='[]' AND active_process_count=1 AND observed_at=? AND evidence_ref=?""",
            (
                quiet['quiesce_observation_id'],
                operation['task_id'],
                closed['id'],
                source['instance_id'],
                source['control_generation'],
                closed['ended_at'],
                f'sqlite:code_operation_steps/{closed["id"]}/3#sha256={digest}',
            ),
        ).fetchone()
        is not None
    )


def read_session_replacement(connection, operation, *, ready=True):
    """A matching JSON pointer alone never grants a successor session."""
    step = connection.execute(
        "SELECT * FROM code_operation_steps WHERE operation_id=? AND step_no=1 AND step_type='RESTORE_SOURCE'",
        (operation['id'],),
    ).fetchone()
    if step is None or step['external_identity'] is None:
        return None
    data = exact(strict_json_object(step['external_identity']), ('replacement',))
    intent = exact(
        data['replacement'],
        (
            'source_session_id',
            'target_session_id',
            'instance_id',
            'role',
            'source_generation',
            'target_generation',
            'nonce',
            'candidate_id',
            'archived_at',
            'source_window',
            'quiet',
            'source_evidence',
        ),
    )
    for field in (
        'source_session_id',
        'target_session_id',
        'instance_id',
        'source_generation',
        'target_generation',
        'candidate_id',
        'archived_at',
    ):
        strict_integer(intent[field], field)
    if (
        canonical_input(data) != step['external_identity']
        or operation['operation_type'] != 'REPAIR'
        or operation['resource_kind'] != 'TASK'
        or operation['resource_id'] != operation['task_id']
        or operation['session_id'] != intent['source_session_id']
        or operation['control_generation'] != intent['source_generation']
        or intent['target_generation'] != intent['source_generation'] + 1
        or intent['target_generation'] > MAX_SAFE_INTEGER
        or intent['source_session_id'] == intent['target_session_id']
        or intent['role'] not in ('BACKEND', 'FRONTEND', 'INTEGRATION')
        or type(intent['nonce']) is not str
        or re.fullmatch('[0-9a-f]{32}', intent['nonce']) is None
        or step['fixed_input'] != operation['fixed_input']
    ):
        raise StorageUnavailable('Original same-role replacement intent differs')
    source = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (intent['source_session_id'], operation['task_id']),
    ).fetchone()
    target = connection.execute(
        'SELECT * FROM code_sessions WHERE id=? AND task_id=?',
        (intent['target_session_id'], operation['task_id']),
    ).fetchone()
    candidate = connection.execute(
        'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
        (intent['candidate_id'], operation['task_id']),
    ).fetchone()
    from .task_repairs import _fixed

    fixed = _fixed(strict_json_object(operation['fixed_input']))
    if (
        source is None
        or target is None
        or candidate is None
        or source['status'] != 'RETIRED'
        or source['role'] != intent['role']
        or target['role'] != intent['role']
        or source['instance_id'] != intent['instance_id']
        or target['instance_id'] != intent['instance_id']
        or source['control_generation'] != intent['source_generation']
        or target['control_generation'] != intent['target_generation']
        or candidate['role'] != intent['role']
        or not _candidate_follows_cancelled_replacement(
            connection, operation, source, candidate, intent
        )
        or fixed.get('candidate_id') != candidate['id']
        or target['created_at'] < operation['created_at']
    ):
        raise StorageUnavailable('Original same-role replacement scope differs')
    evidence = exact(
        intent['source_evidence'], ('candidate_id', 'manifest_sha256', 'restored_file_count')
    )
    strict_integer(evidence['restored_file_count'], 'restored_file_count', minimum=0)
    strict_integer(evidence['candidate_id'], 'source_evidence.candidate_id')
    if (
        evidence['candidate_id'] != candidate['id']
        or evidence['manifest_sha256'] != candidate['manifest_sha256']
    ):
        raise StorageUnavailable('Original same-role restored source differs')
    _quiet(connection, operation, source, intent)
    if ready:
        result = strict_json_object(step['result_ref']) if step['result_ref'] is not None else {}
        if (
            step['status'] != 'SUCCEEDED'
            or result
            != {
                **evidence,
                'replacement_session_id': target['id'],
                'native_session_id': target['native_session_id'],
            }
            or not _identifier(target['native_session_id'], 'ses')
            or target['native_session_id'] == source['native_session_id']
        ):
            raise StorageUnavailable('Original same-role creation is not confirmed')
    return SessionReplacement(operation, source, target, intent, step)


def replacement_for_session(connection, task_id, session_id, *, ready=True):
    if (
        connection.execute(
            "SELECT 1 FROM code_operations WHERE task_id=? AND operation_type='REPAIR' LIMIT 1",
            (task_id,),
        ).fetchone()
        is None
    ):
        return None
    rows = connection.execute(
        """SELECT o.* FROM code_operations o JOIN code_operation_steps s ON s.operation_id=o.id
           WHERE o.task_id=? AND o.operation_type='REPAIR' AND s.step_no=1
           AND json_extract(s.external_identity,'$.replacement.target_session_id')=?""",
        (task_id, session_id),
    ).fetchall()
    if len(rows) > 1:
        raise StorageUnavailable('More than one same-role creation owns this session')
    return None if not rows else read_session_replacement(connection, rows[0], ready=ready)


def replacement_origin(connection, task_id, session_id):
    visited = set()
    while True:
        if session_id in visited:
            raise StorageUnavailable('Same-role replacement lineage contains a cycle')
        visited.add(session_id)
        original = replacement_for_session(connection, task_id, session_id)
        if original is None:
            return session_id
        session_id = original.source['id']


def repair_execution(connection, operation):
    original = read_session_replacement(connection, operation, ready=False)
    if original is None:
        return operation['session_id'], operation['control_generation']
    return original.target['id'], original.target['control_generation']
