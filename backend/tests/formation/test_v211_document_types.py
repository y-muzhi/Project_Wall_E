"""Document creation and offline writing guidance through the V2.1 backend."""

from uuid import uuid4
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.documents.api import doc_router
from backend.app.documents import design_profiles
from backend.app.documents.markdown import parse_markdown
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
    'kind,original_heading,chapter,table_heading,other_heading,rule,file',
    [
        (
            'FRONTEND_DESIGN',
            '页面与导航',
            '5. 页面与交互',
            '排列、格式与适配要求',
            '4.7 AI任务补充',
            '按前端设计的职责',
            'frontend.md',
        ),
        (
            'BACKEND_DESIGN',
            '业务对象与状态',
            '3. 业务对象（按对象重复）',
            '应用输入映射及附加接入限制',
            '5.6 独立组件',
            '按后端设计的职责',
            'backend.md',
        ),
    ],
)
@pytest.mark.parametrize('initial', ('EMPTY', 'FRAMEWORK'))
def test_design_creation_and_writing_use_the_selected_kind(
    workspace, kind, original_heading, chapter, table_heading, other_heading, rule, file, initial
):
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
            assert document['template_ref']['version'] == 'framework-v2'
            reference = (
                Path(__file__).resolve().parents[2] / 'resources/design-frameworks/v2' / file
            )
            markdown = document['markdown_content']
            assert markdown.encode('utf-8') == reference.read_bytes()
            assert ('# ' + chapter) in markdown
            assert table_heading in markdown and other_heading not in markdown
            assert (
                sum(block.block_type == 'table' for block in parse_markdown(markdown).blocks) >= 20
            )
            assert '8.5 规格完成与实现验收' in markdown and '附录A. 待确认事项' in markdown
            assert all(
                block['created_source_type'] == 'TEMPLATE'
                for block in document['block_state_json']['blocks']
            )
        else:
            assert document['markdown_content'] == ''
            assert document['template_ref']['version'] == 'blank-v1'
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
    assert (chapter if initial == 'FRAMEWORK' else original_heading) in structure['rules'][1]
    assert structure['template'] is None


@pytest.mark.parametrize('kind', ('FRONTEND_DESIGN', 'BACKEND_DESIGN'))
def test_previous_framework_is_readable_and_same_key_replays_across_release(
    workspace, monkeypatch, kind
):
    database, executor, catalog = workspace
    app = FastAPI()
    app.include_router(doc_router)
    app.include_router(req_router)
    app.state.walle_runtime = HttpRuntime(database, catalog, executor)
    payload = {
        'name': '历史框架',
        'document_kind': kind,
        'template_ref': None,
        'initial_content': 'FRAMEWORK',
    }
    path = '/api/v1/requirements/1/documents'
    headers = {'Idempotency-Key': str(uuid4())}
    with TestClient(app) as client:
        with monkeypatch.context() as patch:
            patch.setattr(design_profiles, 'FRAMEWORK_VERSION', 'framework-v1')
            previous = client.post(path, json=payload, headers=headers)
        assert previous.status_code == 201, previous.text
        saved = previous.json()['data']
        document = saved['document']
        legacy = document['template_ref']
        assert legacy['version'] == 'framework-v1'
        assert len(parse_markdown(document['markdown_content']).blocks) == 6
        assert 'markdown_sha256' not in design_profiles.design_resource_content(legacy)
        replay = client.post(path, json=payload, headers=headers)
        assert replay.status_code == 201 and replay.json()['data'] == saved
        data = client.get(f'/api/v1/requirements/1/current-document?document_id={document["id"]}')
        assert data.status_code == 200 and data.json()['data'] == document
        fresh = client.post(path, json=payload, headers={'Idempotency-Key': str(uuid4())})
        assert fresh.status_code == 201, fresh.text
        assert fresh.json()['data']['document']['template_ref']['version'] == 'framework-v2'
