"""Actual V1.5 proposal -> decisions -> one atomic target CONTENT commit."""
import json
import sqlite3
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts, update
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.guide.test_v15_acceptance import accept
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_execution import execute, Gateway, output
from backend.app.documents.markdown import parse_markdown
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.suggestions.commands import decide_suggestion, complete_batch, discard_batch
from backend.app.suggestions.queries import get_batch
from backend.app.suggestions.api import batch_router
from backend.app.shared.http_boundary import HttpRuntime


def pending(workspace, monkeypatch):
    offline_gate(monkeypatch)
    source = document(workspace, name='只读来源', reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    target = document(workspace, name='实际目标', reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    with workspace[0].transaction() as connection:
        revision = connection.execute('SELECT id FROM revisions WHERE document_id=?', (source['id'],)).fetchone()[0]
    refs = [{'kind': 'REVISION', 'document_id': source['id'], 'revision_id': revision, 'block_ids': None}]
    accepted = accept(workspace, operation='PROPOSE_CHANGES', target={'kind': 'EXISTING', 'document_id': target['id'], 'expected_content_version': 1},
        scope={'scope_type': 'DOCUMENT', 'scope_ref': None}, source_refs=refs)
    assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    blocks = parse_markdown(target['markdown_content']).blocks
    patches = [{'title': '修改'+str(index), 'explanation': '落实用户目标', 'impact': None, 'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': target['block_state_json']['blocks'][index]['block_id']}, 'selector_json': None, 'original_content': blocks[index].markdown,
        'proposed_markdown': '# 调整后的目标' if index == 0 else '新的目标说明。', 'proposed_data_json': None} for index in (0, 1)]
    result = execute(workspace, Gateway(lambda context: output(context, response_type='CHANGE_PROPOSALS', suggestions=patches)))
    assert result['code'] == 'AI_FINISHED', result
    read = get_batch(workspace[0], 1, catalog=workspace[2]);assert read['code'] == 'READ_OK', read
    assert read['data']['target_document_id'] == target['id'] and refs[0] in read['data']['source_refs']
    return source, target, read['data']


def decide(workspace, identity, decision='ACCEPTED', content=None):
    payload = {'suggestion_id': identity, 'decision': decision, 'idempotency_key': str(uuid4())}
    if decision == 'EDITED': payload['edited_content'] = content
    return decide_suggestion(workspace[1], payload, catalog=workspace[2])


def complete(workspace, **changes):
    return complete_batch(workspace[1], {'batch_id': 1, 'expected_content_version': 1, 'idempotency_key': str(uuid4()), **changes}, catalog=workspace[2])


def test_edited_and_rejected_decisions_only_write_target_on_completion_with_real_revision_and_idempotency(workspace, monkeypatch):
    source, target, batch = pending(workspace, monkeypatch);before = counts(workspace[0])
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    assert decide(workspace, batch['suggestions'][0]['id'], 'EDITED', '# 人工确认的目标')['code'] == 'SUGGESTION_DECIDED'
    assert complete(workspace)['code'] == 'BATCH_PENDING'
    assert decide(workspace, batch['suggestions'][1]['id'], 'REJECTED')['code'] == 'SUGGESTION_DECIDED'
    request = {'batch_id': 1, 'expected_content_version': 1, 'idempotency_key': str(uuid4())}
    result = complete_batch(workspace[1], request, catalog=workspace[2]);assert result['code'] == 'BATCH_APPLIED', result
    assert complete_batch(workspace[1], request, catalog=workspace[2]) == result
    effect = result['data']['document_effect'];assert effect['document_id'] == target['id'] and effect['after_content_version'] == 2
    assert result['data']['applied_suggestion_ids'] == [batch['suggestions'][0]['id']]
    with workspace[0].transaction() as connection:
        actual = DocumentRepository(connection).get_current(1, target['id'])
        assert actual['markdown_content'].startswith('# 人工确认的目标')
        assert actual['markdown_content'].split('\n', 1)[1] == target['markdown_content'].split('\n', 1)[1]
        assert DocumentRepository(connection).get_current(1, source['id'])['markdown_content'] == source['markdown_content']
        revision = connection.execute('SELECT * FROM revisions WHERE id=?', (effect['revision_id'],)).fetchone()
        assert revision['document_id'] == target['id'] and revision['source_content_version'] == 2
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'IDLE'
        assert RequirementRepository(connection).get(1)['status'] == 'CLOSED'
    assert counts(workspace[0])['llm_uses'] == before['llm_uses']
    assert counts(workspace[0])['revisions'] == before['revisions']+1


def test_all_rejected_is_no_change_and_discard_preserves_decisions_and_content(workspace, monkeypatch):
    source, target, batch = pending(workspace, monkeypatch);before = counts(workspace[0])
    for item in batch['suggestions']: assert decide(workspace, item['id'], 'REJECTED')['code'] == 'SUGGESTION_DECIDED'
    result = complete(workspace);assert result['code'] == 'BATCH_NO_CHANGE', result
    assert result['data']['document_effect']['result'] == 'NO_CHANGE' and result['data']['applied_suggestion_ids'] == []
    assert counts(workspace[0])['revisions'] == before['revisions']


def test_discard_works_with_pending_decisions_without_changing_any_document(workspace, monkeypatch):
    source, target, batch = pending(workspace, monkeypatch);before = counts(workspace[0])
    assert decide(workspace, batch['suggestions'][0]['id'])['code'] == 'SUGGESTION_DECIDED'
    request = {'batch_id': 1, 'idempotency_key': str(uuid4())};result = discard_batch(workspace[1], request)
    assert result['code'] == 'BATCH_DISCARDED', result
    assert discard_batch(workspace[1], request) == result
    actual = get_batch(workspace[0], 1, catalog=workspace[2]);assert actual['code'] == 'READ_OK', actual
    assert actual['data']['suggestions'][0]['status'] == 'ACCEPTED' and actual['data']['counts']['pending'] == 1
    assert counts(workspace[0])['revisions'] == before['revisions']


def test_wrong_version_rejects_and_storage_failure_rolls_back_whole_adoption(workspace, monkeypatch):
    _, target, batch = pending(workspace, monkeypatch)
    for item in batch['suggestions']: assert decide(workspace, item['id'])['code'] == 'SUGGESTION_DECIDED'
    assert complete(workspace, expected_content_version=9)['code'] == 'CONTENT_VERSION_CONFLICT'
    before = counts(workspace[0]);original = AuditRepository.record_content_commit
    def unavailable(*args, **kwargs): raise sqlite3.OperationalError('fixture write unavailable')
    monkeypatch.setattr(AuditRepository, 'record_content_commit', unavailable)
    assert complete(workspace)['code'] == 'STORAGE_UNAVAILABLE'
    assert counts(workspace[0]) == before
    with workspace[0].transaction() as connection:
        assert DocumentRepository(connection).get_current(1, target['id'])['content_version'] == 1
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'SUGGESTION_REVIEWING'
    monkeypatch.setattr(AuditRepository, 'record_content_commit', original)
    assert complete(workspace)['code'] == 'BATCH_APPLIED'


def test_actual_http_read_decide_and_complete_preserve_target_effect_and_forbid_null_edit(workspace, monkeypatch):
    _, target, batch = pending(workspace, monkeypatch)
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(batch_router)
    with TestClient(app) as client:
        read = client.get('/api/v1/suggestion-batches/1');assert read.status_code == 200, read.text
        for item in batch['suggestions']:
            path = '/api/v1/suggestions/'+str(item['id'])+'/decision'
            assert client.put(path, json={'decision': 'REJECTED', 'edited_content': None}, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
            decided = client.put(path, json={'decision': 'REJECTED'}, headers={'Idempotency-Key': str(uuid4())})
            assert decided.status_code == 200, decided.text
        result = client.post('/api/v1/suggestion-batches/1/complete', json={'expected_content_version': 1}, headers={'Idempotency-Key': str(uuid4())})
        assert result.status_code == 200, result.text
        assert result.json()['data']['document_effect']['document_id'] == target['id']
        assert set(result.json()['data']['current_document']) == {'id', 'requirement_id', 'document_type', 'markdown_content', 'block_state_json', 'content_version', 'created_at', 'updated_at'}


def test_precise_row_adoption_keeps_non_target_row_and_records_user_edited_batch_provenance(workspace, monkeypatch):
    from backend.tests.documents.test_v15_editing import start, candidate, save, finish
    from backend.app.documents.tables import table_model
    offline_gate(monkeypatch)
    current = document(workspace)['data']['document'];draft = start(workspace, current['id'])['data']['manual_draft']
    markdown = '| key | value |\n| --- | --- |\n| A | original |\n| B | untouched |\n'
    snapshot = candidate(workspace, draft, markdown);saved = save(workspace, draft, snapshot)
    assert saved['code'] == 'DRAFT_SAVED', saved
    assert finish(workspace, saved['data'])['code'] == 'DRAFT_COMPLETED'
    with workspace[0].transaction() as connection:
        actual = DocumentRepository(connection).get_current(1, current['id']);state = json.loads(actual['block_state_json'])
    identity = state['blocks'][0]['block_id'];table = table_model(parse_markdown(markdown).blocks[0])
    result = accept(workspace, operation='PROPOSE_CHANGES', target={'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': 2},
        scope={'scope_type': 'BLOCK', 'scope_ref': {'block_id': identity}})
    assert result['code'] == 'GUIDE_ACCEPTED', result
    patch = {'title': '调整A行', 'explanation': '保留其余行', 'impact': None, 'patch_operation': 'REPLACE_TABLE_ROW',
        'target_ref': {'block_id': identity}, 'selector_json': {'key_column_index': 0, 'key_value': 'A'},
        'original_content': table.rows[0].markdown, 'proposed_markdown': None, 'proposed_data_json': {'cells': ['A', 'proposed']}}
    assert execute(workspace, Gateway(lambda context: output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch])))['code'] == 'AI_FINISHED'
    batch = get_batch(workspace[0], 1, catalog=workspace[2]);assert batch['code'] == 'READ_OK', batch
    assert decide(workspace, batch['data']['suggestions'][0]['id'], 'EDITED', '{"cells":["A","user edit"]}')['code'] == 'SUGGESTION_DECIDED'
    result = complete(workspace, expected_content_version=2);assert result['code'] == 'BATCH_APPLIED', result
    with workspace[0].transaction() as connection:
        actual = DocumentRepository(connection).get_current(1, current['id'])
        assert '| B | untouched |\n' in actual['markdown_content']
        assert list(table_model(parse_markdown(actual['markdown_content']).blocks[0]).rows[0].cells) == ['A', 'user edit']
        metadata = json.loads(actual['block_state_json'])['blocks'][0]
        assert metadata['block_id'] == identity and metadata['last_modified_by_type'] == 'USER' and metadata['last_modified_source_type'] == 'SUGGESTION_BATCH'
