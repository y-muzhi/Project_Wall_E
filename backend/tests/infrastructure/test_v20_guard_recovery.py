"""Narrow recovery permission policy ports; no deployed-program admission claim."""

from contextlib import contextmanager
from dataclasses import replace
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_recovery as recovery
from backend.app.infrastructure.guard_backend_program import POLICY_VERSION, BackendProgramAdmission
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.guard_controller_records import GuardControllerRegistration
from backend.app.infrastructure.guard_request_header import PROTOCOL, _parse
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_executable_pin import ExecutableIdentity
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_process import (
    NativeProcessIdentity,
    NativeProcessObservation,
)


def facts():
    native = NativeProcessIdentity(
        123,
        '1' * 16,
        r'C:\Backend\walle-backend.exe',
        'S-1-5-21-1',
        None,
        False,
        False,
        False,
    )
    binding = GuardControllerBinding('a' * 64, str(uuid4()), native)
    old_binding = GuardControllerBinding(
        'a' * 64, str(uuid4()), replace(native, pid=124, creation_time_hex='2' * 16)
    )
    image = ExecutableIdentity(
        FileIdentity(native.image_path, '3' * 16, '4' * 32, False, 'NTFS'),
        16,
        'b' * 64,
        'win-x64',
    )
    admission = BackendProgramAdmission(
        POLICY_VERSION, 'REGISTERED-BACKEND-PROGRAM', 'c' * 64, 'd' * 64
    )
    current = GuardControllerRegistration(
        binding,
        admission.program_ref,
        admission.manifest_sha256,
        image,
        '2026-11-06T00:00:00.000Z',
        admission,
    )
    old = replace(
        current, binding=old_binding, backend_admission=replace(admission, evidence_sha256='e' * 64)
    )
    return current, old, admission


def test_same_private_program_provenance_does_not_require_reusing_old_process_or_admission_digest():
    current, old, admission = facts()
    assert current.binding.controller != old.binding.controller
    assert current.backend_admission != old.backend_admission
    assert (
        recovery.require_recovery_program_provenance(current, old, current.binding, admission)
        is None
    )


@pytest.mark.parametrize(
    'change',
    [
        lambda old: replace(old, backend_admission=None),
        lambda old: replace(old, binding=replace(old.binding, installation_ref='f' * 64)),
        lambda old: replace(
            old,
            binding=replace(
                old.binding, controller=replace(old.binding.controller, user_sid='S-1-5-21-2')
            ),
        ),
        lambda old: replace(old, backend_program_ref='OTHER-REGISTERED-PROGRAM'),
        lambda old: replace(old, backend_package_sha256='f' * 64),
        lambda old: replace(old, image=replace(old.image, sha256='f' * 64)),
        lambda old: replace(old, image=replace(old.image, byte_count=17)),
        lambda old: replace(
            old, backend_admission=replace(old.backend_admission, policy_version='OTHER')
        ),
    ],
)
def test_metadata_missing_program_wrong_installation_user_or_image_cannot_be_recovered(change):
    current, old, admission = facts()
    with pytest.raises(recovery.GuardRecoveryUnknown):
        recovery.require_recovery_program_provenance(
            current, change(old), current.binding, admission
        )


def test_current_admission_and_current_private_registration_must_also_match():
    current, old, admission = facts()
    for actual in [
        replace(current, backend_admission=None),
        replace(current, backend_admission=replace(admission, evidence_sha256='f' * 64)),
        replace(current, binding=old.binding),
    ]:
        with pytest.raises(recovery.GuardRecoveryUnknown):
            recovery.require_recovery_program_provenance(actual, old, current.binding, admission)


