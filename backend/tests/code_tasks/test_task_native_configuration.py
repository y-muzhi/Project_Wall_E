"""Original C39 four-stage SQL/HTTP protocol with an explicit offline native stand-in."""

import hashlib
from copy import deepcopy
from dataclasses import asdict, replace
from uuid import uuid4

import pytest

from backend.app.code_tasks.authorizations import project_grant
from backend.app.code_tasks.task_configuration_control import _digest
from backend.app.code_tasks.task_configuration_live_records import stored_profile_content
from backend.app.code_tasks.task_configuration_native import adopted_native_permission_scopes
from backend.app.code_tasks.task_instance_driver import NativeConfigurationPreparation
from backend.app.code_tasks.task_live_configuration import advance_live_configuration
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.managed_read_scopes import (
    BASIS,
    RESOURCE_SHA256,
    WORKSPACE,
    scope_options,
)
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.tests.code_tasks import test_task_live_configuration as live
from backend.tests.code_tasks import test_task_stop as stop_fixture

package = live.package
service = live.service
isolated_readiness = live.isolated_readiness
original_instance = live.original_instance
ready = live.ready
fixed_price = live.fixed_price
opened = live.opened
idle_task = live.idle_task
versioned_runtime_fixture = live.versioned_runtime_fixture


@pytest.fixture(autouse=True)
def managed_roots(monkeypatch, request):
    original = stop_fixture.scope

    def approved_scope():
        value = original()
        value['read_roots'] = list(getattr(request, 'param', (WORKSPACE, BASIS)))
        return value

    monkeypatch.setattr(stop_fixture, 'scope', approved_scope)


@pytest.fixture
def native_task(idle_task):
    idle_task[2].app.state.walle_repository_registration.accepts_native_permission_updates = True
    return idle_task


def target(fixture, *, basis):
    database, _, client, _, _, task_id, _, _, _ = fixture
    with database.transaction() as connection:
        task = dict(
            connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        )
        profile = connection.execute(
            'SELECT * FROM code_execution_profile_versions WHERE id=?',
            (task['execution_profile_version_id'],),
        ).fetchone()
        grant = project_grant(
            connection.execute(
                'SELECT * FROM code_authorizations WHERE id=?', (task['authorization_id'],)
            ).fetchone()
        )
        content = stored_profile_content(profile)
    scope = deepcopy(grant['scope'])
    scope['read_roots'] = [WORKSPACE, BASIS] if basis else [WORKSPACE]
    snapshot = live.fixture_snapshot(content)
    snapshot['SCOPE'] = scope_options()
    with live.resources(snapshot):
        result = live.approve(client, {'profile_version_id': profile['id'], 'scope': scope})
    assert result.status_code == 201, result.text
    return task, result.json()['data']['resource_id'], content, scope, snapshot


def accept(fixture, proposal, key=None):
    old, grant, _, _, snapshot = proposal
    client = fixture[2]
    with live.resources(snapshot):
        return client.post(
            f'/api/v1/code-tasks/{old["id"]}/configuration',
            json={
                'expected_state_version': old['state_version'],
                'execution_profile_version_id': old['execution_profile_version_id'],
                'authorization_id': grant,
                'reason': '明确调整原启动边界内固定依据的读取许可',
            },
            headers={'Idempotency-Key': key or str(uuid4())},
        )


class NativeDriver(live.ReadOnlyDriver):
    def __init__(self, fixture, mode='success'):
        super().__init__(fixture)
        self.mode = mode
        self.permission = 'e' * 64
        self.published = False
        self.dispatches = 0
        self.observations = 0
        self.unknown_once = False

    def observed(self, scope, window, credential, checkpoint):
        return replace(
            super().observe_control_configuration(scope, window, credential, checkpoint),
            permission_sha256=self.permission,
        )

    def prepare_native_configuration(self, scope, window, credential, profile, grant, checkpoint):
        observation = self.observed(scope, window, credential, checkpoint)
        creation = LaunchScope('a' * 64, scope.operation_id, 4, scope.nonce)
        with self.fixture[0].transaction() as connection:
            history = adopted_native_permission_scopes(connection, scope, creation)
        proof = {
            'protocol_version': 'READ20-MANAGED-1',
            'resource_sha256': RESOURCE_SHA256,
            'profile_sha256': _digest(profile),
            'authorization_scope_sha256': _digest(grant),
            'read_roots': sorted(grant['read_roots']),
            'workspace_sha256': _digest(asdict(observation.quiescence.workspace)),
            'basis_sha256': 'b' * 64 if BASIS in grant['read_roots'] else None,
            'agent': observation.configuration.agent_ref,
            'permission_sha256': 'd' * 64,
        }
        if self.mode == 'bad-proof':
            proof['workspace_sha256'] = '0' * 64
        next_permission = hashlib.sha256(
            (self.permission + canonical_input(proof)).encode()
        ).hexdigest()
        return NativeConfigurationPreparation(
            observation, canonical_input(proof), next_permission, creation, history
        )

    def apply_native_configuration(
        self, scope, window, credential, profile, grant, identity, checkpoint, *, dispatch
    ):
        checkpoint()
        self.observations += 1
        if dispatch:
            if self.mode == 'missing-intent':
                raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_INTENT_REQUIRED')
            self.published = True
            self.dispatches += 1
            self.permission = identity['target_permission_sha256']
        elif not self.published:
            raise TaskExecutionError('ORIGINAL_NATIVE_ACTION_INTENT_REQUIRED')
        if not self.unknown_once and (
            self.mode == 'third-unknown'
            and self.observations == 1
            or self.mode == 'fourth-unknown'
            and self.observations == 2
        ):
            self.unknown_once = True
            return None
        result = self.observed(scope, window, credential, checkpoint)
        if self.mode == 'drift':
            return replace(result, permission_sha256='0' * 64)
        return result


