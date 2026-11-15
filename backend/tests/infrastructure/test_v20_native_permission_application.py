"""Real loopback PATCH and private NTFS original intent; no model or business adoption."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from threading import Barrier, local

import pytest

from backend.app.code_tasks import task_native_actions as native_actions_module
from backend.app.code_tasks.task_native_actions import TaskNativeActions
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_private_record import PrivateRecordError
from backend.tests.infrastructure import test_v20_opencode_instance_control as native_fixture
from backend.tests.infrastructure.test_v20_opencode_instance_control import (
    _CHECKPOINT,
    _SESSION,
    _TIMEOUT,
    _session_input,
)
from tools.quality_gate import environment

native_control = native_fixture.native_control

RESET = {'permission': '*', 'pattern': '*', 'action': 'deny'}
READ = {'permission': 'read', 'pattern': 'workspace/*', 'action': 'ask'}
ROUTE = ('PATCH', '/session/' + _SESSION)


def prepare(fixture):
    control, original, state, launch = fixture
    payload = _session_input(launch)
    payload['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    original.create_session(payload, _CHECKPOINT, **_TIMEOUT)
    scope = LaunchScope(launch.controller_ref, 91, 3, 'original-permission-change')
    actions = TaskNativeActions(original._package, launch, control, action_scope=scope)
    expected = {
        key: deepcopy(state['session'][key])
        for key in ('id', 'title', 'agent', 'model', 'metadata', 'permission')
    }
    return actions, expected, state


@pytest.mark.parametrize('drop', [False, True])
def test_original_patch_unknown_is_read_only_even_after_reopening(native_control, drop):
    actions, before, state = prepare(native_control)
    if drop:
        state['drops'].add(ROUTE)
        with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
            actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    else:
        result = actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
        assert result['permission'] == before['permission'] + [RESET, READ]
    assert actions._read('permission', 'intent') is not None
    assert (actions._read('permission', 'ack') is None) is drop
    control, original, _, launch = native_control
    reopened = TaskNativeActions(original._package, launch, control, action_scope=actions._scope)
    with pytest.raises(TaskExecutionError, match='REQUIRES_OBSERVATION'):
        reopened.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    for _ in range(2):
        observed = reopened.observe_permission(_CHECKPOINT, **_TIMEOUT)
        assert observed['id'] == before['id']
    assert state['requests'].count(ROUTE) == 1
    assert state['patch_body'] == {'permission': [RESET, READ]}


@pytest.mark.parametrize('field', ['agent', 'model', 'metadata', 'title', 'permission'])
def test_same_session_policy_drift_stays_unknown_without_patch_replay(native_control, field):
    actions, before, state = prepare(native_control)
    state['drops'].add(ROUTE)
    with pytest.raises(TaskExecutionError):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    correct = deepcopy(state['session'][field])
    state['session'][field] = [] if field == 'permission' else 'drift'
    with pytest.raises(TaskExecutionError, match='EFFECTIVE_POLICY_UNKNOWN'):
        actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'ack') is None
    state['session'][field] = correct
    actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert state['requests'].count(ROUTE) == 1


@pytest.mark.parametrize(
    'rules',
    [
        [],
        [READ],
        [RESET, {'permission': 'read', 'pattern': '*', 'action': 'always'}],
        [RESET, {'permission': 'read', 'pattern': '*', 'action': 'allow', 'extra': True}],
        [RESET, {'permission': '', 'pattern': '*', 'action': 'allow'}],
    ],
)
def test_bad_rules_fail_before_intent_or_mutation(native_control, rules):
    actions, before, state = prepare(native_control)
    with pytest.raises(TaskExecutionError):
        actions.apply_permission(before, rules, _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'intent') is None
    assert ROUTE not in state['requests']


def test_before_policy_drift_refuses_intent_and_empty_patch_cannot_revoke(native_control):
    actions, before, state = prepare(native_control)
    before['agent'] = 'wrong-agent'
    with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
        actions.apply_permission(before, [RESET], _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'intent') is None
    assert ROUTE not in state['requests']


def test_stop_after_intent_prevents_patch_and_reconciliation_never_sends(native_control):
    actions, before, state = prepare(native_control)

    def stopped():
        if actions._read('permission', 'intent') is not None:
            raise TaskExecutionError('STOP_REQUESTED')

    with pytest.raises(TaskExecutionError, match='STOP_REQUESTED'):
        actions.apply_permission(before, [RESET, READ], stopped, **_TIMEOUT)
    assert actions._read('permission', 'intent') is not None
    assert ROUTE not in state['requests']
    with pytest.raises(TaskExecutionError, match='EFFECTIVE_POLICY_UNKNOWN'):
        actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert ROUTE not in state['requests']


def test_wrong_action_scope_cannot_publish_permission_intent(native_control):
    _, actions, state, _ = native_control
    with pytest.raises(TaskExecutionError, match='APPLICATION_SCOPE_REQUIRED'):
        actions.apply_permission({}, [RESET], _CHECKPOINT, **_TIMEOUT)
    assert ROUTE not in state['requests']


@pytest.mark.parametrize('action', ['session', 'initial', 'permission'])
def test_same_original_intent_has_only_one_publisher_and_one_http_mutation(
    native_control, monkeypatch, action
):
    control, original, state, launch = native_control
    if action == 'permission':
        first, before, state = prepare(native_control)
        second = TaskNativeActions(original._package, launch, control, action_scope=first._scope)
        route = ROUTE
        invoke = lambda actions: actions.apply_permission(
            before, [RESET, READ], _CHECKPOINT, **_TIMEOUT
        )
    elif action == 'initial':
        original.create_session(_session_input(launch), _CHECKPOINT, **_TIMEOUT)
        first = original
        second = TaskNativeActions(original._package, launch, control)
        payload = original.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
        route = ('POST', '/session/' + _SESSION + '/prompt_async')
        invoke = lambda actions: actions.send_initial(_SESSION, payload, _CHECKPOINT, **_TIMEOUT)
    else:
        first = original
        second = TaskNativeActions(original._package, launch, control)
        payload = _session_input(launch)
        route = ('POST', '/session')
        invoke = lambda actions: actions.create_session(payload, _CHECKPOINT, **_TIMEOUT)

    gate = Barrier(2)
    counters = local()
    read = TaskNativeActions._read

    def competing_read(self, kind, phase):
        value = read(self, kind, phase)
        if kind == action and phase == 'intent':
            counters.reads = getattr(counters, 'reads', 0) + 1
            if counters.reads == (2 if action == 'permission' else 1):
                assert value is None
                gate.wait(timeout=10)
        return value

    monkeypatch.setattr(TaskNativeActions, '_read', competing_read)

    def attempt(actions):
        try:
            invoke(actions)
            return 'sent'
        except RuntimeError as error:
            return type(error).__name__

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (first, second)))
    assert results.count('sent') == 1, results
    assert state['requests'].count(route) == 1
    assert read(first, action, 'intent') is not None


def test_permission_input_is_frozen_and_reset_covers_previous_wildcards(native_control):
    actions, before, state = prepare(native_control)
    rules = [deepcopy(RESET), deepcopy(READ)]

    def changed_alias():
        if actions._read('permission', 'intent') is not None:
            rules[-1]['action'] = 'allow'
            before['permission'][0]['action'] = 'deny'

    observed = actions.apply_permission(before, rules, changed_alias, **_TIMEOUT)
    assert state['patch_body'] == {'permission': [RESET, READ]}
    assert observed['permission'][0]['action'] == 'allow'
    assert observed['permission'][-1]['action'] == 'ask'


def test_permission_capacity_is_checked_before_writing_original_intent(native_control, monkeypatch):
    from backend.app.infrastructure import opencode_instance_control

    actions, before, state = prepare(native_control)
    monkeypatch.setattr(opencode_instance_control, '_MAX_NATIVE_JSON', 300)
    with pytest.raises(TaskExecutionError, match='REQUEST_TOO_LARGE'):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'intent') is None
    assert ROUTE not in state['requests']


@pytest.mark.parametrize('action', ['session', 'initial'])
@pytest.mark.parametrize('kind', ['extra', 'model', 'permission-or-parts'])
def test_invalid_launch_input_leaves_no_phantom_original_intent(native_control, action, kind):
    _, actions, state, launch = native_control
    if action == 'session':
        payload = _session_input(launch)
    else:
        actions.create_session(_session_input(launch), _CHECKPOINT, **_TIMEOUT)
        payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    if kind == 'extra':
        payload['unexpected'] = True
    elif kind == 'model':
        payload['model'] = {'providerID': 'walle'}
    elif action == 'session':
        payload['permission'] = [{'permission': 'read', 'pattern': '*', 'action': 'always'}]
    else:
        payload['parts'][0]['type'] = 'tool'
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError):
        if action == 'session':
            actions.create_session(payload, _CHECKPOINT, **_TIMEOUT)
        else:
            actions.send_initial(_SESSION, payload, _CHECKPOINT, **_TIMEOUT)
    assert actions._read(action, 'intent') is None
    assert tuple(state['requests']) == requests


@pytest.mark.parametrize('action', ['session', 'initial'])
def test_launch_uses_frozen_original_bytes_when_checkpoint_mutates_caller(native_control, action):
    _, actions, state, launch = native_control
    if action == 'session':
        payload = _session_input(launch)
    else:
        actions.create_session(_session_input(launch), _CHECKPOINT, **_TIMEOUT)
        payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])

    def mutate():
        if actions._read(action, 'intent') is not None:
            if action == 'session':
                payload['permission'] = [deepcopy(RESET)]
            else:
                payload['parts'][0]['text'] = 'caller changed bytes'

    if action == 'session':
        actions.create_session(payload, mutate, **_TIMEOUT)
        assert state['session']['permission'] == []
    else:
        actions.send_initial(_SESSION, payload, mutate, **_TIMEOUT)
        assert state['message']['parts'][0]['text'] == 'fixed'
    original = actions._original(action)['input']
    if action == 'session':
        assert original['permission'] == []
    else:
        assert original['payload']['parts'][0]['text'] == 'fixed'


def test_uncertain_intent_publication_cannot_acquire_dispatch_on_retry(native_control, monkeypatch):
    actions, before, state = prepare(native_control)
    publish = native_actions_module._publish_original

    def lost_published_confirmation(package, name, raw, limit):
        publish(package, name, raw, limit)
        if name.endswith('.task-opencode-permission-intent.json'):
            raise PrivateRecordError('PRIVATE_RECORD_PUBLISHED_FLUSH_UNVERIFIED')

    monkeypatch.setattr(native_actions_module, '_publish_original', lost_published_confirmation)
    with pytest.raises(TaskExecutionError, match='PUBLICATION_UNKNOWN'):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'intent') is not None
    assert ROUTE not in state['requests']
    with pytest.raises(TaskExecutionError, match='REQUIRES_OBSERVATION'):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    with pytest.raises(TaskExecutionError, match='EFFECTIVE_POLICY_UNKNOWN'):
        actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert ROUTE not in state['requests']


def test_ack_persistence_failure_recovers_only_same_actual_permission(native_control, monkeypatch):
    actions, before, state = prepare(native_control)
    publish = native_actions_module._publish_original

    def lost_ack(package, name, raw, limit):
        publish(package, name, raw, limit)
        if name.endswith('.task-opencode-permission-ack.json'):
            raise PrivateRecordError('PRIVATE_RECORD_PUBLISHED_FLUSH_UNVERIFIED')

    monkeypatch.setattr(native_actions_module, '_publish_original', lost_ack)
    with pytest.raises(PrivateRecordError):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'ack') is not None
    observed = actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert observed['permission'] == before['permission'] + [RESET, READ]
    assert state['requests'].count(ROUTE) == 1


@pytest.mark.parametrize(
    'rules',
    [
        None,
        {},
        [RESET, None],
        [RESET, {'permission': 'read', 'pattern': 'a\x00b', 'action': 'ask'}],
    ],
)
def test_malformed_permission_wire_cannot_send_or_persist(native_control, rules):
    actions, before, state = prepare(native_control)
    with pytest.raises(TaskExecutionError, match='RULES_REQUIRED'):
        actions.apply_permission(before, rules, _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'intent') is None
    assert ROUTE not in state['requests']


@pytest.mark.parametrize('predecessor', [False, True])
def test_new_process_recovers_original_permission_using_only_get(
    native_control, tmp_path, predecessor
):
    actions, before, state = prepare(native_control)
    previous_applications = ()
    if predecessor:
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
        control, original, _, launch = native_control
        previous_applications = (actions._scope,)
        actions = TaskNativeActions(
            original._package,
            launch,
            control,
            action_scope=LaunchScope(launch.controller_ref, 92, 3, 'second-permission-change'),
        )
        before = {
            key: deepcopy(state['session'][key])
            for key in ('id', 'title', 'agent', 'model', 'metadata', 'permission')
        }
    state['drops'].add(ROUTE)
    with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
        actions.apply_permission(
            before,
            [RESET, READ],
            _CHECKPOINT,
            **_TIMEOUT,
            previous_applications=previous_applications,
        )
    control, _, _, launch = native_control
    port = control._credential._endpoint[1]
    plan = native_fixture._plan(1, port)
    payload = {
        'launch': asdict(launch),
        'action': asdict(actions._scope),
        'credential': control._credential.pipe_payload(launch, plan),
        'directory': str(actions._package.path),
        'pid': os.getpid(),
        'port': port,
        'permission': before['permission'] + [RESET, READ],
    }
    script = """
