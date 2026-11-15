"""Bounded overlapped IO on an original protected Guard pipe endpoint.

Timeout/cancel never proves that a peer processed a request. Only the original
OVERLAPPED is cancelled; buffers/event/endpoint remain strongly owned until its
completion is observed. Unknown native completion retains the owner in-process.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from threading import RLock, get_ident
from time import monotonic

from .windows_guard_pipe import GuardPipeClient, GuardPipeServer

CHUNK_LIMIT = 65536
POLL_MS = 25
CANCEL_WAIT_MS = 1000
_RETAINED = set()
_RETAINED_GATE = RLock()


class PipeIOError(RuntimeError):
    def __init__(self, code, native_error=None, *, transferred=None):
        self.code = code
        self.native_error = native_error
        self.transferred = transferred
        super().__init__(code)


class Overlapped(ctypes.Structure):
    _fields_ = [
        ('internal', ctypes.c_size_t),
        ('internal_high', ctypes.c_size_t),
        ('offset', wintypes.DWORD),
        ('offset_high', wintypes.DWORD),
        ('event', wintypes.HANDLE),
    ]


@dataclass
class _Pending:
    kind: str
    overlapped: Overlapped
    event: int
    buffer: object
    capacity: int
    dispatched: bool = False


def _api(kernel):
    if ctypes.sizeof(Overlapped) != 32:
        raise PipeIOError('PIPE_OVERLAPPED_LAYOUT_UNSUPPORTED')
    kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped)]
    kernel.ConnectNamedPipe.restype = wintypes.BOOL
    for function in (kernel.ReadFile, kernel.WriteFile):
        function.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(Overlapped),
        ]
        function.restype = wintypes.BOOL
    kernel.GetOverlappedResultEx.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Overlapped),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    kernel.GetOverlappedResultEx.restype = wintypes.BOOL
    kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped)]
    kernel.CancelIoEx.restype = wintypes.BOOL
    return kernel


def _deadline(timeout_ms):
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 300000:
        raise PipeIOError('PIPE_IO_TIMEOUT_INVALID')
    return monotonic() + timeout_ms / 1000


class _BoundedPipeTransfer:
    """One serialized consumer; a failed stream must be closed, never replayed."""

    def __init__(self, endpoint, *, connected):
        endpoint._check_thread()
        self._owner_thread = get_ident()
        self._gate = RLock()
        self._endpoint = endpoint
        self._kernel = _api(endpoint._kernel)
        self._lease = endpoint.endpoint()
        self._handle = self._lease.__enter__()
        self._pending = None
        self._framing_owner = None
        self._connected = connected
        self._failed = False
        self._closed = False

    def _check_thread(self):
        if get_ident() != self._owner_thread:
            raise PipeIOError('ORIGINAL_PIPE_IO_OWNER_THREAD_DIFFERS')

    def _check(self):
        self._check_thread()
        if self._closed or self._failed or self._pending is not None:
            raise PipeIOError('ORIGINAL_PIPE_IO_UNAVAILABLE')
        self._endpoint.verify()

    def _allocate(self, kind, capacity, raw=None):
        event = self._kernel.CreateEventW(None, True, False, None)
        if not event:
            raise PipeIOError('PIPE_IO_EVENT_UNAVAILABLE', ctypes.get_last_error())
        pending = _Pending(kind, Overlapped(event=event), event, None, capacity)
        self._pending = pending
        with _RETAINED_GATE:
            _RETAINED.add(self)
        try:
            if capacity:
                pending.buffer = ctypes.create_string_buffer(capacity)
                if raw is not None:
                    ctypes.memmove(pending.buffer, raw, len(raw))
        except BaseException:
            self._complete()
            raise
        return pending

    def _complete(self):
        pending = self._pending
        if pending is None:
            return
        if not self._kernel.CloseHandle(pending.event):
            error = PipeIOError('PIPE_IO_EVENT_CLOSE_UNVERIFIED', ctypes.get_last_error())
            error.retained_owner = self
            raise error
        self._pending = None
        with _RETAINED_GATE:
            _RETAINED.discard(self)

    def _unknown(self, code, native_error):
        self._failed = True
        error = PipeIOError(code, native_error)
        error.retained_owner = self
        raise error

    def _result(self, wait_ms):
        pending = self._pending
        transferred = wintypes.DWORD()
        if self._kernel.GetOverlappedResultEx(
            self._handle,
            ctypes.byref(pending.overlapped),
            ctypes.byref(transferred),
            wait_ms,
            False,
        ):
            if transferred.value > pending.capacity:
                self._unknown('PIPE_IO_TRANSFER_SIZE_UNVERIFIED', None)
            return True, transferred.value, None
        code = ctypes.get_last_error()
        if code in (258, 996):
            return False, None, code
        # These are completed IO outcomes, not a statement about business effects.
        if code in (995, 109, 232, 233, 234):
            return True, None, code
        self._unknown('PIPE_IO_COMPLETION_UNKNOWN', code)

    def _cancel(self):
        pending = self._pending
        if pending is None:
            return None, None
        if not pending.dispatched:
            self._complete()
            return None, None
        if not self._kernel.CancelIoEx(self._handle, ctypes.byref(pending.overlapped)):
            code = ctypes.get_last_error()
            if code != 1168:  # NOT_FOUND may be a completion race; still query the original IO.
                self._unknown('PIPE_IO_CANCEL_UNVERIFIED', code)
        deadline = monotonic() + CANCEL_WAIT_MS / 1000
        while True:
            complete, transferred, code = self._result(POLL_MS)
            if complete:
                self._complete()
                return transferred, code
            if monotonic() >= deadline:
                self._unknown('PIPE_IO_CANCEL_COMPLETION_UNKNOWN', code)

    def _execute(self, kind, capacity, deadline, cancelled, raw=None):
        if cancelled() or monotonic() >= deadline:
            self._failed = True
            raise PipeIOError('PIPE_IO_CANCELLED_BEFORE_DISPATCH')
        pending = self._allocate(kind, capacity, raw)
        count = wintypes.DWORD()
        pointer = ctypes.byref(pending.overlapped)
        pending.dispatched = True
        if kind == 'CONNECT':
            success = self._kernel.ConnectNamedPipe(self._handle, pointer)
        elif kind == 'READ':
            success = self._kernel.ReadFile(
                self._handle, pending.buffer, capacity, ctypes.byref(count), pointer
            )
        else:
            success = self._kernel.WriteFile(
                self._handle, pending.buffer, capacity, ctypes.byref(count), pointer
            )
        if not success:
            code = ctypes.get_last_error()
            if kind == 'CONNECT' and code == 535:  # Peer connected before ConnectNamedPipe.
                self._complete()
                return b''
            if code != 997:
                self._failed = True
                self._complete()
                raise PipeIOError('PIPE_IO_DISPATCH_FAILED', code)
        try:
            wait_ms = 0
            while True:
                complete, transferred, code = self._result(wait_ms)
                if complete:
                    data = (
                        bytes(pending.buffer.raw[:transferred])
                        if kind == 'READ' and transferred is not None
                        else transferred
                    )
                    self._complete()
                    if code is not None:
                        self._failed = True
                        raise PipeIOError('PIPE_IO_FAILED', code)
                    return data
                if cancelled() or monotonic() >= deadline:
                    self._failed = True
                    transferred, code = self._cancel()
                    raise PipeIOError(
                        'PIPE_IO_CANCELLED_OR_TIMED_OUT', code, transferred=transferred
                    )
                wait_ms = max(1, min(POLL_MS, int((deadline - monotonic()) * 1000)))
        except BaseException as error:
            self._failed = True
            if self._pending is not None and getattr(error, 'retained_owner', None) is not self:
                self._cancel()
            raise

    def connect(self, *, timeout_ms, cancelled):
        self._check_thread()
        deadline = _deadline(timeout_ms)
        with self._gate:
            self._check()
            if self._connected:
                raise PipeIOError('ORIGINAL_PIPE_ALREADY_CONNECTED')
            self._execute('CONNECT', 0, deadline, cancelled)
            self._connected = True

    def read_exact(self, count, *, timeout_ms, cancelled):
        self._check_thread()
        deadline = _deadline(timeout_ms)
        if type(count) is not int or not 1 <= count <= CHUNK_LIMIT:
            raise PipeIOError('PIPE_READ_CAPACITY_INVALID')
        with self._gate:
            self._check()
            if not self._connected:
                raise PipeIOError('ORIGINAL_PIPE_NOT_CONNECTED')
            result = bytearray()
            while len(result) < count:
                current = self._execute('READ', count - len(result), deadline, cancelled)
                if not current:
                    self._failed = True
                    raise PipeIOError('PIPE_READ_EOF')
                result.extend(current)
            return bytes(result)

    def write_all(self, raw, *, timeout_ms, cancelled):
        self._check_thread()
        deadline = _deadline(timeout_ms)
        if type(raw) is not bytes or not 1 <= len(raw) <= CHUNK_LIMIT:
            raise PipeIOError('PIPE_WRITE_CAPACITY_INVALID')
        with self._gate:
            self._check()
            if not self._connected:
                raise PipeIOError('ORIGINAL_PIPE_NOT_CONNECTED')
            sent = 0
            while sent < len(raw):
                transferred = self._execute(
                    'WRITE', len(raw) - sent, deadline, cancelled, raw[sent:]
                )
                if not transferred:
                    self._failed = True
                    raise PipeIOError('PIPE_WRITE_INCOMPLETE')
                sent += transferred

    def close(self):
        self._check_thread()
        with self._gate:
            self._failed = True
            if self._pending is not None:
                self._cancel()
            if self._lease is not None:
                lease, self._lease = self._lease, None
                lease.__exit__(None, None, None)
            self._closed = True

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


class GuardPipeIO(_BoundedPipeTransfer):
    def __init__(self, endpoint):
        if type(endpoint) not in (GuardPipeServer, GuardPipeClient):
            raise TypeError('Original protected Guard endpoint required')
        super().__init__(endpoint, connected=type(endpoint) is GuardPipeClient)
