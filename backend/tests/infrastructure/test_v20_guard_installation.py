"""Installer contracts and explicit native ports; never install or control an OS service."""

import ctypes
import os
from ctypes import wintypes
from hashlib import sha256
from types import SimpleNamespace

import pytest

from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import current_operator_sid
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure import test_v20_guard_bootstrap_inspection as fixtures
from tools import windows_guard_install_contract as contract
from tools import windows_guard_install_identity as identity
from tools import windows_guard_install_service as services
from tools import windows_guard_installation as installation

programs = fixtures.programs
prepared = fixtures.prepared
tmp_path = fixtures.tmp_path
group = fixtures.group
controller = fixtures.controller
ordinary_controller = fixtures.ordinary_controller


@pytest.mark.parametrize(
    'field,value',
    [
        ('scope', 'INSTALL_EVERYTHING'),
        ('schema_version', True),
        ('installer_program_sha256', 'b' * 64),
        ('installation_root', 'C:\\Other'),
        ('backend_sid', contract.SYSTEM),
        ('deployment_sha256', 'c' * 64),
        ('service.required_privileges', ['SeDebugPrivilege']),
        ('service.account', 'LocalService'),
        ('service.start_type', 'AUTO_START'),
        ('service.image_path', 'unregistered.exe'),
        ('permissions.journal_owner', contract.ADMINISTRATORS),
        ('permissions.installer_own_temporary_privileges', ['SeBackupPrivilege']),
        ('permissions.program_owner', contract.SYSTEM),
        ('permissions.program_access', {contract.SYSTEM: contract.FULL_FILE_ACCESS}),
        ('limits_ms.start', 99999999),
        ('programs.guard.member_count', 1),
        ('bootstrap.plan_sha256', 'e' * 64),
    ],
)
def test_rehashed_altered_request_cannot_expand_original_sources_or_system_scope(
    group, field, value
):
    with fixtures.opened(group) as inputs:
        request = contract.make_installation_request(inputs, 'a' * 64)
        parent = request
        parts = field.split('.')
        for part in parts[:-1]:
            parent = parent[part]
        parent[parts[-1]] = value
        raw = _bytes(request)
        with pytest.raises(contract.GuardInstallationError, match='BINDING_DIFFERS'):
            contract.verify_installation_request(raw, sha256(raw).hexdigest(), inputs, 'a' * 64)
    assert not group[2].exists()


def test_actual_original_request_is_exact_and_pins_private_journal_and_four_privileges(group):
    with fixtures.opened(group) as inputs:
        request = contract.make_installation_request(inputs, 'a' * 64)
        raw = _bytes(request)
        assert (
            contract.verify_installation_request(raw, sha256(raw).hexdigest(), inputs, 'a' * 64)
            == request
        )
        assert request['permissions']['journal_access'] == {
            contract.SYSTEM: contract.FULL_FILE_ACCESS
        }
        assert request['service']['required_privileges'] == list(contract.SERVICE_PRIVILEGES)
        assert request['permissions']['service_access'][request['backend_sid']] == 0x20005
        assert request['limits_ms'] == {'start': 180000, 'probe_hold': 90000, 'stop': 150000}
        for altered in (b' ' + raw, raw + b'\n', raw[:-1]):
            with pytest.raises(contract.GuardInstallationError):
                contract.verify_installation_request(
                    altered, sha256(altered).hexdigest(), inputs, 'a' * 64
                )
        with pytest.raises(contract.GuardInstallationError):
            contract.verify_installation_request(raw, 'f' * 64, inputs, 'a' * 64)


def test_actual_ordinary_user_is_rejected_before_any_installation_native_port():
    with ObservedProcess(os.getpid()) as own:
        assert not own.identity.is_elevated
        with pytest.raises(contract.GuardInstallationError, match='ELEVATED_SAME_USER'):
            identity.InstallationOperator(current_operator_sid())


