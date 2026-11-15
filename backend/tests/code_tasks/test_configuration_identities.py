"""Four real configuration identity endpoints, original ledger and private Schema200."""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.app.code_tasks import configuration_identities as identities
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown, StorageUnavailable
from backend.app.service import create_app
from backend.tests.infrastructure.test_v20_command_http import package, service, close

PATHS = (
    (
        '/api/v1/code-execution-profiles',
        'EXECUTION_PROFILE',
        'code_execution_profiles',
        'ExecutionProfile',
    ),
    ('/api/v1/code-check-sets', 'CHECK_SET', 'code_check_sets', 'CheckSet'),
)


def create(client, path, name, key=None):
    return client.post(path, json={'name': name}, headers={'Idempotency-Key': key or str(uuid4())})


@pytest.mark.parametrize('path,kind,table,sequence', PATHS)
def test_actual_create_replay_receipt_and_no_implicit_version_or_execution(
    service, path, kind, table, sequence
):
    database, app, client = service
    key = str(uuid4())
    first = create(client, path, '配置名称', key)
    replay = create(client, path, '配置名称', key)
    assert first.status_code == replay.status_code == 201, first.text
    assert (
        first.json()['data'] == replay.json()['data'] == {'resource_kind': kind, 'resource_id': 1}
    )
    assert first.json()['meta']['request_id'] != replay.json()['meta']['request_id']
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': path,
            'request_key': key,
        },
    ).json()['data']
    assert receipt['record_status'] == 'SUCCEEDED'
    assert receipt['original_http_status'] == 201
    assert receipt['original_outcome']['data'] == first.json()['data']
    with database.transaction() as connection:
        assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 1
        assert (
            connection.execute(
                'SELECT last_value FROM sequences WHERE entity_kind=?', (sequence,)
            ).fetchone()[0]
            == 1
        )
        for unused in (
            'code_execution_profile_versions',
            'code_check_set_versions',
            'code_authorizations',
            'code_tasks',
            'testing_tasks',
            'code_operations',
            'llm_uses',
        ):
            assert connection.execute(f'SELECT COUNT(*) FROM {unused}').fetchone()[0] == 0
    assert not any(row['event'].startswith('DISPATCH') for row in app.state.walle_worker.events)
    assert client.get(path).json()['data'] == {
        'items': [
            {'id': 1, 'name': '配置名称', 'latest_version_id': None},
        ]
    }


@pytest.mark.parametrize('path,kind,table,sequence', PATHS)
def test_duplicate_display_names_have_distinct_identity_only_when_new_intent(
    service, path, kind, table, sequence
):
    _, _, client = service
    first = create(client, path, '同名')
    second = create(client, path, '同名')
    assert first.status_code == second.status_code == 201
    assert first.json()['data']['resource_id'] != second.json()['data']['resource_id']


def test_closed_original_request_precedes_new_fingerprint_and_never_creates_identity(service):
    database, _, client = service
    path = PATHS[0][0]
    original = {'method': 'POST', 'path': path, 'request_key': str(uuid4())}
    assert close(client, original).status_code == 200
    response = create(client, path, '迟到不同名称', original['request_key'])
    assert response.status_code == 409 and response.json()['error']['code'] == 'COMMAND_CLOSED'
    with database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM code_execution_profiles').fetchone()[0] == 0
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM sequences WHERE entity_kind=?', ('ExecutionProfile',)
            ).fetchone()[0]
            == 0
        )


def test_same_key_changed_input_is_conflict_without_second_allocation(service):
    database, _, client = service
    path = PATHS[1][0]
    key = str(uuid4())
    assert create(client, path, '原名称', key).status_code == 201
    result = create(client, path, '新名称', key)
    assert result.status_code == 409 and result.json()['error']['code'] == 'OPERATION_CONFLICT'
    with database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM code_check_sets').fetchone()[0] == 1


@pytest.mark.parametrize(
    'query', ['page=0', 'page=01', 'page=100001', 'page=', 'page=1&page=2', 'page_size=1', 'kind=x']
)
def test_page_shape_is_strict_and_uses_no_database_after_rejection(service, query):
    database, _, client = service
    with patch.object(database, 'transaction', side_effect=AssertionError('No read')):
        response = client.get(PATHS[0][0] + '?' + query)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    'body',
    [
        {'name': ''},
        {'name': '\u3000'},
        {'name': None},
        {'name': 1},
        {'name': '\0'},
        {'name': 'x', 'id': 3},
        {},
    ],
)
def test_invalid_input_never_creates_identity_or_claim(service, body):
    database, _, client = service
    response = client.post(PATHS[0][0], json=body, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 422, response.text
    with database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM code_execution_profiles').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM idempotency_records').fetchone()[0] == 0


