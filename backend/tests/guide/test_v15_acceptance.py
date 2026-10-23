"""Real V1.5 acceptance/read/cancellation; all provider dependencies forbidden."""
import asyncio
import json
from copy import deepcopy
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, create, counts, update
from backend.tests.documents.test_v15_documents import workspace, document
from backend.app.guide.commands import create_guide_run, cancel_guide_run, continue_guide_run, retry_guide_run
from backend.app.guide.queries import get_guide_run, list_guide_runs
from backend.app.guide.api import guide_router
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.shared.http_boundary import HttpRuntime


def body(**changes):
    return {'requirement_id': 1, 'expected_discussion_version': 1, 'operation': 'DISCUSS',
        'instruction': '  用户原话\r\n保留空白。  ', 'target': None, 'scope': None, 'source_refs': [],
        'proposal_ref': None, 'acknowledge_source_changes': False, 'idempotency_key': str(uuid4()), **changes}


def accept(workspace, **changes):
    return create_guide_run(workspace[1], body(**changes), catalog=workspace[2])


def test_zero_document_acceptance_is_one_message_pending_version_and_actual_run_receipt(workspace):
    db = workspace[0]
    key = str(uuid4())
    result = accept(workspace, idempotency_key=key)
    assert result['code'] == 'GUIDE_ACCEPTED', result
    assert result['data'] == {'processing': 'MODEL', 'guide_run_id': 1, 'user_message_id': 2}
    assert accept(workspace, idempotency_key=key) == result
    assert accept(workspace, idempotency_key=key, instruction='different')['code'] == 'IDEMPOTENCY_CONFLICT'
    with db.transaction() as connection:
        root = connection.execute('SELECT * FROM requirements').fetchone()
        state = json.loads(root['discussion_state_json'])
        assert state['pending_user_message_ids'] == [2]
        assert root['discussion_version'] == 2 and root['metadata_version'] == 1
        assert root['document_work_state'] == 'GUIDE_ACTIVE'
        run = connection.execute('SELECT * FROM guide_runs').fetchone()
        basis = json.loads(run['execution_basis_json'])
        assert basis['discussion_version'] == run['discussion_version_snapshot'] == 2
        assert basis['requirement']['active_operation_id'] == run['id']
        assert basis['target_document'] is None and basis['authorization']['allowed_targets'] == []
        assert basis['source_snapshots'][0]['value']['message']['id'] == 1
        assert basis['user_message']['content'] == body()['instruction']
        assert basis['resources']['structure'] is None
    run = get_guide_run(db, 1)
    assert run['code'] == 'READ_OK', run
    assert run['data']['operation'] == 'DISCUSS' and run['data']['target'] is None
    assert run['data']['material_summary'] is None and run['data']['application_result'] is None
    assert counts(db)['requirement_documents'] == counts(db)['llm_uses'] == 0


def test_explicit_generate_freezes_new_attributes_without_creating_a_document(workspace):
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    target = {'kind': 'NEW', 'name': '需求初稿', 'document_kind': 'brief', 'template_ref': {'key': 'structure.brief', 'version': 'v1'}}
    result = accept(workspace, operation='GENERATE', target=target)
    assert result['code'] == 'GUIDE_ACCEPTED', result
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT * FROM guide_runs').fetchone()
        assert run['action_type'] == 'GENERATE' and run['target_document_id'] is None
        basis = json.loads(run['execution_basis_json'])
        assert basis['request']['target'] == target and basis['resources']['structure']['key'] == 'structure.brief'
    assert counts(workspace[0])['requirement_documents'] == 0


def test_existing_target_scope_and_revision_sources_are_fixed_and_do_not_grant_reference_writes(workspace):
    target = document(workspace)['data']['document']
    reference = document(workspace, name='参考稿')['data']['document']
    result = accept(workspace, operation='REVISE', target={'kind': 'EXISTING', 'document_id': target['id'], 'expected_content_version': 1},
        scope={'scope_type': 'DOCUMENT', 'scope_ref': None}, source_refs=[{'kind': 'REVISION', 'document_id': reference['id'], 'revision_id': 2, 'block_ids': None}])
    assert result['code'] == 'GUIDE_ACCEPTED', result
    with workspace[0].transaction() as connection:
        basis = json.loads(connection.execute('SELECT execution_basis_json FROM guide_runs').fetchone()[0])
        assert basis['authorization']['target_document_id'] == target['id']
        assert basis['authorization']['operation'] == 'REVISE'
        assert basis['source_snapshots'][0]['value']['document_id'] == reference['id']
        assert basis['target_document']['id'] == target['id']
    assert get_guide_run(workspace[0], 1)['data']['target']['document_id'] == target['id']


