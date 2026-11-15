"""Explicit frozen-backend deployment probes; never open business data or send requests."""

import argparse
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from time import monotonic, sleep

from backend.app.infrastructure.program_manifest import BACKEND_PROGRAM_POLICY, GUARD_PROGRAM_POLICY
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.windows_guard_service import connect_registered_guard
from backend.app.infrastructure.windows_private_package import current_operator_sid
from backend.app.infrastructure.windows_process import ObservedProcess

READER_LIFETIME_SECONDS = 300
MAX_READER_COMMAND_BYTES = 16


class BackendGuardProbeError(RuntimeError):
    pass


def _require_probe_runtime():
    if not getattr(sys, 'frozen', False) or Path(sys.executable).name != 'walle-backend.exe':
        raise BackendGuardProbeError('DEDICATED_FROZEN_BACKEND_PROBE_REQUIRED')
    if any(
        name == prefix or name.startswith(prefix + '.')
        for name in sys.modules
        for prefix in ('backend.app.service', 'backend.app.infrastructure.database')
    ):
        raise BackendGuardProbeError('BACKEND_PROBE_BUSINESS_IMPORT_REJECTED')


def _require_original_ordinary_reader(process):
    original = process.observe()
    identity = original.identity
    if (
        original.state != 'RUNNING'
        or identity.is_appcontainer
        or identity.is_elevated
        or identity.user_sid in ('S-1-5-18', 'S-1-5-19', 'S-1-5-20')
        or current_operator_sid() != identity.user_sid
    ):
        raise BackendGuardProbeError('BACKEND_PROBE_ORDINARY_ORIGINAL_READER_REQUIRED')
    return identity


def _control_api():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel.ReadFile.restype = wintypes.BOOL
    return kernel


class ReaderControlPipe:
    """Borrow the original stdin pipe; read only the fixed bounded STOP command."""

    def __init__(self):
        self._kernel = _control_api()
        self._handle = self._kernel.GetStdHandle(wintypes.DWORD(-10).value)
        if (
            not self._handle
            or self._handle == ctypes.c_void_p(-1).value
            or self._kernel.GetFileType(self._handle) != 3
        ):
            raise BackendGuardProbeError('BACKEND_READER_CONTROL_PIPE_REQUIRED')
        self._raw = bytearray()

    def _closed(self):
        if self._raw:
            raise BackendGuardProbeError('BACKEND_READER_INCOMPLETE_COMMAND')
        return True

    def stopped(self):
        available = wintypes.DWORD()
        if not self._kernel.PeekNamedPipe(
            self._handle, None, 0, None, ctypes.byref(available), None
        ):
            if ctypes.get_last_error() in (109, 233):
                return self._closed()
            raise BackendGuardProbeError('BACKEND_READER_PIPE_STATE_UNVERIFIED')
        if not available.value:
            return False
        if available.value > MAX_READER_COMMAND_BYTES - len(self._raw):
            raise BackendGuardProbeError('BACKEND_READER_COMMAND_LIMIT')
        data = ctypes.create_string_buffer(available.value)
        count = wintypes.DWORD()
        if not self._kernel.ReadFile(
            self._handle, data, len(data), ctypes.byref(count), None
        ) or not 1 <= count.value <= len(data):
            raise BackendGuardProbeError('BACKEND_READER_COMMAND_READ_UNVERIFIED')
        self._raw.extend(data.raw[: count.value])
        if b'\n' in self._raw:
            if self._raw != b'STOP\n':
                raise BackendGuardProbeError('BACKEND_READER_COMMAND_REJECTED')
            return True
        if not b'STOP\n'.startswith(self._raw):
            raise BackendGuardProbeError('BACKEND_READER_COMMAND_REJECTED')
        return False


def hold_installation_reader(program_sha256):
    _require_probe_runtime()
    with (
        ProgramPackageLease(
            Path(sys.executable).parent,
            expected_sha256=program_sha256,
            policy=BACKEND_PROGRAM_POLICY,
        ) as package,
        ObservedProcess(os.getpid()) as original,
    ):
        package.verify_running_entry(sys.executable)
        identity = _require_original_ordinary_reader(original)
        control = ReaderControlPipe()
        print(
            'BACKEND_INSTALLATION_READER_READY '
            f'pid={identity.pid} created={identity.creation_time_hex}',
            flush=True,
        )
        deadline = monotonic() + READER_LIFETIME_SECONDS
        while not control.stopped():
            if monotonic() >= deadline:
                raise BackendGuardProbeError('BACKEND_READER_LIFETIME_EXCEEDED')
            _require_original_ordinary_reader(original)
            sleep(0.05)
        package.verify()
        _require_probe_runtime()
    print('BACKEND_INSTALLATION_READER_RELEASED no_database_service_or_model', flush=True)
    return 0


def verify_guard(program_sha256, guard_root, guard_sha256, installation_ref):
    _require_probe_runtime()
    with (
        ProgramPackageLease(
            Path(sys.executable).parent,
            expected_sha256=program_sha256,
            policy=BACKEND_PROGRAM_POLICY,
        ) as backend,
        ProgramPackageLease(
            guard_root,
            expected_sha256=guard_sha256,
            policy=GUARD_PROGRAM_POLICY,
        ) as guard,
        ObservedProcess(os.getpid()) as original,
    ):
        backend.verify_running_entry(sys.executable)
        identity = _require_original_ordinary_reader(original)
        with connect_registered_guard(
            installation_ref, backend_sid=identity.user_sid, program=guard._entry
        ) as endpoint:
            endpoint.verify()
            _require_original_ordinary_reader(original)
        guard.verify()
        backend.verify()
        _require_probe_runtime()
    print('BACKEND_GUARD_PROCESS_AND_PIPE_VERIFIED no_business_request_sent', flush=True)
    return 0


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--hold-installation-reader', action='store_true')
    mode.add_argument('--verify-guard', action='store_true')
    parser.add_argument('--program-sha256', required=True)
    parser.add_argument('--guard-package', type=Path)
    parser.add_argument('--guard-sha256')
    parser.add_argument('--installation-ref')
    values = parser.parse_args(arguments)
    guard_arguments = (values.guard_package, values.guard_sha256, values.installation_ref)
    if values.hold_installation_reader and any(value is not None for value in guard_arguments):
        parser.error('Installation reader cannot accept Guard connection arguments')
    if values.verify_guard and any(value is None for value in guard_arguments):
        parser.error('Guard inspection requires the fixed Guard package, digest and installation')
    try:
        if values.hold_installation_reader:
            return hold_installation_reader(values.program_sha256)
        return verify_guard(
            values.program_sha256,
            values.guard_package,
            values.guard_sha256,
            values.installation_ref,
        )
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        print('BACKEND_DEPLOYMENT_PROBE_REJECTED', file=sys.stderr)
        if getattr(error, 'retained_owner', None) is not None:
            os._exit(1)
        return 1
