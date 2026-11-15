"""Bounded configuration and control of only one explicitly pinned Guard service."""

import ctypes
from ctypes import wintypes
from time import monotonic, sleep

from backend.app.infrastructure.windows_guard_service import _api as query_api
from backend.app.infrastructure.windows_guard_service import (
    _ServiceStatusProcess,
    guard_service_name,
)
from backend.app.infrastructure.windows_process import ObservedProcess
from tools.windows_guard_install_contract import (
    ADMINISTRATORS,
    SERVICE_PRIVILEGES,
    SYSTEM,
    GuardInstallationError,
    service_rights,
)
from tools.windows_guard_install_files import NativeDescriptor
from tools.windows_guard_install_identity import InstallationOperator

SERVICE_OBJECT_TYPE = 2  # SE_SERVICE from the Windows SE_OBJECT_TYPE enum.


class QueryConfig(ctypes.Structure):
    _fields_ = [
        ('kind', wintypes.DWORD),
        ('start', wintypes.DWORD),
        ('error', wintypes.DWORD),
        ('binary', wintypes.LPVOID),
        ('group', wintypes.LPVOID),
        ('tag', wintypes.DWORD),
        ('dependencies', wintypes.LPVOID),
        ('account', wintypes.LPVOID),
        ('display', wintypes.LPVOID),
    ]


class RequiredPrivileges(ctypes.Structure):
    _fields_ = [('names', wintypes.LPVOID)]


class FailureActions(ctypes.Structure):
    _fields_ = [
        ('reset', wintypes.DWORD),
        ('reboot', wintypes.LPVOID),
        ('command', wintypes.LPVOID),
        ('count', wintypes.DWORD),
        ('actions', wintypes.LPVOID),
    ]


def service_api():
    api = query_api()
    api.CreateServiceW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        *[wintypes.DWORD] * 4,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
    ]
    api.CreateServiceW.restype = wintypes.HANDLE
    api.QueryServiceConfigW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.QueryServiceConfigW.restype = wintypes.BOOL
    api.QueryServiceConfig2W.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.QueryServiceConfig2W.restype = wintypes.BOOL
    api.ChangeServiceConfig2W.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID]
    api.ChangeServiceConfig2W.restype = wintypes.BOOL
    api.SetServiceObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID]
    api.SetServiceObjectSecurity.restype = wintypes.BOOL
    api.StartServiceW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR)]
    api.StartServiceW.restype = wintypes.BOOL
    api.ControlService.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID]
    api.ControlService.restype = wintypes.BOOL
    return api


def _buffer(call, minimum):
    needed = wintypes.DWORD()
    ctypes.set_last_error(0)
    if call(None, 0, ctypes.byref(needed)) or ctypes.get_last_error() != 122:
        raise GuardInstallationError('SERVICE_CONFIGURATION_LENGTH_UNVERIFIED')
    if not minimum <= needed.value <= 8192:
        raise GuardInstallationError('SERVICE_CONFIGURATION_SIZE_UNSUPPORTED')
    raw = ctypes.create_string_buffer(needed.value)
    actual = wintypes.DWORD()
    if not call(raw, len(raw), ctypes.byref(actual)) or actual.value > len(raw):
        raise GuardInstallationError('SERVICE_CONFIGURATION_QUERY_FAILED')
    return raw


def _text(raw, pointer, minimum, *, multiple=False):
    if not pointer:
        return () if multiple else ''
    start, end = ctypes.addressof(raw), ctypes.addressof(raw) + len(raw)
    if not start + minimum <= pointer <= end - 2 or pointer % 2:
        raise GuardInstallationError('SERVICE_CONFIGURATION_POINTER_OUTSIDE_BUFFER')
    remaining = ctypes.string_at(pointer, end - pointer)
    if len(remaining) % 2:
        raise GuardInstallationError('SERVICE_CONFIGURATION_TEXT_SIZE_INVALID')
    text = remaining.decode('utf-16-le', errors='strict')
    if multiple:
        if text.startswith('\0'):
            return ()
        terminator = text.find('\0\0')
        if terminator < 0:
            raise GuardInstallationError('SERVICE_CONFIGURATION_MULTI_STRING_UNTERMINATED')
        values = tuple(text[:terminator].split('\0'))
        if len(values) > 64 or any(not 1 <= len(value) <= 256 for value in values):
            raise GuardInstallationError('SERVICE_CONFIGURATION_MULTI_STRING_LIMIT')
        return values
    terminator = text.find('\0')
    if terminator < 0:
        raise GuardInstallationError('SERVICE_CONFIGURATION_STRING_UNTERMINATED')
    return text[:terminator]