@pytest.mark.parametrize(
    'mode',
    [
        'success',
        'third-unknown',
        'fourth-unknown',
        'missing-intent',
        'bad-proof',
        'drift',
    ],
)
def test_native_read_application_uses_original_stages_and_never_redispatches(native_task, mode):
    proposal = target(native_task, basis=False)
    reply = accept(native_task, proposal)
    assert reply.status_code == 202, reply.text
    operation = reply.json()['data']['operation_id']
    driver = NativeDriver(native_task, mode)
    database, runtime, client, _, _, task_id, _, _, _ = native_task
    assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
    response = client.get(f'/api/v1/code-operations/{operation}')
    assert response.status_code == 200, response.text
    current = response.json()['data']
    if mode == 'success':
        assert current['status'] == 'SUCCEEDED'
    else:
        assert current['status'] == 'UNKNOWN'
        with database.transaction() as connection:
            task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
            assert task['authorization_id'] == proposal[0]['authorization_id']
        if mode in ('third-unknown', 'fourth-unknown', 'drift'):
            if mode == 'fourth-unknown':
                assert [step['status'] for step in current['steps']] == [
                    'SUCCEEDED',
                    'SUCCEEDED',
                    'SUCCEEDED',
                    'UNKNOWN',
                ]
            elif mode == 'third-unknown':
                assert [step['status'] for step in current['steps']] == [
                    'SUCCEEDED',
                    'SUCCEEDED',
                    'UNKNOWN',
                    'PENDING',
                ]
            driver.mode = 'success'
            assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
            current = client.get(f'/api/v1/code-operations/{operation}').json()['data']
            assert current['status'] == 'SUCCEEDED'
        elif mode == 'missing-intent':
            assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
            assert driver.dispatches == 0
        else:
            assert driver.dispatches == 0
    assert driver.dispatches <= 1
    assert all(step['external_identity'] is None for step in current['steps'])


def test_repeat_native_application_keeps_original_launch_and_exact_adopted_prefix(native_task):
    database, runtime, client, _, _, task_id, _, _, _ = native_task
    driver = NativeDriver(native_task)
    original = None
    for basis in (False, True):
        proposal = target(native_task, basis=basis)
        original = original or proposal[0]
        reply = accept(native_task, proposal)
        assert reply.status_code == 202, reply.text
        assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
        operation = reply.json()['data']['operation_id']
        record = client.get(f'/api/v1/code-operations/{operation}')
        assert record.status_code == 200, record.text
        assert record.json()['data']['status'] == 'SUCCEEDED'
    assert driver.dispatches == 2
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        session = connection.execute(
            'SELECT * FROM code_sessions WHERE id=?', (task['active_session_id'],)
        ).fetchone()
        scope = live.original_active_session_scope(connection, task, session)
        creation = LaunchScope('a' * 64, scope.operation_id, 4, scope.nonce)
        history = adopted_native_permission_scopes(connection, scope, creation)
        assert len(history) == 2 and history[0].operation_id != history[1].operation_id
        assert scope.operation_id == native_task[3].window.operation_id
        assert task['active_session_id'] == original['active_session_id']
        assert task['workspace_id'] == original['workspace_id']


def test_missing_native_worker_capability_refuses_before_binding_or_operation(native_task):
    proposal = target(native_task, basis=False)
    native_task[2].app.state.walle_repository_registration.accepts_native_permission_updates = False
    reply = accept(native_task, proposal)
    assert reply.status_code == 503, reply.text
    with native_task[0].transaction() as connection:
        grant = connection.execute(
            'SELECT task_id,status FROM code_authorizations WHERE id=?', (proposal[1],)
        ).fetchone()
        assert tuple(grant) == (None, 'APPROVED_UNBOUND')
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE operation_type='APPLY_CONFIGURATION'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize('managed_roots', [[WORKSPACE]], indirect=True)
def test_new_registered_root_cannot_expand_the_original_launch_boundary(native_task):
    proposal = target(native_task, basis=True)
    reply = accept(native_task, proposal)
    assert reply.status_code == 403, reply.text
    assert reply.json()['error']['code'] == 'AUTHORIZATION_NOT_APPLICABLE'
    with native_task[0].transaction() as connection:
        row = connection.execute(
            'SELECT task_id,status FROM code_authorizations WHERE id=?', (proposal[1],)
        ).fetchone()
        assert tuple(row) == (None, 'APPROVED_UNBOUND')


