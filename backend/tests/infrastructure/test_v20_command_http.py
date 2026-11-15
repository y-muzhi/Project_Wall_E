"""Actual service factory and shared HTTP boundary on private Schema200 only."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.app.service import create_app
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.schema_v20_release import (
    build_candidate,
    _load_verified_release,
    digest,
)
from backend.app.infrastructure.sqlite_runtime import require_active
from backend.app.code_tasks.command_registry import registered_command

AT = '2026-11-04T01:00:00.000Z'


@pytest.fixture(scope='module')
def package():
    require_active()
    with TemporaryDirectory(prefix='v20-http-', dir=os.environ['WALLE_CHECK_TEMP']) as directory:
        root = Path(directory)
        bundle = root / 'release'
        bundle.mkdir()
        files = build_candidate('http-test')
        for name, content in files.items():
            with (bundle / name).open('xb') as stream:
                stream.write(content)
        yield root, _load_verified_release(bundle, digest(files['manifest.json']))


@pytest.fixture
def service(package):
    root, release = package
    database = Database(root / (str(uuid4()) + '.sqlite'), schema_release=release)
    database.initialize()
    app = create_app(database=database)
    with TestClient(app) as client:
        yield database, app, client


def identity(path='/api/v1/code-execution-profiles'):
    return {'method': 'POST', 'path': path, 'request_key': str(uuid4())}


def close(client, original, **extra):
    return client.post(
        '/api/v1/command-intents/close',
        json={'method': original['method'], 'path': original['path'], **extra},
        headers={'Idempotency-Key': original['request_key']},
    )


def test_missing_lookup_never_receives_and_close_is_persistent_with_fresh_http_ids(service):
    database, app, client = service
    original = identity()
    before = client.get('/api/v1/code-command-receipts', params=original)
    assert before.status_code == 200, before.text
    assert before.json()['data']['lookup_status'] == 'NOT_FOUND'
    first = close(client, original)
    second = close(client, original)
    assert first.status_code == second.status_code == 200
    assert first.json()['data'] == second.json()['data']
    assert first.json()['meta']['request_id'] != second.json()['meta']['request_id']
    receipt = client.get('/api/v1/code-command-receipts', params=original).json()['data']
    assert receipt['record_status'] == 'CLOSED'
    assert receipt['original_http_status'] == 409
    assert receipt['original_outcome']['error']['message'] == '原请求已关闭，不再执行'
    assert receipt['original_outcome']['error']['details']['path'] == original['path']
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0] == 1
        for table in ('code_tasks', 'testing_tasks', 'code_operations', 'guide_runs', 'llm_uses'):
            assert connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
    assert not any(event['event'].startswith('DISPATCH') for event in app.state.walle_worker.events)


def test_testing_receipt_is_independent_and_wrong_module_is_rejected(service):
    database, app, client = service
    original = identity('/api/v1/test-plans')
    assert close(client, original).status_code == 200
    response = client.get('/api/v1/testing-command-receipts', params=original)
    assert response.status_code == 200, response.text
    assert response.json()['data']['record_status'] == 'CLOSED'
    assert client.get('/api/v1/code-command-receipts', params=original).status_code == 422
    code_original = identity()
    assert client.get('/api/v1/testing-command-receipts', params=code_original).status_code == 422


def test_illegal_close_and_unknown_or_duplicate_parameters_do_not_create_rows(service):
    database, app, client = service
    original = identity()
    assert close(client, original, actor='browser').status_code == 422
    bad = client.post(
        '/api/v1/command-intents/close',
        json={'method': 'POST', 'path': original['path'], 'bad field': 'x'},
        headers={'Idempotency-Key': original['request_key']},
    )
    assert bad.status_code == 422, bad.text
    assert set(bad.json()['error']['details']['field_errors'][0]) == {'field', 'reason'}
    for method, path in (
        ('GET', original['path']),
        ('POST', '/api/v1/command-intents/close'),
        ('POST', 'https://example.test/api/v1/code-execution-profiles'),
        ('POST', '/api/v1/code-tasks/01/start'),
    ):
        assert close(client, {**original, 'method': method, 'path': path}).status_code == 422
    upper = 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'
    assert (
        client.post(
            '/api/v1/command-intents/close',
            json={'method': 'POST', 'path': original['path']},
            headers={'Idempotency-Key': upper},
        ).status_code
        == 422
    )
    assert (
        client.get(
            '/api/v1/code-command-receipts',
            params=original,
            headers={'Idempotency-Key': original['request_key']},
        ).status_code
        == 422
    )
    duplicate = [
        ('method', 'POST'),
        ('method', 'POST'),
        ('path', original['path']),
        ('request_key', original['request_key']),
    ]
    assert client.get('/api/v1/code-command-receipts', params=duplicate).status_code == 422
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0] == 0


def test_original_success_and_rejection_are_projected_without_request_body(service):
    database, app, client = service
    original = identity()
    scope = registered_command(original['method'], original['path'], original['request_key']).scope
    executor = app.state.walle_runtime.commands()

    def create(connection):
        connection.execute('INSERT INTO code_execution_profiles VALUES(1,?,?)', ('profile', AT))
        return Success(
            {
                'code': 'CREATED',
                'data': {'resource_kind': 'EXECUTION_PROFILE', 'resource_id': 1},
                'details': None,
            },
            201,
        )

    executor.execute(scope, {'name': 'private original input'}, create)
    response = close(client, original)
    assert response.status_code == 200, response.text
    receipt = response.json()['data']['original_receipt']
    assert response.json()['data']['close_status'] == 'ALREADY_RECEIVED'
    assert receipt['original_outcome']['data'] == {
        'resource_kind': 'EXECUTION_PROFILE',
        'resource_id': 1,
    }
    assert receipt['original_http_status'] == 201
    assert 'private original input' not in response.text
    rejected = identity()
    scope = registered_command(rejected['method'], rejected['path'], rejected['request_key']).scope
    executor.execute(
        scope,
        {},
        lambda _: Rejection(
            'AUTHORIZATION_NOT_APPLICABLE', {'task_id': None, 'authorization_id': None}
        ),
    )
    receipt = client.get('/api/v1/code-command-receipts', params=rejected).json()['data']
    assert receipt['record_status'] == 'REJECTED'
    assert receipt['original_http_status'] == 403
    assert receipt['original_outcome']['error']['details'] == {
        'task_id': None,
        'authorization_id': None,
    }


def test_storage_failure_is_503_not_missing_receipt_and_lease_retirement_fences_close(service):
    database, app, client = service
    original = identity()
    with patch.object(
        database, 'transaction', side_effect=StorageUnavailable('private internal fault')
    ):
        response = client.get('/api/v1/code-command-receipts', params=original)
    assert response.status_code == 503, response.text
    assert response.json()['error']['details'] == {'capability_codes': ['DATABASE']}
    assert 'private internal fault' not in response.text
    app.state.walle_http_lease.retire()
    response = close(client, original)
    assert response.status_code == 503, response.text
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0] == 0


def test_151_service_keeps_document_contract_and_refuses_200_control_without_upgrade(package):
    root, _ = package
    database = Database(root / 'source151.sqlite')
    database.initialize()
    with TestClient(create_app(database=database)) as client:
        response = close(client, identity())
        assert response.status_code == 503, response.text
        assert response.json()['error']['details'] == {'capability_codes': ['DATABASE']}
        assert client.get('/api/v1/requirements').status_code == 200
    with database.transaction() as connection:
        assert connection.execute('SELECT version FROM schema_migrations').fetchone()[0] == 151
        assert connection.execute('SELECT count(*) FROM idempotency_records').fetchone()[0] == 0
