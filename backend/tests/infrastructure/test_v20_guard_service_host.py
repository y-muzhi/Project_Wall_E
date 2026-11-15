"""SCM port fixture only: actual callback ABI/lifecycle, not a SYSTEM service install."""

import ctypes
import importlib
import subprocess
import sys
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest

from backend.app.infrastructure import windows_guard_service_host as service
from backend.app.infrastructure.guard_deployment_configuration import GuardDeploymentError
from backend.app.infrastructure.guard_service_diagnostics import (
    GuardFailureReason,
    GuardFailureStage,
    GuardServiceDiagnostic,
    decode_service_diagnostic,
)
from backend.app.infrastructure.windows_guard_service import GuardServiceError
from backend.tests.code_tasks import test_local_deployment as local
from backend.tests.infrastructure import test_v20_guard_deployment_configuration as deployments

tmp_path = local.tmp_path
guard_source = deployments.guard_source
INSTALLATION = 'a' * 64


class ScmPort:
    def __init__(self):
        self.statuses = []
        self.handler = None
        self.registered_name = None
        self.host = None
        self.register_failure = False
        self.dispatch_failure = False
        self.skip_main = False
        self.fail_state = None
        self.main_arguments = None

    def RegisterServiceCtrlHandlerExW(self, name, handler, context):
        self.registered_name = name
        self.handler = handler
        return 0 if self.register_failure else 101

    def SetServiceStatus(self, handle, pointer):
        assert handle == 101
        status = ctypes.cast(pointer, ctypes.POINTER(service._ServiceStatus)).contents
        snapshot = {name: getattr(status, name) for name, _ in service._ServiceStatus._fields_}
        self.statuses.append(snapshot)
        return status.state != self.fail_state

    def StartServiceCtrlDispatcherW(self, table):
        assert table[0].name == self.host.name
        assert table[1].name is None and not table[1].main
        if self.dispatch_failure:
            return False
        if not self.skip_main:
            values = self.main_arguments or [self.host.name]
            arguments = (ctypes.wintypes.LPWSTR * len(values))(*values)
            table[0].main(len(values), arguments)
        return True


class OwnedGuard:
    def __init__(self, port):
        self.port = port
        self.spec = SimpleNamespace(installation_ref=INSTALLATION)
        self.events = [('create', get_ident())]
        self.close_count = 0
        self.run_error = None
        self.close_error = None
        self.run_action = None

    def serve(self, *, cancelled):
        self.events.append(('serve', get_ident()))
        assert not cancelled()
        if self.run_action:
            self.run_action()
        elif self.run_error:
            raise self.run_error
        else:
            assert self.port.handler(service.SERVICE_CONTROL_STOP, 0, None, None) == 0
        assert cancelled() or self.run_action is not None

    def close(self):
        self.events.append(('close', get_ident()))
        self.close_count += 1
        if self.close_error:
            raise self.close_error


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    port = ScmPort()
    monkeypatch.setattr(service, '_api', lambda: port)
    host = service.GuardServiceHost(INSTALLATION, str(tmp_path / 'guard.json'), 'b' * 64)
    port.host = host
    owner = OwnedGuard(port)

    def factory(path, sha, *, cancelled):
        assert path == str(tmp_path / 'guard.json') and sha == 'b' * 64
        assert not cancelled()
        return owner

    monkeypatch.setattr(service, 'GuardDeploymentOwner', factory)
    return port, host, owner, factory


def states(port):
    return [row['state'] for row in port.statuses]


def test_actual_callback_abi_and_same_owner_thread_lifecycle(lifecycle):
    port, host, owner, _ = lifecycle
    result = host.run()
    assert result == service.GuardServiceOutcome(0, None, None)
    assert port.registered_name == service.guard_service_name(INSTALLATION)
    assert [event for event, _ in owner.events] == ['create', 'serve', 'close']
    assert len({thread for _, thread in owner.events}) == 1
    assert owner.close_count == 1 and host._owner is None
    assert states(port) == [2, 4, 3, 3, 1]
    for row in port.statuses:
        assert row['service_type'] == 16
        assert row['controls_accepted'] == (5 if row['state'] == 4 else 0)
        assert row['win32_exit_code'] == row['service_exit_code'] == 0
        assert (row['check_point'] > 0) == (row['state'] in (2, 3))
    with pytest.raises(GuardServiceError, match='ALREADY_USED'):
        host.run()


