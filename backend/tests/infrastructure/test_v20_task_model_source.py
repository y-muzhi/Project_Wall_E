"""Actual TCP owners and fail-closed model preflight without a supplier."""

import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from backend.app.code_tasks.task_model_ingress import ModelWindow, TaskModelIngress
from backend.app.code_tasks.task_runtime_launch import RuntimeTaskLaunch
from backend.app.infrastructure.guard_task_model_source import (
    AcceptedModelConnection,
    check_model_source_result,
    decode_model_source_request,
    verify_model_source,
)
from backend.app.infrastructure.opencode_model_credential import OpenCodeModelCredential
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.infrastructure.windows_task_endpoints import verify_task_model_connection


@contextmanager
def _accepted():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(8)
        code = (
            'import socket,sys; '
            's=socket.create_connection(("127.0.0.1",int(sys.argv[1])),8); '
            's.settimeout(15); s.recv(1); s.close()'
        )
        with subprocess.Popen(
            [sys._base_executable, '-I', '-B', '-c', code, str(listener.getsockname()[1])],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as child:
            try:
                accepted, _ = listener.accept()
                with (
                    accepted,
                    ObservedProcess(child.pid) as root,
                    ObservedProcess(os.getpid()) as backend,
                ):
                    yield accepted, root.identity, backend.identity
            finally:
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=4)


def _request(connection):
    return SimpleNamespace(
        action='VERIFY_MODEL_SOURCE',
        scope=LaunchScope('a' * 64, 3, 4, 'original-model-source'),
        binding_ref='b' * 32,
        recovery=None,
        input=connection.wire(),
    )


def test_actual_tcp_table_checks_both_owners_and_exact_connection():
    with _accepted() as (accepted, root, backend):
        source = AcceptedModelConnection.from_accept(accepted)
        verify_task_model_connection(
            source.client,
            source.server,
            root_pid=root.pid,
            backend_pid=backend.pid,
        )
        with pytest.raises(TaskExecutionError, match='MODEL_CONNECTION_OWNER_UNVERIFIED'):
            verify_task_model_connection(
                source.client,
                source.server,
                root_pid=backend.pid,
                backend_pid=root.pid,
            )
        with pytest.raises(TaskExecutionError):
            verify_task_model_connection(
                source.client,
                source.server,
                root_pid=root.pid,
                backend_pid=root.pid,
            )


def test_guard_requires_fixed_listener_root_and_correlated_evidence():
    with _accepted() as (accepted, root, backend):
        source = AcceptedModelConnection.from_accept(accepted)
        request = _request(source)
        assert decode_model_source_request(request) == source
        seen = []
        roots = [(root, 'c' * 32), (root, 'c' * 32)]

        def observe(checkpoint):
            checkpoint()
            return roots.pop(0)

        execution = SimpleNamespace(
            _native=SimpleNamespace(verify_model_root=observe),
            _network=SimpleNamespace(model_listener=source.server),
        )
        result = verify_model_source(request, execution, backend, lambda: seen.append('check'))
        assert seen == ['check', 'check']
        assert result.data['resource_ref'] == 'c' * 32
        check_model_source_result(request, result.data)
        with pytest.raises(TaskExecutionError, match='EVIDENCE_DIFFERS'):
            check_model_source_result(request, {**result.data, 'connection_sha256': '0' * 64})
        execution._network.model_listener = source.client
        with pytest.raises(TaskExecutionError, match='LISTENER_DIFFERS'):
            verify_model_source(request, execution, backend, lambda: None)
        request.input['address_family'] = 'IPv6'
        with pytest.raises(TaskExecutionError, match='CONNECTION_DIFFERS'):
            decode_model_source_request(request)


