"""Budget-only control versions, original receipts, and active-window invariants."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import pytest

from backend.app.code_tasks.coding_model_wait import hold_coding_model
from backend.app.code_tasks.task_model_ingress import ModelWindow
from backend.app.code_tasks.task_start_session import advance_start_session
from backend.tests.code_tasks.test_task_start import (
    isolated_readiness,
    original_operation,
    start,
    stop,
)
from backend.tests.code_tasks.test_task_start_instance import original_instance
from backend.tests.code_tasks.test_task_start_session import NativeDriver, ready
from backend.tests.code_tasks.test_task_stop import seed_task
from backend.tests.infrastructure.test_v20_command_http import package, service


def budget(client, task_id, version, amount, key=None, **extra):
    return client.post(
        f'/api/v1/code-tasks/{task_id}/budget',
        headers={'Idempotency-Key': key or str(uuid4())},
        json={
            'expected_state_version': version,
            'new_budget_limit_cny': amount,
            'reason': '为原任务明确追加预算',
            **extra,
        },
    )


@pytest.mark.parametrize('queued_start', [False, True])
def test_budget_receipt_replays_and_keeps_unstarted_stop_provable(
    service, isolated_readiness, queued_start
):
    database, app, client = service
    task_id = seed_task(database, app.state.walle_runtime, client)
    path = f'/api/v1/code-tasks/{task_id}'
    key = str(uuid4())
    assert budget(client, task_id, 1, '0.100000').json()['error']['code'] == 'BUDGET_NOT_INCREASED'
    assert budget(client, task_id, 1, 1).status_code == 422
    assert budget(client, task_id, 1, '1.1', reason='   ').status_code == 422
    first = budget(client, task_id, 1, '0.21', key)
    assert first.status_code == 200, first.text
    original = first.json()['data']
    assert original['state_version'] == 2
    assert original['budget']['limit_cny'] == '0.210000'
    assert original['active_operations'] == []
    assert client.get(path).json()['data'] == original
    assert budget(client, task_id, 1, '0.22').json()['error']['code'] == 'VERSION_CONFLICT'
    assert (
        budget(client, task_id, 1, '0.210000', key).json()['error']['code'] == 'OPERATION_CONFLICT'
    )
    assert budget(client, task_id, 2, '0.25').status_code == 200
    assert budget(client, task_id, 1, '0.21', key).json()['data'] == original
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': path + '/budget',
            'request_key': key,
        },
    ).json()['data']
    assert receipt['task_id'] == task_id and receipt['operation_id'] is None
    assert receipt['original_outcome']['data'] == original
    version = 3
    if queued_start:
        started = start(client, task_id, version=version)
        assert started.status_code == 202, started.text
        version += 1
        raised = budget(client, task_id, version, '0.26')
        assert raised.status_code == 200, raised.text
        original_start = started.json()['data']['operation_id']
        assert raised.json()['data']['active_operations'] == [
            {'id': original_start, 'operation_type': 'START', 'status': 'PENDING'},
        ]
        version += 1
    stopped = stop(client, task_id, version)
    assert stopped.status_code == 202, stopped.text
    identity = stopped.json()['data']['operation_id']
    deadline = monotonic() + 5
    while original_operation(client, identity)['status'] != 'SUCCEEDED':
        assert monotonic() < deadline
        sleep(0.03)
    assert budget(client, task_id, version + 2, '0.26').json()['error']['code'] == 'TASK_ENDED'
    assert budget(client, task_id, 1, '0.21', key).json()['data'] == original
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_workspaces').fetchone()[0] == 0


def test_budget_wait_keeps_window_and_original_items(ready):
    database, runtime, client, parent, task_id, _, receipt = ready
    driver = NativeDriver()
    assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
    assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
    scope = driver.calls[-1][1]
    window = ModelWindow(
        task_id,
        scope.instance_id,
        scope.control_generation,
        scope.session_id,
        'ses_original',
        receipt['operation_id'],
        'msg_original',
    )
    with database.transaction(write=True) as connection:
        hold_coding_model(connection, window, driver.credential, kind='BUDGET')
        saved_window = connection.execute('SELECT model_window FROM code_sessions').fetchone()[0]
    path = f'/api/v1/code-tasks/{task_id}'
    prior = client.get(path).json()['data']
    assert prior['status'] == 'WAITING'
    with ThreadPoolExecutor(max_workers=2) as callers:
        results = list(callers.map(lambda amount: budget(client, task_id, 5, amount), ('1', '2')))
    assert sorted(result.status_code for result in results) == [200, 409]
    current = client.get(path).json()['data']
    assert current['state_version'] == 6
    for field in (
        'status',
        'phase',
        'resume_phase',
        'waiting_items',
        'control_generation',
        'active_session_id',
    ):
        assert current[field] == prior[field]
    with database.transaction() as connection:
        assert (
            connection.execute('SELECT model_window FROM code_sessions').fetchone()[0]
            == saved_window
        )
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
        assert (
            connection.execute(
                'SELECT count(*) FROM code_operations WHERE task_id=?', (task_id,)
            ).fetchone()[0]
            == 1
        )


def test_budget_during_native_start_keeps_dispatch_identity(ready):
    database, runtime, client, parent, task_id, _, receipt = ready
    driver = NativeDriver()
    action = {'cancelled': lambda: False, 'driver': driver}
    path = f'/api/v1/code-tasks/{task_id}'

    def increase(scope, amount):
        task = client.get(path).json()['data']
        version = task['state_version']
        response = budget(client, task_id, version, amount)
        assert response.status_code == 200, response.text
        assert response.json()['data']['state_version'] == version + 1
        assert response.json()['data']['active_operations'][0]['id'] == receipt['operation_id']
        assert scope.state_version == receipt['state_version'] + 1

    driver.on_create = lambda scope: increase(scope, '0.34')
    driver.on_send = lambda scope: increase(scope, '0.48')
    assert advance_start_session(runtime, parent, **action)
    assert advance_start_session(runtime, parent, **action)
    assert len(driver.calls) == 2
    current = client.get(path).json()['data']
    assert current['status'] == 'RUNNING'
    assert current['state_version'] == receipt['state_version'] + 4
    assert current['budget']['limit_cny'] == '0.480000'
    assert original_operation(client, receipt['operation_id'])['status'] == 'SUCCEEDED'
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_sessions').fetchone()[0] == 1
        assert (
            connection.execute(
                'SELECT count(*) FROM code_operations WHERE task_id=?', (task_id,)
            ).fetchone()[0]
            == 1
        )
