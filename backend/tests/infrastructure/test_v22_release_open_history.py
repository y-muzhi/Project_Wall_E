"""Read only the original fixed release result while host recovery blocks admission."""

import os
import runpy
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest


@pytest.fixture
def observation(monkeypatch):
    pytest.importorskip('fcntl')
    from backend.app.infrastructure import environment_release_open as release

    events = []

    def check_hold(*, offline=False):
        events.append('hold:offline' if offline else 'hold:online')
        if not offline:
            raise EnvironmentFailure('HOST_RECOVERY_HOLD')

    def check_identity(*, maintenance):
        assert maintenance
        events.append('check:maintenance')

    installation = SimpleNamespace(
        check_identity=check_identity,
        check_hold=check_hold,
        directory=lambda native, kind: nullcontext(0),
        environment_id=str(uuid4()),
        data_generation=str(uuid4()),
        deployment_id=str(uuid4()),
        configuration_sha256='a' * 64,
        application_uid=12000,
        group=12000,
    )
    plan = {
        'operation_id': str(uuid4()),
        'run_id': str(uuid4()),
        'gateway_verification': {'sha256': 'b' * 64},
        'release_verification': {'sha256': 'c' * 64},
    }
    pin = 'd' * 64
    name = f'open-{plan["run_id"]}.v1.json'
    closed = {
        'admission': 'CLOSED',
        'control_revision': 12,
        'last_opened_deployment_id': None,
        'open_receipt_ref': None,
    }
    transition = {'after': closed, 'after_sha256': digest(canonical(closed))}
    plan['control_sha256'] = transition['after_sha256']
    plan['transition_sha256'] = digest(canonical(transition))
    record = {
        **release.expected_open_receipt(installation, plan, transition, pin),
        'opened_at': release.now(),
    }
    state = SimpleNamespace(closed=closed, control=closed, record=None)
    monkeypatch.setattr(release, 'read_release_transition', lambda fd, owner, op: transition)
    monkeypatch.setattr(release, 'read_control', lambda fd, owner: state.control)

    def read_entry(fd, entry, *, owner, group):
        assert (entry, owner, group) == (name, installation.application_uid, installation.group)
        if state.record is None:
            raise FileNotFoundError(entry)
        return canonical(state.record)

    def cannot_write(*args, **kwargs):
        pytest.fail('A read-only observation attempted to write release control.')

    monkeypatch.setattr(release, 'read_entry', read_entry)
    monkeypatch.setattr(release, 'persisted_write', cannot_write)
    return release, installation, plan, pin, name, record, events, state


@pytest.mark.parametrize(
    'control,record_kind,result',
    [
        ('SELECTED', 'MISSING', 'RELEASE_OPEN_NOT_PREPARED'),
        ('SELECTED', 'ORIGINAL', 'PENDING_RECONCILIATION'),
        ('OPEN', 'ORIGINAL', 'RELEASE_OPEN_CONFIRMED'),
        ('STOPPED', 'ORIGINAL', 'RELEASE_OPEN_CONFIRMED'),
        ('OPEN', 'FOREIGN', None),
        ('STALE', 'ORIGINAL', None),
    ],
)
def test_frozen_host_observes_only_the_exact_original_receipt(
    observation, control, record_kind, result
):
    release, installation, plan, pin, name, record, events, state = observation
    if control in ('OPEN', 'STOPPED', 'STALE'):
        state.control = {
            **state.closed,
            'admission': 'OPEN' if control == 'OPEN' else 'CLOSED',
            'control_revision': 13 if control == 'OPEN' else 14,
            'last_opened_deployment_id': installation.deployment_id,
            'open_receipt_ref': name if control != 'STALE' else f'open-{uuid4()}.v1.json',
        }
    if record_kind != 'MISSING':
        state.record = record if record_kind == 'ORIGINAL' else {**record, 'start_sha256': 'e' * 64}
    if result is None:
        with pytest.raises(EnvironmentFailure, match='RELEASE_OPEN_UNVERIFIED'):
            release.observe_release_open(None, installation, plan, pin)
    else:
        outcome = release.observe_release_open(None, installation, plan, pin)
        assert outcome['status'] == result
        assert outcome['admission'] == state.control['admission']
        assert outcome['control_revision'] == state.control['control_revision']
        if result == 'RELEASE_OPEN_CONFIRMED':
            assert outcome['open_receipt_sha256'] == digest(canonical(record))
    assert events == ['check:maintenance', 'hold:offline']


