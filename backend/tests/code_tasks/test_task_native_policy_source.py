"""Real Schema200 START/grant source plus physical NTFS compilation, no provider."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.app.code_tasks.task_initial_prompt import NativeCodingPolicy
from backend.app.code_tasks.task_instance_driver import TaskInstanceDriver
from backend.app.code_tasks.task_native_policy import (
    NativePolicyCompilationError,
    read_managed_session_policy_input,
)
from backend.app.code_tasks.task_start_session import advance_start_session
from backend.app.infrastructure.managed_read_scopes import BASIS, WORKSPACE
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.tests.code_tasks import test_task_start as start_fixture
from backend.tests.code_tasks import test_task_start_instance as instance_fixture
from backend.tests.code_tasks import test_task_start_session as session_fixture
from backend.tests.code_tasks import test_task_stop as stop_fixture
from backend.tests.infrastructure import test_v20_command_http as http_fixture

package = http_fixture.package
service = http_fixture.service
isolated_readiness = start_fixture.isolated_readiness
original_instance = instance_fixture.original_instance
ready = session_fixture.ready


@pytest.fixture(autouse=True)
def managed_roots(monkeypatch):
    original = stop_fixture.scope

    def approved_scope():
        value = original()
        value['read_roots'] = [WORKSPACE, BASIS]
        return value

    monkeypatch.setattr(stop_fixture, 'scope', approved_scope)


def owner_directories(tmp_path):
    root = tmp_path / 'native-instance'
    root.mkdir()
    values = {}
    for role in ('workspace', 'basis'):
        path = root / role
        path.mkdir()
        with LocalPathGuard(path, directory=True) as guard:
            values[role] = guard.verify()
    return SimpleNamespace(**values)


def compiler(database):
    driver = object.__new__(TaskInstanceDriver)
    driver._database = database
    driver._installation = SimpleNamespace(
        coding=NativeCodingPolicy('walle-code', (('*', '*', 'deny'),))
    )
    return driver


def test_original_pending_start_compiles_exact_current_grant_and_preserves_status(ready, tmp_path):
    database, runtime, _, parent, _, _, _ = ready
    driver = session_fixture.NativeDriver()
    owner = owner_directories(tmp_path)
    actual = compiler(database)
    results = []

    def creating(scope):
        with database.transaction() as connection:
            profile, grant, source = read_managed_session_policy_input(connection, scope)
            row = connection.execute('SELECT status FROM code_authorizations').fetchone()
            assert row['status'] == 'BOUND_PENDING_APPLY'
        policy = actual._compile_session_policy(owner, scope, lambda: None)
        assert policy.permission()[0]['action'] == 'deny'
        assert any(row['permission'] == 'external_directory' for row in policy.permission())
        assert grant['read_roots'] == [WORKSPACE, BASIS]
        assert profile['check_set_version_id'] == 1 and len(source) == 64
        with database.transaction() as connection:
            assert (
                connection.execute('SELECT status FROM code_authorizations').fetchone()[0]
                == row['status']
            )
        results.append(policy)

    driver.on_create = creating
    assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
    assert len(results) == 1


@pytest.mark.parametrize(
    'field',
    [
        'task_id',
        'session_id',
        'instance_id',
        'workspace_id',
        'control_generation',
        'operation_id',
        'profile_id',
        'authorization_id',
    ],
)
def test_wrong_start_scope_cannot_borrow_the_pending_pair(ready, field):
    database, runtime, _, parent, _, _, _ = ready
    driver = session_fixture.NativeDriver()
    checked = []

    def creating(scope):
        invalid = replace(scope, **{field: getattr(scope, field) + 1})
        with database.transaction() as connection, pytest.raises(NativePolicyCompilationError):
            read_managed_session_policy_input(connection, invalid)
        checked.append(field)

    driver.on_create = creating
    assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
    assert checked == [field]


def test_real_stop_during_compilation_fences_current_grant_before_any_dispatch(ready, tmp_path):
    database, runtime, client, parent, task_id, _, _ = ready
    driver = session_fixture.NativeDriver()
    owner = owner_directories(tmp_path)
    actual = compiler(database)
    stopped = []

    def creating(scope):
        calls = 0

        def checkpoint():
            nonlocal calls
            calls += 1
            if calls == 4:
                detail = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']
                response = start_fixture.stop(client, task_id, detail['state_version'])
                assert response.status_code == 202, response.text
                stopped.append(response.json()['data']['operation_id'])

        with pytest.raises(TaskExecutionError, match='POLICY_UNVERIFIED'):
            actual._compile_session_policy(owner, scope, checkpoint)
        # The simulated caller does not send anything after a fenced preparation.
        raise TaskExecutionError('STOP_REQUESTED')

    driver.on_create = creating
    advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
    assert len(stopped) == 1
    assert [kind for kind, _ in driver.calls] == ['create']


def test_missing_prelaunch_directory_identity_or_database_never_uses_static_policy(ready, tmp_path):
    database, runtime, _, parent, _, _, _ = ready
    driver = session_fixture.NativeDriver()
    owner = owner_directories(tmp_path)
    actual = compiler(database)
    checked = []

    def creating(scope):
        saved = owner.basis
        owner.basis = None
        with pytest.raises(TaskExecutionError, match='POLICY_SOURCE_REQUIRED'):
            actual._compile_session_policy(owner, scope, lambda: None)
        owner.basis = saved
        actual._database = None
        with pytest.raises(TaskExecutionError, match='POLICY_SOURCE_REQUIRED'):
            actual._compile_session_policy(owner, scope, lambda: None)
        actual._database = database
        checked.append(True)

    driver.on_create = creating
    assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=driver)
    assert checked == [True]
