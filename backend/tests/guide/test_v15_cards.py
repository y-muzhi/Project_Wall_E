"""Real C07 cards -> C06 program/model transactions, isolated offline APIs."""
import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_context import compiled
from backend.tests.guide.test_v15_execution import execute, Gateway, output, delta
from backend.tests.guide.test_v15_counting import offline_gate
from backend.app.guide.commands import submit_card_responses
from backend.app.messages.queries import list_messages
from backend.app.messages.api import message_router
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.shared.http_boundary import HttpRuntime


def card(keys=('a', 'b'), *, confirm=False):
    return {'card_key': 'c1', 'card_type': 'CONFIRM' if confirm else 'SINGLE_SELECT', 'question': '请选择下一步', 'context': '', 'required': True,
        'options': [{'option_key': key, 'label': ('确认以上事实和变更' if key == 'confirm' else '尚未确认' if key == 'defer' and keys[0] == 'confirm' else key),
            'description': '', 'impact': '', 'risks': ''} for key in keys], 'selection_rule': {'min': 1, 'max': 1},
        'custom_answer': {'enabled': False, 'max_length': 0}, 'recommendation': None, 'related_spec_context': []}


def group(purpose, payload=None):
    keys = ('a', 'b') if purpose == 'CLARIFICATION' else ('confirm', 'defer') if purpose == 'FACT_CONFIRMATION' else ('accept', 'defer')
    return {'schema_version': 1, 'intro': '', 'purpose': purpose, 'cards': [card(keys, confirm=purpose != 'CLARIFICATION')], 'action_payload': payload}


def seed_cards(workspace, monkeypatch, purpose='CLARIFICATION', *, progress=True, changes=None):
    offline_gate(monkeypatch)
    assert accept(workspace, **(changes or {}))['code'] == 'GUIDE_ACCEPTED'
    def returned(context):
        payload = None
        if purpose == 'PHASE_CHANGE':
            payload = {'phase_kind': 'SOLUTION', 'closure_summary': '目标已明确，保留待验证项', 'unresolved_refs': [],
                'basis_discussion_version': context.input['current_request']['basis_ref']['discussion_version']}
        if purpose == 'DOCUMENT_ACTION':
            payload = {'operation': 'GENERATE', 'target': {'kind': 'NEW', 'name': '建议新稿', 'document_kind': 'brief', 'template_ref': None},
                'scope': None, 'source_refs': [context.input['current_request']['message_ref']],
                'basis_discussion_version': context.input['current_request']['basis_ref']['discussion_version'], 'unresolved_impacts': [], 'selectable_fields': []}
        return output(context, cards=group(purpose, payload), progress_delta=delta(context) if progress else None)
    result = execute(workspace, Gateway(returned))
    assert result['code'] == 'AI_FINISHED', result
    messages = list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2])
    assert messages['code'] == 'READ_OK', messages
    return messages['data']['items'][-1]


def body(message, selected='a', *, selection=None, key=None):
    return {'message_id': message['id'], 'schema_version': 1, 'expected_discussion_version': message['structured_content']['program_binding']['discussion_version'],
        'responses': [{'card_key': 'c1', 'selected_option_keys': [selected], 'custom_answer': None, 'skipped': False}],
        'execution_selection': selection, 'idempotency_key': key or str(uuid4())}


def submit(workspace, request):
    return submit_card_responses(workspace[1], request, catalog=workspace[2])


def test_same_round_progress_binds_available_card_to_actual_final_version_then_answer_creates_new_discussion(workspace, monkeypatch):
    message = seed_cards(workspace, monkeypatch)
    assert message['card_state'] == 'AVAILABLE' and message['structured_content']['program_binding']['discussion_version'] == 3
    before = counts(workspace[0]);request = body(message)
    result = submit(workspace, request)
    assert result['code'] == 'CARDS_ACCEPTED', result
    assert result['data']['processing'] == 'MODEL' and result['data']['guide_run_id'] != message['guide_run_id']
    assert submit(workspace, request) == result
    assert counts(workspace[0])['guide_runs'] == before['guide_runs'] + 1 and counts(workspace[0])['llm_uses'] == before['llm_uses']
    context = compiled(workspace, result['data']['guide_run_id'])
    assert context.input['current_request']['content'] is None
    assert context.input['current_request']['formal_answers'][0]['selected_options'] == [{'option_key': 'a', 'label': 'a'}]
    assert context.input_json.count('请选择下一步') == 1
    rows = list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2])
    assert rows['code'] == 'READ_OK', rows
    assert next(row for row in rows['data']['items'] if row['id'] == message['id'])['card_state'] == 'ANSWERED'
    assert rows['data']['items'][-1]['guide_run_id'] == result['data']['guide_run_id']