def test_lost_target_admission_prevents_original_patch_and_later_recovery_does_not_send(
    native_task, monkeypatch
):
    from backend.app.code_tasks import task_live_configuration as flow
    from backend.app.infrastructure.resources import ConfigInvalid

    proposal = target(native_task, basis=False)
    reply = accept(native_task, proposal)
    assert reply.status_code == 202, reply.text
    driver = NativeDriver(native_task)
    actual_prepare = driver.prepare_native_configuration
    blocked = False

    def prepared(*args):
        nonlocal blocked
        value = actual_prepare(*args)
        blocked = True
        return value

    actual_validate = flow._validate_control_target

    def validate(*args, **kwargs):
        if blocked:
            raise ConfigInvalid('ISOLATED_ADMISSION_LOST')
        return actual_validate(*args, **kwargs)

    monkeypatch.setattr(driver, 'prepare_native_configuration', prepared)
    monkeypatch.setattr(flow, '_validate_control_target', validate)
    runtime = native_task[1]
    assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
    assert driver.dispatches == 0
    operation = reply.json()['data']['operation_id']
    with native_task[0].transaction() as connection:
        before = connection.execute(
            'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=3',
            (operation,),
        ).fetchone()[0]
    blocked = False
    assert advance_live_configuration(runtime, driver, cancelled=lambda: False)
    assert driver.dispatches == 0
    with native_task[0].transaction() as connection:
        after = connection.execute(
            'SELECT external_identity FROM code_operation_steps WHERE operation_id=? AND step_no=3',
            (operation,),
        ).fetchone()[0]
        assert after == before


def finish_original_stop(fixture, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from backend.app.code_tasks import task_runtime_stop
    from backend.tests.code_tasks.test_task_runtime_stop import StopDriver

    _, runtime, client, _, parent, task_id, _, _, _ = fixture
    clock = datetime.now(UTC) + timedelta(days=1)

    def after_grace(_):
        nonlocal clock
        clock += timedelta(minutes=2)
        return clock.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    monkeypatch.setattr(task_runtime_stop, 'operation_time', after_grace)
    driver = StopDriver(parent)
    terminal = None
    for _ in range(10):
        task_runtime_stop.advance_owned_stops(runtime, driver, cancelled=lambda: False)
        terminal = client.get(f'/api/v1/code-tasks/{task_id}')
        assert terminal.status_code == 200, terminal.text
        if terminal.json()['data']['status'] == 'TERMINATED':
            break
    assert terminal is not None and terminal.json()['data']['status'] == 'TERMINATED', (
        None if terminal is None else terminal.text
    )


def test_stop_after_native_dispatch_retains_facts_and_never_adopts_the_target(
    native_task, monkeypatch
):
    proposal = target(native_task, basis=False)
    reply = accept(native_task, proposal)
    assert reply.status_code == 202, reply.text
    database, runtime, client, _, _, task_id, _, _, _ = native_task

    class Stopped(NativeDriver):
        def apply_native_configuration(self, *args, **kwargs):
            result = super().apply_native_configuration(*args, **kwargs)
            if kwargs['dispatch']:
                detail = client.get(f'/api/v1/code-tasks/{task_id}').json()['data']
                stopped = live.stop(client, task_id, detail['state_version'])
                assert stopped.status_code == 202, stopped.text
            return result

    driver = Stopped(native_task)
    advance_live_configuration(runtime, driver, cancelled=lambda: False)
    assert driver.dispatches == 1
    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (task_id,)).fetchone()
        assert task['authorization_id'] == proposal[0]['authorization_id']
        assert task['status'] == 'STOPPING'
    response = client.get(f'/api/v1/code-operations/{reply.json()["data"]["operation_id"]}')
    assert response.status_code == 200, response.text
    assert response.json()['data']['status'] == 'RUNNING'
    finish_original_stop(native_task, monkeypatch)
    response = client.get(f'/api/v1/code-operations/{reply.json()["data"]["operation_id"]}')
    assert response.status_code == 200, response.text
    assert response.json()['data']['status'] == 'CANCELLED'


def test_same_key_and_concurrent_workers_only_dispatch_one_original(native_task):
    from concurrent.futures import ThreadPoolExecutor

    proposal = target(native_task, basis=False)
    key = str(uuid4())
    reply = accept(native_task, proposal, key)
    assert reply.status_code == 202, reply.text
    driver = NativeDriver(native_task)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda _: advance_live_configuration(
                    native_task[1], driver, cancelled=lambda: False
                ),
                range(2),
            )
        )
    assert driver.dispatches == 1
    replay = accept(native_task, proposal, key)
    assert replay.status_code == 202, replay.text
    assert replay.json()['data'] == reply.json()['data']
    assert not advance_live_configuration(native_task[1], driver, cancelled=lambda: False)
    assert driver.dispatches == 1
