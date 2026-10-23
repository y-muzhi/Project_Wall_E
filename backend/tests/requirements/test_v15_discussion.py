"""Isolated real SQLite and HTTP discussion transactions; no provider calls."""
import json
import sqlite3
from copy import deepcopy
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, create, update, counts
from backend.tests.documents.test_v15_documents import workspace, document, metadata
from backend.tests.documents.test_v15_editing import start
from backend.app.requirements.commands import update_discussion
from backend.app.requirements.queries import get_requirement
from backend.app.requirements.discussion import validate_discussion
from backend.app.requirements.api import req_router
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.requirements.source_refs import verify_source_refs
from backend.app.shared.command_execution import Rejected


def command(workspace, value, version=1, key=None, requirement_id=1):
    return update_discussion(workspace[1], {'requirement_id': requirement_id, 'expected_discussion_version': version,
        'discussion_command': value, 'idempotency_key': key or str(uuid4())}, catalog=workspace[2])


def binding(target=None, refs=None, scope=None):
    return {'type': 'SET_BINDING', 'target_document_id': target, 'source_refs': refs or [], 'scope': scope}


def phase(kind='SOLUTION', unresolved=None):
    return {'type': 'CHANGE_PHASE', 'phase_kind': kind, 'closure_message': '保留未决问题，进入下一阶段', 'unresolved_refs': unresolved or []}


def topic_fixture(workspace):
    db = workspace[0]
    with db.transaction(write=True) as connection:
        repo = RequirementRepository(connection)
        root = repo.get(1)
        state = deepcopy(root['discussion_state_json'])
        state['topics'] = [{'topic_ref': 't1', 'phase_ref': 'p1', 'mainline_ref': 'value', 'title': '目标', 'purpose': '明确价值',
            'expected_outcomes': [{'outcome_ref': 'o1', 'text': '目标已描述', 'criterion': '有用户依据'}],
            'assessment': 'DISCUSSING', 'evidence_refs': [], 'dependencies': [], 'unresolved_impacts': [],
            'updated_by_message_id': root['initial_message_id']}]
        state['counters']['topic'] = 2
        repo.update_discussion(root, state, root['updated_at'])


def test_binding_empty_no_change_then_actual_message_and_idempotent_receipt(workspace):
    db, executor, _ = workspace
    before = counts(db)
    assert command(workspace, binding())['code'] == 'NO_CHANGE'
    assert counts(db) == before
    key = str(uuid4())
    value = binding(refs=[{'kind': 'MESSAGE', 'message_id': 1}])
    result = command(workspace, value, key=key)
    assert result['code'] == 'UPDATED', result
    assert result['data']['discussion_version'] == 2
    assert command(workspace, value, key=key) == result
    assert command(workspace, binding(), key=key)['code'] == 'IDEMPOTENCY_CONFLICT'
    assert command(workspace, binding())['code'] == 'DISCUSSION_VERSION_CONFLICT'
    assert command(workspace, value, version=2)['code'] == 'NO_CHANGE'
    with db.transaction() as connection:
        messages = connection.execute('SELECT * FROM conversation_messages ORDER BY id').fetchall()
        assert len(messages) == 2 and messages[-1]['guide_run_id'] is None and messages[-1]['phase_ref'] == 'p1'
        event = connection.execute('SELECT * FROM document_change_audits').fetchone()
        assert event['source_id'] == messages[-1]['id']
    assert counts(db)['guide_runs'] == counts(db)['llm_uses'] == counts(db)['requirement_documents'] == 0


