"""Original native control over real loopback and one-shot private receipts."""

import json
import os
from base64 import b64encode
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.code_tasks import task_instance_driver
from backend.app.code_tasks.task_instance_driver import TaskInstanceDriver
from backend.app.code_tasks.task_native_actions import TaskNativeActions
from backend.app.code_tasks.task_native_issues import normalize_permission, normalize_question
from backend.app.infrastructure.opencode_binary import VERSION
from backend.app.infrastructure.opencode_control import (
    OpenCodeControlCredential,
    OpenCodeControlTransportError,
)
from backend.app.infrastructure.opencode_instance_control import OpenCodeInstanceControl
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_task_endpoints import _plan

_SESSION = 'ses_fixture'


def _CHECKPOINT():
    pass


_TIMEOUT = {'timeout_ms': 4000}


@pytest.fixture
def native_control(tmp_path, request):
    root_name = getattr(request, 'param', 'native')
    configured_scope = None
    if type(root_name) is dict and set(root_name) == {'directory_role', 'scope_fixture'}:
        configured_scope = request.getfixturevalue(root_name['scope_fixture'])
        root_name = root_name['directory_role']
        if type(configured_scope) is not LaunchScope:
            raise ValueError('Original isolated native launch scope required')
    if root_name not in ('native', 'workspace'):
        raise ValueError('Known isolated native directory role required')
    path = create_private_package(tmp_path / root_name)
    state = {'requests': [], 'message': None, 'session': None, 'drops': set(), 'overrides': {}}

    class NativeHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond('GET')

        def do_POST(self):
            self.respond('POST')

        def do_PATCH(self):
            self.respond('PATCH')

        def respond(self, method):
            target = urlsplit(self.path)
            route = target.path
            query = parse_qs(target.query)
            state['requests'].append((method, route))
            authorized = self.headers.get('Authorization') == authorization
            if not authorized:
                self.finish_response(401, {})
                return
            if route == '/global/health':
                self.finish_response(200, {'healthy': True, 'version': VERSION})
                return
            assert query['directory'] == [directory.canonical_path]
            if route == '/event' and 'events' in state:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.end_headers()
                self.write_event({'id': 'evt_ready', 'type': 'server.connected', 'properties': {}})
                try:
                    for _ in range(6):
                        event = state['events'].get(timeout=3)
                        if event is None:
                            break
                        self.write_event(event)
                except (Empty, OSError):
                    pass
                return
            body = None
            if method in ('POST', 'PATCH'):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            status = 200
            if route in state['overrides']:
                result = state['overrides'][route]
            elif (method, route) == ('POST', '/question/que_original/reply'):
                state['reply_body'] = body
                if 'events' in state:
                    fields = {
                        'sessionID': _SESSION,
                        'requestID': 'que_original',
                        'answers': body['answers'],
                    }
                    state['events'].put(
                        {
                            'id': 'evt_other',
                            'type': 'question.replied',
                            'properties': {**fields, 'sessionID': 'ses_other'},
                        }
                    )
                    if state.get('valid_reply_event'):
                        state['events'].put(
                            {'id': 'evt_reply', 'type': 'question.replied', 'properties': fields}
                        )
                    state['events'].put(None)
                result = state.get('reply_ack', True)
            elif route == '/path':
                result = {
                    'directory': directory.canonical_path,
                    'worktree': directory.canonical_path,
                }
            elif (method, route) == ('POST', '/permission/per_selected/reply'):
                state['permission_body'] = body
                if 'events' in state:
                    for event_id, session, identity, reply in state.get('permission_events', []):
                        state['events'].put(
                            {
                                'id': event_id,
                                'type': 'permission.replied',
                                'properties': {
                                    'sessionID': session,
                                    'requestID': identity,
                                    'reply': reply,
                                },
                            }
                        )
                    state['events'].put(None)
                result = True
            elif (method, route) == ('POST', '/session'):
                state['session'] = {
                    **body,
                    'id': _SESSION,
                    'directory': directory.canonical_path,
                    'metadata': body['metadata'],
                }
                result = state['session']
            elif (method, route) == ('PATCH', '/session/' + _SESSION):
                state['patch_body'] = body
                state['session']['permission'] += body['permission']
                result = state['session']
            elif route == '/session':
                result = [state['session']]
            elif route == '/session/' + _SESSION:
                result = state['session']
            elif route == '/config':
                result = {'provider': {}}
            elif route == '/config/providers':
                result = {'providers': [], 'default': {}}
            elif route == '/session/status':
                result = {_SESSION: {'type': 'busy'}}
            elif route in ('/question', '/permission'):
                prefix = 'que' if route == '/question' else 'per'
                result = [
                    {'id': prefix + '_first', 'sessionID': 'ses_other'},
                    {'id': prefix + '_next', 'sessionID': _SESSION},
                ]
            elif route == '/session/' + _SESSION + '/prompt_async':
                state['message'] = {
                    'info': {'id': body['messageID'], 'sessionID': _SESSION, 'role': 'user'},
                    'parts': [
                        {**part, 'sessionID': _SESSION, 'messageID': body['messageID']}
                        for part in body['parts']
                    ],
                }
                status, result = 204, None
            elif route == '/session/' + _SESSION + '/message/' + state['message']['info']['id']:
                result = state['message']
            else:
                status, result = 404, {}
            if (method, route) not in state['drops']:
                self.finish_response(status, result)

        def write_event(self, event):
            self.wfile.write(b'event: message\r\ndata: ' + json.dumps(event).encode() + b'\r\n\r\n')
            self.wfile.flush()

        def finish_response(self, status, result):
            raw = b'' if result is None else json.dumps(result).encode()
            self.send_response(status)
            if status == 401 and state.get('challenge', True):
                self.send_header('WWW-Authenticate', 'Basic realm="Native test"')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    with (
        ThreadingHTTPServer(('127.0.0.1', 0), NativeHandler) as server,
        ObservedProcess(os.getpid()) as process,
        PrivatePackageGuard(path) as package,
    ):
        directory = package.verify()
        scope = configured_scope or LaunchScope('a' * 64, 3, 4, 'original-task-native-test')
        plan = _plan(1, server.server_port)
        credential = OpenCodeControlCredential.issue(scope, plan)
        environment = credential.launch_variables(scope, plan)
        username, password = (
            environment['OPENCODE_SERVER_USERNAME'],
            environment['OPENCODE_SERVER_PASSWORD'],
        )
        authorization = 'Basic ' + b64encode(f'{username}:{password}'.encode()).decode()
        control = OpenCodeInstanceControl(credential, process, process.identity, directory)
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            yield control, TaskNativeActions(package, scope, control), state, scope
        finally:
            credential.close()
            server.shutdown()
            thread.join(4)
        assert not thread.is_alive()