@pytest.fixture
def policy_port(monkeypatch):
    # This port covers decision/order/scope only. Production requires exact
    # original Native owners and a ProtectedBackendProgram constructor success.
    current, old, admission = facts()
    journal = SimpleNamespace(_gate=RLock(), _scope_gates={})
    entry = SimpleNamespace(
        gate=RLock(),
        job_ref='original-guard-binding-001',
        scope=old.binding.scope(17, 2, 'original-recovery-nonce-00001'),
    )
    journal.inspect = lambda scope: SimpleNamespace(scope=scope, stop_closed=False)

    class RecordsPort:
        _journal = journal

        def read_seal(self, controller_ref, epoch):
            raise LaunchOutcomeUnknown('Original durable seal missing')

        def read(self, controller_ref, epoch):
            for value in (current, old):
                if (
                    value.binding.controller_ref == controller_ref
                    and value.binding.owner_epoch == epoch
                ):
                    return value
            raise LaunchOutcomeUnknown('ORIGINAL_RECORD_MISSING')

    class ProgramPort:
        active = 0
        peer = SimpleNamespace(_program=SimpleNamespace(verify=lambda: current.image))

        @contextmanager
        def admission(self, **boundary):
            self.active += 1
            try:
                yield admission
            finally:
                self.active -= 1

    class RegistryPort:
        _journal = journal
        _controller_ref = old.binding.controller_ref
        _controller = SimpleNamespace(
            _expected=old.binding.controller,
            _controller=SimpleNamespace(
                observe=lambda: NativeProcessObservation(old.binding.controller, 'EXITED', 0)
            ),
        )

        _watch_source = _controller._controller

        def _entry(self, scope):
            assert scope == entry.scope
            return entry

    program = ProgramPort()
    records = RecordsPort()
    registry = RegistryPort()
    monkeypatch.setattr(recovery, 'ProtectedBackendProgram', ProgramPort)
    monkeypatch.setattr(recovery, 'GuardControllerRecords', RecordsPort)
    monkeypatch.setattr(recovery, 'ControlGitRegistry', RegistryPort)
    monkeypatch.setattr(
        recovery, 'parse_guard_request_header', lambda wire, binding, **kw: _parse(wire, binding)
    )

    def request(action='STOP', binding_ref=entry.job_ref):
        action_input = {
            'recovery': {
                'controller_ref': old.binding.controller_ref,
                'owner_epoch': old.binding.owner_epoch,
            }
        }
        if action == 'OBSERVE':
            action_input['observed_action'] = 'RESUME'
        return _parse(
            {
                'protocol_version': PROTOCOL,
                'action': action,
                'controller_ref': current.binding.controller_ref,
                'owner_epoch': current.binding.owner_epoch,
                'operation_id': 17,
                'step_no': 2,
                'nonce': entry.scope.nonce,
                'binding_ref': binding_ref,
                'input': action_input,
            },
            current.binding,
        )

    def resolve(value=None, **changed):
        return recovery.recover_control_git_scope(
            request() if value is None else value,
            current.binding,
            **{
                'peer': program.peer,
                'program': program,
                'records': records,
                'registry': registry,
                'timeout_ms': 3000,
                'cancelled': lambda: False,
                **changed,
            },
        )

    return SimpleNamespace(
        current=current,
        old=old,
        program=program,
        registry=registry,
        records=records,
        journal=journal,
        entry=entry,
        resolve=resolve,
        request=request,
    )


@pytest.mark.parametrize('action', ['OBSERVE', 'STOP', 'RELEASE'])
def test_policy_port_only_exposes_original_scope_inside_current_program_lease(policy_port, action):
    port = policy_port
    with port.resolve(port.request(action)) as target:
        assert target.registry is port.registry
        assert target.scope == port.entry.scope
        assert target.action == action
        assert target.binding_ref == port.entry.job_ref
        assert port.program.active == 1
        assert not hasattr(target, 'stopped')
        assert not hasattr(target, 'cleanup_complete')
    assert port.program.active == 0


@pytest.mark.parametrize('state', ['RUNNING', 'UNKNOWN'])
def test_registry_closed_boolean_does_not_substitute_actual_exit_or_durable_domain_seal(
    policy_port, state
):
    port = policy_port
    port.registry._admission_closed = True
    port.registry._controller._controller.observe = lambda: NativeProcessObservation(
        port.old.binding.controller, state, None
    )
    with pytest.raises(recovery.GuardRecoveryUnknown, match='EXIT_OR_RELIABLE_CLOSURE'):
        with port.resolve():
            pytest.fail('No permit for active or unknown old controller')
    assert port.program.active == 0


