"""Original CREATE_SESSION/SEND_INITIAL on isolated SQLite with ASGI projections."""

import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest

from backend.app.code_tasks import task_start_session as flow
from backend.app.code_tasks.coding_model_listener import CodingModelListener
from backend.app.code_tasks.task_model_ingress import ModelWindow, read_original_open_window
from backend.app.code_tasks.task_runtime_launch import RuntimeTaskLaunch
from backend.app.code_tasks.task_start_instance import advance_start_instance
from backend.app.infrastructure.guard_task_model_source import AcceptedModelConnection
from backend.app.infrastructure.opencode_model_credential import OpenCodeModelCredential
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks.test_task_start import (
    isolated_readiness,
    original_operation,
    start,
    stop,
)
from backend.tests.code_tasks.test_task_start_instance import _evidence, original_instance
from backend.tests.infrastructure.test_v20_command_http import package, service

_NATIVE = 'ses_original'
_MESSAGE = 'msg_original'
_CREDENTIAL = 'a' * 32


class NativeDriver:
    def __init__(self):
        self.calls = []
        self.credential = _CREDENTIAL
        self.on_create = None
        self.on_send = None

    def session_available(self, operation_id):
        return operation_id > 0

    def gateway_reference(self, scope):
        return self.credential

    def initial_payload(self, scope, context):
        assert context.native_session_id == _NATIVE
        assert len(context.documents) == 2
        return {
            'messageID': _MESSAGE,
            'parts': [{'id': 'prt_first', 'type': 'text', 'text': '固定内容'}],
        }

    def create_session(self, scope, checkpoint):
        self.calls.append(('create', scope))
        checkpoint()
        if self.on_create:
            self.on_create(scope)
        return _NATIVE

    def send_initial(self, scope, original, payload, checkpoint):
        self.calls.append(('send', scope))
        checkpoint()
        if self.on_send:
            self.on_send(scope)
        assert original['native_message_id'] == payload['messageID']
        return payload['messageID']


@pytest.fixture
def ready(original_instance):
    _, runtime, _, parent, _, _, _ = original_instance

    class Driver:
        def start(self, original, checkpoint, *, cancelled):
            checkpoint()
            return _evidence(original.claim)

    assert advance_start_instance(runtime, parent, cancelled=lambda: False, driver=Driver())
    return original_instance