def _session_input(scope):
    return {
        'title': 'WALL-E original task',
        'agent': 'walle-code',
        'model': {'id': 'walle-code', 'providerID': 'walle'},
        'metadata': {
            'walle': {
                'task_id': 10,
                'execution_session_id': 11,
                'instance_id': 12,
                'operation_id': scope.operation_id,
                'control_generation': 1,
                'nonce': scope.nonce,
            }
        },
        'permission': [],
    }


@pytest.mark.parametrize(
    ('error_kind', 'diagnostic', 'retry'),
    [
        (TaskExecutionError, 'LISTENER_PENDING', True),
        (TaskExecutionError, 'RESULT_UNVERIFIED', True),
        (OpenCodeControlTransportError, 'TCP_DENIED', False),
        (OpenCodeControlTransportError, 'TCP_TIMEOUT', False),
        (OpenCodeControlTransportError, 'HTTP_TIMEOUT', False),
    ],
)
def test_startup_only_retries_original_transient_control_results(
    monkeypatch, error_kind, diagnostic, retry
):
    calls = []
    failure = error_kind('ORIGINAL_TASK_CONTROL_' + diagnostic)

    def check_ready(checkpoint, *, timeout_ms):
        checkpoint()
        calls.append(timeout_ms)
        if len(calls) == 1:
            raise failure

    monkeypatch.setattr(task_instance_driver, 'sleep', lambda _seconds: None)
    control = SimpleNamespace(verify_ready=check_ready)
    driver = TaskInstanceDriver.__new__(TaskInstanceDriver)
    if retry:
        driver._wait_ready(control, _CHECKPOINT, lambda: _TIMEOUT)
        assert calls == [4000, 4000]
    else:
        with pytest.raises(error_kind) as caught:
            driver._wait_ready(control, _CHECKPOINT, lambda: _TIMEOUT)
        assert caught.value is failure
        assert calls == [4000]


def test_native_configuration_status_and_pending_are_bound(native_control):
    control, _, state, _ = native_control
    assert control.verify_ready(_CHECKPOINT, **_TIMEOUT) == VERSION
    assert state['requests'][:2] == [('GET', '/global/health')] * 2
    state['challenge'] = False
    with pytest.raises(TaskExecutionError, match='BASIC_CHALLENGE_REQUIRED'):
        control.verify_ready(_CHECKPOINT, **_TIMEOUT)
    assert state['requests'].count(('GET', '/global/health')) == 3
    assert control.configuration(_CHECKPOINT, **_TIMEOUT)[1]['providers'] == []
    assert control.execution_status(_SESSION, _CHECKPOINT, **_TIMEOUT) == {'type': 'busy'}
    assert control.pending(_SESSION, 'question', _CHECKPOINT, **_TIMEOUT)[0]['id'] == 'que_next'
    assert control.pending(_SESSION, 'permission', _CHECKPOINT, **_TIMEOUT)[0]['id'] == 'per_next'
    state['overrides']['/session/status'] = {'ses_other': {'type': 'idle'}}
    with pytest.raises(TaskExecutionError, match='STATUS_UNKNOWN'):
        control.execution_status(_SESSION, _CHECKPOINT, **_TIMEOUT)
    with pytest.raises(TaskExecutionError, match='IDENTIFIER_INVALID'):
        control.session('ses_/../config', _CHECKPOINT, **_TIMEOUT)


