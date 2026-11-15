"""Bounded loader diagnostics for a DEBUG_ONLY_THIS_PROCESS child created by this test thread.

Never attaches by PID or enables debug privileges. The caller owns the original process,
thread and Job; Windows owns event process/thread handles until ContinueDebugEvent(EXIT).
Image/DLL file handles are closed by this debugger. No raw traces are written to disk.
"""

import ctypes
import struct
from ctypes import wintypes
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic


class ExceptionRecord(ctypes.Structure):
    _fields_ = [
        ('code', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('record', ctypes.c_void_p),
        ('address', ctypes.c_void_p),
        ('count', wintypes.DWORD),
        ('information', ctypes.c_size_t * 15),
    ]


class ExceptionInfo(ctypes.Structure):
    _fields_ = [('record', ExceptionRecord), ('first_chance', wintypes.DWORD)]


class CreateInfo(ctypes.Structure):
    _fields_ = [
        ('file', wintypes.HANDLE),
        ('process', wintypes.HANDLE),
        ('thread', wintypes.HANDLE),
        ('base', ctypes.c_void_p),
        ('debug_offset', wintypes.DWORD),
        ('debug_size', wintypes.DWORD),
        ('thread_local_base', ctypes.c_void_p),
        ('start', ctypes.c_void_p),
        ('name', ctypes.c_void_p),
        ('unicode', wintypes.WORD),
    ]


class LoadInfo(ctypes.Structure):
    _fields_ = [
        ('file', wintypes.HANDLE),
        ('base', ctypes.c_void_p),
        ('debug_offset', wintypes.DWORD),
        ('debug_size', wintypes.DWORD),
        ('name', ctypes.c_void_p),
        ('unicode', wintypes.WORD),
    ]


class DebugString(ctypes.Structure):
    _fields_ = [
        ('address', ctypes.c_void_p),
        ('unicode', wintypes.WORD),
        ('length', wintypes.WORD),
    ]


class CreateThreadInfo(ctypes.Structure):
    _fields_ = [
        ('thread', wintypes.HANDLE),
        ('thread_local_base', ctypes.c_void_p),
        ('start', ctypes.c_void_p),
    ]


class EventData(ctypes.Union):
    _fields_ = [
        ('exception', ExceptionInfo),
        ('thread', CreateThreadInfo),
        ('create', CreateInfo),
        ('load', LoadInfo),
        ('exit_code', wintypes.DWORD),
        ('string', DebugString),
    ]


class DebugEvent(ctypes.Structure):
    _fields_ = [
        ('code', wintypes.DWORD),
        ('pid', wintypes.DWORD),
        ('tid', wintypes.DWORD),
        ('data', EventData),
    ]


@dataclass(frozen=True)
class StartupTrace:
    images: tuple[str, ...]
    exceptions: tuple[str, ...]
    messages: tuple[str, ...]
    exit_code: int
    stderr: str


def collect_owned_startup(info, job):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'WaitForDebugEventEx': ([ctypes.POINTER(DebugEvent), wintypes.DWORD], wintypes.BOOL),
        'ContinueDebugEvent': ([wintypes.DWORD, wintypes.DWORD, wintypes.DWORD], wintypes.BOOL),
        'ResumeThread': ([wintypes.HANDLE], wintypes.DWORD),
        'GetProcessId': ([wintypes.HANDLE], wintypes.DWORD),
        'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
        'GetFinalPathNameByHandleW': (
            [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD],
            wintypes.DWORD,
        ),
        'ReadProcessMemory': (
            [
                wintypes.HANDLE,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            ],
            wintypes.BOOL,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = arguments
        function.restype = result
    images = []
    exceptions = []
    messages = []
    ntdll_range = None
    loader_breakpoint_seen = False
    original_threads = {info.tid: info.thread}
    deadline = monotonic() + 12
    exit_code = None
    try:
        assert ctypes.sizeof(DebugEvent) == 176
        assert kernel.GetProcessId(info.process) == info.pid
        assert job.observe_members().process_ids == (info.pid,)
        assert kernel.ResumeThread(info.thread) == 1
        for _ in range(192):
            event = DebugEvent()
            if not kernel.WaitForDebugEventEx(ctypes.byref(event), 100):
                error = ctypes.get_last_error()
                if error == 121 and monotonic() < deadline:
                    continue
                raise AssertionError(('WAIT_OWNED_DEBUG_EVENT', error))
            status = 0x00010002  # DBG_CONTINUE for loader breakpoints and non-exception events.
            try:
                assert event.pid == info.pid
                if event.code in (3, 6):
                    handle = event.data.create.file if event.code == 3 else event.data.load.file
                    if handle:
                        try:
                            path = ctypes.create_unicode_buffer(32768)
                            length = kernel.GetFinalPathNameByHandleW(handle, path, len(path), 0)
                            assert 0 < length < len(path)
                            name = Path(path.value).name
                            images.append(name)
                            if name.casefold() == 'ntdll.dll':
                                base = (
                                    event.data.create.base
                                    if event.code == 3
                                    else event.data.load.base
                                )
                                header = ctypes.create_string_buffer(4096)
                                read = ctypes.c_size_t()
                                assert kernel.ReadProcessMemory(
                                    info.process, base, header, len(header), ctypes.byref(read)
                                )
                                pe = struct.unpack_from('<I', header.raw, 60)[0]
                                assert (
                                    header.raw[:2] == b'MZ' and header.raw[pe : pe + 4] == b'PE\0\0'
                                )
                                size = struct.unpack_from('<I', header.raw, pe + 24 + 56)[0]
                                assert 0 < size < 16 * 1024 * 1024
                                ntdll_range = base, base + size
                        finally:
                            assert kernel.CloseHandle(handle)
                elif event.code == 1:
                    code = event.data.exception.record.code
                    exceptions.append(f'0x{code:08X}:{event.data.exception.first_chance}')
                    address = event.data.exception.record.address
                    loader_breakpoint = (
                        code == 0x80000003
                        and not loader_breakpoint_seen
                        and ntdll_range is not None
                        and ntdll_range[0] <= address < ntdll_range[1]
                    )
                    if loader_breakpoint:
                        loader_breakpoint_seen = True
                    else:
                        status = 0x80010001  # DBG_EXCEPTION_NOT_HANDLED; never mask child faults.
                        if (
                            code == 0x80000003
                            and event.data.exception.first_chance == 1
                            and event.tid in original_threads
                        ):
                            import json
                            from types import SimpleNamespace
                            from backend.tests.infrastructure.v20_owned_thread_sample import (
                                sample_owned_thread,
                            )

                            original = SimpleNamespace(
                                process=info.process,
                                pid=info.pid,
                                thread=original_threads[event.tid],
                            )
                            sampled = sample_owned_thread(
                                original, stopped_by_original_debug_event=True
                            )
                            messages.append('ORIGINAL_FAULT ' + json.dumps(sampled))
                elif event.code == 2:
                    original_threads[event.tid] = event.data.thread.thread
                elif event.code == 4:
                    original_threads.pop(event.tid, None)
                elif event.code == 8:
                    string = event.data.string
                    length = min(string.length, 512) * (2 if string.unicode else 1)
                    if length and string.address:
                        buffer = ctypes.create_string_buffer(length)
                        read = ctypes.c_size_t()
                        if kernel.ReadProcessMemory(
                            info.process, string.address, buffer, length, ctypes.byref(read)
                        ):
                            encoding = 'utf-16-le' if string.unicode else 'mbcs'
                            messages.append(
                                buffer.raw[: read.value].decode(encoding, 'replace').rstrip('\0')
                            )
                elif event.code == 5:
                    exit_code = event.data.exit_code
            finally:
                assert kernel.ContinueDebugEvent(event.pid, event.tid, status)
            if exit_code is not None:
                break
            assert monotonic() < deadline, 'Owned debugger deadline exceeded'
    finally:
        if exit_code is None:
            # Only this original Job, never a reconstructed PID or another process tree.
            job.terminate_owned(1)
            drain_deadline = monotonic() + 3
            while monotonic() < drain_deadline:
                event = DebugEvent()
                if kernel.WaitForDebugEventEx(ctypes.byref(event), 100):
                    if event.code in (3, 6):
                        handle = event.data.create.file if event.code == 3 else event.data.load.file
                        if handle:
                            kernel.CloseHandle(handle)
                    kernel.ContinueDebugEvent(event.pid, event.tid, 0x00010002)
                    if event.code == 5:
                        break
    assert exit_code is not None, 'Owned child did not exit within the bounded trace'
    assert kernel.WaitForSingleObject(info.process, 5000) == 0
    stderr = ''
    streams = getattr(info, '_diagnostic_streams', None)
    if streams is not None:
        stderr = streams.stderr_bytes().decode('utf-8', 'replace')
    return StartupTrace(tuple(images), tuple(exceptions), tuple(messages), exit_code, stderr)


class ActivationContext(ctypes.Structure):
    _fields_ = [
        ('size', wintypes.ULONG),
        ('flags', wintypes.DWORD),
        ('source', wintypes.LPCWSTR),
        ('architecture', wintypes.USHORT),
        ('language', wintypes.WORD),
        ('assembly_directory', wintypes.LPCWSTR),
        ('resource', ctypes.c_void_p),
        ('application', wintypes.LPCWSTR),
        ('module', wintypes.HMODULE),
    ]


def probe_activation_contexts(token, runtime):
    """No activation, registry mutation, DLL execution, capability or ACL changes."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateActCtxW.argtypes = [ctypes.POINTER(ActivationContext)]
    kernel.CreateActCtxW.restype = wintypes.HANDLE
    kernel.ReleaseActCtx.argtypes = [wintypes.HANDLE]
    kernel.ReleaseActCtx.restype = None
    rows = []

    def inspect(label):
        for name, resource in (('python.exe', 1), ('python313.dll', 2), ('zlib.dll', 2)):
            request = ActivationContext()
            request.size = ctypes.sizeof(request)
            request.flags = 8 | 32
            request.source = str(runtime / name)
            request.resource = resource
            request.application = str(runtime / 'python.exe')
            ctypes.set_last_error(0)
            handle = kernel.CreateActCtxW(ctypes.byref(request))
            error = ctypes.get_last_error()
            if handle and handle != ctypes.c_void_p(-1).value:
                kernel.ReleaseActCtx(handle)
                rows.append((label, name, True, 0))
            else:
                rows.append((label, name, False, error))

    inspect('operator')
    token.with_restricted_token(lambda: inspect('original-lpac'))
    return tuple(rows)


def drain_owned_debug_exit(info):
    """Drain a terminated original diagnostic child even when its test fails before resume."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.WaitForDebugEventEx.argtypes = [ctypes.POINTER(DebugEvent), wintypes.DWORD]
    kernel.WaitForDebugEventEx.restype = wintypes.BOOL
    kernel.ContinueDebugEvent.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    kernel.ContinueDebugEvent.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    deadline = monotonic() + 4
    while monotonic() < deadline:
        event = DebugEvent()
        if not kernel.WaitForDebugEventEx(ctypes.byref(event), 100):
            error = ctypes.get_last_error()
            assert error == 121, ('DRAIN_OWNED_DEBUG_EVENT', error)
            continue
        assert event.pid == info.pid
        try:
            if event.code in (3, 6):
                handle = event.data.create.file if event.code == 3 else event.data.load.file
                if handle:
                    assert kernel.CloseHandle(handle)
        finally:
            assert kernel.ContinueDebugEvent(event.pid, event.tid, 0x00010002)
        if event.code == 5:
            return
    raise AssertionError('Owned debug exit was not observed')


@contextmanager
def diagnostic_registry_read_capability(original, profile):
    """One named read capability, only for the trusted exit91 diagnostic program."""
    from backend.app.infrastructure.windows_job import SecurityCapabilities

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [('sid', ctypes.c_void_p), ('attributes', wintypes.DWORD)]

    kernel = ctypes.WinDLL('kernelbase', use_last_error=True)
    derive = kernel.DeriveCapabilitySidsFromName
    sid_array = ctypes.POINTER(ctypes.c_void_p)
    derive.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(sid_array),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(sid_array),
        ctypes.POINTER(wintypes.DWORD),
    ]
    derive.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    groups = sid_array()
    capabilities = sid_array()
    group_count = wintypes.DWORD()
    capability_count = wintypes.DWORD()
    try:
        assert derive(
            'registryRead',
            ctypes.byref(groups),
            ctypes.byref(group_count),
            ctypes.byref(capabilities),
            ctypes.byref(capability_count),
        ), ctypes.get_last_error()
        assert capability_count.value == 1 and group_count.value <= 4
        with original(profile) as base:
            values = (SidAndAttributes * 1)(SidAndAttributes(capabilities[0], 4))
            yield SecurityCapabilities(
                base.appcontainer_sid, ctypes.cast(values, ctypes.c_void_p), 1, 0
            )
    finally:
        for array, count in ((groups, group_count.value), (capabilities, capability_count.value)):
            if array:
                for index in range(count):
                    assert not kernel.LocalFree(array[index])
                assert not kernel.LocalFree(ctypes.cast(array, ctypes.c_void_p))


class DiagnosticStdio:
    """Exact owned anonymous pipe ends for this fixed trusted diagnostic command."""

    def __init__(self):
        from backend.app.infrastructure.windows_stdio import _api

        self.kernel, _, _ = _api()
        self.handles = []
        self.child = []
        self.parents = []

    def __enter__(self):
        from backend.app.infrastructure.windows_private_package import SecurityAttributes

        attributes = SecurityAttributes()
        attributes.length = ctypes.sizeof(attributes)
        attributes.inherit_handle = True
        try:
            for index in range(3):
                read = wintypes.HANDLE()
                write = wintypes.HANDLE()
                assert self.kernel.CreatePipe(
                    ctypes.byref(read), ctypes.byref(write), ctypes.byref(attributes), 4096
                ), ctypes.get_last_error()
                self.handles.extend((read.value, write.value))
                child, parent = (
                    (read.value, write.value) if index == 0 else (write.value, read.value)
                )
                assert self.kernel.SetHandleInformation(parent, 1, 0)
                self.child.append(child)
                self.parents.append(parent)
            return self
        except BaseException:
            self.close()
            raise

    def close_child_ends(self):
        for handle in self.child:
            if handle in self.handles:
                assert self.kernel.CloseHandle(handle)
                self.handles.remove(handle)

    def stderr_bytes(self):
        from backend.app.infrastructure.windows_pipe_capture import _read_api, read_available_pipe

        kernel = _read_api(self.kernel)
        from time import sleep

        output = bytearray()
        for _ in range(100):
            data = read_available_pipe(kernel, self.parents[2], 4096 - len(output))
            if data is None:
                return bytes(output)
            if not data:
                sleep(0.01)
                continue
            output.extend(data)
            assert len(output) < 4096, 'Diagnostic STDERR exceeded bound'
        raise AssertionError('Diagnostic STDERR did not end')

    def close(self):
        for handle in tuple(self.handles):
            assert self.kernel.CloseHandle(handle)
            self.handles.remove(handle)

    def __exit__(self, *unused):
        self.close()