def test_phase_confirmation_is_program_only_with_immutable_answer_and_readable_program_receipt(workspace, monkeypatch):
    message = seed_cards(workspace, monkeypatch, 'PHASE_CHANGE');before = counts(workspace[0]);request = body(message, 'accept')
    result = submit(workspace, request)
    assert result['code'] == 'PROGRAM_PROCESSED', result
    assert result['data']['processing'] == 'PROGRAM' and result['data']['result'] == 'APPLIED'
    assert counts(workspace[0])['guide_runs'] == before['guide_runs'] and counts(workspace[0])['llm_uses'] == before['llm_uses']
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get(1)
        assert root['discussion_state_json']['phase']['kind'] == 'SOLUTION' and root['document_work_state'] == 'IDLE'
    rows = list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2]);assert rows['code'] == 'READ_OK', rows
    formal = rows['data']['items'][-1]
    assert formal['guide_run_id'] is None and formal['program_receipt'] == result['data']
    assert submit(workspace, request) == result
    duplicate = submit(workspace, body(message, 'accept'))
    assert duplicate['code'] == 'CARD_ALREADY_ANSWERED' and duplicate['details']['response_message_id'] == formal['id']


def test_phase_card_resolves_same_round_topic_evidence_and_outcome_before_program_confirmation(workspace, monkeypatch):
    from backend.tests.guide.test_v15_progress import delta as progress_delta
    offline_gate(monkeypatch);assert accept(workspace)['code'] == 'GUIDE_ACCEPTED'
    def returned(context):
        payload = {'phase_kind': 'SOLUTION', 'closure_summary': '保留本轮待验证依据',
            'unresolved_refs': ['new_t1', 'new_e1', 'new_o1'],
            'basis_discussion_version': context.input['current_request']['basis_ref']['discussion_version']}
        return output(context, progress_delta=progress_delta(), cards=group('PHASE_CHANGE', payload))
    result = execute(workspace, Gateway(returned));assert result['code'] == 'AI_FINISHED', result
    rows = list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2]);assert rows['code'] == 'READ_OK', rows
    message = rows['data']['items'][-1]
    assert message['card_state'] == 'AVAILABLE'
    assert message['structured_content']['action_payload']['unresolved_refs'] == ['t1', 'e1', 't1:o1']
    result = submit(workspace, body(message, 'accept'));assert result['code'] == 'PROGRAM_PROCESSED', result
    with workspace[0].transaction() as connection:
        state = RequirementRepository(connection).get(1)['discussion_state_json']
        audit = json.loads(connection.execute("SELECT payload_json FROM document_change_audits WHERE event_type='PHASE_CHANGED' ORDER BY id DESC LIMIT 1").fetchone()[0])
        assert audit['phase_before']['closure']['unresolved_refs'] == ['t1', 'e1', 't1:o1']
        assert state['phase']['kind'] == 'SOLUTION'


@pytest.mark.parametrize('purpose', ['DOCUMENT_ACTION', 'PHASE_CHANGE'])
def test_defer_program_records_a_real_disposition_without_model_or_document_side_effect(workspace, monkeypatch, purpose):
    message = seed_cards(workspace, monkeypatch, purpose);before = counts(workspace[0])
    result = submit(workspace, body(message, 'defer'))
    assert result['code'] == 'PROGRAM_PROCESSED' and result['data']['result'] == 'DEFERRED', result
    assert all(counts(workspace[0])[key] == before[key] for key in ('guide_runs', 'llm_uses', 'requirement_documents', 'revisions'))
    with workspace[0].transaction() as connection:
        state = RequirementRepository(connection).get(1)['discussion_state_json']
        assert state['dispositions'][-1]['message_id'] == result['data']['user_message_id']


