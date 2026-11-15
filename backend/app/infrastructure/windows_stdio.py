"""Fresh backend-owned STDIO pipes and Guard-only copies of child endpoints.

No byte read/write, business DB, model body or credentials are handled here.
Private descriptors travel only over authenticated Guard IPC, never public HTTP.
"""

import ctypes
import os
import re
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from .runtime_launch_journal import LaunchFence, LaunchScope, TestingLaunchScope
from .windows_check_stdin import create_check_stdin
from .windows_controller_token import ControllerPrimaryToken
from .windows_process import NativeProcessIdentity, ObservedProcess, _identity
from .windows_process import _api as process_api

CHILD_ENDS = ('STDIN_READ', 'STDOUT_WRITE', 'STDERR_WRITE')
PARENT_ENDS = {'STDIN': 'STDIN_WRITE', 'STDOUT': 'STDOUT_READ', 'STDERR': 'STDERR_READ'}
ALL_ENDS = (
    'STDIN_READ',
    'STDIN_WRITE',
    'STDOUT_READ',
    'STDOUT_WRITE',
    'STDERR_READ',
    'STDERR_WRITE',
)
MAX_HANDLE = 0x7FFFFFFFFFFFFFFF


class StdioBoundaryError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


class ObjectBasicInformation(ctypes.Structure):
    _fields_ = [
        ('attributes', wintypes.ULONG),
        ('granted_access', wintypes.ULONG),
        ('handle_count', wintypes.ULONG),
        ('pointer_count', wintypes.ULONG),
        ('reserved', wintypes.ULONG * 10),
    ]


@dataclass(frozen=True)
class ChildStdioDescriptor:
    owner: NativeProcessIdentity
    scope: LaunchScope
    io_nonce: str
    stdin_handle: str
    stdout_handle: str
    stderr_handle: str


@dataclass(frozen=True)
class GuardStdioBinding:
    owner: NativeProcessIdentity
    scope: LaunchScope
    io_nonce: str
    guard_io_ref: str


def _error(code):
    return StdioBoundaryError(code, ctypes.get_last_error())


def _api():
    kernel, security = process_api()
    kernel.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.CreatePipe.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetHandleInformation.restype = wintypes.BOOL
    kernel.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel.SetHandleInformation.restype = wintypes.BOOL
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
    native = ctypes.WinDLL('ntdll', use_last_error=True)
    native.NtQueryObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    native.NtQueryObject.restype = wintypes.LONG
    if ctypes.sizeof(ObjectBasicInformation) != 56:
        raise StdioBoundaryError('STDIO_NATIVE_LAYOUT_UNSUPPORTED')
    return kernel, security, native


def _handle_text(value):
    if type(value) is not int or not 1 <= value <= MAX_HANDLE:
        raise StdioBoundaryError('STDIO_HANDLE_INVALID')
    return f'{value:016x}'


