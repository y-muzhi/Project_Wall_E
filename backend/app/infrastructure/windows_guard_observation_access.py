"""Allow a Guard's configured backend to verify its live Windows identity."""

import ctypes
import os
from contextlib import ExitStack
from ctypes import wintypes

from .windows_private_package import _sid_text, current_operator_sid
from .windows_process import PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE, TOKEN_QUERY
from .windows_process import _api as process_api

_SYSTEM_SID = 'S-1-5-18'
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_SE_KERNEL_OBJECT = 6
_DACL_SECURITY_INFORMATION = 0x4
_GRANT_ACCESS = 1
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_USER = 1


class GuardObservationAccessError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


class _Trustee(ctypes.Structure):
    _fields_ = [
        ('multiple_trustee', wintypes.LPVOID),
        ('multiple_operation', ctypes.c_int),
        ('form', ctypes.c_int),
        ('type', ctypes.c_int),
        ('identifier', wintypes.LPVOID),
    ]


class _ExplicitAccess(ctypes.Structure):
    _fields_ = [
        ('rights', wintypes.DWORD),
        ('mode', ctypes.c_int),
        ('inheritance', wintypes.DWORD),
        ('trustee', _Trustee),
    ]


def _api():
    kernel, security = process_api()
    pointer = ctypes.POINTER(wintypes.LPVOID)
    object_args = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD]
    security.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, pointer]
    security.ConvertStringSidToSidW.restype = wintypes.BOOL
    security.GetSecurityInfo.argtypes = [*object_args, *([pointer] * 5)]
    security.GetSecurityInfo.restype = wintypes.DWORD
    security.SetSecurityInfo.argtypes = [*object_args, *([wintypes.LPVOID] * 4)]
    security.SetSecurityInfo.restype = wintypes.DWORD
    security.SetEntriesInAclW.argtypes = [
        wintypes.ULONG,
        ctypes.POINTER(_ExplicitAccess),
        wintypes.LPVOID,
        pointer,
    ]
    security.SetEntriesInAclW.restype = wintypes.DWORD
    return kernel, security


def _grant_access(kernel, security, handle, sid, rights, code):
    dacl = wintypes.LPVOID()
    descriptor = wintypes.LPVOID()
    updated_dacl = wintypes.LPVOID()
    with ExitStack() as cleanup:
        status = security.GetSecurityInfo(
            handle,
            _SE_KERNEL_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if descriptor.value:
            cleanup.callback(kernel.LocalFree, descriptor)
        if status or not dacl.value:
            raise GuardObservationAccessError(code, status or None)

        entry = _ExplicitAccess(
            rights, _GRANT_ACCESS, 0, _Trustee(None, 0, _TRUSTEE_IS_SID, _TRUSTEE_IS_USER, sid)
        )
        status = security.SetEntriesInAclW(1, ctypes.byref(entry), dacl, ctypes.byref(updated_dacl))
        if updated_dacl.value:
            cleanup.callback(kernel.LocalFree, updated_dacl)
        if status or not updated_dacl.value:
            raise GuardObservationAccessError(code, status or None)

        status = security.SetSecurityInfo(
            handle, _SE_KERNEL_OBJECT, _DACL_SECURITY_INFORMATION, None, None, updated_dacl, None
        )
        if status:
            raise GuardObservationAccessError(code, status)


def grant_backend_observation_access(backend_sid):
    """Merge read-only ACEs on this SYSTEM process and its primary token only."""
    if current_operator_sid() != _SYSTEM_SID or backend_sid == _SYSTEM_SID:
        raise GuardObservationAccessError('GUARD_OBSERVATION_IDENTITY_INVALID')

    kernel, security = _api()
    sid = wintypes.LPVOID()
    process_code = 'GUARD_OBSERVATION_PROCESS_DACL_UNAVAILABLE'
    token_code = 'GUARD_OBSERVATION_TOKEN_DACL_UNAVAILABLE'
    with ExitStack() as cleanup:
        if not security.ConvertStringSidToSidW(backend_sid, ctypes.byref(sid)):
            raise GuardObservationAccessError(
                'GUARD_OBSERVATION_IDENTITY_INVALID', ctypes.get_last_error()
            )
        cleanup.callback(kernel.LocalFree, sid)
        if _sid_text(kernel, security, sid) != backend_sid:
            raise GuardObservationAccessError('GUARD_OBSERVATION_IDENTITY_INVALID')

        process = kernel.OpenProcess(
            _READ_CONTROL | _WRITE_DAC | PROCESS_QUERY_LIMITED_INFORMATION, False, os.getpid()
        )
        if not process:
            raise GuardObservationAccessError(process_code, ctypes.get_last_error())
        cleanup.callback(kernel.CloseHandle, process)

        token = wintypes.HANDLE()
        if not security.OpenProcessToken(
            process, _READ_CONTROL | _WRITE_DAC | TOKEN_QUERY, ctypes.byref(token)
        ):
            raise GuardObservationAccessError(token_code, ctypes.get_last_error())
        cleanup.callback(kernel.CloseHandle, token)

        _grant_access(
            kernel,
            security,
            process,
            sid,
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
            process_code,
        )
        _grant_access(kernel, security, token, sid, TOKEN_QUERY, token_code)