@pytest.mark.parametrize(
    'control', [service.SERVICE_CONTROL_STOP, service.SERVICE_CONTROL_SHUTDOWN]
)
def test_stop_during_construction_never_reports_running_or_serves(lifecycle, monkeypatch, control):
    port, host, owner, original = lifecycle

    def factory(*args, **kwargs):
        value = original(*args, **kwargs)
        assert port.handler(control, 0, None, None) == 0
        assert kwargs['cancelled']()
        return value

    monkeypatch.setattr(service, 'GuardDeploymentOwner', factory)
    assert host.run().exit_code == 0
    assert 4 not in states(port)
    assert [event for event, _ in owner.events] == ['create', 'close']
    assert owner.close_count == 1


def test_clean_cancelled_constructor_is_a_successful_stop(lifecycle, monkeypatch):
    port, host, owner, _ = lifecycle

    def cancelled_factory(*args, **kwargs):
        port.handler(service.SERVICE_CONTROL_STOP, 0, None, None)
        raise GuardDeploymentError('GUARD_DEPLOYMENT_PREPARATION_INTERRUPTED')

    monkeypatch.setattr(service, 'GuardDeploymentOwner', cancelled_factory)
    assert host.run().exit_code == 0
    assert 4 not in states(port) and owner.close_count == 0


@pytest.mark.parametrize('phase', ['construct', 'serve', 'close'])
def test_failure_reports_nonzero_without_retry_or_secret_text(lifecycle, monkeypatch, phase):
    port, host, owner, _ = lifecycle
    failure = RuntimeError('private path and provider secret must not be emitted')
    if phase == 'construct':

        def failed_factory(*args, **kwargs):
            raise failure

        monkeypatch.setattr(service, 'GuardDeploymentOwner', failed_factory)
    elif phase == 'serve':
        owner.run_error = failure
    else:
        owner.close_error = failure
    outcome = host.run()
    assert outcome.exit_code == 1 and 'private' not in outcome.failure_code
    assert port.statuses[-1]['state'] == 1
    assert port.statuses[-1]['win32_exit_code'] == 1066
    diagnostic = decode_service_diagnostic(1066, port.statuses[-1]['service_exit_code'])
    expected = {
        'construct': GuardFailureStage.SERVICE_START,
        'serve': GuardFailureStage.SERVICE_LOOP,
        'close': GuardFailureStage.SHUTDOWN,
    }[phase]
    assert diagnostic == GuardServiceDiagnostic(
        expected, reason=GuardFailureReason.UNKNOWN_INTERNAL_FAILURE
    )
    assert failure in host._errors
    assert owner.close_count == (0 if phase == 'construct' else 1)
    if phase == 'close':
        assert owner in outcome.retained_owner and host._owner is owner
    else:
        assert outcome.retained_owner is None


def test_unknown_constructor_owner_is_retained_without_second_close(lifecycle, monkeypatch):
    _, host, owner, _ = lifecycle

    def failed_factory(*args, **kwargs):
        error = RuntimeError('unknown original owner')
        error.retained_owner = owner
        raise error

    monkeypatch.setattr(service, 'GuardDeploymentOwner', failed_factory)
    outcome = host.run()
    assert outcome.exit_code == 1 and outcome.retained_owner is owner
    assert owner.close_count == 0


def test_installed_service_name_must_match_held_configuration(lifecycle):
    port, host, owner, _ = lifecycle
    owner.spec.installation_ref = 'c' * 64
    assert host.run().exit_code == 1
    assert 4 not in states(port) and owner.close_count == 1


@pytest.mark.parametrize('state', [2, 4, 3, 1])
def test_native_status_failure_is_not_success(lifecycle, state):
    port, host, owner, _ = lifecycle
    port.fail_state = state
    result = host.run()
    assert result.exit_code == 1
    assert owner.close_count <= 1


