"""Explicit multi-document editing, persisted proofs, history and rollback."""
from copy import deepcopy
from uuid import uuid4
import sqlite3
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, create, counts, update
from backend.tests.documents.test_v15_documents import workspace, document, metadata
from backend.app.documents.commands import start_manual_draft, save_manual_draft, complete_manual_draft, cancel_manual_draft
from backend.app.documents.queries import get_current_document, get_manual_draft
from backend.app.documents.snapshot import assign_identities, validate_snapshot, Provenance
from backend.app.documents.markdown import parse_markdown
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.shared.http_boundary import HttpRuntime
from backend.app.documents.api import doc_router
from backend.app.requirements.queries import get_requirement


def start(workspace, identity=1, version=1, restore=None):
    body = {'requirement_id': 1, 'document_id': identity, 'expected_version': version, 'idempotency_key': str(uuid4())}
    if restore is not None:
        body['restore_revision_id'] = restore
    return start_manual_draft(workspace[1], body, catalog=workspace[2])


def test_detail_reports_the_actual_edit_target_for_reopening(workspace):
    document(workspace)
    document(workspace, name='另一文档')
    editing = start(workspace, identity=2)
    assert editing['code'] == 'DRAFT_STARTED', editing
    detail = get_requirement(workspace[0], 1)
    assert detail['code'] == 'READ_OK', detail
    active = detail['data']['active_operation']
    assert active == {'type': 'MANUAL_DRAFT', 'id': editing['data']['manual_draft']['id'], 'summary': '人工编辑中', 'target_document_id': 2}


def candidate(workspace, draft, markdown, identities=None):
    db, _, resources = workspace
    with db.transaction() as connection:
        sources = DocumentSources(connection, 1, resources, document_id=draft['target_document_id'])
        prior = validate_snapshot(draft['markdown_content'], draft['block_state_json'], sources)
        total = len(parse_markdown(markdown).blocks)
        if identities is None:
            identities = list(range(prior.next_block_id, prior.next_block_id + total))
        high = max([prior.next_block_id, *(identity + 1 for identity in identities)])
        return assign_identities(markdown, identities, high, prior, Provenance('USER', 'MANUAL_EDIT', draft['id']), draft['updated_at'], sources)


def save(workspace, draft, snapshot, key=None, **changes):
    return save_manual_draft(workspace[1], {'requirement_id': 1, 'document_id': draft['target_document_id'],
        'draft_id': draft['id'], 'expected_version': draft['content_version'],
        'markdown_content': snapshot.parsed.markdown, 'block_state_json': snapshot.state,
        'idempotency_key': key or str(uuid4()), **changes}, catalog=workspace[2])


def finish(workspace, draft, cancel=False, key=None, **changes):
    operation = cancel_manual_draft if cancel else complete_manual_draft
    options = {} if cancel else {'catalog': workspace[2]}
    return operation(workspace[1], {'requirement_id': 1, 'document_id': draft['target_document_id'],
        'draft_id': draft['id'], 'expected_version': draft['content_version'],
        'idempotency_key': key or str(uuid4()), **changes}, **options)


def test_no_change_completion_releases_session_without_creating_content(workspace):
    db, _, _ = workspace
    document(workspace)
    before = counts(db)
    draft = start(workspace)['data']['manual_draft']
    result = finish(workspace, draft)
    assert result['code'] == 'DRAFT_COMPLETED'
    assert result['data']['result'] == 'NO_CHANGE' and result['data']['after_content_version'] == 1
    assert counts(db) == before
    with db.transaction() as connection:
        assert connection.execute('SELECT document_work_state FROM requirements').fetchone()[0] == 'IDLE'
        assert connection.execute('SELECT status FROM manual_edit_sessions').fetchone()[0] == 'COMPLETED'
    assert get_manual_draft(db, 1, 1)['code'] == 'MANUAL_DRAFT_NOT_FOUND'