def test_snapshot_pagination_keeps_real_empty_and_out_of_range_pages(service):
    database, _, client = service
    path = PATHS[0][0]
    empty = client.get(path + '?page=100000').json()
    assert empty['data'] == {'items': []}
    assert empty['meta']['pagination'] == {
        'page': 100000,
        'page_size': 20,
        'total': 0,
        'total_pages': 0,
    }
    with database.transaction(write=True) as connection:
        connection.executemany(
            'INSERT INTO code_execution_profiles(id,name,created_at) VALUES(?,?,?)',
            [(index, '配置' + str(index), '2026-11-05T00:00:00.000Z') for index in range(1, 24)],
        )
    first = client.get(path).json()
    second = client.get(path + '?page=2').json()
    outside = client.get(path + '?page=3').json()
    assert [row['id'] for row in first['data']['items']] == list(range(23, 3, -1))
    assert [row['id'] for row in second['data']['items']] == [3, 2, 1]
    assert outside['data'] == {'items': []}
    assert outside['meta']['pagination'] == {
        'page': 3,
        'page_size': 20,
        'total': 23,
        'total_pages': 2,
    }


def test_latest_check_version_is_original_highest_coding_version_not_testing(service):
    database, _, client = service
    path = PATHS[1][0]
    assert create(client, path, '检查集合').status_code == 201
    with database.transaction(write=True) as connection:
        connection.executemany(
            'INSERT INTO code_check_set_versions VALUES(?,?,?,?,?,?,?,?)',
            [
                (11, 1, 1, 'CODING', 'CHECK20-CONTROL-1', '[]', '[]', '2026-11-05T00:00:00.000Z'),
                (12, 1, 2, 'CODING', 'CHECK20-CONTROL-1', '[]', '[]', '2026-11-05T00:00:00.000Z'),
                (13, 1, 3, 'TESTING', 'CHECK20-CONTROL-1', '[]', '[]', '2026-11-05T00:00:00.000Z'),
            ],
        )
    assert client.get(path).json()['data']['items'][0]['latest_version_id'] == 12


def test_insert_failure_rolls_back_original_counter_and_claim_in_one_transaction(service):
    database, _, client = service
    with patch.object(identities, 'operation_time', return_value='invalid timestamp'):
        response = create(client, PATHS[0][0], '事务失败')
    assert response.status_code == 503, response.text
    with database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM code_execution_profiles').fetchone()[0] == 0
        assert (
            connection.execute(
                'SELECT COUNT(*) FROM sequences WHERE entity_kind=?', ('ExecutionProfile',)
            ).fetchone()[0]
            == 0
        )
        assert connection.execute('SELECT COUNT(*) FROM idempotency_records').fetchone()[0] == 0


def test_lost_commit_ack_is_recovered_by_original_receipt_without_duplicate_create(service):
    database, _, client = service
    original = database.transaction

    @contextmanager
    def lost(*, write=False):
        with original(write=write) as connection:
            yield connection
        if write:
            raise CommitOutcomeUnknown('Owned lost commit acknowledgment')

    path, key = PATHS[0][0], str(uuid4())
    with patch.object(database, 'transaction', side_effect=lost):
        response = create(client, path, '原提交', key)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'STORAGE_UNAVAILABLE'
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': path,
            'request_key': key,
        },
    ).json()['data']
    assert receipt['record_status'] == 'SUCCEEDED'
    assert receipt['original_outcome']['data']['resource_id'] == 1
    assert create(client, path, '原提交', key).status_code == 201
    with database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM code_execution_profiles').fetchone()[0] == 1


def test_get_is_one_read_snapshot_and_never_launches_process_or_writes(service):
    database, _, client = service
    original = database.transaction
    writes = []

    @contextmanager
    def observe(*, write=False):
        writes.append(write)
        with original(write=write) as connection:
            yield connection

    with patch.object(database, 'transaction', side_effect=observe):
        with patch('subprocess.Popen', side_effect=AssertionError('No process on GET')):
            response = client.get(PATHS[0][0])
    assert response.status_code == 200, response.text
    assert writes == [False]


