"""Read-only OC20-CONFIG-1 probe for the actual Windows managed source."""

import ctypes
import os
from ctypes import wintypes
from uuid import UUID

from .windows_local_paths import LocalPathGuard, PathBoundaryError, local_absolute_path

_PROGRAM_DATA = UUID('62ab5d82-fdc1-4dc3-a9dd-070d1d495d97')


def _program_data():
    if os.name != 'nt':
        raise PathBoundaryError('OPENCODE_WINDOWS_MANAGED_SOURCE_UNAVAILABLE')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    memory = ctypes.WinDLL('ole32', use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    memory.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    memory.CoInitializeEx.restype = ctypes.c_long
    memory.CoUninitialize.argtypes = []
    memory.CoUninitialize.restype = None
    memory.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    memory.CoTaskMemFree.restype = None
    status = memory.CoInitializeEx(None, 0)
    if status not in (0, 1):
        raise PathBoundaryError('OPENCODE_WINDOWS_COM_UNAVAILABLE', status)
    folder = ctypes.create_string_buffer(_PROGRAM_DATA.bytes_le, 16)
    result = wintypes.LPWSTR()
    try:
        status = shell.SHGetKnownFolderPath(folder, 0, None, ctypes.byref(result))
        if status != 0 or not result:
            raise PathBoundaryError('OPENCODE_WINDOWS_MANAGED_SOURCE_UNAVAILABLE', status)
        return local_absolute_path(result.value)
    finally:
        if result:
            memory.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))
        memory.CoUninitialize()


def _source_is_absent(directory):
    with LocalPathGuard(directory, directory=True) as parent:
        parent.verify()
        try:
            (parent.path / 'opencode').lstat()
        except FileNotFoundError:
            parent.verify()
            return True
        parent.verify()
        return False


def opencode_managed_source_clear():
    """An existing entry, inaccessible path, or unproved volume cannot be bypassed."""
    try:
        return _source_is_absent(_program_data())
    except (OSError, PathBoundaryError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        return False
