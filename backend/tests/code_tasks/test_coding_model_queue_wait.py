"""Real local sockets expire the original QUEUED entry without supplier dispatch."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest

from backend.app.code_tasks import task_start_session as flow
from backend.app.code_tasks.coding_model_listener import CodingModelListener
from backend.app.code_tasks.task_runtime_launch import RuntimeTaskLaunch
from backend.app.infrastructure.guard_task_model_source import AcceptedModelConnection
from backend.app.infrastructure.opencode_model_credential import OpenCodeModelCredential
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_authorizations as grants
from backend.tests.code_tasks import test_execution_profile_versions as versions
from backend.tests.code_tasks.test_task_start import isolated_readiness  # noqa: F401
from backend.tests.code_tasks.test_task_start_instance import original_instance  # noqa: F401
from backend.tests.code_tasks.test_task_start_session import (
    NativeDriver,
    _exchange,
    ready,  # noqa: F401
)
from backend.tests.infrastructure.test_v20_command_http import package, service  # noqa: F401


@pytest.fixture
def bounded_queue_profile(request, monkeypatch):
    original = versions.body

    def profile():
        content = original()
        content['limits']['queue_wait_seconds'] = request.param
        return content

    def grant_profile():
        content = original()
        content['limits']['queue_wait_seconds'] = 1
        return content

    # Prepare both immutable inputs before the original task/grant is created.
    monkeypatch.setattr(versions, 'body', profile)
    monkeypatch.setattr(grants, 'body', grant_profile)


@pytest.fixture
def queued_task(bounded_queue_profile, ready):  # noqa: F811
    return ready


@pytest.mark.parametrize('bounded_queue_profile', [1, 3], indirect=True)
def test_original_queue_expiry_uses_narrower_current_limit_and_never_dispatches(
    queued_task, monkeypatch
):
    database, runtime, _client, parent, _task_id, _, receipt = queued_task
    driver = NativeDriver()
    options = {'cancelled': lambda: False, 'driver': driver}
    assert flow.advance_start_session(runtime, parent, **options)
    scope = driver.calls[0][1]
    launch = object.__new__(RuntimeTaskLaunch)
    launch._original = SimpleNamespace(
        scope=SimpleNamespace(operation_id=receipt['operation_id'], nonce=scope.nonce)
    )
    dispatched, verified = [], []

    @contextmanager
    def connect():
        yield 'owned-queue-frame'

    def verify_source(accepted, *, timeout_ms, cancelled, frames):
        assert frames == 'owned-queue-frame' and not cancelled()
        assert AcceptedModelConnection.from_accept(accepted).server == listener.endpoint
        verified.append(accepted)
        return {'source_evidence_ref': 'a' * 64, 'connection_sha256': 'b' * 64}

    monkeypatch.setattr(launch, 'verify_model_source', verify_source)

    def dispatch(reference, proof, raw, verify, stream, cancelled, *, instance_secret):
        dispatched.append(proof.window)
        assert verify() == proof and not cancelled()
        stream(b'data: [DONE]\r\n\r\n')

    with CodingModelListener(('127.0.0.1', 0), dispatch) as listener:
        credential = OpenCodeModelCredential(driver.credential, listener.endpoint, 'e' * 64)
        route = listener.attach(launch, credential, connect, database)
        submitted = Event()
        with ThreadPoolExecutor(max_workers=1) as requests:
            responses = []

            def original_send(scope):
                original = flow._initial_binding(
                    scope, 'ses_original', 'msg_original', 'd' * 64, credential.reference
                )
                route.queue(scope, original)
                assert route._queue_wait_seconds(route._window) == 1
                pending = requests.submit(
                    _exchange, listener.endpoint, credential.route, sent=submitted
                )
                assert submitted.wait(3)
                response = pending.result(timeout=5)
                assert response.startswith(b'HTTP/1.1 409 Conflict')
                assert b'WALLE_HOLD' in response
                responses.append(response)
                assert not dispatched and not verified
                with database.transaction() as connection:
                    session = connection.execute(
                        'SELECT model_window FROM code_sessions'
                    ).fetchone()
                    assert strict_json_object(session[0])['state'] == 'QUEUED'
                    assert connection.execute('SELECT COUNT(*) FROM llm_uses').fetchone()[0] == 0

            driver.on_send = original_send
            assert flow.advance_start_session(runtime, parent, **options)
            assert len(responses) == 1 and not dispatched and not verified
        # The expired socket does not resume itself when the original message
        # becomes OPEN. A separate explicit local request still uses that window.
        assert b'data: [DONE]' in _exchange(listener.endpoint, credential.route)
        assert len(dispatched) == 1 and len(verified) == 2
