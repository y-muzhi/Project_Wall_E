"""Issue sealed HTTP requests only to the verified original Windows TASK root."""

import http.client
import os
import socket
from dataclasses import dataclass
from hashlib import sha256
from io import BufferedReader, RawIOBase
from select import select
from time import monotonic, sleep

from backend.app.shared.validation import strict_integer

from .check_case_evidence import HttpStepObservation, evaluate_http_case
from .check_case_pack import CheckCase
from .check_case_values import (
    header_value,
    relative_target,
    request_headers,
    request_method,
    response_header,
)
from .check_runner_bundle import CheckResourceError, reference
from .windows_process import NativeProcessIdentity, ObservedProcess
from .windows_task_endpoints import (
    original_http_listener_ready,
    require_private_http_port,
    verify_original_http_connection,
)

_POLL_SECONDS = 0.05
_MAX_HEADERS = 64
_RESPONSE_OVERHEAD = 32 * 1024
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class OwnedHttpUnavailable(CheckResourceError):
    """No business bytes were sent in the original case."""


class OwnedHttpUnknown(CheckResourceError):
    """At least one original step may have issued business bytes."""


@dataclass(frozen=True)
class OwnedHttpEndpoint:
    endpoint_ref: str
    port: int

    def __post_init__(self):
        reference(self.endpoint_ref)
        if type(self.port) is not int or not 49152 <= self.port <= 65535:
            raise OwnedHttpUnavailable('ORIGINAL_CHECK_HTTP_PRIVATE_PORT_REQUIRED')

    @property
    def address(self):
        return ('127.0.0.1', self.port)


def allocate_http_endpoint(endpoint_ref):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', 0))
        endpoint = OwnedHttpEndpoint(endpoint_ref, probe.getsockname()[1])
    require_private_http_port(endpoint.address)
    return endpoint


def _checkpoint(deadline, active):
    if monotonic() >= deadline:
        raise TimeoutError('ORIGINAL_CHECK_HTTP_DEADLINE')
    active()


def _wait(connection, deadline, active, *, writing=False):
    while True:
        _checkpoint(deadline, active)
        readers = [] if writing else [connection]
        writers = [connection] if writing else []
        read, write, error = select(readers, writers, [connection], _POLL_SECONDS)
        if error:
            raise OSError('ORIGINAL_CHECK_HTTP_SOCKET_ERROR')
        if read or write:
            _checkpoint(deadline, active)
            return


class _BoundedWire(RawIOBase):
    def __init__(self, connection, deadline, active, remaining):
        super().__init__()
        self._connection = connection
        self._deadline, self._active = deadline, active
        self._remaining = remaining

    def readable(self):
        return True

    def readinto(self, buffer):
        if not len(buffer):
            return 0
        while True:
            _wait(self._connection, self._deadline, self._active)
            try:
                size = self._connection.recv_into(buffer, min(len(buffer), self._remaining + 1))
                break
            except BlockingIOError:
                continue
        if size > self._remaining:
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_WIRE_LIMIT')
        self._remaining -= size
        return size


class _ResponseSource:
    def __init__(self, stream):
        self._stream = stream

    def makefile(self, mode):
        if mode != 'rb':
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_RESPONSE_STREAM_REQUIRED')
        return self._stream


def _original_request(step, endpoint, maximum, *, headers_decoder=request_headers):
    if step.op != 'REQUEST' or len(step.operands) != 5:
        raise OwnedHttpUnavailable('ORIGINAL_CHECK_HTTP_STEP_DIFFERS')
    endpoint_ref, path, method, headers, body = step.operands
    if (
        endpoint_ref != endpoint.endpoint_ref
        or type(body) is not bytes
        or len(body) > maximum
        or type(headers) is not tuple
        or headers_decoder(dict(headers)) != headers
    ):
        raise OwnedHttpUnavailable('ORIGINAL_CHECK_HTTP_REQUEST_DIFFERS')
    path, method = relative_target(path), request_method(method)
    lines = [
        f'{method} {path} HTTP/1.1',
        f'Host: 127.0.0.1:{endpoint.port}',
        'Connection: close',
        f'Content-Length: {len(body)}',
        *(f'{name}: {value}' for name, value in headers),
    ]
    return method, ('\r\n'.join(lines) + '\r\n\r\n').encode('ascii') + body


