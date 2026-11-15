"""Replacement authority needs the original immutable source, quiet and creation."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from hashlib import sha256

import pytest

from backend.app.code_tasks.task_session_replacement import (
    read_session_replacement,
    repair_execution,
    replacement_origin,
)
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import canonical_input

AT = '2026-11-11T07:20:00.000Z'


@pytest.fixture
def original():
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE code_operations(id INTEGER,task_id INTEGER,resource_kind TEXT,resource_id INTEGER,
                session_id INTEGER,operation_type TEXT,control_generation INTEGER,fixed_input TEXT,created_at TEXT);
            CREATE TABLE code_operation_steps(operation_id INTEGER,step_no INTEGER,step_type TEXT,status TEXT,
                external_identity TEXT,result_ref TEXT,fixed_input TEXT);
            CREATE TABLE code_sessions(id INTEGER,task_id INTEGER,instance_id INTEGER,role TEXT,
                control_generation INTEGER,status TEXT,model_window TEXT,native_session_id TEXT,created_at TEXT);
            CREATE TABLE code_candidates(id INTEGER,task_id INTEGER,role TEXT,control_generation INTEGER,manifest_sha256 TEXT);
            CREATE TABLE code_instances(id INTEGER,task_id INTEGER,runtime_binding TEXT,process_identity TEXT);
            CREATE TABLE code_runtime_observations(id INTEGER,task_id INTEGER,operation_id INTEGER,instance_id INTEGER,
                control_generation INTEGER,kind TEXT,result TEXT,reason_codes TEXT,active_process_count INTEGER,
                evidence_ref TEXT,observed_at TEXT,runtime_binding_ref TEXT);
        """)
        window = {
            'operation_id': 1,
            'native_trigger_message_id': 'msg_original',
            'state': 'CLOSED',
            'opened_at': AT,
            'closed_at': AT,
        }
        proof = {
            'turn': {
                'session_id': 'ses_old',
                'trigger_message_id': 'msg_original',
                'assistant_message_id': 'msg_finished',
                'outcome': 'COMPLETED',
            },
            'guard_receipt_sha256': 'a' * 64,
            'active_process_count': 1,
            'workspace': {
                'canonical_path': 'C:/fixture/work',
                'volume_serial': '0' * 16,
                'file_id': '1' * 32,
                'is_directory': True,
                'filesystem': 'NTFS',
            },
        }
        evidence = {'candidate_id': 30, 'manifest_sha256': 'b' * 64, 'restored_file_count': 0}
        intent = {
            'source_session_id': 10,
            'target_session_id': 11,
            'instance_id': 4,
            'role': 'BACKEND',
            'source_generation': 1,
            'target_generation': 2,
            'nonce': 'c' * 32,
            'candidate_id': 30,
            'archived_at': 1,
            'source_window': window,
            'quiet': {'quiesce_observation_id': 50, 'proof': proof},
            'source_evidence': evidence,
        }
        fixed = canonical_input(
            {'candidate_id': 30, 'defect_ids': [20], 'expected_state_version': 9}
        )
        connection.execute(
            "INSERT INTO code_operations VALUES(2,1,'TASK',1,10,'REPAIR',1,?,?)", (fixed, AT)
        )
        connection.execute(
            "INSERT INTO code_sessions VALUES(10,1,4,'BACKEND',1,'RETIRED',?,'ses_old',?)",
            (canonical_input({**window, 'state': 'RETIRED'}), AT),
        )
        connection.execute(
            "INSERT INTO code_sessions VALUES(11,1,4,'BACKEND',2,'ACTIVE',?,'ses_new',?)",
            (canonical_input({'state': 'OPEN'}), AT),
        )
        connection.execute("INSERT INTO code_candidates VALUES(30,1,'BACKEND',1,?)", ('b' * 64,))
        connection.execute(
            'INSERT INTO code_instances VALUES(4,1,?,?)',
            (
                canonical_input({'guard_run_ref': 'guard:original'}),
                canonical_input({'ownership_ref': 'a' * 64}),
            ),
        )
        digest = sha256(canonical_input(proof).encode()).hexdigest()
        connection.execute(
            "INSERT INTO code_runtime_observations VALUES(50,1,2,4,1,'QUIESCE','VERIFIED','[]',1,?,?,'guard:original')",
            (f'sqlite:code_operation_steps/2/1#sha256={digest}', AT),
        )
        result = {**evidence, 'replacement_session_id': 11, 'native_session_id': 'ses_new'}
        connection.execute(
            "INSERT INTO code_operation_steps VALUES(2,1,'RESTORE_SOURCE','SUCCEEDED',?,?,?)",
            (canonical_input({'replacement': intent}), canonical_input(result), fixed),
        )
        yield connection, intent


def test_original_operation_identity_and_source_history_remain_fixed(original):
    connection, _ = original
    operation = connection.execute('SELECT * FROM code_operations WHERE id=2').fetchone()
    result = read_session_replacement(connection, operation)
    assert result.source['id'] == 10 and result.target['id'] == 11
    assert repair_execution(connection, operation) == (11, 2)
    assert replacement_origin(connection, 1, 11) == 10
    assert (operation['session_id'], operation['control_generation']) == (10, 1)


