"""Private CHECK_DRIVER result pipe, independent of standard streams.

Only the Guard copies the offered writer. Its explicit creation handle belongs to
one suspended driver root, and the registered bootstrap clears inheritance
before it can create a browser. The backend owns the sole reader.
"""

import ctypes
import os
import re
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from uuid import uuid4

from .check_case_evidence import BrowserCaseFrames, CheckEvidenceUnknown, DriverFrameIdentity
from .runtime_launch_journal import LaunchFence, TestingLaunchScope
from .windows_controller_token import ControllerPrimaryToken
from .windows_pipe_capture import OutputCaptureError, _read_api, read_available_pipe
from .windows_process import NativeProcessIdentity, ObservedProcess, _identity
from .windows_stdio import StdioBoundaryError, _error, _handle, _handle_text, _OwnedPipeEnds

_READ = 'DRIVER_RESULT_READ'
_WRITE = 'DRIVER_RESULT_WRITE'
_HEADER_BYTES = 4
_MAX_FRAME_BYTES = 128 * 1024
_MAX_STREAM_BYTES = 16 * 1024 * 1024


def _nonce(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{32}', value) is not None


@dataclass(frozen=True)
class DriverPipeOffer:
    scope: TestingLaunchScope
    owner: NativeProcessIdentity
    nonce: str
    write_handle: str = field(repr=False)

    def __post_init__(self):
        if (
            type(self.scope) is not TestingLaunchScope
            or type(self.owner) is not NativeProcessIdentity
            or not _nonce(self.nonce)
        ):
            raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_OFFER_REQUIRED')
        _handle(self.write_handle)


@dataclass(frozen=True)
class DriverPipeBinding:
    scope: TestingLaunchScope
    owner: NativeProcessIdentity
    nonce: str
    guard_io_ref: str

    def __post_init__(self):
        if (
            type(self.scope) is not TestingLaunchScope
            or type(self.owner) is not NativeProcessIdentity
            or not _nonce(self.nonce)
            or not _nonce(self.guard_io_ref)
        ):
            raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_BINDING_REQUIRED')


class BackendDriverResultPipe(_OwnedPipeEnds):
    """Backend retains an uncertain offer until its original scope is closed."""

    def __init__(self, scope):
        if type(scope) is not TestingLaunchScope:
            raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_SCOPE_REQUIRED')
        self._initialize()
        self.scope = scope
        self.nonce = uuid4().hex
        self._state = 'LOCAL'
        self._binding = None
        self._reader_claimed = False
        with ObservedProcess(os.getpid()) as current:
            self.owner = current.identity
        read, write = wintypes.HANDLE(), wintypes.HANDLE()
        if not self._kernel.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0):
            raise _error('DRIVER_RESULT_PIPE_UNAVAILABLE')
        self._ends.update({_READ: read.value, _WRITE: write.value})
        try:
            self._verify((_READ, _WRITE), inheritable=False)
        except BaseException:
            self.close()
            raise

    def descriptor(self):
        with self._gate:
            if self._state != 'LOCAL' or os.getpid() != self.owner.pid:
                raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_OFFER_ALREADY_DISPATCHED')
            self._verify((_WRITE,), inheritable=False)
            return DriverPipeOffer(
                self.scope, self.owner, self.nonce, _handle_text(self._ends[_WRITE])
            )

    def offer(self):
        with self._gate:
            offer = self.descriptor()
            self._state = 'OFFERED'
            return offer

    def acknowledge(self, binding):
        with self._gate:
            if (
                type(binding) is not DriverPipeBinding
                or (binding.scope, binding.owner, binding.nonce)
                != (self.scope, self.owner, self.nonce)
                or self._state not in ('OFFERED', 'ACKNOWLEDGED')
                or self._binding is not None
                and self._binding != binding
            ):
                raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_ACK_DIFFERS')
            self._binding = binding
            self._state = 'ACKNOWLEDGED'
            self._close((_WRITE,))

    def close_offer(self, fence):
        with self._gate:
            if type(fence) is not LaunchFence or fence.scope != self.scope or not fence.stop_closed:
                raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_STOP_REQUIRED')
            self._state = 'CLOSED'
            self._close((_WRITE,))

    @contextmanager
    def claim_reader(self):
        with self._gate:
            if (
                self._state != 'ACKNOWLEDGED'
                or self._reader_claimed
                or os.getpid() != self.owner.pid
            ):
                raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_READER_REQUIRED')
            lease = self._borrow((_READ,), inheritable=False)
            handles = lease.__enter__()
            self._reader_claimed = True
        try:
            yield handles[0]
        finally:
            lease.__exit__(None, None, None)

    def close(self):
        with self._gate:
            if self._state == 'OFFERED':
                error = StdioBoundaryError('ORIGINAL_DRIVER_RESULT_OFFER_UNKNOWN')
                error.retained_owner = self
                raise error
            super().close()

    def __enter__(self):
        return self