def test_source_ownership_actual_revision_block_subset_and_scope(workspace):
    db, executor, resources = workspace
    create(executor, title='另一需求')
    target = document(workspace, kind='DESIGN', reference=resources.collaboration.reference('structure.design'))['data']['document']
    source = {'kind': 'REVISION', 'document_id': target['id'], 'revision_id': 1, 'block_ids': [target['block_state_json']['blocks'][0]['block_id']]}
    accepted = command(workspace, binding(target['id'], [source], {'scope_type': 'DOCUMENT', 'scope_ref': None}))
    assert accepted['code'] == 'UPDATED', accepted
    assert accepted['data']['discussion']['binding']['document_kind'] == 'design'
    before = counts(db)
    assert command(workspace, binding(target['id']), requirement_id=2)['code'] == 'SOURCE_INVALID'
    assert command(workspace, binding(refs=[{'kind': 'MESSAGE', 'message_id': 999}]), 2)['code'] == 'SOURCE_INVALID'
    assert command(workspace, binding(refs=[{**source, 'block_ids': [999]}]), 2)['code'] == 'SOURCE_INVALID'
    assert command(workspace, binding(target['id'], scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': 999}}), 2)['code'] == 'SCOPE_INVALID'
    assert command(workspace, binding(scope={'scope_type': 'DOCUMENT', 'scope_ref': None}), 2)['code'] == 'SCOPE_INVALID'
    assert counts(db) == before
    assert metadata(workspace, target['id'], 1, {'type': 'ARCHIVE'})['code'] == 'UPDATED'
    assert command(workspace, binding(target['id']), 2)['code'] == 'STATE_CONFLICT'


def test_focus_disposition_and_user_phase_closure_keep_history_and_business_status(workspace):
    db, executor, _ = workspace
    topic_fixture(workspace)
    assert update(executor, 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    assert command(workspace, {'type': 'SET_FOCUS', 'topic_ref': 't1'}, 2)['code'] == 'UPDATED'
    disposition = {'type': 'SET_DISPOSITION', 'subject_ref': 't1', 'decision': 'DECLINE_DRAFT', 'description': '先继续讨论'}
    result = command(workspace, disposition, 3)
    assert result['code'] == 'UPDATED', result
    user_decision = result['data']['discussion']['dispositions'][-1]
    assert user_decision['kind'] == 'REJECT_DRAFT'
    assert command(workspace, phase(unresolved=['t1']), 4)['code'] == 'UPDATED'
    detail = get_requirement(db, 1, expand='discussion')['data']
    state = detail['discussion']
    assert state['phase']['phase_ref'] == 'p2' and state['phase']['kind'] == 'SOLUTION' and state['phase']['closure'] is None
    assert state['topics'][0]['phase_ref'] == 'p1' and state['focus_topic_ref'] is None
    assert state['counters'] == {'phase': 3, 'topic': 2, 'evidence': 1}
    assert detail['requirement']['status'] == 'CLOSED' and detail['requirement']['metadata_version'] == 2
    with db.transaction() as connection:
        event = connection.execute("SELECT payload_json FROM document_change_audits WHERE event_type='PHASE_CHANGED'").fetchone()
        history = json.loads(event['payload_json'])
        assert history['phase_before']['phase_ref'] == 'p1'
        closure = history['phase_before']['closure']
        assert closure['unresolved_refs'] == ['t1']
        assert connection.execute('SELECT role FROM conversation_messages WHERE id=?', (closure['message_id'],)).fetchone()[0] == 'USER'
        assert connection.execute('SELECT role FROM conversation_messages WHERE id=?', (user_decision['message_id'],)).fetchone()[0] == 'USER'
    assert command(workspace, {'type': 'SET_FOCUS', 'topic_ref': 't1'}, 5)['code'] == 'SOURCE_INVALID'
    assert counts(db)['guide_runs'] == counts(db)['llm_uses'] == counts(db)['requirement_documents'] == 0


def test_occupancy_blocks_discussion_but_same_closed_status_is_independent(workspace):
    document(workspace)
    assert start(workspace)['code'] == 'DRAFT_STARTED'
    before = counts(workspace[0])
    assert command(workspace, phase())['code'] == 'WORK_STATE_CONFLICT'
    assert counts(workspace[0]) == before
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'


def test_failed_event_rolls_back_message_state_version_and_replay_can_later_succeed(workspace, monkeypatch):
    db = workspace[0]
    before = get_requirement(db, 1, expand='discussion')
    totals = counts(db)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('injected event failure')
    key = str(uuid4())
    with monkeypatch.context() as patch:
        patch.setattr(AuditRepository, 'record_discussion_update', fail)
        assert command(workspace, phase(), key=key)['code'] == 'STORAGE_UNAVAILABLE'
    assert get_requirement(db, 1, expand='discussion') == before and counts(db) == totals
    assert command(workspace, phase(), key=key)['code'] == 'UPDATED'


def test_same_discussion_version_race_commits_one_action(workspace):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda kind: command(workspace, phase(kind)), ['SOLUTION', 'REVIEW']))
    assert sorted(result['code'] for result in results) == ['DISCUSSION_VERSION_CONFLICT', 'UPDATED']
    assert counts(workspace[0])['conversation_messages'] == 2


def test_patch_dispatches_exact_union_and_keeps_safe_version_details(workspace):
    app = FastAPI();app.include_router(req_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    with TestClient(app) as client:
        key = {'Idempotency-Key': str(uuid4())}
        body = {'expected_discussion_version': 1, 'discussion_command': phase()}
        response = client.patch('/api/v1/requirements/1', json=body, headers=key)
        assert response.status_code == 200, response.text
        assert response.json()['data']['discussion_version'] == 2
        assert client.patch('/api/v1/requirements/1', json=body, headers=key).json()['data'] == response.json()['data']
        stale = client.patch('/api/v1/requirements/1', json=body, headers={'Idempotency-Key': str(uuid4())})
        assert stale.status_code == 409 and stale.json()['error']['code'] == 'DISCUSSION_VERSION_CONFLICT'
        for bad in [{**body, 'changes': {'title': 'mixed'}}, {**body, 'discussion_command': {**phase(), 'status': 'CLOSED'}},
            {'expected_discussion_version': 2, 'discussion_state_json': {}},
            {'expected_discussion_version': 2, 'discussion_command': {'type': 'SET_FOCUS', 'topic_ref': None}}]:
            assert client.patch('/api/v1/requirements/1', json=bad, headers={'Idempotency-Key': str(uuid4())}).status_code == 422


def test_discussion_counters_cannot_reuse_an_allocated_reference(workspace):
    state = get_requirement(workspace[0], 1, expand='discussion')['data']['discussion']
    state['counters']['phase'] = 1
    with pytest.raises(ValueError):
        validate_discussion(state)


def test_completed_analysis_is_a_source_but_private_or_missing_material_is_not(workspace):
    from backend.tests.requirements.test_v15_foundation import seed_running
    db = workspace[0]
    seed_running(db)
    result = {'kind': 'RUN_RESULT', 'guide_run_id': 10}
    with db.transaction(write=True) as connection:
        with pytest.raises(Rejected):
            verify_source_refs(connection, 1, [result])
        at = connection.execute('SELECT created_at FROM guide_runs WHERE id=10').fetchone()[0]
        analysis = {'conclusion': 'NO_CHANGE', 'summary': 'No changes needed', 'findings': [], 'covered_refs': [], 'unresolved': []}
        connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',ended_at=?,final_result_json=? WHERE id=10", (at, json.dumps({'analysis': analysis})))
        assert verify_source_refs(connection, 1, [result]) == [result]
        with pytest.raises(Rejected):
            verify_source_refs(connection, 2, [result])
        with pytest.raises(Rejected):
            verify_source_refs(connection, 1, [{'kind': 'RUN_MATERIAL', 'guide_run_id': 10, 'material_ref': 'authorization'}])


def test_card_source_requires_the_actual_owned_submitted_answer(workspace):
    db = workspace[0]
    at = get_requirement(db, 1)['data']['requirement']['created_at']
    card = {'card_key': 'c1', 'card_type': 'SINGLE_SELECT', 'question': 'Choose', 'context': '', 'required': False,
        'options': [{'option_key': value, 'label': value, 'description': '', 'impact': '', 'risks': ''} for value in ['a', 'b']],
        'selection_rule': {'min': 0, 'max': 1}, 'custom_answer': {'enabled': False, 'max_length': 0}, 'recommendation': None, 'related_spec_context': []}
    cards = {'schema_version': 1, 'intro': '', 'purpose': 'CLARIFICATION', 'cards': [card], 'action_payload': None,
        'program_binding': {'discussion_version': 1, 'target_content_version': None, 'source_heads': []}}
    answers = {'schema_version': 1, 'responses': [{'card_key': 'c1', 'selected_option_keys': ['a'], 'custom_answer': None, 'skipped': False}], 'execution_selection': None}
    # Explicit persisted card/answer fixture; this does not exercise or claim a model call.
    with db.transaction(write=True) as connection:
        connection.execute("INSERT INTO conversation_messages(id,requirement_id,guide_run_id,sequence_no,role,content,message_type,structured_content_json,reply_to_message_id,idempotency_key,created_at,phase_ref,topic_refs,document_ids) VALUES (20,1,NULL,2,'ASSISTANT','Choose','INTERACTION_CARDS',?,NULL,NULL,?,NULL,'[]','[]')", (json.dumps(cards), at))
        connection.execute("INSERT INTO conversation_messages(id,requirement_id,guide_run_id,sequence_no,role,content,message_type,structured_content_json,reply_to_message_id,idempotency_key,created_at,phase_ref,topic_refs,document_ids) VALUES (21,1,NULL,3,'USER','a','CARD_RESPONSE',?,20,?,?,NULL,'[]','[]')", (json.dumps(answers), str(uuid4()), at))
        source = {'kind': 'CARD_ANSWER', 'message_id': 21, 'card_key': 'c1'}
        assert verify_source_refs(connection, 1, [source]) == [source]
        for bad in [{**source, 'message_id': 20}, {**source, 'card_key': 'missing'}]:
            with pytest.raises(Rejected):
                verify_source_refs(connection, 1, [bad])
