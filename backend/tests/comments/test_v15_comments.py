"""Explicit document comment ownership, actual anchors and lifecycle guards."""
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.tests.requirements.test_v15_foundation import tmp_path, setup, update
from backend.tests.documents.test_v15_documents import workspace, document, metadata
from backend.tests.documents.test_v15_editing import start
from backend.app.comments.commands import create_comment, edit_comment, resolve_comment, reopen_comment, delete_comment
from backend.app.comments.queries import list_comments, get_comment, get_comment_index
from backend.app.comments.api import comment_router
from backend.app.shared.http_boundary import HttpRuntime


def comment(workspace, identity=1, **changes):
    return create_comment(workspace[1], {'requirement_id': 1, 'document_id': identity, 'expected_content_version': 1,
        'content': '请核对这一项。', 'anchor_type': 'BLOCK', 'block_id': 1, 'idempotency_key': str(uuid4()), **changes}, catalog=workspace[2])


def framework(workspace, name='需求说明'):
    return document(workspace, name=name, reference=workspace[2].collaboration.reference('structure.brief'))


def action(workspace, command, identity=1, **changes):
    return command(workspace[1], {'comment_id': identity, 'idempotency_key': str(uuid4()), **changes})


def test_comments_are_bound_to_the_selected_document(workspace):
    framework(workspace)
    framework(workspace, '独立材料')
    for identity in (1, 2):
        result = comment(workspace, identity)
        assert result['code'] == 'COMMENT_CREATED', result
        assert result['data']['document_id'] == identity
    for identity in (1, 2):
        payload = {'requirement_id': 1, 'document_id': identity}
        listing = list_comments(workspace[0], payload, catalog=workspace[2])
        assert listing['code'] == 'READ_OK', listing
        assert [row['id'] for row in listing['data']['items']] == [identity]
        index = get_comment_index(workspace[0], payload, catalog=workspace[2])
        assert index['code'] == 'READ_OK', index
        assert index['data']['total_count'] == index['data']['open_count'] == 1
        assert index['data']['comments'][0]['id'] == identity
    assert get_comment_index(workspace[0], {'requirement_id': 2, 'document_id': 1})['code'] == 'NOT_FOUND'


def test_closed_requirement_allows_comment_lifecycle(workspace):
    framework(workspace)
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    assert comment(workspace)['code'] == 'COMMENT_CREATED'
    assert action(workspace, edit_comment, content='新的说明')['data']['content'] == '新的说明'
    assert action(workspace, resolve_comment)['data']['status'] == 'RESOLVED'
    assert action(workspace, edit_comment, content='不可编辑已解决项')['code'] == 'STATE_CONFLICT'
    assert action(workspace, reopen_comment)['data']['resolved_at'] is None
    assert action(workspace, delete_comment)['data']['deleted_at'] is not None
    assert get_comment(workspace[0], 1)['data']['content'] == '新的说明'
    assert list_comments(workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2])['data']['total'] == 0


def test_archived_and_occupied_documents_cannot_change_comments(workspace):
    framework(workspace)
    assert comment(workspace)['code'] == 'COMMENT_CREATED'
    assert metadata(workspace, 1, 1, {'type': 'ARCHIVE'})['code'] == 'UPDATED'
    assert comment(workspace)['code'] == 'STATE_CONFLICT'
    assert action(workspace, resolve_comment)['code'] == 'STATE_CONFLICT'
    assert get_comment_index(workspace[0], {'requirement_id': 1, 'document_id': 1}, catalog=workspace[2])['code'] == 'READ_OK'
    assert metadata(workspace, 1, 2, {'type': 'RESTORE'})['code'] == 'UPDATED'
    assert start(workspace)['code'] == 'DRAFT_STARTED'
    assert comment(workspace)['code'] == 'WORK_STATE_CONFLICT'
    assert action(workspace, delete_comment)['code'] == 'WORK_STATE_CONFLICT'


def test_http_strict_target_selection_and_selection_anchor(workspace):
    framework(workspace)
    app = FastAPI()
    app.include_router(comment_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    with TestClient(app) as client:
        for path in ('comments', 'comment-index'):
            assert client.get('/api/v1/requirements/1/' + path).status_code == 422
        body = {'document_id': 1, 'expected_content_version': 1, 'content': '说明', 'anchor_type': 'BLOCK', 'block_id': 1}
        invalid = client.post('/api/v1/requirements/1/comments', json={**body, 'selection': None}, headers={'Idempotency-Key': str(uuid4())})
        assert invalid.status_code == 422
        response = client.post('/api/v1/requirements/1/comments', json=body, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 201, response.text
        assert response.json()['data']['document_id'] == 1
        listing = client.get('/api/v1/requirements/1/comments?document_id=1')
        assert listing.status_code == 200, listing.text
        assert listing.json()['data']['items'][0]['location']['status'] == 'ATTACHED'
        index = client.get('/api/v1/requirements/1/comment-index?document_id=1')
        assert index.status_code == 200, index.text
    invalid = comment(workspace, block_id=999)
    assert invalid['code'] == 'ANCHOR_INVALID'
