"""Private ASGI/Schema200 execution versions; mock resources never prove admission."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure.database import CommitOutcomeUnknown
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.code_tasks.execution_profile_resources import (
    RESOURCE_KINDS,
    reference_error,
    readiness,
)
from backend.tests.infrastructure.test_v20_command_http import package, service, close
from backend.tests.code_tasks.test_execution_profile_content import body, command
from backend.tests.code_tasks.test_check_set_versions import EMPTY

PATH = '/api/v1/code-execution-profiles/1/versions'


def publish(client, value=None, key=None, path=PATH):
    return client.post(
        path,
        json=body() if value is None else value,
        headers={'Idempotency-Key': key or str(uuid4())},
    )


def parents(client):
    for path in ('/api/v1/code-execution-profiles', '/api/v1/code-check-sets'):
        result = client.post(
            path, json={'name': '测试专用'}, headers={'Idempotency-Key': str(uuid4())}
        )
        assert result.status_code == 201, result.text
    result = client.post(
        '/api/v1/code-check-sets/1/versions', json=EMPTY, headers={'Idempotency-Key': str(uuid4())}
    )
    assert result.status_code == 201, result.text


def fixture_snapshot(content=None):
    content = body() if content is None else content
    rows = {kind: [] for kind in RESOURCE_KINDS}

    def add(kind, value):
        rows[kind].append(
            {
                'value': deepcopy(value),
                'ready': False,
                'unresolved_capability_codes': ['Q20-CONFIG'],
            }
        )

    add('EXECUTOR', content['executor'])
    add('GIT', content['git'])
    add('MODEL', {'model_profile_ref': 'deepseek-v2'})
    add('PRICE', {'price_version_id': 1, 'model_profile_ref': 'deepseek-v2'})
    add('CAPABILITY', {'capability_code': 'Q20-MODEL', 'evidence_ref': 'test-only-admission'})
    add(
        'CONTENT_POLICY',
        {
            key: content['capture_rules'][key]
            for key in ('content_policy_version', 'secret_policy_ref')
        },
    )
    for definition in content['commands']:
        add('COMMAND', definition)
    return rows


def seed_price(database):
    # Isolated fabricated algorithm fixture, never copied to production resources.
    with database.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO model_price_versions VALUES(1,'deepseek-v2','test-only-snapshot',
            'ARK_CN_BEIJING','test-only-account','default','2026-11-01T00:00:00.000Z',NULL,
            'CNY','1.000000','2.000000','[]','{}','TOTAL_HALF_UP_6DP','test-only-source',
            '2026-11-01T00:00:00.000Z')"""
        )


@contextmanager
def resources(snapshot=None):
    snapshot = fixture_snapshot() if snapshot is None else snapshot
    with patch.object(
        ResourceCatalog,
        'code_configuration_options',
        lambda self, kind: deepcopy(snapshot.get(kind, [])),
    ):
        yield snapshot


def test_actual_create_replay_receipt_read_list_draft_and_no_execution(service):
    database, app, client = service
    parents(client)
    seed_price(database)
    key = str(uuid4())
    with resources():
        first = publish(client, key=key)
        assert first.status_code == 201, first.text
        assert publish(client, key=key).json()['data'] == first.json()['data']
        assert first.json()['data'] == {
            'resource_kind': 'EXECUTION_PROFILE_VERSION',
            'resource_id': 1,
        }
        data = client.get('/api/v1/code-execution-profile-versions/1').json()['data']
        assert {field: data[field] for field in body()} == body()
        assert data['profile_id'] == data['version'] == 1
        assert data['ready'] is False and 'Q20-MODEL' in data['unresolved_capability_codes']
        assert client.get(PATH).json()['data']['items'] == [data]
    # Replays must not depend on the catalogue still being available.
    with patch.object(
        ResourceCatalog, 'code_configuration_options', side_effect=ConfigInvalid('private')
    ):
        assert publish(client, key=key).status_code == 201
    receipt = client.get(
        '/api/v1/code-command-receipts', params={'method': 'POST', 'path': PATH, 'request_key': key}
    )
    assert receipt.json()['data']['original_outcome']['data'] == first.json()['data']
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT last_value FROM sequences WHERE entity_kind='ExecutionProfileVersion'"
            ).fetchone()[0]
            == 1
        )
        for table in ('code_tasks', 'testing_tasks', 'llm_uses', 'code_operations'):
            assert connection.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
    assert not any(event['event'].startswith('DISPATCH') for event in app.state.walle_worker.events)