@pytest.mark.parametrize('phase', ['register', 'dispatch', 'missing-main', 'extra-arguments'])
def test_native_registration_and_dispatch_are_fail_closed(lifecycle, phase):
    port, host, owner, _ = lifecycle
    if phase == 'register':
        port.register_failure = True
    elif phase == 'dispatch':
        port.dispatch_failure = True
    elif phase == 'missing-main':
        port.skip_main = True
    else:
        port.main_arguments = [host.name, '--arbitrary']
    if phase == 'dispatch':
        with pytest.raises(GuardServiceError, match='DISPATCH_UNAVAILABLE'):
            host.run()
    else:
        assert host.run().exit_code == 1
    assert owner.close_count == 0


def test_interrogate_and_unknown_controls_do_not_run_business_actions(lifecycle):
    port, host, owner, _ = lifecycle

    def action():
        before = len(owner.events)
        assert port.handler(4, 0, None, None) == 0
        assert port.handler(128, 0, None, None) == 120
        assert len(owner.events) == before
        assert port.handler(1, 0, None, None) == 0

    owner.run_action = action
    assert host.run().exit_code == 0


@pytest.mark.parametrize('retained', [False, True])
def test_entry_exits_only_this_guard_when_original_owner_is_unknown(
    lifecycle, monkeypatch, retained
):
    _, host, _, _ = lifecycle
    entry = importlib.import_module('backend.runtime_guard.__main__')
    calls = []
    outcome = service.GuardServiceOutcome(1, 'FIXTURE_FAILURE', object() if retained else None)

    class HostPort:
        def __init__(self, *args):
            pass

        def run(self):
            return outcome

    def own_exit(code):
        calls.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(entry, 'GuardServiceHost', HostPort)
    monkeypatch.setattr(entry.os, '_exit', own_exit)
    arguments = [
        '--installation-ref',
        INSTALLATION,
        '--manifest',
        str(host.manifest),
        '--sha256',
        'b' * 64,
    ]
    if retained:
        with pytest.raises(SystemExit) as stopped:
            entry.main(arguments)
        assert stopped.value.code == 1 and calls == [1]
    else:
        assert entry.main(arguments) == 1 and calls == []


@pytest.mark.parametrize('defect', ['ref', 'path', 'sha'])
def test_cli_rejects_invalid_fixed_identity_before_scm(lifecycle, monkeypatch, defect):
    _, host, _, _ = lifecycle
    entry = importlib.import_module('backend.runtime_guard.__main__')

    def forbidden(*args):
        raise AssertionError('Invalid CLI must not touch SCM')

    monkeypatch.setattr(entry, 'GuardServiceHost', forbidden)
    arguments = [
        '--installation-ref',
        INSTALLATION if defect != 'ref' else 'bad',
        '--manifest',
        str(host.manifest) if defect != 'path' else 'relative.json',
        '--sha256',
        'b' * 64 if defect != 'sha' else 'bad',
    ]
    with pytest.raises(SystemExit) as failure:
        entry.main(arguments)
    assert failure.value.code == 2


