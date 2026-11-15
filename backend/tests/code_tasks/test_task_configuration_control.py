"""Real C39 third-step persistence, read-only recovery, and adoption fences."""

from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest

from backend.app.code_tasks import task_live_configuration as flow
from backend.app.infrastructure.opencode_instance_control import NativeTurnCompletion
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object
from backend.tests.code_tasks import test_task_live_configuration as live

fixed_price = live.fixed_price
isolated_readiness = live.isolated_readiness
opened = live.opened
original_instance = live.original_instance
ready = live.ready
package = live.package
service = live.service
idle_task = live.idle_task
versioned_runtime_fixture = live.versioned_runtime_fixture


@pytest.mark.parametrize(
    'mode',
    [
        'success',
        'backwards-clock',
        'unknown',
        'verification-unknown',
        'verification-drift',
        'cancelled',
        'budget',
        'stop',
        'permission-drift',
        'configuration-drift',
        'quiescence-drift',
    ],
)
def test_control_application_retains_one_third_identity_and_recovers_by_observation(
    idle_task, monkeypatch, mode
):
    database, runtime, client, _, _, task_id, _, _, _ = idle_task
    old, profile, grant, content = live.target_pair(idle_task)
    path = f'/api/v1/code-tasks/{task_id}'
    with live.resources(live.fixture_snapshot(content)):
        accepted = client.post(
            path + '/configuration',
            json={
                'expected_state_version': old['state_version'],
                'execution_profile_version_id': profile,
                'authorization_id': grant,
                'reason': '明确应用控制组合',
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['data']['operation_id']
    cancelled = Event()
    retained = {}

    class Driver(live.ReadOnlyDriver):
        def observe_control_configuration(self, scope, window, credential_ref, checkpoint):
            result = super().observe_control_configuration(
                scope, window, credential_ref, checkpoint
            )
            if len(self.calls) == 3 and mode.startswith('verification-'):
                actual = client.get(path + f'/operations/{identity}')
                assert actual.status_code == 200, actual.text
                assert [step['status'] for step in actual.json()['data']['steps']] == [
                    'SUCCEEDED',
                    'SUCCEEDED',
                    'SUCCEEDED',
                    'RUNNING',
                ]
                return (
                    None
                    if mode == 'verification-unknown'
                    else replace(result, permission_sha256='0' * 64)
                )
            if len(self.calls) != 2:
                return result
            original = client.get(path + f'/operations/{identity}')
            assert original.status_code == 200, original.text
            assert [step['status'] for step in original.json()['data']['steps']] == [
                'SUCCEEDED',
                'SUCCEEDED',
                'RUNNING',
                'PENDING',
            ]
            assert all(
                step['external_identity'] is None for step in original.json()['data']['steps']
            )
            with database.transaction() as connection:
                steps = connection.execute(
                    'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                    (identity,),
                ).fetchall()
                retained['third'] = steps[2]['external_identity']
                retained['quiet'] = dict(steps[1])
                original_identity = strict_json_object(retained['third'])
                assert original_identity['mode'] == 'CONTROL_ONLY'
                assert len(original_identity['nonce']) == 32
            view = client.get(path).json()['data']
            assert view['execution_profile_version_id'] == old['execution_profile_version_id']
            assert view['authorization_id'] == old['authorization_id']
            assert view['configuration_application']['status'] == 'PENDING'
            if mode == 'unknown':
                return None
            if mode == 'backwards-clock':
                monkeypatch.setattr(flow, 'operation_time', lambda _: old['updated_at'])
            if mode == 'cancelled':
                cancelled.set()
                checkpoint()
            if mode == 'budget':
                updated = client.post(
                    path + '/budget',
                    json={
                        'expected_state_version': view['state_version'],
                        'new_budget_limit_cny': '0.200000',
                        'reason': '第三步期间明确追加',
                    },
                    headers={'Idempotency-Key': str(uuid4())},
                )
                assert updated.status_code == 200, updated.text
                checkpoint()
            if mode == 'stop':
                stopped = live.stop(client, task_id, view['state_version'])
                assert stopped.status_code == 202, stopped.text
                checkpoint()
            if mode == 'permission-drift':
                return replace(result, permission_sha256='0' * 64)
            if mode == 'configuration-drift':
                return replace(
                    result,
                    configuration=replace(result.configuration, nonsecret_config_sha256='0' * 64),
                )
            if mode == 'quiescence-drift':
                return replace(
                    result,
                    quiescence=replace(
                        result.quiescence,
                        turn=NativeTurnCompletion(
                            window.native_session_id,
                            window.trigger_message_id,
                            'msg_different',
                            'COMPLETED',
                        ),
                    ),
                )
            return result

    driver = Driver(idle_task)
    advanced = flow.advance_live_configuration(runtime, driver, cancelled=cancelled.is_set)
    assert len(driver.calls) == (
        3
        if mode in ('success', 'backwards-clock', 'verification-unknown', 'verification-drift')
        else 2
    )
    assert advanced == (mode not in ('cancelled', 'budget', 'stop'))
    with database.transaction() as connection:
        rows = connection.execute(
            'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no', (identity,)
        ).fetchall()
        assert dict(rows[1]) == retained['quiet']
        assert rows[2]['external_identity'] == retained['third']
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM code_runtime_observations WHERE operation_id=? AND kind='QUIESCE'",
                (identity,),
            ).fetchone()[0]
            == 1
        )
    if mode == 'stop':
        assert not flow.advance_live_configuration(
            runtime, live.ReadOnlyDriver(idle_task), cancelled=lambda: False
        )
        with database.transaction(write=True) as connection:
            flow.interrupt_live_configurations(connection, task_id, operation_time(None))
        stopped = client.get(path + f'/operations/{identity}')
        assert stopped.status_code == 200, stopped.text
        assert [step['status'] for step in stopped.json()['data']['steps']] == [
            'SUCCEEDED',
            'SUCCEEDED',
            'CANCELLED',
            'CANCELLED',
        ]
        return
    if mode not in ('success', 'backwards-clock'):
        operation = client.get(path + f'/operations/{identity}')
        assert operation.status_code == 200, operation.text
        unknown = mode not in ('cancelled', 'budget')
        expected = (
            ['SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED', 'UNKNOWN']
            if mode.startswith('verification-')
            else ['SUCCEEDED', 'SUCCEEDED', 'UNKNOWN' if unknown else 'RUNNING', 'PENDING']
        )
        assert [step['status'] for step in operation.json()['data']['steps']] == expected
        cancelled.clear()
        # Only remove the polling delay; the retained identity and all adoption checks remain real.
        monkeypatch.setattr(flow, '_OBSERVE_RECHECK_SECONDS', 0)
        recovering = live.ReadOnlyDriver(idle_task)
        assert flow.advance_live_configuration(runtime, recovering, cancelled=lambda: False)
        assert len(recovering.calls) == (1 if mode.startswith('verification-') else 2)
    final = client.get(path)
    assert final.status_code == 200, final.text
    assert (
        final.json()['data']['execution_profile_version_id'],
        final.json()['data']['authorization_id'],
    ) == (profile, grant)
    assert final.json()['data']['configuration_application']['status'] == 'APPLIED'
    if mode == 'budget':
        assert final.json()['data']['budget']['limit_cny'] == '0.200000'
    with database.transaction() as connection:
        steps = connection.execute(
            'SELECT * FROM code_operation_steps WHERE operation_id=? ORDER BY step_no', (identity,)
        ).fetchall()
        assert dict(steps[1]) == retained['quiet']
        assert steps[2]['external_identity'] == retained['third']
        assert all(step['status'] == 'SUCCEEDED' for step in steps)
        if mode == 'backwards-clock':
            assert steps[2]['ended_at'] >= steps[1]['ended_at'] > old['updated_at']
        if mode == 'success':
            from copy import deepcopy

            from backend.app.code_tasks.task_configuration_control import verify_control_result
            from backend.app.infrastructure.database import StorageUnavailable

            control_identity = strict_json_object(steps[2]['external_identity'])
            result = strict_json_object(steps[3]['result_ref'])
            verify_control_result(control_identity, result)
            changes = [
                ('native_permission_sha256', '0' * 64),
                ('nonsecret_config_ref', 'sha256:' + '0' * 64),
                ('agent_ref', 'foreign-agent'),
                ('runtime_bundle_ref', 'opencode-bundle:sha256:' + '0' * 64),
                ('source_ref', 'sha256:' + '0' * 64),
            ]
            for field, value in changes:
                changed = deepcopy(result)
                if field == 'native_permission_sha256':
                    changed[field] = value
                elif field == 'agent_ref':
                    changed['effective_evidence']['role_model_refs'][field] = value
                elif field == 'source_ref':
                    changed['effective_evidence']['source_refs'] = [value]
                else:
                    changed['effective_evidence'][field] = value
                with pytest.raises(StorageUnavailable):
                    verify_control_result(control_identity, changed)