import json
import sys

from backend.app.infrastructure.sqlite_runtime import activate
activate()
from backend.app.code_tasks.task_native_actions import TaskNativeActions
from backend.app.infrastructure.opencode_control import OpenCodeControlCredential
from backend.app.infrastructure.opencode_instance_control import OpenCodeInstanceControl
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_task_endpoints import _plan
value = json.loads(sys.stdin.read())
scope = LaunchScope(**value['launch'])
credential = OpenCodeControlCredential.from_pipe(
    scope, _plan(1, value['port']), value['credential']
)
try:
    with ObservedProcess(value['pid']) as process, PrivatePackageGuard(value['directory']) as package:
        control = OpenCodeInstanceControl(credential, process, process.identity, package.verify())
        actions = TaskNativeActions(
            package, scope, control, action_scope=LaunchScope(**value['action'])
        )
        result = actions.observe_permission(lambda: None, timeout_ms=4000)
        assert result['permission'] == value['permission']
        print('RESTORED_READ_ONLY')
finally:
    credential.close()
"""
    requests = len(state['requests'])
    result = subprocess.run(
        [sys.executable, '-B', '-X', 'utf8', '-c', script],
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
        env=environment(tmp_path),
        cwd=Path(__file__).resolve().parents[3],
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'RESTORED_READ_ONLY'
    assert state['requests'][requests:] == [('GET', '/session/' + _SESSION)]
    assert state['requests'].count(ROUTE) == 1 + int(predecessor)
    assert actions._read('permission', 'ack') is not None


@pytest.mark.parametrize('defect', ['missing', 'extra', 'reset', 'before', 'rules'])
def test_malformed_retained_permission_intent_is_not_queried_or_acknowledged(
    native_control, defect
):
    actions, before, state = prepare(native_control)
    payload = {'before': deepcopy(before), 'rules': [deepcopy(RESET), deepcopy(READ)]}
    if defect == 'missing':
        payload.pop('before')
    elif defect == 'extra':
        payload['new-key'] = True
    elif defect == 'reset':
        payload['rules'] = [deepcopy(READ)]
    elif defect == 'before':
        payload['before']['model'] = None
    else:
        payload['rules'] = [{'action': 'deny'}]
    actions._write(
        'permission',
        'intent',
        {'scope': actions._scope.key, 'action': 'permission', 'input': payload},
    )
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError):
        actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert tuple(state['requests']) == requests
    assert actions._read('permission', 'ack') is None


def test_permission_reserves_complete_ack_capacity_before_writing_or_sending(
    native_control, monkeypatch
):
    from backend.app.infrastructure.runtime_launch_journal import _bytes

    actions, before, state = prepare(native_control)
    intent = {
        'scope': actions._scope.key,
        'action': 'permission',
        'input': {'before': before, 'rules': [RESET, READ]},
    }
    monkeypatch.setattr(native_actions_module, '_LIMIT', len(_bytes(intent)))
    with pytest.raises(TaskExecutionError, match='RECORD_TOO_LARGE'):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'intent') is None
    assert ROUTE not in state['requests']


@pytest.mark.parametrize('action', ['session', 'initial'])
def test_original_record_envelope_is_bounded_before_publish(native_control, monkeypatch, action):
    _, actions, state, launch = native_control
    if action == 'session':
        payload = _session_input(launch)
        invoke = lambda: actions.create_session(payload, _CHECKPOINT, **_TIMEOUT)
    else:
        actions.create_session(_session_input(launch), _CHECKPOINT, **_TIMEOUT)
        payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed' * 500])
        invoke = lambda: actions.send_initial(_SESSION, payload, _CHECKPOINT, **_TIMEOUT)
    maximum = 32 if action == 'session' else len(actions._read('session', 'ack')) + 1
    monkeypatch.setattr(native_actions_module, '_LIMIT', maximum)
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError, match='RECORD_TOO_LARGE'):
        invoke()
    assert tuple(state['requests']) == requests
    assert actions._read(action, 'intent') is None


@pytest.mark.parametrize('case', ['object', 'nonfinite', 'cycle', 'surrogate'])
def test_non_json_session_input_is_typed_rejection_before_original_intent(native_control, case):
    _, actions, state, launch = native_control
    payload = _session_input(launch)
    if case == 'object':
        payload['metadata']['invalid'] = object()
    elif case == 'nonfinite':
        payload['metadata']['invalid'] = float('nan')
    elif case == 'cycle':
        payload['metadata']['invalid'] = payload
    else:
        payload['title'] = chr(0xD800)
    with pytest.raises(TaskExecutionError, match='REQUEST_INVALID'):
        actions.create_session(payload, _CHECKPOINT, **_TIMEOUT)
    assert actions._read('session', 'intent') is None
    assert not state['requests']


@pytest.mark.parametrize('value', [True, 1.0])
def test_equal_numeric_metadata_is_not_the_same_native_identity(native_control, value):
    actions, before, state = prepare(native_control)
    state['session']['metadata']['walle']['control_generation'] = value
    with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'intent') is None
    assert ROUTE not in state['requests']


@pytest.mark.parametrize('value', [True, 1.0])
def test_metadata_type_drift_after_patch_stays_unknown_until_exact_restore(native_control, value):
    actions, before, state = prepare(native_control)
    state['drops'].add(ROUTE)
    with pytest.raises(TaskExecutionError):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    state['session']['metadata']['walle']['control_generation'] = value
    with pytest.raises(TaskExecutionError, match='EFFECTIVE_POLICY_UNKNOWN'):
        actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert actions._read('permission', 'ack') is None
    state['session']['metadata']['walle']['control_generation'] = 1
    actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert state['requests'].count(ROUTE) == 1


@pytest.mark.parametrize('value', [True, 1.0])
def test_original_creation_metadata_does_not_coerce_numeric_types(native_control, value):
    control, actions, state, scope = native_control
    payload = _session_input(scope)
    wrong = deepcopy(payload)
    wrong['metadata']['walle']['control_generation'] = value
    wrong.update(id=_SESSION, directory=control._workspace.canonical_path)
    state['overrides']['/session'] = wrong
    with pytest.raises(TaskExecutionError, match='ASSOCIATION_UNKNOWN'):
        actions.create_session(payload, _CHECKPOINT, **_TIMEOUT)
    assert actions._read('session', 'ack') is None
    state['overrides']['/session'] = [wrong]
    with pytest.raises(TaskExecutionError, match='ASSOCIATION_UNKNOWN'):
        actions.observe_session(_CHECKPOINT, **_TIMEOUT)
    assert state['requests'].count(('POST', '/session')) == 1


@pytest.mark.parametrize('field', ['id', 'title', 'agent', 'model', 'metadata', 'permission'])
def test_current_get_and_caller_cannot_self_certify_a_different_creation(native_control, field):
    actions, before, state = prepare(native_control)
    replacements = {
        'id': 'ses_otherOriginal',
        'title': 'different original title',
        'agent': 'other-agent',
        'model': {'providerID': 'other', 'modelID': 'other'},
        'metadata': {'walle': {'operation_id': 999}},
        'permission': [deepcopy(RESET)],
    }
    before[field] = deepcopy(replacements[field])
    state['session'][field] = deepcopy(replacements[field])
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError):
        actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert tuple(state['requests']) == requests
    assert actions._read('permission', 'intent') is None
    assert actions._read('permission', 'ack') is None


@pytest.mark.parametrize('phase', ['intent', 'ack'])
@pytest.mark.parametrize('defect', ['missing', 'corrupt', 'different'])
@pytest.mark.parametrize('recover', [False, True])
def test_permission_source_must_remain_original_before_dispatch_and_recovery(
    native_control, monkeypatch, phase, defect, recover
):
    actions, before, state = prepare(native_control)
    if recover:
        state['drops'].add(ROUTE)
        with pytest.raises(TaskExecutionError):
            actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    read = TaskNativeActions._read
    launch = native_control[3]

    def changed_source(self, action, stage):
        raw = read(self, action, stage)
        if self._scope == launch and action == 'session' and stage == phase:
            if defect == 'missing':
                return None
            if defect == 'corrupt':
                return b'{'
            value = json.loads(raw)
            if phase == 'ack':
                value['result']['native_session_id'] = 'ses_otherOriginal'
            else:
                value['input']['title'] = 'different retained creation'
            return json.dumps(value).encode()
        return raw

    monkeypatch.setattr(TaskNativeActions, '_read', changed_source)
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError):
        if recover:
            actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
        else:
            actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert tuple(state['requests']) == requests
    assert actions._read('permission', 'ack') is None
    assert state['requests'].count(ROUTE) == int(recover)
    monkeypatch.setattr(TaskNativeActions, '_read', read)
    if recover:
        actions.observe_permission(_CHECKPOINT, **_TIMEOUT)
        assert state['requests'].count(ROUTE) == 1


def test_second_permission_application_requires_adopted_predecessor_not_current_get(native_control):
    actions, before, state = prepare(native_control)
    actions.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    control, original, _, launch = native_control
    next_actions = TaskNativeActions(
        original._package,
        launch,
        control,
        action_scope=LaunchScope(launch.controller_ref, 92, 3, 'second-permission-change'),
    )
    current = {
        key: deepcopy(state['session'][key])
        for key in ('id', 'title', 'agent', 'model', 'metadata', 'permission')
    }
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
        next_actions.apply_permission(current, [RESET], _CHECKPOINT, **_TIMEOUT)
    assert tuple(state['requests']) == requests
    assert next_actions._read('permission', 'intent') is None
    assert state['requests'].count(ROUTE) == 1


@pytest.mark.parametrize('step', [1, 4])
@pytest.mark.parametrize('drop', [False, True])
def test_successor_permission_retains_original_creation_scope_for_read_only_recovery(
    native_control, step, drop
):
    actions, _, state = prepare(native_control)
    control, original, _, launch = native_control
    source = LaunchScope(launch.controller_ref, 90, step, 'successor-session-source')
    creator = TaskNativeActions(original._package, launch, control, action_scope=source)
    payload = _session_input(source)
    creator.create_session(payload, _CHECKPOINT, **_TIMEOUT)
    expected = {
        key: deepcopy(state['session'][key])
        for key in ('id', 'title', 'agent', 'model', 'metadata', 'permission')
    }
    with pytest.raises(TaskExecutionError):
        actions.apply_permission(expected, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    assert ROUTE not in state['requests']
    if drop:
        state['drops'].add(ROUTE)
        with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
            actions.apply_permission(
                expected, [RESET, READ], _CHECKPOINT, **_TIMEOUT, session_scope=source
            )
    else:
        actions.apply_permission(
            expected, [RESET, READ], _CHECKPOINT, **_TIMEOUT, session_scope=source
        )
    retained = actions._original('permission')
    assert retained['input']['session_scope'] == asdict(source)
    reopened = TaskNativeActions(original._package, launch, control, action_scope=actions._scope)
    before = len(state['requests'])
    result = reopened.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert result['permission'] == expected['permission'] + [RESET, READ]
    assert state['requests'][before:] == [('GET', '/session/' + _SESSION)]
    assert state['requests'].count(ROUTE) == 1


@pytest.mark.parametrize('field', ['task_id', 'instance_id'])
def test_successor_source_from_other_task_or_instance_cannot_authorize_patch(native_control, field):
    actions, _, state = prepare(native_control)
    control, original, _, launch = native_control
    source = LaunchScope(launch.controller_ref, 90, 4, 'successor-session-source')
    creator = TaskNativeActions(original._package, launch, control, action_scope=source)
    payload = _session_input(source)
    payload['metadata']['walle'][field] += 1
    creator.create_session(payload, _CHECKPOINT, **_TIMEOUT)
    expected = {
        key: deepcopy(state['session'][key])
        for key in ('id', 'title', 'agent', 'model', 'metadata', 'permission')
    }
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError, match='SESSION_SOURCE_DIFFERS'):
        actions.apply_permission(
            expected, [RESET, READ], _CHECKPOINT, **_TIMEOUT, session_scope=source
        )
    assert tuple(state['requests']) == requests
    assert actions._read('permission', 'intent') is None


@pytest.mark.parametrize('defect', ['controller', 'operation', 'step', 'type'])
def test_permission_creation_scope_is_program_owned_and_cannot_alias_apply_step(
    native_control, defect
):
    actions, before, state = prepare(native_control)
    launch = native_control[3]
    values = asdict(launch)
    if defect == 'controller':
        values['controller_ref'] = 'f' * 64
    elif defect == 'operation':
        values.update(operation_id=actions._scope.operation_id, step_no=1)
    elif defect == 'step':
        values.update(operation_id=90, step_no=3)
    source = values if defect == 'type' else LaunchScope(**values)
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError, match='SESSION_SOURCE'):
        actions.apply_permission(
            before, [RESET, READ], _CHECKPOINT, **_TIMEOUT, session_scope=source
        )
    assert tuple(state['requests']) == requests
    assert actions._read('permission', 'intent') is None


def _permission_current(state):
    return {
        key: deepcopy(state['session'][key])
        for key in ('id', 'title', 'agent', 'model', 'metadata', 'permission')
    }


def _next_permission(native_control, operation):
    control, original, _, launch = native_control
    return TaskNativeActions(
        original._package,
        launch,
        control,
        action_scope=LaunchScope(
            launch.controller_ref, operation, 3, 'permission-chain-' + str(operation)
        ),
    )


@pytest.mark.parametrize('drop', [False, True])
def test_exact_native_predecessors_allow_multiple_changes_and_recover_without_repatch(
    native_control, drop
):
    first, before, state = prepare(native_control)
    first.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    second = _next_permission(native_control, 92)
    second.apply_permission(
        _permission_current(state),
        [RESET],
        _CHECKPOINT,
        **_TIMEOUT,
        previous_applications=(first._scope,),
    )
    third = _next_permission(native_control, 93)
    expected = _permission_current(state)
    if drop:
        state['drops'].add(ROUTE)
        with pytest.raises(TaskExecutionError, match='RESULT_UNVERIFIED'):
            third.apply_permission(
                expected,
                [RESET, READ],
                _CHECKPOINT,
                **_TIMEOUT,
                previous_applications=(first._scope, second._scope),
            )
    else:
        third.apply_permission(
            expected,
            [RESET, READ],
            _CHECKPOINT,
            **_TIMEOUT,
            previous_applications=(first._scope, second._scope),
        )
    reopened = _next_permission(native_control, 93)
    requests = len(state['requests'])
    result = reopened.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert result['permission'] == expected['permission'] + [RESET, READ]
    assert state['requests'][requests:] == [('GET', '/session/' + _SESSION)]
    assert state['requests'].count(ROUTE) == 3


@pytest.mark.parametrize('defect', ['missing', 'reversed', 'duplicate', 'self', 'type'])
def test_predecessor_chain_cannot_skip_reorder_repeat_or_reference_itself(native_control, defect):
    first, before, state = prepare(native_control)
    first.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    second = _next_permission(native_control, 92)
    second.apply_permission(
        _permission_current(state),
        [RESET],
        _CHECKPOINT,
        **_TIMEOUT,
        previous_applications=(first._scope,),
    )
    third = _next_permission(native_control, 93)
    invalid = {
        'missing': (second._scope,),
        'reversed': (second._scope, first._scope),
        'duplicate': (first._scope, first._scope),
        'self': (first._scope, third._scope),
        'type': [first._scope, second._scope],
    }[defect]
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError):
        third.apply_permission(
            _permission_current(state),
            [RESET, READ],
            _CHECKPOINT,
            **_TIMEOUT,
            previous_applications=invalid,
        )
    assert tuple(state['requests']) == requests
    assert third._read('permission', 'intent') is None


@pytest.mark.parametrize('phase', ['intent', 'ack'])
@pytest.mark.parametrize('defect', ['missing', 'corrupt', 'different'])
def test_predecessor_damage_blocks_reconciliation_before_http_and_can_restore_same_intent(
    native_control, monkeypatch, phase, defect
):
    first, before, state = prepare(native_control)
    first.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    second = _next_permission(native_control, 92)
    state['drops'].add(ROUTE)
    with pytest.raises(TaskExecutionError):
        second.apply_permission(
            _permission_current(state),
            [RESET],
            _CHECKPOINT,
            **_TIMEOUT,
            previous_applications=(first._scope,),
        )
    read = TaskNativeActions._read

    def damaged(self, action, stage):
        raw = read(self, action, stage)
        if self._scope == first._scope and action == 'permission' and stage == phase:
            if defect == 'missing':
                return None
            if defect == 'corrupt':
                return b'{'
            value = json.loads(raw)
            if phase == 'ack':
                value['result']['permission'] = []
            else:
                value['input']['before']['title'] = 'wrong original predecessor'
            return json.dumps(value).encode()
        return raw

    monkeypatch.setattr(TaskNativeActions, '_read', damaged)
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError):
        second.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert tuple(state['requests']) == requests
    assert second._read('permission', 'ack') is None
    monkeypatch.setattr(TaskNativeActions, '_read', read)
    second.observe_permission(_CHECKPOINT, **_TIMEOUT)
    assert state['requests'].count(ROUTE) == 2


@pytest.mark.parametrize('recover', [False, True])
def test_stop_during_predecessor_read_never_reaches_http_or_new_intent(
    native_control, monkeypatch, recover
):
    first, before, state = prepare(native_control)
    first.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    second = _next_permission(native_control, 92)
    expected = _permission_current(state)
    if recover:
        state['drops'].add(ROUTE)
        with pytest.raises(TaskExecutionError):
            second.apply_permission(
                expected,
                [RESET],
                _CHECKPOINT,
                **_TIMEOUT,
                previous_applications=(first._scope,),
            )
    stopping = False
    read = TaskNativeActions._read

    def reading(self, action, phase):
        nonlocal stopping
        raw = read(self, action, phase)
        if self._scope == first._scope and action == 'permission' and phase == 'intent':
            stopping = True
        return raw

    def checkpoint():
        if stopping:
            raise TaskExecutionError('STOP_REQUESTED')

    monkeypatch.setattr(TaskNativeActions, '_read', reading)
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError, match='STOP_REQUESTED'):
        if recover:
            second.observe_permission(checkpoint, **_TIMEOUT)
        else:
            second.apply_permission(
                expected,
                [RESET],
                checkpoint,
                **_TIMEOUT,
                previous_applications=(first._scope,),
            )
    assert tuple(state['requests']) == requests
    assert (second._read('permission', 'intent') is not None) is recover
    assert second._read('permission', 'ack') is None
    monkeypatch.setattr(TaskNativeActions, '_read', read)
    if recover:
        second.observe_permission(_CHECKPOINT, **_TIMEOUT)
        assert state['requests'].count(ROUTE) == 2


def test_explicit_native_history_becomes_session_expected_without_rewriting_creation(
    native_control,
):
    first, before, state = prepare(native_control)
    first.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    control, original, _, launch = native_control
    created = original._read('session', 'intent')
    accepted = TaskNativeActions(
        original._package, launch, control, permission_history=(first._scope,)
    )
    expected = accepted.expected_session_policy(_CHECKPOINT)
    assert expected['permission'] == before['permission'] + [RESET, READ]
    expected['permission'].clear()
    assert accepted.expected_session_policy(_CHECKPOINT)['permission']
    with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
        original.observe_session(_CHECKPOINT, **_TIMEOUT)
    assert accepted.observe_session(_CHECKPOINT, **_TIMEOUT)['id'] == before['id']
    payload = accepted.initial_payload(
        'walle-code', 'walle', 'walle-code', ['fixed after native change']
    )
    accepted.send_initial(before['id'], payload, _CHECKPOINT, **_TIMEOUT)
    assert state['requests'].count(('POST', '/session/' + _SESSION + '/prompt_async')) == 1
    assert original._read('session', 'intent') == created
    assert state['requests'].count(ROUTE) == 1
    with pytest.raises(TaskExecutionError, match='ALREADY_HAS_PERMISSION_HISTORY'):
        accepted.prepare_session(_session_input(launch))


@pytest.mark.parametrize('phase', ['intent', 'ack'])
def test_session_history_requires_complete_original_permission_before_http(
    native_control, monkeypatch, phase
):
    first, before, state = prepare(native_control)
    first.apply_permission(before, [RESET, READ], _CHECKPOINT, **_TIMEOUT)
    control, original, _, launch = native_control
    accepted = TaskNativeActions(
        original._package, launch, control, permission_history=(first._scope,)
    )
    read = TaskNativeActions._read

    def missing(self, action, stage):
        if self._scope == first._scope and action == 'permission' and stage == phase:
            return None
        return read(self, action, stage)

    monkeypatch.setattr(TaskNativeActions, '_read', missing)
    requests = tuple(state['requests'])
    with pytest.raises(TaskExecutionError):
        accepted.observe_session(_CHECKPOINT, **_TIMEOUT)
    assert tuple(state['requests']) == requests
