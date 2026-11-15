"""Dedicated HTTP/1.1 listener for the original local OpenCode model binding."""

import re
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import BoundedSemaphore, Event, RLock, Thread
from time import monotonic

from backend.app.infrastructure.opencode_model_credential import OpenCodeModelCredential
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.shared.validation import strict_integer, strict_json_object

from .coding_model_request import REQUEST_BYTES, CodingModelProtocolError
from .task_model_ingress import (
    ModelWindow,
    TaskModelIngress,
    read_original_open_window,
    read_original_window_state,
)

_MAX_HEADER = 16 * 1024
_MAX_CONNECTIONS = 8
_HEADER_NAME = re.compile(r"[!#$%&'*+.\^_`|~0-9A-Za-z-]+")
_LENGTH = re.compile(r'[1-9][0-9]{0,6}')
_PUBLIC_MESSAGE = 'WALL-E execution is waiting for a confirmed control action.'
_ERRORS = {
    'protocol': (400, 'Bad Request', 'WALLE_PROTOCOL'),
    'source': (403, 'Forbidden', 'WALLE_SOURCE'),
    'budget': (402, 'Payment Required', 'WALLE_BUDGET'),
    'hold': (409, 'Conflict', 'WALLE_HOLD'),
}


class CodingGatewayError(RuntimeError):
    def __init__(self, kind):
        if kind not in _ERRORS:
            raise ValueError('Unknown Coding gateway error')
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True)
class _Head:
    method: str
    target: str
    version: str
    headers: tuple[tuple[str, str], ...]
    body_length: int


class _LocalHttp:
    def __init__(self, connection, endpoint, *, cancelled, timeout):
        self.connection = connection
        self._endpoint = endpoint
        self.cancelled = cancelled
        self.deadline = monotonic() + timeout
        self.started = False

    def _receive(self, limit):
        remaining = self.deadline - monotonic()
        if self.cancelled() or remaining <= 0:
            raise CodingGatewayError('hold')
        self.connection.settimeout(remaining)
        part = self.connection.recv(limit)
        if not part:
            raise CodingGatewayError('protocol')
        return part

    def head(self):
        received = bytearray()
        while b'\r\n\r\n' not in received:
            if len(received) >= _MAX_HEADER:
                raise CodingGatewayError('protocol')
            received.extend(self._receive(min(4096, _MAX_HEADER - len(received))))
        head, _, prefix = bytes(received).partition(b'\r\n\r\n')
        try:
            lines = head.decode('ascii', errors='strict').split('\r\n')
            method, target, version = lines[0].split(' ')
        except (UnicodeError, ValueError):
            raise CodingGatewayError('protocol') from None
        if (
            method != 'POST'
            or version != 'HTTP/1.1'
            or len(lines) > 65
            or not re.fullmatch(r'/internal/code-model/[0-9a-f]{32}/v1/chat/completions', target)
        ):
            raise CodingGatewayError('protocol')
        headers = []
        framing = {}
        for line in lines[1:]:
            name, colon, value = line.partition(':')
            if (
                not colon
                or not _HEADER_NAME.fullmatch(name)
                or any((ord(char) < 32 and char != '\t') or ord(char) == 127 for char in value)
            ):
                raise CodingGatewayError('protocol')
            name, value = name.lower(), value.strip(' \t')
            if name in ('transfer-encoding', 'expect', 'upgrade', 'proxy-connection'):
                raise CodingGatewayError('protocol')
            if name in ('host', 'content-length'):
                if name in framing:
                    raise CodingGatewayError('protocol')
                framing[name] = value
            headers.append((name, value))
        address, port = self._endpoint
        length = framing.get('content-length', '')
        if framing.get('host') != f'{address}:{port}' or not _LENGTH.fullmatch(length):
            raise CodingGatewayError('protocol')
        length = int(length)
        if length > REQUEST_BYTES or len(prefix) > length:
            raise CodingGatewayError('protocol')
        return _Head(method, target, version, tuple(headers), length), prefix

    def body(self, head, prefix):
        payload = bytearray(prefix)
        while len(payload) < head.body_length:
            payload.extend(self._receive(min(head.body_length - len(payload), 65536)))
        return bytes(payload)

    def _write(self, value):
        self.connection.settimeout(3)
        self.connection.sendall(value)

    def error(self, kind):
        if self.started:
            return
        status, description, code = _ERRORS[kind]
        body = _bytes(
            {
                'error': {
                    'type': 'walle_control_error',
                    'code': code,
                    'message': _PUBLIC_MESSAGE,
                }
            }
        )
        head = (
            f'HTTP/1.1 {status} {description}\r\n'
            f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n'
            'Connection: close\r\nCache-Control: no-store\r\n\r\n'
        ).encode('ascii')
        self.started = True
        self._write(head + body)

    def stream(self, frame):
        if self.cancelled():
            raise CodingGatewayError('hold')
        if not self.started:
            self.started = True
            self._write(
                b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                b'Connection: close\r\nCache-Control: no-store\r\n\r\n'
            )
        self._write(frame)