def test_lost_native_responses_observe_exact_original_without_post_replay(native_control):
    control, actions, state, scope = native_control
    session = _session_input(scope)
    state['drops'].add(('POST', '/session'))
    with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
        actions.create_session(session, _CHECKPOINT, **_TIMEOUT)
    with pytest.raises(TaskExecutionError, match='REQUIRES_OBSERVATION'):
        actions.create_session(session, _CHECKPOINT, **_TIMEOUT)
    with pytest.raises(TaskExecutionError, match='LIST_INCOMPLETE'):
        control.find_session(session['metadata'], _CHECKPOINT, limit=1, **_TIMEOUT)
    assert actions.observe_session(_CHECKPOINT, **_TIMEOUT)['id'] == _SESSION
    assert actions.observe_session(_CHECKPOINT, **_TIMEOUT)['metadata'] == session['metadata']
    assert state['requests'].count(('POST', '/session')) == 1

    prompt = actions.initial_payload('walle-code', 'walle', 'walle-code', ['固定依据', '第一条'])
    assert prompt['messageID'].startswith('msg_')
    assert all(len(part['id']) == 30 for part in prompt['parts'])
    assert prompt['parts'][0]['id'] != prompt['parts'][1]['id']
    route = ('POST', '/session/' + _SESSION + '/prompt_async')
    state['drops'].add(route)
    with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
        actions.send_initial(_SESSION, prompt, _CHECKPOINT, **_TIMEOUT)
    with pytest.raises(TaskExecutionError, match='REQUIRES_OBSERVATION'):
        actions.send_initial(_SESSION, prompt, _CHECKPOINT, **_TIMEOUT)
    assert actions.observe_initial(_CHECKPOINT, **_TIMEOUT)['info']['id'] == prompt['messageID']
    state['message']['parts'][0]['text'] = 'changed'
    with pytest.raises(TaskExecutionError, match='ASSOCIATION_UNKNOWN'):
        actions.observe_initial(_CHECKPOINT, **_TIMEOUT)
    assert state['requests'].count(route) == 1


def test_oversize_native_prompt_is_rejected_before_creating_a_send_intent(
    native_control, monkeypatch
):
    from backend.app.infrastructure import opencode_instance_control

    _, actions, state, _ = native_control
    before = tuple(state['requests'])
    monkeypatch.setattr(opencode_instance_control, '_MAX_NATIVE_JSON', 220)
    with pytest.raises(TaskExecutionError, match='REQUEST_TOO_LARGE'):
        actions.initial_payload('walle-code', 'walle', 'walle-code', ['长' * 100])
    assert tuple(state['requests']) == before
    assert actions._read('initial', 'intent') is None


def test_native_acknowledged_session_and_message_are_distinct(native_control):
    _, actions, state, scope = native_control
    prompt = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    with pytest.raises(TaskExecutionError, match='SESSION_ACK_REQUIRED'):
        actions.send_initial(_SESSION, prompt, _CHECKPOINT, **_TIMEOUT)
    session = _session_input(scope)
    assert actions.create_session(session, _CHECKPOINT, **_TIMEOUT)['id'] == _SESSION
    assert actions.send_initial(_SESSION, prompt, _CHECKPOINT, **_TIMEOUT) == prompt['messageID']
    assert actions.observe_initial(_CHECKPOINT, **_TIMEOUT)['info']['role'] == 'user'
    assert [route for method, route in state['requests'] if method == 'POST'] == [
        '/session',
        '/session/' + _SESSION + '/prompt_async',
    ]


def test_continuation_uses_exact_settled_turn_and_checks_live_activity(native_control):
    control, _, state, _ = native_control
    route = '/session/' + _SESSION + '/message'
    source = {'id': 'msg_original', 'sessionID': _SESSION, 'role': 'user', 'time': {'created': 1}}
    assistant = {
        'id': 'msg_reply',
        'sessionID': _SESSION,
        'role': 'assistant',
        'parentID': 'msg_original',
        'time': {'created': 2, 'completed': 3},
        'finish': 'stop',
    }
    state['overrides'][route] = [{'info': source, 'parts': []}, {'info': assistant, 'parts': []}]
    assert control.settled_turn(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT) == 'msg_reply'
    assert not control.original_turn_idle(_SESSION, _CHECKPOINT, **_TIMEOUT)
    state['overrides']['/session/status'] = {}
    assert control.original_turn_idle(_SESSION, _CHECKPOINT, **_TIMEOUT)
    state['overrides']['/session/status'] = {'ses_other': {'type': 'busy'}}
    assert not control.original_turn_idle(_SESSION, _CHECKPOINT, **_TIMEOUT)
    assistant['parentID'] = 'msg_another'
    with pytest.raises(TaskExecutionError, match='TURN_UNVERIFIED'):
        control.settled_turn(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT)
    assistant['parentID'] = 'msg_original'
    assistant['finish'] = 'tool-calls'
    with pytest.raises(TaskExecutionError, match='TURN_UNVERIFIED'):
        control.settled_turn(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT)
    assistant['error'] = {'name': 'MessageAbortedError'}
    assert control.settled_turn(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT) == 'msg_reply'
    state['overrides'][route].append(
        {'info': {**source, 'id': 'msg_new', 'time': {'created': 4}}, 'parts': []}
    )
    with pytest.raises(TaskExecutionError, match='TURN_UNVERIFIED'):
        control.settled_turn(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT)
    assert all(method == 'GET' for method, _ in state['requests'])


