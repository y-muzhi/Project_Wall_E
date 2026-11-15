"""Compare local socket initialization under the exact original LPAC token; no connect."""

import ctypes
from ctypes import wintypes
import pytest
from backend.app.infrastructure.windows_lpac_token import LpacProcessToken
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    controller,
    lpac_scope,
    ordinary_controller,
    suspended_lpac,
    tmp_path,
)


def socket_initialization():
    ws = ctypes.WinDLL('ws2_32', use_last_error=True)
    ws.WSAStartup.argtypes = [wintypes.WORD, ctypes.c_void_p]
    ws.WSAStartup.restype = ctypes.c_int
    ws.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    ws.socket.restype = ctypes.c_size_t
    ws.WSAGetLastError.restype = ctypes.c_int
    ws.closesocket.argtypes = [ctypes.c_size_t]
    ws.closesocket.restype = ctypes.c_int
    ws.WSACleanup.restype = ctypes.c_int
    data = ctypes.create_string_buffer(1024)
    started = ws.WSAStartup(0x0202, data)
    if started:
        return started, None
    try:
        handle = ws.socket(2, 1, 6)
        if handle == ctypes.c_size_t(-1).value:
            return 0, ws.WSAGetLastError()
        assert ws.closesocket(handle) == 0
        return 0, 0
    finally:
        assert ws.WSACleanup() == 0


@pytest.mark.parametrize('suspended_lpac', ['base_runtime_registry_read_debug'], indirect=True)
def test_thread_impersonation_does_not_reproduce_primary_process_socket_restriction(suspended_lpac):
    _, job, profile, info, pin = suspended_lpac
    ordinary = socket_initialization()
    token = LpacProcessToken(info, job, profile, pin, capability_names=('registryRead',))
    try:
        restricted = token.with_restricted_token(socket_initialization)
    finally:
        token.close()
    print('SOCKET_INITIALIZATION_ONLY', ordinary, restricted)
    assert ordinary == (0, 0)
    assert restricted == (0, 0)
