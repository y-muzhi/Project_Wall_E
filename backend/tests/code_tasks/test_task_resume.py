"""Isolated original Coding model resumes, original receipts and dispatch fences."""

from datetime import datetime, timedelta
from contextlib import contextmanager
import socket
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_resume, task_resume_runtime, task_runtime_stop
from backend.app.code_tasks.coding_model_listener import CodingModelListener
from backend.app.code_tasks.coding_model_wait import hold_coding_model
from backend.app.code_tasks.task_instance_driver import TaskInstanceDriver
from backend.app.code_tasks.task_model_ingress import TaskModelIngress, read_original_window_state
from backend.app.code_tasks.task_runtime_launch import RuntimeTaskLaunch
from backend.app.infrastructure.guard_task_model_source import AcceptedModelConnection
from backend.app.infrastructure.opencode_model_credential import OpenCodeModelCredential
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.command_execution import operation_time
from backend.tests.code_tasks.test_coding_model_gateway import fixed_price, opened
from backend.tests.code_tasks.test_task_start import isolated_readiness, original_operation, stop
from backend.tests.code_tasks.test_task_start_instance import original_instance
from backend.tests.code_tasks.test_task_start_session import _exchange, ready
from backend.tests.code_tasks.test_task_runtime_stop import StopDriver
from backend.tests.infrastructure.test_v20_command_http import package, service


class ContinuationDriver:
    def __init__(self, database, *, mode):
        self.database = database
        self.mode = mode
        self.sends = []
        self.reads = []

    def session_available(self, start_id):
        return start_id > 0

    def continuation_payload(self, scope, previous, credential_ref, checkpoint):
        checkpoint()
        if self.mode == 'busy':
            raise TaskExecutionError('ORIGINAL_TASK_CONTINUATION_ACTIVITY_UNVERIFIED')
        return {
            'messageID': 'msg_continued',
            'model': {'providerID': 'walle', 'modelID': 'walle-code'},
            'agent': 'coding',
            'parts': [{'id': 'prt_continued', 'type': 'text', 'text': '继续原后端会话'}],
        }

    def dispatch_continuation(self, scope, previous, window, credential_ref, payload, checkpoint):
        checkpoint()
        with self.database.transaction() as connection:
            assert read_original_window_state(connection, previous, credential_ref) is None
            assert read_original_window_state(connection, window, credential_ref) == 'QUEUED'
        self.sends.append(window)
        if self.mode == 'lost':
            raise TaskExecutionError('ORIGINAL_OPENCODE_RESPONSE_UNVERIFIED')

    def observe_continuation(self, scope, window, credential_ref, payload, checkpoint):
        checkpoint()
        self.reads.append(window)
        if self.mode == 'lost':
            raise TaskExecutionError('ORIGINAL_OPENCODE_RESPONSE_UNVERIFIED')
        return payload['messageID']


@pytest.fixture
def waiting(opened, monkeypatch):
    db, runtime, client, proof, credential, admission = opened
    original = task_resume.accept_resume

    monkeypatch.setattr(
        task_resume,
        'accept_resume',
        lambda runtime, request, *, available, delivery_epoch=None, cleanup_available=False: (
            original(
                runtime,
                request,
                available=True,
                delivery_epoch=delivery_epoch,
                cleanup_available=cleanup_available,
            )
        ),
    )
    window = proof.window
    with db.transaction(write=True) as connection:
        hold_coding_model(connection, window, credential, kind='BUDGET')
    view_path = f'/api/v1/code-tasks/{window.task_id}'
    response = client.get(view_path)
    assert response.status_code == 200, response.text
    task = response.json()['data']
    data = {
        'expected_state_version': task['state_version'],
        'operation_id': window.operation_id,
        'waiting_item_ids': [item['id'] for item in task['waiting_items']],
    }
    return (
        db,
        runtime,
        client,
        window,
        credential,
        {admission.evidence_ref: admission},
        view_path,
        data,
    )


def _post(client, path, data, key=None):
    return client.post(
        path + '/resume', json=data, headers={'Idempotency-Key': key or str(uuid4())}
    )


