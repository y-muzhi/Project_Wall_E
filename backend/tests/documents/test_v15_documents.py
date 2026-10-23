"""V1.5 multi-document create/read/metadata with real transactions and HTTP."""
from uuid import uuid4
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.documents.api import doc_router
from backend.app.documents.commands import create_document, update_document_metadata
from backend.app.documents.queries import get_current_document
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.queries import get_requirement
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.requirements.test_v15_foundation import tmp_path, setup, create, update, counts, seed_running


@pytest.fixture
def workspace(setup):
    db, executor = setup
    create(executor)
    return db, executor, ResourceCatalog()


def document(workspace, *, name='需求说明', kind='REQUIREMENT_BRIEF', reference=None, key=None, requirement_id=1):
    db, executor, resources = workspace
    return create_document(executor, {'requirement_id': requirement_id, 'name': name, 'document_kind': kind,
        'template_ref': reference, 'idempotency_key': key or str(uuid4())}, catalog=resources)


def metadata(workspace, identity, version, change, key=None):
    return update_document_metadata(workspace[1], {'document_id': identity, 'expected_metadata_version': version,
        'change': change, 'idempotency_key': key or str(uuid4())}, catalog=workspace[2])


def test_empty_and_same_named_current_documents_have_independent_identity_and_v1(workspace):
    db, executor, resources = workspace
    one, two = document(workspace), document(workspace)
    assert one['code'] == two['code'] == 'CREATED'
    assert one['data']['document']['id'] != two['data']['document']['id']
    assert one['data']['document']['markdown_content'] == ''
    assert one['data']['document']['block_state_json'] == {'schema_version': 1, 'next_block_id': 1, 'blocks': []}
    detail = get_requirement(db, 1)['data']
    assert [item['id'] for item in detail['documents']] == [1, 2]
    assert detail['requirement']['document_work_state'] == 'IDLE'
    with db.transaction() as connection:
        rows = connection.execute('SELECT * FROM revisions ORDER BY id').fetchall()
        assert len(rows) == 2
        assert all(row['revision_type'] == 'CONTENT' and row['version_no'] == row['source_content_version'] == 1 for row in rows)
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    assert counts(db)['guide_runs'] == counts(db)['llm_uses'] == 0


@pytest.mark.parametrize('kind,profile', [('REQUIREMENT_BRIEF', 'brief'), ('DESIGN', 'design'), ('SPECIFICATION', 'specification')])
def test_fixed_frameworks_use_their_own_type_resources_and_actual_provenance(workspace, kind, profile):
    db, _, resources = workspace
    reference = resources.collaboration.reference('structure.' + profile)
    created = document(workspace, kind=kind, reference=reference)
    assert created['code'] == 'CREATED', created
    current = created['data']['document']
    assert current['template_ref'] == reference
    if profile == 'specification':
        assert current['markdown_content'] == resources.template('NEW', 'new-requirement', 'v4').markdown
    else:
        assert current['markdown_content'].startswith('# 1. ')
        assert len(current['block_state_json']['blocks']) == 7
    assert all(block['created_source_type'] == 'TEMPLATE' and block['created_by_type'] == 'SYSTEM' for block in current['block_state_json']['blocks'])
    assert get_current_document(db, 1, current['id'], catalog=resources)['data'] == current


def test_wrong_resource_or_arbitrary_markdown_is_rejected_without_partial_document(workspace):
    db, _, resources = workspace
    reference = resources.collaboration.reference('structure.design')
    assert document(workspace, reference=reference)['code'] == 'TEMPLATE_INVALID'
    reference = resources.collaboration.reference('structure.brief')
    assert document(workspace, reference={**reference, 'digest': '0' * 64})['code'] == 'TEMPLATE_INVALID'
    value = {'requirement_id': 1, 'name': '无效输入', 'document_kind': 'DESIGN', 'template_ref': None,
        'markdown_content': 'caller cannot forge a fixed framework', 'idempotency_key': str(uuid4())}
    assert create_document(workspace[1], value, catalog=resources)['code'] == 'INVALID_INPUT'
    assert counts(db)['requirement_documents'] == counts(db)['revisions'] == 0
    assert counts(db)['conversation_messages'] == 1


def test_read_requires_exact_owned_target_and_never_falls_back_to_another_current(workspace):
    db, _, resources = workspace
    document(workspace)
    document(workspace, name='文档二')
    assert get_current_document(db, 1, catalog=resources)['code'] == 'INVALID_INPUT'
    assert get_current_document(db, 1, 999, catalog=resources)['code'] == 'NOT_FOUND'
    assert get_current_document(db, 999, 1, catalog=resources)['code'] == 'NOT_FOUND'
    assert get_current_document(db, 1, 2, catalog=resources)['data']['name'] == '文档二'