def test_actual_original_external_reader_and_new_root_binding(group, ordinary_controller):
    reader, _ = ordinary_controller
    with fixtures.opened(group, reader=reader) as inputs:
        destination = group[2]
        destination.mkdir()
        with LocalPathGuard(destination, directory=True) as original:
            inputs.bind_new_installation_root(original)
            inputs.verify()
            with pytest.raises(RuntimeError, match='ORIGINAL_NEW_INSTALLATION'):
                inputs.bind_new_installation_root(original)
    with fixtures.opened(group, reader=reader, allow_existing_target=True) as inputs:
        inputs.verify()


@pytest.mark.parametrize('pointer_offset', [-2, 0, 7, 9, 64, 65])
def test_native_service_text_never_reads_outside_pinned_buffer(pointer_offset):
    raw = ctypes.create_string_buffer(64)
    with pytest.raises(contract.GuardInstallationError, match='POINTER_OUTSIDE_BUFFER'):
        services._text(raw, ctypes.addressof(raw) + pointer_offset, 8)


def test_native_service_multistring_and_size_bounds_are_strict():
    raw = ctypes.create_string_buffer(24)
    ctypes.memmove(ctypes.addressof(raw) + 8, 'A\0B\0\0'.encode('utf-16-le'), 10)
    assert services._text(raw, ctypes.addressof(raw) + 8, 8, multiple=True) == ('A', 'B')
    ctypes.memset(ctypes.addressof(raw) + 8, 65, 16)
    with pytest.raises(contract.GuardInstallationError, match='UNTERMINATED'):
        services._text(raw, ctypes.addressof(raw) + 8, 8, multiple=True)
    for size in (0, 3, 8193):

        def query(data, count, needed, value=size):
            ctypes.cast(needed, ctypes.POINTER(wintypes.DWORD)).contents.value = value
            ctypes.set_last_error(122)
            return False

        with pytest.raises(contract.GuardInstallationError, match='SIZE_UNSUPPORTED'):
            services._buffer(query, 4)


class ServicePort:
    def __init__(self, existing=False):
        self.calls = []
        self.existing = existing

    def OpenSCManagerW(self, *args):
        self.calls.append(('manager', args[-1]))
        return 11

    def OpenServiceW(self, *args):
        self.calls.append(('open', args[1]))
        ctypes.set_last_error(0 if self.existing else 1060)
        return 12 if self.existing else None

    def CloseServiceHandle(self, handle):
        self.calls.append(('close', handle))
        return True

    def CreateServiceW(self, *args):
        self.calls.append(('create', args))
        return 13

    def SetServiceObjectSecurity(self, *args):
        self.calls.append(('security', args[:2]))
        return True

    def ChangeServiceConfig2W(self, handle, kind, value):
        if kind == 6:
            pointer = ctypes.cast(value, ctypes.POINTER(services.RequiredPrivileges)).contents.names
            names = ctypes.wstring_at(
                pointer, sum(len(v) + 1 for v in contract.SERVICE_PRIVILEGES) + 1
            )
            self.calls.append(('privileges', names))
        else:
            self.calls.append(('config', kind))
        return True


def service_fixture(monkeypatch, *, existing=False):
    operator = object.__new__(identity.InstallationOperator)
    monkeypatch.setattr(identity.InstallationOperator, 'verify', lambda self: self)
    port = ServicePort(existing)
    monkeypatch.setattr(services, 'service_api', lambda: port)
    request = {
        'installation_ref': 'a' * 64,
        'backend_sid': 'S-1-5-21-1-2-3-1001',
        'service': {
            'name': services.guard_service_name('a' * 64),
            'image_path': '"C:\\Fixed\\walle-guard.exe" --fixed',
        },
    }
    return operator, port, request


def test_existing_service_is_never_changed_or_started(monkeypatch):
    operator, port, request = service_fixture(monkeypatch, existing=True)
    with pytest.raises(contract.GuardInstallationError, match='CREATE_ONLY'):
        services.NativeGuardService(request, operator, new=True)
    assert not any(call[0] in ('create', 'security', 'config', 'privileges') for call in port.calls)
    assert ('close', 12) in port.calls and ('close', 11) in port.calls


