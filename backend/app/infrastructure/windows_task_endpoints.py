"""Observe the exact original TASK loopback endpoints without sending application bytes."""

import ctypes
import hashlib
import socket
from contextlib import ExitStack
from ctypes import wintypes
from ipaddress import ip_address
from struct import unpack_from

from .opencode_task_launch import TaskExecutionError, TaskExecutionPlan
from .runtime_launch_journal import _bytes
from .windows_process import ObservedProcess

_OWNER_PID_LISTENER = 3
_OWNER_PID_CONNECTIONS = 4
_MAX_TABLE_BYTES = 8 * 1024 * 1024


def _tcp_table(family, table_class):
    query = ctypes.WinDLL('iphlpapi').GetExtendedTcpTable
    query.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    )
    query.restype = wintypes.DWORD
    size = wintypes.DWORD()
    buffer = None
    for _ in range(4):
        status = query(buffer, ctypes.byref(size), False, family, table_class, 0)
        if status == 0 and buffer is not None:
            break
        if status != 122 or not 4 <= size.value <= _MAX_TABLE_BYTES:
            raise TaskExecutionError('ORIGINAL_TASK_TCP_TABLE_UNAVAILABLE')
        buffer = ctypes.create_string_buffer(size.value)
    else:
        raise TaskExecutionError('ORIGINAL_TASK_TCP_TABLE_UNVERIFIED')
    count = unpack_from('<I', buffer)[0]
    row_size = 24 if family == socket.AF_INET else 56
    if 4 + count * row_size > len(buffer):
        raise TaskExecutionError('ORIGINAL_TASK_TCP_TABLE_LAYOUT_DIFFERS')
    return buffer, range(4, 4 + count * row_size, row_size), row_size


def _listeners(family):
    buffer, offsets, row_size = _tcp_table(family, _OWNER_PID_LISTENER)
    result = []
    for offset in offsets:
        if family == socket.AF_INET:
            (state,) = unpack_from('<I', buffer, offset)
            address = ip_address(buffer[offset + 4 : offset + 8])
            port_offset = offset + 8
        else:
            (state,) = unpack_from('<I', buffer, offset + 48)
            address = ip_address(buffer[offset : offset + 16])
            port_offset = offset + 20
        if state != 2:
            continue
        port = int.from_bytes(buffer[port_offset : port_offset + 2], 'big')
        (pid,) = unpack_from('<I', buffer, offset + row_size - 4)
        result.append((address, port, pid))
    return result


def _established_connections():
    buffer, offsets, _ = _tcp_table(socket.AF_INET, _OWNER_PID_CONNECTIONS)
    rows = []
    for offset in offsets:
        state, _, _, _, _, owner = unpack_from('<6I', buffer, offset)
        if state != 5:
            continue
        source = (
            str(ip_address(buffer[offset + 4 : offset + 8])),
            int.from_bytes(buffer[offset + 8 : offset + 10], 'big'),
        )
        target = (
            str(ip_address(buffer[offset + 12 : offset + 16])),
            int.from_bytes(buffer[offset + 16 : offset + 18], 'big'),
        )
        rows.append((source, target, owner))
    return rows


def _connection_owners(rows, local, remote):
    return [pid for source, target, pid in rows if source == local and target == remote]


def verify_task_control_connection(connection, endpoint, pid):
    local, remote = connection.getsockname(), connection.getpeername()
    if remote != endpoint or local[0] != endpoint[0]:
        raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CONNECTION_DIFFERS')
    if _connection_owners(_established_connections(), remote, local) != [pid]:
        raise TaskExecutionError('ORIGINAL_TASK_CONTROL_CONNECTION_OWNER_UNVERIFIED')


def verify_task_model_connection(client, server, *, root_pid, backend_pid):
    if client[0] != '127.0.0.1' or server[0] != '127.0.0.1' or client == server:
        raise TaskExecutionError('ORIGINAL_TASK_MODEL_CONNECTION_DIFFERS')
    rows = _established_connections()
    if (
        root_pid == backend_pid
        or _connection_owners(rows, client, server) != [root_pid]
        or _connection_owners(rows, server, client) != [backend_pid]
    ):
        raise TaskExecutionError('ORIGINAL_TASK_MODEL_CONNECTION_OWNER_UNVERIFIED')