def test_version_and_input_rejections_cannot_leave_user_messages_or_occupancy(workspace):
    before = counts(workspace[0])
    for changes, code in [({'expected_discussion_version': 2}, 'DISCUSSION_VERSION_CONFLICT'),
            ({'operation': 'GENERATE'}, 'INVALID_INPUT'), ({'operation': 'REVIEW'}, 'INVALID_INPUT'),
            ({'target': {'kind': 'EXISTING', 'document_id': 999, 'expected_content_version': 1}}, 'SOURCE_INVALID'),
            ({'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None}}, 'INVALID_INPUT'),
            ({'source_refs': [{'kind': 'MESSAGE', 'message_id': 999}]}, 'SOURCE_INVALID')]:
        result = accept(workspace, **changes)
        assert result['code'] == code, result
        assert counts(workspace[0]) == before
    result = create_guide_run(workspace[1], {**body(), 'action_type': 'ASK'}, catalog=workspace[2])
    assert result['code'] == 'INVALID_INPUT'


def test_acceptance_rollback_and_concurrent_version_competition(workspace, monkeypatch):
    before = counts(workspace[0])
    def fail(*args, **kwargs):
        raise ValueError('Injected acceptance failure')
    with monkeypatch.context() as patch:
        patch.setattr(GuideRepository, 'accept_collaboration', fail)
        assert accept(workspace)['code'] == 'INTERNAL_ERROR'
    assert counts(workspace[0]) == before
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: accept(workspace), range(2)))
    assert sorted(result['code'] for result in results) == ['DISCUSSION_VERSION_CONFLICT', 'GUIDE_ACCEPTED']


def test_cancel_during_persisting_releases_only_the_actual_run_and_keeps_pending(workspace):
    accepted = accept(workspace);assert accepted['code'] == 'GUIDE_ACCEPTED'
    with workspace[0].transaction(write=True) as connection:
        connection.execute("UPDATE guide_runs SET current_step='PERSISTING' WHERE id=1")
    key = str(uuid4())
    result = cancel_guide_run(workspace[1], {'guide_run_id': 1, 'idempotency_key': key})
    assert result['code'] == 'GUIDE_CANCELLED', result
    assert cancel_guide_run(workspace[1], {'guide_run_id': 1, 'idempotency_key': key}) == result
    run = get_guide_run(workspace[0], 1)
    assert run['code'] == 'READ_OK', run
    assert run['data']['status'] == 'CANCELLED' and run['data']['progress_result'] == 'NOT_REQUESTED'
    with workspace[0].transaction() as connection:
        root = connection.execute('SELECT * FROM requirements').fetchone()
        assert root['document_work_state'] == 'IDLE' and json.loads(root['discussion_state_json'])['pending_user_message_ids'] == [2]


def test_offline_release_blocks_before_context_counting_chat_and_cleans_occupancy(workspace, monkeypatch):
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    def forbidden(*args, **kwargs):
        raise AssertionError('No context/counting/provider work is allowed before admission')
    # Patch the consumer after importing its module. Patching the producer
    # before the lazy execution import would permanently capture this fixture
    # in collaboration_counting even after monkeypatch restored the producer.
    monkeypatch.setattr('backend.app.guide.collaboration_execution._canonical', forbidden)
    monkeypatch.setattr('backend.app.guide.collaboration_counting.compile_context', forbidden)
    result = asyncio.run(execute_guide_run(workspace[0], {'guide_run_id': 1}, process_lock=workspace[1].process_lock,
        catalog=workspace[2], profile=ModelProfile('offline-only', DEFAULT_PROFILE), gateway=forbidden, counting_counter=forbidden))
    assert result['code'] == 'AI_FAILED', result
    assert result['details']['error_code'] == 'CONFIG_INVALID'
    assert counts(workspace[0])['llm_uses'] == 0
    run = get_guide_run(workspace[0], 1)
    assert run['data']['status'] == 'FAILED' and run['data']['error_code'] == 'CONFIG_INVALID'