def test_two_documents_explicit_session_identity_and_previous_confirmation(workspace):
    db, executor, resources = workspace
    first = document(workspace)['data']
    second = document(workspace, name='参考文档')['data']['document']
    metadata(workspace, 1, 1, {'type': 'CONFIRM', 'expected_content_version': 1, 'revision_id': first['revision_id']})
    draft = start(workspace)['data']['manual_draft']
    assert draft['target_document_id'] == 1 and draft['base_content_version'] == 1
    assert get_manual_draft(db, 1, 2)['code'] == 'MANUAL_DRAFT_NOT_FOUND'
    incoming = candidate(workspace, draft, '# 新内容\n\n正文')
    assert save(workspace, draft, incoming, document_id=2)['code'] == 'MANUAL_DRAFT_NOT_FOUND'
    assert save(workspace, draft, incoming, draft_id=999)['code'] == 'MANUAL_DRAFT_NOT_FOUND'
    saved = save(workspace, draft, incoming)
    assert saved['code'] == 'DRAFT_SAVED', saved
    # User business state is free even while the real editor is occupied.
    assert update(executor, 1, {'status': 'CLOSED'})['code'] == 'UPDATED'
    effect = finish(workspace, saved['data'])
    assert effect['code'] == 'DRAFT_COMPLETED', effect
    assert effect['data']['result'] == 'UPDATED' and effect['data']['after_content_version'] == 2
    current = get_current_document(db, 1, 1, catalog=resources)['data']
    assert current['markdown_content'] == incoming.parsed.markdown
    assert current['current_revision_id'] != current['confirmed_revision_id'] == first['revision_id']
    assert get_current_document(db, 1, 2, catalog=resources)['data'] == second
    with db.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM revisions WHERE document_id=1').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM revisions WHERE document_id=2').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM manual_draft_context').fetchone()[0] == 0


def test_autosave_idempotency_stale_version_and_cancel_preserve_formal_body(workspace):
    db, _, resources = workspace
    original = document(workspace)['data']['document']
    draft = start(workspace)['data']['manual_draft']
    incoming = candidate(workspace, draft, '尚未提交的草稿')
    key = str(uuid4())
    saved = save(workspace, draft, incoming, key=key)
    assert saved['code'] == 'DRAFT_SAVED', saved
    assert save(workspace, draft, incoming, key=key) == saved
    assert save(workspace, draft, incoming)['code'] == 'CONTENT_VERSION_CONFLICT'
    assert get_current_document(db, 1, 1, catalog=resources)['data'] == original
    assert get_manual_draft(db, 1, 1, catalog=resources)['data'] == saved['data']
    assert finish(workspace, saved['data'], cancel=True)['code'] == 'DRAFT_CANCELLED'
    assert get_current_document(db, 1, 1, catalog=resources)['data'] == original
    with db.transaction() as connection:
        assert connection.execute('SELECT status FROM manual_edit_sessions').fetchone()[0] == 'CANCELLED'


def test_failed_formal_event_rolls_back_body_revision_and_session_close(workspace, monkeypatch):
    db, _, resources = workspace
    original = document(workspace)['data']['document']
    draft = start(workspace)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, '正式提交失败时保留草稿'))['data']
    before = counts(db)

    def fail(*args, **kwargs):
        raise sqlite3.IntegrityError('isolated content event failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(AuditRepository, 'record_content_commit', fail)
        assert finish(workspace, saved)['code'] == 'STORAGE_UNAVAILABLE'
    assert counts(db) == before
    assert get_current_document(db, 1, 1, catalog=resources)['data'] == original
    assert get_manual_draft(db, 1, 1, catalog=resources)['data'] == saved
    assert finish(workspace, saved)['data']['after_content_version'] == 2


def test_restore_goes_through_new_draft_and_never_rewinds_high_water_or_version(workspace):
    db, _, resources = workspace
    document(workspace)
    draft = start(workspace)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, '历史正文V2'))['data']
    revision2 = finish(workspace, saved)['data']['revision_id']
    metadata(workspace, 1, 1, {'type': 'CONFIRM', 'expected_content_version': 2, 'revision_id': revision2})
    draft = start(workspace, version=2)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, '后来改成V3'))['data']
    assert finish(workspace, saved)['data']['after_content_version'] == 3
    current = get_current_document(db, 1, 1, catalog=resources)['data']
    restoring = start(workspace, version=3, restore=revision2)
    assert restoring['code'] == 'DRAFT_STARTED', restoring
    restored = restoring['data']['manual_draft']
    assert restored['markdown_content'] == '历史正文V2'
    assert restored['block_state_json']['next_block_id'] > current['block_state_json']['next_block_id']
    assert get_current_document(db, 1, 1, catalog=resources)['data']['content_version'] == 3
    effect = finish(workspace, restored)
    assert effect['data']['after_content_version'] == 4
    head = get_current_document(db, 1, 1, catalog=resources)['data']
    assert head['confirmed_revision_id'] == revision2 and head['current_revision_id'] != revision2
    with db.transaction() as connection:
        import json
        sources = json.loads(connection.execute('SELECT source_refs_json FROM revisions WHERE id=?', (effect['data']['revision_id'],)).fetchone()[0])
        assert sources == [{'kind': 'REVISION', 'document_id': 1, 'revision_id': revision2, 'block_ids': None}]
        assert connection.execute('SELECT count(*) FROM revisions WHERE document_id=1').fetchone()[0] == 4