def test_new_service_registration_seals_security_and_privileges_without_start(monkeypatch):
    operator, port, request = service_fixture(monkeypatch)

    class Descriptor:
        _descriptor = 17

        def __init__(self, *args, **kwargs):
            pass

        def apply(self, handle, **options):
            assert options == {'object_type': 2}
            port.calls.append(('protected-dacl', handle, options))

        def close(self):
            port.calls.append(('descriptor-close',))

    monkeypatch.setattr(services, 'NativeDescriptor', Descriptor)
    monkeypatch.setattr(services.NativeGuardService, 'verify', lambda self: None)
    monkeypatch.setattr(
        services.NativeGuardService, 'status', lambda self: SimpleNamespace(state=1)
    )
    with services.NativeGuardService(request, operator, new=True) as service:
        service.create()
        with pytest.raises(contract.GuardInstallationError, match='CREATE_ONLY'):
            service.create()
    create = next(value[1] for value in port.calls if value[0] == 'create')
    assert create[4:7] == (16, 3, 1)
    assert create[11] == 'LocalSystem'
    assert any(value[0] == 'protected-dacl' for value in port.calls)
    names = next(value[1] for value in port.calls if value[0] == 'privileges')
    assert names == '\0'.join(contract.SERVICE_PRIVILEGES) + '\0\0'
    assert ('config', 2) in port.calls and ('config', 4) in port.calls


def test_probe_channel_unknown_close_still_closes_other_known_owners_once():
    calls = []

    class Owner:
        def __init__(self, name, fail=False):
            self.name, self.fail = name, fail

        def close(self):
            calls.append(self.name)
            if self.fail:
                raise OSError('injected unknown closure')

    channel = object.__new__(installation.ProbeChannel)
    channel._closed = channel._close_failed = False
    channel._orphaned = []
    channel._owners = [Owner('package'), Owner('source', True)]
    with pytest.raises(contract.GuardInstallationError) as result:
        channel.close()
    assert result.value.retained_owner is channel
    assert calls == ['source', 'package']
    with pytest.raises(contract.GuardInstallationError, match='PREVIOUSLY'):
        channel.close()
    assert calls == ['source', 'package']


@pytest.mark.parametrize('prior,missing', [(0, False), (2, False), (0, True)])
def test_restore_scope_only_changes_existing_own_fixed_privilege_and_restores(
    monkeypatch, prior, missing
):
    operator = object.__new__(identity.InstallationOperator)
    operator._kernel = operator._security = operator._token = object()
    monkeypatch.setattr(identity.InstallationOperator, 'verify', lambda self: self)
    scope = object.__new__(identity.RestorePrivilege)
    scope.operator = operator
    scope._closed = scope._close_failed = False
    scope._snapshot = None
    scope._key = 42
    state = {7: 2}
    if not missing:
        state[42] = prior
    original = dict(state)
    changes = []
    monkeypatch.setattr(scope, '_state', lambda: (('unchanged-group',), dict(state)))

    def adjust(value):
        changes.append((42, value))
        state[42] = value

    monkeypatch.setattr(scope, '_adjust', adjust)
    if missing:
        with (
            pytest.raises(contract.GuardInstallationError, match='EXISTING_INSTALLER'),
            scope,
        ):
            pytest.fail('Missing privilege must not be added')
        assert changes == []
    else:
        with scope:
            assert state[42] == prior | 2
        assert state == original
        assert all(key == 42 for key, _ in changes)
    scope.close()


def test_failed_start_does_not_stop_a_service_started_elsewhere(monkeypatch):
    operator, port, request = service_fixture(monkeypatch, existing=True)
    request['limits_ms'] = {'start': 1, 'stop': 1}
    port.StartServiceW = lambda *args: False
    monkeypatch.setattr(services.NativeGuardService, 'verify', lambda self: None)
    monkeypatch.setattr(
        services.NativeGuardService, 'status', lambda self: SimpleNamespace(state=1)
    )
    with services.NativeGuardService(request, operator, new=False) as service:
        with pytest.raises(contract.GuardInstallationError, match='SERVICE_START_FAILED'):
            service.start(lambda: False)
        # If stop_owned queried status or sent STOP, the missing native port would fail.
        monkeypatch.setattr(
            service, 'status', lambda: pytest.fail('Failed start acquired no stop ownership')
        )
        service.stop_owned()
        assert service._start_attempted and not service._start_accepted


