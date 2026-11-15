import os
import subprocess
import sys
from time import monotonic

import pytest

from backend.app.infrastructure.check_case_pack import CaseAssertion, CaseStep, CheckCase
from backend.app.infrastructure.owned_check_http import (
    OwnedHttpEndpoint,
    OwnedHttpUnavailable,
    OwnedHttpUnknown,
    run_owned_http_case,
)
from backend.app.infrastructure.windows_process import ObservedProcess

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='real Windows TCP ownership')

_SERVER = r"""
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_POST(self):
        data = self.rfile.read(int(self.headers['Content-Length']))
        print(self.path, data.decode('ascii'), flush=True)
        if self.path == '/broken':
            self.send_response(200)
            self.send_header('Content-Length', '100')
            self.end_headers()
            self.wfile.write(b'truncated')
            self.close_connection = True
            return
        self.send_response(302 if self.path == '/redirect' else 200)
        self.send_header('Location', 'http://127.0.0.1:8000/forbidden')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass

class PrivateServer(HTTPServer):
    allow_reuse_address = False
    allow_reuse_port = False

with PrivateServer(('127.0.0.1', 0), Handler) as server:
    print(server.server_port, flush=True)
    server.serve_forever()
"""


@pytest.fixture
def original_http_process():
    process = subprocess.Popen(
        [sys._base_executable, '-I', '-B', '-c', _SERVER],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
        text=True,
    )
    try:
        endpoint = OwnedHttpEndpoint('product', int(process.stdout.readline()))
        with ObservedProcess(process.pid) as owned:
            yield process, endpoint, owned.identity
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdout.close()


def _case(*paths):
    steps = tuple(
        CaseStep(f'step{index}', 'REQUEST', ('product', path, 'POST', (), b'private'))
        for index, path in enumerate(paths)
    )
    assertions = tuple(
        CaseAssertion(step.step_id + '-status', 'STATUS', (step.step_id, expected))
        for step, expected in zip(steps, (302, 200), strict=False)
    )
    return CheckCase('original', 'Original', (), steps, assertions, 4)


def _run(case, endpoint, identity, actions, *, job=None, output=128):
    return run_owned_http_case(
        case,
        endpoint,
        identity,
        output_limit=output,
        request_limit=128,
        deadline=monotonic() + 4,
        active=lambda: None,
        verify_job=job if job is not None else lambda: actions.append('job'),
        before_send=lambda step, digest: actions.append(step),
    )


def test_owned_http_binds_each_connection_and_never_follows_redirect(original_http_process):
    process, endpoint, identity = original_http_process
    actions = []
    result = _run(_case('/redirect', '/second'), endpoint, identity, actions)
    assert result['result'] == 'PASSED'
    assert actions == ['job', 'step0', 'job', 'step1']
    assert process.stdout.readline().strip() == '/redirect private'
    assert process.stdout.readline().strip() == '/second private'


def test_owned_http_rejects_foreign_listener_and_unproved_job_before_bytes(original_http_process):
    _, endpoint, identity = original_http_process
    actions = []

    def reject():
        raise RuntimeError('test guard observes a different original Job')

    with ObservedProcess(os.getpid()) as foreign, pytest.raises(OwnedHttpUnavailable):
        _run(_case('/wrong'), endpoint, foreign.identity, actions)
    with pytest.raises(OwnedHttpUnavailable):
        _run(_case('/wrong'), endpoint, identity, actions, job=reject)
    assert actions == []


def test_owned_http_truncated_response_after_send_is_unknown(original_http_process):
    process, endpoint, identity = original_http_process
    actions = []
    with pytest.raises(OwnedHttpUnknown):
        _run(_case('/broken', '/never'), endpoint, identity, actions)
    assert actions == ['job', 'step0']
    assert process.stdout.readline().strip() == '/broken private'
