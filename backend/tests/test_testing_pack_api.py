"""Testing pack identities and original receipts through the production HTTP router."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401
from backend.tests.test_testing_plan_api import PLANS, VERSIONS, setup
from backend.tests.test_testing_policy_api import post, receipt

PACKS = VERSIONS + '/1/packs'
PACK = '/api/v1/test-pack-versions/1'


def published_plan(service):
    _, _, client = service
    plan_content = setup(service)
    result = post(client, PLANS + '/1/versions', {'plan_content': plan_content})
    assert result.status_code == 201, result.text
    return plan_content


def test_draft_pack_is_bound_to_published_plan_and_replayed_after_parent_revocation(service):
    database, _, client = service
    published_plan(service)
    key_before_publish = str(uuid4())
    premature = post(client, PACKS, {}, key_before_publish)
    assert premature.status_code == 409 and premature.json()['error']['code'] == 'INVALID_STATE'
    result = post(client, VERSIONS + '/1/publish', {'expected_state_version': 1})
    assert result.status_code == 200, result.text
    assert post(client, PACKS, {}, key_before_publish).json()['error'] == premature.json()['error']

    key = str(uuid4())
    result = post(client, PACKS, {}, key)
    assert result.status_code == 201, result.text
    assert result.json()['data'] == {'test_pack_version_id': 1}
    assert receipt(client, PACKS, key)['original_outcome']['data'] == result.json()['data']
    saved = client.get(PACK).json()['data']
    assert saved['id'] == saved['version'] == saved['state_version'] == 1
    assert saved['plan_version_id'] == 1 and saved['status'] == 'DRAFT'
    assert saved['sha256'] is saved['check_set_version_id'] is saved['validation_id'] is None
    assert saved['ready'] is False and saved['reason_codes'] == ['PACK_NOT_SEALED', 'Q20-CHECKS']
    assert 'content_ref' not in saved
    assert client.get(PACKS).json()['data']['items'] == [saved]
    overflow = client.get(PACKS, params={'page': 2}).json()
    assert overflow['data']['items'] == [] and overflow['meta']['pagination']['total'] == 1

    revoked = post(
        client, VERSIONS + '/1/revoke', {'expected_state_version': 2, 'reason': '更新依据'}
    )
    assert revoked.status_code == 200, revoked.text
    assert post(client, PACKS, {}, key).json()['data'] == result.json()['data']
    later = post(client, PACKS, {})
    assert later.status_code == 409 and later.json()['error']['code'] == 'TEST_ASSET_REVOKED'
    history = client.get(PACK).json()['data']
    assert history['status'] == 'DRAFT' and history['reason_codes'] == ['TEST_ASSET_REVOKED']
    with database.transaction() as connection:
        for table in (
            'testing_pack_validations',
            'testing_tasks',
            'code_check_set_versions',
            'llm_uses',
        ):
            assert connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_pack_concurrent_numbers_and_strict_path_body_filters(service):
    _, _, client = service
    published_plan(service)
    assert post(client, VERSIONS + '/1/publish', {'expected_state_version': 1}).status_code == 200
    assert client.get(VERSIONS + '/999/packs').status_code == 404
    assert client.get('/api/v1/test-pack-versions/999').status_code == 404
    assert post(client, VERSIONS + '/999/packs', {}).status_code == 404
    assert post(client, PACKS, {'status': 'SEALED'}).status_code == 422
    assert client.get(PACKS, params={'page_size': 20}).status_code == 422
    assert client.get(PACK, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: post(client, PACKS, {}), range(3)))
    assert [item.status_code for item in results] == [201] * 3
    assert [row['version'] for row in client.get(PACKS).json()['data']['items']] == [1, 2, 3]
