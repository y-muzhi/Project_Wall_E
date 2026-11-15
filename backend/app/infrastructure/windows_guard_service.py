"""Read the fixed local Guard service and bind the original authenticated pipe."""

import ctypes
import os
from contextlib import contextmanager
from ctypes import wintypes

from .windows_executable_pin import ExecutablePin
from .windows_guard_pipe import GuardPipeClient, pipe_name
from .windows_private_package import current_operator_sid
from .windows_process import ObservedProcess

GUARD_SERVICE_SID = 'S-1-5-18'
SC_MANAGER_CONNECT = 0x1
SERVICE_QUERY_STATUS = 0x4
SERVICE_WIN32_OWN_PROCESS = 0x10
SERVICE_RUNNING = 4


class GuardServiceError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


class _ServiceStatusProcess(ctypes.Structure):
    _fields_ = [
        ('service_type', wintypes.DWORD),
        ('state', wintypes.DWORD),
        ('controls_accepted', wintypes.DWORD),
        ('win32_exit_code', wintypes.DWORD),
        ('service_exit_code', wintypes.DWORD),
        ('check_point', wintypes.DWORD),
        ('wait_hint', wintypes.DWORD),
        ('pid', wintypes.DWORD),
        ('flags', wintypes.DWORD),
    ]


def _error(code):
    return GuardServiceError(code, ctypes.get_last_error())


def _api():
    if os.name != 'nt':
        raise GuardServiceError('WINDOWS_GUARD_SERVICE_REQUIRED')
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenSCManagerW.restype = wintypes.HANDLE
    api.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenServiceW.restype = wintypes.HANDLE
    api.QueryServiceStatusEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.POINTER(_ServiceStatusProcess),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.QueryServiceStatusEx.restype = wintypes.BOOL
    api.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    api.CloseServiceHandle.restype = wintypes.BOOL
    return api


def guard_service_name(installation_ref):
    pipe_name(installation_ref)
    return 'WALLE.RuntimeGuard.' + installation_ref


class _GuardServiceStatus:
    def __init__(self, installation_ref):
        name = guard_service_name(installation_ref)
        self._api = _api()
        self._service = None
        self._manager = self._api.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not self._manager:
            raise _error('GUARD_SERVICE_MANAGER_UNAVAILABLE')
        try:
            self._service = self._api.OpenServiceW(self._manager, name, SERVICE_QUERY_STATUS)
            if not self._service:
                raise _error('REGISTERED_GUARD_SERVICE_UNAVAILABLE')
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                raise cleanup from original
            raise

    def running_pid(self):
        if not self._service:
            raise GuardServiceError('REGISTERED_GUARD_SERVICE_CLOSED')
        status = _ServiceStatusProcess()
        needed = wintypes.DWORD()
        if not self._api.QueryServiceStatusEx(
            self._service, 0, ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(needed)
        ):
            raise _error('GUARD_SERVICE_STATUS_UNAVAILABLE')
        if (
            status.service_type != SERVICE_WIN32_OWN_PROCESS
            or status.state != SERVICE_RUNNING
            or status.pid == 0
            or status.flags != 0
        ):
            raise GuardServiceError('REGISTERED_GUARD_SERVICE_NOT_RUNNING')
        return status.pid

    def close(self):
        for attribute in ('_service', '_manager'):
            handle = getattr(self, attribute)
            if handle:
                if not self._api.CloseServiceHandle(handle):
                    error = _error('GUARD_SERVICE_QUERY_HANDLE_CLOSE_UNVERIFIED')
                    error.retained_owner = self
                    raise error
                setattr(self, attribute, None)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def _verify_registered_guard_process(service, process):
    current = process.observe()
    if (
        current.state != 'RUNNING'
        or current.identity.user_sid != GUARD_SERVICE_SID
        or current.identity.pid != service.running_pid()
    ):
        raise GuardServiceError('REGISTERED_GUARD_SERVICE_PROCESS_DIFFERS')


@contextmanager
def connect_registered_guard(installation_ref, *, backend_sid, program):
    """Open only the fixed service endpoint, with no service control rights."""
    if type(program) is not ExecutablePin:
        raise TypeError('Trusted registered Guard image required')
    if backend_sid == GUARD_SERVICE_SID or current_operator_sid() != backend_sid:
        raise GuardServiceError('ORIGINAL_GUARD_BACKEND_SID_DIFFERS')
    with (
        _GuardServiceStatus(installation_ref) as service,
        ObservedProcess(service.running_pid()) as process,
    ):
        _verify_registered_guard_process(service, process)
        with GuardPipeClient(
            installation_ref,
            backend_sid=backend_sid,
            server_sid=GUARD_SERVICE_SID,
            expected_guard=process.identity,
            program=program,
        ) as endpoint:
            _verify_registered_guard_process(service, process)
            yield endpoint
