"""One original staged reference transaction on controlled Git STDIO."""

import math
from dataclasses import dataclass
from threading import get_ident
from time import monotonic, sleep

from .git_ref_protocol import (
    RefAckDecoder,
    RefPrepareInput,
    RefProtocolError,
    abort_bytes,
    commit_bytes,
)
from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope
from .windows_pipe_capture import STREAMS, _read_api, read_available_pipe
from .windows_process_input import OriginalProcessInput
from .windows_stdio import BackendStandardIO


@dataclass(frozen=True)
class RefProcessBinding:
    scope: LaunchScope
    io_nonce: str
    intent_sha256: str


@dataclass(frozen=True)
class RefCommitPermit:
    """An internal capability returned only after the original durable send gate."""

    binding: RefProcessBinding


class _RefTransaction:
    _kind = None

    def __init__(self, streams, intent, *, scope, max_output_bytes, deadline, cancelled):
        if (
            type(streams) is not BackendStandardIO
            or type(scope) is not LaunchScope
            or streams._scope != scope
            or streams._copy_binding is None
            or streams._copy_binding.scope != scope
            or streams._copy_binding.io_nonce != streams._nonce
            or type(intent) is not RefPrepareInput
            or intent.kind != self._kind
            or type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or not callable(cancelled)
        ):
            raise RefProtocolError('ORIGINAL_GIT_REF_TRANSACTION_REQUIRED')
        self._thread = get_ident()
        self._streams, self._intent = streams, intent
        self._deadline, self._cancelled = deadline, cancelled
        self._stdio = streams._copy_binding
        self.binding = RefProcessBinding(scope, self._stdio.io_nonce, intent.input_sha256)
        self._decoder = RefAckDecoder(max_output_bytes=max_output_bytes)
        self._phase = 'NEW'
        self._closed = False
        self._checkpoint()
        self._kernel = _read_api(streams._kernel)
        self._input = OriginalProcessInput(streams)
        self._lease = streams.output_endpoints()
        self._handles = dict(zip(STREAMS, self._lease.__enter__(), strict=True))

    def _check_thread(self):
        if get_ident() != self._thread:
            raise RefProtocolError('ORIGINAL_GIT_REF_TRANSACTION_THREAD_DIFFERS')

    def _require(self, phase):
        self._check_thread()
        if self._closed or self._phase != phase:
            raise LaunchOutcomeUnknown('ORIGINAL_GIT_REF_TRANSACTION_PHASE_DIFFERS')
        self._checkpoint()

    def _checkpoint(self):
        if self._streams._copy_binding != self._stdio:
            raise LaunchOutcomeUnknown('ORIGINAL_GIT_REF_TRANSACTION_STDIO_DIFFERS')
        if self._cancelled() or monotonic() >= self._deadline:
            raise LaunchOutcomeUnknown('ORIGINAL_GIT_REF_TRANSACTION_CANCELLED_OR_TIMED_OUT')

    def _stderr(self):
        data = read_available_pipe(self._kernel, self._handles['STDERR'], 1)
        if data:
            raise RefProtocolError('ORIGINAL_GIT_REF_TRANSACTION_STDERR_NOT_EMPTY')
        return data is None

    def _wait_for(self, expected):
        while True:
            self._checkpoint()
            self._stderr()
            data = read_available_pipe(self._kernel, self._handles['STDOUT'], 512)
            if data is None:
                raise RefProtocolError('ORIGINAL_GIT_REF_TRANSACTION_ACK_TRUNCATED')
            if data:
                self._decoder.feed(data)
                phases = self._decoder.phases
                if phases == expected and not self._decoder._pending:
                    return
                if phases != expected[: len(phases)] or phases == expected:
                    raise RefProtocolError('ORIGINAL_GIT_REF_TRANSACTION_ACK_DIFFERS')
            sleep(0.005)

    def prepare(self):
        self._require('NEW')
        self._phase = 'UNCERTAIN'
        self._input.write(self._intent.prepare_bytes())
        self._wait_for(('START', 'PREPARE'))
        self._phase = 'PREPARED'
        return self.binding

    def abort(self):
        self._require('PREPARED')
        self._phase = 'UNCERTAIN'
        self._input.write(abort_bytes())
        self._finish('ABORT')
        self._phase = 'ABORTED'

    def _prepare_commit(self):
        self._require('PREPARED')
        self._phase = 'UNCERTAIN'

    def _check_permit(self, permit):
        if type(permit) is not RefCommitPermit or permit.binding != self.binding:
            raise LaunchOutcomeUnknown('ORIGINAL_GIT_COMMIT_PERMIT_REQUIRED')
        self._checkpoint()

    def _send_commit(self, permit):
        self._check_permit(permit)
        self._input.write(commit_bytes())

    def _confirm_commit(self):
        self._finish('COMMIT')
        self._phase = 'COMMITTED'

    def _finish(self, phase):
        self._wait_for(('START', 'PREPARE', phase))
        self._streams.close_input()
        while True:
            self._checkpoint()
            stderr_eof = self._stderr()
            output = read_available_pipe(self._kernel, self._handles['STDOUT'], 1)
            if output:
                raise RefProtocolError('ORIGINAL_GIT_REF_TRANSACTION_TRAILING_OUTPUT')
            if output is None and stderr_eof:
                self._decoder.finish(expected_terminal=phase)
                return
            sleep(0.005)

    def close(self):
        self._check_thread()
        if not self._closed:
            self._lease.__exit__(None, None, None)
            self._closed = True


class BaselineRefTransaction(_RefTransaction):
    _kind = 'BASELINE_CREATE'

    def commit(self, persist_dispatch):
        if not callable(persist_dispatch):
            raise TypeError('Original durable dispatch gate required')
        self._prepare_commit()
        self._send_commit(persist_dispatch(self.binding))
        self._confirm_commit()


class DeliveryRefTransaction(_RefTransaction):
    _kind = 'DELIVERY_UPDATE'

    def commit(self, dispatch_gate):
        if not callable(dispatch_gate):
            raise TypeError('Original delivery dispatch fence required')
        self._require('PREPARED')
        # Only the single bounded nonblocking pipe write is inside the stop fence.
        # Never wait for Git output while a database writer is held.
        with dispatch_gate(self.binding) as permit:
            self._check_permit(permit)
            self._phase = 'UNCERTAIN'
            self._input.write(commit_bytes())
        self._confirm_commit()