def test_absent_parent_and_unknown_real_resources_are_original_rejections(service):
    database, _, client = service
    key = str(uuid4())
    assert publish(client, key=key).status_code == 404
    parents(client)
    assert publish(client, key=key).status_code == 404
    rejected = publish(client)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()['error']['details']['field_errors'] == [
        {'field': 'executor', 'reason': 'RELATION'}
    ]
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_execution_profile_versions').fetchone()[0]
            == 0
        )


def test_changed_input_conflicts_and_close_prevents_late_publication(service):
    database, _, client = service
    parents(client)
    seed_price(database)
    key = str(uuid4())
    with resources():
        assert publish(client, key=key).status_code == 201
        changed = body()
        changed['limits']['max_model_requests'] += 1
        assert publish(client, changed, key).status_code == 409
        closed = str(uuid4())
        assert (
            close(client, {'method': 'POST', 'path': PATH, 'request_key': closed}).status_code
            == 200
        )
        result = publish(client, key=closed)
        assert result.status_code == 409 and result.json()['error']['code'] == 'COMMAND_CLOSED'


def test_serialized_concurrent_original_keys_allocate_unique_versions(service):
    database, _, client = service
    parents(client)
    seed_price(database)
    with resources(), ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: publish(client), range(3)))
    assert [result.status_code for result in responses] == [201] * 3
    with database.transaction() as connection:
        rows = connection.execute(
            'SELECT id,version FROM code_execution_profile_versions ORDER BY version'
        ).fetchall()
        assert [tuple(row) for row in rows] == [(1, 1), (2, 2), (3, 3)]


def test_pagination_latest_identity_and_real_overflow(service):
    database, _, client = service
    parents(client)
    seed_price(database)
    with resources():
        for _ in range(21):
            assert publish(client).status_code == 201
        first = client.get(PATH)
        assert len(first.json()['data']['items']) == 20
        assert [row['version'] for row in first.json()['data']['items']] == list(range(21, 1, -1))
        second = client.get(PATH, params={'page': '2'})
        assert second.json()['data']['items'][0]['version'] == 1
        overflow = client.get(PATH, params={'page': '3'})
        assert overflow.json()['data']['items'] == []
        assert overflow.json()['meta']['pagination'] == {
            'page': 3,
            'page_size': 20,
            'total': 21,
            'total_pages': 2,
        }
        assert (
            client.get('/api/v1/code-execution-profiles').json()['data']['items'][0][
                'latest_version_id'
            ]
            == 21
        )
        assert client.get('/api/v1/code-execution-profiles/99/versions').status_code == 404


@pytest.mark.parametrize(
    'bad', ['price', 'snapshot', 'check-set', 'template', 'supplier-secret', 'network', 'runtime']
)
def test_references_are_checked_against_actual_database_and_entire_registered_values(service, bad):
    database, _, client = service
    parents(client)
    seed_price(database)
    value = body()
    value['commands'] = [command()]
    snapshot = fixture_snapshot(value)
    if bad == 'price':
        value['models']['bindings'][0]['price_version_id'] = 99
    elif bad == 'snapshot':
        value['models']['bindings'][0]['model_snapshot_ref'] = 'unrelated'
    elif bad == 'check-set':
        value['check_set_version_id'] = 99
    elif bad == 'template':
        value['commands'][0]['argument_template'] = ['--eval', 'arbitrary user text']
    elif bad == 'supplier-secret':
        value['environment']['secret_refs'] = ['ARK_API_KEY']
    elif bad == 'network':
        value['commands'][0]['network_scope_ref'] = 'arbitrary-host'
        snapshot['COMMAND'][0]['value'] = deepcopy(value['commands'][0])
        snapshot['SCOPE'] = [
            {'ready': False, 'value': {'scope_ref': 'arbitrary-host', 'scope_kind': 'READ_ROOT'}}
        ]
    else:
        value['environment']['node_ref'] = 'python-ref'
        snapshot['RUNTIME'] = [
            {'ready': False, 'value': {'runtime_ref': 'python-ref', 'runtime_kind': 'PYTHON'}}
        ]
    with resources(snapshot):
        result = publish(client, value)
    assert result.status_code == 422, result.text
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_execution_profile_versions').fetchone()[0]
            == 0
        )


def test_catalogue_failure_is_explicit_config_error_not_missing_option(service):
    _, _, client = service
    parents(client)
    with patch.object(
        ResourceCatalog, 'code_configuration_options', side_effect=ConfigInvalid('PRIVATE')
    ):
        result = publish(client)
    assert result.status_code == 503, result.text
    assert result.json()['error']['details'] == {'capability_codes': ['Q20-CONFIG']}
    assert 'PRIVATE' not in result.text


