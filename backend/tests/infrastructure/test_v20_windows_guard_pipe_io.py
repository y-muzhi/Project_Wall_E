"""Actual protected endpoint IO and cancellation; only owned short-lived peers."""

import ctypes
import hashlib
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Event, Timer
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_guard_pipe_io as module
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_guard_pipe import (
    CLIENT_ACCESS,
    GuardPipeError,
    GuardPipeServer,
)
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_pipe_peer import NamedPipePeerLease, PipePeerError
from backend.app.infrastructure.windows_private_package import current_operator_sid
from backend.app.infrastructure.windows_process import ObservedProcess, ProcessObservationError
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.infrastructure.test_v20_windows_pipe_peer import SCRIPT_API
from backend.tests.requirements.test_v15_foundation import tmp_path

CLIENT_API = """
k.ReadFile.argtypes=[wintypes.HANDLE,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.LPVOID]
k.ReadFile.restype=wintypes.BOOL
k.WriteFile.argtypes=k.ReadFile.argtypes
k.WriteFile.restype=wintypes.BOOL
k.CloseHandle.argtypes=[wintypes.HANDLE]
k.CloseHandle.restype=wintypes.BOOL
def write(raw):
    buffer=ctypes.create_string_buffer(raw)
    count=wintypes.DWORD()
    assert k.WriteFile(h,buffer,len(raw),ctypes.byref(count),None)
    assert count.value==len(raw)
"""


@contextmanager
def client_owner(directory, server, mode, *, script=None):
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    root = None
    held = {}
    code = (
        SCRIPT_API
        + CLIENT_API
        + f"""
h=k.CreateFileW({server.name!r},{CLIENT_ACCESS},0,None,3,0,None)
assert h not in (None,ctypes.c_void_p(-1).value)
with Path('io-peer-ready.tmp').open('x',encoding='ascii') as stream:
    stream.write(str(os.getpid()))
    stream.flush()
    os.fsync(stream.fileno())
os.replace('io-peer-ready.tmp','io-peer-ready')
"""
    )
    if mode == 'ECHO':
        code += """
write(b'ab')
time.sleep(0.03)
write(b'cd')
buffer=ctypes.create_string_buffer(5)
count=wintypes.DWORD()
assert k.ReadFile(h,buffer,5,ctypes.byref(count),None)
assert count.value==5 and buffer.raw==b'hello'
write(b'ok')
"""
    elif mode == 'CLOSE_WHILE_ALIVE':
        code += """
gate=ctypes.create_string_buffer(1)
count=wintypes.DWORD()
assert k.ReadFile(h,gate,1,ctypes.byref(count),None)
assert count.value==1 and gate.raw==b'g'
assert k.CloseHandle(h)
with Path('io-peer-closed.tmp').open('x',encoding='ascii') as stream:
    stream.write('closed')
    stream.flush()
    os.fsync(stream.fileno())
os.replace('io-peer-closed.tmp','io-peer-closed')
"""
    elif mode == 'PARTIAL_EOF':
        code += "write(b'ab')\nassert k.CloseHandle(h)\n"
    elif mode == 'FRAME_GOOD':
        code += """
raw='{"hello":"世界"}'.encode('utf-8')
header=len(raw).to_bytes(4,'big')
write(header[:2])
time.sleep(0.01)
write(header[2:]+raw[:3])
time.sleep(0.01)
write(raw[3:])
"""
    elif mode == 'FRAME_BAD_SIZE':
        code += "write((65533).to_bytes(4,'big'))\n"
    elif mode == 'FRAME_BAD_JSON':
        code += """
raw=b'{"x":1,"x":2}'
write(len(raw).to_bytes(4,'big')+raw)
"""
    elif mode == 'FRAME_PARTIAL':
        code += "write((20).to_bytes(4,'big')+b'{}')\nassert k.CloseHandle(h)\n"
    elif mode == 'FRAME_DEADLINE':
        code += """
gate=ctypes.create_string_buffer(1)
count=wintypes.DWORD()
assert k.ReadFile(h,gate,1,ctypes.byref(count),None)
assert count.value==1 and gate.raw==b'g'
raw=b'{"ok":true}'
time.sleep(0.04)
write(len(raw).to_bytes(4,'big'))
time.sleep(0.04)
write(raw)
"""
    elif mode == 'FRAME_EXCHANGE':
        code += """
import json
header=ctypes.create_string_buffer(4)
count=wintypes.DWORD()
assert k.ReadFile(h,header,4,ctypes.byref(count),None)
assert count.value==4
size=int.from_bytes(header.raw,'big')
assert 1<=size<=65532
body=ctypes.create_string_buffer(size)
assert k.ReadFile(h,body,size,ctypes.byref(count),None)
assert count.value==size and json.loads(body.raw)=={'msg':'你好'}
raw=b'{"reply":"ok"}'
write(len(raw).to_bytes(4,'big')+raw)
"""
    elif mode == 'BACKEND_BINDING':
        from pathlib import Path

        code += f'import sys\nsys.path.insert(0,{str(Path(__file__).resolve().parents[3])!r})\n'
        code += f"""
import json
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
original_lock=ProcessLock(Path.cwd()/'backend-caller.lock')
original_lock.acquire()
binding=bind_backend_controller(original_lock,{server.name.rsplit('.', 1)[1]!r})
raw=json.dumps({{'owner_epoch':binding.owner_epoch,'controller_ref':binding.controller_ref}},separators=(',',':')).encode('utf-8')
write(len(raw).to_bytes(4,'big')+raw)
"""
    code = script if script is not None else code + 'time.sleep(60)\n'
    try:
        root = TestSuspendedRoot(job, directory, code)

        def ready():
            marker = directory / 'io-peer-ready'
            deadline = monotonic() + 10
            while not marker.exists() and monotonic() < deadline:
                sleep(0.01)
            assert marker.exists(), 'Owned pipe client did not connect'
            pid = int(marker.read_text(encoding='ascii'))
            if pid not in held:
                held[pid] = ObservedProcess(pid)
                assert job.contains_process(held[pid])
            return held[pid]

        yield SimpleNamespace(start=root.resume, ready=ready, job=job)
    finally:
        members = job.observe_members()
        assert members.complete
        for pid in members.process_ids:
            if pid not in held:
                try:
                    process = ObservedProcess(pid)
                except ProcessObservationError:
                    continue
                assert job.contains_process(process)
                held[pid] = process
        job.terminate_owned(1)
        for process in held.values():
            assert process._kernel.WaitForSingleObject(process._handle, 8000) == 0
            process.close()
        if root is not None:
            assert job._kernel.WaitForSingleObject(root.info.process, 8000) == 0
            root.close()
        deadline = monotonic() + 8
        while job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        assert job.observe_members().complete and not job.observe_members().process_ids
        job.close()