@pytest.mark.parametrize(
    'mode', ['completed', 'error', 'running', 'foreign', 'subtask', 'repeated']
)
def test_original_turn_requires_all_tool_parts_to_be_settled(native_control, mode):
    control, _, state, _ = native_control
    tool = {
        'id': 'prt_owned',
        'sessionID': _SESSION,
        'messageID': 'msg_reply',
        'type': 'tool',
        'callID': 'original-call',
        'tool': 'edit',
        'state': {'status': mode, 'time': {'start': 2, 'end': 4}},
    }
    if mode == 'foreign':
        tool['sessionID'] = 'ses_other'
    if mode == 'subtask':
        tool['type'] = 'subtask'
    if mode == 'repeated':
        tool['state']['status'] = 'completed'
    parts = [tool, tool] if mode == 'repeated' else [tool]
    state['overrides']['/session/' + _SESSION + '/message'] = [
        {
            'info': {
                'id': 'msg_original',
                'sessionID': _SESSION,
                'role': 'user',
                'time': {'created': 1},
            },
            'parts': [],
        },
        {
            'info': {
                'id': 'msg_reply',
                'sessionID': _SESSION,
                'role': 'assistant',
                'parentID': 'msg_original',
                'time': {'created': 2, 'completed': 5},
                'finish': 'stop',
            },
            'parts': parts,
        },
    ]
    if mode in ('completed', 'error'):
        assert (
            control.settled_turn(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT) == 'msg_reply'
        )
    else:
        with pytest.raises(TaskExecutionError, match='PART_UNVERIFIED|TOOL_NOT_SETTLED'):
            control.settled_turn(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT)


def test_native_pending_contract_scopes_and_normalizes_actual_http(native_control):
    control, _, state, _ = native_control
    state['overrides']['/question'] = [
        {'id': 'que_other', 'sessionID': 'ses_other', 'questions': []},
        {
            'id': 'que_selected',
            'sessionID': _SESSION,
            'questions': [
                {
                    'header': '原题',
                    'question': '核对原设计',
                    'options': [{'label': '有依据', 'description': '原文'}],
                },
            ],
        },
    ]
    state['overrides']['/permission'] = [
        {
            'id': 'per_selected',
            'sessionID': _SESSION,
            'permission': 'read',
            'patterns': ['src/*.ts'],
            'metadata': {'native_only': 'fixture'},
            'always': ['*'],
            'tool': {'messageID': 'msg_original', 'callID': 'tool_id'},
        },
    ]
    question = [
        normalize_question(row)
        for row in control.pending(_SESSION, 'question', _CHECKPOINT, **_TIMEOUT)
    ]
    assert len(question) == 1 and question[0]['native_question_id'] == 'que_selected'
    assert json.loads(question[0]['questions']) == [
        {
            'index': 0,
            'header': '原题',
            'text': '核对原设计',
            'options': [{'label': '有依据', 'description': '原文'}],
            'multiple': False,
            'custom': True,
        }
    ]
    permission = [
        normalize_permission(row)
        for row in control.pending(_SESSION, 'permission', _CHECKPOINT, **_TIMEOUT)
    ]
    assert len(permission) == 1 and permission[0]['requested_action'] == 'READ'
    assert json.loads(permission[0]['patterns']) == ['src/*.ts']
    assert 'native_only' not in str(permission) and 'always' not in permission[0]
    assert state['requests'] == [('GET', '/question'), ('GET', '/permission')]


@pytest.mark.parametrize('ack', ['http', 'event', 'unproven'])
def test_question_reply_uses_one_native_post_and_matching_evidence(
    native_control, monkeypatch, ack
):
    control, actions, state, launch = native_control
    state['events'] = Queue()
    state['valid_reply_event'] = ack == 'event'
    route = '/question/que_original/reply'
    if ack != 'http':
        state['drops'].add(('POST', route))
    driver = object.__new__(TaskInstanceDriver)
    scope = SimpleNamespace(query_timeout_seconds=2, send_timeout_seconds=2)

    from backend.tests.infrastructure.test_v20_native_session_policy import configure_driver

    actions.create_session(_session_input(launch), _CHECKPOINT, **_TIMEOUT)
    owner = SimpleNamespace(
        credential=control._credential,
        workspace=control._workspace,
        gateway=SimpleNamespace(),
    )
    configure_driver(driver, owner, state)

    @contextmanager
    def original_actions(actual_owner, actual_scope):
        assert actual_owner is owner and actual_scope is scope
        yield actions

    monkeypatch.setattr(driver, '_native_actions', original_actions)
    state['requests'].clear()
    monkeypatch.setattr(
        driver, '_session_owner', lambda original: owner if original is scope else None
    )
    payload = [['原答案'], ['用户事实']]
    if ack == 'unproven':
        with pytest.raises(TaskExecutionError):
            driver.send_question_response(scope, _SESSION, 'que_original', payload, _CHECKPOINT)
    else:
        evidence = driver.send_question_response(
            scope, _SESSION, 'que_original', payload, _CHECKPOINT
        )
        assert evidence == (
            {'source': 'HTTP_200'}
            if ack == 'http'
            else {'source': 'NATIVE_EVENT', 'event_id': 'evt_reply'}
        )
    assert state['reply_body'] == {'answers': payload}
    assert state['requests'] == [
        ('GET', '/session/' + _SESSION),
        ('GET', '/config'),
        ('GET', '/config/providers'),
        ('GET', '/session/' + _SESSION),
        ('GET', '/event'),
        ('POST', route),
    ]


