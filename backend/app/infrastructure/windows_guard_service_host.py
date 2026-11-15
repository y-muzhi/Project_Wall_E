"""Own one SCM callback lifecycle; never install, stop or control another service."""

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from threading import Event, RLock, Thread

from .deployment_manifest import absolute_path, digest
from .guard_deployment_configuration import GuardDeploymentError, GuardDeploymentOwner
from .guard_service_diagnostics import GuardFailureStage, diagnostic_for_failure
from .windows_guard_service import GuardServiceError, guard_service_name

SERVICE_STOPPED = 1
SERVICE_START_PENDING = 2
SERVICE_STOP_PENDING = 3
SERVICE_RUNNING = 4
SERVICE_ACCEPT_STOP = 1
SERVICE_ACCEPT_SHUTDOWN = 4
SERVICE_CONTROL_STOP = 1
SERVICE_CONTROL_INTERROGATE = 4
SERVICE_CONTROL_SHUTDOWN = 5
SERVICE_WIN32_OWN_PROCESS = 0x10
ERROR_SERVICE_SPECIFIC_ERROR = 1066
ERROR_CALL_NOT_IMPLEMENTED = 120
PENDING_WAIT_MS = 125000
SERVICE_MAIN = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))
SERVICE_HANDLER = ctypes.WINFUNCTYPE(
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID
)


class _ServiceStatus(ctypes.Structure):
    _fields_ = [
        ('service_type', wintypes.DWORD),
        ('state', wintypes.DWORD),
        ('controls_accepted', wintypes.DWORD),
        ('win32_exit_code', wintypes.DWORD),
        ('service_exit_code', wintypes.DWORD),
        ('check_point', wintypes.DWORD),
        ('wait_hint', wintypes.DWORD),
    ]


class _ServiceTableEntry(ctypes.Structure):
    _fields_ = [('name', wintypes.LPWSTR), ('main', SERVICE_MAIN)]


def _api():
    if os.name != 'nt':
        raise GuardServiceError('WINDOWS_GUARD_SERVICE_REQUIRED')
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.RegisterServiceCtrlHandlerExW.argtypes = [
        wintypes.LPCWSTR,
        SERVICE_HANDLER,
        wintypes.LPVOID,
    ]
    api.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    api.SetServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ServiceStatus)]
    api.SetServiceStatus.restype = wintypes.BOOL
    api.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(_ServiceTableEntry)]
    api.StartServiceCtrlDispatcherW.restype = wintypes.BOOL
    return api


@dataclass(frozen=True)
class GuardServiceOutcome:
    exit_code: int
    failure_code: str | None
    retained_owner: object | None