def read_service_configuration(api, handle):
    size = ctypes.sizeof(QueryConfig)
    raw = _buffer(
        lambda data, count, needed: api.QueryServiceConfigW(handle, data, count, needed), size
    )
    value = QueryConfig.from_buffer(raw)
    result = {
        'kind': value.kind,
        'start': value.start,
        'error': value.error,
        'tag': value.tag,
        'binary': _text(raw, value.binary, size),
        'group': _text(raw, value.group, size),
        'dependencies': _text(raw, value.dependencies, size, multiple=True),
        'account': _text(raw, value.account, size),
        'display': _text(raw, value.display, size),
    }
    privileges = _buffer(
        lambda data, count, needed: api.QueryServiceConfig2W(handle, 6, data, count, needed),
        ctypes.sizeof(RequiredPrivileges),
    )
    result['privileges'] = _text(
        privileges,
        RequiredPrivileges.from_buffer(privileges).names,
        ctypes.sizeof(RequiredPrivileges),
        multiple=True,
    )
    failures = _buffer(
        lambda data, count, needed: api.QueryServiceConfig2W(handle, 2, data, count, needed),
        ctypes.sizeof(FailureActions),
    )
    actions = FailureActions.from_buffer(failures)
    result['failure_count'] = actions.count
    result['failure_command'] = _text(failures, actions.command, ctypes.sizeof(FailureActions))
    result['failure_reboot'] = _text(failures, actions.reboot, ctypes.sizeof(FailureActions))
    flags = _buffer(
        lambda data, count, needed: api.QueryServiceConfig2W(handle, 4, data, count, needed), 4
    )
    result['failure_noncrash'] = wintypes.DWORD.from_buffer(flags).value
    return result