@pytest.mark.parametrize('missing_fact', ('process', 'listener'))
def test_unavailable_gateway_observation_rejects_the_original_opening_proof(
    monkeypatch, observation, missing_fact
):
    release, *_ = observation
    process = {
        'pid': 25000,
        'uid': 12000,
        'start_ticks': '3109',
        'boot_id': str(uuid4()),
        'listener_inode': '3994',
    }

    def disappeared(*args):
        raise FileNotFoundError('original gateway observation is unavailable')

    def process_epoch(pid):
        assert pid == process['pid']
        return process['start_ticks'], process['boot_id']

    def listener_inodes(pid, port):
        assert pid == os.getpid() and port == 9443
        return {process['listener_inode']}

    monkeypatch.setattr(
        release, 'process_epoch', disappeared if missing_fact == 'process' else process_epoch
    )
    monkeypatch.setattr(
        release, 'listener_inodes', disappeared if missing_fact == 'listener' else listener_inodes
    )
    with pytest.raises(EnvironmentFailure, match='RELEASE_OPEN_UNVERIFIED'):
        release.assert_gateway({'verified_at': release.now(), 'gateway_process': process}, 9443)


@pytest.mark.parametrize('sidecar_suffix', ('-wal', '-shm', '-journal', None))
def test_release_open_checks_sidecars_before_the_first_sqlite_read(
    observation, tmp_path, sidecar_suffix
):
    release, *_ = observation
    events = []
    path = tmp_path / 'wall-e.sqlite'
    scope = object.__new__(release.ReleaseOpenScope)
    scope.lock = SimpleNamespace(assert_owned=lambda: events.append('assert-lock'))
    scope.database = SimpleNamespace(path=path, preflight=lambda: events.append('read-sqlite'))

    if sidecar_suffix is None:
        scope.preflight()
        assert events == ['assert-lock', 'read-sqlite']
    else:
        sidecar = path.with_name(path.name + sidecar_suffix)
        sidecar.write_bytes(b'original sidecar')
        with pytest.raises(EnvironmentFailure, match='RELEASE_OPEN_UNVERIFIED'):
            scope.preflight()
        assert events == ['assert-lock']
        assert sidecar.read_bytes() == b'original sidecar'


def test_release_observation_launcher_admits_a_protected_offline_read(monkeypatch, observation):
    from backend.app.infrastructure import environment_command, environment_lock, sqlite_runtime

    release, installation, plan, pin, *_ = observation
    project = Path(__file__).resolve().parents[3]
    launcher = runpy.run_path(str(project / 'tools/linux_runtime/manage_registry.py'))
    args = SimpleNamespace(
        action='_observe-release-open',
        root=Path('/private/runtime'),
        home=Path('/private/home'),
        temporary=Path('/private/tmp'),
        sha256='a' * 64,
        program_sha256='b' * 64,
        release_open_operation=plan['operation_id'],
        release_open_policy=Path('/private/release-open-policy.v1.json'),
        release_open_policy_sha256=pin,
    )
    active = object()
    native = object()
    calls = []

    def admission_inputs(actual_args, actual_active, program, *, offline=False):
        assert (actual_args, actual_active, program) == (args, active, args.program_sha256)
        installation.check_hold(offline=offline)
        calls.append('admit')
        return installation, object()

    def open_inputs(owner, operation, path, actual_pin):
        assert (owner, operation, path, actual_pin) == (
            installation,
            args.release_open_operation,
            args.release_open_policy,
            pin,
        )
        calls.append('inputs')
        return plan

    def observe(actual_native, owner, actual_plan, actual_pin):
        assert (actual_native, owner, actual_plan, actual_pin) == (native, installation, plan, pin)
        calls.append('observe')
        return {'status': 'RELEASE_OPEN_NOT_PREPARED'}

    monkeypatch.setattr(os, 'umask', lambda _: 0o077)
    monkeypatch.setattr(sqlite_runtime, 'bind_linux_runtime', lambda check: None)
    monkeypatch.setattr(environment_lock, 'NativeEnvironmentFiles', lambda runtime: native)
    monkeypatch.setattr(environment_command, 'admission_inputs', admission_inputs)
    monkeypatch.setattr(release, 'open_inputs', open_inputs)
    monkeypatch.setattr(release, 'observe_release_open', observe)
    entry = {
        'minimum_environment': lambda home, tmp: dict(os.environ),
        'demand': lambda condition, reason: None,
        'admit_target': lambda root, runtime_hash, tmp: ({}, (), ()),
        'verify_target_imports': lambda root, manifest: None,
        'validate_mappings': lambda *args: None,
        'require_active': lambda: active,
    }
    assert launcher['target'](args, entry) == {'status': 'RELEASE_OPEN_NOT_PREPARED'}
    assert calls == ['admit', 'inputs', 'observe']
