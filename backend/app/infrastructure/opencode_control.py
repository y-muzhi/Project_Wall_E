"""Ephemeral Basic credential for one original OpenCode loopback instance."""

import hashlib
import re
from base64 import b64encode
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
from secrets import token_hex
from threading import RLock
from time import monotonic

from backend.app.shared.validation import strict_json_object

from .opencode_binary import VERSION
from .opencode_events import OpenCodeEvents
from .opencode_model_credential import OpenCodeModelCredential
from .opencode_task_launch import TaskExecutionError, TaskExecutionPlan
from .runtime_launch_journal import LaunchScope, _bytes
from .windows_process import NativeProcessIdentity, ObservedProcess, ProcessObservationError
from .windows_task_endpoints import verify_task_control_connection


class OpenCodeControlCredential:
    def __init__(self, scope, plan, *, reference, password):
        if (
            type(scope) is not LaunchScope
            or scope.step_no != 4
            or type(plan) is not TaskExecutionPlan
            or type(reference) is not str
            or not re.fullmatch('[0-9a-f]{32}', reference)
            or type(password) is not str
            or not re.fullmatch('[0-9a-f]{64}', password)
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_INVALID')
        self._scope, self._endpoint = scope, plan.network['control'][0]
        self._model_endpoint = plan.network['model'][0]
        self.reference = reference
        self._password = password
        self._gate = RLock()

    @classmethod
    def issue(cls, scope, plan):
        return cls(scope, plan, reference=token_hex(16), password=token_hex(32))

    @classmethod
    def from_pipe(cls, scope, plan, value):
        if type(value) is not dict or set(value) != {'reference', 'password'}:
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_INVALID')
        return cls(scope, plan, reference=value['reference'], password=value['password'])

    def _verify(self, scope, plan):
        if (
            self._password is None
            or scope != self._scope
            or plan.network['control'][0] != self._endpoint
            or plan.network['model'][0] != self._model_endpoint
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_UNVERIFIED')

    def pipe_payload(self, scope, plan):
        with self._gate:
            self._verify(scope, plan)
            return {'reference': self.reference, 'password': self._password}

    def facts(self, scope, plan):
        with self._gate:
            self._verify(scope, plan)
            commitment = hashlib.sha256(
                _bytes(
                    [
                        'opencode-control-v1',
                        scope.key,
                        self._endpoint,
                        self._model_endpoint,
                        self.reference,
                        self._password,
                    ]
                )
            ).hexdigest()
            return {'credential_ref': self.reference, 'credential_sha256': commitment}

    def model_credential(self, scope, plan):
        with self._gate:
            self._verify(scope, plan)
            return OpenCodeModelCredential.derive(scope, self._model_endpoint, self._password)

    def launch_variables(self, scope, plan):
        with self._gate:
            self._verify(scope, plan)
            return {
                'OPENCODE_SERVER_USERNAME': 'walle-' + self.reference,
                'OPENCODE_SERVER_PASSWORD': self._password,
                **self.model_credential(scope, plan).environment(),
            }

    def close(self):
        with self._gate:
            self._password = None

    def _open_verified(
        self, process, expected, remaining, *, method, target, body, authenticated, accept
    ):
        if self._password is None:
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CREDENTIAL_UNVERIFIED')
        before = process.observe()
        if before.identity != expected or before.state != 'RUNNING':
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_OWNER_UNVERIFIED')
        connection = HTTPConnection(*self._endpoint, timeout=remaining())
        try:
            connection.connect()
            connection.auto_open = 0
            verify_task_control_connection(connection.sock, self._endpoint, expected.pid)
            connection.sock.settimeout(remaining())
            if process.observe() != before:
                raise TaskExecutionError('ORIGINAL_TASK_CONTROL_OWNER_UNVERIFIED')
            headers = {'Connection': 'close', 'Accept': accept}
            if authenticated:
                token = b64encode(
                    ('walle-' + self.reference + ':' + self._password).encode('ascii')
                ).decode('ascii')
                headers['Authorization'] = 'Basic ' + token
            if body is not None:
                headers['Content-Type'] = 'application/json'
            connection.request(method, target, body=body, headers=headers)
        except BaseException:
            connection.close()
            raise
        return connection, before

    @contextmanager
    def _event_stream(self, process, expected, checkpoint, *, target, timeout_ms, ready_timeout_ms):
        if (
            type(process) is not ObservedProcess
            or type(expected) is not NativeProcessIdentity
            or type(timeout_ms) is not int
            or not 1 <= ready_timeout_ms <= timeout_ms <= 30000
        ):
            raise TaskExecutionError('ORIGINAL_TASK_EVENT_OWNER_REQUIRED')
        deadline = monotonic() + timeout_ms / 1000
        read_deadline = monotonic() + ready_timeout_ms / 1000
        connection = None
        response = None

        def remaining():
            checkpoint()
            seconds = min(deadline, read_deadline) - monotonic()
            if seconds <= 0:
                raise TaskExecutionError('ORIGINAL_TASK_EVENT_DEADLINE')
            return seconds

        try:
            with self._gate, process._gate:
                connection, before = self._open_verified(
                    process,
                    expected,
                    remaining,
                    method='GET',
                    target=target,
                    body=None,
                    authenticated=True,
                    accept='text/event-stream',
                )
                channel = connection.sock
            response = connection.getresponse()
            if response.status != 200 or response.headers.get_content_type() != 'text/event-stream':
                raise TaskExecutionError('ORIGINAL_TASK_EVENT_STREAM_UNVERIFIED')

            def receive():
                with self._gate, process._gate:
                    if self._password is None or process.observe() != before:
                        raise TaskExecutionError('ORIGINAL_TASK_EVENT_OWNER_UNVERIFIED')
                channel.settimeout(remaining())
                result = response.read1(4096)
                remaining()
                return result

            events = OpenCodeEvents(receive)
            if events.next()['type'] != 'server.connected':
                raise TaskExecutionError('ORIGINAL_TASK_EVENT_READY_UNVERIFIED')
            read_deadline = deadline
            yield events
        except (HTTPException, OSError, ProcessObservationError, ValueError):
            raise TaskExecutionError('ORIGINAL_TASK_EVENT_STREAM_UNVERIFIED') from None
        finally:
            if response is not None:
                response.close()
            if connection is not None:
                connection.close()

    def _request(
        self,
        process,
        expected,
        checkpoint,
        *,
        method,
        target,
        timeout_ms,
        body=None,
        authenticated=True,
        max_response_bytes=4096,
    ):
        if (
            type(process) is not ObservedProcess
            or type(expected) is not NativeProcessIdentity
            or type(timeout_ms) is not int
            or not 1 <= timeout_ms <= 30000
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_OWNER_REQUIRED')
        deadline = monotonic() + timeout_ms / 1000

        def remaining():
            checkpoint()
            duration = deadline - monotonic()
            if duration <= 0:
                raise TaskExecutionError('ORIGINAL_TASK_CONTROL_DEADLINE')
            return duration

        with self._gate, process._gate:
            connection = None
            try:
                connection, before = self._open_verified(
                    process,
                    expected,
                    remaining,
                    method=method,
                    target=target,
                    body=body,
                    authenticated=authenticated,
                    accept='application/json',
                )
                with connection.getresponse() as response:
                    status = response.status
                    challenges = response.headers.get_all('WWW-Authenticate', [])
                    raw = response.read(max_response_bytes + 1)
                if len(raw) > max_response_bytes:
                    raise TaskExecutionError('ORIGINAL_TASK_CONTROL_RESPONSE_TOO_LARGE')
                remaining()
                if process.observe() != before:
                    raise TaskExecutionError('ORIGINAL_TASK_CONTROL_OWNER_UNVERIFIED')
                return status, raw, challenges
            except (HTTPException, OSError, ProcessObservationError, ValueError):
                raise TaskExecutionError('ORIGINAL_TASK_CONTROL_RESULT_UNVERIFIED') from None
            finally:
                if connection is not None:
                    connection.close()

    def probe_health(self, process, expected, checkpoint, *, timeout_ms):
        status, raw, _ = self._request(
            process,
            expected,
            checkpoint,
            method='GET',
            target='/global/health',
            timeout_ms=timeout_ms,
        )
        try:
            health = strict_json_object(raw) if status == 200 else {}
        except ValueError as error:
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_HEALTH_UNVERIFIED') from error
        if (
            set(health) != {'healthy', 'version'}
            or health['healthy'] is not True
            or health['version'] != VERSION
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_HEALTH_UNVERIFIED')
        return VERSION

    def verify_basic_challenge(self, process, expected, checkpoint, *, timeout_ms):
        status, _, challenges = self._request(
            process,
            expected,
            checkpoint,
            method='GET',
            target='/global/health',
            timeout_ms=timeout_ms,
            authenticated=False,
        )
        if (
            status != 401
            or len(challenges) != 1
            or re.match(r'^Basic(?:[ ]|$)', challenges[0], re.IGNORECASE) is None
        ):
            raise TaskExecutionError('ORIGINAL_TASK_CONTROL_BASIC_CHALLENGE_REQUIRED')