@pytest.mark.parametrize(
    'mode', ['once', 'wrong-root', 'wrong-edit-target', 'partial-denial', 'no-events']
)
def test_permission_post_pins_scope_and_only_observes_frozen_originals(
    native_control, monkeypatch, mode
):
    control, actions, state, launch = native_control
    workspace = control._workspace
    if mode != 'no-events':
        state['events'] = Queue()
    driver = object.__new__(TaskInstanceDriver)
    scope = SimpleNamespace(query_timeout_seconds=1, send_timeout_seconds=1)

    from backend.tests.infrastructure.test_v20_native_session_policy import configure_driver

    actions.create_session(_session_input(launch), _CHECKPOINT, **_TIMEOUT)
    owner = SimpleNamespace(
        credential=control._credential,
        workspace=control._workspace,
        gateway=SimpleNamespace(),
    )
    configure_driver(driver, owner, state)

    @contextmanager
    def original_actions(actual_owner, actual_scope):
        assert actual_owner is owner and actual_scope is scope
        yield actions

    monkeypatch.setattr(driver, '_native_actions', original_actions)
    state['requests'].clear()
    monkeypatch.setattr(
        driver, '_session_owner', lambda original: owner if original is scope else None
    )
    path = Path(workspace.canonical_path) / 'existing.txt'
    with path.open('xb') as file:
        file.write(b'isolated file')
    original = {
        'id': 'per_selected',
        'sessionID': _SESSION,
        'permission': 'read',
        'patterns': ['existing.txt'],
        'always': ['*'],
        'metadata': {},
    }
    if mode == 'wrong-edit-target':
        original.update(permission='edit', metadata={'filepath': str(path.with_name('else.txt'))})
    if mode == 'wrong-root':
        state['overrides']['/path'] = {
            'directory': str(path.parent),
            'worktree': str(path.parent.parent),
        }
    reply = 'reject' if mode in ('partial-denial', 'no-events') else 'once'
    route = '/permission/per_selected/reply'
    candidates = ('per_selected', 'per_peer') if reply == 'reject' else ('per_selected',)
    receipts, claims = {}, []

    def claim():
        if reply == 'reject':
            assert ('GET', '/event') in state['requests']
        claims.append('original')

    def record(identity, evidence):
        assert claims == ['original']
        receipts[identity] = evidence

    def send():
        driver.decide_native_permission(
            scope, (_SESSION, original, candidates, reply), _CHECKPOINT, claim, record
        )

    if mode == 'partial-denial':
        state['drops'].add(('POST', route))
        state['permission_events'] = [
            ('evt_wrong_session', 'ses_other', 'per_peer', 'reject'),
            ('evt_wrong_decision', _SESSION, 'per_peer', 'once'),
            ('evt_new', _SESSION, 'per_unobserved', 'reject'),
            ('evt_own', _SESSION, 'per_selected', 'reject'),
        ]
    if mode == 'once':
        send()
        assert receipts == {'per_selected': {'source': 'HTTP_200'}}
        assert state['requests'] == [
            ('GET', '/session/' + _SESSION),
            ('GET', '/config'),
            ('GET', '/config/providers'),
            ('GET', '/session/' + _SESSION),
            ('GET', '/path'),
            ('GET', '/event'),
            ('POST', route),
        ]
    else:
        with pytest.raises(TaskExecutionError):
            send()
        if mode == 'partial-denial':
            assert receipts == {'per_selected': {'source': 'NATIVE_EVENT', 'event_id': 'evt_own'}}
        else:
            assert not receipts and not claims and ('POST', route) not in state['requests']
    if claims:
        assert state['permission_body'] == {'reply': reply}
        assert state['requests'].count(('POST', route)) == 1


@pytest.mark.parametrize(
    'outcome',
    ['completed', 'cancelled', 'error', 'false-cancel', 'other-question', 'other-active'],
)
def test_capture_requires_exact_terminal_outcome_and_no_instance_writers(native_control, outcome):
    control, _, state, _ = native_control
    state['overrides']['/session/' + _SESSION + '/message'] = [
        {
            'info': {
                'id': 'msg_original',
                'sessionID': _SESSION,
                'role': 'user',
                'time': {'created': 20},
            },
            'parts': [],
        },
        {
            'info': {
                'id': 'msg_result',
                'sessionID': _SESSION,
                'role': 'assistant',
                'parentID': 'msg_original',
                'time': {'created': 21, 'completed': 25},
                'finish': 'stop',
            },
            'parts': [],
        },
    ]
    assistant = state['overrides']['/session/' + _SESSION + '/message'][-1]
    identity = {'sessionID': _SESSION, 'messageID': 'msg_result'}
    assistant['parts'] = [
        {**identity, 'id': 'prt_observed', 'type': 'text', 'text': '实际执行观察'},
        {**identity, 'id': 'prt_internal', 'type': 'reasoning', 'text': '原生内部内容'},
        {**identity, 'id': 'prt_synthetic', 'type': 'text', 'synthetic': True, 'text': '非消息'},
        {
            **identity,
            'id': 'prt_tool',
            'type': 'tool',
            'callID': 'call_fixture',
            'tool': 'read',
            'state': {
                'status': 'completed',
                'time': {'start': 22, 'end': 24},
                'input': {'path': 'private'},
                'output': '未授权的工具正文',
            },
        },
    ]
    last = state['overrides']['/session/' + _SESSION + '/message'][-1]['info']
    state['overrides']['/session/status'] = {}
    state['overrides']['/question'] = []
    state['overrides']['/permission'] = []
    if outcome in ('cancelled', 'error', 'false-cancel'):
        last['finish'] = 'error'
        last['error'] = {
            'name': 'APIError' if outcome == 'error' else 'MessageAbortedError',
            'data': {} if outcome == 'false-cancel' else {'message': 'stopped'},
        }
    if outcome == 'other-question':
        state['overrides']['/question'] = [{'id': 'que_other', 'sessionID': 'ses_other'}]
    if outcome == 'other-active':
        state['overrides']['/session/status'] = {'ses_other': {'type': 'busy'}}
    if outcome in ('completed', 'cancelled'):
        fact = control.capture_turn_completion(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT)
        assert (fact.session_id, fact.trigger_message_id, fact.assistant_message_id) == (
            _SESSION,
            'msg_original',
            'msg_result',
        )
        assert fact.outcome == outcome.upper()
        expected = [
            ('prt_observed', 'MESSAGE', '实际执行观察'),
            ('prt_tool', 'TOOL', 'read：已结束。'),
        ]
        if outcome == 'cancelled':
            expected.append(('error:msg_result', 'ERROR', '原生执行已取消。'))
        assert [(item.event_id, item.kind, item.text) for item in fact.records] == expected
    else:
        with pytest.raises(TaskExecutionError):
            control.capture_turn_completion(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT)
    assert all(method == 'GET' for method, _ in state['requests'])