def _matching_listeners(rows, address, port):
    original = ip_address(address)
    return [
        row
        for row in rows
        if row[1] == port
        and (
            row[0] == original
            or row[0].is_unspecified
            or getattr(row[0], 'ipv4_mapped', None) == original
        )
    ]


def _verify_listener(rows, address, port, pid):
    if _matching_listeners(rows, address, port) != [(ip_address(address), port, pid)]:
        raise TaskExecutionError('ORIGINAL_TASK_LISTENER_OWNER_UNVERIFIED')


def require_private_http_port(endpoint):
    if (
        type(endpoint) is not tuple
        or len(endpoint) != 2
        or endpoint[0] != '127.0.0.1'
        or type(endpoint[1]) is not int
        or not 49152 <= endpoint[1] <= 65535
    ):
        raise TaskExecutionError('ORIGINAL_CHECK_HTTP_PRIVATE_PORT_REQUIRED')
    rows = _listeners(socket.AF_INET) + _listeners(socket.AF_INET6)
    if _matching_listeners(rows, *endpoint):
        raise TaskExecutionError('ORIGINAL_CHECK_HTTP_PORT_IN_USE')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(endpoint)
        except OSError as error:
            raise TaskExecutionError('ORIGINAL_CHECK_HTTP_PORT_IN_USE') from error


def original_http_listener_ready(endpoint, pid):
    address, port = endpoint
    rows = _listeners(socket.AF_INET) + _listeners(socket.AF_INET6)
    if not _matching_listeners(rows, address, port):
        return False
    _verify_listener(rows, address, port, pid)
    return True


def verify_original_http_connection(connection, endpoint, *, root_pid, backend_pid):
    local, remote = connection.getsockname(), connection.getpeername()
    if remote != endpoint or local[0] != endpoint[0] or root_pid == backend_pid:
        raise TaskExecutionError('ORIGINAL_CHECK_HTTP_CONNECTION_DIFFERS')
    rows = _established_connections()
    if _connection_owners(rows, remote, local) != [root_pid] or _connection_owners(
        rows, local, remote
    ) != [backend_pid]:
        raise TaskExecutionError('ORIGINAL_CHECK_HTTP_CONNECTION_OWNER_UNVERIFIED')


def observe_task_endpoints(plan, process, expected, checkpoint):
    if type(plan) is not TaskExecutionPlan or type(process) is not ObservedProcess:
        raise TaskExecutionError('ORIGINAL_TASK_ENDPOINT_OWNER_REQUIRED')
    with process._gate, ExitStack() as held:
        checkpoint()
        before = process.observe()
        if before.identity != expected or before.state != 'RUNNING':
            raise TaskExecutionError('ORIGINAL_TASK_ENDPOINT_OWNER_UNVERIFIED')
        rows = _listeners(socket.AF_INET) + _listeners(socket.AF_INET6)
        network = plan.network
        for role in ('model', 'forward'):
            for address, port in network[role]:
                checkpoint()
                _verify_listener(rows, address, port, expected.pid)
        for role in ('control', 'application'):
            for address, port in network[role]:
                checkpoint()
                family = socket.AF_INET if address == '127.0.0.1' else socket.AF_INET6
                probe = held.enter_context(socket.socket(family, socket.SOCK_STREAM))
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                if family == socket.AF_INET6:
                    probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                try:
                    probe.bind((address, port))
                except OSError as error:
                    raise TaskExecutionError('ORIGINAL_TASK_LISTENER_PORT_UNAVAILABLE') from error
        if process.observe() != before:
            raise TaskExecutionError('ORIGINAL_TASK_ENDPOINT_OWNER_UNVERIFIED')
        checkpoint()
        return hashlib.sha256(
            _bytes(
                {
                    'network': network,
                    'backend_pid': expected.pid,
                    'backend_created': expected.creation_time_hex,
                }
            )
        ).hexdigest()
