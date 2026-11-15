"""Real service HTTP and isolated Schema200 for Testing policy."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

from backend.app.infrastructure.windows_private_package import current_operator_sid
from backend.app.testing.policy_content import LIMIT_FIELDS
from backend.tests.code_tasks.test_execution_profile_versions import resources
from backend.tests.infrastructure.test_v20_command_http import close, package, service  # noqa: F401

PROFILE = '/api/v1/testing-profile-versions'
AUTH = '/api/v1/testing-authorizations'
OPTIONS = {
    'RUNNER': [{'value': {'runner_ref': 'registered-runner'}, 'ready': True}],
    'RUNTIME': [{'value': {'runtime_ref': 'registered-runtime'}, 'ready': True}],
    'CAPABILITY': [
        {
            'value': {'evidence_ref': 'registered-admission'},
            'ready': False,
            'unresolved_capability_codes': ['Q20-BROWSER'],
        }
    ],
}


def content(name='独立测试'):
    return {
        'name': name,
        'runner_refs': ['registered-runner'],
        'environment_refs': ['registered-runtime'],
        'commands': [],
        'model_binding': None,
        'limits': dict.fromkeys(LIMIT_FIELDS, 1),
        'admission_refs': ['registered-admission'],
    }


def post(client, path, value, key=None):
    return client.post(path, json=value, headers={'Idempotency-Key': key or str(uuid4())})


def create(client, value=None, key=None):
    return post(client, PROFILE, {'profile_content': content() if value is None else value}, key)


def receipt(client, path, key):
    original = {'method': 'POST', 'path': path, 'request_key': key}
    assert client.get('/api/v1/code-command-receipts', params=original).status_code == 422
    response = client.get('/api/v1/testing-command-receipts', params=original)
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_profile_version_page_and_original_after_catalogue_changes(service):
    database, _, client = service
    key = str(uuid4())
    with resources(OPTIONS):
        created = create(client, content(' 独立测试 '), key)
        assert created.status_code == 201, created.text
        fixed = created.json()['data']
        assert fixed['name'] == '独立测试'
        assert fixed['id'] == fixed['version'] == 1
        assert fixed['ready'] is False and 'Q20-CHECKS' in fixed['reason_codes']
        assert create(client, key=key).json()['data'] == fixed
        assert (
            create(client, content('不同名'), key).json()['error']['code'] == 'OPERATION_CONFLICT'
        )
        assert create(client).json()['data']['version'] == 2
        assert create(client, content('不同名')).json()['data']['version'] == 1
        assert client.get(PROFILE + '/1').json()['data'] == fixed
        page = client.get(PROFILE, params={'name': '独立测试'}).json()
        assert [row['id'] for row in page['data']['items']] == [1, 2]
        assert page['meta']['pagination']['total'] == 2
        overflow = client.get(PROFILE, params={'page': 2, 'name': '独立测试'}).json()
        assert overflow['data']['items'] == []
        assert overflow['meta']['pagination'] == {
            'page': 2,
            'page_size': 20,
            'total': 2,
            'total_pages': 1,
        }
    with resources({}):
        assert create(client, key=key).json()['data'] == fixed
        assert 'Q20-CONFIG' in client.get(PROFILE + '/1').json()['data']['reason_codes']
    assert receipt(client, PROFILE, key)['original_outcome']['data'] == fixed
    assert client.get(PROFILE + '/999').status_code == 404
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM testing_profile_versions').fetchone()[0] == 3
        )


def test_explicit_authorization_budget_and_original_receipts(service):
    database, _, client = service
    key, rejected_key = str(uuid4()), str(uuid4())
    with resources(OPTIONS):
        result = create(client)
        assert result.status_code == 201, result.text
        body = {'profile_version_id': 1, 'scope_kind': 'PACK_VALIDATION', 'budget_limit_cny': '0'}
        denied = post(client, AUTH, {**body, 'budget_limit_cny': '0.000001'}, rejected_key)
        assert denied.status_code == 403, denied.text
        assert denied.json()['error']['details'] == {'task_id': None, 'authorization_id': None}
        assert (
            receipt(client, AUTH, rejected_key)['original_outcome']['error']
            == denied.json()['error']
        )
        created = post(client, AUTH, body, key)
        assert created.status_code == 201, created.text
        fixed = created.json()['data']
        assert fixed['status'] == 'APPROVED_UNBOUND'
        assert fixed['actor_ref'] == current_operator_sid()
        assert fixed['testing_task_id'] is None and fixed['validation_id'] is None
        assert fixed['budget_limit_cny'] == '0.000000' and fixed['ready'] is False
        assert (
            post(client, AUTH, {**body, 'budget_limit_cny': '0.000000'}, key).json()['data']
            == fixed
        )
        assert client.get(AUTH + '/1').json()['data'] == fixed
        assert post(client, AUTH, {**body, 'profile_version_id': 999}).status_code == 404
        assert post(client, AUTH, {**body, 'actor_ref': 'browser'}).status_code == 422
        task = post(client, AUTH, {**body, 'scope_kind': 'TASK', 'budget_limit_cny': '1.2'})
        assert task.status_code == 201, task.text
        assert task.json()['data']['budget_limit_cny'] == '1.200000'
    saved = receipt(client, AUTH, key)
    assert saved['original_http_status'] == 201 and saved['original_outcome']['data'] == fixed
    assert saved['task_id'] is saved['testing_task_id'] is saved['operation_id'] is None
    assert client.get(AUTH + '/999').status_code == 404
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM testing_authorizations').fetchone()[0] == 2
        for table in ('code_tasks', 'testing_tasks', 'llm_uses', 'code_operations'):
            assert connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_closed_original_invalid_payload_and_concurrent_versions(service):
    _, _, client = service
    identity = {'method': 'POST', 'path': PROFILE, 'request_key': str(uuid4())}
    assert close(client, identity).status_code == 200
    assert create(client, key=identity['request_key']).json()['error']['code'] == 'COMMAND_CLOSED'
    assert client.get(PROFILE, params={'page_size': 10}).status_code == 422
    assert client.get(PROFILE, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
    assert client.get(PROFILE, params=[('name', 'a'), ('name', 'b')]).status_code == 422
    bad = content()
    bad['limits']['max_input_bytes'] = 8 * 1024 * 1024 + 1
    assert create(client, bad).status_code == 422
    bad = content()
    bad['runner_refs'] = ['unregistered']
    bad_key = str(uuid4())
    with resources(OPTIONS):
        invalid = create(client, bad, bad_key)
        assert invalid.status_code == 422, invalid.text
        assert invalid.json()['error']['code'] == 'CHECK_CONFIGURATION_INVALID'
        assert invalid.json()['error']['details']['field_errors'] == [
            {'field': 'runner_refs[0]', 'reason': 'RELATION'}
        ]
        with ThreadPoolExecutor(max_workers=3) as pool:
            completed = list(pool.map(lambda _: create(client), range(3)))
        assert [item.status_code for item in completed] == [201] * 3
        assert sorted(item.json()['data']['version'] for item in completed) == [1, 2, 3]
    changed = deepcopy(OPTIONS)
    changed['RUNNER'].append({'value': {'runner_ref': 'unregistered'}, 'ready': True})
    with resources(changed):
        assert create(client, bad, bad_key).json()['error'] == invalid.json()['error']
