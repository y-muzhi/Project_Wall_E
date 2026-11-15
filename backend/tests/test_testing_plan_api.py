"""Testing plans through real document revisions, production HTTP, and private Schema200."""

from copy import deepcopy
from uuid import uuid4

from backend.tests.documents.test_v15_documents import document, metadata
from backend.tests.documents.test_v15_editing import candidate, finish, save, start
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.requirements.test_v15_foundation import create
from backend.tests.test_testing_policy_api import post, receipt

PLANS = '/api/v1/test-plans'
VERSIONS = '/api/v1/test-plan-versions'
MAIN = '页面保留原始文件。'
MATERIAL = '界面明确显示执行结果。'


def add_revision(workspace, markdown, *, confirmed=True):
    created = document(workspace, kind='DESIGN', name=str(uuid4()))['data']
    identity = created['document']['id']
    draft = start(workspace, identity=identity, version=1)['data']['manual_draft']
    saved = save(workspace, draft, candidate(workspace, draft, markdown + '\n'))
    finished = finish(workspace, saved['data'])
    assert finished['code'] == 'DRAFT_COMPLETED', finished
    revision = finished['data']['revision_id']
    if confirmed:
        result = metadata(
            workspace,
            identity,
            1,
            {'type': 'CONFIRM', 'expected_content_version': 2, 'revision_id': revision},
        )
        assert result['code'] == 'UPDATED', result
    return {'document_id': identity, 'revision_id': revision}


def setup(service, *, confirmed=True):
    database, app, client = service
    runtime = app.state.walle_runtime
    workspace = (database, runtime.commands(), runtime.catalog)
    create(runtime.commands())
    main = add_revision(workspace, MAIN, confirmed=confirmed)
    material = add_revision(workspace, MATERIAL)
    plan = post(client, PLANS, {'name': ' 独立测试计划 '})
    assert plan.status_code == 201, plan.text
    assert plan.json()['data'] == {'plan_id': 1}
    return {
        'requirement_id': 1,
        'document_id': main['document_id'],
        'design_revision_id': main['revision_id'],
        'material_refs': [material],
        'behaviors': [
            {
                'behavior_id': 'fixed-file',
                'name': '保留文件',
                'basis_refs': [
                    {**main, 'quote': MAIN},
                    {**material, 'quote': MATERIAL},
                ],
                'stages': ['ACCEPTANCE'],
                'importance': 'CRITICAL',
                'mode': 'MANUAL',
                'case_ids': [],
                'explanation': '按原设计检查受测文件和执行结果。',
            }
        ],
        'cases': [],
        'unresolved_questions': [],
    }


def test_exact_fixed_revision_draft_cas_and_manual_publication_revocation(service):
    database, _, client = service
    content = setup(service)
    path = PLANS + '/1/versions'
    create_key = str(uuid4())
    creation = post(client, path, {'plan_content': content}, create_key)
    assert creation.status_code == 201, creation.text
    first = creation.json()['data']
    assert first['status'] == 'DRAFT' and first['state_version'] == first['version'] == 1
    assert first['material_refs'] == content['material_refs']
    assert client.get(VERSIONS + '/1').json()['data'] == first
    assert client.get(path).json()['data']['items'] == [first]
    assert client.get(path, params={'page': 2}).json()['data']['items'] == []
    plan = client.get(PLANS + '/1').json()['data']
    assert plan['versions_count'] == 1 and plan['name'] == '独立测试计划'
    assert client.get(PLANS, params={'requirement_id': 1}).json()['data']['items'] == [plan]
    assert client.get(PLANS, params={'requirement_id': 2}).json()['data']['items'] == []

    draft_path = VERSIONS + '/1/draft'
    draft_key = str(uuid4())
    edited = deepcopy(content)
    edited['behaviors'][0]['explanation'] = '按固定设计复查。'
    draft_request = {'expected_state_version': 1, 'plan_content': edited}
    saved = post(client, draft_path, draft_request, draft_key)
    assert saved.status_code == 200, saved.text
    assert saved.json()['data']['state_version'] == 2
    stale = post(client, draft_path, draft_request)
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'VERSION_CONFLICT'
    assert stale.json()['error']['details']['current_state_version'] == 2

    publish_path = VERSIONS + '/1/publish'
    publish_key = str(uuid4())
    published = post(client, publish_path, {'expected_state_version': 2}, publish_key)
    assert published.status_code == 200, published.text
    frozen = published.json()['data']
    assert frozen['status'] == 'PUBLISHED' and frozen['published_at'] is not None
    denied = post(client, draft_path, {'expected_state_version': 3, 'plan_content': edited})
    assert denied.status_code == 409 and denied.json()['error']['code'] == 'INVALID_STATE'

    revoke_path = VERSIONS + '/1/revoke'
    revoked = post(
        client, revoke_path, {'expected_state_version': 3, 'reason': '新的测试依据待确认'}
    )
    assert revoked.status_code == 200, revoked.text
    closed = revoked.json()['data']
    assert closed['status'] == 'REVOKED' and closed['state_version'] == 4
    assert (
        closed['published_at'] == frozen['published_at']
        and closed['behaviors'] == edited['behaviors']
    )
    assert closed['revocation_reason'] == '新的测试依据待确认'
    assert post(client, path, {'plan_content': content}, create_key).json()['data'] == first
    assert post(client, draft_path, draft_request, draft_key).json()['data'] == saved.json()['data']
    assert receipt(client, publish_path, publish_key)['original_outcome']['data'] == frozen
    with database.transaction() as connection:
        operations = connection.execute(
            'SELECT resource_kind,resource_id,operation_type,task_id,testing_task_id FROM code_operations ORDER BY id',
        ).fetchall()
        assert [tuple(row) for row in operations] == [
            ('TEST_PLAN_VERSION', 1, 'PUBLISH_PLAN', None, None),
            ('TEST_PLAN_VERSION', 1, 'REVOKE_PLAN', None, None),
        ]
        assert connection.execute('SELECT COUNT(*) FROM code_operation_steps').fetchone()[0] == 4
        for table in ('code_tasks', 'testing_tasks', 'llm_uses'):
            assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


