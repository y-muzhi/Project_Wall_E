"""A bounded fixed cat-file batch reader on one original Git STDIO binding."""

import math
import re
from dataclasses import dataclass
from threading import get_ident
from time import monotonic, sleep

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import object_format
from .git_commit_closure import ObjectReadRequest
from .git_object_read import GitObjectReadError, _binding, verify_git_object
from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope
from .windows_pipe_capture import STREAMS, _read_api, read_available_pipe
from .windows_process_input import OriginalProcessInput
from .windows_stdio import BackendStandardIO

MAX_HEADER_BYTES = 128


def _positive(value):
    return type(value) is int and 1 <= value <= MAX_SAFE_INTEGER


def _batch_size(header, request):
    if header == request.object_oid.encode('ascii') + b' missing':
        raise GitObjectReadError('ORIGINAL_BATCH_OBJECT_MISSING')
    fields = header.split(b' ')
    if (
        len(fields) != 3
        or fields[0] != request.object_oid.encode('ascii')
        or fields[1] != request.object_type.encode('ascii')
        or re.fullmatch(rb'0|[1-9][0-9]{0,15}', fields[2]) is None
    ):
        raise GitObjectReadError('ORIGINAL_BATCH_HEADER_DIFFERS')
    size = int(fields[2])
    if size > request.max_output_bytes:
        raise GitObjectReadError('ORIGINAL_BATCH_OBJECT_TOO_LARGE')
    return size


@dataclass(frozen=True)
class BatchCompletion:
    scope: LaunchScope
    io_nonce: str
    request_count: int
    output_bytes: int


