"""V1.5 real SQLite and in-process HTTP; no sockets or model/计数 access."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.infrastructure.database import Database, SchemaMismatch, Migration, configured_path
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.requirements.api import req_router
from backend.app.requirements.commands import create_requirement, update_requirement
from backend.app.requirements.contracts import STATUSES
from backend.app.requirements.queries import get_requirement
from backend.app.shared.http_boundary import HttpRuntime

TIME = '2026-10-22T00:00:00.000Z'


@pytest.fixture
def tmp_path():
    # Override pytest's retained tmp_path: this task requires immediate cleanup
    # after both successful and failed tests, including isolated SQLite files.
    with TemporaryDirectory(prefix='walle-v15-foundation-') as directory:
        yield Path(directory)


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / 'v15.sqlite')
    assert db.initialize()['schema_version'] == 150
    with ProcessLock.for_database(db.path) as lock:
        executor = Idempotency(db, lock)
        yield db, executor


def create(executor, **changes):
    payload = {'title': '电影记录', 'requirement_type': 'NEW', 'initial_idea': '想记录、评分并推荐电影。', 'idempotency_key': str(uuid4())}
    return create_requirement(executor, {**payload, **changes})


def update(executor, version, changes, key=None):
    return update_requirement(executor, {'requirement_id': 1, 'expected_metadata_version': version,
        'changes': changes, 'idempotency_key': key or str(uuid4())})


def counts(db):
    with db.transaction() as connection:
        return {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
            for table in ('requirements', 'conversation_messages', 'requirement_documents', 'revisions', 'guide_runs', 'llm_uses', 'document_change_audits')}


def test_create_is_one_initial_message_zero_documents_runs_and_calls(setup):
    db, executor = setup
    key = str(uuid4())
    result = create(executor, idempotency_key=key)
    assert result['code'] == 'CREATED'
    data = result['data']
    root = data['requirement']
    assert data['documents'] == []
    assert root['status'] == 'PLANNING'
    assert root['document_work_state'] == 'IDLE'
    assert root['metadata_version'] == root['discussion_version'] == 1
    assert root['initial_message_id'] == data['initial_message_id']
    assert not {'template_key', 'template_version', 'initialization_mode'} & root.keys()
    assert counts(db) == {'requirements': 1, 'conversation_messages': 1, 'requirement_documents': 0, 'revisions': 0, 'guide_runs': 0, 'llm_uses': 0, 'document_change_audits': 0}
    with db.transaction() as connection:
        message = dict(connection.execute('SELECT * FROM conversation_messages').fetchone())
        assert message['role'] == 'USER' and message['message_type'] == 'TEXT'
        assert message['guide_run_id'] is None and message['content'] == '想记录、评分并推荐电影。'
        assert message['topic_refs'] == message['document_ids'] == '[]'
    assert create(executor, idempotency_key=key) == result
    assert create(executor, title='另一个标题', idempotency_key=key)['code'] == 'IDEMPOTENCY_CONFLICT'
    assert counts(db)['conversation_messages'] == 1
    before = counts(db)
    detail = get_requirement(db, root['id'])
    assert detail['code'] == 'READ_OK'
    assert detail['data']['discussion'] is None
    expanded = get_requirement(db, root['id'], expand='discussion')['data']
    assert expanded['discussion']['phase']['kind'] == 'DISCOVERY'
    assert expanded['discussion']['topics'] == []
    assert counts(db) == before


def test_all_twenty_five_status_pairs_are_user_owned_and_same_status_is_no_change(setup):
    db, executor = setup
    create(executor)
    for previous in STATUSES:
        version = get_requirement(db, 1)['data']['requirement']['metadata_version']
        current = update(executor, version, {'status': previous})['data']
        for target in STATUSES:
            # Return to the intended source pair with the real current version.
            current = update(executor, current['metadata_version'], {'status': previous})['data']
            with db.transaction() as connection:
                discussion_before = connection.execute('SELECT discussion_state_json FROM requirements').fetchone()[0]
            event_count = counts(db)['document_change_audits']
            result = update(executor, current['metadata_version'], {'status': target})
            assert result['code'] == ('NO_CHANGE' if previous == target else 'UPDATED')
            after = result['data']
            assert after['status'] == target
            assert after['metadata_version'] == current['metadata_version'] + (previous != target)
            assert after['discussion_version'] == 1 and after['document_work_state'] == 'IDLE'
            assert (after['closed_at'] is not None) == (target == 'CLOSED')
            assert (after['completed_at'] is not None) == (target == 'COMPLETED')
            assert counts(db)['document_change_audits'] == event_count + (previous != target)
            with db.transaction() as connection:
                assert connection.execute('SELECT discussion_state_json FROM requirements').fetchone()[0] == discussion_before
            current = after
    assert counts(db)['guide_runs'] == counts(db)['llm_uses'] == counts(db)['requirement_documents'] == 0


def test_attribute_replay_conflict_and_concurrent_versions(setup):
    db, executor = setup
    create(executor)
    key = str(uuid4())
    accepted = update(executor, 1, {'title': '新标题'}, key)
    assert accepted['code'] == 'UPDATED'
    assert update(executor, 1, {'title': '新标题'}, key) == accepted
    assert update(executor, 1, {'title': '不同请求'}, key)['code'] == 'IDEMPOTENCY_CONFLICT'
    stale = update(executor, 1, {'status': 'CLOSED'})
    assert stale['code'] == 'METADATA_VERSION_CONFLICT'
    assert stale['details'] == {'expected_version': 1, 'actual_version': 2, 'resource_kind': 'Requirement', 'resource_id': 1}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, executor, 2, {'title': value}) for value in ('并发一', '并发二')]
        results = [future.result() for future in futures]
    assert sorted(result['code'] for result in results) == ['METADATA_VERSION_CONFLICT', 'UPDATED']
    assert counts(db)['document_change_audits'] == 2


def seed_running(db):
    # Storage-level in-flight fixture; no model/acceptance or fake paid receipt.
    with db.transaction(write=True) as connection:
        at = connection.execute('SELECT updated_at FROM requirements WHERE id=1').fetchone()[0]
        connection.execute("""INSERT INTO guide_runs(id,requirement_id,idempotency_key,trigger_message_id,trigger_type,source_type,source_id,function_type,context_template_key,context_template_version,prompt_version,action_type,mode_snapshot,instruction_summary,scope_type,scope_ref_json,read_scope_manifest_json,allowed_targets_json,status,current_step,final_result_json,created_at,started_at,waiting_user_at,ended_at,updated_at,error_code,error_message,cancel_reason,retry_of_guide_run_id,operation,target_document_id,parent_guide_run_id,discussion_version_snapshot,execution_basis_json)
            VALUES (10,1,?,1,'USER_INSTRUCTION','USER_INSTRUCTION',NULL,'collaboration_v1','collaboration_context_v1','v1','v1','ASK',NULL,'讨论',NULL,NULL,'{}','{}','RUNNING','PREPARING',NULL,?,NULL,NULL,NULL,?,NULL,NULL,NULL,NULL,'DISCUSS',NULL,NULL,1,'{}')""", (str(uuid4()), at, at))
        RequirementRepository(connection).occupy_guide(1, 10, at)


def test_closing_during_running_operation_does_not_cancel_or_rebind_it(setup):
    db, executor = setup
    create(executor)
    seed_running(db)
    with db.transaction() as connection:
        run_before = dict(connection.execute('SELECT * FROM guide_runs WHERE id=10').fetchone())
    result = update(executor, 1, {'title': '关闭仍可维护', 'status': 'CLOSED'})
    assert result['code'] == 'UPDATED'
    assert result['data']['document_work_state'] == 'GUIDE_ACTIVE'
    assert result['data']['active_operation_id'] == 10
    with db.transaction() as connection:
        assert dict(connection.execute('SELECT * FROM guide_runs WHERE id=10').fetchone()) == run_before
    assert get_requirement(db, 1)['data']['active_operation']['id'] == 10


def test_creation_and_attribute_failure_roll_back_all_related_records(setup, monkeypatch):
    db, executor = setup
    from backend.app.infrastructure.message_repository import MessageRepository
    original = MessageRepository.create_user_text

    def fail_after_message(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise sqlite3.IntegrityError('isolated injected failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(MessageRepository, 'create_user_text', fail_after_message)
        assert create(executor)['code'] == 'STORAGE_UNAVAILABLE'
    assert all(value == 0 for value in counts(db).values())
    assert create(executor)['data']['requirement']['id'] == 1
    before = get_requirement(db, 1)['data']

    def fail_event(*args, **kwargs):
        raise sqlite3.IntegrityError('isolated event failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(AuditRepository, 'record_requirement_update', fail_event)
        assert update(executor, 1, {'status': 'CLOSED'})['code'] == 'STORAGE_UNAVAILABLE'
    assert get_requirement(db, 1)['data'] == before
    assert counts(db)['document_change_audits'] == 0


def test_http_new_contracts_replay_errors_and_removed_initialization(setup):
    db, executor = setup
    app = FastAPI()
    app.include_router(req_router)
    app.state.walle_runtime = HttpRuntime(db, ResourceCatalog(), executor)
    with TestClient(app) as client:
        headers = {'Idempotency-Key': str(uuid4())}
        body = {'title': 'HTTP创建', 'requirement_type': 'NEW', 'initial_idea': '初始内容'}
        response = client.post('/api/v1/requirements', json=body, headers=headers)
        assert response.status_code == 201, response.text
        replay = client.post('/api/v1/requirements', json=body, headers=headers)
        assert replay.status_code == 201 and replay.json()['data'] == response.json()['data']
        assert replay.json()['meta']['request_id'] != response.json()['meta']['request_id']
        assert client.get('/api/v1/requirements/1').json()['data']['documents'] == []
        assert client.get('/api/v1/requirements/1?expand=discussion').json()['data']['discussion']['phase']['kind'] == 'DISCOVERY'
        assert client.get('/api/v1/requirements?status=PLANNING').json()['meta']['pagination']['total'] == 1
        assert client.get('/api/v1/requirements?status=ACTIVE').status_code == 422
        assert client.post('/api/v1/requirements', json={**body, 'initialization_mode': 'IDEATION'}, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
        patch = {'expected_metadata_version': 1, 'changes': {'status': 'CLOSED'}}
        response = client.patch('/api/v1/requirements/1', json=patch, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 200, response.text
        conflict = client.patch('/api/v1/requirements/1', json=patch, headers={'Idempotency-Key': str(uuid4())})
        assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'METADATA_VERSION_CONFLICT'
        response = client.post('/api/v1/requirements/1/complete', json={'expected_metadata_version': 2}, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 200 and response.json()['data']['status'] == 'COMPLETED'
        response = client.post('/api/v1/requirements/1/reactivate', json={'expected_metadata_version': 3}, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 200 and response.json()['data']['status'] == 'PLANNING'
        legacy = client.post('/api/v1/requirements/1/complete-initialization', headers={'Idempotency-Key': str(uuid4())})
        assert legacy.status_code == 409 and legacy.json()['error']['code'] == 'STATE_CONFLICT'
        assert client.post('/api/v1/requirements/1/complete-initialization', json={'expected_content_version': 1}, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
    assert counts(db)['guide_runs'] == counts(db)['llm_uses'] == 0


def test_database_requires_explicit_path_and_rejects_old_schema_without_mutation(tmp_path, monkeypatch):
    monkeypatch.delenv('WALLE_DATABASE_PATH', raising=False)
    with pytest.raises(SchemaMismatch):
        configured_path()
    monkeypatch.setenv('WALLE_DATABASE_PATH', 'relative.sqlite')
    with pytest.raises(SchemaMismatch):
        configured_path()
    old = tmp_path / 'old.sqlite'
    connection = sqlite3.connect(old)
    connection.executescript("CREATE TABLE old_user_text(content TEXT); INSERT INTO old_user_text VALUES ('preserve');")
    connection.close()
    before = hashlib.sha256(old.read_bytes()).hexdigest()
    with pytest.raises(SchemaMismatch):
        Database(old).initialize()
    assert hashlib.sha256(old.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob('*.backup.sqlite'))


def test_schema_repeat_integrity_and_deferred_initial_message_rollback(setup):
    db, executor = setup
    # Initialize requires its own process lock; check after current lock ends is
    # covered below with an independent target rather than trying to reenter.
    create(executor)
    with db.transaction() as connection:
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert len(names) == 17
        assert {'manual_edit_sessions', 'manual_block_origins', 'manual_block_allocation_ranges', 'idempotency_records'} <= names
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET initial_message_id=999 WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction(write=True) as connection:
            connection.execute('DELETE FROM conversation_messages WHERE id=1')


def test_new_schema_initialization_is_repeatable_and_detects_altered_objects(tmp_path):
    db = Database(tmp_path / 'repeat.sqlite')
    assert db.initialize()['initialized'] is True
    assert db.initialize()['initialized'] is False
    connection = sqlite3.connect(db.path)
    connection.execute('DROP INDEX documents_order')
    connection.close()
    with pytest.raises(SchemaMismatch):
        with db.transaction():
            pass
