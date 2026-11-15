"""Actual repository list/detail routes over isolated saved registrations."""

import json
from dataclasses import replace

import pytest

from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.code_tasks.repository_observation_publish import (
    publish_repository_observation,
    start_repository_observation,
)
from backend.app.code_tasks.repository_registration import (
    publish_repository_registration,
    start_repository_registration,
)
from backend.app.infrastructure.schema_transport import compact
from backend.tests.code_tasks.test_repository_acceptance import request
from backend.tests.code_tasks.test_repository_observation_publish import capture as observation
from backend.tests.code_tasks.test_repository_registration import capture as registration
from backend.tests.infrastructure.test_v20_command_http import package, service

PATH = '/api/v1/code-repositories'
AT = '2026-11-07T00:00:00.000Z'


def register(runtime):
    original = accept_repository_operation(runtime, request())['data']
    start_repository_registration(runtime, original['operation_id'])
    return publish_repository_registration(runtime, original['operation_id'], registration())


def observe(runtime, repository_id, status):
    accepted = accept_repository_operation(runtime, request(repository_id))['data']
    operation_id = accepted['operation_id']
    start_repository_observation(runtime, operation_id)
    with runtime.database.transaction(write=True) as connection:
        at = connection.execute(
            'SELECT started_at FROM code_operations WHERE id=?', (operation_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE code_operation_steps SET status='SUCCEEDED',started_at=?,ended_at=? "
            'WHERE operation_id=? AND step_no=1',
            (at, at, operation_id),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='RUNNING',started_at=? "
            'WHERE operation_id=? AND step_no=2',
            (at, operation_id),
        )
    source = observation()
    payload = json.loads(source.payload_json)
    payload['observed_at'] = AT
    if status != 'READABLE':
        payload.update(status=status, head_commit=None, local_branches=[], worktrees=[])
    return publish_repository_observation(
        runtime, operation_id, replace(source, payload_json=compact(payload))
    )


def test_list_and_detail_read_saved_repository_and_latest_original_status(service):
    database, app, client = service
    runtime = app.state.walle_runtime
    pending = accept_repository_operation(runtime, request())['data']
    before = client.get(PATH)
    assert before.status_code == 200 and before.json()['data'] == {'items': []}
    assert client.get(f'{PATH}/{pending["resource_id"]}').status_code == 404

    repository_id = register(runtime)
    assert client.get(f'{PATH}/{repository_id}').json()['data']['latest_observation'] is None
    first = observe(runtime, repository_id, 'READABLE')
    latest = observe(runtime, repository_id, 'UNKNOWN')
    assert latest > first
    summary = client.get(PATH)
    detail = client.get(f'{PATH}/{repository_id}')
    assert summary.status_code == detail.status_code == 200, detail.text
    row = summary.json()['data']['items'][0]
    assert row == {
        'id': repository_id,
        'name': 'fixture',
        'object_format': 'sha1',
        'created_at': row['created_at'],
        'root_path': None,
        'latest_observation': {'id': latest, 'status': 'UNKNOWN', 'observed_at': AT},
    }
    assert detail.json()['data'] == {**row, 'root_path': registration().canonical_root}
    assert 'pagination' not in detail.json()['meta']
    assert 'git_common_dir' not in detail.text
    assert (
        client.get(f'{PATH}/{repository_id}/observations/{first}').json()['data']['status']
        == 'READABLE'
    )
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_operations').fetchone()[0] == 4
        assert (
            connection.execute('SELECT count(*) FROM code_repository_observations').fetchone()[0]
            == 2
        )
        assert connection.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0


def test_saved_list_preserves_stable_order_and_actual_overflow(service):
    database, _, client = service
    with database.transaction(write=True) as connection:
        connection.executemany(
            'INSERT INTO code_repositories VALUES(?,?,?,?,?,?)',
            [
                (
                    number,
                    f'仓库 {number}',
                    f'C:\\data{number}',
                    f'C:\\data{number}\\.git',
                    'sha256',
                    AT,
                )
                for number in range(1, 22)
            ],
        )
    first, second, beyond = [client.get(PATH, params={'page': index}) for index in (1, 2, 3)]
    assert first.status_code == second.status_code == beyond.status_code == 200
    assert [row['id'] for row in first.json()['data']['items']] == list(range(21, 1, -1))
    assert [row['id'] for row in second.json()['data']['items']] == [1]
    assert beyond.json()['data'] == {'items': []}
    assert beyond.json()['meta']['pagination'] == {
        'page': 3,
        'page_size': 20,
        'total': 21,
        'total_pages': 2,
    }


def test_read_boundaries_reject_path_overrides_and_report_storage_retirement(service):
    _, app, client = service
    for target in ('?page=0', '?page=1&page=2', '?root_path=elsewhere', '/01', '/1?page=1'):
        assert client.get(PATH + target).status_code == 422
    assert (
        client.get(PATH, headers={'Idempotency-Key': request().idempotency_key}).status_code == 422
    )
    app.state.walle_worker.accepting = False
    for target in (PATH, PATH + '/1'):
        unavailable = client.get(target)
        assert unavailable.status_code == 503
        assert unavailable.json()['error']['details'] == {'capability_codes': ['DATABASE']}