def _handle(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{16}', value) is None:
        raise StdioBoundaryError('STDIO_HANDLE_INVALID')
    parsed = int(value, 16)
    _handle_text(parsed)
    return parsed


def _descriptor(value):
    if type(value) is not ChildStdioDescriptor or type(value.owner) is not NativeProcessIdentity:
        raise StdioBoundaryError('ORIGINAL_STDIO_DESCRIPTOR_REQUIRED')
    if (
        not isinstance(value.scope, LaunchScope)
        or type(value.io_nonce) is not str
        or re.fullmatch(
            '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', value.io_nonce
        )
        is None
    ):
        raise StdioBoundaryError('ORIGINAL_STDIO_SCOPE_INVALID')
    handles = tuple(
        _handle(text) for text in (value.stdin_handle, value.stdout_handle, value.stderr_handle)
    )
    if len(set(handles)) != 3:
        raise StdioBoundaryError('STDIO_ENDPOINTS_MUST_DIFFER')
    return handles


def _verify_pipe(kernel, native, handle, role, *, inheritable):
    if kernel.GetFileType(handle) != 3:
        raise StdioBoundaryError('ONLY_PIPE_STDIO_ALLOWED')
    basic = ObjectBasicInformation()
    returned = wintypes.ULONG()
    status = native.NtQueryObject(
        handle, 0, ctypes.byref(basic), ctypes.sizeof(basic), ctypes.byref(returned)
    )
    if status != 0 or returned.value != ctypes.sizeof(basic):
        raise StdioBoundaryError('STDIO_GRANTED_ACCESS_UNVERIFIED', status)
    readable = bool(basic.granted_access & 1)
    writable = bool(basic.granted_access & 2)
    if (role.endswith('_READ') and (not readable or writable)) or (
        role.endswith('_WRITE') and (not writable or readable)
    ):
        raise StdioBoundaryError('STDIO_DIRECTION_DIFFERS')
    flags = wintypes.DWORD()
    if not kernel.GetHandleInformation(handle, ctypes.byref(flags)):
        raise _error('STDIO_INHERITANCE_UNVERIFIED')
    if bool(flags.value & 1) != inheritable:
        raise StdioBoundaryError('STDIO_INHERITANCE_DIFFERS')


class _OwnedPipeEnds:
    def _initialize(self):
        self._gate = RLock()
        self._kernel, self._security, self._native = _api()
        self._ends = {}
        self._users = {}
        self._source_process = None

    def _verify(self, names, *, inheritable):
        for name in names:
            handle = self._ends.get(name)
            if handle is None:
                raise StdioBoundaryError('STDIO_ENDPOINT_CLOSED')
            _verify_pipe(self._kernel, self._native, handle, name, inheritable=inheritable)

    @contextmanager
    def _borrow(self, names, *, inheritable):
        with self._gate:
            self._verify(names, inheritable=inheritable)
            handles = tuple(self._ends[name] for name in names)
            for name in names:
                self._users[name] = self._users.get(name, 0) + 1
        try:
            yield handles
        finally:
            with self._gate:
                for name in names:
                    self._users[name] -= 1

    def _close(self, names):
        with self._gate:
            if any(self._users.get(name, 0) for name in names):
                raise StdioBoundaryError('STDIO_ENDPOINT_IN_USE')
            failures = []
            for name in names:
                handle = self._ends.get(name)
                if handle is None:
                    continue
                if self._kernel.CloseHandle(handle):
                    del self._ends[name]
                else:
                    failures.append(ctypes.get_last_error())
            if self._source_process is not None:
                if self._kernel.CloseHandle(self._source_process):
                    self._source_process = None
                else:
                    failures.append(ctypes.get_last_error())
            if failures:
                error = StdioBoundaryError('STDIO_CLOSE_UNVERIFIED', failures[0])
                error.retained_owner = self
                raise error

    def close(self):
        with self._gate:
            self._close(tuple(self._ends))

    def __exit__(self, kind, error, traceback):
        self.close()


class BackendStandardIO(_OwnedPipeEnds):
    """Backend owns parent ends; Guard never receives a parent data endpoint."""

    def __init__(self, scope, *, bounded_input=False):
        if (
            not isinstance(scope, LaunchScope)
            or type(bounded_input) is not bool
            or (bounded_input and type(scope) is not TestingLaunchScope)
        ):
            raise StdioBoundaryError('ORIGINAL_STDIO_SCOPE_INVALID')
        self._initialize()
        with ObservedProcess(os.getpid()) as current:
            self._owner = current.identity
        self._scope = scope
        self._nonce = str(uuid4())
        self._handoff_state = 'LOCAL'
        self._copy_binding = None
        self._output_claimed = False
        self._bounded_input = bounded_input
        try:
            for read_name, write_name in (
                ('STDIN_READ', 'STDIN_WRITE'),
                ('STDOUT_READ', 'STDOUT_WRITE'),
                ('STDERR_READ', 'STDERR_WRITE'),
            ):
                if bounded_input and read_name == 'STDIN_READ':
                    self._ends[read_name], self._ends[write_name] = create_check_stdin()
                    continue
                read, write = wintypes.HANDLE(), wintypes.HANDLE()
                # NULL security attributes: both initial handles are noninheritable.
                if not self._kernel.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0):
                    raise _error('STDIO_PIPE_CREATE_FAILED')
                self._ends[read_name] = read.value
                self._ends[write_name] = write.value
            self._verify(ALL_ENDS, inheritable=False)
        except BaseException as original:
            try:
                self.close()
            except StdioBoundaryError as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    @property
    def owner(self):
        return self._owner

    def descriptor(self):
        with self._gate:
            if os.getpid() != self._owner.pid:
                raise StdioBoundaryError('STDIO_CREATOR_PROCESS_DIFFERS')
            self._verify(CHILD_ENDS, inheritable=False)
            return ChildStdioDescriptor(
                self._owner,
                self._scope,
                self._nonce,
                *(_handle_text(self._ends[name]) for name in CHILD_ENDS),
            )

    def begin_handoff(self):
        with self._gate:
            if self._handoff_state != 'LOCAL':
                raise StdioBoundaryError('STDIO_HANDOFF_REQUIRES_ORIGINAL_OBSERVATION')
            descriptor = self.descriptor()
            self._handoff_state = 'MAY_HAVE_BEEN_SENT'
            return descriptor

    def acknowledge_copy(self, binding):
        with self._gate:
            if (
                type(binding) is not GuardStdioBinding
                or binding.owner != self._owner
                or binding.scope != self._scope
                or binding.io_nonce != self._nonce
                or type(binding.guard_io_ref) is not str
                or re.fullmatch('[0-9a-f]{32}', binding.guard_io_ref) is None
            ):
                raise StdioBoundaryError('STDIO_COPY_BINDING_DIFFERS')
            if self._handoff_state == 'LOCAL':
                raise StdioBoundaryError('STDIO_HANDOFF_NOT_PREPARED')
            if self._copy_binding is not None and self._copy_binding != binding:
                raise StdioBoundaryError('STDIO_COPY_CANNOT_REBIND')
            self._copy_binding = binding
            if self._handoff_state != 'SCOPE_CLOSED':
                self._handoff_state = 'GUARD_COPY_RECORDED'

    def acknowledge_closed_scope(self, fence):
        with self._gate:
            if (
                type(fence) is not LaunchFence
                or fence.scope != self._scope
                or fence.stop_closed is not True
            ):
                raise StdioBoundaryError('STDIO_ORIGINAL_CLOSURE_REQUIRED')
            self._handoff_state = 'SCOPE_CLOSED'
            # This permits local duplicate cleanup, never declares Root/Task STOP.

    def _require_handoff_settled(self):
        if self._handoff_state == 'MAY_HAVE_BEEN_SENT':
            error = StdioBoundaryError('STDIO_HANDOFF_UNVERIFIED')
            error.retained_owner = self
            raise error

    def close(self):
        with self._gate:
            self._require_handoff_settled()
            super().close()

    @contextmanager
    def parent_endpoint(self, stream):
        if os.getpid() != self._owner.pid or type(stream) is not str or stream not in PARENT_ENDS:
            raise StdioBoundaryError('STDIO_PARENT_STREAM_INVALID')
        with self._gate:
            if stream != 'STDIN' and self._output_claimed:
                raise StdioBoundaryError('STDIO_OUTPUT_READER_ALREADY_CLAIMED')
            lease = self._borrow((PARENT_ENDS[stream],), inheritable=False)
            handles = lease.__enter__()
        try:
            yield handles[0]
        finally:
            lease.__exit__(None, None, None)

    @contextmanager
    def output_endpoints(self):
        """One original output consumer; consuming bytes cannot be replayed."""
        names = (PARENT_ENDS['STDOUT'], PARENT_ENDS['STDERR'])
        with self._gate:
            if os.getpid() != self._owner.pid:
                raise StdioBoundaryError('STDIO_CREATOR_PROCESS_DIFFERS')
            if self._output_claimed or any(self._users.get(name, 0) for name in names):
                raise StdioBoundaryError('STDIO_OUTPUT_READER_ALREADY_CLAIMED')
            lease = self._borrow(names, inheritable=False)
            handles = lease.__enter__()
            self._output_claimed = True
        try:
            yield handles
        finally:
            lease.__exit__(None, None, None)

    def close_input(self):
        """Close the single original parent input writer after Guard copies."""
        with self._gate:
            if self._handoff_state != 'GUARD_COPY_RECORDED':
                raise StdioBoundaryError('STDIO_COPY_ACK_REQUIRED')
            self._close(('STDIN_WRITE',))

    def release_child_copies(self):
        """Backend calls only after original Guard copy/creation acknowledgment."""
        with self._gate:
            if self._handoff_state == 'LOCAL':
                raise StdioBoundaryError('STDIO_COPY_ACK_REQUIRED')
            self._require_handoff_settled()
            self._close(CHILD_ENDS)

    def __enter__(self):
        with self._gate:
            self._verify(ALL_ENDS, inheritable=False)
        return self