class TaskModelRoute:
    def __init__(self, listener, launch, credential, connect, database):
        self._listener, self._launch, self._credential = listener, launch, credential
        self._connect, self._database = connect, database
        self._window = self._ingress = None
        self._revoked = Event()
        self._gate = RLock()

    @property
    def credential_ref(self):
        return self._credential.reference

    @property
    def accepting(self):
        return self._listener.accepting and not self._revoked.is_set()

    def revoke(self):
        with self._gate:
            self._revoked.set()
            if self._ingress is not None:
                self._ingress.revoke()
        self._listener.remove(self)

    def _read(self, window, credential_ref):
        with self._database.transaction() as connection:
            return read_original_open_window(connection, window, credential_ref)

    def _read_state(self, window):
        with self._database.transaction() as connection:
            return read_original_window_state(connection, window, self.credential_ref)

    def _queue_wait_seconds(self, window):
        with self._database.transaction() as connection:
            # The original window check also proves the verified C39 lineage.
            if read_original_window_state(connection, window, self.credential_ref) not in (
                'OPEN',
                'QUEUED',
            ):
                raise CodingGatewayError('hold')
            row = connection.execute(
                """SELECT p.limits AS profile_limits,a.scope AS authorization_scope
                   FROM code_tasks t JOIN code_execution_profile_versions p
                     ON p.id=t.execution_profile_version_id
                   JOIN code_authorizations a ON a.id=t.authorization_id AND a.task_id=t.id
                     AND a.profile_version_id=p.id AND a.status IN ('BOUND_PENDING_APPLY','EFFECTIVE')
                   WHERE t.id=? AND t.control_generation=? AND t.stop_requested_at IS NULL""",
                (window.task_id, window.generation),
            ).fetchone()
            if row is None:
                raise CodingGatewayError('hold')
            profile = strict_json_object(row['profile_limits'])
            authorization = strict_json_object(row['authorization_scope'])['limits']
            return min(
                strict_integer(profile['queue_wait_seconds'], 'queue_wait_seconds'),
                strict_integer(authorization['queue_wait_seconds'], 'queue_wait_seconds'),
            )

    def _verify(self, accepted, *, timeout_ms, cancelled):
        with self._connect() as frames:
            return self._launch.verify_model_source(
                accepted, timeout_ms=timeout_ms, cancelled=cancelled, frames=frames
            )

    def queue(self, scope, original):
        window = ModelWindow(
            scope.task_id,
            scope.instance_id,
            scope.control_generation,
            scope.session_id,
            original['native_session_id'],
            scope.operation_id,
            original['native_message_id'],
        )
        with self._gate:
            if (
                not self.accepting
                or self._window is not None
                or self._launch._original.scope.operation_id != scope.operation_id
                or self._launch._original.scope.nonce != scope.nonce
                or original['gateway_credential_ref'] != self.credential_ref
                or self._read_state(window) != 'QUEUED'
            ):
                raise TaskExecutionError('ORIGINAL_MODEL_QUEUE_FENCED')
            self._window = window
            self._ingress = TaskModelIngress(
                self._launch, window, self._read, self._credential, verify_source=self._verify
            )

    def queue_continuation(self, previous, window):
        with self._gate:
            if (
                not self.accepting
                or self._window != previous
                or self._ingress is None
                or previous.task_id != window.task_id
                or previous.instance_id != window.instance_id
                or previous.generation != window.generation
                or previous.execution_session_id != window.execution_session_id
                or previous.native_session_id != window.native_session_id
                or previous.operation_id == window.operation_id
                or self._read_state(window) != 'QUEUED'
            ):
                raise TaskExecutionError('ORIGINAL_MODEL_QUEUE_FENCED')
            self._ingress.revoke()
            self._window = window
            self._ingress = TaskModelIngress(
                self._launch, window, self._read, self._credential, verify_source=self._verify
            )

    def revoke_session_source(self, previous):
        with self._gate:
            if not self.accepting or self._window != previous or self._ingress is None:
                raise TaskExecutionError('ORIGINAL_ROLE_SOURCE_GATEWAY_DIFFERS')
            self._ingress.revoke()

    def owns_successor_window(self, window):
        with self._gate:
            return self.accepting and self._ingress is not None and self._window == window

    def queue_successor(self, previous, scope, original):
        window = ModelWindow(
            scope.task_id,
            scope.instance_id,
            scope.control_generation,
            scope.session_id,
            original['native_session_id'],
            scope.transition_operation_id,
            original['native_message_id'],
        )
        with self._gate:
            if (
                not self.accepting
                or self._window not in (previous, window)
                or self._ingress is None
                or previous.task_id != window.task_id
                or previous.instance_id != window.instance_id
                or previous.generation + 1 != window.generation
                or previous.execution_session_id == window.execution_session_id
                or previous.native_session_id == window.native_session_id
                or previous.operation_id == window.operation_id
                or self._launch._original.scope.operation_id != scope.operation_id
                or self._launch._original.scope.nonce != scope.nonce
                or original['gateway_credential_ref'] != self.credential_ref
                or self._read_state(window) != 'QUEUED'
            ):
                raise TaskExecutionError('ORIGINAL_ROLE_GATEWAY_QUEUE_FENCED')
            if self._window == window:
                return
            self._ingress.revoke()
            self._window = window
            self._ingress = TaskModelIngress(
                self._launch, window, self._read, self._credential, verify_source=self._verify
            )

    def _original(self, connection, head, accepted_window):
        with self._gate:
            if not self.accepting or self._ingress is None:
                raise CodingGatewayError('hold')
            ingress, window = self._ingress, self._window
            if window != accepted_window:
                raise CodingGatewayError('hold')
        try:
            ingress.check_request(connection, head.method, head.target, head.version, head.headers)
        except TaskExecutionError:
            raise CodingGatewayError('source') from None
        return ingress, window

    def process(self, exchange, head, prefix, dispatch, accepted_window):
        ingress, window = self._original(exchange.connection, head, accepted_window)
        raw = exchange.body(head, prefix)
        queued_deadline = monotonic() + self._queue_wait_seconds(window)

        def checkpoint():
            if exchange.cancelled() or not self.accepting:
                raise CodingGatewayError('hold')

        while True:
            checkpoint()
            state = self._read_state(window)
            if monotonic() >= queued_deadline:
                raise CodingGatewayError('hold')
            if state == 'OPEN':
                break
            if state != 'QUEUED':
                raise CodingGatewayError('hold')
            self._revoked.wait(0.025)

        def verify():
            checkpoint()
            try:
                return ingress.verify(
                    exchange.connection,
                    head.method,
                    head.target,
                    head.version,
                    head.headers,
                    checkpoint,
                    timeout_ms=5000,
                    cancelled=lambda: exchange.cancelled() or not self.accepting,
                )
            except TaskExecutionError as error:
                kind = 'hold' if str(error) == 'ORIGINAL_MODEL_WINDOW_FENCED' else 'source'
                raise CodingGatewayError(kind) from None

        proof = verify()
        dispatch(
            self.credential_ref,
            proof,
            raw,
            verify,
            exchange.stream,
            lambda: exchange.cancelled() or not self.accepting,
            instance_secret=self._credential._secret,
        )
        if not exchange.started:
            raise CodingGatewayError('hold')