def test_repair_successor_private_scope_recovers_lost_create_and_send_without_replay(
    native_control,
):
    control, original, state, launch = native_control
    successor = LaunchScope(launch.controller_ref, launch.operation_id + 1, 1, 'd' * 32)
    actions = TaskNativeActions(original._package, launch, control, action_scope=successor)
    session = _session_input(successor)
    session['metadata']['walle'].update(execution_session_id=13, control_generation=2)
    state['drops'].add(('POST', '/session'))
    with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
        actions.create_session(session, _CHECKPOINT, **_TIMEOUT)
    recovered = TaskNativeActions(original._package, launch, control, action_scope=successor)
    assert recovered.observe_session(_CHECKPOINT, **_TIMEOUT)['metadata'] == session['metadata']
    with pytest.raises(TaskExecutionError, match='REQUIRES_OBSERVATION'):
        recovered.create_session(session, _CHECKPOINT, **_TIMEOUT)
    assert original._read('session', 'intent') is None
    payload = recovered.plan_initial_payload('walle-code', 'walle', 'walle-code', ['固定原缺陷'])
    assert payload == recovered.plan_initial_payload(
        'walle-code', 'walle', 'walle-code', ['固定原缺陷']
    )
    state['drops'].add(('POST', '/session/' + _SESSION + '/prompt_async'))
    with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
        recovered.send_initial(_SESSION, payload, _CHECKPOINT, **_TIMEOUT)
    assert recovered.observe_initial(_CHECKPOINT, **_TIMEOUT)['info']['id'] == payload['messageID']
    assert state['requests'].count(('POST', '/session')) == 1
    assert state['requests'].count(('POST', '/session/' + _SESSION + '/prompt_async')) == 1


@pytest.mark.parametrize(
    'case',
    [
        'archived',
        'available',
        'missing-time',
        'busy',
        'pending',
        'wrong-metadata',
        'wrong-guard',
        'invalid-time',
    ],
)
def test_repair_archive_decision_requires_same_settled_native_turn_and_job(
    native_control, monkeypatch, case
):
    from backend.app.code_tasks.task_model_ingress import ModelWindow

    _, actions, state, launch = native_control
    session = _session_input(launch)
    actions.create_session(session, _CHECKPOINT, **_TIMEOUT)
    state['session']['time'] = {'archived': 123}
    state['overrides']['/session/status'] = {}
    state['overrides']['/question'] = []
    state['overrides']['/permission'] = []
    state['overrides']['/session/' + _SESSION + '/message'] = [
        {
            'info': {
                'id': 'msg_original',
                'sessionID': _SESSION,
                'role': 'user',
                'time': {'created': 1},
            },
            'parts': [],
        },
        {
            'info': {
                'id': 'msg_reply',
                'sessionID': _SESSION,
                'role': 'assistant',
                'parentID': 'msg_original',
                'time': {'created': 2, 'completed': 3},
                'finish': 'stop',
            },
            'parts': [],
        },
    ]
    if case == 'available':
        state['session']['time'] = {}
    elif case == 'missing-time':
        state['session'].pop('time')
    elif case == 'busy':
        state['overrides']['/session/status'] = {_SESSION: {'type': 'busy'}}
    elif case == 'pending':
        state['overrides']['/question'] = [{'id': 'que_pending', 'sessionID': _SESSION}]
    elif case == 'wrong-metadata':
        state['session']['metadata'] = {'walle': {'task_id': 999}}
    elif case == 'invalid-time':
        state['session']['time'] = {'archived': 1.5}
    driver = object.__new__(TaskInstanceDriver)
    from backend.tests.infrastructure.test_v20_native_session_policy import configure_driver

    owner = SimpleNamespace(gateway=SimpleNamespace())
    configure_driver(driver, owner, state)
    scope = SimpleNamespace(
        query_timeout_seconds=2, metadata=lambda: _session_input(launch)['metadata']
    )
    window = ModelWindow(10, 12, 1, 11, _SESSION, 3, 'msg_original')
    monkeypatch.setattr(driver, '_continuation_owner', lambda *args: owner)

    @contextmanager
    def native_actions(actual, actual_scope):
        assert actual is owner and actual_scope is scope
        yield actions

    monkeypatch.setattr(driver, '_native_actions', native_actions)
    guards = []

    def guard(*args):
        guards.append(True)
        return 'b' * 64 if case == 'wrong-guard' and len(guards) > 1 else 'a' * 64

    monkeypatch.setattr(driver, '_continuation_guard', guard)
    before = len([method for method, _ in state['requests'] if method == 'POST'])
    if case in ('archived', 'available', 'missing-time'):
        result = driver.repair_session_archived_at(scope, window, 'fixture', _CHECKPOINT)
        assert result == (123 if case == 'archived' else None)
    else:
        with pytest.raises((TaskExecutionError, ValueError)):
            driver.repair_session_archived_at(scope, window, 'fixture', _CHECKPOINT)
    assert len([method for method, _ in state['requests'] if method == 'POST']) == before


