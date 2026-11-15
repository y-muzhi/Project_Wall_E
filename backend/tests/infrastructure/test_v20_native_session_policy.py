"""Original static session policy, reused by production turn entry points."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.app.code_tasks.task_instance_driver import TaskInstanceDriver
from backend.app.code_tasks.task_model_ingress import ModelWindow
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.tests.infrastructure import test_v20_opencode_instance_control as native

native_control = native.native_control


@pytest.mark.parametrize('lost', [False, True])
@pytest.mark.parametrize('field', ['title', 'agent', 'model', 'permission'])
def test_observed_session_cannot_admit_policy_drift_or_save_false_ack(native_control, lost, field):
    _, actions, state, scope = native_control
    if lost:
        state['drops'].add(('POST', '/session'))
        with pytest.raises(TaskExecutionError):
            actions.create_session(
                native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT
            )
    else:
        actions.create_session(native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT)
    acknowledged = actions._read('session', 'ack')
    correct = deepcopy(state['session'][field])
    state['session'][field] = (
        [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
        if field == 'permission'
        else 'foreign'
    )
    before = tuple(state['requests'])
    with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
        actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)
    assert actions._read('session', 'ack') == acknowledged
    assert all(method == 'GET' for method, _ in state['requests'][len(before) :])
    state['session'][field] = correct
    assert actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)['id'] == native._SESSION
    assert state['requests'].count(('POST', '/session')) == 1


def configure_driver(driver, owner, state):
    """Install a fixed offline config/provider group; HTTP still reads actual fixture state."""
    from hashlib import sha256

    from backend.app.code_tasks.task_initial_configuration import InitialConfigurationObservation
    from backend.app.code_tasks.task_initial_prompt import (
        CP20_SYSTEM,
        NativeCodingPolicy,
        checked_coding_configuration,
    )
    from backend.app.infrastructure.opencode_model_credential import MODEL_BEARER_ENV
    from backend.app.infrastructure.runtime_launch_journal import _bytes

    policy = NativeCodingPolicy('walle-code', (('*', '*', 'deny'),))
    credential = SimpleNamespace(
        base_url='http://127.0.0.1:19117/internal/fixture/v1',
        _secret='isolated-no-provider-secret',
        environment=lambda: {MODEL_BEARER_ENV: 'isolated-no-provider-secret'},
    )
    models = {'walle-code': {'id': 'walle-code'}, 'walle-compaction': {'id': 'walle-compaction'}}
    configuration = {
        'agent': {'walle-code': {'prompt': CP20_SYSTEM, 'model': 'walle/walle-code'}},
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
    providers = {'providers': [{'id': 'walle', 'models': deepcopy(models)}]}
    state['overrides']['/config'] = configuration
    state['overrides']['/config/providers'] = providers
    fixed = checked_coding_configuration((configuration, providers), credential, policy)
    owner.configuration = InitialConfigurationObservation(
        'opencode-bundle:sha256:' + 'a' * 64,
        'e' * 64,
        sha256(_bytes(fixed)).hexdigest(),
        policy.agent,
    )
    owner.gateway._credential = credential
    driver._installation = SimpleNamespace(coding=policy)


def production_driver(fixture, monkeypatch):
    _, actions, _, launch = fixture
    actions.create_session(native._session_input(launch), native._CHECKPOINT, **native._TIMEOUT)
    previous = ModelWindow(10, 12, 1, 11, native._SESSION, 3, 'msg_original')
    scope = SimpleNamespace(
        task_id=10,
        instance_id=12,
        control_generation=1,
        session_id=11,
        query_timeout_seconds=2,
        send_timeout_seconds=2,
        metadata=lambda: native._session_input(launch)['metadata'],
    )
    queues = []

    def queue(old, new):
        assert old == previous
        queues.append(new)

    owner = SimpleNamespace(gateway=SimpleNamespace(_window=previous, queue_continuation=queue))
    driver = object.__new__(TaskInstanceDriver)
    configure_driver(driver, owner, fixture[2])
    monkeypatch.setattr(driver, '_continuation_owner', lambda *args: owner)
    monkeypatch.setattr(driver, '_continuation_guard', lambda *args: 'a' * 64)

    @contextmanager
    def original_actions(actual_owner, actual_scope):
        assert actual_owner is owner and actual_scope is scope
        yield actions

    monkeypatch.setattr(driver, '_native_actions', original_actions)
    return driver, scope, previous, queues


@pytest.mark.parametrize('entry', ['resume', 'capture', 'archive'])
@pytest.mark.parametrize('field', ['agent', 'model', 'permission'])
def test_production_turn_entries_refuse_drift_before_reading_turn_or_building_message(
    native_control, monkeypatch, entry, field
):
    _, _, state, _ = native_control
    driver, scope, previous, queues = production_driver(native_control, monkeypatch)
    state['session'][field] = [] if field == 'permission' else 'foreign'
    if field == 'permission':
        state['session'][field] = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    start = len(state['requests'])
    with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
        if entry == 'resume':
            driver.continuation_payload(scope, previous, 'fixture', native._CHECKPOINT)
        elif entry == 'capture':
            driver.observe_capture_turn(scope, previous, 'fixture', native._CHECKPOINT)
        else:
            driver.repair_session_archived_at(scope, previous, 'fixture', native._CHECKPOINT)
    assert state['requests'][start:] == [('GET', '/session/' + native._SESSION)]
    assert not queues


@pytest.mark.parametrize('mode', ['success', 'drift', 'stop', 'mutate', 'wrong-message'])
def test_final_continuation_dispatch_rechecks_before_queue_and_freezes_wire(
    native_control, monkeypatch, mode
):
    _, actions, state, _ = native_control
    driver, scope, previous, queues = production_driver(native_control, monkeypatch)
    payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    window = ModelWindow(10, 12, 1, 11, native._SESSION, 77, payload['messageID'])
    original_id = payload['messageID']
    if mode == 'drift':
        state['session']['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    elif mode == 'wrong-message':
        payload['messageID'] = 'msg_foreign'

    def checkpoint():
        if mode == 'stop':
            raise TaskExecutionError('FIXTURE_STOP')
        if mode == 'mutate':
            payload['parts'][0]['text'] = 'changed by caller'
            payload['messageID'] = 'msg_mutated'

    start = len(state['requests'])
    if mode in ('drift', 'stop', 'wrong-message'):
        with pytest.raises(TaskExecutionError):
            driver.dispatch_continuation(scope, previous, window, 'fixture', payload, checkpoint)
        assert not queues
        assert all(method == 'GET' for method, _ in state['requests'][start:])
    else:
        driver.dispatch_continuation(scope, previous, window, 'fixture', payload, checkpoint)
        assert queues == [window]
        assert state['message']['info']['id'] == original_id
        assert state['message']['parts'][0]['text'] == 'fixed'
        assert state['requests'][start:] == [
            ('GET', '/session/' + native._SESSION),
            ('GET', '/config'),
            ('GET', '/config/providers'),
            ('GET', '/session/' + native._SESSION),
            ('POST', '/session/' + native._SESSION + '/prompt_async'),
        ]


@pytest.mark.parametrize('field', ['title', 'agent', 'model', 'permission'])
def test_initial_prompt_reads_live_policy_before_intent_or_post(native_control, field):
    _, actions, state, scope = native_control
    actions.create_session(native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT)
    payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    correct = deepcopy(state['session'][field])
    state['session'][field] = (
        [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
        if field == 'permission'
        else 'foreign'
    )
    before = len(state['requests'])
    with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
        actions.send_initial(native._SESSION, payload, native._CHECKPOINT, **native._TIMEOUT)
    assert actions._read('initial', 'intent') is None
    assert state['requests'][before:] == [('GET', '/session/' + native._SESSION)]
    state['session'][field] = correct
    actions.send_initial(native._SESSION, payload, native._CHECKPOINT, **native._TIMEOUT)
    assert state['requests'].count(('POST', '/session/' + native._SESSION + '/prompt_async')) == 1


@pytest.mark.parametrize('action', ['session', 'initial'])
def test_positive_receipt_capacity_is_reserved_before_query_or_dispatch(
    native_control, monkeypatch, action
):
    from backend.app.code_tasks import task_native_actions as module
    from backend.app.infrastructure.runtime_launch_journal import _bytes

    _, actions, state, scope = native_control
    if action == 'session':
        payload = native._session_input(scope)
        fixed = payload
    else:
        actions.create_session(native._session_input(scope), native._CHECKPOINT, **native._TIMEOUT)
        payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
        fixed = {'session_id': native._SESSION, 'payload': payload}
    intent = {'scope': scope.key, 'action': action, 'input': fixed}
    limit = len(_bytes(intent))
    before = tuple(state['requests'])
    monkeypatch.setattr(module, '_LIMIT', limit)
    with pytest.raises(TaskExecutionError, match='RECORD_TOO_LARGE'):
        if action == 'session':
            actions.create_session(payload, native._CHECKPOINT, **native._TIMEOUT)
        else:
            actions.send_initial(native._SESSION, payload, native._CHECKPOINT, **native._TIMEOUT)
    assert tuple(state['requests']) == before
    assert actions._read(action, 'intent') is None


@pytest.mark.parametrize('entry', ['dispatch', 'resume', 'capture', 'archive'])
@pytest.mark.parametrize('fault', ['config', 'providers', 'digest', 'missing', 'during-read'])
def test_live_configuration_group_refuses_drift_before_turn_or_queue(
    native_control, monkeypatch, entry, fault
):
    _, actions, state, _ = native_control
    driver, scope, previous, queues = production_driver(native_control, monkeypatch)
    if fault == 'config':
        state['overrides']['/config']['agent']['walle-code']['prompt'] = 'foreign'
    elif fault == 'providers':
        state['overrides']['/config/providers']['providers'][0]['models'].pop('walle-compaction')
    elif fault == 'digest':
        state['overrides']['/config']['plugin'] = ['unapproved']
    elif fault == 'missing':
        owner = driver._continuation_owner(scope, 'fixture')
        owner.configuration = None
    else:
        original = actions._control.configuration

        def change_during_read(*args, **kwargs):
            result = original(*args, **kwargs)
            state['session']['permission'] = [
                {'permission': '*', 'pattern': '*', 'action': 'allow'}
            ]
            return result

        monkeypatch.setattr(actions._control, 'configuration', change_during_read)
    payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    window = ModelWindow(10, 12, 1, 11, native._SESSION, 77, payload['messageID'])
    start = len(state['requests'])
    with pytest.raises(TaskExecutionError):
        if entry == 'dispatch':
            driver.dispatch_continuation(
                scope, previous, window, 'fixture', payload, native._CHECKPOINT
            )
        elif entry == 'resume':
            driver.continuation_payload(scope, previous, 'fixture', native._CHECKPOINT)
        elif entry == 'capture':
            driver.observe_capture_turn(scope, previous, 'fixture', native._CHECKPOINT)
        else:
            driver.repair_session_archived_at(scope, previous, 'fixture', native._CHECKPOINT)
    assert not queues
    assert all(method == 'GET' for method, _ in state['requests'][start:])
    assert not any('/message' in path for _, path in state['requests'][start:])


def test_final_dispatch_rejects_changed_guard_after_group_read(native_control, monkeypatch):
    _, actions, state, _ = native_control
    driver, scope, previous, queues = production_driver(native_control, monkeypatch)
    guards = iter(['a' * 64, 'b' * 64])
    monkeypatch.setattr(driver, '_continuation_guard', lambda *args: next(guards))
    payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    window = ModelWindow(10, 12, 1, 11, native._SESSION, 77, payload['messageID'])
    start = len(state['requests'])
    with pytest.raises(TaskExecutionError, match='GUARD_DIFFERS'):
        driver.dispatch_continuation(
            scope, previous, window, 'fixture', payload, native._CHECKPOINT
        )
    assert not queues
    assert all(method == 'GET' for method, _ in state['requests'][start:])


@pytest.mark.parametrize('successor', [False, True])
@pytest.mark.parametrize('mode', ['success', 'config', 'providers', 'guard', 'mutate', 'capacity'])
def test_initial_and_successor_dispatch_check_group_before_queue(
    native_control, monkeypatch, successor, mode
):
    from hashlib import sha256

    from backend.app.code_tasks.task_start_session import StartSessionScope, SuccessorSessionScope
    from backend.app.infrastructure.runtime_launch_journal import _bytes

    _, actions, state, launch = native_control
    scope = StartSessionScope(3, 10, 12, 11, 1, 2, 20, 21, launch.nonce, 22, 2, 2)
    if successor:
        scope = SuccessorSessionScope(
            **{**scope.__dict__, 'control_generation': 2},
            role='FRONTEND',
            transition_operation_id=77,
            transition_nonce='b' * 32,
            original_launch_generation=1,
        )
    if successor:
        from backend.app.code_tasks.task_native_actions import TaskNativeActions
        from backend.app.infrastructure.runtime_launch_journal import LaunchScope

        actions = TaskNativeActions(
            actions._package,
            launch,
            actions._control,
            action_scope=LaunchScope(launch.controller_ref, 77, 4, 'b' * 32),
        )
    request = native._session_input(launch)
    request['metadata'] = scope.metadata()
    actions.create_session(request, native._CHECKPOINT, **native._TIMEOUT)
    previous = ModelWindow(10, 12, 1, 9, 'ses_previous', 3, 'msg_previous')
    queues = []
    owner = SimpleNamespace(
        gateway=SimpleNamespace(
            queue=lambda *args: queues.append(args),
            queue_successor=lambda *args: queues.append(args),
        )
    )
    driver = object.__new__(TaskInstanceDriver)
    configure_driver(driver, owner, state)
    monkeypatch.setattr(driver, '_session_owner', lambda *args: owner)
    monkeypatch.setattr(driver, 'gateway_reference', lambda *args: 'fixture')
    guards = iter(['a' * 64, ('b' if mode == 'guard' else 'a') * 64])
    monkeypatch.setattr(driver, '_continuation_guard', lambda *args: next(guards))

    @contextmanager
    def original_actions(actual_owner, actual_scope=None):
        assert actual_owner is owner and actual_scope in (None, scope)
        yield actions

    monkeypatch.setattr(driver, '_native_actions', original_actions)
    payload = actions.initial_payload('walle-code', 'walle', 'walle-code', ['fixed'])
    original_id = payload['messageID']
    original = {
        'gateway_credential_ref': 'fixture',
        'payload_sha256': sha256(_bytes(payload)).hexdigest(),
        'native_session_id': native._SESSION,
    }
    if mode == 'config':
        state['overrides']['/config']['plugin'] = ['foreign']
    elif mode == 'providers':
        state['overrides']['/config/providers']['providers'] = []
    elif mode == 'capacity':
        from backend.app.code_tasks import task_native_actions

        monkeypatch.setattr(task_native_actions, '_LIMIT', 1)

    def checkpoint():
        if mode == 'mutate':
            payload['parts'][0]['text'] = 'foreign'
            payload['messageID'] = 'msg_foreign'
            original['native_session_id'] = 'ses_foreign'
            original['gateway_credential_ref'] = 'foreign'
            original['payload_sha256'] = '0' * 64

    before = len(state['requests'])

    def send():
        if successor:
            return driver.send_successor(scope, previous, original, payload, checkpoint)
        return driver.send_initial(scope, original, payload, checkpoint)

    if mode in ('config', 'providers', 'guard', 'capacity'):
        with pytest.raises(TaskExecutionError):
            send()
        assert not queues
        assert actions._read('initial', 'intent') is None
        assert all(method == 'GET' for method, _ in state['requests'][before:])
        if mode == 'capacity':
            assert len(state['requests']) == before
    else:
        assert send() == original_id
        assert len(queues) == 1
        queued = queues[0][-1]
        assert queued['native_session_id'] == native._SESSION
        assert queued['gateway_credential_ref'] == 'fixture'
        assert state['message']['parts'][0]['text'] == 'fixed'
        assert (
            state['requests'][before:].count(
                ('POST', '/session/' + native._SESSION + '/prompt_async')
            )
            == 1
        )
        assert ('GET', '/config/providers') in state['requests'][before:]


@pytest.mark.parametrize(
    'mode', ['success', 'config', 'capacity', 'guard', 'recover', 'recovery-drift']
)
def test_created_session_requires_live_group_and_recovery_never_posts(
    native_control, monkeypatch, mode
):
    from backend.app.code_tasks.task_start_session import StartSessionScope

    _, actions, state, launch = native_control
    scope = StartSessionScope(3, 10, 12, 11, 1, 2, 20, 21, launch.nonce, 22, 2, 2)
    driver = object.__new__(TaskInstanceDriver)
    owner = SimpleNamespace(gateway=SimpleNamespace())
    configure_driver(driver, owner, state)
    monkeypatch.setattr(driver, '_session_owner', lambda *args: owner)
    # This existing group fixture isolates HTTP/group behavior. Compilation and
    # persisted grant inputs have their own real NTFS/Schema200 coverage.
    monkeypatch.setattr(
        driver, '_compile_session_policy', lambda *args: driver._installation.coding
    )
    guards = []

    def guard(*args):
        guards.append(True)
        return ('b' if mode == 'guard' and len(guards) > 1 else 'a') * 64

    monkeypatch.setattr(driver, '_continuation_guard', guard)

    @contextmanager
    def original_actions(actual_owner, actual_scope):
        assert actual_owner is owner and actual_scope is scope
        yield actions

    monkeypatch.setattr(driver, '_native_actions', original_actions)
    if mode in ('recover', 'recovery-drift'):
        request = {
            'title': 'WALL-E Coding 10 BACKEND',
            'agent': 'walle-code',
            'model': {'id': 'walle-code', 'providerID': 'walle'},
            'permission': driver._installation.coding.permission(),
            'metadata': scope.metadata(),
        }
        actions.create_session(request, native._CHECKPOINT, **native._TIMEOUT)
    if mode in ('config', 'recovery-drift'):
        state['overrides']['/config']['plugin'] = ['unapproved']
    elif mode == 'capacity':
        from backend.app.code_tasks import task_native_actions

        monkeypatch.setattr(task_native_actions, '_LIMIT', 1)
    start = len(state['requests'])
    if mode in ('success', 'recover'):
        if mode == 'success':
            assert driver.create_session(scope, native._CHECKPOINT).native_id == native._SESSION
        else:
            assert driver.observe_created_session(scope, native._CHECKPOINT) == native._SESSION
        assert ('GET', '/config/providers') in state['requests'][start:]
    else:
        with pytest.raises(TaskExecutionError):
            if mode == 'recovery-drift':
                driver.observe_created_session(scope, native._CHECKPOINT)
            else:
                driver.create_session(scope, native._CHECKPOINT)
        assert not any(method == 'POST' for method, _ in state['requests'][start:])
        if mode == 'capacity':
            assert len(state['requests']) == start
    if mode in ('recover', 'recovery-drift'):
        assert all(method == 'GET' for method, _ in state['requests'][start:])


@pytest.mark.parametrize('action', ['question', 'allow', 'deny'])
@pytest.mark.parametrize('fault', ['config', 'providers', 'session'])
def test_issue_continuation_requires_group_but_denial_remains_available(
    native_control, monkeypatch, action, fault
):
    from queue import Queue

    control, _, state, _ = native_control
    driver, scope, _, _ = production_driver(native_control, monkeypatch)
    owner = driver._continuation_owner(scope, 'fixture')
    owner.credential = control._credential
    owner.workspace = control._workspace
    monkeypatch.setattr(driver, '_session_owner', lambda *args: owner)
    state['events'] = Queue()
    if fault == 'config':
        state['overrides']['/config']['plugin'] = ['unapproved']
    elif fault == 'providers':
        state['overrides']['/config/providers']['providers'] = []
    else:
        state['session']['permission'] = [{'permission': '*', 'pattern': '*', 'action': 'allow'}]
    original = {
        'id': 'per_selected',
        'sessionID': native._SESSION,
        'permission': 'read',
        'patterns': ['existing.txt'],
        'always': ['*'],
        'metadata': {},
    }
    claims, records = [], []
    start = len(state['requests'])

    def send():
        if action == 'question':
            return driver.send_question_response(
                scope, native._SESSION, 'que_original', [['fixed']], native._CHECKPOINT
            )
        return driver.decide_native_permission(
            scope,
            (
                native._SESSION,
                original,
                ('per_selected',),
                'reject' if action == 'deny' else 'once',
            ),
            native._CHECKPOINT,
            lambda: claims.append(True),
            lambda identity, evidence: records.append((identity, evidence)),
        )

    if action == 'deny':
        state['permission_events'] = [('evt_denied', native._SESSION, 'per_selected', 'reject')]
        send()
        assert claims == [True] and len(records) == 1
        assert ('POST', '/permission/per_selected/reply') in state['requests'][start:]
        assert not any(path.startswith('/config') for _, path in state['requests'][start:])
    else:
        with pytest.raises(
            TaskExecutionError, match='POLICY_DIFFERS|PROVIDER_DIFFERS|CONFIGURATION_DIFFERS'
        ):
            send()
        assert not claims and not records
        assert all(method == 'GET' for method, _ in state['requests'][start:])


def test_question_answer_snapshot_survives_new_configuration_checkpoints(
    native_control, monkeypatch
):
    from queue import Queue

    control, _, state, _ = native_control
    driver, scope, _, _ = production_driver(native_control, monkeypatch)
    owner = driver._continuation_owner(scope, 'fixture')
    owner.credential = control._credential
    monkeypatch.setattr(driver, '_session_owner', lambda *args: owner)
    state['events'] = Queue()
    answers = [['fixed first'], ['fixed second']]

    def checkpoint():
        answers[0][0] = 'caller mutation'
        answers.append(['foreign third'])

    result = driver.send_question_response(
        scope, native._SESSION, 'que_original', answers, checkpoint
    )
    assert result == {'source': 'HTTP_200'}
    assert state['reply_body'] == {'answers': [['fixed first'], ['fixed second']]}
    assert state['requests'].count(('POST', '/question/que_original/reply')) == 1


@pytest.mark.parametrize('reply', ['once', 'reject'])
def test_permission_snapshot_keeps_original_object_and_denial_cohort(
    native_control, monkeypatch, reply
):
    from pathlib import Path
    from queue import Queue

    control, _, state, _ = native_control
    driver, scope, _, _ = production_driver(native_control, monkeypatch)
    owner = driver._continuation_owner(scope, 'fixture')
    owner.workspace = control._workspace
    monkeypatch.setattr(driver, '_session_owner', lambda *args: owner)
    state['events'] = Queue()
    state['permission_events'] = [('evt_denied', native._SESSION, 'per_selected', 'reject')]
    with (Path(control._workspace.canonical_path) / 'existing.txt').open('xb') as stream:
        stream.write(b'original fixture')
    original = {
        'id': 'per_selected',
        'sessionID': native._SESSION,
        'permission': 'read',
        'patterns': ['existing.txt'],
        'always': ['*'],
        'metadata': {},
    }
    candidates = ['per_selected']
    claims, records = [], []

    def checkpoint():
        original['patterns'][0] = 'foreign.txt'
        if 'per_foreign' not in candidates:
            candidates.append('per_foreign')

    driver.decide_native_permission(
        scope,
        (native._SESSION, original, candidates, reply),
        checkpoint,
        lambda: claims.append(True),
        lambda identity, evidence: records.append((identity, evidence)),
    )
    assert claims == [True] and [identity for identity, _ in records] == ['per_selected']
    assert state['requests'].count(('POST', '/permission/per_selected/reply')) == 1
