"""Isolated API47 scope, exact confirmations, original receipts and recovery."""

from uuid import uuid4

import pytest

from backend.app.code_tasks import task_permission_response as response
from backend.app.code_tasks.task_model_ingress import read_original_window_state
from backend.app.code_tasks.task_native_issues import advance_native_issue_observation
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.tests.code_tasks.test_coding_model_gateway import fixed_price, opened
from backend.tests.code_tasks.test_task_native_issues import OriginalIssueDriver
from backend.tests.code_tasks.test_task_start import isolated_readiness, original_operation, stop
from backend.tests.code_tasks.test_task_start_instance import original_instance
from backend.tests.code_tasks.test_task_start_session import ready
from backend.tests.infrastructure.test_v20_command_http import package, service


def pending(window, identity, tool, pattern):
    return {
        'id': identity,
        'sessionID': window.native_session_id,
        'permission': tool,
        'patterns': [pattern],
        'always': ['*'],
        'metadata': {},
    }


class Driver:
    def __init__(self, database, window, credential):
        self.database, self.window, self.credential = database, window, credential
        self.permissions = [
            pending(window, 'per_selected', 'read', 'src/main.ts'),
            pending(window, 'per_peer', 'bash', 'echo fixture'),
        ]
        self.sends = []
        self.mode = 'all'

    def session_available(self, start):
        return start == self.window.operation_id

    def observe_native_issues(self, scope, native, checkpoint):
        assert scope.session_id == self.window.execution_session_id
        assert native == self.window.native_session_id
        checkpoint()
        questions, _ = OriginalIssueDriver(self.window).observe_native_issues(
            scope, native, checkpoint
        )
        return (questions if self.mode == 'question-wait' else ()), tuple(self.permissions)

    def decide_native_permission(self, scope, dispatch, checkpoint, claim, record):
        native, original, candidates, reply = dispatch
        assert native == self.window.native_session_id and original['id'] == 'per_selected'
        if self.mode == 'wrong-path':
            raise TaskExecutionError('ORIGINAL_PERMISSION_OBJECT_DIFFERS')
        checkpoint()
        claim()
        self.sends.append((reply, candidates))
        with self.database.transaction() as connection:
            queued = reply == 'reject' and self.mode != 'question-wait'
            assert read_original_window_state(connection, self.window, self.credential) == (
                'QUEUED' if queued else None
            )
        if self.mode == 'crash':
            raise KeyboardInterrupt('isolated worker loss after durable dispatch')
        if reply == 'once':
            record('per_selected', {'source': 'HTTP_200'})
        else:
            record('per_selected', {'source': 'NATIVE_EVENT', 'event_id': 'evt_original'})
            if self.mode not in ('partial', 'crash'):
                record('per_peer', {'source': 'NATIVE_EVENT', 'event_id': 'evt_peer'})
            if self.mode == 'question-wait':
                assert 'per_peer' in candidates


@pytest.fixture
def permissions(opened, monkeypatch):
    db, runtime, client, proof, credential, _ = opened
    driver = Driver(db, proof.window, credential)
    advance_native_issue_observation(runtime, driver, 0, cancelled=lambda: False)
    decide = response.decide_permission
    monkeypatch.setattr(
        response, 'decide_permission', lambda rt, rq, *, available: decide(rt, rq, available=True)
    )
    path = f'/api/v1/code-tasks/{proof.window.task_id}'

    def rows():
        result = client.get(path + '/permissions')
        assert result.status_code == 200, result.text
        return {item['native_permission_id']: item for item in result.json()['data']['items']}

    return db, runtime, client, path, driver, rows