def test_read_query_rejects_overrides_and_server_metadata_before_writes(service):
    _, _, client = service
    parents(client)
    for path in (
        PATH + '?page=01',
        PATH + '?page=1&page=2',
        PATH + '?ready=true',
        '/api/v1/code-execution-profile-versions/01',
    ):
        assert client.get(path).status_code == 422
    assert client.get(PATH, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
    for field in ('ready', 'created_at', 'version', 'profile_id', 'id'):
        assert publish(client, {**body(), field: 1}).status_code == 422


def test_identity_capacity_rejects_without_version_id_consumption(service):
    database, _, client = service
    parents(client)
    seed_price(database)
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO sequences VALUES('ExecutionProfileVersion',9007199254740991)"
        )
    with resources():
        result = publish(client)
    assert result.status_code == 409, result.text
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_execution_profile_versions').fetchone()[0]
            == 0
        )


def test_labels_and_boolean_admission_do_not_prove_model_evidence():
    content = body()
    snapshot = fixture_snapshot()
    for rows in snapshot.values():
        for row in rows:
            row['ready'] = True
            row['unresolved_capability_codes'] = []
    result = readiness(content, snapshot, {'ready': True})
    assert result == {'ready': False, 'unresolved_capability_codes': ['Q20-MODEL']}


def test_lost_commit_ack_replays_original_without_second_version(service):
    database, _, client = service
    parents(client)
    seed_price(database)
    key = str(uuid4())
    transaction = database.transaction
    committed = False

    @contextmanager
    def unknown(*, write=False):
        nonlocal committed
        with transaction(write=write) as connection:
            yield connection
        if write and not committed:
            committed = True
            raise CommitOutcomeUnknown('Injected lost commit acknowledgment')

    with resources(), patch.object(database, 'transaction', unknown):
        first = publish(client, key=key)
    assert first.status_code == 503, first.text
    with resources():
        assert publish(client, key=key).status_code == 201
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT count(*) FROM code_execution_profile_versions').fetchone()[0]
            == 1
        )


@pytest.mark.parametrize('corruption', ['duplicate-json', 'normalized-template', 'unknown-field'])
def test_bad_stored_content_is_neither_normalized_nor_returned_as_empty(service, corruption):
    from backend.app.infrastructure.schema_transport import compact
    from backend.app.code_tasks.execution_profile_content import FIELDS
    from backend.tests.code_tasks.test_execution_profile_content import delivery

    database, _, client = service
    parents(client)
    content = body()
    encoded = {
        field: compact(content[field])
        if field != 'check_set_version_id' and content[field] is not None
        else content[field]
        for field in FIELDS
    }
    if corruption == 'duplicate-json':
        encoded['limits'] = '{"max_model_requests":1,' + encoded['limits'][1:]
    elif corruption == 'normalized-template':
        encoded['delivery'] = compact(delivery())
    else:
        encoded['executor'] = encoded['executor'][:-1] + ',"PRIVATE":"must not leak"}'
    columns = ('id', 'profile_id', 'version', *FIELDS, 'created_at')
    encoded.update(id=1, profile_id=1, version=1, created_at='2026-11-05T00:00:00.000Z')
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_execution_profile_versions('
            + ','.join(columns)
            + ') VALUES('
            + ','.join('?' for _ in columns)
            + ')',
            tuple(encoded[field] for field in columns),
        )
    for path in (PATH, '/api/v1/code-execution-profile-versions/1'):
        response = client.get(path)
        assert response.status_code == 503, response.text
        assert 'must not leak' not in response.text


def test_current_catalogue_failure_and_http_lease_have_code_error_contract(service):
    database, app, client = service
    parents(client)
    seed_price(database)
    with resources():
        assert publish(client).status_code == 201
    with patch.object(
        ResourceCatalog, 'code_configuration_options', side_effect=ConfigInvalid('PRIVATE')
    ):
        for path in (PATH, '/api/v1/code-execution-profile-versions/1'):
            response = client.get(path)
            assert response.status_code == 503, response.text
            assert response.json()['error']['details'] == {'capability_codes': ['Q20-CONFIG']}
    app.state.walle_http_lease.retire()
    for path in (PATH, '/api/v1/code-execution-profile-versions/1'):
        response = client.get(path)
        assert response.status_code == 503, response.text
        assert response.json()['error']['code'] == 'STORAGE_UNAVAILABLE'


def test_testing_check_set_cannot_be_bound_by_coding_configuration(service):
    database, _, client = service
    parents(client)
    seed_price(database)
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO code_check_set_versions VALUES(2,1,2,'TESTING','CHECK20-CONTROL-1','[]','[]','2026-11-05T00:00:00.000Z')"
        )
    value = body()
    value['check_set_version_id'] = 2
    with resources():
        response = publish(client, value)
    assert response.status_code == 422, response.text
    assert response.json()['error']['details']['field_errors'] == [
        {'field': 'check_set_version_id', 'reason': 'RELATION'}
    ]
