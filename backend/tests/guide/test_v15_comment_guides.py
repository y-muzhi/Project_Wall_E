"""Actual comment-owned proposals and frozen source snapshot; no provider I/O."""
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, counts, update
from backend.tests.documents.test_v15_documents import workspace, document, metadata
from backend.tests.comments.test_v15_comments import comment
from backend.tests.guide.test_v15_execution import execute, Gateway, output
from backend.tests.guide.test_v15_counting import offline_gate
from backend.tests.guide.test_v15_context import compiled
from backend.app.guide.commands import modify_from_comment, retry_guide_run, fail_guide_run
from backend.app.guide.queries import get_guide_run
from backend.app.guide.api import guide_router
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.documents.markdown import parse_markdown
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.comments.commands import edit_comment


def source(workspace):
    current = document(workspace, reference=workspace[2].collaboration.reference('structure.brief'))['data']['document']
    other = document(workspace, name='独立阅读稿')['data']['document']
    actual = comment(workspace, identity=current['id'])
    assert actual['code'] == 'COMMENT_CREATED', actual
    return current, other, actual['data']


def body(identity=1, **changes):
    return {'comment_id': identity, 'expected_content_version': 1, 'expected_discussion_version': 1, 'idempotency_key': str(uuid4()), **changes}


def test_comment_acceptance_has_two_versions_actual_owner_and_frozen_original_source(workspace):
    current, other, original = source(workspace)
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    request = body(original['id']);result = modify_from_comment(workspace[1], request, catalog=workspace[2])
    assert result['code'] == 'GUIDE_ACCEPTED', result
    assert result['data']['processing'] == 'MODEL'
    assert modify_from_comment(workspace[1], request, catalog=workspace[2]) == result
    with workspace[0].transaction() as connection:
        run = connection.execute('SELECT * FROM guide_runs').fetchone();basis = json.loads(run['execution_basis_json'])
        assert run['operation'] == 'PROPOSE_CHANGES' and run['source_type'] == 'COMMENT' and run['source_id'] == original['id']
        assert run['target_document_id'] == current['id'] != other['id']
        assert basis['comment_source'] == original and basis['request']['instruction'] == original['content']
        assert RequirementRepository(connection).get(1)['status'] == 'CLOSED'
    context = compiled(workspace)
    assert context.input['current_request']['operation'] == 'PROPOSE_CHANGES'
    assert context.input_json.count(original['content']) == 1
    assert context.input['documents'][0]['document_id'] == current['id']
    anchor = next(item for item in context.basis['selected'] if item['ref'] == 'r1:comment_anchor')
    assert anchor['kind'] == 'RUN_MATERIAL' and anchor['source_refs'][0]['guide_run_id'] == result['data']['guide_run_id']
    assert counts(workspace[0])['llm_uses'] == 0


def test_comment_proposal_uses_existing_batch_without_writing_or_resolving_source(workspace, monkeypatch):
    offline_gate(monkeypatch);current, other, original = source(workspace)
    accepted = modify_from_comment(workspace[1], body(original['id']), catalog=workspace[2]);assert accepted['code'] == 'GUIDE_ACCEPTED', accepted
    patch = {'title': '落实评论', 'explanation': '调整本条评论的目标', 'impact': '当前目标章节', 'patch_operation': 'REPLACE_BLOCK',
        'target_ref': {'block_id': 1}, 'selector_json': None, 'original_content': parse_markdown(current['markdown_content']).blocks[0].markdown,
        'proposed_markdown': '# 评论建议的新目标', 'proposed_data_json': None}
    result = execute(workspace, Gateway(lambda context: output(context, response_type='CHANGE_PROPOSALS', suggestions=[patch])))
    assert result['code'] == 'AI_FINISHED', result
    run = get_guide_run(workspace[0], accepted['data']['guide_run_id']);assert run['code'] == 'READ_OK', run
    assert run['data']['application_result'] == 'APPLIED' and run['data']['suggestion_batch_id'] is not None
    with workspace[0].transaction() as connection:
        batch = connection.execute('SELECT * FROM suggestion_batches').fetchone()
        assert batch['target_document_id'] == current['id'] and batch['source_type'] == 'COMMENT' and batch['source_id'] == original['id']
        assert connection.execute('SELECT status FROM comments WHERE id=?', (original['id'],)).fetchone()[0] == 'OPEN'
        assert RequirementRepository(connection).get(1)['document_work_state'] == 'SUGGESTION_REVIEWING'
        assert all(row['content_version'] == 1 for row in connection.execute("SELECT content_version FROM requirement_documents WHERE document_type='CURRENT'"))


def test_stale_discussion_or_content_and_archived_comment_target_cannot_save_a_run(workspace):
    current, _, original = source(workspace);before = counts(workspace[0])
    for changes, code in [({'expected_discussion_version': 99}, 'DISCUSSION_VERSION_CONFLICT'), ({'expected_content_version': 99}, 'CONTENT_VERSION_CONFLICT')]:
        assert modify_from_comment(workspace[1], body(original['id'], **changes), catalog=workspace[2])['code'] == code
        assert counts(workspace[0]) == before
    assert metadata(workspace, current['id'], 1, {'type': 'ARCHIVE'})['code'] == 'UPDATED'
    assert modify_from_comment(workspace[1], body(original['id']), catalog=workspace[2])['code'] == 'STATE_CONFLICT'


def test_failed_comment_retry_keeps_source_and_rejects_changed_comment_without_another_input(workspace):
    _, _, original = source(workspace);assert modify_from_comment(workspace[1], body(original['id']), catalog=workspace[2])['code'] == 'GUIDE_ACCEPTED'
    assert fail_guide_run(workspace[0], {'guide_run_id': 1, 'error_code': 'CONFIG_INVALID', 'safe_message': '离线准入未完成'}, process_lock=workspace[1].process_lock)['code'] == 'RUN_FAILED'
    changed = edit_comment(workspace[1], {'comment_id': original['id'], 'content': '修改后的评论', 'idempotency_key': str(uuid4())})
    assert changed['code'] == 'COMMENT_UPDATED', changed
    before = counts(workspace[0]);result = retry_guide_run(workspace[1], {'guide_run_id': 1, 'idempotency_key': str(uuid4())}, catalog=workspace[2])
    assert result['code'] == 'SOURCE_INVALID', result
    assert counts(workspace[0]) == before


def test_comment_route_returns_only_new_receipt_and_requires_both_versions(workspace):
    _, _, original = source(workspace)
    app = FastAPI();app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1]);app.include_router(guide_router)
    with TestClient(app) as client:
        path = '/api/v1/comments/'+str(original['id'])+'/guide-runs'
        assert client.post(path, json={'expected_content_version': 1}, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
        result = client.post(path, json={'expected_content_version': 1, 'expected_discussion_version': 1}, headers={'Idempotency-Key': str(uuid4())})
        assert result.status_code == 202, result.text
        assert set(result.json()['data']) == {'processing', 'guide_run_id', 'user_message_id'}