@pytest.mark.parametrize(
    'mode', ['all', 'partial', 'question-wait', 'once', 'wrong-path', 'crash', 'stop']
)
def test_api47_persists_only_proven_permission_decisions(permissions, mode):
    db, runtime, client, path, driver, rows = permissions
    original = rows()
    selected = original['per_selected']
    peer = original['per_peer']
    assert selected['object_refs'] == [{'kind': 'WORKSPACE_PATH', 'path': 'src/main.ts'}]
    assert peer['object_refs'] == []
    decision = 'ALLOW_ONCE' if mode in ('once', 'wrong-path') else 'DENY'
    driver.mode = mode
    body = {
        'expected_state_version': 5,
        'session_id': driver.window.execution_session_id,
        'decision': decision,
    }
    endpoint = f'{path}/permissions/{selected["id"]}/responses'
    key = str(uuid4())

    def post(target, data, original_key=None):
        return client.post(
            target, json=data, headers={'Idempotency-Key': original_key or str(uuid4())}
        )

    denied = post(f'{path}/permissions/{peer["id"]}/responses', {**body, 'decision': 'ALLOW_ONCE'})
    assert denied.status_code == 403, denied.text
    assert denied.json()['error']['code'] == 'PERMISSION_NOT_GRANTED'
    assert post(endpoint, {**body, 'decision': 'always'}).status_code == 422
    assert (
        post(endpoint, {**body, 'session_id': body['session_id'] + 1}).json()['error']['code']
        == 'SESSION_NOT_CURRENT'
    )
    accepted = post(endpoint, body, key)
    assert accepted.status_code == 202, accepted.text
    receipt = accepted.json()['data']
    operation_id = receipt['operation_id']
    assert receipt['state_version'] == 6
    assert post(endpoint, body, key).json()['data'] == receipt
    assert original_operation(client, operation_id)['status'] == 'PENDING'
    before_records = client.get(path + '/records').json()['data']['items']
    assert all(row['source_id'] != operation_id for row in before_records)
    task = client.get(path).json()['data']
    assert task['active_operations'] == [
        {'id': operation_id, 'operation_type': 'DECIDE_PERMISSION', 'status': 'PENDING'},
    ]
    assert rows()['per_selected']['status'] == 'ANSWERING'
    queried = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': endpoint,
            'request_key': key,
        },
    )
    assert queried.status_code == 200, queried.text
    assert queried.json()['data']['operation_id'] == operation_id

    def advance():
        return response.advance_permission_responses(runtime, driver, cancelled=lambda: False)

    if mode == 'stop':
        assert stop(client, driver.window.task_id, 6).status_code == 202
        assert not advance() and not driver.sends
        return
    if mode == 'crash':
        with pytest.raises(KeyboardInterrupt, match='worker loss'):
            advance()
    assert advance()
    assert not advance()
    current = rows()
    view = original_operation(client, operation_id)
    assert 'evt_original' not in str(view) and 'echo fixture' not in str(view)
    records = client.get(path + '/records', params={'session_id': body['session_id']})
    assert records.status_code == 200, records.text
    items = records.json()['data']['items']
    assert items[: len(before_records)] == before_records
    items = items[len(before_records) :]
    if mode in ('all', 'question-wait', 'once'):
        assert len(items) == 1
        assert (items[0]['kind'], items[0]['source_id']) == ('CONTROL', operation_id)
        assert 'evt_original' not in str(items) and 'echo fixture' not in str(items)
    else:
        assert items == []
    assert post(endpoint, body, key).json()['data'] == receipt
    if mode == 'wrong-path':
        assert view['status'] == 'FAILED' and view['failure_code'] == 'PERMISSION_NOT_GRANTED'
        assert current['per_selected']['status'] == 'OPEN' and not driver.sends
        return
    assert len(driver.sends) == 1
    assert driver.sends[0][0] == ('once' if decision == 'ALLOW_ONCE' else 'reject')
    if mode in ('partial', 'crash'):
        assert view['status'] == 'UNKNOWN'
        assert current['per_peer']['status'] == 'UNKNOWN'
        assert current['per_peer']['resolved_at'] is None
        result = view['steps'][1]['result_ref']
        assert result['confirmed_permission_ids'] == ([selected['id']] if mode == 'partial' else [])
        assert peer['id'] in result['pending_permission_ids']
        # Seeing the same original after an uncertain POST is not proof it can be sent again.
        advance_native_issue_observation(runtime, driver, 0, cancelled=lambda: False)
        assert rows()['per_peer']['status'] == 'UNKNOWN'
    else:
        assert view['status'] == 'SUCCEEDED'
        assert current['per_selected']['status'] == ('RESOLVED' if mode == 'once' else 'REJECTED')
        assert current['per_peer']['status'] == ('OPEN' if mode == 'once' else 'REJECTED')
    task = client.get(path)
    assert task.status_code == 200, task.text
    kinds = [row['kind'] for row in task.json()['data']['waiting_items']]
    if mode == 'question-wait':
        assert kinds == ['QUESTION']
    elif mode == 'all':
        assert kinds == [] and task.json()['data']['status'] == 'RUNNING'
    else:
        assert all(kind == 'PERMISSION' for kind in kinds) and kinds