@pytest.fixture
def channel(tmp_path):
    with GuardPipeServer(uuid4().hex + uuid4().hex, backend_sid=current_operator_sid()) as server:
        with ExitStack() as owners:

            def client(mode='SILENT'):
                return owners.enter_context(client_owner(tmp_path, server, mode))

            with module.GuardPipeIO(server) as io:
                yield io, client, server
                assert io._pending is None and io not in module._RETAINED


@pytest.mark.parametrize('early', [True, False])
def test_real_partial_reads_full_write_and_connect_race(channel, early):
    io, client, server = channel
    peer = client('ECHO')
    timer = None
    try:
        if early:
            peer.start()
            peer.ready()
        else:
            timer = Timer(0.03, peer.start)
            timer.start()
        io.connect(timeout_ms=3000, cancelled=lambda: False)
        peer.ready()
        assert io.read_exact(4, timeout_ms=3000, cancelled=lambda: False) == b'abcd'
        io.write_all(b'hello', timeout_ms=3000, cancelled=lambda: False)
        assert io.read_exact(2, timeout_ms=3000, cancelled=lambda: False) == b'ok'
        assert io._pending is None and io not in module._RETAINED
        server.verify()
    finally:
        if timer is not None:
            timer.join(3)


def test_connect_timeout_confirms_original_cancellation_then_forbids_stream_reuse(channel):
    io, _, _ = channel
    with pytest.raises(module.PipeIOError, match='CANCELLED_OR_TIMED_OUT') as error:
        io.connect(timeout_ms=20, cancelled=lambda: False)
    assert error.value.native_error == 995 and error.value.transferred is None
    assert io._pending is None and io not in module._RETAINED
    with pytest.raises(module.PipeIOError, match='UNAVAILABLE'):
        io.connect(timeout_ms=100, cancelled=lambda: False)