@pytest.mark.parametrize('mode', ['success', 'lost', 'busy', 'stop-before-dispatch'])
def test_original_model_resume(waiting, monkeypatch, mode):
    db, runtime, client, previous, credential, admissions, path, data = waiting
    key = str(uuid4())
    assert (
        _post(client, path, {**data, 'waiting_item_ids': []}).json()['error']['code']
        == 'OPERATION_CONFLICT'
    )
    assert (
        _post(client, path, {**data, 'waiting_item_ids': data['waiting_item_ids'] * 2}).status_code
        == 422
    )
    assert (
        _post(client, path, {**data, 'operation_id': previous.operation_id + 100}).status_code
        == 409
    )
    assert _post(client, path, {**data, 'repository_quiescent_confirmed': True}).status_code == 422
    response = _post(client, path, data, key)
    assert response.status_code == 202, response.text
    accepted = response.json()['data']
    identity = accepted['operation_id']
    assert accepted['task_status'] == 'WAITING' and identity != previous.operation_id
    assert _post(client, path, data, key).json()['data'] == accepted
    current = client.get(path).json()['data']
    assert current['active_operations'] == [
        {'id': identity, 'operation_type': 'RESUME', 'status': 'PENDING'}
    ]
    assert original_operation(client, identity)['status'] == 'PENDING'
    scoped = client.get(f'{path}/operations/{identity}')
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()['data'] == original_operation(client, identity)
    page = client.get(f'{path}/operations')
    assert page.status_code == 200, page.text
    assert page.json()['meta']['pagination'] == {
        'page': 1,
        'page_size': 20,
        'total': 2,
        'total_pages': 1,
    }
    assert [row['id'] for row in page.json()['data']['items']] == [identity, previous.operation_id]
    past = client.get(f'{path}/operations', params={'page': 2}).json()
    assert past['data']['items'] == [] and past['meta']['pagination']['total'] == 2
    assert client.get(f'{path}/operations', params={'page': 100001}).status_code == 422
    assert client.get(f'{path}/operations/{identity}', params={'page': 1}).status_code == 422
    assert (
        client.get(f'/api/v1/code-tasks/{previous.task_id + 100}/operations/{identity}').status_code
        == 404
    )
    assert client.get(f'{path}/operations/{identity + 100}').status_code == 404
    assert (
        client.get(f'{path}/operations/{identity}', headers={'Idempotency-Key': key}).status_code
        == 422
    )
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': path + '/resume',
            'request_key': key,
        },
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()['data']['original_outcome']['data'] == accepted
    assert (
        _post(client, path, {**data, 'expected_state_version': current['state_version']}).json()[
            'error'
        ]['code']
        == 'OPERATION_IN_PROGRESS'
    )
    driver = ContinuationDriver(db, mode=mode)
    if mode == 'stop-before-dispatch':
        assert stop(client, previous.task_id, current['state_version']).status_code == 202
        assert not task_resume_runtime.advance_model_resumes(
            runtime, driver, admissions, cancelled=lambda: False
        )
        assert not driver.sends and not driver.reads
        with db.transaction() as connection:
            assert read_original_window_state(connection, previous, credential) is None
        return
    assert task_resume_runtime.advance_model_resumes(
        runtime, driver, admissions, cancelled=lambda: False
    )
    operation = original_operation(client, identity)
    if mode == 'busy':
        assert (
            operation['status'] == 'FAILED' and operation['failure_code'] == 'EXECUTION_NOT_STOPPED'
        )
        assert not driver.sends and not driver.reads
        with db.transaction() as connection:
            assert read_original_window_state(connection, previous, credential) == 'HELD'
        assert client.get(path).json()['data']['status'] == 'WAITING'
        return
    if mode == 'lost':
        assert operation['status'] == 'UNKNOWN'
        assert client.get(path).json()['data']['status'] == 'WAITING'
        assert not task_resume_runtime.advance_model_resumes(
            runtime, driver, admissions, cancelled=lambda: False
        )
        later = datetime.fromisoformat(operation_time(None)) + timedelta(seconds=4)
        monkeypatch.setattr(
            task_resume_runtime,
            'operation_time',
            lambda _: later.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
        )
        driver.mode = 'success'
        assert task_resume_runtime.advance_model_resumes(
            runtime, driver, admissions, cancelled=lambda: False
        )
        assert len(driver.reads) == 2
        operation = original_operation(client, identity)
    assert operation['status'] == 'SUCCEEDED'
    assert len(driver.sends) == 1
    assert operation['steps'][2]['external_identity'] == {}
    assert 'msg_continued' not in str(operation)
    task = client.get(path).json()['data']
    assert (
        task['status'] == 'RUNNING' and not task['waiting_items'] and not task['active_operations']
    )
    assert task['active_session_id'] == previous.execution_session_id
    assert _post(client, path, data, key).json()['data'] == accepted
    with db.transaction() as connection:
        assert read_original_window_state(connection, previous, credential) is None
        assert read_original_window_state(connection, driver.sends[0], credential) == 'OPEN'
        assert (
            connection.execute('SELECT native_message_id FROM code_sessions').fetchone()[0]
            == previous.trigger_message_id
        )
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def test_old_accepted_socket_cannot_cross_continuation_window(waiting, monkeypatch):
    db, runtime, client, previous, credential, admissions, path, data = waiting
    accepted = _post(client, path, data)
    assert accepted.status_code == 202, accepted.text
    prior_accept = Event()
    launch = object.__new__(RuntimeTaskLaunch)
    launch._original = SimpleNamespace(scope=SimpleNamespace(operation_id=previous.operation_id))
    proofs = []

    @contextmanager
    def connect():
        yield 'original-frame'

    def verify_source(accepted, *, timeout_ms, cancelled, frames):
        assert not cancelled() and frames == 'original-frame'
        assert AcceptedModelConnection.from_accept(accepted).server == listener.endpoint
        return {'source_evidence_ref': 'a' * 64, 'connection_sha256': 'b' * 64}

    monkeypatch.setattr(launch, 'verify_model_source', verify_source)

    def dispatch(reference, proof, raw, verify, stream, cancelled, *, instance_secret):
        proofs.append(proof.window)
        stream(b'data: [DONE]\r\n\r\n')

    with CodingModelListener(('127.0.0.1', 0), dispatch) as listener:
        admitted = OpenCodeModelCredential(credential, listener.endpoint, 'e' * 64)
        route = listener.attach(launch, admitted, connect, db)
        route._window = previous
        route._ingress = TaskModelIngress(
            launch, previous, route._read, admitted, verify_source=route._verify
        )
        handle = listener._serve

        def observed(connection, windows):
            prior_accept.set()
            return handle(connection, windows)

        monkeypatch.setattr(listener, '_serve', observed)
        driver = ContinuationDriver(db, mode='success')
        original = driver.dispatch_continuation

        def send(scope, old, new, reference, payload, checkpoint):
            route.queue_continuation(old, new)
            original(scope, old, new, reference, payload, checkpoint)

        monkeypatch.setattr(driver, 'dispatch_continuation', send)
        with socket.create_connection(listener.endpoint, timeout=5) as stale:
            assert prior_accept.wait(3)
            assert task_resume_runtime.advance_model_resumes(
                runtime, driver, admissions, cancelled=lambda: False
            )
            endpoint = f'{listener.endpoint[0]}:{listener.endpoint[1]}'
            stale.sendall(
                (
                    'POST '
                    + admitted.route
                    + ' HTTP/1.1\r\nHost: '
                    + endpoint
                    + '\r\nContent-Type: application/json\r\nAccept: text/event-stream\r\nContent-Length: 2'
                    + '\r\nAuthorization: Bearer '
                    + ('e' * 64)
                    + '\r\nx-opencode-session-id: ses_original\r\n\r\n{}'
                ).encode()
            )
            result = bytearray()
            while chunk := stale.recv(8192):
                result.extend(chunk)
            assert b'WALLE_HOLD' in result and not proofs
        assert b'data: [DONE]' in _exchange(listener.endpoint, admitted.route)
        assert proofs == driver.sends