class NativeGuardService:
    def __init__(self, request, operator, *, new):
        if type(operator) is not InstallationOperator or type(new) is not bool:
            raise GuardInstallationError('ACTUAL_INSTALLATION_OPERATOR_REQUIRED')
        self.operator = operator.verify()
        self.request = request
        self.name = guard_service_name(request['installation_ref'])
        if self.name != request['service']['name']:
            raise GuardInstallationError('FIXED_INSTALLATION_SERVICE_NAME_REQUIRED')
        self._api = service_api()
        self._manager = None
        self._service = None
        self._descriptor = None
        self._process = None
        self._start_attempted = False
        self._start_accepted = False
        self._stop_sent = False
        self._closed = False
        self._close_failed = False
        try:
            self._manager = self._api.OpenSCManagerW(None, None, 3 if new else 1)
            if not self._manager:
                raise GuardInstallationError('INSTALLER_SERVICE_MANAGER_UNAVAILABLE')
            rights = 0xE0037 if new else 0x20035
            self._service = self._api.OpenServiceW(self._manager, self.name, rights)
            if new:
                if self._service or ctypes.get_last_error() != 1060:
                    raise GuardInstallationError('CREATE_ONLY_NEW_GUARD_SERVICE_REQUIRED')
            elif not self._service:
                raise GuardInstallationError('ORIGINAL_INSTALLED_SERVICE_UNAVAILABLE')
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def create(self):
        self.operator.verify()
        if self._service:
            raise GuardInstallationError('CREATE_ONLY_NEW_GUARD_SERVICE_REQUIRED')
        self._service = self._api.CreateServiceW(
            self._manager,
            self.name,
            self.name,
            0xE0037,
            0x10,
            3,
            1,
            self.request['service']['image_path'],
            None,
            None,
            None,
            'LocalSystem',
            None,
        )
        if not self._service:
            raise GuardInstallationError('CREATE_ONLY_GUARD_SERVICE_FAILED')
        self._descriptor = NativeDescriptor(
            ADMINISTRATORS, service_rights(self.request['backend_sid']), directory=False
        )
        if not self._api.SetServiceObjectSecurity(self._service, 7, self._descriptor._descriptor):
            raise GuardInstallationError('NEW_GUARD_SERVICE_SECURITY_SEAL_FAILED')
        self._descriptor.apply(self._service, object_type=SERVICE_OBJECT_TYPE)
        names = ctypes.create_unicode_buffer('\0'.join(SERVICE_PRIVILEGES) + '\0\0')
        privileges = RequiredPrivileges(ctypes.addressof(names))
        if not self._api.ChangeServiceConfig2W(self._service, 6, ctypes.byref(privileges)):
            raise GuardInstallationError('NEW_GUARD_SERVICE_PRIVILEGES_UNVERIFIED')
        failures = FailureActions()
        flag = wintypes.BOOL(False)
        if not self._api.ChangeServiceConfig2W(
            self._service, 2, ctypes.byref(failures)
        ) or not self._api.ChangeServiceConfig2W(self._service, 4, ctypes.byref(flag)):
            raise GuardInstallationError('NEW_GUARD_SERVICE_FAILURE_ACTIONS_UNVERIFIED')
        self.verify()
        if self.status().state != 1:
            raise GuardInstallationError('NEW_SERVICE_MUST_REMAIN_STOPPED')

    def verify(self):
        self.operator.verify()
        actual = read_service_configuration(self._api, self._service)
        expected = {
            'kind': 0x10,
            'start': 3,
            'error': 1,
            'tag': 0,
            'binary': self.request['service']['image_path'],
            'group': '',
            'dependencies': (),
            'account': 'LocalSystem',
            'display': self.name,
            'privileges': SERVICE_PRIVILEGES,
            'failure_count': 0,
            'failure_command': '',
            'failure_reboot': '',
            'failure_noncrash': 0,
        }
        if actual != expected:
            raise GuardInstallationError('INSTALLED_SERVICE_CONFIGURATION_DIFFERS')
        if self._descriptor is None:
            self._descriptor = NativeDescriptor(
                ADMINISTRATORS, service_rights(self.request['backend_sid']), directory=False
            )
        self._descriptor.verify_handle(self._service, object_type=SERVICE_OBJECT_TYPE)
        return actual

    def status(self):
        value, needed = _ServiceStatusProcess(), wintypes.DWORD()
        if not self._api.QueryServiceStatusEx(
            self._service, 0, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(needed)
        ):
            raise GuardInstallationError('ORIGINAL_SERVICE_STATUS_UNAVAILABLE')
        if value.service_type != 0x10 or value.flags != 0:
            raise GuardInstallationError('ORIGINAL_SERVICE_PROCESS_KIND_DIFFERS')
        return value

    def _capture_original(self, status):
        if not status.pid:
            return
        if self._process is None:
            process = ObservedProcess(status.pid)
            self._process = process
            expected_image = self.request['service']['arguments'][0]
            if (
                process.identity.user_sid != SYSTEM
                or process.identity.is_appcontainer
                or process.identity.image_path.casefold() != expected_image.casefold()
            ):
                raise GuardInstallationError('ORIGINAL_SYSTEM_GUARD_PROCESS_DIFFERS')
        elif status.pid != self._process.identity.pid:
            raise GuardInstallationError('ORIGINAL_SYSTEM_GUARD_PID_CHANGED')

    def start(self, cancelled):
        self.verify()
        if self.status().state != 1 or self._start_attempted:
            raise GuardInstallationError('EXPLICIT_STOPPED_SERVICE_START_REQUIRED')
        if cancelled():
            raise GuardInstallationError('GUARD_SERVICE_START_CANCELLED')
        self._start_attempted = True
        if not self._api.StartServiceW(self._service, 0, None):
            raise GuardInstallationError('ORIGINAL_GUARD_SERVICE_START_FAILED')
        self._start_accepted = True
        deadline = monotonic() + self.request['limits_ms']['start'] / 1000
        while monotonic() < deadline:
            status = self.status()
            self._capture_original(status)
            if status.state == 4:
                if self._process is None or self._process.observe().state != 'RUNNING':
                    raise GuardInstallationError('ORIGINAL_GUARD_RUNNING_PROCESS_UNAVAILABLE')
                return self._process.identity
            if status.state == 1 or cancelled():
                raise GuardInstallationError('ORIGINAL_GUARD_START_NOT_RUNNING')
            sleep(0.1)
        raise GuardInstallationError('ORIGINAL_GUARD_START_DEADLINE_EXCEEDED')

    def stop_owned(self):
        if not self._start_accepted:
            return
        deadline = monotonic() + self.request['limits_ms']['stop'] / 1000
        while monotonic() < deadline:
            status = self.status()
            self._capture_original(status)
            if status.state == 1:
                if self._process is None:
                    raise GuardInstallationError('GUARD_EXIT_WITHOUT_ORIGINAL_PROCESS_EVIDENCE')
                if status.win32_exit_code != 0 or status.service_exit_code != 0:
                    raise GuardInstallationError('ORIGINAL_GUARD_STOP_NOT_VERIFIED')
                original = self._process.observe()
                if original.state == 'EXITED':
                    if original.exit_code != 0:
                        raise GuardInstallationError('ORIGINAL_GUARD_STOP_NOT_VERIFIED')
                    return
                if original.state != 'RUNNING':
                    raise GuardInstallationError('ORIGINAL_GUARD_STOP_NOT_VERIFIED')
                # SCM STOPPED is reported before ServiceMain returns. The frozen
                # root still owns its complete program lease until dispatcher exit.
                sleep(0.1)
                continue
            if status.state == 4 and not self._stop_sent:
                self._stop_sent = True
                response = ctypes.create_string_buffer(64)
                if not self._api.ControlService(self._service, 1, response):
                    raise GuardInstallationError('ORIGINAL_GUARD_STOP_SEND_UNVERIFIED')
            sleep(0.1)
        raise GuardInstallationError('ORIGINAL_GUARD_STOP_DEADLINE_EXCEEDED')

    def close(self):
        if self._close_failed:
            error = GuardInstallationError('INSTALLER_SERVICE_CLOSE_PREVIOUSLY_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        failures = []
        for owner in (self._process, self._descriptor):
            if owner is not None:
                try:
                    owner.close()
                except BaseException as error:  # noqa: BLE001 -- Close every known original owner.
                    failures.append(error)
        for field in ('_service', '_manager'):
            handle = getattr(self, field)
            if handle:
                if self._api.CloseServiceHandle(handle):
                    setattr(self, field, None)
                else:
                    failures.append(field)
        if failures:
            self._close_failed = True
            error = GuardInstallationError('INSTALLER_SERVICE_CLOSE_UNVERIFIED')
            error.retained_owner = self
            raise error
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
