"""Root-owned private Windows GUI namespace for the fixed LPAC browser."""

import ctypes
import os
from ctypes import wintypes
from threading import get_native_id
from uuid import uuid4

from .check_case_evidence import CheckEvidenceUnknown
from .windows_private_package import SecurityAttributes, _api
from .windows_process import ObservedProcess


def _gui_api():
    user = ctypes.WinDLL('user32', use_last_error=True)
    for name in ('GetProcessWindowStation',):
        getattr(user, name).argtypes = []
        getattr(user, name).restype = wintypes.HANDLE
    user.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user.GetThreadDesktop.restype = wintypes.HANDLE
    for name in (
        'SetProcessWindowStation',
        'SetThreadDesktop',
        'CloseWindowStation',
        'CloseDesktop',
    ):
        getattr(user, name).argtypes = [wintypes.HANDLE]
        getattr(user, name).restype = wintypes.BOOL
    user.CreateWindowStationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    user.CreateWindowStationW.restype = wintypes.HANDLE
    user.CreateDesktopW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    user.CreateDesktopW.restype = wintypes.HANDLE
    return user


class PrivateBrowserDesktop:
    """Create-only objects, no inherited GUI handles or changes to user objects."""

    def __init__(self):
        self._user = _gui_api()
        self._kernel, self._security = _api()
        self._station = self._desktop = None
        self._previous_station = self._previous_desktop = None
        self._thread = get_native_id()
        self._station_changed = self._desktop_changed = False
        self._closed = False

    def __enter__(self):
        with ObservedProcess(os.getpid()) as root:
            identity = root.identity
        if not identity.is_appcontainer or identity.is_lpac is False or identity.is_elevated:
            raise CheckEvidenceUnknown('ORIGINAL_LPAC_GUI_ROOT_REQUIRED')
        if identity.is_lpac is None:
            from .windows_lpac_token import prove_current_lpac_opt_out

            prove_current_lpac_opt_out(identity.user_sid, identity.appcontainer_sid)
        descriptor = wintypes.LPVOID()
        user = self._user
        text = (
            'D:P(A;OICI;GA;;;' + identity.user_sid + ')'
            '(A;OICI;GA;;;' + identity.appcontainer_sid + ')S:(ML;;NW;;;LW)'
        )
        if not self._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text, 1, ctypes.byref(descriptor), None
        ):
            raise CheckEvidenceUnknown('PRIVATE_BROWSER_GUI_POLICY_FAILED')
        try:
            self._previous_station = user.GetProcessWindowStation()
            self._previous_desktop = user.GetThreadDesktop(self._thread)
            if not self._previous_station or not self._previous_desktop:
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_GUI_ORIGIN_UNVERIFIED')
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            self._station = user.CreateWindowStationW(
                None, 1, 0x37F | 0x20000, ctypes.byref(attributes)
            )
            if not self._station:
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_WINDOWSTATION_UNAVAILABLE')
            if not user.SetProcessWindowStation(self._station):
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_WINDOWSTATION_ATTACH_FAILED')
            self._station_changed = True
            self._desktop = user.CreateDesktopW(
                'wallecheck-' + uuid4().hex, None, None, 0, 0x200C7, ctypes.byref(attributes)
            )
            if not self._desktop:
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_DESKTOP_UNAVAILABLE')
            if not user.SetThreadDesktop(self._desktop):
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_DESKTOP_ATTACH_FAILED')
            self._desktop_changed = True
            return self
        except BaseException:
            self.close()
            raise
        finally:
            if self._kernel.LocalFree(descriptor):
                self.close()
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_GUI_POLICY_RELEASE_UNKNOWN')

    def close(self):
        if self._closed:
            return
        if get_native_id() != self._thread:
            raise CheckEvidenceUnknown('PRIVATE_BROWSER_GUI_THREAD_DIFFERS')
        user = self._user
        if self._station_changed:
            if not user.SetProcessWindowStation(self._previous_station):
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_GUI_ORIGIN_RESTORE_UNKNOWN')
            self._station_changed = False
        if self._desktop_changed:
            if not user.SetThreadDesktop(self._previous_desktop):
                raise CheckEvidenceUnknown('PRIVATE_BROWSER_GUI_THREAD_RESTORE_UNKNOWN')
            self._desktop_changed = False
        for attribute, close in (
            ('_desktop', user.CloseDesktop),
            ('_station', user.CloseWindowStation),
        ):
            handle = getattr(self, attribute)
            if handle:
                if not close(handle):
                    raise CheckEvidenceUnknown('PRIVATE_BROWSER_GUI_RELEASE_UNKNOWN')
                setattr(self, attribute, None)
        self._closed = True

    def __exit__(self, *unused):
        self.close()