def _original_response(
    connection, step, method, deadline, active, remaining, *, response_decoder=None
):
    wire = _BoundedWire(connection, deadline, active, remaining + _RESPONSE_OVERHEAD)
    with (
        BufferedReader(wire) as stream,
        http.client.HTTPResponse(_ResponseSource(stream), method=method) as response,
    ):
        response.begin()
        if not 200 <= response.status <= 599 or response.version not in (10, 11):
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_RESPONSE_PROTOCOL_DIFFERS')
        headers = response.getheaders()
        if len(headers) > _MAX_HEADERS or response.headers.defects:
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_RESPONSE_HEADERS_UNVERIFIED')
        lengths = response.headers.get_all('Content-Length', [])
        encodings = response.headers.get_all('Transfer-Encoding', [])
        if (
            len(lengths) > 1
            or lengths
            and (len(lengths[0]) > 10 or not lengths[0].isascii() or not lengths[0].isdigit())
            or encodings
            and (lengths or len(encodings) != 1 or encodings[0].lower() != 'chunked')
        ):
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_RESPONSE_FRAMING_DIFFERS')
        if response_decoder is None:
            relevant = []
            for name, value in headers:
                try:
                    safe_name = response_header(name.lower())
                except CheckResourceError:
                    continue
                relevant.append((safe_name, header_value(value)))
        else:
            relevant = response_decoder(response.status, headers)
        remaining -= sum(len(name) + len(value) for name, value in relevant)
        expected = response.length
        if remaining < 0 or expected is not None and expected > remaining:
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_RESPONSE_LIMIT')
        body = response.read(remaining + 1)
        if len(body) > remaining or expected is not None and len(body) != expected:
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_RESPONSE_INCOMPLETE')
        return HttpStepObservation(step.step_id, response.status, tuple(relevant), body)


def _send_request(connection, raw, deadline, active):
    pending = memoryview(raw)
    while pending:
        _wait(connection, deadline, active, writing=True)
        try:
            written = connection.send(pending[:16384])
        except BlockingIOError:
            continue
        if written <= 0:
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_SOCKET_CLOSED')
        pending = pending[written:]


def _root_running(process):
    if process.observe().state != 'RUNNING':
        raise OwnedHttpUnavailable('ORIGINAL_CHECK_HTTP_ROOT_NOT_RUNNING')


def _connect(endpoint, process, deadline, active):
    while True:
        _checkpoint(deadline, active)
        _root_running(process)
        if original_http_listener_ready(endpoint.address, process.identity.pid):
            break
        sleep(_POLL_SECONDS)
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    try:
        connection.settimeout(min(_POLL_SECONDS, max(0.001, deadline - monotonic())))
        connection.connect(endpoint.address)
        connection.setblocking(False)
        return connection
    except BaseException:
        connection.close()
        raise


def _exchange_original_request(
    step,
    endpoint,
    process,
    method,
    raw,
    *,
    deadline,
    active,
    verify_job,
    before_send,
    remaining,
    response_decoder=None,
):
    with _connect(endpoint, process, deadline, active) as connection:
        _checkpoint(deadline, active)
        verify_job()
        _root_running(process)
        if not original_http_listener_ready(endpoint.address, process.identity.pid):
            raise OwnedHttpUnavailable('ORIGINAL_CHECK_HTTP_LISTENER_LOST')
        verify_original_http_connection(
            connection, endpoint.address, root_pid=process.identity.pid, backend_pid=os.getpid()
        )
        before_send(step.step_id, sha256(raw).hexdigest())
        _wait(connection, deadline, active, writing=True)
        _root_running(process)
        verify_original_http_connection(
            connection, endpoint.address, root_pid=process.identity.pid, backend_pid=os.getpid()
        )
        _send_request(connection, raw, deadline, active)
        return _original_response(
            connection,
            step,
            method,
            deadline,
            active,
            remaining,
            response_decoder=response_decoder,
        )


def run_owned_http_case(
    case,
    endpoint,
    identity,
    *,
    output_limit,
    request_limit,
    deadline,
    active,
    verify_job,
    before_send,
):
    """Hold the original process and require native and durable proof before every send."""
    if (
        type(case) is not CheckCase
        or type(endpoint) is not OwnedHttpEndpoint
        or type(identity) is not NativeProcessIdentity
        or not case.steps
    ):
        raise OwnedHttpUnavailable('ORIGINAL_CHECK_HTTP_INPUTS_REQUIRED')
    limit = strict_integer(output_limit, 'output_limit', maximum=_MAX_OUTPUT_BYTES)
    request_limit = strict_integer(request_limit, 'request_limit', maximum=_MAX_OUTPUT_BYTES)
    requests = tuple(_original_request(step, endpoint, request_limit) for step in case.steps)
    observations = []
    dispatched = False
    remaining = limit

    def record(step_id, request_sha256):
        nonlocal dispatched
        before_send(step_id, request_sha256)
        dispatched = True

    try:
        with ObservedProcess(identity.pid, expected=identity) as process:
            for step, (method, raw) in zip(case.steps, requests, strict=True):
                observed = _exchange_original_request(
                    step,
                    endpoint,
                    process,
                    method,
                    raw,
                    deadline=deadline,
                    active=active,
                    verify_job=verify_job,
                    before_send=record,
                    remaining=remaining,
                )
                observations.append(observed)
                remaining -= len(observed.body) + sum(
                    len(name) + len(value) for name, value in observed.headers
                )
        return evaluate_http_case(case, tuple(observations), output_limit=limit)
    except Exception as error:
        if dispatched:
            raise OwnedHttpUnknown('ORIGINAL_CHECK_HTTP_RESULT_UNVERIFIED') from error
        raise OwnedHttpUnavailable('ORIGINAL_CHECK_HTTP_DISPATCH_UNAVAILABLE') from error