def test_storage_failure_and_retired_owner_are_503_not_empty_lists(service):
    database, app, client = service
    with patch.object(
        database, 'transaction', side_effect=StorageUnavailable('private store error')
    ):
        response = client.get(PATHS[0][0])
    assert response.status_code == 503
    assert response.json()['error']['details'] == {'capability_codes': ['DATABASE']}
    assert 'private store error' not in response.text
    app.state.walle_http_lease.retire()
    assert client.get(PATHS[1][0]).status_code == 503


def test_151_service_never_adds_config_tables_or_updates_document_data(package):
    root, _ = package
    database = Database(root / ('legacy-config-' + uuid4().hex + '.sqlite'))
    database.initialize()
    with TestClient(create_app(database=database)) as client:
        assert create(client, PATHS[0][0], '拒绝151').status_code == 503
        assert client.get(PATHS[1][0]).status_code == 503
        assert client.get('/api/v1/requirements').status_code == 200
    with database.transaction() as connection:
        assert connection.execute('SELECT version FROM schema_migrations').fetchone()[0] == 151
        assert connection.execute('SELECT COUNT(*) FROM idempotency_records').fetchone()[0] == 0


@pytest.mark.parametrize('corruption', ['extra', 'kind', 'status', 'code'])
def test_original_receipt_replay_and_close_never_expose_corrupt_creation_result(
    service, corruption
):
    database, app, client = service
    path, key = PATHS[0][0], str(uuid4())
    assert create(client, path, '原名称').status_code == 201
    original = {
        'code': 'CREATED',
        'data': {'resource_kind': 'EXECUTION_PROFILE', 'resource_id': 1},
        'details': None,
    }
    status = 201
    marker = 'PRIVATE_EXTRA_FIELD_DO_NOT_RETURN'
    if corruption == 'extra':
        original['data']['private_extra'] = marker
    elif corruption == 'kind':
        original['data']['resource_kind'] = 'CHECK_SET'
    elif corruption == 'status':
        status = 200
    else:
        original['code'] = 'UPDATED'
    from backend.app.code_tasks.command_registry import registered_command
    from backend.app.infrastructure.idempotency import canonical_input

    # Existing terminal records are immutable. Insert a deliberately malformed
    # INITIAL fixture row without disabling/changing any product protection.
    command = registered_command('POST', path, key)
    at = '2026-11-05T00:00:00.000Z'
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO idempotency_records('
            'capability_id,target_identity,idempotency_key,business_input_json,status,'
            'owner_epoch,created_at,updated_at,success_result_json,http_status,error_result_json'
            ') VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (
                *command.scope.identity,
                canonical_input({'name': '原名称'}),
                'SUCCEEDED',
                app.state.walle_runtime.commands().owner_epoch,
                at,
                at,
                canonical_input(original),
                status,
                None,
            ),
        )
    responses = [
        client.get(
            '/api/v1/code-command-receipts',
            params={
                'method': 'POST',
                'path': path,
                'request_key': key,
            },
        ),
        create(client, path, '原名称', key),
        close(client, {'method': 'POST', 'path': path, 'request_key': key}),
    ]
    for response in responses:
        assert response.status_code == 500, response.text
        assert response.json()['error']['code'] == 'INTERNAL_ERROR'
        assert marker not in response.text
    with database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM code_execution_profiles').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM idempotency_records').fetchone()[0] == 2


def test_malformed_native_success_rolls_back_callback_writes_before_acceptance(service):
    from backend.app.infrastructure.idempotency import Success
    from backend.app.code_tasks.command_registry import registered_command

    database, app, _ = service
    key = str(uuid4())
    scope = registered_command('POST', PATHS[0][0], key).scope

    def invalid(connection):
        connection.execute(
            'INSERT INTO code_execution_profiles VALUES(1,?,?)',
            ('不能提交', '2026-11-05T00:00:00.000Z'),
        )
        return Success(
            {
                'code': 'CREATED',
                'data': {
                    'resource_kind': 'EXECUTION_PROFILE',
                    'resource_id': 1,
                    'private_extra': 'secret',
                },
                'details': None,
            },
            201,
        )

    with pytest.raises(ValueError, match='success contract differs'):
        app.state.walle_runtime.commands().execute(scope, {'name': '不能提交'}, invalid)
    with database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM code_execution_profiles').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM idempotency_records').fetchone()[0] == 0
