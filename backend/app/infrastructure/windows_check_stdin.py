"""Local, one-way overlapped input for a fixed original Testing command."""

import ctypes
import os
from ctypes import wintypes
from threading import get_ident
from time import monotonic
from uuid import uuid4

from .windows_guard_pipe import SERVER_ACCESS, SecurityAttributes, _api, verify_pipe_security
from .windows_guard_pipe_io import CHUNK_LIMIT, PipeIOError, _BoundedPipeTransfer
from .windows_private_package import current_operator_sid

MAX_STDIN_BYTES = 1024 * 1024
_INVALID = ctypes.c_void_p(-1).value


def _error(code):
    return PipeIOError(code, ctypes.get_last_error())


def create_check_stdin():
    """The current backend connects both private ends before transferring the reader."""
    kernel, security = _api()
    sid = current_operator_sid()
    name = r'\\.\pipe\WALLE.CheckInput.' + uuid4().hex
    descriptor = wintypes.LPVOID()
    sddl = f'O:{sid}D:P(A;;0x{SERVER_ACCESS:08x};;;{sid})'
    if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise _error('TESTING_STDIN_DACL_UNAVAILABLE')
    writer = reader = None
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        writer = kernel.CreateNamedPipeW(
            name,
            2 | 0x80000 | 0x40000000,
            8,
            1,
            CHUNK_LIMIT,
            0,
            1000,
            ctypes.byref(attributes),
        )
        if writer in (None, _INVALID):
            raise _error('TESTING_STDIN_WRITER_UNAVAILABLE')
        reader = kernel.CreateFileW(name, 0x80000000, 0, None, 3, 0, None)
        if reader in (None, _INVALID):
            raise _error('TESTING_STDIN_READER_UNAVAILABLE')
        peer = wintypes.ULONG()
        for check, handle in (
            (kernel.GetNamedPipeClientProcessId, writer),
            (kernel.GetNamedPipeServerProcessId, reader),
        ):
            check.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
            check.restype = wintypes.BOOL
            if not check(handle, ctypes.byref(peer)) or peer.value != os.getpid():
                raise _error('TESTING_STDIN_ORIGINAL_PIPE_PEER_DIFFERS')
        verify_pipe_security(kernel, security, writer, server_sid=sid, backend_sid=sid)
        return reader, writer
    except BaseException:
        for handle in (reader, writer):
            if handle not in (None, _INVALID):
                kernel.CloseHandle(handle)
        raise
    finally:
        kernel.LocalFree(descriptor)


class CheckStdinPort:
    def __init__(self, streams):
        self._streams = streams
        self._kernel = streams._kernel
        self._thread = get_ident()

    def _check_thread(self):
        if get_ident() != self._thread or os.getpid() != self._streams.owner.pid:
            raise PipeIOError('TESTING_STDIN_ORIGINAL_OWNER_DIFFERS')

    def verify(self):
        self._check_thread()
        self._streams._verify(('STDIN_WRITE',), inheritable=False)

    def endpoint(self):
        return self._streams.parent_endpoint('STDIN')


class CheckStdinWriter(_BoundedPipeTransfer):
    def __init__(self, streams):
        if not streams._bounded_input:
            raise PipeIOError('TESTING_STDIN_ORIGINAL_PIPE_REQUIRED')
        super().__init__(CheckStdinPort(streams), connected=True)

    def send(self, raw, *, deadline, cancelled):
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_STDIN_BYTES:
            raise PipeIOError('TESTING_STDIN_CAPACITY_DIFFERS')
        for offset in range(0, len(raw), CHUNK_LIMIT):
            timeout = min(300000, int((deadline - monotonic()) * 1000))
            if timeout <= 0 or cancelled():
                raise PipeIOError('TESTING_STDIN_INTERRUPTED')
            self.write_all(
                raw[offset : offset + CHUNK_LIMIT], timeout_ms=timeout, cancelled=cancelled
            )