def test_actual_service_security_read_uses_se_service_without_any_changes():
    from tools.windows_guard_install_files import NativeDescriptor

    api = services.service_api()
    manager = api.OpenSCManagerW(None, None, 1)
    assert manager
    handle = None
    descriptor = NativeDescriptor(
        contract.ADMINISTRATORS,
        contract.service_rights(current_operator_sid()),
        directory=False,
    )
    try:
        handle = api.OpenServiceW(manager, 'Schedule', 0x20000)
        assert handle
        with pytest.raises(contract.GuardInstallationError) as result:
            descriptor.verify_handle(handle, object_type=services.SERVICE_OBJECT_TYPE)
        assert str(result.value) != 'INSTALLATION_ORIGINAL_SECURITY_UNAVAILABLE'
        assert not descriptor._reads
    finally:
        descriptor.close()
        if handle:
            assert api.CloseServiceHandle(handle)
        assert api.CloseServiceHandle(manager)


def test_system_driver_requires_explicit_current_authorization_before_any_io(monkeypatch):
    from backend.tests.infrastructure import v20_guard_system_bootstrap_worker as worker

    monkeypatch.setattr(worker, 'execute', lambda value: pytest.fail('No system action allowed'))
    with pytest.raises(SystemExit) as result:
        worker.main(
            [
                '--install',
                '--installer',
                'nonexistent-installer',
                '--installer-sha256',
                'a' * 64,
                '--request',
                'nonexistent-request',
                '--request-sha256',
                'b' * 64,
            ]
        )
    assert result.value.code == 2
    with pytest.raises(RuntimeError, match='Original dedicated installer'):
        worker.AdministratorAction(object(), [], None)


@pytest.mark.parametrize('created', ['0' * 16, 'A' * 16, '123', None])
def test_system_coordination_marker_is_not_original_process_admission(tmp_path, created):
    from backend.tests.infrastructure import v20_guard_system_bootstrap_worker as worker

    with (tmp_path / 'READY').open('xb') as stream:
        stream.write(_bytes({'pid': 1, 'created_at': created}))
    with pytest.raises(RuntimeError, match='readiness differs'):
        worker.verify_ready(tmp_path, SimpleNamespace(poll=lambda: None))


def test_administrator_unknown_handle_close_is_retained_without_retry():
    from backend.tests.infrastructure import v20_guard_system_bootstrap_worker as worker

    calls = []
    action = object.__new__(worker.AdministratorAction)
    action._handle = 17
    action._close_failed = False
    action._kernel = SimpleNamespace(CloseHandle=lambda handle: calls.append(handle) or False)
    with pytest.raises(RuntimeError) as result:
        action.close()
    assert result.value.retained_owner is action and calls == [17]
    with pytest.raises(RuntimeError, match='previously'):
        action.close()
    assert calls == [17]


@pytest.fixture
def user_owned_writer(tmp_path, monkeypatch):
    """Native IO only: isolated user-owned files, never trusted installation ownership."""
    from tools import windows_guard_install_files as files

    actual_descriptor = files.NativeDescriptor
    user = current_operator_sid()
    monkeypatch.setattr(
        files,
        'NativeDescriptor',
        lambda owner, rights, *, directory: actual_descriptor(
            user, {user: contract.FULL_FILE_ACCESS}, directory=directory
        ),
    )
    # The ordinary fixture bypasses only the admin identity port; destination is
    # this test's private temporary subtree. Production does not expose this port.
    operator = object.__new__(identity.InstallationOperator)
    monkeypatch.setattr(identity.InstallationOperator, 'verify', lambda self: self)
    root = tmp_path / 'native-user-io'
    with files.ProtectedInstallationWriter(
        {'installation_root': str(root), 'backend_sid': user}, operator, lambda: None
    ) as writer:
        writer.create_directory(root)
        yield writer


def test_actual_native_new_file_write_and_metadata_read_share_original_source_lock(
    user_owned_writer,
):
    writer = user_owned_writer
    target = writer.root / 'new-fixed-input'
    raw = b'original pinned bytes' * 90000
    original = writer.write_bytes(target, raw)
    with installation.LockedFileSource(target, max_file_bytes=len(raw)) as source:
        assert source.snapshot.file == original
        assert source.snapshot.raw == raw
        handle = writer._open(target, 0x20080)
        try:
            writer._program_file.verify_handle(handle)
        finally:
            writer._close_handle(handle)
    assert target.read_bytes() == raw