def test_confirmation_is_revision_specific_and_metadata_actions_never_change_content(workspace):
    db, _, resources = workspace
    first = document(workspace)['data']
    other = document(workspace, name='设计稿', kind='DESIGN')['data']
    identity, revision = first['document']['id'], first['revision_id']
    before = counts(db)
    assert metadata(workspace, identity, 1, {'type': 'CONFIRM', 'expected_content_version': 2, 'revision_id': revision})['code'] == 'CONTENT_VERSION_CONFLICT'
    assert metadata(workspace, identity, 1, {'type': 'CONFIRM', 'expected_content_version': 1, 'revision_id': other['revision_id']})['code'] == 'SOURCE_INVALID'
    accepted = metadata(workspace, identity, 1, {'type': 'CONFIRM', 'expected_content_version': 1, 'revision_id': revision})
    assert accepted['code'] == 'UPDATED'
    assert accepted['data']['document']['confirmed_revision_id'] == revision
    repeated = metadata(workspace, identity, 2, {'type': 'CONFIRM', 'expected_content_version': 1, 'revision_id': revision})
    assert repeated['code'] == 'NO_CHANGE' and repeated['data']['event_id'] is None
    renamed = metadata(workspace, identity, 2, {'type': 'RENAME', 'name': '新的文档名'})
    assert renamed['code'] == 'UPDATED'
    assert renamed['data']['document']['content_version'] == 1
    assert renamed['data']['document']['confirmed_revision_id'] == revision
    assert counts(db)['revisions'] == before['revisions']
    with db.transaction() as connection:
        revision_row = connection.execute('SELECT * FROM revisions WHERE id=?', (revision,)).fetchone()
        assert revision_row['markdown_snapshot'] == '' and revision_row['source_content_version'] == 1
    assert get_current_document(db, 1, other['document']['id'], catalog=resources)['data'] == other['document']


def test_archive_read_restore_and_business_closed_are_independent(workspace):
    db, executor, resources = workspace
    update(executor, 1, {'status': 'CLOSED'})
    created = document(workspace)['data']
    identity = created['document']['id']
    archived = metadata(workspace, identity, 1, {'type': 'ARCHIVE'})
    assert archived['code'] == 'UPDATED' and archived['data']['document']['archived_at'] is not None
    assert metadata(workspace, identity, 2, {'type': 'ARCHIVE'})['code'] == 'NO_CHANGE'
    assert metadata(workspace, identity, 2, {'type': 'RENAME', 'name': '归档中改名'})['code'] == 'STATE_CONFLICT'
    assert get_current_document(db, 1, identity, catalog=resources)['code'] == 'READ_OK'
    restored = metadata(workspace, identity, 2, {'type': 'RESTORE'})
    assert restored['code'] == 'UPDATED' and restored['data']['document']['archived_at'] is None
    assert get_requirement(db, 1)['data']['requirement']['status'] == 'CLOSED'


def test_occupancy_version_and_idempotency_protect_document_commands(workspace):
    db, _, _ = workspace
    key = str(uuid4())
    accepted = document(workspace, key=key)
    assert document(workspace, key=key) == accepted
    assert document(workspace, key=key, name='另一份')['code'] == 'IDEMPOTENCY_CONFLICT'
    renamed = metadata(workspace, 1, 1, {'type': 'RENAME', 'name': '并发目标'})
    assert renamed['code'] == 'UPDATED'
    assert metadata(workspace, 1, 1, {'type': 'ARCHIVE'})['code'] == 'METADATA_VERSION_CONFLICT'
    seed_running(db)
    assert document(workspace)['code'] == 'WORK_STATE_CONFLICT'
    assert metadata(workspace, 1, 2, {'type': 'ARCHIVE'})['code'] == 'WORK_STATE_CONFLICT'


def test_event_failure_rolls_back_document_revision_and_action_message(workspace, monkeypatch):
    db, _, _ = workspace
    before = counts(db)

    def fail(*args, **kwargs):
        raise sqlite3.IntegrityError('isolated document event failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(AuditRepository, 'record_document_event', fail)
        assert document(workspace)['code'] == 'STORAGE_UNAVAILABLE'
    assert counts(db) == before
    assert document(workspace)['data']['document']['id'] == 1
    with monkeypatch.context() as scoped:
        scoped.setattr(AuditRepository, 'record_document_event', fail)
        assert metadata(workspace, 1, 1, {'type': 'RENAME', 'name': '事务回滚'})['code'] == 'STORAGE_UNAVAILABLE'
    assert get_requirement(db, 1)['data']['documents'][0]['name'] == '需求说明'


def test_actual_http_document_paths_and_strict_target_parameter(workspace):
    db, executor, resources = workspace
    app = FastAPI()
    app.include_router(doc_router)
    app.state.walle_runtime = HttpRuntime(db, resources, executor)
    with TestClient(app) as client:
        response = client.post('/api/v1/requirements/1/documents', json={'name': 'HTTP文档', 'document_kind': 'DESIGN', 'template_ref': None}, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 201, response.text
        assert client.get('/api/v1/requirements/1/current-document').status_code == 422
        read = client.get('/api/v1/requirements/1/current-document?document_id=1')
        assert read.status_code == 200 and read.json()['data']['name'] == 'HTTP文档'
        assert client.get('/api/v1/requirements/1/current-document?document_id=1&document_id=2').status_code == 422
        patch = {'expected_metadata_version': 1, 'change': {'type': 'CONFIRM', 'expected_content_version': 1, 'revision_id': response.json()['data']['revision_id']}}
        confirmation = client.patch('/api/v1/documents/1', json=patch, headers={'Idempotency-Key': str(uuid4())})
        assert confirmation.status_code == 200, confirmation.text
        assert confirmation.json()['data']['document']['confirmed_revision_id'] == 1
