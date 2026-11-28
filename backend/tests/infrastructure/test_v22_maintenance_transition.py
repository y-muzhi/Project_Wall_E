"""Keep original closed maintenance evidence stable during host recovery."""

from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure import environment_maintenance as maintenance
from backend.app.infrastructure.environment_control import CONTROL_NAME, maintained_control
from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest


@pytest.mark.parametrize('action', ('enter', 'cancel'))
@pytest.mark.parametrize('freeze', (False, True))
def test_maintenance_writes_follow_host_admission(monkeypatch, action, freeze):
    reason = 'HOST_RECOVERY_HOLD'
    original = {
        'admission': 'CLOSED',
        'closed_reason': 'NORMAL_STOP',
        'control_revision': 10,
        'operation_id': str(uuid4()),
        'outbound_hold': False,
    }
    operation = str(uuid4())
    pin = 'a' * 64
    subjects = {key: str(uuid4()) for key in maintenance.SCOPE}
    plan = {
        **subjects,
        'operation_id': operation,
        'expected_control_revision': original['control_revision'],
        'expected_control_sha256': digest(canonical(original)),
    }
    intent = {'operation_id': operation, 'plan_sha256': pin, 'before': original}
    initial = original if action == 'enter' else maintained_control(original, operation, pin)
    state = SimpleNamespace(control=initial, frozen=False, checked=False, guarded=False)
    writes = []

    def before_writing():
        assert state.guarded and not state.frozen
        assert state.checked

    @contextmanager
    def admission():
        assert state.checked
        if state.frozen:
            raise EnvironmentFailure(reason)
        state.guarded = True
        try:
            yield
        finally:
            state.guarded = False

    installation = SimpleNamespace(
        host_admission=admission,
        lock=lambda native: nullcontext(SimpleNamespace(assert_owned=lambda: None)),
        directory=lambda native, kind: nullcontext(0),
    )

    def verify_source(*arguments):
        assert not state.frozen
        state.checked = True
        state.frozen = freeze

    def persist(fd, name, raw, *, mode, replace=False):
        before_writing()
        if replace:
            assert name == CONTROL_NAME
            state.control = maintenance.decode(raw, maintenance.UNKNOWN)
        writes.append(name)

    def fact(fd, installation, name, record, *, create=False):
        if create:
            before_writing()
            writes.append(name)
        return create

    monkeypatch.setattr(maintenance, 'read_control', lambda fd, owner: state.control)
    monkeypatch.setattr(
        maintenance, 'maybe_intent', lambda *args: None if action == 'enter' else intent
    )
    monkeypatch.setattr(maintenance, 'verify_source', verify_source)
    monkeypatch.setattr(maintenance, 'require_before_selection', lambda fd, operation: None)
    monkeypatch.setattr(maintenance, 'persisted_write', persist)
    monkeypatch.setattr(maintenance, 'write_fact', fact)
    arguments = (None, installation, None, plan, pin, action)
    if freeze:
        with pytest.raises(EnvironmentFailure, match=reason):
            maintenance.select_maintenance(*arguments)
        assert state.control == initial and writes == []
    else:
        selected = maintenance.select_maintenance(*arguments)
        if action == 'enter':
            assert selected['status'] == 'MAINTENANCE_CLOSED'
            assert state.control == maintained_control(original, operation, pin)
            assert writes == [maintenance.maintenance_name(operation), CONTROL_NAME]
        else:
            request, proof, _ = maintenance.cancellation_facts(intent)
            assert selected['status'] == 'MAINTENANCE_CANCELLED'
            assert state.control == maintenance.released_control(original)
            assert writes == [request, CONTROL_NAME, proof]
    assert not state.guarded


@pytest.mark.parametrize('action', ('enter', 'cancel', 'observe'))
def test_maintenance_launcher_keeps_frozen_host_observation_read_only(monkeypatch, action):
    program = Path('/fixed/application')
    plan = {
        'program': str(program),
        'program_sha256': 'b' * 64,
        'installation_sha256': 'c' * 64,
        **{key: str(uuid4()) for key in maintenance.SCOPE},
    }
    args = SimpleNamespace(
        maintenance_action=action,
        maintenance_policy=Path('/fixed/environment-maintenance.v1.json'),
        maintenance_policy_sha256='d' * 64,
        anchor=Path('/fixed/installation.v1.json'),
        anchor_sha256=plan['installation_sha256'],
    )
    checked = []
    installation = SimpleNamespace(
        description={},
        check_identity=lambda *, maintenance: checked.append(maintenance),
        **{key: plan[key] for key in maintenance.SCOPE},
    )
    monkeypatch.setattr(maintenance, 'load_policy', lambda path, pin: plan)

    def admission_inputs(*items, offline=False):
        if not offline:
            raise EnvironmentFailure('HOST_RECOVERY_HOLD')
        return installation, None

    def observe(native, installation, release, plan, pin, mode):
        assert mode == 'observe'
        return {'status': 'MAINTENANCE_CLOSED'}

    monkeypatch.setattr(maintenance, 'admission_inputs', admission_inputs)
    monkeypatch.setattr(maintenance, 'select_maintenance', observe)
    entry = {'verify_program': lambda project: plan['program_sha256']}
    if action == 'observe':
        assert maintenance.run_maintenance(None, None, args, entry) == {
            'status': 'MAINTENANCE_CLOSED'
        }
        assert checked == [True]
    else:
        with pytest.raises(EnvironmentFailure, match='HOST_RECOVERY_HOLD'):
            maintenance.run_maintenance(None, None, args, entry)
        assert checked == []