class GitObjectBatch:
    """Exactly one writer and output consumer. One unverified frame retires this stream."""

    def __init__(
        self, streams, *, scope, format, max_requests, max_output_bytes, deadline, cancelled
    ):
        object_format(format)
        if (
            type(streams) is not BackendStandardIO
            or type(scope) is not LaunchScope
            or streams._scope != scope
            or streams._copy_binding is None
            or streams._copy_binding.scope != scope
            or streams._copy_binding.io_nonce != streams._nonce
        ):
            raise GitObjectReadError('ORIGINAL_BATCH_STDIO_REQUIRED')
        if (
            not _positive(max_requests)
            or not _positive(max_output_bytes)
            or type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or not callable(cancelled)
        ):
            raise GitObjectReadError('ORIGINAL_BATCH_BOUNDARY_REQUIRED')
        self._thread = get_ident()
        self._streams = streams
        self._binding = streams._copy_binding
        self._format = format
        self._deadline, self._cancelled = deadline, cancelled
        self._request_limit, self._wire_limit = max_requests, max_output_bytes
        self._requests = self._wire_bytes = 0
        self._prefix = bytearray()
        self._active = False
        self._failed = False
        self._done = False
        self._closed = False
        self._kernel = _read_api(streams._kernel)
        self._checkpoint(deadline)
        self._input = OriginalProcessInput(streams)
        self._lease = streams.output_endpoints()
        self._handles = dict(zip(STREAMS, self._lease.__enter__(), strict=True))

    def _check_thread(self):
        if get_ident() != self._thread:
            raise GitObjectReadError('ORIGINAL_BATCH_OWNER_THREAD_DIFFERS')

    def _require_idle(self):
        self._check_thread()
        if self._active or self._failed or self._done or self._closed:
            raise GitObjectReadError('ORIGINAL_BATCH_STREAM_NOT_AVAILABLE')

    def _checkpoint(self, deadline):
        if (
            self._streams._copy_binding != self._binding
            or self._streams._scope != self._binding.scope
            or self._streams._nonce != self._binding.io_nonce
        ):
            raise GitObjectReadError('ORIGINAL_BATCH_STDIO_DIFFERS')
        if self._cancelled() or monotonic() >= deadline:
            raise LaunchOutcomeUnknown('ORIGINAL_BATCH_CANCELLED_OR_TIMED_OUT')

    def _check_stderr(self):
        data = read_available_pipe(self._kernel, self._handles['STDERR'], 1)
        if data:
            raise GitObjectReadError('ORIGINAL_BATCH_STDERR_NOT_EMPTY')
        return data is None

    def _stdout(self, limit, deadline):
        while True:
            self._checkpoint(deadline)
            self._check_stderr()
            remaining = self._wire_limit - self._wire_bytes
            data = read_available_pipe(
                self._kernel, self._handles['STDOUT'], min(limit, remaining + 1)
            )
            if data is None:
                raise GitObjectReadError('ORIGINAL_BATCH_TRUNCATED')
            if data:
                if len(data) > remaining:
                    raise GitObjectReadError('ORIGINAL_BATCH_OUTPUT_LIMIT_EXCEEDED')
                self._wire_bytes += len(data)
                return data
            sleep(0.005)

    def _header(self, deadline):
        while True:
            newline = self._prefix.find(b'\n')
            if newline >= 0:
                header = bytes(self._prefix[:newline])
                del self._prefix[: newline + 1]
                return header
            capacity = MAX_HEADER_BYTES - len(self._prefix)
            if capacity <= 0:
                raise GitObjectReadError('ORIGINAL_BATCH_HEADER_TOO_LONG')
            self._prefix.extend(self._stdout(capacity, deadline))

    def _body(self, size, deadline):
        take = min(size + 1, len(self._prefix))
        data = self._prefix[:take]
        del self._prefix[:take]
        while len(data) <= size:
            data.extend(self._stdout(size + 1 - len(data), deadline))
        if data[-1] != 10:
            raise GitObjectReadError('ORIGINAL_BATCH_TRAILER_DIFFERS')
        return bytes(data[:-1])

    def read(self, request):
        self._require_idle()
        self._active = True
        try:
            if (
                type(request) is not ObjectReadRequest
                or request.format != self._format
                or not _positive(request.max_output_bytes)
                or type(request.remaining_seconds) not in (int, float)
                or not math.isfinite(request.remaining_seconds)
                or request.remaining_seconds <= 0
            ):
                raise GitObjectReadError('ORIGINAL_BATCH_REQUEST_INVALID')
            _binding(request.format, request.object_type, request.object_oid)
            if self._requests >= self._request_limit:
                raise GitObjectReadError('ORIGINAL_BATCH_REQUEST_LIMIT_EXCEEDED')
            deadline = min(self._deadline, monotonic() + request.remaining_seconds)
            self._checkpoint(deadline)
            self._check_stderr()
            self._requests += 1
            self._input.write(request.object_oid.encode('ascii') + b'\n')
            size = _batch_size(self._header(deadline), request)
            if size + 1 > self._wire_limit - self._wire_bytes + len(self._prefix):
                raise GitObjectReadError('ORIGINAL_BATCH_OUTPUT_LIMIT_EXCEEDED')
            raw = self._body(size, deadline)
            value = verify_git_object(
                raw,
                format=request.format,
                object_type=request.object_type,
                oid=request.object_oid,
                max_output_bytes=request.max_output_bytes,
            )
            self._checkpoint(deadline)
            self._check_stderr()
            return value
        except BaseException:
            self._failed = True
            raise
        finally:
            self._active = False

    def finish(self):
        """Verify no trailing bytes and both EOFs before using collected evidence."""
        self._require_idle()
        self._active = True
        try:
            self._checkpoint(self._deadline)
            if self._prefix:
                raise GitObjectReadError('ORIGINAL_BATCH_UNSOLICITED_OUTPUT')
            self._streams.close_input()
            while True:
                self._checkpoint(self._deadline)
                stderr_eof = self._check_stderr()
                stdout = read_available_pipe(self._kernel, self._handles['STDOUT'], 1)
                if stdout:
                    raise GitObjectReadError('ORIGINAL_BATCH_UNSOLICITED_OUTPUT')
                if stdout is None and stderr_eof:
                    self._done = True
                    return BatchCompletion(
                        self._binding.scope,
                        self._binding.io_nonce,
                        self._requests,
                        self._wire_bytes,
                    )
                sleep(0.005)
        except BaseException:
            self._failed = True
            raise
        finally:
            self._active = False

    def close(self):
        self._check_thread()
        if self._active:
            raise GitObjectReadError('ORIGINAL_BATCH_STREAM_IN_USE')
        if not self._closed:
            self._lease.__exit__(None, None, None)
            self._closed = True
