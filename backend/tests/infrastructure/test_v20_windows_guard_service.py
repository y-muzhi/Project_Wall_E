"""Read-only SCM contract and an independent service process source."""

import ctypes
import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_guard_service as module
from backend.app.infrastructure.windows_executable_pin import ExecutablePin

REF = 'a' * 64
BACKEND_SID = 'S-1-5-21-1-2-3-1000'


class ScmPort:
    def __init__(self):
        self.calls = []
        self.statuses = []

    def OpenSCManagerW(self, machine, database, access):
        self.calls.append(('manager', machine, database, access))
        return 1

    def OpenServiceW(self, manager, name, access):
        self.calls.append(('service', manager, name, access))
        return 2

    def QueryServiceStatusEx(self, service, level, output, capacity, needed):
        assert (service, level, capacity) == (2, 0, ctypes.sizeof(module._ServiceStatusProcess))
        self.calls.append(('query',))
        status = output._obj
        status.service_type, status.state, status.pid, status.flags = self.statuses.pop(0)
        return True

    def CloseServiceHandle(self, handle):
        self.calls.append(('close', handle))
        return True


@pytest.fixture
def scm(monkeypatch):
    result = ScmPort()
    monkeypatch.setattr(module, '_api', lambda: result)
    return result


@pytest.mark.parametrize('facts', [(32, 4, 88, 0), (16, 3, 88, 0), (16, 4, 0, 0), (16, 4, 88, 1)])
def test_uncertain_or_shared_service_status_never_supplies_pid(scm, facts):
    scm.statuses.append(facts)
    with module._GuardServiceStatus(REF) as status:
        with pytest.raises(module.GuardServiceError, match='NOT_RUNNING'):
            status.running_pid()
    assert scm.calls == [
        ('manager', None, None, 1),
        ('service', 1, 'WALLE.RuntimeGuard.' + REF, 4),
        ('query',),
        ('close', 2),
        ('close', 1),
    ]


@pytest.mark.parametrize('after_open', [88, 89])
def test_connector_rechecks_original_service_pid_before_yielding_pipe(scm, monkeypatch, after_open):
    scm.statuses.extend([(16, 4, 88, 0), (16, 4, 88, 0), (16, 4, after_open, 0)])
    identity = SimpleNamespace(pid=88, user_sid=module.GUARD_SERVICE_SID)
    program = object.__new__(ExecutablePin)
    endpoint = object()
    events = []

    @contextmanager
    def open_process(pid):
        assert pid == 88
        events.append('original-process')
        try:
            yield SimpleNamespace(
                identity=identity,
                observe=lambda: SimpleNamespace(identity=identity, state='RUNNING'),
            )
        finally:
            events.append('process-closed')

    @contextmanager
    def open_pipe(installation_ref, **options):
        assert installation_ref == REF
        assert options == dict(
            backend_sid=BACKEND_SID,
            server_sid=module.GUARD_SERVICE_SID,
            expected_guard=identity,
            program=program,
        )
        events.append('pipe')
        try:
            yield endpoint
        finally:
            events.append('pipe-closed')

    # Native SCM and authenticated pipe APIs have independent integration tests.
    monkeypatch.setattr(module, 'current_operator_sid', lambda: BACKEND_SID)
    monkeypatch.setattr(module, 'ObservedProcess', open_process)
    monkeypatch.setattr(module, 'GuardPipeClient', open_pipe)
    connection = module.connect_registered_guard(REF, backend_sid=BACKEND_SID, program=program)
    if after_open == 88:
        with connection as actual:
            assert actual is endpoint
            events.append('exposed')
        assert events == ['original-process', 'pipe', 'exposed', 'pipe-closed', 'process-closed']
    else:
        with pytest.raises(module.GuardServiceError, match='PROCESS_DIFFERS'), connection:
            pytest.fail('Unverified service must not expose a connection')
        assert events == ['original-process', 'pipe', 'pipe-closed', 'process-closed']
    assert scm.statuses == []
    assert scm.calls[-2:] == [('close', 2), ('close', 1)]


@pytest.mark.skipif(os.name != 'nt', reason='Requires Windows service query APIs')
def test_native_query_of_unique_absent_service_never_starts_any_service():
    reference = uuid4().hex + uuid4().hex
    with pytest.raises(
        module.GuardServiceError, match='REGISTERED_GUARD_SERVICE_UNAVAILABLE'
    ) as error:
        module._GuardServiceStatus(reference)
    assert error.value.native_error == 1060