def test_draft_protects_original_source_and_rejects_unconfirmed_publish(service):
    _, _, client = service
    content = setup(service, confirmed=False)
    path = PLANS + '/1/versions'
    version_path = VERSIONS + '/1'
    bad = deepcopy(content)
    bad['behaviors'][0]['basis_refs'][0]['quote'] = '不属于固定原文的内容'
    rejected = post(client, path, {'plan_content': bad})
    assert rejected.status_code == 422 and rejected.json()['error']['code'] == 'BASIS_REF_INVALID'
    assert client.get(PLANS + '/1').json()['data']['versions_count'] == 0
    created = post(client, path, {'plan_content': content})
    assert created.status_code == 201, created.text
    unconfirmed = post(client, version_path + '/publish', {'expected_state_version': 1})
    assert (
        unconfirmed.status_code == 422
        and unconfirmed.json()['error']['code'] == 'BASIS_REF_INVALID'
    )
    bad = deepcopy(content)
    bad['material_refs'] = []
    denied = post(
        client, version_path + '/draft', {'expected_state_version': 1, 'plan_content': bad}
    )
    assert denied.status_code == 422 and denied.json()['error']['code'] == 'BASIS_REF_INVALID'
    assert client.get(version_path).json()['data'] == created.json()['data']


def test_confirmed_draft_keeps_ambiguity_and_never_publishes_unadmitted_auto_cases(service):
    _, _, client = service
    content = setup(service)
    path = PLANS + '/1/versions'
    content['unresolved_questions'] = ['原文缺少恢复行为']
    saved = post(client, path, {'plan_content': content})
    assert saved.status_code == 201, saved.text
    failure = post(client, VERSIONS + '/1/publish', {'expected_state_version': 1})
    assert failure.status_code == 409 and failure.json()['error']['code'] == 'INVALID_STATE'
    content['unresolved_questions'] = []
    content['behaviors'][0]['mode'] = 'AUTO'
    content['behaviors'][0]['case_ids'] = ['auto-case']
    content['cases'] = [
        {
            'case_id': 'auto-case',
            'name': '原用例',
            'behavior_ids': ['fixed-file'],
            'visibility': 'HELD_OUT',
            'driver_kind': 'CLI',
            'steps': [],
            'assertions': [],
            'timeout_seconds': 1,
        }
    ]
    incomplete = post(
        client, VERSIONS + '/1/draft', {'expected_state_version': 1, 'plan_content': content}
    )
    assert incomplete.status_code == 200, incomplete.text
    assert (
        post(client, VERSIONS + '/1/publish', {'expected_state_version': 2}).json()['error']['code']
        == 'CHECK_CONFIGURATION_INVALID'
    )
    content['cases'][0]['steps'] = [{'step_id': 'untrusted', 'op': 'SCRIPT', 'shell': 'arbitrary'}]
    wrong = post(
        client, VERSIONS + '/1/draft', {'expected_state_version': 2, 'plan_content': content}
    )
    assert wrong.status_code == 422 and wrong.json()['error']['code'] == 'INVALID_INPUT'
    assert client.get(VERSIONS + '/1').json()['data'] == incomplete.json()['data']