def test_actual_native_create_new_refuses_to_replace_an_existing_input(user_owned_writer):
    writer = user_owned_writer
    target = writer.root / 'existing-input'
    writer.write_bytes(target, b'preserve this original')
    with pytest.raises(contract.GuardInstallationError, match='HANDLE_UNAVAILABLE'):
        writer.write_bytes(target, b'replacement forbidden')
    assert target.read_bytes() == b'preserve this original'


def test_actual_native_partial_source_failure_propagates_without_false_success(user_owned_writer):
    writer = user_owned_writer

    class BrokenSource:
        snapshot = SimpleNamespace(byte_count=9, sha256=sha256(b'long-data').hexdigest())

        def consume_verified(self, consume):
            consume(b'part')
            raise OSError('injected original source failure')

    target = writer.root / 'incomplete-new-input'
    with pytest.raises(OSError, match='original source failure'):
        writer.write_file(target, BrokenSource())
    # A failed create-only installation retains its new partial resource; it
    # neither reports success nor overwrites/repairs it on a subsequent attempt.
    assert target.read_bytes() == b'part'
    with pytest.raises(contract.GuardInstallationError, match='HANDLE_UNAVAILABLE'):
        writer.write_bytes(target, b'new-data')
    assert target.read_bytes() == b'part'


def test_actual_native_short_write_is_rejected_and_original_handle_is_closed(
    user_owned_writer, monkeypatch
):
    writer = user_owned_writer
    actual_write = writer._kernel.WriteFile

    def incomplete(handle, data, count, written, overlapped):
        assert actual_write(handle, data, 1, written, overlapped)
        return True

    monkeypatch.setattr(writer._kernel, 'WriteFile', incomplete)
    target = writer.root / 'short-new-input'
    with pytest.raises(contract.GuardInstallationError, match='WRITE_INCOMPLETE'):
        writer.write_bytes(target, b'more-than-one-byte')
    # Opening an exclusive write handle succeeds only if the original native
    # creation handle was actually closed by the failure path.
    with target.open('r+b') as stream:
        assert stream.read() == b'm'


@pytest.mark.parametrize('unknown_part', ['groups', 'other-privilege', 'restore-call'])
def test_restore_scope_retains_unknown_state_and_never_retries_adjustment(
    monkeypatch, unknown_part
):
    operator = object.__new__(identity.InstallationOperator)
    monkeypatch.setattr(identity.InstallationOperator, 'verify', lambda self: self)
    scope = object.__new__(identity.RestorePrivilege)
    scope.operator = operator
    scope._closed = scope._close_failed = False
    scope._snapshot = None
    scope._key = 42
    groups = ['original-group']
    state = {7: 2, 42: 0}
    changes = []
    monkeypatch.setattr(scope, '_state', lambda: (tuple(groups), dict(state)))

    def adjust(value):
        changes.append(value)
        if unknown_part == 'restore-call' and value == 0:
            raise OSError('injected restore result unknown')
        state[42] = value

    monkeypatch.setattr(scope, '_adjust', adjust)
    scope.__enter__()
    if unknown_part == 'groups':
        groups.append('unexpected-group')
    elif unknown_part == 'other-privilege':
        state[7] = 0
    with pytest.raises(contract.GuardInstallationError) as result:
        scope.close()
    assert result.value.retained_owner is scope
    previous_calls = tuple(changes)
    with pytest.raises(contract.GuardInstallationError, match='PREVIOUSLY'):
        scope.close()
    assert tuple(changes) == previous_calls
    assert changes[0] == 2 and changes.count(0) <= 1


def test_service_unknown_original_handle_close_still_closes_known_manager_once(monkeypatch):
    operator, port, request = service_fixture(monkeypatch, existing=True)

    def close(handle):
        port.calls.append(('close', handle))
        return handle != 12

    port.CloseServiceHandle = close
    service = services.NativeGuardService(request, operator, new=False)
    with pytest.raises(contract.GuardInstallationError) as result:
        service.close()
    assert result.value.retained_owner is service
    assert port.calls[-2:] == [('close', 12), ('close', 11)]
    previous = tuple(port.calls)
    with pytest.raises(contract.GuardInstallationError, match='PREVIOUSLY'):
        service.close()
    assert tuple(port.calls) == previous


