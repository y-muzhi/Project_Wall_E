"""Bounded nonblocking reads of original backend STDOUT/STDERR pipe ends.

No process creation, termination, waiting, text decoding or business completion.
EOF only completes this byte stream; the original Job/operation remains separate.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from threading import RLock
from uuid import UUID

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .runtime_launch_journal import LaunchScope
from .windows_stdio import BackendStandardIO

READ_CHUNK = 32 * 1024
STREAMS = ('STDOUT', 'STDERR')


class OutputCaptureError(RuntimeError):
    def __init__(self, reason, native_error=None):
        self.reason = reason
        self.native_error = native_error
        super().__init__(reason)


@dataclass(frozen=True)
class OutputProgress:
    scope: LaunchScope = field(repr=False)
    io_nonce: str = field(repr=False)
    stdout_bytes: int
    stderr_bytes: int
    stdout_eof: bool
    stderr_eof: bool
    limit_exceeded: bool
    failure_reason: str | None

    @property
    def complete(self):
        return (
            self.stdout_eof
            and self.stderr_eof
            and not self.limit_exceeded
            and self.failure_reason is None
        )


@dataclass(frozen=True)
class CapturedOutput:
    progress: OutputProgress
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)


def _read_api(kernel):
    kernel.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel.ReadFile.restype = wintypes.BOOL
    return kernel


def read_available_pipe(kernel, handle, limit):
    """One bounded read by the original sole reader. None is observed EOF."""
    available = wintypes.DWORD()
    if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
        error = ctypes.get_last_error()
        if error == 109:
            return None
        raise OutputCaptureError('OUTPUT_PEEK_UNVERIFIED', error)
    if not available.value:
        return b''
    count = min(available.value, READ_CHUNK, limit)
    data = ctypes.create_string_buffer(count)
    received = wintypes.DWORD()
    if not kernel.ReadFile(handle, data, count, ctypes.byref(received), None):
        raise OutputCaptureError('OUTPUT_READ_UNVERIFIED', ctypes.get_last_error())
    if not 1 <= received.value <= count:
        raise OutputCaptureError('OUTPUT_READ_COUNT_UNVERIFIED')
    return data.raw[: received.value]


class BoundedOutputCapture:
    """The one consumer of this actual backend pipe pair, for its whole lifetime."""

    def __init__(self, streams, *, scope, max_output_bytes, drain_after_limit=False):
        if type(streams) is not BackendStandardIO or not isinstance(scope, LaunchScope):
            raise OutputCaptureError('ORIGINAL_BACKEND_OUTPUT_REQUIRED')
        if streams._scope != scope:
            raise OutputCaptureError('ORIGINAL_OUTPUT_SCOPE_DIFFERS')
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_SAFE_INTEGER:
            raise OutputCaptureError('OUTPUT_CAPTURE_LIMIT_INVALID')
        self._gate = RLock()
        self._streams, self._scope = streams, scope
        self._nonce, self._owner = streams._nonce, streams.owner
        if type(drain_after_limit) is not bool:
            raise OutputCaptureError('OUTPUT_DRAIN_POLICY_INVALID')
        self._limit, self._total = max_output_bytes, 0
        self._drain_after_limit = drain_after_limit
        self._buffers = {name: bytearray() for name in STREAMS}
        self._eof = set()
        self._exceeded = False
        self._failure = None
        self._closed = False
        self._first = 0
        self._kernel = _read_api(streams._kernel)
        self._lease = streams.output_endpoints()
        self._handles = dict(zip(STREAMS, self._lease.__enter__(), strict=True))

    def _fail(self, reason, native_error=None):
        self._failure = reason
        error = OutputCaptureError(reason, native_error)
        error.retained_owner = self
        raise error

    def _progress(self):
        return OutputProgress(
            self._scope,
            self._nonce,
            len(self._buffers['STDOUT']),
            len(self._buffers['STDERR']),
            'STDOUT' in self._eof,
            'STDERR' in self._eof,
            self._exceeded,
            self._failure,
        )

    def progress(self):
        with self._gate:
            return self._progress()

    def snapshot(self):
        """A detached private byte snapshot, never an automatic audit log."""
        with self._gate:
            return CapturedOutput(
                self._progress(), bytes(self._buffers['STDOUT']), bytes(self._buffers['STDERR'])
            )

    def require_complete(self):
        with self._gate:
            if not self._progress().complete:
                raise OutputCaptureError('OUTPUT_CAPTURE_INCOMPLETE')
            return self.snapshot()

    def _read_one(self, stream):
        if stream in self._eof or (self._exceeded and not self._drain_after_limit):
            return
        remaining = self._limit - self._total
        size = READ_CHUNK if self._exceeded else remaining + 1
        try:
            data = read_available_pipe(self._kernel, self._handles[stream], size)
        except OutputCaptureError as error:
            self._fail(error.reason, error.native_error)
        if data is None:
            self._eof.add(stream)
            return
        retained = min(len(data), remaining)
        self._buffers[stream].extend(data[:retained])
        self._total += retained
        if len(data) > remaining:
            self._exceeded = True

    def poll(self):
        """At most two bounded reads; no wait or unbounded drain on a busy stream."""
        with self._gate:
            if self._closed:
                raise OutputCaptureError('OUTPUT_CAPTURE_CLOSED')
            if self._failure is not None:
                self._fail(self._failure)
            if (
                self._streams._scope != self._scope
                or self._streams._nonce != self._nonce
                or self._streams.owner != self._owner
            ):
                self._fail('ORIGINAL_OUTPUT_BINDING_DIFFERS')
            order = STREAMS[self._first :] + STREAMS[: self._first]
            self._first = 1 - self._first
            try:
                for stream in order:
                    self._read_one(stream)
            except BaseException as error:
                # ReadFile may already have consumed bytes before interruption
                # or allocation failure. Never resume as if the missing bytes
                # were an empty/successful chunk.
                if self._failure is None:
                    self._failure = 'OUTPUT_CAPTURE_INTERRUPTED'
                error.retained_owner = self
                raise
            return self._progress()

    def close(self):
        with self._gate:
            if not self._closed:
                self._lease.__exit__(None, None, None)
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def verify_original_output(output, *, scope, io_nonce, max_output_bytes):
    if (
        not isinstance(scope, LaunchScope)
        or type(max_output_bytes) is not int
        or not 1 <= max_output_bytes <= MAX_SAFE_INTEGER
    ):
        raise OutputCaptureError('ORIGINAL_OUTPUT_RESULT_BINDING_REQUIRED')
    if type(io_nonce) is not str or len(io_nonce) != 36:
        raise OutputCaptureError('ORIGINAL_OUTPUT_NONCE_INVALID')
    try:
        original_nonce = UUID(io_nonce)
    except ValueError:
        raise OutputCaptureError('ORIGINAL_OUTPUT_NONCE_INVALID') from None
    if original_nonce.version != 4 or str(original_nonce) != io_nonce:
        raise OutputCaptureError('ORIGINAL_OUTPUT_NONCE_INVALID')
    if type(output) is not CapturedOutput or type(output.progress) is not OutputProgress:
        raise OutputCaptureError('COMPLETE_ORIGINAL_OUTPUT_REQUIRED')
    state = output.progress
    if (
        state.scope != scope
        or type(io_nonce) is not str
        or state.io_nonce != io_nonce
        or state.stdout_eof is not True
        or state.stderr_eof is not True
        or state.limit_exceeded is not False
        or state.failure_reason is not None
        or type(output.stdout) is not bytes
        or type(output.stderr) is not bytes
        or type(state.stdout_bytes) is not int
        or state.stdout_bytes != len(output.stdout)
        or type(state.stderr_bytes) is not int
        or state.stderr_bytes != len(output.stderr)
        or len(output.stdout) + len(output.stderr) > max_output_bytes
    ):
        raise OutputCaptureError('COMPLETE_ORIGINAL_OUTPUT_REQUIRED')
    return output


def require_complete_output(output, *, scope, io_nonce, exit_code, max_output_bytes):
    verified = verify_original_output(
        output, scope=scope, io_nonce=io_nonce, max_output_bytes=max_output_bytes
    )
    if type(exit_code) is not int or exit_code != 0 or verified.stderr:
        raise OutputCaptureError('COMPLETE_ORIGINAL_OUTPUT_REQUIRED')
    return verified
