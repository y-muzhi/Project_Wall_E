"""Original question and permission observations, durable ownership and public reads."""

from datetime import datetime, timedelta

import pytest

from backend.app.code_tasks import task_runtime_stop
from backend.app.code_tasks.task_native_issues import advance_native_issue_observation
from backend.app.code_tasks.task_model_ingress import read_original_window_state
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.command_execution import operation_time
from backend.tests.code_tasks.test_coding_model_gateway import fixed_price, opened
from backend.tests.code_tasks.test_task_start import isolated_readiness, stop
from backend.tests.code_tasks.test_task_start_instance import original_instance
from backend.tests.code_tasks.test_task_start_session import ready
from backend.tests.code_tasks.test_task_runtime_stop import StopDriver
from backend.tests.infrastructure.test_v20_command_http import package, service


class OriginalIssueDriver:
    def __init__(self, window):
        self.window = window
        self.mode = 'open'
        self.on_read = None

    def session_available(self, identity):
        return identity == self.window.operation_id

    def observe_native_issues(self, scope, native, checkpoint):
        assert (
            native == self.window.native_session_id
            and scope.session_id == self.window.execution_session_id
        )
        checkpoint()
        if self.on_read:
            self.on_read()
        if self.mode == 'offline':
            raise TaskExecutionError('ORIGINAL_OPENCODE_RESULT_UNVERIFIED')
        if self.mode == 'empty':
            return (), ()
        return (
            (
                {
                    'id': 'que_original',
                    'sessionID': native,
                    'questions': [
                        {
                            'header': '原问题',
                            'question': '请核对行为',
                            'options': [{'label': '已核对', 'description': '说明'}],
                        },
                        {
                            'header': '另一题',
                            'question': '原第二项',
                            'options': [],
                            'custom': False,
                            'multiple': True,
                        },
                    ],
                },
            ),
            (
                {
                    'id': 'per_original',
                    'sessionID': native,
                    'permission': 'bash',
                    'patterns': ['echo *'],
                    'metadata': {'private_payload': 'private-opaque'},
                    'always': ['*'],
                    'tool': {'messageID': 'msg_original', 'callID': 'tool_original'},
                },
            ),
        )


def test_original_issues_are_persisted_and_missing_does_not_resolve(opened):
    db, runtime, client, proof, credential, _ = opened
    window = proof.window
    path = f'/api/v1/code-tasks/{window.task_id}'
    for resource in ('questions', 'permissions'):
        empty = client.get(path + '/' + resource)
        assert empty.status_code == 200, empty.text
        assert empty.json()['data']['items'] == []
        assert empty.json()['meta']['pagination']['total'] == 0
        assert (
            client.get(
                path + '/' + resource, params=[('status', 'OPEN'), ('status', 'UNKNOWN')]
            ).status_code
            == 422
        )
        assert client.get(path + '/' + resource, params={'status': 'MISSING'}).status_code == 422
    driver = OriginalIssueDriver(window)
    cursor = advance_native_issue_observation(runtime, driver, 0, cancelled=lambda: False)
    assert cursor == window.task_id
    task_response = client.get(path)
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()['data']
    assert task['status'] == 'WAITING' and task['state_version'] == 5
    assert [item['kind'] for item in task['waiting_items']] == ['QUESTION', 'PERMISSION']
    for resource in ('questions', 'permissions'):
        listing = client.get(path + '/' + resource, params={'status': 'OPEN'})
        assert listing.status_code == 200, listing.text
        assert listing.json()['meta']['pagination']['total'] == 1
        assert listing.json()['data']['items'][0]['task_id'] == window.task_id
        assert listing.json()['data']['items'][0]['available_actions'][0]['enabled'] is False
        assert client.get(path + '/' + resource, params={'page': 2}).json()['data']['items'] == []
        assert (
            client.get(f'/api/v1/code-tasks/{window.task_id + 100}/{resource}').status_code == 404
        )
    question = client.get(path + '/questions').json()['data']['items'][0]
    assert (
        question['questions'][0]['multiple'] is False and question['questions'][0]['custom'] is True
    )
    assert question['questions'][1]['index'] == 1 and question['questions'][1]['custom'] is False
    permission = client.get(path + '/permissions').json()['data']['items'][0]
    assert permission['requested_action'] == 'EXECUTE' and permission['object_refs'] == []
    assert 'private_payload' not in str(permission) and 'always' not in permission
    with db.transaction() as connection:
        assert read_original_window_state(connection, window, credential) is None
    advance_native_issue_observation(runtime, driver, cursor, cancelled=lambda: False)
    assert client.get(path).json()['data']['state_version'] == 5
    driver.mode = 'offline'
    advance_native_issue_observation(runtime, driver, cursor, cancelled=lambda: False)
    assert client.get(path + '/questions').json()['data']['items'][0]['status'] == 'OPEN'
    driver.mode = 'empty'
    advance_native_issue_observation(runtime, driver, cursor, cancelled=lambda: False)
    for resource in ('questions', 'permissions'):
        view = client.get(path + '/' + resource).json()['data']['items'][0]
        assert view['status'] == 'UNKNOWN' and view['resolved_at'] is None
    assert client.get(path).json()['data']['waiting_items'] == task['waiting_items']
    driver.mode = 'open'
    advance_native_issue_observation(runtime, driver, cursor, cancelled=lambda: False)
    assert client.get(path + '/questions').json()['data']['items'][0]['status'] == 'OPEN'
    assert client.get(path).json()['data']['waiting_items'] == task['waiting_items']


def test_stop_fences_late_issue_observation(opened):
    _, runtime, client, proof, _, _ = opened
    window = proof.window
    driver = OriginalIssueDriver(window)
    driver.on_read = lambda: stop(client, window.task_id, 4).raise_for_status()
    advance_native_issue_observation(runtime, driver, 0, cancelled=lambda: False)
    path = f'/api/v1/code-tasks/{window.task_id}'
    assert client.get(path + '/questions').json()['data']['items'] == []
    assert client.get(path + '/permissions').json()['data']['items'] == []


def test_owned_stop_retires_open_issues_without_fabricating_answers(opened, ready, monkeypatch):
    _, runtime, client, proof, _, _ = opened
    window = proof.window
    advance_native_issue_observation(
        runtime, OriginalIssueDriver(window), 0, cancelled=lambda: False
    )
    path = f'/api/v1/code-tasks/{window.task_id}'
    response = stop(client, window.task_id, 5)
    assert response.status_code == 202, response.text
    clock = datetime.fromisoformat(operation_time(None)) + timedelta(seconds=3)
    monkeypatch.setattr(
        task_runtime_stop,
        'operation_time',
        lambda _: clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
    )
    driver = StopDriver(ready[3])
    for index in range(6):
        if index == 3:
            clock += timedelta(days=1)
        assert task_runtime_stop.advance_owned_stops(runtime, driver, cancelled=lambda: False)
    task = client.get(path).json()['data']
    assert task['status'] == 'TERMINATED' and task['waiting_items'] == []
    for resource in ('questions', 'permissions'):
        rows = client.get(path + '/' + resource, params={'status': 'OBSOLETE'}).json()['data'][
            'items'
        ]
        assert len(rows) == 1 and rows[0]['resolved_at'] is None
        assert all(action['reason_code'] == 'TASK_ENDED' for action in rows[0]['available_actions'])