def test_original_observation_error_never_reopens_old_pid_or_treats_absence_as_exit(policy_port):
    def unknown():
        raise OSError('Original process handle unavailable')

    policy_port.registry._controller._controller.observe = unknown
    with pytest.raises(recovery.GuardRecoveryUnknown, match='EXIT_OR_RELIABLE_CLOSURE'):
        with policy_port.resolve():
            pytest.fail('No proof of exit')


@pytest.mark.parametrize('change', ['binding', 'journal', 'process_identity', 'fence', 'entry'])
def test_policy_port_rejects_cross_resource_journal_or_original_owner_mismatch(policy_port, change):
    port = policy_port
    request = port.request()
    if change == 'binding':
        request = port.request(binding_ref='other-guard-binding-001')
    elif change == 'journal':
        port.registry._journal = object()
    elif change == 'process_identity':
        port.registry._controller._expected = port.current.binding.controller
    elif change == 'fence':
        port.journal.inspect = lambda _: None
    else:
        port.entry.scope = port.current.binding.scope(17, 2, port.entry.scope.nonce)
        # Preserve lookup behavior so the explicit stored entry check is covered.
        port.registry._entry = lambda _: port.entry
    with pytest.raises(recovery.GuardRecoveryUnknown):
        with port.resolve(request):
            pytest.fail('No cross-scope authority')


def test_guard_restart_missing_original_registry_remains_unknown(policy_port):
    with pytest.raises(recovery.GuardRecoveryUnknown, match='ORIGINAL_GUARD_RESOURCE_OWNERS'):
        with policy_port.resolve(registry=None):
            pytest.fail('No old PID or Job-name reconstruction')


def test_current_program_json_claim_and_forged_header_snapshot_are_not_permission(policy_port):
    port = policy_port
    with pytest.raises(recovery.GuardRecoveryUnknown, match='ACTUAL_PROTECTED'):
        with port.resolve(program={'admitted': True}):
            pytest.fail('No claim admission')
    malformed = replace(port.request(), recovery=None)
    with pytest.raises(recovery.GuardRecoveryUnknown, match='SELECTOR_REQUIRED'):
        with port.resolve(malformed):
            pytest.fail('No header/selector disagreement')


def test_verified_durable_domain_seal_port_allows_original_scope_without_claiming_process_exit(
    policy_port,
):
    port = policy_port
    seal = object()
    port.registry._controller._controller.observe = lambda: NativeProcessObservation(
        port.old.binding.controller, 'RUNNING', None
    )
    port.records.read_seal = lambda *args: seal
    port.journal.verify_controller_closure = lambda *args: seal
    port.journal.inspect = lambda scope: SimpleNamespace(scope=scope, stop_closed=True)
    with port.resolve() as target:
        assert target.scope == port.entry.scope
        assert not hasattr(target, 'process_exited')


def test_seal_without_complete_original_scope_closure_is_not_permission(policy_port):
    port = policy_port
    seal = object()
    port.registry._controller._controller.observe = lambda: NativeProcessObservation(
        port.old.binding.controller, 'UNKNOWN', None
    )
    port.records.read_seal = lambda *args: seal
    port.journal.verify_controller_closure = lambda *args: seal
    with pytest.raises(recovery.GuardRecoveryUnknown, match='EXIT_OR_RELIABLE_CLOSURE'):
        with port.resolve():
            pytest.fail('A marker alone does not complete original dispatch closure')


def test_active_journal_scope_returns_unknown_without_waiting_for_original_dispatch(policy_port):
    port = policy_port
    port.journal._scope_gates[port.entry.scope.key] = SimpleNamespace(users=1)
    with pytest.raises(recovery.GuardRecoveryUnknown, match='STILL_IN_FLIGHT'):
        with port.resolve():
            pytest.fail('No blocking query while original callback is in flight')


def test_recovery_uses_original_watch_copy_without_waiting_on_token_source_port(policy_port):
    port = policy_port

    def forbidden():
        raise AssertionError('Do not wait on the actor token source')

    port.registry._controller._controller = SimpleNamespace(observe=forbidden)
    with port.resolve() as target:
        assert target.scope == port.entry.scope