def test_model_preflight_requires_native_window_and_rechecks_after_guard(monkeypatch):
    window = ModelWindow(1, 2, 3, 4, 'ses_original', 5, 'msg_initial')
    actual = [window]
    sent = []
    launch = object.__new__(RuntimeTaskLaunch)

    def verify(accepted, **options):
        sent.append(AcceptedModelConnection.from_accept(accepted))
        return {'source_evidence_ref': 'a' * 64, 'connection_sha256': 'b' * 64}

    monkeypatch.setattr(launch, 'verify_model_source', verify)
    credential = OpenCodeModelCredential('d' * 32, ('127.0.0.1', 1), 'e' * 64)
    ingress = TaskModelIngress(
        launch,
        window,
        lambda expected, reference: actual[0],
        credential,
        verify_source=lambda *args, **options: launch.verify_model_source(*args, **options),
    )
    headers = [
        ('Authorization', 'Bearer ' + 'e' * 64),
        ('Content-Type', 'application/json'),
        ('Accept', 'text/event-stream'),
        ('X-Opencode-Session-Id', window.native_session_id),
    ]
    with _accepted() as (accepted, _, _):

        def send(fields, method='POST'):
            return ingress.verify(
                accepted,
                method,
                ingress.route,
                'HTTP/1.1',
                fields,
                lambda: None,
                timeout_ms=1000,
                cancelled=lambda: False,
            )

        invalid = [
            [('Origin', 'http://127.0.0.1')],
            [('Authorization', 'Bearer duplicate')],
            [('X-Opencode-Parent-Session-Id', 'ses_parent')],
            [('X-Parent-Session-Id', 'ses_parent')],
        ]
        for added in invalid:
            with pytest.raises(TaskExecutionError):
                send(headers + added)
        with pytest.raises(TaskExecutionError):
            send(headers, 'GET')
        assert not sent
        assert send(headers).window == window

        def close_window(accepted, **options):
            proof = verify(accepted, **options)
            actual[0] = None
            return proof

        monkeypatch.setattr(launch, 'verify_model_source', close_window)
        with pytest.raises(TaskExecutionError, match='WINDOW_FENCED'):
            send(headers)
        assert len(sent) == 2
        ingress.revoke()
        with pytest.raises(TaskExecutionError, match='CREDENTIAL_UNVERIFIED'):
            send(headers)


def test_backend_source_requires_matching_durable_create_resume_and_no_stop(monkeypatch):
    launch = object.__new__(RuntimeTaskLaunch)
    original = {
        'resource_ref': 'c' * 32,
        'job_ref': 'b' * 32,
        'receipt_sha256': 'd' * 64,
        'process_identity': {'pid': 71},
    }
    running = {**original, 'process_state': 'RUNNING'}
    acknowledgements = {
        'CREATE_SUSPENDED': {'native': {**original, 'process_state': 'SUSPENDED'}},
        'RESUME': {'native': running},
    }
    stopped = []
    launch._reference = 'b' * 32
    launch._evidence = SimpleNamespace(
        read_ack=acknowledgements.get,
        _known_intent=lambda action: stopped or None,
    )
    monkeypatch.setattr(launch, '_request', lambda action, data, binding: (action, data, binding))

    def exchange(request, **options):
        assert request == ('VERIFY_MODEL_SOURCE', source.wire(), launch._reference)
        return SimpleNamespace(status='MODEL_SOURCE', result={'resource_ref': 'c' * 32})

    monkeypatch.setattr(launch, '_exchange', exchange)
    with _accepted() as (accepted, _, _):
        source = AcceptedModelConnection.from_accept(accepted)
        assert launch.running_receipt() == running
        assert launch.verify_model_source(accepted, timeout_ms=1000, cancelled=lambda: False)
        running['process_identity'] = {'pid': 72}
        with pytest.raises(TaskExecutionError, match='RUNNING_RECEIPT_DIFFERS'):
            launch.running_receipt()
        running['process_identity'] = original['process_identity']
        stopped.append('stop intent')
        with pytest.raises(TaskExecutionError, match='RUNNING_RECEIPT_REQUIRED'):
            launch.verify_model_source(accepted, timeout_ms=1000, cancelled=lambda: False)
