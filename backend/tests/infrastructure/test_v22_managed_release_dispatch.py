"""Keep managed release dispatch behind live, operation-bound evidence."""

import json
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure


@pytest.mark.parametrize(
    'case',
    (
        'gateway_lost_while_verifying_runtime',
        'gateway_lost_while_reserving_capacity',
        'invalid_command',
        'host_frozen_before_reservation',
        'host_frozen_after_reservation',
        'application_extra_group_before_reservation',
        'application_extra_group_after_reservation',
        'lost_observation',
        'capacity_policy_changed_after_dispatch',
        'host_rebooted_after_dispatch',
        'capacity_blocked',
    ),
)
def test_release_dispatch_checks_closed_state_after_preparing_to_launch(
    case, monkeypatch, tmp_path
):
    pytest.importorskip('fcntl')
    from backend.app.management import release_runtime as runtime
    from backend.app.management.runtime_capacity import MINIMUM

    events = []
    facts = {}
    gateway_live = True
    lock_held = False
    host_held = False
    host_frozen = case == 'host_frozen_before_reservation'
    extra_group_present = case == 'application_extra_group_before_reservation'
    dispatch_host_locks = []
    boot_id = str(uuid4())
    run_id = str(uuid4())
    capacity_available = True
    control = {
        'control_revision': 18,
        'admission': 'CLOSED',
        'closed_reason': 'RECOVERY_REQUIRED',
        'outbound_hold': True,
    }

    @contextmanager
    def environment_lock(_):
        nonlocal lock_held
        assert not lock_held
        lock_held = True
        try:
            yield SimpleNamespace(assert_owned=lambda: None)
        finally:
            lock_held = False

    @contextmanager
    def host_admission():
        nonlocal host_held
        assert lock_held and not host_held
        if host_frozen:
            raise EnvironmentFailure('HOST_RECOVERY_HOLD')
        host_held = True
        try:
            yield
        finally:
            host_held = False

    def verify_opening_evidence(*_):
        assert lock_held
        events.append('check closed')
        if not gateway_live:
            raise EnvironmentFailure('QA_GATEWAY_CHANGED')

    def verify_groups(_):
        assert lock_held and host_held
        if extra_group_present:
            raise EnvironmentFailure(runtime.RESOURCE)

    def verify_runtime(*_):
        nonlocal gateway_live
        events.append('verify runtime')
        if case == 'gateway_lost_while_verifying_runtime':
            gateway_live = False
        return {'python': {'executable_ref': 'bin/python3.13'}}, None

    def admission(*_, input_bytes):
        nonlocal gateway_live, host_frozen, extra_group_present
        events.append('reserve capacity')
        if case == 'host_frozen_after_reservation' and events.count('reserve capacity') == 1:
            host_frozen = True
        if case == 'application_extra_group_after_reservation':
            extra_group_present = True
        if case == 'gateway_lost_while_reserving_capacity':
            gateway_live = False
        if case == 'capacity_blocked':
            return {'status': runtime.OPEN_BLOCKED, 'missing': ['run_slots']}
        return {'status': runtime.OPEN_AUTHORIZED, 'request': json.loads(input_bytes)}

    def command(*_):
        events.append('assemble command')
        if case == 'invalid_command':
            raise EnvironmentFailure('QA_COMMAND_INVALID')
        return ['owned-systemd-test-command']

    def record(_, name, value):
        events.append(('record dispatch', lock_held))
        dispatch_host_locks.append(host_held)
        assert name == runtime.DISPATCH and name not in facts
        facts[name] = value

    def launch(args, timeout):
        assert not lock_held and not host_held
        assert args == ['owned-systemd-test-command'] and timeout == 15
        assert runtime.DISPATCH in facts
        events.append('launch')

    def observe(_catalog, _args, _entry, setup, request, _selection, *, wait):
        events.append('wait' if wait else 'observe original')
        assert request == facts[runtime.DISPATCH]['request']
        assert request['limits'] == limits
        assert setup[0]['memory_bytes'] == limits['memory_bytes']
        raise EnvironmentFailure(runtime.UNVERIFIED, uncertain=True)

    args = SimpleNamespace(
        root=tmp_path,
        release_operation_id=str(uuid4()),
        managed_release_open_policy_sha256='a' * 64,
        sha256='runtime',
    )
    environment = SimpleNamespace(
        environment_id=str(uuid4()),
        description={'purpose': 'INTEGRATION'},
        lock=environment_lock,
        host_admission=host_admission,
        path=lambda _: tmp_path,
    )
    selected = {
        'control_sha256': 'control',
        'transition_sha256': 'transition',
        'control_revision': 18,
        'environment_id': environment.environment_id,
        'data_generation': str(uuid4()),
        'deployment_id': str(uuid4()),
        'configuration_sha256': 'c' * 64,
    }
    target = runtime.SelectedDeployment(
        environment,
        selected,
        {'candidate_ref': 'candidate', 'sha256': 'package'},
        'profile',
        'admit',
    )
    open_pin = 'b' * 64
    launch_policy = {'release_open_policy': {'sha256': open_pin}}
    limits = dict(MINIMUM)
    capacity = SimpleNamespace(profile=lambda _: limits, sha256='d' * 64)
    catalog = SimpleNamespace(directory=tmp_path)
    registry = SimpleNamespace(uid=123, gid=123)

    def load_current_capacity(_):
        if not capacity_available:
            raise EnvironmentFailure('QA_CAPACITY_CHANGED')
        return capacity

    monkeypatch.setattr(runtime, 'load_launch', lambda *_: (launch_policy, '', '', open_pin))
    monkeypatch.setattr(runtime, 'verify_live_launch', lambda *_, **__: None)
    monkeypatch.setattr(runtime, 'open_inputs', lambda *_: {**selected, 'run_id': run_id})
    monkeypatch.setattr(runtime, 'load_capacity', load_current_capacity)
    monkeypatch.setattr(runtime, 'machine_clock', lambda: (boot_id, 1))
    monkeypatch.setattr(runtime, 'NativeEnvironmentFiles', lambda _: None)
    monkeypatch.setattr(runtime, 'control_directory', lambda _: nullcontext(None))
    monkeypatch.setattr(runtime, 'observed_transition', lambda *_: {'after': control})
    monkeypatch.setattr(runtime, 'read_control', lambda *_: control)
    monkeypatch.setattr(runtime, 'unit_facts', lambda _: {'LoadState': 'not-found'})
    monkeypatch.setattr(runtime, 'opening_evidence', verify_opening_evidence)
    monkeypatch.setattr(runtime, 'verify_application_groups', verify_groups, raising=False)
    monkeypatch.setattr(runtime, 'manager_command', lambda *_: [])
    monkeypatch.setattr(runtime, 'invoke_observer', admission)
    monkeypatch.setattr(runtime, 'startup_command', command)
    monkeypatch.setattr(runtime, 'optional_fact', lambda _, name: facts.get(name))
    monkeypatch.setattr(runtime, 'write_fact', record)
    monkeypatch.setattr(runtime, 'run_bounded', launch)
    monkeypatch.setattr(runtime, 'confirm_dispatch', observe)

    def start():
        return runtime.start_selected_deployment(
            catalog, registry, args, {'verify_runtime': verify_runtime}, 'manager', None, target
        )

    prepared = ['verify runtime', 'assemble command']
    if case == 'capacity_blocked':
        assert start() == {'status': runtime.OPEN_BLOCKED, 'missing': ['run_slots']}
        assert events == [*prepared, 'check closed', 'reserve capacity']
        assert not facts
        return

    reason = {
        'gateway_lost_while_verifying_runtime': 'QA_GATEWAY_CHANGED',
        'gateway_lost_while_reserving_capacity': 'QA_GATEWAY_CHANGED',
        'invalid_command': 'QA_COMMAND_INVALID',
        'host_frozen_before_reservation': 'HOST_RECOVERY_HOLD',
        'host_frozen_after_reservation': 'HOST_RECOVERY_HOLD',
        'application_extra_group_before_reservation': runtime.RESOURCE,
        'application_extra_group_after_reservation': runtime.RESOURCE,
        'lost_observation': runtime.UNVERIFIED,
        'capacity_policy_changed_after_dispatch': runtime.UNVERIFIED,
        'host_rebooted_after_dispatch': runtime.UNVERIFIED,
    }[case]
    with pytest.raises(EnvironmentFailure, match=reason) as result:
        start()
    assert result.value.uncertain is (reason == runtime.UNVERIFIED)
    reserved = [*prepared, 'check closed', 'reserve capacity', 'check closed']
    if case == 'invalid_command':
        assert events == prepared and not facts
    elif case == 'host_frozen_before_reservation':
        assert events == prepared and not facts
    elif case == 'host_frozen_after_reservation':
        assert events == [*prepared, 'check closed', 'reserve capacity'] and not facts
        host_frozen = False
        with pytest.raises(EnvironmentFailure, match=runtime.UNVERIFIED) as retry:
            start()
        assert retry.value.uncertain
        assert dispatch_host_locks == [True]
        assert events.count('launch') == 1
    elif case == 'application_extra_group_before_reservation':
        assert events == [*prepared, 'check closed'] and not facts
    elif case == 'application_extra_group_after_reservation':
        assert events == reserved and not facts
    elif case == 'gateway_lost_while_verifying_runtime':
        assert events == [*prepared, 'check closed'] and not facts
    elif case == 'gateway_lost_while_reserving_capacity':
        assert events == reserved and not facts
    else:
        assert events == [*reserved, ('record dispatch', True), 'launch', 'wait']
        if case == 'capacity_policy_changed_after_dispatch':
            capacity_available = False
        if case == 'host_rebooted_after_dispatch':
            boot_id = str(uuid4())
        with pytest.raises(EnvironmentFailure, match=runtime.UNVERIFIED) as retry:
            start()
        assert retry.value.uncertain
        assert events[-1] == (
            'wait' if case == 'host_rebooted_after_dispatch' else 'observe original'
        )
        assert events.count('launch') == events.count('reserve capacity') == 1
        assert dispatch_host_locks == [True]
