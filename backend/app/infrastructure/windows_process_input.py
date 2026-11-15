"""Bounded writes to the original backend's noninherited pipe endpoint."""

import ctypes
from ctypes import wintypes

from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_stdio import BackendStandardIO

PIPE_NOWAIT = 1
MAX_TYPED_INPUT_BYTES = 512


class OriginalProcessInput:
    def __init__(self, streams):
        if type(streams) is not BackendStandardIO or streams._copy_binding is None:
            raise TypeError('Original prepared backend STDIO required')
        self._streams = streams
        self._binding = streams._copy_binding
        self._kernel = streams._kernel
        self._kernel.SetNamedPipeHandleState.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel.SetNamedPipeHandleState.restype = wintypes.BOOL
        self._kernel.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self._kernel.WriteFile.restype = wintypes.BOOL
        with streams.parent_endpoint('STDIN') as handle:
            mode = wintypes.DWORD(PIPE_NOWAIT)
            if not self._kernel.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
                raise LaunchOutcomeUnknown('ORIGINAL_PROCESS_INPUT_MODE_UNVERIFIED')

    def write_available(self, data):
        if type(data) is not bytes or not 1 <= len(data) <= MAX_TYPED_INPUT_BYTES:
            raise ValueError('Original typed pipe payload required')
        if self._streams._copy_binding != self._binding:
            raise LaunchOutcomeUnknown('ORIGINAL_PROCESS_INPUT_BINDING_DIFFERS')
        written = wintypes.DWORD()
        with self._streams.parent_endpoint('STDIN') as handle:
            if not self._kernel.WriteFile(
                handle, data, len(data), ctypes.byref(written), None
            ) or written.value > len(data):
                raise LaunchOutcomeUnknown('ORIGINAL_PROCESS_INPUT_WRITE_UNVERIFIED')
        return written.value

    def write(self, data):
        if self.write_available(data) != len(data):
            raise LaunchOutcomeUnknown('ORIGINAL_PROCESS_INPUT_WRITE_UNVERIFIED')
