"""Real C39 API/Schema200, NTFS and native HTTP; OS/Guard and model remain explicit fixtures."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.code_tasks.authorizations import project_grant
from backend.app.code_tasks.task_configuration_live_records import stored_profile_content
from backend.app.code_tasks.task_instance_driver import TaskInstanceDriver
from backend.app.code_tasks.task_live_configuration import advance_live_configuration
from backend.app.code_tasks.task_native_policy import compile_managed_native_policy
from backend.app.code_tasks.task_start_session import original_active_session_scope
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.tests.code_tasks import test_task_native_configuration as source
from backend.tests.infrastructure import test_v20_opencode_instance_control as native
from backend.tests.infrastructure.test_v20_native_session_policy import configure_driver

package = source.package
service = source.service
isolated_readiness = source.isolated_readiness
original_instance = source.original_instance
ready = source.ready
fixed_price = source.fixed_price
opened = source.opened
idle_task = source.idle_task
versioned_runtime_fixture = source.versioned_runtime_fixture
managed_roots = source.managed_roots
native_task = source.native_task
native_control = native.native_control


@pytest.fixture
def native_creation_scope(native_task, monkeypatch):
    database, _, _, _, _, task_id, _, _, _ = native_task
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        session = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (task['active_session_id'],)
        ).fetchone()
        scope = original_active_session_scope(connection, task, session)
        monkeypatch.setattr(native, '_SESSION', session['native_session_id'])
    return LaunchScope('a' * 64, scope.operation_id, 4, scope.nonce)


def configured_driver(fixture, native_control, monkeypatch):
    database, _, _, ingress, _, task_id, guard_receipt, _, _ = fixture
    control, actions, state, launch = native_control
    basis_path = Path(control._workspace.canonical_path).with_name('basis')
    basis_path.mkdir()
    with LocalPathGuard(basis_path, directory=True) as guard:
        basis = guard.verify()
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        session = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (task['active_session_id'],)
        ).fetchone()
        scope = original_active_session_scope(connection, task, session)
        profile = stored_profile_content(
            connection.execute(
                'SELECT * FROM code_execution_profile_versions WHERE id=?',
                (task['execution_profile_version_id'],),
            ).fetchone()
        )
        grant = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (task['authorization_id'],)
            ).fetchone()
        )['scope']
    compiled = compile_managed_native_policy(
        profile,
        grant,
        agent='walle-code',
        workspace=control._workspace,
        basis=basis,
        checkpoint=native._CHECKPOINT,
    )
    actions.create_session(
        {
            'title': 'WALL-E Coding original managed session',
            'agent': compiled.policy.agent,
            'model': {'id': 'walle-code', 'providerID': 'walle'},
            'metadata': scope.metadata(),
            'permission': compiled.policy.permission(),
        },
        native._CHECKPOINT,
        **native._TIMEOUT,
    )
    window = ingress.window
    state['overrides']['/session/' + native._SESSION + '/message'] = [
        {
            'info': {
                'id': window.trigger_message_id,
                'sessionID': native._SESSION,
                'role': 'user',
                'time': {'created': 20},
            },
            'parts': [],
        },
        {
            'info': {
                'id': 'msg_nativeConfigurationEnd',
                'sessionID': native._SESSION,
                'role': 'assistant',
                'parentID': window.trigger_message_id,
                'time': {'created': 21, 'completed': 25},
                'finish': 'stop',
            },
            'parts': [],
        },
    ]
    state['overrides']['/session/status'] = {}
    state['overrides']['/question'] = []
    state['overrides']['/permission'] = []
    owner = SimpleNamespace(
        workspace=control._workspace,
        basis=basis,
        scratch=None,
        credential=control._credential,
        gateway=SimpleNamespace(_window=window),
    )

    class Runtime:
        _original = SimpleNamespace(scope=launch)

        @contextmanager
        def running_control(self, credential, workspace):
            assert credential is control._credential and workspace == control._workspace
            yield control

    owner.launch = Runtime()
    driver = object.__new__(TaskInstanceDriver)
    driver._database = database
    driver._parent = actions._package
    configure_driver(driver, owner, state)
    monkeypatch.setattr(driver, '_session_owner', lambda *args: owner)
    monkeypatch.setattr(driver, '_continuation_owner', lambda *args: owner)
    # Authenticated Guard/Job/OS admission is a named fixture boundary here.
    monkeypatch.setattr(driver, '_continuation_guard', lambda *args: guard_receipt)
    return driver, owner, scope, state, actions


@pytest.mark.parametrize(
    'native_control',
    [
        {'directory_role': 'workspace', 'scope_fixture': 'native_creation_scope'},
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    'mode',
    [
        'success',
        'third-reply',
        'fourth-read',
        'stop-after-patch',
        'pending',
        'unpublished-intent',
        'final-configuration-drift',
        'final-permission-drift',
        'basis-identity-drift',
        'control-between-native',
        'budget-after-patch',
    ],
)
def test_native_read_change_from_real_api_through_original_patch_and_adopted_session(
    native_task, native_control, monkeypatch, mode
):
    driver, owner, scope, state, original = configured_driver(
        native_task, native_control, monkeypatch
    )
    database, runtime, client, _, _, task_id, _, _, _ = native_task
    route = ('PATCH', '/session/' + native._SESSION)
    proposal = source.target(native_task, basis=False)
    reply = source.accept(native_task, proposal)
    assert reply.status_code == 202, reply.text
    operation = reply.json()['data']['operation_id']
    errors = []
    native_observations = 0
    configuration_before = None
    permission_before = None
    basis_before = owner.basis
    for name in ('prepare_native_configuration', 'apply_native_configuration'):
        method = getattr(driver, name)

        def observed(*args, _method=method, _name=name, **kwargs):
            nonlocal native_observations, configuration_before, permission_before
            if _name == 'apply_native_configuration':
                native_observations += 1
                if mode == 'unpublished-intent' and kwargs['dispatch']:
                    raise TaskExecutionError('ISOLATED_INTERRUPT_BEFORE_PERMISSION_INTENT')
                if native_observations == 2:
                    if mode == 'final-configuration-drift':
                        configuration_before = deepcopy(state['overrides']['/config'])
                        state['overrides']['/config']['agent']['walle-code']['prompt'] = 'drift'
                    elif mode == 'final-permission-drift':
                        permission_before = deepcopy(state['session']['permission'])
                        state['session']['permission'] = [
                            {'permission': '*', 'pattern': '*', 'action': 'allow'}
                        ]
                    elif mode == 'basis-identity-drift':
                        owner.basis = replace(owner.basis, file_id='0' * 32)
                if mode == 'fourth-read' and native_observations == 2:
                    state['drops'].add(('GET', '/session/' + native._SESSION))
            try:
                result = _method(*args, **kwargs)
                if mode == 'budget-after-patch' and kwargs.get('dispatch') is True:
                    detail = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']
                    increased = client.post(
                        f'/api/v1/code-tasks/{task_id}/budget',
                        json={
                            'expected_state_version': detail['state_version'],
                            'new_budget_limit_cny': '0.200000',
                            'reason': '原生PATCH后独立增加预算',
                        },
                        headers={'Idempotency-Key': str(uuid4())},
                    )
                    assert increased.status_code == 200, increased.text
                if mode == 'stop-after-patch' and kwargs.get('dispatch') is True:
                    detail = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']
                    stopped = source.live.stop(client, task_id, detail['state_version'])
                    assert stopped.status_code == 202, stopped.text
                return result
            except Exception as error:
                code = str(error)
                errors.append(
                    (_name, type(error).__name__, code if code.isupper() else 'unclassified')
                )
                raise

        monkeypatch.setattr(driver, name, observed)
    if mode == 'pending':
        state['overrides']['/question'] = [{'id': 'que_stillWaiting', 'sessionID': native._SESSION}]
    if mode == 'third-reply':
        state['drops'].add(route)
    advanced = advance_live_configuration(runtime, driver, cancelled=lambda: False)
    assert advanced is (mode not in ('stop-after-patch', 'budget-after-patch'))
    response = client.get(f'/api/v1/code-operations/{operation}')
    assert response.status_code == 200, response.text
    current = response.json()['data']
    if mode == 'budget-after-patch':
        assert current['status'] == 'RUNNING', current
        assert [step['status'] for step in current['steps']] == [
            'SUCCEEDED',
            'SUCCEEDED',
            'RUNNING',
            'PENDING',
        ]
        detail = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']
        assert detail['authorization_id'] == proposal[0]['authorization_id']
        assert detail['budget']['limit_cny'] == '0.200000'
        assert state['requests'].count(route) == 1
        assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
        current = client.get(f'/api/v1/code-operations/{operation}').json()['data']
        detail = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']
        assert detail['budget']['limit_cny'] == '0.200000'
    if mode == 'pending':
        assert current['status'] == 'UNKNOWN'
        assert state['requests'].count(route) == 0
        assert errors == [
            (
                'prepare_native_configuration',
                'TaskExecutionError',
                'ORIGINAL_OPENCODE_INSTANCE_STILL_WAITING',
            )
        ]
        return
    if mode == 'stop-after-patch':
        assert current['status'] == 'RUNNING', current
        assert state['requests'].count(route) == 1
        with database.transaction() as connection:
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            assert task['authorization_id'] == proposal[0]['authorization_id']
            assert task['status'] == 'STOPPING'
        source.finish_original_stop(native_task, monkeypatch)
        response = client.get(f'/api/v1/code-operations/{operation}')
        assert response.status_code == 200, response.text
        assert response.json()['data']['status'] == 'CANCELLED'
        assert state['requests'].count(route) == 1
        return
    if mode == 'unpublished-intent':
        assert current['status'] == 'UNKNOWN', (current, errors)
        assert [step['status'] for step in current['steps']] == [
            'SUCCEEDED',
            'SUCCEEDED',
            'UNKNOWN',
            'PENDING',
        ]
        assert state['requests'].count(route) == 0
        assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
        assert state['requests'].count(route) == 0
        with database.transaction() as connection:
            retained = connection.execute(
                'SELECT authorization_id FROM code_tasks WHERE id=?', (task_id,)
            ).fetchone()[0]
        assert retained == proposal[0]['authorization_id']
        assert state['requests'].count(('POST', '/session')) == 1
        return
    final_drift = mode in (
        'final-configuration-drift',
        'final-permission-drift',
        'basis-identity-drift',
    )
    if final_drift:
        assert current['status'] == 'UNKNOWN', (current, errors)
        assert [step['status'] for step in current['steps']] == [
            'SUCCEEDED',
            'SUCCEEDED',
            'SUCCEEDED',
            'UNKNOWN',
        ]
        assert state['requests'].count(route) == 1
        with database.transaction() as connection:
            retained = connection.execute(
                'SELECT authorization_id FROM code_tasks WHERE id=?', (task_id,)
            ).fetchone()[0]
        assert retained == proposal[0]['authorization_id']
        if configuration_before is not None:
            state['overrides']['/config'] = configuration_before
        if permission_before is not None:
            state['session']['permission'] = permission_before
        owner.basis = basis_before
    if mode in ('third-reply', 'fourth-read') or final_drift:
        assert current['status'] == 'UNKNOWN', current
        if mode == 'fourth-read':
            assert [step['status'] for step in current['steps']] == [
                'SUCCEEDED',
                'SUCCEEDED',
                'SUCCEEDED',
                'UNKNOWN',
            ]
            state['drops'].remove(('GET', '/session/' + native._SESSION))
        with database.transaction() as connection:
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            assert task['authorization_id'] == proposal[0]['authorization_id']
        assert state['requests'].count(route) == 1, errors
        # A positive native permission is not a business adoption; ordinary
        # session observation must still reject it before reconciliation.
        with (
            driver._native_actions(owner, scope) as actions,
            pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'),
        ):
            actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)
        assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
        response = client.get(f'/api/v1/code-operations/{operation}')
        assert response.status_code == 200, response.text
        current = response.json()['data']
    assert current['status'] == 'SUCCEEDED', (
        errors,
        [step['status'] for step in current['steps']],
        state['requests'],
    )
    assert state['requests'].count(route) == 1
    with driver._native_actions(owner, scope) as actions:
        assert len(actions._permission_history) == 1
        session = actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)
        assert session['permission'] == state['session']['permission']
    assert original._original('session')['input']['permission'] != state['session']['permission']
    # Pure preparation of the next message uses the newly adopted native
    # expected group but does not queue or send a model request.
    before = deepcopy(state['requests'])
    payload = driver.continuation_payload(
        scope, owner.gateway._window, 'fixture', native._CHECKPOINT
    )
    assert payload['messageID'].startswith('msg_')
    assert all(method == 'GET' for method, _ in state['requests'][len(before) :])
    assert state['requests'].count(route) == 1

    if mode in ('success', 'control-between-native'):
        # Restore within the original launch boundary using a second explicit
        # C39. Its before policy must include the first adopted native ACK.
        if mode == 'control-between-native':
            unchanged = source.target(native_task, basis=False)
            control_reply = source.accept(native_task, unchanged)
            assert control_reply.status_code == 202, control_reply.text
            assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
            control_record = client.get(
                f'/api/v1/code-operations/{control_reply.json()["data"]["operation_id"]}'
            )
            assert control_record.status_code == 200, control_record.text
            assert control_record.json()['data']['status'] == 'SUCCEEDED'
            assert state['requests'].count(route) == 1
            with driver._native_actions(owner, scope) as actions:
                assert len(actions._permission_history) == 1
                actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)
        restored = source.target(native_task, basis=True)
        accepted = source.accept(native_task, restored)
        assert accepted.status_code == 202, accepted.text
        assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
        record = client.get(f'/api/v1/code-operations/{accepted.json()["data"]["operation_id"]}')
        assert record.status_code == 200, record.text
        assert record.json()['data']['status'] == 'SUCCEEDED', (record.text, errors)
        assert state['requests'].count(route) == 2
        with driver._native_actions(owner, scope) as actions:
            assert len(actions._permission_history) == 2
            actions.observe_session(native._CHECKPOINT, **native._TIMEOUT)
        assert state['requests'].count(('POST', '/session')) == 1
