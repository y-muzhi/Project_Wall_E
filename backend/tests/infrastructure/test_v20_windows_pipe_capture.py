"""Original bounded backend pipes: real bytes/EOF, exclusivity and uncertain IO."""

import ctypes
import hashlib
from ctypes import wintypes
from dataclasses import FrozenInstanceError, asdict
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.code_tasks.task_output_capture import TaskOutputCapture
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchFence, LaunchScope
from backend.app.infrastructure.windows_pipe_capture import (
    BoundedOutputCapture,
    OutputCaptureError,
    READ_CHUNK,
)
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_stdio import BackendStandardIO, StdioBoundaryError
from backend.app.shared.validation import strict_json_object
from backend.tests.infrastructure.test_v20_windows_stdio import scope


def write(streams, name, raw):
    kernel = streams._kernel
    kernel.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel.WriteFile.restype = wintypes.BOOL
    data = ctypes.create_string_buffer(raw)
    written = wintypes.DWORD()
    assert kernel.WriteFile(
        streams._ends[name + '_WRITE'], data, len(raw), ctypes.byref(written), None
    )
    assert written.value == len(raw)


def finish_writers(streams):
    streams._close(('STDOUT_WRITE', 'STDERR_WRITE'))


def dword(pointer, value):
    ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = value


def test_real_binary_outputs_idle_is_not_eof_and_eof_does_not_require_process_claim():
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=100) as capture,
    ):
        first = capture.poll()
        assert not first.complete and not first.stdout_eof and not first.stderr_eof
        with pytest.raises(OutputCaptureError, match='INCOMPLETE'):
            capture.require_complete()
        write(streams, 'STDOUT', b'PRIVATE\0\xff\r\n')
        write(streams, 'STDERR', b'\xf0\x9f\x98\x80')
        progress = capture.poll()
        assert progress.stdout_bytes == 11 and progress.stderr_bytes == 4
        old = capture.snapshot()
        assert not old.progress.complete and 'PRIVATE' not in repr(old)
        finish_writers(streams)
        assert capture.poll().complete
        result = capture.require_complete()
        assert result.stdout == b'PRIVATE\0\xff\r\n' and result.stderr == b'\xf0\x9f\x98\x80'
        assert result.progress.io_nonce == streams._nonce and result.progress.scope == scope()
        assert not old.progress.complete
        with pytest.raises(FrozenInstanceError):
            result.stdout = b'changed'


@pytest.mark.parametrize('invalid', [None, False, 0, -1, '100', 1.5, 9007199254740992])
def test_invalid_limit_does_not_claim_original_pipes(invalid):
    with BackendStandardIO(scope()) as streams:
        with pytest.raises(OutputCaptureError, match='LIMIT_INVALID'):
            BoundedOutputCapture(streams, scope=scope(), max_output_bytes=invalid)
        assert not streams._output_claimed


def test_wrong_owner_scope_or_foreign_resource_cannot_claim_pipes():
    with BackendStandardIO(scope()) as streams:
        with pytest.raises(OutputCaptureError, match='SCOPE_DIFFERS'):
            BoundedOutputCapture(streams, scope=scope(2), max_output_bytes=100)
        assert not streams._output_claimed
    for value in (None, {}, object()):
        with pytest.raises(OutputCaptureError, match='ORIGINAL_BACKEND'):
            BoundedOutputCapture(value, scope=scope(), max_output_bytes=100)


def test_one_reader_for_lifetime_and_active_lease_prohibits_raw_borrow_or_close():
    streams = BackendStandardIO(scope())
    try:
        with streams.parent_endpoint('STDOUT'):
            with pytest.raises(StdioBoundaryError, match='ALREADY_CLAIMED'):
                BoundedOutputCapture(streams, scope=scope(), max_output_bytes=100)
        capture = BoundedOutputCapture(streams, scope=scope(), max_output_bytes=100)
        try:
            for name in ('STDOUT', 'STDERR'):
                with pytest.raises(StdioBoundaryError, match='ALREADY_CLAIMED'):
                    with streams.parent_endpoint(name):
                        pytest.fail('Another reader')
            with streams.parent_endpoint('STDIN') as handle:
                assert handle
            with pytest.raises(StdioBoundaryError, match='IN_USE'):
                streams.close()
        finally:
            capture.close()
        capture.close()
        with pytest.raises(OutputCaptureError, match='CLOSED'):
            capture.poll()
        with pytest.raises(StdioBoundaryError, match='ALREADY_CLAIMED'):
            BoundedOutputCapture(streams, scope=scope(), max_output_bytes=100)
        with pytest.raises(StdioBoundaryError, match='ALREADY_CLAIMED'):
            with streams.parent_endpoint('STDOUT'):
                pytest.fail('Cannot replay a consumed stream')
    finally:
        streams.close()


def test_combined_limit_keeps_only_prefix_and_never_calls_it_complete():
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=5) as capture,
    ):
        write(streams, 'STDOUT', b'abc')
        write(streams, 'STDERR', b'def')
        progress = capture.poll()
        assert progress.limit_exceeded and not progress.complete
        result = capture.snapshot()
        assert result.stdout + result.stderr == b'abcde'
        assert result.progress.stdout_bytes + result.progress.stderr_bytes == 5
        finish_writers(streams)
        with patch.object(capture, '_kernel', SimpleNamespace()):
            assert capture.poll() == progress
        with pytest.raises(OutputCaptureError, match='INCOMPLETE'):
            capture.require_complete()