@pytest.mark.parametrize('case', ['same-source', 'new-turn', 'pending', 'changed-guard'])
def test_replacement_source_is_rechecked_after_creation_before_queue(
    native_control, monkeypatch, case
):
    from backend.app.code_tasks.task_instance_driver import CaptureTurnEvidence

    control, actions, state, launch = native_control
    actions.create_session(_session_input(launch), _CHECKPOINT, **_TIMEOUT)
    state['overrides']['/session/status'] = {}
    state['overrides']['/question'] = []
    state['overrides']['/permission'] = []
    messages = [
        {
            'info': {
                'id': 'msg_original',
                'sessionID': _SESSION,
                'role': 'user',
                'time': {'created': 1},
            },
            'parts': [],
        },
        {
            'info': {
                'id': 'msg_reply',
                'sessionID': _SESSION,
                'role': 'assistant',
                'parentID': 'msg_original',
                'time': {'created': 2, 'completed': 3},
                'finish': 'stop',
            },
            'parts': [],
        },
    ]
    state['overrides']['/session/' + _SESSION + '/message'] = messages
    turn = control.capture_turn_completion(_SESSION, 'msg_original', _CHECKPOINT, **_TIMEOUT)
    proof = CaptureTurnEvidence(turn, 'a' * 64, 1, control._workspace).scope_proof()
    if case == 'new-turn':
        messages.append(
            {
                'info': {
                    'id': 'msg_later',
                    'sessionID': _SESSION,
                    'role': 'user',
                    'time': {'created': 4},
                },
                'parts': [],
            }
        )
    elif case == 'pending':
        state['overrides']['/permission'] = [{'id': 'per_later', 'sessionID': _SESSION}]
    driver = object.__new__(TaskInstanceDriver)
    owner = SimpleNamespace(
        credential=control._credential,
        workspace=control._workspace,
        scratch=None,
        gateway=SimpleNamespace(_credential=SimpleNamespace(_secret='temporary-fixture-gateway')),
    )
    scope = SimpleNamespace(query_timeout_seconds=2)
    monkeypatch.setattr(driver, '_continuation_owner', lambda *args: owner)

    @contextmanager
    def native_actions(*args):
        yield actions

    monkeypatch.setattr(driver, '_native_actions', native_actions)
    monkeypatch.setattr(
        driver,
        '_continuation_guard',
        lambda *args: 'b' * 64 if case == 'changed-guard' else 'a' * 64,
    )
    before = sum(method == 'POST' for method, _ in state['requests'])
    if case == 'same-source':
        assert (
            driver.observe_replacement_source(scope, proof, 'fixture', _CHECKPOINT).scope_proof()
            == proof
        )
    else:
        with pytest.raises(TaskExecutionError):
            driver.observe_replacement_source(scope, proof, 'fixture', _CHECKPOINT)
    assert sum(method == 'POST' for method, _ in state['requests']) == before


