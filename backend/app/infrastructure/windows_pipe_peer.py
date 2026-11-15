"""Retain and revalidate a named-pipe peer's original native process and image.

This OS probe is NOT the Guard server, pipe DACL/local-only creation, protected
runtime-package admission or owner_epoch protocol. Expected identities/programs
come from trusted registration, never RPC assertions. It starts no process.
"""

import ctypes
import os
from contextlib import contextmanager
from ctypes import wintypes
from threading import RLock, get_ident

from .windows_executable_pin import ExecutablePin
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_process import NativeProcessIdentity, ObservedProcess, _identity
from .windows_process import _api as process_api


class PipePeerError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


def _error(code):
    return PipePeerError(code, ctypes.get_last_error())


def _api():
    kernel, security = process_api()
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    kernel.DuplicateHandle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.GetNamedPipeInfo.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.DWORD)] * 4
    kernel.GetNamedPipeInfo.restype = wintypes.BOOL
    kernel.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    for function in (kernel.GetNamedPipeClientProcessId, kernel.GetNamedPipeServerProcessId):
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        function.restype = wintypes.BOOL
    return kernel, security


class NamedPipePeerLease:
    """Own a non-inheritable duplicate and one held peer process; never reopen a PID."""

    def __init__(self, pipe_handle, *, peer_kind, expected, program, expected_user_sid):
        if type(pipe_handle) is not int or not 1 <= pipe_handle <= 0x7FFFFFFFFFFFFFFF:
            raise PipePeerError('ORIGINAL_PIPE_HANDLE_REQUIRED')
        if peer_kind not in ('CLIENT', 'SERVER'):
            raise PipePeerError('REGISTERED_PIPE_PEER_ROLE_REQUIRED')
        if type(expected) is not NativeProcessIdentity or type(program) is not ExecutablePin:
            raise PipePeerError('TRUSTED_ORIGINAL_PEER_REGISTRATION_REQUIRED')
        if expected.pid == os.getpid():
            raise PipePeerError('DISTINCT_PIPE_PEER_REQUIRED')
        if type(expected_user_sid) is not str or expected.user_sid != expected_user_sid:
            raise PipePeerError('REGISTERED_PIPE_PEER_USER_DIFFERS')
        if (
            expected.is_appcontainer
            or expected.appcontainer_sid is not None
            or expected.is_lpac is not False
        ):
            raise PipePeerError('APPCONTAINER_CONTROL_PEER_REJECTED')
        if peer_kind == 'CLIENT' and (
            expected.is_elevated or expected.user_sid in ('S-1-5-18', 'S-1-5-19', 'S-1-5-20')
        ):
            raise PipePeerError('ORDINARY_BACKEND_PEER_REQUIRED')
        self._owner_thread = get_ident()
        self._gate = RLock()
        self._users = 0
        self._closed = False
        self._pipe = None
        self._process = None
        self._program_lease = None
        self._program = program
        self._expected = expected
        self._peer_kind = peer_kind
        self._kernel, self._security = _api()
        try:
            copied = wintypes.HANDLE()
            current = self._kernel.GetCurrentProcess()
            if not self._kernel.DuplicateHandle(
                current, pipe_handle, current, ctypes.byref(copied), 0, False, 2
            ):
                raise _error('ORIGINAL_PIPE_DUPLICATE_UNAVAILABLE')
            self._pipe = copied.value
            self._verify_pipe()
            if self._peer_pid() != expected.pid:
                raise PipePeerError('ORIGINAL_PIPE_PEER_PID_DIFFERS')
            self._process = ObservedProcess(expected.pid, expected=expected)
            self._program_lease = program.creation_path()
            self._program_lease.__enter__()
            self.verify()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    def _check_thread(self):
        if get_ident() != self._owner_thread:
            raise PipePeerError('ORIGINAL_PIPE_PEER_OWNER_THREAD_DIFFERS')

    def _pid(self, function):
        value = wintypes.ULONG()
        if not function(self._pipe, ctypes.byref(value)) or not value.value:
            raise _error('ORIGINAL_PIPE_PROCESS_UNAVAILABLE')
        return value.value

    def _peer_pid(self):
        function = (
            self._kernel.GetNamedPipeClientProcessId
            if self._peer_kind == 'CLIENT'
            else self._kernel.GetNamedPipeServerProcessId
        )
        return self._pid(function)

    def _verify_pipe(self):
        flags = wintypes.DWORD()
        if (
            not self._kernel.GetHandleInformation(self._pipe, ctypes.byref(flags))
            or flags.value & 1
        ):
            raise _error('ORIGINAL_PIPE_INHERITANCE_UNVERIFIED')
        if self._kernel.GetFileType(self._pipe) != 3:
            raise PipePeerError('NAMED_PIPE_REQUIRED')
        info = wintypes.DWORD()
        if not self._kernel.GetNamedPipeInfo(self._pipe, ctypes.byref(info), None, None, None):
            raise _error('ORIGINAL_PIPE_INFORMATION_UNAVAILABLE')
        server_end = bool(info.value & 1)
        if server_end != (self._peer_kind == 'CLIENT'):
            raise PipePeerError('ORIGINAL_PIPE_ENDPOINT_ROLE_DIFFERS')
        own = (
            self._kernel.GetNamedPipeServerProcessId
            if server_end
            else self._kernel.GetNamedPipeClientProcessId
        )
        if self._pid(own) != os.getpid():
            raise PipePeerError('ORIGINAL_PIPE_LOCAL_OWNER_DIFFERS')
        # Process IDs can remain available after the other endpoint closes.
        # This zero-byte query consumes no frame data. Production endpoints are
        # overlapped and owned by one actor, with no concurrent pending IO here.
        if not self._kernel.PeekNamedPipe(self._pipe, None, 0, None, None, None):
            raise _error('ORIGINAL_PIPE_CONNECTION_UNAVAILABLE')

    def verify(self):
        self._check_thread()
        with self._gate:
            if self._closed or self._pipe is None or self._process is None:
                raise PipePeerError('ORIGINAL_PIPE_PEER_CLOSED')
            self._verify_pipe()
            if self._peer_pid() != self._expected.pid:
                raise PipePeerError('ORIGINAL_PIPE_PEER_CHANGED')
            if self._process.observe().state != 'RUNNING':
                raise PipePeerError('ORIGINAL_PIPE_PEER_EXITED')
            with self._process._gate:
                actual = _identity(
                    self._kernel, self._security, self._process._handle, self._expected.pid
                )
                if actual != self._expected:
                    raise PipePeerError('ORIGINAL_PIPE_PEER_IDENTITY_CHANGED')
            pinned = self._program.verify()
            path = local_absolute_path(actual.image_path)
            if str(path).casefold() != str(self._program.path).casefold():
                raise PipePeerError('REGISTERED_PIPE_PEER_IMAGE_DIFFERS')
            with LocalPathGuard(path, directory=False) as image:
                if image.identity != pinned.file:
                    raise PipePeerError('REGISTERED_PIPE_PEER_IMAGE_OBJECT_DIFFERS')
            if self._peer_pid() != self._expected.pid:
                raise PipePeerError('ORIGINAL_PIPE_PEER_CHANGED')
            return actual

    @contextmanager
    def original_process(self):
        self._check_thread()
        with self._gate:
            self.verify()
            self._users += 1
            try:
                yield self._process
            finally:
                self._users -= 1
                self.verify()

    def close(self):
        self._check_thread()
        with self._gate:
            if self._users:
                raise PipePeerError('ORIGINAL_PIPE_PEER_IN_USE')
            self._closed = True
            try:
                if self._process is not None:
                    self._process.close()
                    self._process = None
                if self._pipe is not None:
                    if not self._kernel.CloseHandle(self._pipe):
                        raise _error('ORIGINAL_PIPE_CLOSE_UNVERIFIED')
                    self._pipe = None
                if self._program_lease is not None:
                    lease, self._program_lease = self._program_lease, None
                    lease.__exit__(None, None, None)
            except BaseException as error:
                error.retained_owner = self
                raise

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


@contextmanager
def discover_registered_pipe_client(pipe_handle, *, program, expected_user_sid):
    """Capture an actual connected client; RPC fields never choose the process."""
    if type(pipe_handle) is not int or not 1 <= pipe_handle <= 0x7FFFFFFFFFFFFFFF:
        raise PipePeerError('ORIGINAL_PIPE_HANDLE_REQUIRED')
    kernel, _ = _api()
    candidate = wintypes.ULONG()
    if (
        not kernel.GetNamedPipeClientProcessId(pipe_handle, ctypes.byref(candidate))
        or not candidate.value
    ):
        raise _error('CONNECTED_BACKEND_PROCESS_UNAVAILABLE')
    with (
        ObservedProcess(candidate.value) as process,
        NamedPipePeerLease(
            pipe_handle,
            peer_kind='CLIENT',
            expected=process.identity,
            program=program,
            expected_user_sid=expected_user_sid,
        ) as peer,
        peer.original_process() as original,
    ):
        # The existing lease checks a live connection, original creation time,
        # native token, exact pinned image object and a repeated kernel peer id.
        yield original