def test_document_action_accepts_one_fixed_new_target_and_does_not_rewrite_it_or_double_accept(workspace, monkeypatch):
    message = seed_cards(workspace, monkeypatch, 'DOCUMENT_ACTION');payload = message['structured_content']['action_payload']
    selection = {key: payload[key] for key in ('target', 'scope', 'source_refs')} | {'acknowledge_source_changes': False}
    before = counts(workspace[0]);wrong = {**selection, 'target': {**selection['target'], 'name': '擅自替换目标'}}
    assert submit(workspace, body(message, 'accept', selection=wrong))['code'] == 'SOURCE_INVALID'
    assert counts(workspace[0]) == before
    request = body(message, 'accept', selection=selection);result = submit(workspace, request)
    assert result['code'] == 'CARDS_ACCEPTED' and result['data']['processing'] == 'MODEL', result
    assert submit(workspace, request) == result
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT * FROM guide_runs WHERE id=?', (result['data']['guide_run_id'],)).fetchone()
        assert run['operation'] == 'GENERATE' and json.loads(run['execution_basis_json'])['request']['target'] == payload['target']
    assert counts(workspace[0])['requirement_documents'] == 0


@pytest.mark.parametrize('purpose', ['PHASE_CHANGE', 'CLARIFICATION'])
def test_http_uses_200_program_receipt_and_202_new_model_receipt_on_the_same_route(workspace, monkeypatch, purpose):
    message = seed_cards(workspace, monkeypatch, purpose)
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(message_router)
    request = body(message, 'accept' if purpose == 'PHASE_CHANGE' else 'a');key = request.pop('idempotency_key');request.pop('message_id')
    with TestClient(app) as client:
        response = client.post('/api/v1/conversation-messages/'+str(message['id'])+'/responses', json=request, headers={'Idempotency-Key': key})
        assert response.status_code == (200 if purpose == 'PHASE_CHANGE' else 202), response.text
        assert response.json()['data']['processing'] == ('PROGRAM' if purpose == 'PHASE_CHANGE' else 'MODEL')
        messages = client.get('/api/v1/requirements/1/messages')
        assert messages.status_code == 200, messages.text
        formal = messages.json()['data']['items'][-1]
        if purpose == 'PHASE_CHANGE':
            assert formal['program_receipt'] == response.json()['data']
        else:
            assert formal['guide_run_id'] == response.json()['data']['guide_run_id'] and formal['program_receipt'] is None


def test_exact_fact_confirmation_writes_directly_through_real_session_without_new_model_or_batch(workspace, monkeypatch):
    from backend.tests.requirements.test_v15_foundation import update
    from backend.app.documents.markdown import parse_markdown
    offline_gate(monkeypatch)
    current = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    assert accept(workspace, target={'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': 1},
        scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': 1}})['code'] == 'GUIDE_ACCEPTED'
    patch = {'title': '确认目标', 'explanation': '根据所给用户原话调整目标', 'impact': '目标章节', 'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': 1}, 'selector_json': None, 'original_content': parse_markdown(current['markdown_content']).blocks[0].markdown,
        'proposed_markdown': '# 用户确认的新目标', 'proposed_data_json': None}
    def returned(context):
        action = {'confirmed_fact_patches': [{'patch': patch, 'evidence': [{'message_id': context.input['current_request']['message_id'], 'quoted_text': '用户原话'}]}]}
        return output(context, cards=group('FACT_CONFIRMATION', action))
    result = execute(workspace, Gateway(returned));assert result['code'] == 'AI_FINISHED', result
    rows = list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2]);assert rows['code'] == 'READ_OK', rows
    message = rows['data']['items'][-1];assert message['card_state'] == 'AVAILABLE' and message['structured_content']['purpose'] == 'FACT_CONFIRMATION'
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    before = counts(workspace[0]);request = body(message, 'confirm');result = submit(workspace, request)
    assert result['code'] == 'PROGRAM_PROCESSED', result
    assert result['data']['document_effect']['result'] == 'UPDATED' and result['data']['document_effect']['after_content_version'] == 2
    assert counts(workspace[0])['guide_runs'] == before['guide_runs'] and counts(workspace[0])['llm_uses'] == before['llm_uses']
    assert submit(workspace, request) == result
    with workspace[0].transaction() as connection:
        actual = DocumentRepository(connection).get_current(1, current['id'])
        assert actual['markdown_content'].startswith('# 用户确认的新目标')
        assert connection.execute("SELECT count(*) FROM requirement_documents WHERE document_type='MANUAL_DRAFT'").fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM suggestion_batches').fetchone()[0] == 0
        sessions = connection.execute('SELECT * FROM manual_edit_sessions').fetchall()
        assert len(sessions) == 1 and sessions[0]['status'] == 'COMPLETED'
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'IDLE'
        assert RequirementRepository(connection).get(1)['status'] == 'CLOSED'
    assert list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2])['code'] == 'READ_OK'