@pytest.mark.parametrize(
    'case',
    [
        'original-create',
        'no-original-intent',
        'changed-policy',
        'changed-metadata',
        'changed-policy-after-ack',
        'changed-metadata-after-ack',
    ],
)
def test_created_session_reconciliation_reads_only_original_private_intent(
    native_control, monkeypatch, case
):
    control, actions, state, scope = native_control
    request = _session_input(scope)
    state['drops'].add(('POST', '/session'))
    with pytest.raises(TaskExecutionError):
        actions.create_session(request, _CHECKPOINT, **_TIMEOUT)
    state['session'].update(
        {key: request[key] for key in ('title', 'agent', 'model', 'permission')}
    )
    if case.endswith('-after-ack'):
        assert actions.observe_session(_CHECKPOINT, **_TIMEOUT)['id'] == _SESSION
    if case == 'no-original-intent':
        other = LaunchScope(scope.controller_ref, scope.operation_id + 1, 4, 'e' * 32)
        actions = TaskNativeActions(actions._package, scope, control, action_scope=other)
    elif case in ('changed-policy', 'changed-policy-after-ack'):
        state['session']['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    elif case in ('changed-metadata', 'changed-metadata-after-ack'):
        state['session']['metadata'] = {'walle': {'task_id': 999}}
    driver = object.__new__(TaskInstanceDriver)
    from backend.tests.infrastructure.test_v20_native_session_policy import configure_driver

    owner = SimpleNamespace(gateway=SimpleNamespace())
    configure_driver(driver, owner, state)
    original = SimpleNamespace(query_timeout_seconds=2)
    monkeypatch.setattr(
        driver, '_session_owner', lambda actual: owner if actual is original else None
    )

    @contextmanager
    def native_actions(*args):
        yield actions

    monkeypatch.setattr(driver, '_native_actions', native_actions)
    before = tuple(state['requests'])
    if case == 'original-create':
        assert driver.observe_created_session(original, _CHECKPOINT) == _SESSION
    else:
        with pytest.raises(TaskExecutionError):
            driver.observe_created_session(original, _CHECKPOINT)
    assert state['requests'].count(('POST', '/session')) == 1
    assert all(method == 'GET' for method, _ in state['requests'][len(before) :])


@pytest.mark.parametrize(
    'case', ['verified', 'permission', 'configuration', 'metadata', 'guard', 'model-alias']
)
def test_live_control_observation_reads_actual_original_native_group(
    native_control, monkeypatch, case
):
    from hashlib import sha256

    from backend.app.code_tasks.task_initial_configuration import InitialConfigurationObservation
    from backend.app.code_tasks.task_initial_prompt import (
        CP20_SYSTEM,
        NativeCodingPolicy,
        checked_coding_configuration,
    )
    from backend.app.code_tasks.task_instance_driver import CaptureTurnEvidence
    from backend.app.code_tasks.task_model_ingress import ModelWindow
    from backend.app.infrastructure.opencode_instance_control import NativeTurnCompletion
    from backend.app.infrastructure.runtime_launch_journal import _bytes

    control, actions, state, launch = native_control
    request = _session_input(launch)
    request['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'deny'}]
    policy = NativeCodingPolicy(request['agent'], (('*', '*', 'deny'),))
    actions.create_session(request, _CHECKPOINT, **_TIMEOUT)
    state['session'].update(
        {key: request[key] for key in ('title', 'agent', 'model', 'permission')}
    )
    credential = SimpleNamespace(
        base_url='http://127.0.0.1:19117/internal/fixture/v1',
    )
    from backend.app.infrastructure.opencode_model_credential import MODEL_BEARER_ENV

    credential.environment = lambda: {MODEL_BEARER_ENV: 'isolated-no-provider-secret'}
    models = {'walle-code': {'id': 'walle-code'}, 'walle-compaction': {'id': 'walle-compaction'}}
    configuration = {
        'agent': {request['agent']: {'prompt': CP20_SYSTEM, 'model': 'walle/walle-code'}},
        'provider': {
            'walle': {
                'npm': '@ai-sdk/openai-compatible',
                'models': models,
                'options': {
                    'baseURL': credential.base_url,
                    'apiKey': 'isolated-no-provider-secret',
                },
            }
        },
    }
    providers = {'providers': [{'id': 'walle', 'models': models}]}
    state['overrides']['/config'] = configuration
    state['overrides']['/config/providers'] = providers
    checked = checked_coding_configuration((configuration, providers), credential, policy)
    original = InitialConfigurationObservation(
        'opencode-bundle:sha256:' + 'a' * 64,
        'e' * 64,
        sha256(_bytes(checked)).hexdigest(),
        request['agent'],
    )
    owner = SimpleNamespace(configuration=original, gateway=SimpleNamespace(_credential=credential))
    scope = SimpleNamespace(query_timeout_seconds=2)
    window = ModelWindow(10, 12, 1, 11, _SESSION, 3, 'msg_original')
    quiet = CaptureTurnEvidence(
        NativeTurnCompletion(_SESSION, 'msg_original', 'msg_finished', 'COMPLETED'),
        'a' * 64,
        1,
        control._workspace,
    )
    driver = object.__new__(TaskInstanceDriver)
    driver._installation = SimpleNamespace(coding=policy)
    monkeypatch.setattr(driver, '_continuation_owner', lambda *args: owner)
    monkeypatch.setattr(driver, 'observe_capture_turn', lambda *args: quiet)
    monkeypatch.setattr(
        driver, '_continuation_guard', lambda *args: 'b' * 64 if case == 'guard' else 'a' * 64
    )

    @contextmanager
    def native_actions(actual_owner, actual_scope):
        assert actual_owner is owner and actual_scope is scope
        yield actions

    monkeypatch.setattr(driver, '_native_actions', native_actions)
    if case == 'permission':
        state['session']['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    elif case == 'configuration':
        configuration['agent'][request['agent']]['prompt'] = 'different source'
    elif case == 'metadata':
        state['session']['metadata'] = {'walle': {'task_id': 999}}
    elif case == 'model-alias':
        # The fixed registry exposes apply_patch for gpt-* identifiers only.
        # A changed provider id must fail before accepting that different tool set.
        configuration['provider']['walle']['models']['walle-code']['id'] = 'gpt-5'
    before = len(state['requests'])
    if case == 'verified':
        result = driver.observe_control_configuration(scope, window, 'fixture', _CHECKPOINT)
        assert result.configuration == original and result.quiescence is quiet
        assert result.permission_sha256 == sha256(_bytes(request['permission'])).hexdigest()
    else:
        with pytest.raises(TaskExecutionError):
            driver.observe_control_configuration(scope, window, 'fixture', _CHECKPOINT)
    assert all(method == 'GET' for method, _ in state['requests'][before:])
    assert state['requests'].count(('POST', '/session')) == 1