def test_wrong_restore_revision_rolls_back_new_draft_and_occupancy(workspace):
    db, _, _ = workspace
    document(workspace)
    other = document(workspace)['data']['revision_id']
    before = counts(db)
    assert start(workspace, restore=other)['code'] == 'SOURCE_INVALID'
    assert counts(db) == before
    with db.transaction() as connection:
        assert connection.execute('SELECT document_work_state FROM requirements').fetchone()[0] == 'IDLE'
        assert connection.execute('SELECT count(*) FROM manual_edit_sessions').fetchone()[0] == 0


def test_specification_heading_protection_uses_document_resource_not_business_status(workspace):
    db, executor, resources = workspace
    document(workspace, kind='SPECIFICATION', reference=resources.collaboration.reference('structure.specification'))
    update(executor, 1, {'status': 'COMPLETED'})
    draft = start(workspace)['data']['manual_draft']
    markdown = draft['markdown_content'].replace('# 1.', '# 99.', 1)
    incoming = candidate(workspace, draft, markdown, [block['block_id'] for block in draft['block_state_json']['blocks']])
    assert save(workspace, draft, incoming)['code'] == 'DOCUMENT_INVALID'
    assert get_manual_draft(db, 1, 1, catalog=resources)['data']['content_version'] == 1
    finish(workspace, draft, cancel=True)


def test_reanchoring_changes_only_the_edited_document(workspace):
    db, _, resources = workspace
    for _ in range(2):
        document(workspace, reference=resources.collaboration.reference('structure.brief'))
    with db.transaction(write=True) as connection:
        at = connection.execute('SELECT created_at FROM requirement_documents WHERE id=1').fetchone()[0]
        for identity in (1, 2):
            connection.execute("INSERT INTO comments(id,requirement_id,document_id,content,anchor_type,block_id,anchor_ref_json,anchor_status,status,resolved_at,deleted_at,created_at,updated_at) VALUES (?,1,?,'评论','BLOCK',1,?,'ATTACHED','OPEN',NULL,NULL,?,?)", (identity, identity, json.dumps({'block_markdown_snapshot': '# 需求简述'}), at, at))
    draft = start(workspace)['data']['manual_draft']
    blocks = parse_markdown(draft['markdown_content']).blocks
    markdown = draft['markdown_content'][blocks[1].start_offset:]
    ids = [block['block_id'] for block in draft['block_state_json']['blocks']][1:]
    saved = save(workspace, draft, candidate(workspace, draft, markdown, ids))['data']
    result = finish(workspace, saved)
    assert result['code'] == 'DRAFT_COMPLETED', result
    with db.transaction() as connection:
        assert [tuple(row) for row in connection.execute('SELECT document_id,anchor_status FROM comments ORDER BY id')] == [(1, 'ORPHANED'), (2, 'ATTACHED')]


def test_actual_http_edit_requires_document_session_key_and_returns_real_effect(workspace):
    db, executor, resources = workspace
    document(workspace)
    app = FastAPI()
    app.include_router(doc_router)
    app.state.walle_runtime = HttpRuntime(db, resources, executor)
    with TestClient(app) as client:
        headers = {'Idempotency-Key': str(uuid4())}
        response = client.post('/api/v1/requirements/1/manual-draft', json={'document_id': 1, 'expected_version': 1}, headers=headers)
        assert response.status_code == 201, response.text
        draft = response.json()['data']['manual_draft']
        assert client.get('/api/v1/requirements/1/manual-draft').status_code == 422
        assert client.get('/api/v1/requirements/1/manual-draft?document_id=1').status_code == 200
        incoming = candidate(workspace, draft, 'HTTP草稿')
        body = {'document_id': 1, 'draft_id': draft['id'], 'expected_version': 1, 'markdown_content': incoming.parsed.markdown, 'block_state_json': incoming.state}
        assert client.put('/api/v1/requirements/1/manual-draft', json=body).status_code == 422
        response = client.put('/api/v1/requirements/1/manual-draft', json=body, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 200, response.text
        response = client.post('/api/v1/requirements/1/manual-draft/complete', json={'document_id': 1, 'draft_id': draft['id'], 'expected_version': 2}, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 200, response.text
        assert response.json()['data']['result'] == 'UPDATED'
