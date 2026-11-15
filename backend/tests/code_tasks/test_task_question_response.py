"""Original question reply on the isolated HTTP, SQLite and native boundary."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_question_response as responses
from backend.app.code_tasks import task_runtime_stop
from backend.app.code_tasks.coding_model_listener import CodingModelListener
from backend.app.code_tasks.task_model_ingress import TaskModelIngress, read_original_window_state
from backend.app.code_tasks.task_native_issues import advance_native_issue_observation
from backend.app.code_tasks.task_question_answers import FACT_HEADER, USE_BASIS
from backend.app.code_tasks.task_runtime_launch import RuntimeTaskLaunch
from backend.app.infrastructure.guard_task_model_source import AcceptedModelConnection
from backend.app.infrastructure.opencode_model_credential import OpenCodeModelCredential
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.shared.command_execution import operation_time
from backend.tests.code_tasks import test_coding_model_gateway as model_fixtures
from backend.tests.code_tasks import test_task_start as start_fixtures
from backend.tests.code_tasks import test_task_start_instance as instance_fixtures
from backend.tests.code_tasks import test_task_start_session as session_fixtures
from backend.tests.code_tasks.test_coding_model_gateway import _build, _reply
from backend.tests.code_tasks.test_task_native_issues import OriginalIssueDriver
from backend.tests.code_tasks.test_task_runtime_stop import StopDriver
from backend.tests.code_tasks.test_task_start import original_operation, stop
from backend.tests.code_tasks.test_task_start_session import _exchange
from backend.tests.infrastructure import test_v20_command_http as http_fixtures

# Register the existing dependency fixtures under their original pytest names.
fixed_price = model_fixtures.fixed_price
opened = model_fixtures.opened
isolated_readiness = start_fixtures.isolated_readiness
original_instance = instance_fixtures.original_instance
ready = session_fixtures.ready
package = http_fixtures.package
service = http_fixtures.service


@pytest.fixture
def question(opened, monkeypatch):
    database, runtime, client, proof, credential, _ = opened
    window = proof.window
    observer = OriginalIssueDriver(window)
    observe = observer.observe_native_issues
    observer.observe_native_issues = lambda scope, native, checkpoint: (
        observe(scope, native, checkpoint)[0],
        (),
    )
    advance_native_issue_observation(runtime, observer, 0, cancelled=lambda: False)
    accept = responses.answer_question
    monkeypatch.setattr(
        responses, 'answer_question', lambda rt, rq, *, available: accept(rt, rq, available=True)
    )
    path = f'/api/v1/code-tasks/{window.task_id}'
    issue = client.get(path + '/questions').json()['data']['items'][0]
    return database, runtime, client, window, credential, path, issue


def body(window):
    return {
        'expected_state_version': 5,
        'session_id': window.execution_session_id,
        'answers': [
            {'index': 0, 'action': 'USE_FIXED_BASIS', 'basis_refs': [], 'clarification': None},
            {
                'index': 1,
                'action': 'CLARIFY_FACTS',
                'basis_refs': [],
                'clarification': {
                    'kind': 'OBSERVATION',
                    'text': '  第一行\r\n第二行  ',
                    'option_indices': [],
                    'evidence_refs': [],
                },
            },
        ],
    }


class ReplyDriver:
    def __init__(self, database, window, credential, mode):
        self.database, self.window, self.credential, self.mode = database, window, credential, mode
        self.sends = []

    def session_available(self, operation):
        return operation == self.window.operation_id

    def observe_native_issues(self, scope, native, checkpoint):
        questions, permissions = OriginalIssueDriver(self.window).observe_native_issues(
            scope, native, checkpoint
        )
        return (
            () if self.mode == 'missing' else questions,
            permissions if self.mode == 'other-wait' else (),
        )

    def send_question_response(self, scope, native, identity, answers, checkpoint):
        checkpoint()
        with self.database.transaction() as connection:
            assert read_original_window_state(connection, self.window, self.credential) == (
                None if self.mode == 'other-wait' else 'QUEUED'
            )
        self.sends.append((identity, answers))
        if self.mode == 'unknown':
            raise TaskExecutionError('ORIGINAL_QUESTION_ACK_UNKNOWN')
        return {'source': 'HTTP_200'}


@pytest.mark.parametrize('mode', ['success', 'unknown', 'missing', 'stop', 'other-wait'])
def test_original_question_dispatch_and_receipt(question, mode):
    database, runtime, client, window, credential, path, issue = question
    endpoint = f'{path}/questions/{issue["id"]}/responses'
    key = str(uuid4())

    def post(value, key=None):
        return client.post(endpoint, json=value, headers={'Idempotency-Key': key or str(uuid4())})

    fixed = body(window)
    assert post({**fixed, 'answers': fixed['answers'][:1]}).status_code == 422
    assert (
        post({**fixed, 'session_id': window.execution_session_id + 1}).json()['error']['code']
        == 'SESSION_NOT_CURRENT'
    )
    response = post(fixed, key)
    assert response.status_code == 202, response.text
    data = response.json()['data']
    identity = data['operation_id']
    assert data['state_version'] == 6 and data['task_status'] == 'WAITING'
    assert post(fixed, key).json()['data'] == data
    assert (
        post({**fixed, 'expected_state_version': 6}).json()['error']['code'] == 'OPERATION_CONFLICT'
    )
    assert client.get(path).json()['data']['active_operations'] == [
        {'id': identity, 'operation_type': 'ANSWER_QUESTION', 'status': 'PENDING'},
    ]
    assert client.get(path + '/questions').json()['data']['items'][0]['status'] == 'ANSWERING'
    original = original_operation(client, identity)
    assert original['status'] == 'PENDING' and 'native_answers' not in str(original)
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': endpoint,
            'request_key': key,
        },
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()['data']['operation_id'] == identity
    driver = ReplyDriver(database, window, credential, mode)
    if mode == 'stop':
        assert stop(client, window.task_id, 6).status_code == 202
        assert not responses.advance_question_responses(runtime, driver, cancelled=lambda: False)
        assert not driver.sends
        return
    assert responses.advance_question_responses(runtime, driver, cancelled=lambda: False)
    assert not responses.advance_question_responses(runtime, driver, cancelled=lambda: False)
    operation = original_operation(client, identity)
    observed = client.get(path + '/questions').json()['data']['items'][0]
    if mode == 'other-wait':
        assert (operation['status'], observed['status']) == ('SUCCEEDED', 'RESOLVED')
        current = client.get(path).json()['data']
        assert current['status'] == 'WAITING' and current['state_version'] == 8
        assert [item['kind'] for item in current['waiting_items']] == ['PERMISSION']
    elif mode == 'success':
        assert (operation['status'], observed['status']) == ('SUCCEEDED', 'RESOLVED')
        assert client.get(path).json()['data']['status'] == 'RUNNING'
        with database.transaction() as connection:
            assert read_original_window_state(connection, window, credential) == 'OPEN'
    elif mode == 'unknown':
        assert (operation['status'], observed['status']) == ('UNKNOWN', 'UNKNOWN')
        assert client.get(path).json()['data']['status'] == 'WAITING'
        with database.transaction() as connection:
            assert read_original_window_state(connection, window, credential) is None
    else:
        assert (operation['status'], observed['status']) == ('FAILED', 'UNKNOWN')
        assert not driver.sends
        return
    assert len(driver.sends) == 1
    native = driver.sends[0][1]
    assert native[0] == [USE_BASIS]
    assert native[1][0].startswith(FACT_HEADER + '\n现象\n  第一行\n第二行  ')
    assert post(fixed, key).json()['data'] == data


def test_question_citations_and_evidence_are_fixed_and_task_owned(question):
    database, runtime, client, window, credential, path, issue = question
    task = client.get(path).json()['data']
    endpoint = f'{path}/questions/{issue["id"]}/responses'

    def post(data):
        return client.post(endpoint, json=data, headers={'Idempotency-Key': str(uuid4())})

    fixed = body(window)
    first, second = fixed['answers']
    citation = {
        'document_id': task['document_id'],
        'revision_id': task['design_revision_id'],
        'quote': '原固定设计',
    }
    first.update(action='CITE_FIXED_BASIS', basis_refs=[{**citation, 'quote': '原文不存在'}])
    invalid = post(fixed)
    assert invalid.status_code == 422 and invalid.json()['error']['code'] == 'BASIS_REF_INVALID'
    first['basis_refs'] = [citation]
    second['clarification']['evidence_refs'] = [
        {'kind': 'OPERATION', 'id': window.operation_id + 1000}
    ]
    invalid = post(fixed)
    assert invalid.status_code == 422 and invalid.json()['error']['code'] == 'INVALID_INPUT'
    second['clarification']['evidence_refs'] = [{'kind': 'OPERATION', 'id': window.operation_id}]
    accepted = post(fixed)
    assert accepted.status_code == 202, accepted.text
    driver = ReplyDriver(database, window, credential, 'success')
    assert responses.advance_question_responses(runtime, driver, cancelled=lambda: False)
    answers = driver.sends[0][1]
    assert citation['quote'] in answers[0][0] and '固定依据' in answers[0][0]
    assert f'OPERATION #{window.operation_id} · SUCCEEDED' in answers[1][0]


@pytest.mark.parametrize('interruption', ['stop_before_send', 'worker_restart', 'stop_after_send'])
def test_original_question_send_intent_survives_worker_and_stop(
    question, ready, monkeypatch, interruption
):
    database, runtime, client, window, credential, path, issue = question
    accepted = client.post(
        f'{path}/questions/{issue["id"]}/responses',
        json=body(window),
        headers={'Idempotency-Key': str(uuid4())},
    )
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['data']['operation_id']
    sender = ReplyDriver(database, window, credential, 'success')

    def advance():
        return responses.advance_question_responses(runtime, sender, cancelled=lambda: False)

    dispatched = interruption != 'stop_before_send'
    if dispatched:

        def interrupted(*args):
            raise RuntimeError('Fixture interrupts before confirmation commit')

        with monkeypatch.context() as isolated:
            isolated.setattr(responses, '_complete', interrupted)
            with pytest.raises(RuntimeError, match='before confirmation commit'):
                advance()
        assert original_operation(client, identity)['status'] == 'RUNNING'
        assert len(sender.sends) == 1
    if interruption == 'worker_restart':
        assert advance()
        assert not advance()
        assert len(sender.sends) == 1
        assert original_operation(client, identity)['status'] == 'UNKNOWN'
        assert client.get(path + '/questions').json()['data']['items'][0]['status'] == 'UNKNOWN'
        return

    response = stop(client, window.task_id, 6)
    assert response.status_code == 202, response.text
    assert not advance()
    clock = datetime.fromisoformat(operation_time(None)) + timedelta(seconds=3)
    monkeypatch.setattr(
        task_runtime_stop,
        'operation_time',
        lambda _: clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
    )
    owner = StopDriver(ready[3])
    for index in range(6):
        if index == 3:
            clock += timedelta(days=1)
        assert task_runtime_stop.advance_owned_stops(runtime, owner, cancelled=lambda: False)
    assert len(sender.sends) == int(dispatched)
    assert original_operation(client, identity)['status'] == (
        'UNKNOWN' if dispatched else 'CANCELLED'
    )
    task = client.get(path).json()['data']
    assert task['status'] == 'TERMINATED' and task['waiting_items'] == []
    item = client.get(path + '/questions').json()['data']['items'][0]
    assert (
        item['status'] == ('UNKNOWN' if dispatched else 'OBSOLETE') and item['resolved_at'] is None
    )


@pytest.mark.parametrize('mode', ['success', 'unknown', 'other-wait'])
def test_actual_model_listener_waits_for_original_question_evidence(
    question, opened, monkeypatch, mode
):
    database, runtime, client, window, credential, path, issue = question
    admission = opened[-1]
    accepted = client.post(
        f'{path}/questions/{issue["id"]}/responses',
        json=body(window),
        headers={'Idempotency-Key': str(uuid4())},
    )
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['data']['operation_id']
    launch = object.__new__(RuntimeTaskLaunch)
    launch._original = SimpleNamespace(scope=SimpleNamespace(operation_id=window.operation_id))
    sent = []

    @contextmanager
    def connect():
        yield 'fixture-original-frame'

    def verify_source(accepted, *, timeout_ms, cancelled, frames):
        assert not cancelled() and frames == 'fixture-original-frame'
        assert AcceptedModelConnection.from_accept(accepted).server == listener.endpoint
        return {'source_evidence_ref': 'a' * 64, 'connection_sha256': 'b' * 64}

    def supplier(request):
        with database.transaction() as connection:
            status = connection.execute(
                'SELECT status FROM code_operations WHERE id=?', (identity,)
            ).fetchone()[0]
            assert status == 'SUCCEEDED'
        sent.append(request)
        return _reply(admission.model.model_name, 'complete')

    monkeypatch.setattr(launch, 'verify_model_source', verify_source)
    gateway = _build(runtime, admission, supplier)
    dispatching, observed_window, native_return = Event(), Event(), Event()
    sender = ReplyDriver(database, window, credential, mode)
    send = sender.send_question_response

    def awaiting_ack(*args):
        dispatching.set()
        assert native_return.wait(4)
        return send(*args)

    monkeypatch.setattr(sender, 'send_question_response', awaiting_ack)
    with CodingModelListener(('127.0.0.1', 0), gateway) as listener:
        admitted = OpenCodeModelCredential(credential, listener.endpoint, 'e' * 64)
        route = listener.attach(launch, admitted, connect, database)
        route._window = window
        route._ingress = TaskModelIngress(
            launch, window, route._read, admitted, verify_source=route._verify
        )
        read = route._read_state

        def observed(original):
            state = read(original)
            if not observed_window.is_set():
                assert state == (None if mode == 'other-wait' else 'QUEUED')
                observed_window.set()
            return state

        if mode != 'other-wait':
            monkeypatch.setattr(route, '_read_state', observed)
        with ThreadPoolExecutor(max_workers=2) as threads:
            pending = threads.submit(
                responses.advance_question_responses, runtime, sender, cancelled=lambda: False
            )
            try:
                assert dispatching.wait(3)
                model = threads.submit(_exchange, listener.endpoint, admitted.route)
                if mode == 'other-wait':
                    held = model.result(timeout=3)
                    assert b'WALLE_HOLD' in held
                    assert not pending.done()
                else:
                    assert observed_window.wait(3)
                    assert not model.done()
                assert not sent
            finally:
                native_return.set()
            assert pending.result(timeout=5)
            response = model.result(timeout=5)
    with database.transaction() as connection:
        uses = connection.execute('SELECT COUNT(*) FROM llm_uses').fetchone()[0]
    if mode == 'success':
        assert b'data: [DONE]' in response and len(sent) == uses == 1
    else:
        assert b'WALLE_HOLD' in response and len(sent) == uses == 0
