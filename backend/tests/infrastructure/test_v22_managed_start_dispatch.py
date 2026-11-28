"""Guard the original ordinary preparation and dispatch across host recovery."""

from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest


@pytest.mark.parametrize(
    'changed',
    (
        None,
        'host_hold',
        'control_revision',
        'operation',
        'admission',
        'socket',
        'unit',
        'boot',
        'extra_group',
    ),
)
def test_application_dispatch_requires_the_original_prepared_closed_control(
    changed, tmp_path, monkeypatch
):
    pytest.importorskip('fcntl')
    from backend.app.management import runtime_start as runtime

    issues = []
    locks = []
    operation = str(uuid4())
    boot = str(uuid4())
    plan = {
        'format_version': 1,
        'operation_id': operation,
        'run_id': str(uuid4()),
        'environment_id': str(uuid4()),
        'data_generation': str(uuid4()),
        'deployment_id': str(uuid4()),
        'configuration_sha256': 'a' * 64,
        'control_revision': 12,
    }
    raw = canonical(plan)
    prepared = {**plan, 'start_sha256': digest(raw)}
    control = {
        'operation_id': str(uuid4()) if changed == 'operation' else operation,
        'control_revision': 13 if changed == 'control_revision' else 12,
        'admission': 'OPEN' if changed == 'admission' else 'CLOSED',
        'closed_reason': 'NONE' if changed == 'admission' else 'NORMAL_STOP',
    }

    @contextmanager
    def stable_environment_lock(native):
        assert native is None and not locks
        locks.append('environment')
        try:
            yield SimpleNamespace(assert_owned=lambda: locks == ['environment', 'host'])
        finally:
            assert locks.pop() == 'environment'

    @contextmanager
    def host_admission():
        assert locks == ['environment']
        if changed == 'host_hold':
            raise EnvironmentFailure('HOST_RECOVERY_HOLD')
        locks.append('host')
        try:
            yield
        finally:
            assert locks.pop() == 'host'

    def save(fd, name, value, *, replace):
        assert locks == ['environment', 'host']
        assert (fd, name, replace) == (None, 'start-fact', True)
        issues.append(value)

    environment = SimpleNamespace(
        **{
            field: plan[field]
            for field in (
                'environment_id',
                'data_generation',
                'deployment_id',
                'configuration_sha256',
            )
        },
        application_uid=1320,
        group=1321,
        lock=stable_environment_lock,
        host_admission=host_admission,
        path=lambda _: tmp_path,
    )
    record = {'boot_id': boot, 'start_operation_id': operation, 'state': 'PREPARING'}
    monkeypatch.setattr(runtime, 'control_directory', lambda _: nullcontext(None))
    monkeypatch.setattr(runtime, 'read_control', lambda *_: control)
    monkeypatch.setattr(runtime, 'read_start', lambda *_: raw)
    monkeypatch.setattr(
        runtime, 'machine_clock', lambda: ('new boot' if changed == 'boot' else boot, 1)
    )
    monkeypatch.setattr(
        runtime,
        'unit_facts',
        lambda _: {'LoadState': 'loaded' if changed == 'unit' else 'not-found'},
    )
    monkeypatch.setattr(runtime, 'write_record', save)

    def native_groups(name, group):
        assert (name, group) == ('app', environment.group) and locks == ['environment', 'host']
        return [group, 1322] if changed == 'extra_group' else [group]

    monkeypatch.setattr(
        runtime.pwd,
        'getpwuid',
        lambda uid: SimpleNamespace(pw_name='app', pw_gid=environment.group),
    )
    monkeypatch.setattr(runtime.os, 'getgrouplist', native_groups)
    if changed == 'socket':
        (tmp_path / 'walle.sock').touch()

    def dispatch():
        return runtime.record_application_dispatch(
            None, 'start-fact', record, environment, None, prepared, 'original.service'
        )

    if changed is None:
        result = dispatch()
        assert result == {**record, 'state': 'STARTING', 'prepared': prepared}
        assert issues == [result]
    else:
        with pytest.raises(EnvironmentFailure) as failure:
            dispatch()
        expected = {
            'host_hold': 'HOST_RECOVERY_HOLD',
            'extra_group': runtime.RESOURCE,
        }.get(changed, runtime.UNVERIFIED)
        assert failure.value.code == expected
        assert not issues
    assert not locks and record['state'] == 'PREPARING'


@pytest.mark.parametrize('held', (False, True))
def test_preparation_issue_holds_the_host_guard_but_unit_launch_does_not(held, monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.management import runtime_start as runtime

    class ExpectedLaunch(Exception):
        pass

    locked = False
    events = []
    boot = str(uuid4())
    common = {'start_operation_id': str(uuid4()), 'environment_id': str(uuid4())}
    plan = {'memory_bytes': 256 * 1024**2, 'tasks': 128, 'cpu_percent': 50}
    command = [str(Path('/fixed/prepare'))]

    @contextmanager
    def host_admission():
        nonlocal locked
        if held:
            raise EnvironmentFailure('HOST_RECOVERY_HOLD')
        locked = True
        try:
            yield
        finally:
            locked = False

    def issue(fd, name, value):
        assert locked and value['state'] == 'ISSUED'
        events.append('issued')

    def launch(unit, properties, args):
        assert not locked and args is command
        events.append('launch')
        raise ExpectedLaunch()

    monkeypatch.setattr(runtime, 'machine_clock', lambda: (boot, 1))
    monkeypatch.setattr(runtime, 'preparation_record', lambda *_: None)
    monkeypatch.setattr(runtime, 'unit_facts', lambda _: {'LoadState': 'not-found'})
    monkeypatch.setattr(runtime, 'write_record', issue)
    monkeypatch.setattr(runtime, 'launch_preparation_unit', launch)
    environment = SimpleNamespace(host_admission=host_admission)
    if held:
        with pytest.raises(EnvironmentFailure, match='HOST_RECOVERY_HOLD'):
            runtime.finish_preparation(None, common, plan, environment, command, launch=True)
        assert not events
    else:
        with pytest.raises(ExpectedLaunch):
            runtime.finish_preparation(None, common, plan, environment, command, launch=True)
        assert events == ['issued', 'launch']
    assert not locked
