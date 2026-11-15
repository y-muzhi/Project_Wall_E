"""Drain the original TASK root's two diagnostic pipes before they can block."""

import hashlib
from dataclasses import dataclass
from threading import Event, Thread

from backend.app.infrastructure.guard_task_files import _publish_original, _read_original
from backend.app.infrastructure.guard_task_launch_protocol import task_launch_fence
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import LaunchScope, _bytes
from backend.app.infrastructure.windows_pipe_capture import BoundedOutputCapture, OutputCaptureError

_LIMIT = 4096


@dataclass(frozen=True)
class TaskOutputEvidence:
    status: str
    reference: str


class TaskOutputCapture:
    """One pump per original STDIO. Its evidence never asserts Job/Task completion."""

    def __init__(self, streams, scope, package, max_output_bytes):
        if type(scope) is not LaunchScope or scope.step_no != 4:
            raise TaskExecutionError('ORIGINAL_TASK_OUTPUT_SCOPE_REQUIRED')
        self._scope, self._package, self._identity = scope, package, package.verify()
        self._capture = BoundedOutputCapture(
            streams,
            scope=scope,
            max_output_bytes=max_output_bytes,
            drain_after_limit=True,
        )
        self._name = scope.key + '.task-native-output.json'
        self._stop, self._finished = Event(), Event()
        self._evidence = None
        self._failure = None
        self._thread = Thread(target=self._run, name='walle-task-output', daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self._capture.close()
            raise

    def _run(self):
        try:
            while not self._stop.is_set():
                progress = self._capture.poll()
                if progress.stdout_eof and progress.stderr_eof:
                    break
                self._stop.wait(0.01)
        except OutputCaptureError as error:
            self._failure = error.reason
        except Exception:
            self._failure = 'OUTPUT_CAPTURE_INTERRUPTED'
        finally:
            self._finished.set()

    def finish_after_stop(self, stopped, *, timeout_ms):
        if (
            type(timeout_ms) is not int
            or not 1 <= timeout_ms <= 30000
            or type(stopped) is not dict
            or stopped.get('process_state') not in ('NOT_CREATED', 'EXITED')
            or not task_launch_fence(stopped['fence'], self._scope).stop_closed
        ):
            raise TaskExecutionError('ORIGINAL_TASK_OUTPUT_STOP_REQUIRED')
        if self._evidence is not None:
            return self._evidence
        if not self._finished.wait(timeout_ms / 1000):
            self._stop.set()
        self._thread.join(1)
        if self._thread.is_alive():
            error = TaskExecutionError('ORIGINAL_TASK_OUTPUT_READER_RETAINED')
            error.retained_owner = self
            raise error
        capture = self._capture.snapshot()
        self._capture.close()
        progress = capture.progress
        if self._package.verify() != self._identity:
            raise TaskExecutionError('ORIGINAL_TASK_OUTPUT_PACKAGE_DIFFERS')
        if self._failure is not None or not (progress.stdout_eof and progress.stderr_eof):
            status = 'INCOMPLETE'
        elif progress.limit_exceeded:
            status = 'TRUNCATED'
        else:
            status = 'COMPLETE'
        raw = _bytes(
            {
                'schema_version': 1,
                'scope': self._scope.key,
                'status': status,
                'stdout_bytes': progress.stdout_bytes,
                'stderr_bytes': progress.stderr_bytes,
                'stdout_sha256': hashlib.sha256(capture.stdout).hexdigest(),
                'stderr_sha256': hashlib.sha256(capture.stderr).hexdigest(),
                'stdout_eof': progress.stdout_eof,
                'stderr_eof': progress.stderr_eof,
                'limit_exceeded': progress.limit_exceeded,
                'reason': self._failure
                or ('OUTPUT_EOF_UNVERIFIED' if status == 'INCOMPLETE' else None),
            }
        )
        if _read_original(self._package, self._name, _LIMIT) is None:
            _publish_original(self._package, self._name, raw, _LIMIT)
        if _read_original(self._package, self._name, _LIMIT) != raw:
            raise TaskExecutionError('ORIGINAL_TASK_OUTPUT_EVIDENCE_DIFFERS')
        self._evidence = TaskOutputEvidence(status, hashlib.sha256(raw).hexdigest())
        return self._evidence
