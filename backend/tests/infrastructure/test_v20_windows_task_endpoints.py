"""Real Windows TCP table and exclusive socket probes for original TASK endpoints."""

import os
import socket
from base64 import b64encode
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from backend.app.infrastructure.opencode_binary import VERSION
from backend.app.infrastructure.opencode_control import OpenCodeControlCredential
from backend.app.infrastructure.opencode_runtime_bundle import REF_PREFIX
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError, TaskExecutionPlan
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.infrastructure.windows_task_endpoints import observe_task_endpoints
from backend.tests.infrastructure.test_v20_windows_controller_token import (
    controller,
    ordinary_controller,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


@contextmanager
def listening(address='127.0.0.1'):
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if family == socket.AF_INET6:
            server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        server.bind((address, 0))
        server.listen()
        yield server.getsockname()[1]


def _plan(model, control, forward=None):
    return TaskExecutionPlan.parse(
        {
            'binary_ref': 'fixture',
            'version': VERSION,
            'active_process_limit': 2,
            'job_memory_limit_bytes': 1024 * 1024,
        },
        {
            'model': [{'address': '127.0.0.1', 'port': model}],
            'control': [{'address': '127.0.0.1', 'port': control}],
            'forward': [] if forward is None else [{'address': '::1', 'port': forward}],
            'application': [],
        },
        REF_PREFIX + 'a' * 64,
    )


def test_original_listeners_are_verified_for_both_loopback_families(ordinary_controller):
    other, _ = ordinary_controller
    with listening() as control:
        pass
    with listening() as model, listening('::1') as forward, ObservedProcess(os.getpid()) as process:
        plan = _plan(model, control, forward)
        first = observe_task_endpoints(plan, process, process.identity, lambda: None)
        assert first == observe_task_endpoints(plan, process, process.identity, lambda: None)
        with pytest.raises(TaskExecutionError, match='LISTENER_OWNER_UNVERIFIED'):
            observe_task_endpoints(plan, other, other.identity, lambda: None)
    with ObservedProcess(os.getpid()) as process:
        with pytest.raises(TaskExecutionError, match='LISTENER_OWNER_UNVERIFIED'):
            observe_task_endpoints(plan, process, process.identity, lambda: None)


def test_wildcard_model_listener_and_occupied_control_port_are_rejected():
    with (
        listening('0.0.0.0') as wildcard,
        listening() as control,
        ObservedProcess(os.getpid()) as process,
    ):
        with pytest.raises(TaskExecutionError, match='LISTENER_OWNER_UNVERIFIED'):
            observe_task_endpoints(
                _plan(wildcard, control), process, process.identity, lambda: None
            )
        with listening() as model:
            with pytest.raises(TaskExecutionError, match='PORT_UNAVAILABLE'):
                observe_task_endpoints(
                    _plan(model, control), process, process.identity, lambda: None
                )


def test_basic_probe_sends_only_to_original_established_connection(ordinary_controller):
    other, _ = ordinary_controller
    requests = []

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get('Authorization')))
            body = ('{"healthy":true,"version":"' + VERSION + '"}').encode()
            self.send_response(200 if requests[-1] == ('/global/health', authorization) else 401)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with HTTPServer(('127.0.0.1', 0), Health) as server, ObservedProcess(os.getpid()) as process:
        port = server.server_port
        plan = _plan(1 if port != 1 else 2, port)
        scope = LaunchScope('a' * 64, 3, 4, 'original-task-control-test')
        credential = OpenCodeControlCredential.issue(scope, plan)
        env = credential.launch_variables(scope, plan)
        authorization = (
            'Basic '
            + b64encode(
                (env['OPENCODE_SERVER_USERNAME'] + ':' + env['OPENCODE_SERVER_PASSWORD']).encode()
            ).decode()
        )
        assert env['OPENCODE_SERVER_PASSWORD'] not in repr(credential)
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            with pytest.raises(TaskExecutionError, match='CONNECTION_OWNER_UNVERIFIED'):
                credential.probe_health(other, other.identity, lambda: None, timeout_ms=4000)
            assert not requests
            assert (
                credential.probe_health(process, process.identity, lambda: None, timeout_ms=4000)
                == VERSION
            )
            assert requests == [('/global/health', authorization)]
            credential.close()
            with pytest.raises(TaskExecutionError, match='CREDENTIAL_UNVERIFIED'):
                credential.probe_health(process, process.identity, lambda: None, timeout_ms=4000)
        finally:
            server.shutdown()
            thread.join(4)
        assert not thread.is_alive()