@pytest.mark.parametrize(
    'change',
    [
        'generation',
        'role',
        'source-window',
        'guard',
        'quiet',
        'candidate',
        'native',
        'pending',
        'float-identity',
        'float-source-operation',
        'float-source-candidate',
    ],
)
def test_changed_or_incomplete_replacement_never_grants_authority(original, change):
    connection, intent = original
    if change in ('generation', 'role', 'native'):
        field, value = {
            'generation': ('control_generation', 3),
            'role': ('role', 'FRONTEND'),
            'native': ('native_session_id', 'ses_old'),
        }[change]
        connection.execute(f'UPDATE code_sessions SET {field}=? WHERE id=11', (value,))
    elif change == 'source-window':
        connection.execute("UPDATE code_sessions SET model_window='{}' WHERE id=10")
    elif change == 'guard':
        connection.execute("UPDATE code_instances SET process_identity='{}'")
    elif change == 'quiet':
        connection.execute("UPDATE code_runtime_observations SET evidence_ref='unverified'")
    elif change == 'candidate':
        connection.execute("UPDATE code_candidates SET manifest_sha256='changed'")
    elif change == 'pending':
        connection.execute("UPDATE code_operation_steps SET status='RUNNING',result_ref=NULL")
    elif change == 'float-source-operation':
        altered = deepcopy(intent)
        altered['source_window']['operation_id'] = 1.0
        connection.execute(
            'UPDATE code_operation_steps SET external_identity=?',
            (canonical_input({'replacement': altered}),),
        )
        connection.execute(
            'UPDATE code_sessions SET model_window=? WHERE id=10',
            (canonical_input({**altered['source_window'], 'state': 'RETIRED'}),),
        )
    elif change == 'float-source-candidate':
        altered = deepcopy(intent)
        altered['source_evidence']['candidate_id'] = 30.0
        connection.execute(
            'UPDATE code_operation_steps SET external_identity=?',
            (canonical_input({'replacement': altered}),),
        )
    else:
        altered = deepcopy(intent)
        altered['source_session_id'] = 10.0
        connection.execute(
            'UPDATE code_operation_steps SET external_identity=?',
            (canonical_input({'replacement': altered}),),
        )
    operation = connection.execute('SELECT * FROM code_operations WHERE id=2').fetchone()
    with pytest.raises((StorageUnavailable, ValueError)):
        read_session_replacement(connection, operation)


@pytest.mark.parametrize(
    'state', ['settled', 'pending-create', 'unknown-create', 'unrelated-session']
)
def test_stop_keeps_every_original_same_role_session_in_scope(original, state):
    from backend.app.code_tasks.task_runtime_stop import _stop_sessions

    connection, _ = original
    connection.execute('UPDATE code_sessions SET model_window=\'{"state":"CLOSED"}\' WHERE id=11')
    if state in ('pending-create', 'unknown-create'):
        connection.execute(
            "UPDATE code_sessions SET native_session_id=NULL,model_window=NULL,status='PREPARING' WHERE id=11"
        )
        connection.execute(
            'UPDATE code_operation_steps SET status=?,result_ref=NULL',
            ('UNKNOWN' if state == 'unknown-create' else 'RUNNING',),
        )
    if state == 'unrelated-session':
        connection.execute(
            "INSERT INTO code_sessions VALUES(12,1,4,'BACKEND',2,'RETIRED',NULL,'ses_extra',?)",
            (AT,),
        )
    task = {'id': 1, 'status': 'STOPPING', 'active_session_id': 11}
    stop = {'session_id': 11, 'control_generation': 3}
    start = {'session_id': 10, 'control_generation': 1}
    if state == 'unrelated-session':
        with pytest.raises(StorageUnavailable, match='session chain'):
            _stop_sessions(connection, task, stop, start, {'id': 4})
    else:
        sessions, native = _stop_sessions(connection, task, stop, start, {'id': 4})
        assert set(sessions) == {10, 11} and native['id'] == 11
        assert (native['native_session_id'] is None) == (state != 'settled')


@pytest.mark.parametrize(
    'case',
    ['original-source', 'task', 'instance', 'generation', 'same-session', 'same-native', 'handoff'],
)
def test_same_role_message_keeps_real_old_source_and_exact_new_target(case):
    from dataclasses import replace
    from backend.app.code_tasks.task_model_ingress import ModelWindow
    from backend.app.code_tasks.task_resume_runtime import Continuation
    from backend.app.code_tasks.task_start_session import SuccessorSessionScope
    from backend.app.infrastructure.opencode_task_launch import TaskExecutionError

    scope = SuccessorSessionScope(
        operation_id=1,
        task_id=1,
        instance_id=4,
        session_id=11,
        control_generation=2,
        state_version=2,
        profile_id=1,
        authorization_id=1,
        nonce='a' * 32,
        workspace_id=1,
        query_timeout_seconds=2,
        send_timeout_seconds=2,
        role='BACKEND',
        transition_operation_id=2,
        transition_nonce='b' * 32,
        original_launch_generation=1,
        transition_kind='REPAIR',
        transition_step_no=1,
    )
    previous = ModelWindow(1, 4, 1, 10, 'ses_old', 1, 'msg_old')
    native = 'ses_new'
    if case == 'task':
        previous = replace(previous, task_id=2)
    elif case == 'instance':
        previous = replace(previous, instance_id=5)
    elif case == 'generation':
        previous = replace(previous, generation=2)
    elif case == 'same-session':
        previous = replace(previous, execution_session_id=11)
    elif case == 'same-native':
        native = 'ses_old'
    elif case == 'handoff':
        scope = replace(
            scope, role='FRONTEND', transition_kind='HANDOFF_ROLE', transition_step_no=4
        )
    if case == 'original-source':
        owner = Continuation(scope, previous, 'fixture', native)
        assert owner.previous is previous
        assert owner.previous.native_session_id == 'ses_old'
        assert owner.window(2, 'msg_new') == ModelWindow(1, 4, 2, 11, 'ses_new', 2, 'msg_new')
    else:
        with pytest.raises(TaskExecutionError):
            Continuation(scope, previous, 'fixture', native)
