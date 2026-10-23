"""Real isolated history reads, user marks and existing HTTP paths."""
from uuid import uuid4
import sqlite3
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from backend.tests.requirements.test_v15_foundation import tmp_path, setup, update, counts
from backend.tests.documents.test_v15_documents import workspace, document
from backend.tests.documents.test_v15_editing import start, candidate, save, finish
from backend.app.revisions.commands import create_manual_revision
from backend.app.revisions.queries import list_revisions, get_revision
from backend.app.revisions.api import rev_router
from backend.app.shared.http_boundary import HttpRuntime


def mark(workspace, identity=1, version=1, text='发布前复核', key=None):
    return create_manual_revision(workspace[1], {'requirement_id': 1, 'document_id': identity,
        'expected_version': version, 'description': text, 'idempotency_key': key or str(uuid4())}, catalog=workspace[2])


def test_marks_are_separate_immutable_idempotent_events(workspace):
    document(workspace)
    before = counts(workspace[0])
    key = str(uuid4())
    result = mark(workspace, key=key)
    assert result['code'] == 'VERSION_MARKED', result
    assert mark(workspace, key=key) == result
    assert mark(workspace, text='另一说明', key=key)['code'] == 'IDEMPOTENCY_CONFLICT'
    second = mark(workspace, text='第二次检查')
    assert second['data']['revision_id'] == result['data']['revision_id']
    history = list_revisions(workspace[0], {'requirement_id': 1, 'document_id': 1})
    assert history['code'] == 'READ_OK', history
    row = history['data']['items'][0]
    assert [item['description'] for item in row['markers']] == ['发布前复核', '第二次检查']
    after = counts(workspace[0])
    assert after['revisions'] == before['revisions']
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT description FROM revisions WHERE id=?', (row['id'],)).fetchone()[0] is None
    with pytest.raises(sqlite3.IntegrityError), workspace[0].transaction(write=True) as connection:
        connection.execute("UPDATE revisions SET description='覆盖' WHERE id=?", (row['id'],))


def test_history_is_document_scoped_and_snapshots_survive_edit(workspace):
    document(workspace)
    document(workspace, name='参考材料')
    original = get_revision(workspace[0], 1, catalog=workspace[2])
    draft = start(workspace)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, '新的正文'))['data']
    assert finish(workspace, saved)['code'] == 'DRAFT_COMPLETED'
    history = list_revisions(workspace[0], {'requirement_id': 1, 'document_id': 1})
    assert [row['version_no'] for row in history['data']['items']] == [2, 1]
    assert {row['document_id'] for row in history['data']['items']} == {1}
    assert get_revision(workspace[0], 1, catalog=workspace[2]) == original
    other = list_revisions(workspace[0], {'requirement_id': 1, 'document_id': 2})
    assert other['data']['total'] == 1
    assert list_revisions(workspace[0], {'requirement_id': 2, 'document_id': 1})['code'] == 'NOT_FOUND'
    assert mark(workspace, version=1)['code'] == 'CONTENT_VERSION_CONFLICT'


def test_closed_status_is_allowed_but_occupied_mark_is_rejected(workspace):
    document(workspace)
    assert update(workspace[1], 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    assert mark(workspace)['code'] == 'VERSION_MARKED'
    assert start(workspace)['code'] == 'DRAFT_STARTED'
    assert mark(workspace)['code'] == 'WORK_STATE_CONFLICT'


def test_http_requires_document_and_marks_without_creating_revision(workspace):
    app = FastAPI()
    app.include_router(rev_router)
    app.state.walle_runtime = HttpRuntime(workspace[0], workspace[2], workspace[1])
    document(workspace)
    with TestClient(app) as client:
        assert client.get('/api/v1/requirements/1/revisions').status_code == 422
        result = client.post('/api/v1/requirements/1/revisions', headers={'Idempotency-Key': str(uuid4())}, json={'document_id': 1, 'expected_version': 1})
        assert result.status_code == 200, result.text
        assert result.json()['data']['marked'] is True
        listing = client.get('/api/v1/requirements/1/revisions?document_id=1')
        assert listing.status_code == 200, listing.text
        assert listing.json()['data']['items'][0]['markers'][0]['description'] is None
        snapshot = client.get('/api/v1/revisions/1')
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()['data']['document_id'] == 1