class GuardServiceHost:
    """SCM controls only cancel; original Guard resources stay on ServiceMain's thread."""

    def __init__(self, installation_ref, manifest, expected_sha256):
        self.name = guard_service_name(installation_ref)
        self.installation_ref = installation_ref
        self.manifest = absolute_path(manifest)
        self.expected_sha256 = digest(expected_sha256)
        self._api = _api()
        self._gate = RLock()
        self._cancelled = Event()
        self._heartbeat_stop = Event()
        self._status_handle = None
        self._state = SERVICE_START_PENDING
        self._checkpoint = 0
        self._failure = None
        self._diagnostic = None
        self._errors = []
        self._retained = None
        self._owner = None
        self._ran = False
        self._entered = False
        self._finished = False
        self._handler_callback = SERVICE_HANDLER(self._control)
        self._main_callback = SERVICE_MAIN(self._service_main)
        self._table = (_ServiceTableEntry * 2)(
            _ServiceTableEntry(self.name, self._main_callback),
            _ServiceTableEntry(None, SERVICE_MAIN()),
        )

    def _record_failure(self, code, stage, error=None, *, replace=False):
        with self._gate:
            if replace or self._failure is None:
                self._failure = code
                self._diagnostic = diagnostic_for_failure(error, stage)

    def _report_locked(self):
        pending = self._state in (SERVICE_START_PENDING, SERVICE_STOP_PENDING)
        if pending:
            self._checkpoint += 1
        status = _ServiceStatus(
            SERVICE_WIN32_OWN_PROCESS,
            self._state,
            SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN if self._state == SERVICE_RUNNING else 0,
            ERROR_SERVICE_SPECIFIC_ERROR if self._failure else 0,
            self._diagnostic.service_exit_code if self._diagnostic else 0,
            self._checkpoint if pending else 0,
            PENDING_WAIT_MS if pending else 0,
        )
        if not self._api.SetServiceStatus(self._status_handle, ctypes.byref(status)):
            error = GuardServiceError('GUARD_SERVICE_STATUS_UNVERIFIED', ctypes.get_last_error())
            self._record_failure(str(error), GuardFailureStage.SERVICE_STATUS, error, replace=True)
            self._cancelled.set()
            raise error

    def _state_change(self, state):
        with self._gate:
            if self._state == SERVICE_STOPPED:
                return
            if self._cancelled.is_set() and state in (SERVICE_START_PENDING, SERVICE_RUNNING):
                state = SERVICE_STOP_PENDING
            self._state = state
            self._report_locked()

    def _control(self, control, event_type, event_data, context):
        try:
            if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
                self._cancelled.set()
                self._state_change(SERVICE_STOP_PENDING)
                return 0
            if control == SERVICE_CONTROL_INTERROGATE:
                with self._gate:
                    self._report_locked()
                return 0
            return ERROR_CALL_NOT_IMPLEMENTED
        except BaseException as error:  # noqa: BLE001 -- Never unwind through a native callback.
            self._errors.append(error)
            self._record_failure(
                'GUARD_SERVICE_CONTROL_STATUS_UNVERIFIED', GuardFailureStage.SERVICE_CONTROL, error
            )
            self._cancelled.set()
            return 1

    def _heartbeat(self):
        while not self._heartbeat_stop.wait(1):
            try:
                with self._gate:
                    if self._state in (SERVICE_START_PENDING, SERVICE_STOP_PENDING):
                        self._report_locked()
            except BaseException as error:  # noqa: BLE001 -- Preserve status-thread failure.
                self._errors.append(error)
                self._record_failure(
                    'GUARD_SERVICE_HEARTBEAT_FAILED', GuardFailureStage.SERVICE_HEARTBEAT, error
                )
                self._cancelled.set()
                return

    def _service_main(self, count, arguments):
        heartbeat = None
        stage = GuardFailureStage.SERVICE_START
        try:
            if self._entered:
                raise GuardServiceError('GUARD_SERVICE_CALLBACK_ALREADY_ENTERED')
            self._entered = True
            if count != 1 or arguments[0].casefold() != self.name.casefold():
                raise GuardServiceError('GUARD_SERVICE_ARGUMENTS_DIFFER')
            self._status_handle = self._api.RegisterServiceCtrlHandlerExW(
                self.name, self._handler_callback, None
            )
            if not self._status_handle:
                raise GuardServiceError('GUARD_SERVICE_HANDLER_UNAVAILABLE')
            self._state_change(SERVICE_START_PENDING)
            heartbeat = Thread(target=self._heartbeat, name='walle-guard-scm-status', daemon=False)
            heartbeat.start()
            if not self._cancelled.is_set():
                self._owner = GuardDeploymentOwner(
                    str(self.manifest), self.expected_sha256, cancelled=self._cancelled.is_set
                )
                if self._owner.spec.installation_ref != self.installation_ref:
                    raise GuardServiceError('GUARD_SERVICE_INSTALLATION_DIFFERS')
                self._state_change(SERVICE_RUNNING)
                if not self._cancelled.is_set():
                    stage = GuardFailureStage.SERVICE_LOOP
                    self._owner.serve(cancelled=self._cancelled.is_set)
                    if not self._cancelled.is_set():
                        raise GuardServiceError('GUARD_SERVICE_LOOP_ENDED_WITHOUT_STOP')
        except BaseException as error:  # noqa: BLE001 -- C ServiceMain cannot propagate exceptions.
            self._errors.append(error)
            self._retained = getattr(error, 'retained_owner', None)
            expected_cancel = (
                self._cancelled.is_set()
                and isinstance(error, GuardDeploymentError)
                and str(error) == 'GUARD_DEPLOYMENT_PREPARATION_INTERRUPTED'
                and self._retained is None
            )
            if not expected_cancel:
                self._record_failure('GUARD_SERVICE_START_OR_RUN_FAILED', stage, error)
        finally:
            self._cancelled.set()
            if self._status_handle:
                try:
                    self._state_change(SERVICE_STOP_PENDING)
                except GuardServiceError as error:
                    self._errors.append(error)
                    self._record_failure(
                        'GUARD_SERVICE_STATUS_UNVERIFIED', GuardFailureStage.SERVICE_STATUS, error
                    )
            if self._owner is not None:
                try:
                    self._owner.close()
                except BaseException as error:  # noqa: BLE001 -- Preserve owner at callback boundary.
                    self._errors.append(error)
                    self._record_failure(
                        'GUARD_SERVICE_SHUTDOWN_UNVERIFIED',
                        GuardFailureStage.SHUTDOWN,
                        error,
                        replace=True,
                    )
                    owners = [self._owner]
                    for candidate in (self._retained, getattr(error, 'retained_owner', None)):
                        if candidate is not None and all(item is not candidate for item in owners):
                            owners.append(candidate)
                    self._retained = tuple(owners)
                else:
                    self._owner = None
            self._heartbeat_stop.set()
            if heartbeat is not None:
                heartbeat.join()
            if self._status_handle:
                try:
                    self._state_change(SERVICE_STOPPED)
                except GuardServiceError as error:
                    self._errors.append(error)
                    self._record_failure(
                        'GUARD_SERVICE_STOP_STATUS_UNVERIFIED', GuardFailureStage.STOP_STATUS, error
                    )
            self._finished = True

    def run(self):
        if self._ran:
            raise GuardServiceError('GUARD_SERVICE_DISPATCH_ALREADY_USED')
        self._ran = True
        if not self._api.StartServiceCtrlDispatcherW(self._table):
            error = GuardServiceError('GUARD_SERVICE_DISPATCH_UNAVAILABLE', ctypes.get_last_error())
            if self._retained is not None:
                error.retained_owner = self._retained
            raise error
        if not self._entered or not self._finished:
            self._record_failure(
                'GUARD_SERVICE_CALLBACK_UNVERIFIED', GuardFailureStage.SERVICE_CALLBACK
            )
        return GuardServiceOutcome(1 if self._failure else 0, self._failure, self._retained)