class CodingModelListener:
    def __init__(self, endpoint, dispatch):
        address, port = endpoint
        if (
            address != '127.0.0.1'
            or type(port) is not int
            or not 0 <= port <= 65535
            or not callable(dispatch)
        ):
            raise ValueError('Dedicated model listener requires an exact loopback endpoint')
        self._dispatch = dispatch
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self._socket.bind(endpoint)
            self.endpoint = self._socket.getsockname()
            self._socket.listen(_MAX_CONNECTIONS)
            self._socket.settimeout(0.1)
        except BaseException:
            self._socket.close()
            raise
        self._gate, self._closing = RLock(), Event()
        self._permits = BoundedSemaphore(_MAX_CONNECTIONS)
        self._routes, self._connections = {}, set()
        self._pool = ThreadPoolExecutor(
            max_workers=_MAX_CONNECTIONS, thread_name_prefix='walle-code-model'
        )
        self._thread = Thread(target=self._accept, name='walle-code-model-accept', daemon=True)
        self._thread.start()

    @property
    def accepting(self):
        return not self._closing.is_set() and self._thread.is_alive()

    def attach(self, launch, credential, connect, database):
        if type(credential) is not OpenCodeModelCredential or credential.endpoint != self.endpoint:
            raise TaskExecutionError('ORIGINAL_MODEL_LISTENER_DIFFERS')
        with self._gate:
            if not self.accepting or credential.route in self._routes:
                raise TaskExecutionError('ORIGINAL_MODEL_LISTENER_UNAVAILABLE')
            route = TaskModelRoute(self, launch, credential, connect, database)
            self._routes[credential.route] = route
            return route

    def remove(self, route):
        with self._gate:
            path = route._credential.route
            if self._routes.get(path) is route:
                del self._routes[path]

    def _accept(self):
        while not self._closing.is_set():
            try:
                connection, peer = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._closing.is_set():
                    return
                raise
            if peer[0] != '127.0.0.1' or not self._permits.acquire(blocking=False):
                connection.close()
                continue
            with self._gate:
                if self._closing.is_set():
                    connection.close()
                    self._permits.release()
                    return
                self._connections.add(connection)
                # Capture the original admission window before reading the request.
                # A socket accepted for the held turn cannot enter a later window.
                accepted = {path: (route, route._window) for path, route in self._routes.items()}
                self._pool.submit(self._serve, connection, accepted)

    def _serve(self, connection, accepted):
        try:
            with connection:
                exchange = _LocalHttp(
                    connection, self.endpoint, cancelled=self._closing.is_set, timeout=15
                )
                try:
                    head, prefix = exchange.head()
                    original = accepted.get(head.target)
                    if original is None:
                        raise CodingGatewayError('source')
                    route, window = original
                    route.process(exchange, head, prefix, self._dispatch, window)
                except CodingGatewayError as error:
                    exchange.error(error.kind)
                except CodingModelProtocolError:
                    exchange.error('protocol')
                except (OSError, RuntimeError, ValueError):
                    exchange.error('hold')
        except OSError:
            pass
        finally:
            with self._gate:
                self._connections.discard(connection)
                self._permits.release()

    def close(self):
        with self._gate:
            self._closing.set()
            routes = tuple(self._routes.values())
            self._socket.close()
            for connection in self._connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        for route in routes:
            route.revoke()
        self._thread.join()
        self._pool.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
