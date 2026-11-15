"""Read the actual Windows runtime host ABI and build for deployment admission."""

import ctypes
import os
from ctypes import wintypes

from .runtime_launch_journal import LaunchOutcomeUnknown

_AMD64 = 0x8664


class _WindowsVersion(ctypes.Structure):
    _fields_ = [
        ('size', wintypes.DWORD),
        ('major', wintypes.DWORD),
        ('minor', wintypes.DWORD),
        ('build', wintypes.DWORD),
        ('platform', wintypes.DWORD),
        ('service_pack', wintypes.WCHAR * 128),
        ('service_pack_major', wintypes.WORD),
        ('service_pack_minor', wintypes.WORD),
        ('suite', wintypes.WORD),
        ('product_type', ctypes.c_ubyte),
        ('reserved', ctypes.c_ubyte),
    ]


def _windows_build():
    version = _WindowsVersion()
    version.size = ctypes.sizeof(version)
    if version.size != 284:
        raise LaunchOutcomeUnknown('TASK_WINDOWS_VERSION_LAYOUT_UNSUPPORTED')
    native = ctypes.WinDLL('ntdll').RtlGetVersion
    native.argtypes = [ctypes.POINTER(_WindowsVersion)]
    native.restype = ctypes.c_long
    if native(ctypes.byref(version)) != 0 or version.platform != 2:
        raise LaunchOutcomeUnknown('TASK_WINDOWS_VERSION_UNVERIFIED')
    if (
        (version.major, version.minor) != (10, 0)
        or version.build < 22000
        or version.product_type != 1
    ):
        raise LaunchOutcomeUnknown('TASK_WINDOWS_11_BUILD_REQUIRED')
    return [version.major, version.minor, version.build]


def windows_runtime_host_identity():
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise LaunchOutcomeUnknown('TASK_NATIVE_WINDOWS_X64_REQUIRED')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetCurrentProcess.argtypes = []
    api.GetCurrentProcess.restype = wintypes.HANDLE
    identify = api.IsWow64Process2
    identify.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.POINTER(ctypes.c_uint16),
    ]
    identify.restype = wintypes.BOOL
    emulated, native = ctypes.c_uint16(), ctypes.c_uint16()
    if (
        not identify(api.GetCurrentProcess(), ctypes.byref(emulated), ctypes.byref(native))
        or emulated.value != 0
        or native.value != _AMD64
    ):
        raise LaunchOutcomeUnknown('TASK_NATIVE_WINDOWS_X64_REQUIRED')
    return {'architecture': 'AMD64', 'windows_version': _windows_build()}