def test_owned_stop_retires_runtime_but_preserves_unknown_resume(waiting, ready, monkeypatch):
    db, runtime, client, previous, credential, admissions, path, data = waiting
    response = _post(client, path, data)
    assert response.status_code == 202, response.text
    resumed = response.json()['data']
    driver = ContinuationDriver(db, mode='lost')
    assert task_resume_runtime.advance_model_resumes(
        runtime, driver, admissions, cancelled=lambda: False
    )
    assert original_operation(client, resumed['operation_id'])['status'] == 'UNKNOWN'
    stopped = stop(client, previous.task_id, resumed['state_version'])
    assert stopped.status_code == 202, stopped.text
    native = StopDriver(ready[3])
    clock = datetime.fromisoformat(operation_time(None)) + timedelta(seconds=3)
    monkeypatch.setattr(
        task_runtime_stop,
        'operation_time',
        lambda _: clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
    )
    for index in range(6):
        if index == 3:
            clock += timedelta(days=1)
        assert task_runtime_stop.advance_owned_stops(runtime, native, cancelled=lambda: False)
    assert client.get(path).json()['data']['status'] == 'TERMINATED'
    assert original_operation(client, resumed['operation_id'])['status'] == 'UNKNOWN'
    assert not task_resume_runtime.advance_model_resumes(
        runtime, driver, admissions, cancelled=lambda: False
    )
    assert len(driver.sends) == 1


