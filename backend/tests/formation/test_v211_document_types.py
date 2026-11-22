"""Document creation and offline writing guidance through the V2.1 backend."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.documents.api import doc_router
from backend.app.guide.collaboration_context import compile_context, read_canonical
from backend.app.guide.commands import create_guide_run
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.api import req_router
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.formation.test_v21_discuss_acceptance import (
    base_workspace,
    database,
    released,
    workspace,
)

__all__ = ['base_workspace', 'database', 'released', 'workspace']


@pytest.mark.parametrize(
    'kind,heading,rule',
    [
        ('FRONTEND_DESIGN', '页面与导航', '按前端设计的职责'),
        ('BACKEND_DESIGN', '业务对象与状态', '按后端设计的职责'),
    ],
)
@pytest.mark.parametrize('initial', ('EMPTY', 'FRAMEWORK'))
def test_design_creation_and_writing_use_the_selected_kind(workspace, kind, heading, rule, initial):
    database, executor, catalog = workspace
    app = FastAPI()
    app.include_router(doc_router)
    app.include_router(req_router)
    app.state.walle_runtime = HttpRuntime(database, catalog, executor)
    payload = {
        'name': '咖啡助手设计',
        'document_kind': kind,
        'template_ref': None,
        'initial_content': initial,
    }
    path = '/api/v1/requirements/1/documents'
    headers = {'Idempotency-Key': str(uuid4())}
    with TestClient(app) as client:
        created = client.post(path, json=payload, headers=headers)
        assert created.status_code == 201, created.text
        document = created.json()['data']['document']
        assert document['document_kind'] == kind
        repeated = client.post(path, json=payload, headers=headers)
        assert repeated.status_code == 201
        assert repeated.json()['data'] == created.json()['data']
        identity = document['id']
        if initial == 'FRAMEWORK':
            assert '# ' + heading in document['markdown_content']
            assert all(
                block['created_source_type'] == 'TEMPLATE'
                for block in document['block_state_json']['blocks']
            )
        else:
            assert document['markdown_content'] == ''
        detail = client.get('/api/v1/requirements/1').json()['data']
        assert [item['document_kind'] for item in detail['documents']] == ['DESIGN', 'DESIGN', kind]
        retrieved = client.get(f'/api/v1/requirements/1/current-document?document_id={identity}')
        assert retrieved.status_code == 200, retrieved.text
        assert retrieved.json()['data'] == document

    with database.transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, identity)
    run = create_guide_run(
        executor,
        {
            'requirement_id': 1,
            'document_id': identity,
            'expected_discussion_version': root['discussion_version'],
            'operation': 'REVISE',
            'instruction': '整理这份设计',
            'target': {'kind': 'EXISTING', 'document_id': identity, 'expected_content_version': 1},
            'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None},
            'source_refs': [],
            'proposal_ref': None,
            'acknowledge_source_changes': False,
            'idempotency_key': str(uuid4()),
        },
        catalog=catalog,
    )
    assert run['code'] == 'GUIDE_ACCEPTED', run
    with database.transaction() as connection:
        canonical = read_canonical(connection, run['data']['guide_run_id'], catalog)
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
    structure = compile_context(canonical, catalog).input['structure']
    assert structure['key'] == document['template_ref']['key']
    assert rule in structure['rules'][0]
    assert heading in structure['rules'][1]
