"""Actual creation/recovery HTTP consumes compiled rules; source DB and OS evidence are separate."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.app.code_tasks.task_instance_driver import TaskInstanceDriver
from backend.app.code_tasks.task_native_policy import compile_managed_native_policy
from backend.app.code_tasks.task_start_session import StartSessionScope
from backend.app.infrastructure.managed_read_scopes import BASIS, WORKSPACE
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.tests.code_tasks.test_execution_profile_content import body
from backend.tests.infrastructure import test_v20_opencode_instance_control as native
from backend.tests.infrastructure.test_v20_native_session_policy import configure_driver

native_control = native.native_control


@pytest.mark.parametrize('native_control', ['workspace'], indirect=True)
@pytest.mark.parametrize('include_basis', [False, True])
@pytest.mark.parametrize('mode', ['success', 'create-unknown', 'permission-drift', 'config-drift'])
def test_original_driver_creates_and_recovers_the_exact_compiled_session(
    native_control, monkeypatch, include_basis, mode
):
    control, actions, state, launch = native_control
    basis_path = control._workspace.canonical_path
    from pathlib import Path

    basis_path = Path(basis_path).with_name('basis')
    basis_path.mkdir()
    with LocalPathGuard(basis_path, directory=True) as guard:
        basis = guard.verify()
    profile = body()
    scope_grant = {
        'read_roots': [WORKSPACE, BASIS] if include_basis else [WORKSPACE],
        'write_workspace_only': True,
        'allowed_command_ids': [],
        'network_targets': [],
        'model_profile_refs': ['deepseek-v2'],
        'allow_local_delivery': False,
        'limits': deepcopy(profile['limits']),
    }
    scope = StartSessionScope(3, 10, 12, 11, 1, 2, 20, 21, launch.nonce, 22, 2, 2)
    owner = SimpleNamespace(workspace=control._workspace, basis=basis, gateway=SimpleNamespace())
    driver = object.__new__(TaskInstanceDriver)
    configure_driver(driver, owner, state)
    monkeypatch.setattr(driver, '_session_owner', lambda *args: owner)
    monkeypatch.setattr(driver, '_continuation_guard', lambda *args: 'a' * 64)
    compiled = []

    def compile_policy(actual_owner, actual_scope, checkpoint):
        assert actual_owner is owner and actual_scope is scope
        value = compile_managed_native_policy(
            profile,
            scope_grant,
            agent='walle-code',
            workspace=owner.workspace,
            basis=owner.basis,
            checkpoint=checkpoint,
        )
        compiled.append(value)
        return value.policy

    # DB provenance/STOP is exercised with real Schema200 in the source suite.
    # Here the real compiler and original HTTP/journal/group methods are used.
    monkeypatch.setattr(driver, '_compile_session_policy', compile_policy)

    @contextmanager
    def native_actions(actual_owner, actual_scope):
        assert actual_owner is owner and actual_scope is scope
        yield actions

    monkeypatch.setattr(driver, '_native_actions', native_actions)
    if mode != 'success':
        state['drops'].add(('POST', '/session'))
    if mode == 'create-unknown':
        # A lost POST reply alone can be reconciled immediately by the driver.
        # Drop the first listing too, so this round has no positive read evidence.
        state['drops'].add(('GET', '/session'))
        with pytest.raises(TaskExecutionError):
            driver.create_session(scope, native._CHECKPOINT)
        state['drops'].remove(('GET', '/session'))
    else:
        created = driver.create_session(scope, native._CHECKPOINT)
        assert created.native_id == native._SESSION
    assert len(compiled) == 1
    assert state['session']['permission'] == compiled[0].policy.permission()
    assert actions._original('session')['input']['permission'] == compiled[0].policy.permission()
    assert state['requests'].count(('POST', '/session')) == 1
    before = len(state['requests'])
    if mode == 'permission-drift':
        state['session']['permission'].append(
            {'permission': '*', 'pattern': '*', 'action': 'allow'}
        )
        with pytest.raises(TaskExecutionError, match='SESSION_POLICY_DIFFERS'):
            driver.observe_created_session(scope, native._CHECKPOINT)
    elif mode == 'config-drift':
        state['overrides']['/config']['agent']['walle-code']['prompt'] = 'different source'
        with pytest.raises(TaskExecutionError):
            driver.observe_created_session(scope, native._CHECKPOINT)
    else:
        assert driver.observe_created_session(scope, native._CHECKPOINT) == native._SESSION
    assert state['requests'].count(('POST', '/session')) == 1
    assert all(method == 'GET' for method, _ in state['requests'][before:])