def test_http_run_receipt_and_actual_new_run_history(workspace):
    app = FastAPI();app.include_router(guide_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    with TestClient(app) as client:
        request = body();request.pop('requirement_id');key = request.pop('idempotency_key')
        response = client.post('/api/v1/requirements/1/guide-runs', json=request, headers={'Idempotency-Key': key})
        assert response.status_code == 202, response.text
        assert response.json()['data'] == {'processing': 'MODEL', 'guide_run_id': 1, 'user_message_id': 2}
        read = client.get('/api/v1/guide-runs/1');assert read.status_code == 200, read.text
        assert read.json()['data']['material_summary'] is None
        history = client.get('/api/v1/requirements/1/guide-runs');assert history.status_code == 200, history.text
        assert history.json()['meta']['pagination']['total'] == 1
        assert client.get('/api/v1/requirements/1/guide-runs?status=WAITING_USER').status_code == 422


def test_continue_creates_new_discuss_with_new_input_and_preserves_ended_parent(workspace):
    db, executor, resources = workspace
    assert accept(workspace, operation='GENERATE', target={'kind': 'NEW', 'name': '稿件', 'document_kind': 'brief', 'template_ref': None})['code'] == 'GUIDE_ACCEPTED'
    assert cancel_guide_run(executor, {'guide_run_id': 1, 'idempotency_key': str(uuid4())})['code'] == 'GUIDE_CANCELLED'
    with db.transaction() as connection:
        before = dict(connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone())
    key = str(uuid4());payload = {'guide_run_id': 1, 'instruction': '  接着讨论  ', 'expected_discussion_version': 2, 'idempotency_key': key}
    result = continue_guide_run(executor, payload, catalog=resources)
    assert result['code'] == 'GUIDE_CONTINUED', result
    assert result['data'] == {'processing': 'MODEL', 'guide_run_id': 2, 'user_message_id': 3}
    assert continue_guide_run(executor, payload, catalog=resources) == result
    with db.transaction() as connection:
        assert dict(connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone()) == before
        run = connection.execute('SELECT * FROM guide_runs WHERE id=2').fetchone()
        assert run['parent_guide_run_id'] == 1 and run['operation'] == 'DISCUSS' and run['target_document_id'] is None
        assert run['instruction_summary'] == '  接着讨论  ' and run['discussion_version_snapshot'] == 3
        assert json.loads(run['execution_basis_json'])['authorization']['allowed_targets'] == []


def test_explicit_retry_reuses_original_input_and_builds_new_authority_without_rewriting_parent(workspace):
    db, executor, resources = workspace
    assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    asyncio.run(execute_guide_run(db, {'guide_run_id': 1}, process_lock=executor.process_lock,
        catalog=resources, profile=ModelProfile('offline-only', DEFAULT_PROFILE)))
    with db.transaction() as connection:
        before = dict(connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone())
    payload = {'guide_run_id': 1, 'idempotency_key': str(uuid4())}
    result = retry_guide_run(executor, payload, catalog=resources)
    assert result['code'] == 'GUIDE_RETRY_ACCEPTED', result
    assert result['data'] == {'processing': 'MODEL', 'guide_run_id': 2, 'user_message_id': 2}
    assert retry_guide_run(executor, payload, catalog=resources) == result
    assert counts(db)['conversation_messages'] == 2
    with db.transaction() as connection:
        assert dict(connection.execute('SELECT * FROM guide_runs WHERE id=1').fetchone()) == before
        run = connection.execute('SELECT * FROM guide_runs WHERE id=2').fetchone()
        assert run['retry_of_guide_run_id'] == 1 and run['trigger_type'] == 'RETRY'
        assert run['discussion_version_snapshot'] == 2
        assert json.loads(connection.execute('SELECT discussion_state_json FROM requirements').fetchone()[0])['pending_user_message_ids'] == [2]