def test_stale_version_invalid_selection_and_parallel_answers_do_not_half_write(workspace, monkeypatch):
    message = seed_cards(workspace, monkeypatch);before = counts(workspace[0])
    stale = body(message);stale['expected_discussion_version'] += 1
    assert submit(workspace, stale)['code'] == 'DISCUSSION_VERSION_CONFLICT'
    assert submit(workspace, body(message, 'not_an_option'))['code'] == 'INVALID_INPUT'
    assert counts(workspace[0]) == before
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda selected: submit(workspace, body(message, selected)), ['a', 'b']))
    assert sorted(result['code'] for result in results) == ['CARDS_ACCEPTED', 'CARD_ALREADY_ANSWERED']
    assert counts(workspace[0])['conversation_messages'] == before['conversation_messages']+1
    assert counts(workspace[0])['guide_runs'] == before['guide_runs']+1


def test_source_head_change_needs_explicit_ack_without_rebasing_fixed_revision(workspace, monkeypatch):
    from backend.tests.documents.test_v15_editing import start, candidate, save, finish
    offline_gate(monkeypatch)
    current = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    source = {'kind': 'REVISION', 'document_id': current['id'], 'revision_id': current['current_revision_id'], 'block_ids': None}
    assert accept(workspace, source_refs=[source])['code'] == 'GUIDE_ACCEPTED'
    def returned(context):
        action = {'operation': 'GENERATE', 'target': {'kind': 'NEW', 'name': '建议新稿', 'document_kind': 'brief', 'template_ref': None},
            'scope': None, 'source_refs': ['d1v1'], 'basis_discussion_version': context.input['current_request']['basis_ref']['discussion_version'],
            'unresolved_impacts': [], 'selectable_fields': []}
        return output(context, cards=group('DOCUMENT_ACTION', action))
    assert execute(workspace, Gateway(returned))['code'] == 'AI_FINISHED'
    message = list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2])['data']['items'][-1]
    draft = start(workspace)['data']['manual_draft'];saved = save(workspace, draft, candidate(workspace, draft, '# 已变更的来源'))
    assert saved['code'] == 'DRAFT_SAVED', saved
    assert finish(workspace, saved['data'])['code'] == 'DRAFT_COMPLETED'
    refreshed = list_messages(workspace[0], {'requirement_id': 1}, catalog=workspace[2])['data']['items'][-1]
    assert refreshed['id'] == message['id'] and refreshed['card_state'] == 'AVAILABLE'
    selection = {'target': message['structured_content']['action_payload']['target'], 'scope': None, 'source_refs': message['structured_content']['action_payload']['source_refs'], 'acknowledge_source_changes': False}
    before = counts(workspace[0]);result = submit(workspace, body(message, 'accept', selection=selection))
    assert result['code'] == 'SOURCE_VERSION_CONFLICT', result
    assert counts(workspace[0]) == before
    result = submit(workspace, body(message, 'accept', selection={**selection, 'acknowledge_source_changes': True}))
    assert result['code'] == 'CARDS_ACCEPTED', result
    with workspace[0].transaction() as connection:
        basis = json.loads(connection.execute('SELECT execution_basis_json FROM guide_runs WHERE id=?', (result['data']['guide_run_id'],)).fetchone()[0])
        captured = next(item for item in basis['source_snapshots'] if item['source_ref']['kind'] == 'REVISION')
        assert captured['value']['source_content_version'] == 1