def test_resume_rechecks_budget_before_registering_native_dispatch(waiting):
    db, runtime, client, previous, credential, admissions, path, data = waiting
    with db.transaction(write=True) as connection:
        connection.execute(
            "UPDATE code_tasks SET budget_limit_cny='0.000001' WHERE id=?", (previous.task_id,)
        )
    response = _post(client, path, data)
    assert response.status_code == 202, response.text
    identity = response.json()['data']['operation_id']
    driver = ContinuationDriver(db, mode='success')
    assert task_resume_runtime.advance_model_resumes(
        runtime, driver, admissions, cancelled=lambda: False
    )
    result = original_operation(client, identity)
    assert result['status'] == 'FAILED' and result['failure_code'] == 'CONFIG_NOT_READY'
    assert [step['status'] for step in result['steps']] == ['SUCCEEDED', 'FAILED', 'PENDING']
    assert not driver.sends and not driver.reads
    with db.transaction() as connection:
        assert read_original_window_state(connection, previous, credential) == 'HELD'
    assert client.get(path).json()['data']['status'] == 'WAITING'


@pytest.mark.parametrize('invalid', [None, 'extra_child', 'incomplete', 'closed', 'changed_owner'])
def test_continuation_guard_requires_original_running_root(invalid):
    scope = {'pid': 902, 'creation_time_hex': 'a' * 16}
    saved = {'receipt_sha256': 'a' * 64, 'process_identity': scope}
    observed = {
        'acknowledgement': {'native': saved},
        'fence': {'stop_closed': False},
        'resource': {**saved, 'process_state': 'RUNNING'},
        'job_activity': {'complete': True, 'assigned_count': 1, 'process_ids': [902]},
    }
    if invalid == 'extra_child':
        observed['job_activity'].update(assigned_count=2, process_ids=[902, 903])
    elif invalid == 'incomplete':
        observed['job_activity']['complete'] = False
    elif invalid == 'closed':
        observed['fence']['stop_closed'] = True
    elif invalid == 'changed_owner':
        observed['resource']['process_identity'] = {'pid': 902, 'creation_time_hex': 'b' * 16}
    calls = []

    @contextmanager
    def connect():
        yield 'original-control'

    def observe(action, *, timeout_ms, cancelled):
        assert action == 'RESUME' and timeout_ms == 100 and not cancelled()
        return observed

    launch = SimpleNamespace(reconnect=calls.append, observe=observe, running_receipt=lambda: saved)
    driver = object.__new__(TaskInstanceDriver)
    driver._connect = connect
    owner = SimpleNamespace(launch=launch)

    def checkpoint():
        calls.append('checkpoint')

    if invalid is None:
        driver._continuation_guard(owner, checkpoint, 100)
    else:
        with pytest.raises(TaskExecutionError, match='ACTIVITY_UNVERIFIED'):
            driver._continuation_guard(owner, checkpoint, 100)
    assert calls == ['checkpoint', 'original-control', 'checkpoint']