@pytest.mark.parametrize(
    'failure', ['directory', 'intent', 'guard', 'backend', 'deployment', 'journal']
)
def test_installation_aborts_before_service_registration_after_input_failure(monkeypatch, failure):
    """Workflow port check, not SYSTEM or filesystem ownership evidence."""
    calls = []
    root = installation.Path('C:/explicit-new-test-root')
    inputs = SimpleNamespace(
        guard=object(),
        backend=object(),
        _inputs={installation.DEPLOYMENT_NAME: object()},
        _checkpoint=lambda: None,
        verify_parent_access=lambda reader: calls.append('parent'),
        bind_new_installation_root=lambda guard: calls.append('bind-root'),
    )
    reader = SimpleNamespace(observe=lambda: SimpleNamespace(state='RUNNING'))
    monkeypatch.setattr(installation, 'require_backend_reader', lambda *args: None)

    def step(name):
        calls.append(name)
        if name == failure:
            raise OSError('injected ' + name)

    class Service:
        name = 'explicit-new-test-service'

        def __init__(self, *args, **options):
            assert options == {'new': True}
            calls.append('new-service-port')

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append('close-service')

        def create(self):
            pytest.fail('Partial installation must never register a service')

    class Writer:
        def __init__(self, *args):
            self.root = root
            self._guards = {root: object()}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append('close-writer')

        def create_directory(self, target):
            step('directory')
            return object()

        def write_bytes(self, target, data):
            step('intent')

        def copy_program(self, name, *args):
            step(name)

        def write_file(self, *args):
            step('deployment')

        def create_system_journal(self):
            step('journal')

    monkeypatch.setattr(installation, 'NativeGuardService', Service)
    monkeypatch.setattr(installation, 'ProtectedInstallationWriter', Writer)
    with pytest.raises(OSError, match='injected'):
        installation.install(inputs, reader, {}, b'pinned', 'a' * 64, object())
    assert calls[-2:] == ['close-writer', 'close-service']


@pytest.mark.parametrize(
    'code,specific,pid,allow,accepted',
    [
        (0, 0, 0, False, True),
        (1077, 0, 0, True, True),
        (1077, 0, 0, False, False),
        (5, 0, 0, True, False),
        (0, 1, 0, False, False),
        (1077, 1, 0, True, False),
        (0, 0, 42, False, False),
        (1077, 0, 42, True, False),
    ],
)
def test_never_started_code_is_only_initial_state_not_stop_evidence(
    monkeypatch, code, specific, pid, allow, accepted
):
    from backend.tests.infrastructure import v20_guard_system_bootstrap_worker as worker

    class ReadOnlyStatusPort:
        def __init__(self):
            self.closes = []

        def OpenSCManagerW(self, *args):
            assert args[-1] == 1
            return 11

        def OpenServiceW(self, *args):
            assert args[-1] == 4
            return 12

        def QueryServiceStatusEx(self, handle, kind, target, size, needed):
            status = ctypes.cast(target, ctypes.POINTER(services._ServiceStatusProcess)).contents
            status.service_type = 16
            status.state = 1
            status.flags = 0
            status.pid = pid
            status.win32_exit_code = code
            status.service_exit_code = specific
            return True

        def CloseServiceHandle(self, handle):
            self.closes.append(handle)
            return True

    port = ReadOnlyStatusPort()
    monkeypatch.setattr(services, 'service_api', lambda: port)
    request = {'service': {'name': 'explicit-status-fixture'}}
    if accepted:
        worker.inspect_service(request, expected_state=1, allow_never_started=allow)
    else:
        with pytest.raises(RuntimeError, match='did not stop cleanly'):
            worker.inspect_service(request, expected_state=1, allow_never_started=allow)
    assert port.closes == [12, 11]