@pytest.mark.parametrize('cancel', [False, True])
def test_pending_read_timeout_or_explicit_cancel_is_drained_before_buffer_release(channel, cancel):
    io, client, _ = channel
    peer = client()
    peer.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    peer.ready()
    event = Event()
    timer = Timer(0.03, event.set) if cancel else None
    try:
        if timer is not None:
            timer.start()
        with pytest.raises(module.PipeIOError, match='CANCELLED_OR_TIMED_OUT'):
            io.read_exact(1, timeout_ms=1000 if cancel else 20, cancelled=event.is_set)
        assert io._pending is None and io not in module._RETAINED
        assert peer.ready().observe().state == 'RUNNING'
    finally:
        if timer is not None:
            timer.join(3)


def test_unknown_completion_retains_original_buffer_endpoint_and_owner_until_reconciled(channel):
    io, client, server = channel
    peer = client()
    peer.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    peer.ready()

    def unknown(*_):
        ctypes.set_last_error(6)
        return False

    with patch.object(io._kernel, 'GetOverlappedResultEx', side_effect=unknown):
        with pytest.raises(module.PipeIOError, match='COMPLETION_UNKNOWN') as error:
            io.read_exact(1, timeout_ms=100, cancelled=lambda: False)
        assert error.value.retained_owner is io
        assert io._pending is not None and io._pending.buffer is not None
        assert io in module._RETAINED
        with pytest.raises(GuardPipeError, match='IN_USE'):
            server.close()
    io.close()
    assert io._pending is None and io not in module._RETAINED


def test_unknown_cancel_preserves_original_native_allocation_until_close_can_verify(channel):
    io, client, _ = channel
    peer = client()
    peer.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    peer.ready()

    def unavailable(*_):
        ctypes.set_last_error(5)
        return False

    with patch.object(io._kernel, 'CancelIoEx', side_effect=unavailable):
        with pytest.raises(module.PipeIOError, match='CANCEL_UNVERIFIED') as error:
            io.read_exact(1, timeout_ms=20, cancelled=lambda: False)
        assert error.value.retained_owner is io and io in module._RETAINED
        assert io._pending is not None
    io.close()
    assert io._pending is None and io not in module._RETAINED


def test_partial_eof_is_not_a_full_frame_or_success(channel):
    io, client, _ = channel
    peer = client('PARTIAL_EOF')
    peer.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    peer.ready()
    with pytest.raises(module.PipeIOError):
        io.read_exact(4, timeout_ms=1000, cancelled=lambda: False)
    assert io._pending is None and io not in module._RETAINED


def test_pre_dispatch_cancel_and_bad_capacity_create_no_pending_io(channel):
    io, _, _ = channel
    for value in (None, True, 0, 65537):
        with pytest.raises(module.PipeIOError, match='CAPACITY_INVALID'):
            io.read_exact(value, timeout_ms=100, cancelled=lambda: False)
    with pytest.raises(module.PipeIOError, match='BEFORE_DISPATCH'):
        io.connect(timeout_ms=100, cancelled=lambda: True)
    assert io._pending is None and io not in module._RETAINED


def test_live_process_without_original_pipe_connection_cannot_authorize_requests(channel, tmp_path):
    io, client, server = channel
    backend = client('CLOSE_WHILE_ALIVE')
    backend.start()
    io.connect(timeout_ms=3000, cancelled=lambda: False)
    actual = backend.ready()
    raw = Path(actual.identity.image_path).read_bytes()
    with ExecutablePin(
        actual.identity.image_path,
        expected_byte_count=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    ) as program:
        with NamedPipePeerLease(
            server._handle,
            peer_kind='CLIENT',
            expected=actual.identity,
            program=program,
            expected_user_sid=server.backend_sid,
        ) as original:
            assert original.verify() == actual.identity
            io.write_all(b'g', timeout_ms=3000, cancelled=lambda: False)
            marker = tmp_path / 'io-peer-closed'
            deadline = monotonic() + 5
            while not marker.exists() and monotonic() < deadline:
                sleep(0.01)
            assert marker.read_text(encoding='ascii') == 'closed'
            assert actual.observe().state == 'RUNNING'
            with pytest.raises(PipePeerError):
                original.verify()