def test_racing_control_observers_publish_one_nonce_and_one_quiet_record(idle_task):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    database, runtime, client, _, _, task_id, _, _, _ = idle_task
    old, profile, grant, content = live.target_pair(idle_task)
    path = f'/api/v1/code-tasks/{task_id}'
    with live.resources(live.fixture_snapshot(content)):
        accepted = client.post(
            path + '/configuration',
            json={
                'expected_state_version': old['state_version'],
                'execution_profile_version_id': profile,
                'authorization_id': grant,
                'reason': '竞争观察同一配置意图',
            },
            headers={'Idempotency-Key': str(uuid4())},
        )
    assert accepted.status_code == 202, accepted.text
    identity = accepted.json()['data']['operation_id']
    prepared = Barrier(2)

    class RacingDriver(live.ReadOnlyDriver):
        def observe_control_configuration(self, *args):
            result = super().observe_control_configuration(*args)
            if len(self.calls) == 1:
                prepared.wait(timeout=10)
            return result

    drivers = [RacingDriver(idle_task), RacingDriver(idle_task)]
    with ThreadPoolExecutor(max_workers=2) as threads:
        futures = [
            threads.submit(
                flow.advance_live_configuration, runtime, driver, cancelled=lambda: False
            )
            for driver in drivers
        ]
        assert sorted(future.result(timeout=30) for future in futures) == [False, True]
    with database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM code_runtime_observations WHERE operation_id=? AND kind='QUIESCE'",
                (identity,),
            ).fetchone()[0]
            == 1
        )
        step = connection.execute(
            'SELECT * FROM code_operation_steps WHERE operation_id=? AND step_no=3', (identity,)
        ).fetchone()
        assert step['status'] == 'SUCCEEDED'
        assert strict_json_object(step['external_identity'])['mode'] == 'CONTROL_ONLY'
    result = client.get(path + f'/operations/{identity}')
    assert result.status_code == 200, result.text
    assert result.json()['data']['status'] == 'SUCCEEDED'