def test_fresh_service_entry_import_does_not_load_the_business_database():
    result = subprocess.run(
        [
            sys.executable,
            '-B',
            '-c',
            (
                'import sys;import backend.runtime_guard.__main__;'
                "assert 'backend.app.infrastructure.database' not in sys.modules;"
                "assert 'backend.app.infrastructure.model_profile' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('failure', [None, 'source', 'installation'])
def test_scm_callback_owns_actual_guard_sources_and_pipe_on_one_thread(
    guard_source, monkeypatch, failure
):
    value, manifest, sha = guard_source
    port = ScmPort()
    running = Event()
    owner_threads = []
    owners = []
    expected = value['installation_ref']
    if failure == 'installation':
        expected = 'c' * 64
    monkeypatch.setattr(service, '_api', lambda: port)
    original_factory = service.GuardDeploymentOwner

    def construct(*args, **kwargs):
        owner_threads.append(get_ident())
        owned = original_factory(*args, **kwargs)
        owners.append(owned)
        original_close = owned.close

        def close():
            owner_threads.append(get_ident())
            return original_close()

        monkeypatch.setattr(owned, 'close', close)
        return owned

    monkeypatch.setattr(service, 'GuardDeploymentOwner', construct)
    host = service.GuardServiceHost(
        expected, str(manifest), 'd' * 64 if failure == 'source' else sha
    )
    port.host = host
    native_status = port.SetServiceStatus

    def status(*args):
        accepted = native_status(*args)
        if port.statuses[-1]['state'] == service.SERVICE_RUNNING:
            running.set()
        return accepted

    monkeypatch.setattr(port, 'SetServiceStatus', status)

    def dispatch(table):
        arguments = (ctypes.wintypes.LPWSTR * 1)(host.name)
        callback = Thread(target=lambda: table[0].main(1, arguments))
        callback.start()
        if failure is None:
            assert running.wait(10)
            assert owners and not owners[0]._closed
            with pytest.raises(PermissionError):
                manifest.rename(manifest.with_suffix('.changed'))
            # This control originates on another actual thread. It never owns
            # the actual Guard native handles or journal/pipe operations.
            assert port.handler(service.SERVICE_CONTROL_STOP, 0, None, None) == 0
        callback.join(15)
        assert not callback.is_alive()
        return True

    monkeypatch.setattr(port, 'StartServiceCtrlDispatcherW', dispatch)
    outcome = host.run()
    assert outcome.exit_code == (0 if failure is None else 1), repr(host._errors)
    assert outcome.retained_owner is None
    assert len(set(owner_threads)) == 1 and owner_threads[0] != get_ident()
    assert all(owner._closed and owner.host is None for owner in owners)
    if failure:
        assert service.SERVICE_RUNNING not in states(port)
    manifest.rename(manifest.with_suffix('.released'))


def test_dispatch_failure_keeps_unknown_native_owner_for_entry_failure_exit(lifecycle, monkeypatch):
    port, host, owner, _ = lifecycle
    owner.close_error = RuntimeError('Owned original close failure')
    original = port.StartServiceCtrlDispatcherW

    def dispatched_then_failed(table):
        assert original(table)
        return False

    monkeypatch.setattr(port, 'StartServiceCtrlDispatcherW', dispatched_then_failed)
    with pytest.raises(GuardServiceError) as failure:
        host.run()
    assert owner in failure.value.retained_owner
    assert owner.close_count == 1


def test_entry_dispatch_exception_with_owner_uses_own_process_failure_exit(lifecycle, monkeypatch):
    _, host, _, _ = lifecycle
    entry = importlib.import_module('backend.runtime_guard.__main__')
    retained = object()

    class FailedHost:
        def __init__(self, *args):
            pass

        def run(self):
            error = GuardServiceError('FIXTURE_DISPATCH_FAILED')
            error.retained_owner = retained
            raise error

    def own_exit(code):
        assert code == 1
        raise SystemExit(code)

    monkeypatch.setattr(entry, 'GuardServiceHost', FailedHost)
    monkeypatch.setattr(entry.os, '_exit', own_exit)
    with pytest.raises(SystemExit) as failure:
        entry.main(
            [
                '--installation-ref',
                INSTALLATION,
                '--manifest',
                str(host.manifest),
                '--sha256',
                'b' * 64,
            ]
        )
    assert failure.value.code == 1


def test_scm_keeps_original_constructor_stage_and_native_error(lifecycle, monkeypatch):
    port, host, _, _ = lifecycle

    def failed_factory(*args, **kwargs):
        error = GuardDeploymentError('GUARD_DEPLOYMENT_UNVERIFIED')
        error.guard_diagnostic = GuardServiceDiagnostic(GuardFailureStage.PRIVATE_JOURNAL, 5)
        raise error

    monkeypatch.setattr(service, 'GuardDeploymentOwner', failed_factory)
    assert host.run().exit_code == 1
    diagnostic = decode_service_diagnostic(1066, port.statuses[-1]['service_exit_code'])
    assert diagnostic == GuardServiceDiagnostic(GuardFailureStage.PRIVATE_JOURNAL, 5)
    assert 'private' not in host._failure
