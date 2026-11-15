"""Native witness for the original backend's synchronous workspace writer."""

import ctypes
from ctypes import wintypes

from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_pipe_capture import _read_api
from .windows_process import _identity
from .windows_stdio import _handle, _handle_text, _OwnedPipeEnds

_READ = 'WORKSPACE_READ'
_WRITE = 'WORKSPACE_WRITE'


class WorkspaceWriteError(LaunchOutcomeUnknown):
    pass


class GuardWorkspaceWriteLease(_OwnedPipeEnds):
    def __init__(self):
        self._initialize()
        _read_api(self._kernel)
        self._started = self._may_issue = False

    def offer(self, controller, checkpoint):
        if self._started:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_ALREADY_OFFERED')
        self._started = True
        kernel = self._kernel
        read, write, remote = wintypes.HANDLE(), wintypes.HANDLE(), wintypes.HANDLE()
        if not kernel.CreatePipe(ctypes.byref(read), ctypes.byref(write), None, 0):
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_PIPE_CREATE_UNVERIFIED')
        self._ends.update({_READ: read.value, _WRITE: write.value})
        self._verify((_READ, _WRITE), inheritable=False)
        expected = controller._expected
        self._source_process = kernel.OpenProcess(0x40 | 0x1000 | 0x100000, False, expected.pid)
        if (
            not self._source_process
            or _identity(kernel, self._security, self._source_process, expected.pid) != expected
        ):
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_PROCESS_DIFFERS')
        checkpoint()
        self._may_issue = True
        if (
            not kernel.DuplicateHandle(
                kernel.GetCurrentProcess(),
                write,
                self._source_process,
                ctypes.byref(remote),
                0x00100002,
                False,
                0,
            )
            or not remote.value
        ):
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_HANDOFF_UNVERIFIED')
        self._close((_WRITE,))
        return _handle_text(remote.value)

    def verify_closed(self):
        if not self._may_issue or _WRITE in self._ends:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_CLOSURE_UNVERIFIED')
        with self._borrow((_READ,), inheritable=False) as (reader,):
            available = wintypes.DWORD()
            if self._kernel.PeekNamedPipe(reader, None, 0, None, ctypes.byref(available), None):
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_STILL_ACTIVE')
            if ctypes.get_last_error() != 109:
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_CLOSURE_UNVERIFIED')

    def close(self):
        self._close((_WRITE,))
        if self._may_issue and _READ in self._ends:
            self.verify_closed()
        super().close()


class BackendWorkspaceWriteLease(_OwnedPipeEnds):
    def __init__(self, writer):
        self._initialize()
        handle = _handle(writer)
        self._ends[_WRITE] = handle
        self._verify((_WRITE,), inheritable=False)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None and getattr(error, 'retained_owner', None) is not None:
            error.retained_workspace_writer = self
            return
        self.close()