def test_actual_probe_channel_accepts_validated_path_and_keeps_fixed_descriptor(
    tmp_path, ordinary_controller
):
    from backend.app.infrastructure.windows_private_package import create_private_package
    from tools.windows_program_package import write_new_verified_file

    reader, _ = ordinary_controller
    channel = create_private_package(tmp_path / 'actual-probe-channel')
    descriptor = {
        'request_sha256': 'a' * 64,
        'reader_pid': reader.identity.pid,
        'reader_created_at': reader.identity.creation_time_hex,
        'channel_ref': 'b' * 64,
    }
    write_new_verified_file(channel / 'channel.v1.json', _bytes(descriptor))
    with installation.ProbeChannel(channel, 'a' * 64, reader) as probe:
        assert not probe.stopped()
        write_new_verified_file(channel / 'STOP', b'STOP\n')
        assert probe.stopped()
    assert (channel / 'channel.v1.json').read_bytes() == _bytes(descriptor)


@pytest.mark.parametrize('exit_code,accepted', [(1077, True), (0, False), (5, False)])
def test_original_tool_continuation_requires_never_dispatched_service(
    monkeypatch, exit_code, accepted
):
    from backend.tests.infrastructure import v20_guard_system_bootstrap_worker as worker

    class StatusPort:
        def OpenSCManagerW(self, *args):
            return 11

        def OpenServiceW(self, *args):
            return 12

        def QueryServiceStatusEx(self, handle, kind, target, size, needed):
            value = ctypes.cast(target, ctypes.POINTER(services._ServiceStatusProcess)).contents
            value.state = 1
            value.service_type = 16
            value.win32_exit_code = exit_code
            return True

        def CloseServiceHandle(self, handle):
            return True

    monkeypatch.setattr(services, 'service_api', StatusPort)
    request = {'service': {'name': 'explicit-continuation-fixture'}}
    if accepted:
        worker.inspect_service(
            request, expected_state=1, allow_never_started=True, require_never_started=True
        )
    else:
        with pytest.raises(RuntimeError):
            worker.inspect_service(
                request, expected_state=1, allow_never_started=True, require_never_started=True
            )


@pytest.mark.parametrize('process_exit,accepted', [(0, True), (1, False)])
def test_stopped_scm_waits_for_original_root_exit_and_requires_zero_process_exit(
    monkeypatch, process_exit, accepted
):
    operator, _port, request = service_fixture(monkeypatch, existing=True)
    request['limits_ms'] = {'stop': 1000}
    service = services.NativeGuardService(request, operator, new=False)
    service._start_accepted = True
    observations = []

    def observe():
        observations.append(len(observations))
        return SimpleNamespace(
            state='RUNNING' if len(observations) == 1 else 'EXITED',
            exit_code=None if len(observations) == 1 else process_exit,
        )

    service._process = SimpleNamespace(observe=observe, close=lambda: None)
    monkeypatch.setattr(
        service,
        'status',
        lambda: SimpleNamespace(state=1, pid=0, win32_exit_code=0, service_exit_code=0),
    )
    try:
        if accepted:
            service.stop_owned()
        else:
            with pytest.raises(contract.GuardInstallationError, match='STOP_NOT_VERIFIED'):
                service.stop_owned()
        assert len(observations) == 2
        assert not service._stop_sent
    finally:
        service.close()


def test_read_only_installed_diagnosis_pins_original_sources_before_any_exe(group, monkeypatch):
    from backend.tests.infrastructure import v20_guard_installed_read_worker as worker

    group[2].mkdir()
    monkeypatch.setattr(
        worker, 'launch', lambda *args: pytest.fail('Unverified input cannot launch')
    )
    with pytest.raises(RuntimeError):
        worker.exercise(group[0], 'f' * 64)


def test_actual_read_only_metadata_port_initializes_and_closes_known_owners(tmp_path):
    from backend.tests.infrastructure.v20_guard_installed_read_worker import ReadOnlyMetadataPort

    port = ReadOnlyMetadataPort(tmp_path, current_operator_sid())
    port._checkpoint()
    assert len(port._owners) == 2
    port.close()
    assert port._closed
    port.close()
    with pytest.raises(RuntimeError, match='diagnosis unavailable'):
        port._checkpoint()