class GuardDriverResultWriter(_OwnedPipeEnds):
    """One verified same-access writer and one explicit root creation lease."""

    def __init__(self, controller, scope, offer):
        if (
            type(controller) is not ControllerPrimaryToken
            or type(scope) is not TestingLaunchScope
            or type(offer) is not DriverPipeOffer
            or (offer.scope, offer.owner) != (scope, controller._expected)
        ):
            raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_CONTROLLER_DIFFERS')
        self._initialize()
        self._controller = controller
        self._leased = False
        try:
            with controller.creation_handle():
                source = self._kernel.OpenProcess(0x40 | 0x1000 | 0x100000, False, offer.owner.pid)
                if not source:
                    raise _error('DRIVER_RESULT_SOURCE_UNAVAILABLE')
                self._source_process = source
                if _identity(self._kernel, self._security, source, offer.owner.pid) != offer.owner:
                    raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_PROCESS_DIFFERS')
                handle = wintypes.HANDLE()
                if not self._kernel.DuplicateHandle(
                    source,
                    _handle(offer.write_handle),
                    self._kernel.GetCurrentProcess(),
                    ctypes.byref(handle),
                    0,
                    True,
                    2,
                ):
                    raise _error('DRIVER_RESULT_COPY_UNAVAILABLE')
                self._ends[_WRITE] = handle.value
                self._verify((_WRITE,), inheritable=True)
                if not self._kernel.CloseHandle(source):
                    raise _error('DRIVER_RESULT_SOURCE_CLOSE_UNVERIFIED')
                self._source_process = None
            self.binding = DriverPipeBinding(scope, offer.owner, offer.nonce, uuid4().hex)
        except BaseException:
            self.close()
            raise

    @contextmanager
    def creation_handle(self, scope):
        with self._gate:
            if scope != self.binding.scope or self._leased:
                raise StdioBoundaryError('ORIGINAL_DRIVER_RESULT_CREATION_DIFFERS')
            self._leased = True
        with self._controller.creation_handle(), self._borrow((_WRITE,), inheritable=True) as pair:
            yield pair[0]

    def __enter__(self):
        return self


class DriverResultStream:
    """One bounded frame reader. EOF is necessary and cannot prove root exit."""

    def __init__(self, pipe, identity, pack, *, max_bytes):
        if (
            type(pipe) is not BackendDriverResultPipe
            or type(identity) is not DriverFrameIdentity
            or identity.nonce != pipe.scope.nonce
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= _MAX_STREAM_BYTES
        ):
            raise CheckEvidenceUnknown('ORIGINAL_DRIVER_RESULT_STREAM_REQUIRED')
        self._frames = BrowserCaseFrames(identity, pack, max_bytes=max_bytes)
        self._pipe = pipe
        self._kernel = _read_api(pipe._kernel)
        self._maximum, self._seen = max_bytes, 0
        self._buffer = bytearray()
        self._eof = self._invalid = self._closed = False
        self._lease = pipe.claim_reader()
        self._handle = self._lease.__enter__()

    def poll(self):
        if self._closed or self._invalid:
            raise CheckEvidenceUnknown('ORIGINAL_DRIVER_RESULT_STREAM_UNAVAILABLE')
        if self._eof:
            return True
        try:
            data = read_available_pipe(self._kernel, self._handle, self._maximum - self._seen + 1)
            if data is None:
                if self._buffer:
                    raise CheckEvidenceUnknown('ORIGINAL_DRIVER_RESULT_FRAME_TRUNCATED')
                self._eof = True
                return True
            self._seen += len(data)
            if self._seen > self._maximum:
                raise CheckEvidenceUnknown('ORIGINAL_DRIVER_RESULT_OUTPUT_LIMIT')
            self._buffer.extend(data)
            self._consume_frames()
            return False
        except (OutputCaptureError, CheckEvidenceUnknown):
            self._invalid = True
            self._buffer.clear()
            raise

    def _consume_frames(self):
        while len(self._buffer) >= _HEADER_BYTES:
            size = int.from_bytes(self._buffer[:_HEADER_BYTES], 'big')
            if not 1 <= size <= _MAX_FRAME_BYTES or size + _HEADER_BYTES > self._maximum:
                raise CheckEvidenceUnknown('ORIGINAL_DRIVER_RESULT_FRAME_SIZE_INVALID')
            end = _HEADER_BYTES + size
            if len(self._buffer) < end:
                return
            self._frames.receive(bytes(self._buffer[_HEADER_BYTES:end]))
            del self._buffer[:end]

    def finish(self, *, authenticated_root, original_exit_code):
        if not self._eof or self._invalid:
            raise CheckEvidenceUnknown('ORIGINAL_DRIVER_RESULT_EOF_REQUIRED')
        return self._frames.finish(
            authenticated_root=authenticated_root, original_exit_code=original_exit_code
        )

    def close(self):
        if not self._closed:
            self._lease.__exit__(None, None, None)
            self._closed = True
            self._buffer.clear()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