def test_exact_capacity_requires_real_eof_and_one_late_byte_proves_overflow():
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=3) as capture,
    ):
        write(streams, 'STDOUT', b'abc')
        assert not capture.poll().limit_exceeded
        write(streams, 'STDOUT', b'x')
        assert capture.poll().limit_exceeded
        assert capture.snapshot().stdout == b'abc'
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=3) as capture,
    ):
        write(streams, 'STDOUT', b'abc')
        finish_writers(streams)
        capture.poll()
        assert capture.poll().complete and not capture.progress().limit_exceeded


@pytest.mark.parametrize('failure', ['peek', 'read', 'zero', 'too-many', 'broken-read'])
def test_native_fault_never_becomes_empty_success_and_preserves_original_owner(failure):
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=100) as capture,
    ):
        calls = []

        def peek(handle, buffer, size, read, available, left):
            calls.append('peek')
            if failure == 'peek':
                ctypes.set_last_error(232)
                return False
            dword(available, 3)
            return True

        def read(handle, buffer, size, received, overlapped):
            calls.append('read')
            if failure in ('read', 'broken-read'):
                ctypes.set_last_error(109 if failure == 'broken-read' else 5)
                return False
            dword(received, 0 if failure == 'zero' else size + 1)
            return True

        capture._kernel = SimpleNamespace(PeekNamedPipe=peek, ReadFile=read)
        with pytest.raises(OutputCaptureError) as error:
            capture.poll()
        assert error.value.retained_owner is capture
        assert capture.progress().failure_reason and not capture.progress().complete
        assert not capture.progress().stdout_eof
        before = len(calls)
        with pytest.raises(OutputCaptureError):
            capture.poll()
        assert len(calls) == before
        assert capture.snapshot().stdout == b''


def test_poll_work_is_bounded_and_both_streams_get_turns_without_waiting():
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=4 * READ_CHUNK) as capture,
    ):
        reads = []

        def peek(handle, buffer, size, read, available, left):
            dword(available, 10000000)
            return True

        def read(handle, buffer, size, received, overlapped):
            reads.append((handle, size))
            ctypes.memset(buffer, 65, size)
            dword(received, size)
            return True

        capture._kernel = SimpleNamespace(PeekNamedPipe=peek, ReadFile=read)
        first = capture.poll()
        assert first.stdout_bytes == first.stderr_bytes == READ_CHUNK
        assert len(reads) == 2 and sum(size for _, size in reads) == 2 * READ_CHUNK
        capture.poll()
        assert reads[0][0] == reads[3][0] and reads[1][0] == reads[2][0]


def test_original_scope_or_nonce_change_cannot_rebind_output():
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=100) as capture,
    ):
        streams._nonce = 'changed'
        with pytest.raises(OutputCaptureError, match='BINDING_DIFFERS'):
            capture.poll()
        assert not capture.progress().complete


@pytest.mark.parametrize('interrupt', [KeyboardInterrupt, MemoryError, OSError])
def test_interrupted_native_read_cannot_resume_with_a_missing_chunk(interrupt):
    with (
        BackendStandardIO(scope()) as streams,
        BoundedOutputCapture(streams, scope=scope(), max_output_bytes=100) as capture,
    ):
        calls = []

        def peek(handle, buffer, size, read, available, left):
            dword(available, 3)
            return True

        def read(*arguments):
            calls.append('read may have consumed data')
            raise interrupt()

        capture._kernel = SimpleNamespace(PeekNamedPipe=peek, ReadFile=read)
        with pytest.raises(interrupt) as error:
            capture.poll()
        assert error.value.retained_owner is capture
        assert capture.progress().failure_reason == 'OUTPUT_CAPTURE_INTERRUPTED'
        assert not capture.progress().complete
        with pytest.raises(OutputCaptureError, match='INTERRUPTED'):
            capture.poll()
        assert len(calls) == 1


@pytest.mark.parametrize('limit,status', [(100, 'COMPLETE'), (4, 'TRUNCATED')])
def test_original_task_output_retains_only_safe_evidence_and_drains_after_limit(
    tmp_path, limit, status
):
    original = LaunchScope('a' * 64, 1, 4, 'task-output-fixture')
    with (
        PrivatePackageGuard(create_private_package(tmp_path / 'diagnostics')) as package,
        BackendStandardIO(original) as streams,
    ):
        capture = TaskOutputCapture(streams, original, package, limit)
        fence = asdict(
            LaunchFence(
                1, original, 'b' * 64, 'NONE', 'NONE', None, False, 1, '2026-11-09T08:00:00.000Z'
            )
        )
        with pytest.raises(TaskExecutionError, match='OUTPUT_STOP_REQUIRED'):
            capture.finish_after_stop({'process_state': 'EXITED', 'fence': fence}, timeout_ms=1000)
        write(streams, 'STDOUT', b'private-output')
        write(streams, 'STDERR', b'private-error')
        finish_writers(streams)
        fence['stop_closed'] = True
        stop = {'process_state': 'EXITED', 'fence': fence}
        evidence = capture.finish_after_stop(stop, timeout_ms=1000)
        assert evidence.status == status
        assert capture.finish_after_stop(stop, timeout_ms=1000) == evidence
        raw = (package.path / (original.key + '.task-native-output.json')).read_bytes()
        assert b'private-' not in raw
        assert evidence.reference == hashlib.sha256(raw).hexdigest()
        fact = strict_json_object(raw)
        assert fact['stdout_eof'] is True and fact['stderr_eof'] is True
        assert fact['stdout_bytes'] + fact['stderr_bytes'] == (
            27 if status == 'COMPLETE' else limit
        )
