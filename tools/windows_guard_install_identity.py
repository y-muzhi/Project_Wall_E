"""Installer-only identity gate and bounded restoration of its existing SeRestorePrivilege."""

import ctypes
import os
from ctypes import wintypes

from backend.app.infrastructure.windows_check_logon import _security_state
from backend.app.infrastructure.windows_controller_token import Luid, _luid
from backend.app.infrastructure.windows_private_package import _api, _sid_text, current_operator_sid
from backend.app.infrastructure.windows_process import ObservedProcess, _token_buffer
from tools.windows_guard_install_contract import ADMINISTRATORS, SYSTEM, GuardInstallationError


class Privilege(ctypes.Structure):
    _fields_ = [('luid', Luid), ('attributes', wintypes.DWORD)]


class OnePrivilege(ctypes.Structure):
    _fields_ = [('count', wintypes.DWORD), ('members', Privilege * 1)]


class InstallationOperator:
    def __init__(self, backend_sid):
        self._kernel, self._security = _api()
        self._process = None
        self._token = None
        self._closed = False
        self._close_failed = False
        self.backend_sid = backend_sid
        try:
            self._process = ObservedProcess(os.getpid())
            observed = self._process.observe()
            if (
                observed.state != 'RUNNING'
                or observed.identity.is_appcontainer
                or not observed.identity.is_elevated
                or observed.identity.user_sid != backend_sid
                or backend_sid in (SYSTEM, 'S-1-5-19', 'S-1-5-20')
                or current_operator_sid() != backend_sid
            ):
                raise GuardInstallationError('ELEVATED_SAME_USER_INSTALLATION_OPERATOR_REQUIRED')
            handle = wintypes.HANDLE()
            if not self._security.OpenProcessToken(
                self._kernel.GetCurrentProcess(), 0x28, ctypes.byref(handle)
            ):
                raise GuardInstallationError('INSTALLER_ORIGINAL_PRIMARY_TOKEN_UNAVAILABLE')
            self._token = handle.value
            self.verify()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def verify(self):
        if self._closed or self._close_failed or self._token is None:
            raise GuardInstallationError('INSTALLER_OPERATOR_OWNER_CLOSED')
        actual = self._process.observe()
        if actual.state != 'RUNNING' or not actual.identity.is_elevated:
            raise GuardInstallationError('INSTALLER_ORIGINAL_OPERATOR_NOT_RUNNING')
        if current_operator_sid() != self.backend_sid:
            raise GuardInstallationError('INSTALLER_OPERATOR_CHANGED')
        owner, size = _token_buffer(self._security, self._token, 4)
        if size < ctypes.sizeof(wintypes.LPVOID):
            raise GuardInstallationError('INSTALLER_TOKEN_DEFAULT_OWNER_UNAVAILABLE')
        sid = ctypes.cast(owner, ctypes.POINTER(wintypes.LPVOID)).contents
        if _sid_text(self._kernel, self._security, sid) != ADMINISTRATORS:
            raise GuardInstallationError('INSTALLER_TRUSTED_DEFAULT_OWNER_REQUIRED')
        return self

    def close(self):
        if self._close_failed:
            error = GuardInstallationError('INSTALLER_OPERATOR_CLOSE_PREVIOUSLY_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        failures = []
        if self._token is not None:
            if self._kernel.CloseHandle(self._token):
                self._token = None
            else:
                failures.append('primary token')
        if self._process is not None:
            try:
                self._process.close()
                self._process = None
            except BaseException as error:  # noqa: BLE001 -- Close known owners once.
                failures.append(error)
        if failures:
            self._close_failed = True
            error = GuardInstallationError('INSTALLER_OPERATOR_CLOSE_UNVERIFIED')
            error.retained_owner = self
            raise error
        self._closed = True

    def __enter__(self):
        try:
            return self.verify()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def __exit__(self, kind, error, traceback):
        self.close()


class RestorePrivilege:
    """Never add privileges or touch another process; restore the exact prior state."""

    def __init__(self, operator):
        if type(operator) is not InstallationOperator:
            raise GuardInstallationError('ACTUAL_INSTALLATION_OPERATOR_REQUIRED')
        self.operator = operator.verify()
        self._closed = False
        self._close_failed = False
        self._snapshot = None
        security = operator._security
        security.LookupPrivilegeValueW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.POINTER(Luid),
        ]
        security.LookupPrivilegeValueW.restype = wintypes.BOOL
        security.AdjustTokenPrivileges.argtypes = [
            wintypes.HANDLE,
            wintypes.BOOL,
            ctypes.POINTER(OnePrivilege),
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
        ]
        security.AdjustTokenPrivileges.restype = wintypes.BOOL
        self._luid = Luid()
        if not security.LookupPrivilegeValueW(None, 'SeRestorePrivilege', ctypes.byref(self._luid)):
            raise GuardInstallationError('INSTALLER_RESTORE_PRIVILEGE_IDENTITY_UNAVAILABLE')
        self._key = _luid(self._luid)

    def _state(self):
        self.operator.verify()
        groups, privileges = _security_state(
            self.operator._kernel, self.operator._security, self.operator._token
        )
        return groups, {key: value & 3 for key, value in privileges}

    def _adjust(self, attributes):
        requested = OnePrivilege()
        requested.count = 1
        requested.members[0].luid = self._luid
        requested.members[0].attributes = attributes
        ctypes.set_last_error(0)
        if (
            not self.operator._security.AdjustTokenPrivileges(
                self.operator._token, False, ctypes.byref(requested), 0, None, None
            )
            or ctypes.get_last_error() != 0
        ):
            raise GuardInstallationError('INSTALLER_RESTORE_PRIVILEGE_CHANGE_UNVERIFIED')

    def __enter__(self):
        if self._snapshot is not None or self._closed:
            raise GuardInstallationError('INSTALLER_PRIVILEGE_SCOPE_ALREADY_USED')
        self._snapshot = self._state()
        try:
            attributes = self._snapshot[1].get(self._key)
            if attributes is None:
                raise GuardInstallationError('EXISTING_INSTALLER_RESTORE_PRIVILEGE_REQUIRED')
            self._adjust(attributes | 2)
            expected = self._snapshot[0], {**self._snapshot[1], self._key: attributes | 2}
            if self._state() != expected:
                raise GuardInstallationError('INSTALLER_RESTORE_PRIVILEGE_NOT_EFFECTIVE')
            return self
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def close(self):
        if self._close_failed:
            error = GuardInstallationError('INSTALLER_PRIVILEGE_RESTORATION_PREVIOUSLY_UNVERIFIED')
            error.retained_owner = self
            raise error
        if self._closed:
            return
        try:
            if self._snapshot is not None:
                current = self._state()
                if current != self._snapshot:
                    old = self._snapshot[1].get(self._key)
                    expected = (
                        self._snapshot[0],
                        {**self._snapshot[1], self._key: (old | 2) if old is not None else 2},
                    )
                    if old is None or current != expected:
                        raise GuardInstallationError('INSTALLER_PRIVILEGE_STATE_UNKNOWN')
                    self._adjust(old)
                    if self._state() != self._snapshot:
                        raise GuardInstallationError('INSTALLER_PRIVILEGE_RESTORATION_UNVERIFIED')
            self._closed = True
        except BaseException as original:
            self._close_failed = True
            error = GuardInstallationError('INSTALLER_PRIVILEGE_RESTORATION_UNVERIFIED')
            error.retained_owner = self
            raise error from original

    def __exit__(self, kind, error, traceback):
        self.close()
