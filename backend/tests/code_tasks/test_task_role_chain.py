"""The Coding role prefix requires the original completed handoff evidence."""

import sqlite3
from contextlib import closing
from hashlib import sha256

import pytest

from backend.app.code_tasks.task_role_chain import (
    ROLES,
    STEPS,
    RoleChainUnavailable,
    current_role_chain,
)
from backend.app.infrastructure.idempotency import canonical_input

AT = '2026-11-10T03:00:00.000Z'


@pytest.fixture
def connection():
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE code_sessions(id INTEGER,task_id INTEGER,instance_id INTEGER,role TEXT,control_generation INTEGER,status TEXT,model_window TEXT,native_session_id TEXT,native_message_id TEXT,gateway_credential_ref TEXT,created_at TEXT);
            CREATE TABLE code_operations(id INTEGER,task_id INTEGER,session_id INTEGER,resource_kind TEXT,resource_id INTEGER,testing_task_id INTEGER,operation_type TEXT,control_generation INTEGER,expected_state_version INTEGER,fixed_input TEXT,status TEXT,created_at TEXT,started_at TEXT,ended_at TEXT);
            CREATE TABLE code_operation_steps(id INTEGER,operation_id INTEGER,step_no INTEGER,step_type TEXT,status TEXT,fixed_input TEXT,result_ref TEXT,started_at TEXT,ended_at TEXT);
            CREATE TABLE code_candidates(id INTEGER,task_id INTEGER,role TEXT,control_generation INTEGER,created_at TEXT);
            CREATE TABLE code_verifications(id INTEGER,task_id INTEGER,owner_kind TEXT,candidate_id INTEGER,operation_id INTEGER,purpose TEXT,role TEXT,scope_stages TEXT,backend_handoff_operation_id INTEGER,frontend_handoff_operation_id INTEGER,status TEXT,stop_status TEXT,cleanup_status TEXT,source_integrity_status TEXT,selected_check_ids TEXT,ended_at TEXT);
            CREATE TABLE code_verification_items(id INTEGER,verification_id INTEGER,check_id TEXT,required INTEGER,result TEXT,evidence_kind TEXT);
            CREATE TABLE code_runtime_observations(id INTEGER,task_id INTEGER,operation_id INTEGER,control_generation INTEGER,instance_id INTEGER,kind TEXT,result TEXT,evidence_ref TEXT,observed_at TEXT);
        """)
        yield connection


def add_session(connection, session_id, phase, generation, *, status='ACTIVE', task=1):
    connection.execute(
        'INSERT INTO code_sessions VALUES(?,?,4,?,?,?,?,?,?,?,?)',
        (
            session_id,
            task,
            phase,
            generation,
            status,
            canonical_input(
                {
                    'state': 'RETIRED' if status == 'RETIRED' else 'OPEN',
                    'native_trigger_message_id': f'msg_{session_id}',
                }
            ),
            f'ses_{session_id}',
            f'msg_{session_id}',
            'original-gateway',
            AT,
        ),
    )


def add_handoff(connection, phase_index):
    source, target = 10 + phase_index, 11 + phase_index
    generation = phase_index + 1
    candidate, verify, verify_op, handoff = (
        30 + phase_index,
        40 + phase_index,
        50 + phase_index,
        60 + phase_index,
    )
    role = ROLES[phase_index]
    target_role = ROLES[phase_index + 1]
    fixed = canonical_input(
        {
            'source_session_id': source,
            'candidate_id': candidate,
            'verification_id': verify,
            'target_role': target_role,
            'expected_state_version': 2 + phase_index,
        }
    )
    connection.execute(
        'INSERT INTO code_candidates VALUES(?,1,?,?,?)', (candidate, role, generation, AT)
    )
    connection.execute(
        "INSERT INTO code_operations VALUES(?,1,?,'TASK',1,NULL,'VERIFY_CANDIDATE',?,1,'{}','SUCCEEDED',?,?,?)",
        (verify_op, source, generation, AT, AT, AT),
    )
    scope = '["BACKEND"]' if phase_index == 0 else '["BACKEND","FRONTEND"]'
    connection.execute(
        """INSERT INTO code_verifications VALUES(?,1,'CODING',?,?,'HANDOFF',?,?,?,NULL,
           'FINISHED','VERIFIED','VERIFIED','VERIFIED','["integrity"]',?)""",
        (verify, candidate, verify_op, role, scope, 60 if phase_index else None, AT),
    )
    connection.execute(
        "INSERT INTO code_verification_items VALUES(?,?,'integrity',1,'PASSED','CONTENT_INTEGRITY')",
        (verify, verify),
    )
    connection.execute(
        "INSERT INTO code_operation_steps VALUES(?,?,3,'CHECK','SUCCEEDED','{}',?,?,?)",
        (verify_op, verify_op, canonical_input({'verification_id': verify}), AT, AT),
    )
    connection.execute(
        "INSERT INTO code_operations VALUES(?,1,?,'TASK',1,NULL,'HANDOFF_ROLE',?,?,?,'SUCCEEDED',?,?,?)",
        (handoff, source, generation, 2 + phase_index, fixed, AT, AT, AT),
    )
    proof = {
        'guard_receipt_sha256': 'a' * 64,
        'active_process_count': 1,
        'turn': {
            'session_id': f'ses_{source}',
            'trigger_message_id': f'msg_{source}',
            'assistant_message_id': 'msg_result',
            'outcome': 'COMPLETED',
        },
        'workspace': {
            'canonical_path': 'C:/fixture',
            'volume_serial': '1',
            'file_id': '2',
            'is_directory': True,
            'filesystem': 'NTFS',
        },
    }
    digest = sha256(canonical_input(proof).encode()).hexdigest()
    connection.execute(
        "INSERT INTO code_runtime_observations VALUES(?,1,?,?,4,'QUIESCE','VERIFIED',?,?)",
        (
            handoff,
            handoff,
            generation,
            f'sqlite:code_operation_steps/{handoff}/1#sha256={digest}',
            AT,
        ),
    )
    results = (
        {'quiesce_observation_id': handoff, 'proof': proof},
        {'session_id': source, 'control_generation': generation + 1},
        {'verification_id': verify},
        {'session_id': target, 'native_session_id': f'ses_{target}'},
        {'session_id': target, 'native_message_id': f'msg_{target}'},
    )
    connection.executemany(
        "INSERT INTO code_operation_steps VALUES(?,?,?,?,'SUCCEEDED',?,?,?,?)",
        [
            (handoff * 10 + index, handoff, index, kind, fixed, canonical_input(result), AT, AT)
            for index, (kind, result) in enumerate(zip(STEPS, results, strict=True), 1)
        ],
    )


def task(role, generation, session_id):
    return {
        'id': 1,
        'phase': role,
        'control_generation': generation,
        'active_session_id': session_id,
    }


def test_backend_frontend_and_integration_require_exact_ordered_prefix(connection):
    add_session(connection, 10, 'BACKEND', 1)
    chain = current_role_chain(connection, task('BACKEND', 1, 10))
    assert chain.stages == ('BACKEND',) and chain.operations == ()
    connection.execute(
        "UPDATE code_sessions SET status='RETIRED',model_window=? WHERE id=10",
        (canonical_input({'state': 'RETIRED', 'native_trigger_message_id': 'msg_10'}),),
    )
    add_session(connection, 11, 'FRONTEND', 2)
    add_handoff(connection, 0)
    chain = current_role_chain(connection, task('FRONTEND', 2, 11))
    assert chain.stages == ROLES[:2] and chain.backend_handoff == 60
    assert chain.frontend_handoff is None
    connection.execute(
        "UPDATE code_sessions SET status='RETIRED',model_window=? WHERE id=11",
        (canonical_input({'state': 'RETIRED', 'native_trigger_message_id': 'msg_11'}),),
    )
    add_session(connection, 12, 'INTEGRATION', 3)
    add_handoff(connection, 1)
    chain = current_role_chain(connection, task('INTEGRATION', 3, 12))
    assert chain.stages == ROLES and chain.operations == (60, 61)


@pytest.mark.parametrize(
    'fault,reason',
    [
        ("UPDATE code_operations SET status='UNKNOWN' WHERE id=60", 'ROLE_CHAIN_UNKNOWN'),
        (
            "UPDATE code_operation_steps SET status='UNKNOWN' WHERE operation_id=60 AND step_no=5",
            'ROLE_CHAIN_INCOMPLETE',
        ),
        ('UPDATE code_candidates SET task_id=2', 'ROLE_CHAIN_INCOMPLETE'),
        ("UPDATE code_verifications SET stop_status='UNKNOWN'", 'ROLE_CHAIN_INCOMPLETE'),
        ("UPDATE code_verification_items SET result='FAILED'", 'ROLE_CHAIN_INCOMPLETE'),
        (
            "UPDATE code_runtime_observations SET evidence_ref='not-original'",
            'ROLE_CHAIN_INCOMPLETE',
        ),
        (
            "UPDATE code_sessions SET native_message_id='msg_forged' WHERE id=11",
            'ROLE_CHAIN_INCOMPLETE',
        ),
        ('UPDATE code_sessions SET control_generation=3 WHERE id=11', 'SESSION_NOT_CURRENT'),
        ('DELETE FROM code_operations WHERE id=60', 'ROLE_CHAIN_INCOMPLETE'),
    ],
)
def test_new_role_requires_all_original_references_and_native_acceptance(connection, fault, reason):
    add_session(connection, 10, 'BACKEND', 1, status='RETIRED')
    add_session(connection, 11, 'FRONTEND', 2)
    add_handoff(connection, 0)
    connection.execute(fault)
    with pytest.raises(RoleChainUnavailable, match=reason):
        current_role_chain(connection, task('FRONTEND', 2, 11))