def test_original_start_finishes_after_confirmed_native_message(ready):
    database, runtime, client, parent, task_id, key, receipt = ready
    operation_id = receipt['operation_id']
    driver = NativeDriver()
    records_path = f'/api/v1/code-tasks/{task_id}/records'
    assert client.get(records_path).json()['data']['items'] == []

    def during_create(scope):
        assert scope.metadata()['walle']['execution_session_id'] == scope.session_id
        current = original_operation(client, operation_id)
        assert current['session_id'] == scope.session_id
        assert current['steps'][4]['status'] == 'RUNNING'
        assert client.get(f'/api/v1/code-tasks/{task_id}').json()['data']['status'] == 'PENDING'

    def during_send(scope):
        current = original_operation(client, operation_id)
        assert [step['status'] for step in current['steps'][4:]] == ['SUCCEEDED', 'RUNNING']
        detail = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']
        assert detail['status'] == 'PENDING' and detail['active_session_id'] is None
        assert client.get(records_path).json()['data']['items'] == []
        with database.transaction() as connection:
            session = connection.execute('SELECT * FROM code_sessions').fetchone()
            assert strict_json_object(session['model_window'])['state'] == 'QUEUED'
            expected = ModelWindow(
                task_id,
                scope.instance_id,
                scope.control_generation,
                scope.session_id,
                _NATIVE,
                operation_id,
                _MESSAGE,
            )
            assert read_original_open_window(connection, expected, _CREDENTIAL) is None

    driver.on_create, driver.on_send = during_create, during_send
    options = {'cancelled': lambda: False, 'driver': driver}
    assert flow.advance_start_session(runtime, parent, **options)
    driver.credential = None
    assert not flow.advance_start_session(runtime, parent, **options)
    driver.credential = _CREDENTIAL
    assert flow.advance_start_session(runtime, parent, **options)
    assert not flow.advance_start_session(runtime, parent, **options)
    operation = original_operation(client, operation_id)
    assert operation['status'] == 'SUCCEEDED'
    assert all(step['status'] == 'SUCCEEDED' for step in operation['steps'])
    assert operation['steps'][5]['result_ref'] == {'session_id': operation['session_id']}
    assert _NATIVE not in str(operation) and _MESSAGE not in str(operation)
    assert _CREDENTIAL not in str(operation)
    assert [name for name, _ in driver.calls] == ['create', 'send']
    assert driver.calls[0][1] == driver.calls[1][1]
    assert start(client, task_id, key=key).json()['data'] == receipt
    observed = client.get(records_path)
    assert observed.status_code == 200, observed.text
    records = observed.json()['data']['items']
    assert len(records) == 1
    assert records[0]['kind'] == 'CONTROL' and records[0]['source_id'] == operation_id
    assert records[0]['session_id'] == operation['session_id']
    assert (
        _NATIVE not in str(records)
        and _MESSAGE not in str(records)
        and _CREDENTIAL not in str(records)
    )
    assert (
        client.get(records_path, params={'session_id': operation['session_id']}).json()['data'][
            'items'
        ]
        == records
    )
    assert client.get(records_path, params={'session_id': 999}).status_code == 404
    assert client.get(records_path, params={'page': 2}).json()['data']['items'] == []
    response = client.get(f'/api/v1/code-tasks/{task_id}')
    assert response.status_code == 200, response.text
    task = response.json()['data']
    assert (task['status'], task['phase'], task['state_version']) == ('RUNNING', 'BACKEND', 4)
    assert task['active_session_id'] == operation['session_id']
    assert task['runtime']['activity_status'] == 'UNKNOWN'
    scope = driver.calls[1][1]
    with database.transaction() as connection:
        expected = ModelWindow(
            task_id,
            scope.instance_id,
            scope.control_generation,
            scope.session_id,
            _NATIVE,
            operation_id,
            _MESSAGE,
        )
        assert read_original_open_window(connection, expected, _CREDENTIAL) == expected
    stopped = stop(client, task_id, task['state_version'])
    assert stopped.status_code == 202, stopped.text
    current = client.get(f'/api/v1/code-tasks/{task_id}')
    assert current.status_code == 200, current.text
    assert current.json()['data']['status'] == 'STOPPING'
    with database.transaction() as connection:
        assert read_original_open_window(connection, expected, _CREDENTIAL) is None


@pytest.mark.parametrize('failure', ['create', 'send', 'stop', 'restart'])
def test_native_start_keeps_original_session_without_replay(ready, failure):
    database, runtime, client, parent, task_id, _, receipt = ready
    operation_id = receipt['operation_id']
    driver = NativeDriver()
    options = {'cancelled': lambda: False, 'driver': driver}

    def uncertain(scope):
        if failure == 'stop':
            response = stop(client, task_id, scope.state_version)
            assert response.status_code == 202, response.text
            return
        raise TaskExecutionError('FIXTURE_NATIVE_RESPONSE_UNKNOWN')

    if failure in ('send', 'stop'):
        assert flow.advance_start_session(runtime, parent, **options)
        driver.on_send = uncertain
    elif failure == 'restart':
        with database.transaction(write=True) as connection:
            flow._claim_session(connection, parent, operation_id)
    else:
        driver.on_create = uncertain

    assert flow.advance_start_session(runtime, parent, **options)
    assert not flow.advance_start_session(runtime, parent, **options)
    operation = original_operation(client, operation_id)
    assert operation['status'] == 'UNKNOWN'
    assert operation['steps'][5 if failure in ('send', 'stop') else 4]['status'] == 'UNKNOWN'
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_sessions').fetchone()[0] == 1
        session = connection.execute('SELECT * FROM code_sessions').fetchone()
        assert session['status'] == 'UNKNOWN'
        if failure in ('send', 'stop'):
            window = strict_json_object(session['model_window'])
            assert window['state'] == ('CLOSED' if failure == 'stop' else 'HELD')
            assert window['native_trigger_message_id'] == _MESSAGE
        else:
            assert session['model_window'] is None
        assert connection.execute('SELECT active_session_id FROM code_tasks').fetchone()[0] is None
    expected = {
        'create': ['create'],
        'restart': [],
        'send': ['create', 'send'],
        'stop': ['create', 'send'],
    }
    assert [name for name, _ in driver.calls] == expected[failure]