class GuardStandardIO(_OwnedPipeEnds):
    """Only same-access child-pipe copies, tied to original authenticated owner."""

    def __init__(self, controller_token, descriptor, *, scope):
        handles = _descriptor(descriptor)
        if type(controller_token) is not ControllerPrimaryToken or not isinstance(
            scope, LaunchScope
        ):
            raise StdioBoundaryError('AUTHENTICATED_CONTROLLER_TOKEN_REQUIRED')
        if descriptor.scope != scope or descriptor.owner != controller_token._expected:
            raise StdioBoundaryError('STDIO_ORIGINAL_OWNER_OR_SCOPE_DIFFERS')
        self._initialize()
        self.descriptor = descriptor
        self._controller_token = controller_token
        try:
            # The token lease revalidates the original held non-AC ordinary owner.
            with controller_token.creation_handle():
                source = self._kernel.OpenProcess(
                    0x40 | 0x1000 | 0x100000, False, descriptor.owner.pid
                )
                if not source:
                    raise _error('STDIO_SOURCE_PROCESS_UNAVAILABLE')
                self._source_process = source
                if (
                    _identity(self._kernel, self._security, source, descriptor.owner.pid)
                    != descriptor.owner
                ):
                    raise StdioBoundaryError('STDIO_SOURCE_PROCESS_IDENTITY_DIFFERS')
                for role, handle in zip(CHILD_ENDS, handles, strict=True):
                    copied = wintypes.HANDLE()
                    if not self._kernel.DuplicateHandle(
                        source,
                        handle,
                        self._kernel.GetCurrentProcess(),
                        ctypes.byref(copied),
                        0,
                        True,
                        2,
                    ):
                        raise _error('STDIO_CHILD_DUPLICATE_FAILED')
                    self._ends[role] = copied.value
                    _verify_pipe(self._kernel, self._native, copied.value, role, inheritable=True)
                if not self._kernel.CloseHandle(source):
                    raise _error('STDIO_SOURCE_PROCESS_CLOSE_UNVERIFIED')
                self._source_process = None
            self._binding = GuardStdioBinding(
                descriptor.owner, descriptor.scope, descriptor.io_nonce, uuid4().hex
            )
        except BaseException as original:
            try:
                self.close()
            except StdioBoundaryError as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise

    @property
    def binding(self):
        return self._binding

    @contextmanager
    def creation_handles(self):
        with (
            self._controller_token.creation_handle(),
            self._borrow(CHILD_ENDS, inheritable=True) as handles,
        ):
            yield handles

    def __enter__(self):
        with self._gate:
            self._verify(CHILD_ENDS, inheritable=True)
        return self