def _exchange(endpoint, route, *, secret='e' * 64, extras=(), sent=None):
    payload = b'{"model":"walle-code","messages":[{"role":"user","content":"fixture"}]}'
    host = f'{endpoint[0]}:{endpoint[1]}'
    lines = [
        'POST ' + route + ' HTTP/1.1',
        'Host: ' + host,
        'Content-Type: application/json',
        'Accept: text/event-stream',
        'Content-Length: ' + str(len(payload)),
        'Authorization: Bearer ' + secret,
        'x-opencode-session-id: ' + _NATIVE,
        *extras,
    ]
    with socket.create_connection(endpoint, timeout=5) as connection:
        connection.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode('ascii') + payload)
        if sent is not None:
            sent.set()
        response = bytearray()
        while chunk := connection.recv(8192):
            response.extend(chunk)
    return bytes(response)


def test_actual_dedicated_listener_waits_for_open_and_rechecks_its_original_accept(
    ready, monkeypatch
):
    database, runtime, client, parent, task_id, _, receipt = ready
    driver = NativeDriver()
    options = {'cancelled': lambda: False, 'driver': driver}
    assert flow.advance_start_session(runtime, parent, **options)
    scope = driver.calls[0][1]
    references, verified_connections = [], []
    launch = object.__new__(RuntimeTaskLaunch)
    launch._original = SimpleNamespace(
        scope=SimpleNamespace(operation_id=receipt['operation_id'], nonce=scope.nonce)
    )

    @contextmanager
    def connect():
        yield 'owned-frame'

    def verify_source(accepted, *, timeout_ms, cancelled, frames):
        assert frames == 'owned-frame' and not cancelled()
        connection = AcceptedModelConnection.from_accept(accepted)
        assert connection.server == listener.endpoint
        verified_connections.append(connection)
        return {'source_evidence_ref': 'a' * 64, 'connection_sha256': 'b' * 64}

    monkeypatch.setattr(launch, 'verify_model_source', verify_source)

    def dispatch(credential_ref, proof, raw, verify, stream, cancelled, *, instance_secret):
        assert not cancelled()
        assert instance_secret == 'e' * 64
        references.append((credential_ref, proof))
        assert verify() == proof
        assert b'"fixture"' in raw
        stream(b'data: [DONE]\r\n\r\n')

    with CodingModelListener(('127.0.0.1', 0), dispatch) as listener:
        credential = OpenCodeModelCredential(_CREDENTIAL, listener.endpoint, 'e' * 64)
        route = listener.attach(launch, credential, connect, database)
        submitted = Event()
        with ThreadPoolExecutor(max_workers=1) as browser:
            replies = []

            def early_open_code(scope):
                with database.transaction() as connection:
                    row = connection.execute('SELECT model_window FROM code_sessions').fetchone()
                    assert strict_json_object(row[0])['state'] == 'QUEUED'
                record = flow._initial_binding(
                    scope, _NATIVE, _MESSAGE, 'd' * 64, credential.reference
                )
                route.queue(scope, record)
                replies.append(
                    browser.submit(_exchange, listener.endpoint, credential.route, sent=submitted)
                )
                assert submitted.wait(3)
                assert not replies[0].done()
                assert not references

            driver.on_send = early_open_code
            assert flow.advance_start_session(runtime, parent, **options)
            response = replies[0].result(timeout=6)
            assert response.startswith(b'HTTP/1.1 200 OK') and b'data: [DONE]' in response
            assert len(references) == 1
            assert len(verified_connections) == 2
            assert verified_connections[0] == verified_connections[1]
        assert b'WALLE_PROTOCOL' in _exchange(
            listener.endpoint, credential.route, extras=['Content-Length: 1']
        )
        assert b'WALLE_SOURCE' in _exchange(listener.endpoint, credential.route, secret='bad')
        assert b'WALLE_SOURCE' in _exchange(
            listener.endpoint, credential.route, extras=['Origin: http://127.0.0.1']
        )
        assert stop(client, task_id, 4).status_code == 202
        assert b'WALLE_HOLD' in _exchange(listener.endpoint, credential.route)
        assert len(references) == 1
        route.revoke()
        assert b'WALLE_SOURCE' in _exchange(listener.endpoint, credential.route)
