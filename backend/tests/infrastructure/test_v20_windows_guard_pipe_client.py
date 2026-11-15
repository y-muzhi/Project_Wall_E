"""Actual distinct Guard peer, protected server/client endpoints and duplex IO."""

import hashlib
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_pipe_peer
from backend.app.infrastructure.windows_guard_pipe import GuardPipeClient, GuardPipeError
from backend.app.infrastructure.windows_guard_pipe_io import GuardPipeIO
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_executable_pin import ExecutablePin, ExecutablePinError
from backend.app.infrastructure.windows_private_package import current_operator_sid
from backend.app.infrastructure.windows_process import ObservedProcess, ProcessObservationError
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def guard(tmp_path):
    ref = uuid4().hex + uuid4().hex
    sid = current_operator_sid()
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    root = None
    pin = None
    observed = {}
    code = f"""
import os,sys,time
from pathlib import Path
sys.path.insert(0,{str(ROOT)!r})
from backend.app.infrastructure.windows_guard_pipe import GuardPipeServer
from backend.app.infrastructure.windows_guard_pipe_io import GuardPipeIO
with GuardPipeServer({ref!r},backend_sid={sid!r}) as server:
    with GuardPipeIO(server) as io:
        with Path('guard-pipe-ready.tmp').open('x',encoding='ascii') as stream:
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace('guard-pipe-ready.tmp','guard-pipe-ready')
        io.connect(timeout_ms=10000,cancelled=lambda:False)
        assert io.read_exact(4,timeout_ms=10000,cancelled=lambda:False)==b'ping'
        io.write_all(b'pong',timeout_ms=10000,cancelled=lambda:False)
        time.sleep(60)
"""
    try:
        root = TestSuspendedRoot(job, tmp_path, code)
        root.resume()
        marker = tmp_path / 'guard-pipe-ready'
        deadline = monotonic() + 10
        while not marker.exists() and monotonic() < deadline:
            sleep(0.01)
        assert marker.exists(), 'Owned Guard endpoint fixture did not prepare'
        pid = int(marker.read_text(encoding='ascii'))
        process = ObservedProcess(pid)
        observed[pid] = process
        assert job.contains_process(process)
        path = Path(process.identity.image_path)
        raw = path.read_bytes()
        pin = ExecutablePin(
            path, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
        )
        yield SimpleNamespace(ref=ref, sid=sid, process=process, program=pin, job=job)
    finally:
        try:
            if pin is not None:
                pin.close()
        finally:
            members = job.observe_members()
            assert members.complete
            for pid in members.process_ids:
                if pid not in observed:
                    try:
                        member = ObservedProcess(pid)
                    except ProcessObservationError:
                        continue
                    assert job.contains_process(member)
                    observed[pid] = member
            job.terminate_owned(1)
            for member in observed.values():
                assert member._kernel.WaitForSingleObject(member._handle, 8000) == 0
                member.close()
            if root is not None:
                assert job._kernel.WaitForSingleObject(root.info.process, 8000) == 0
                root.close()
            deadline = monotonic() + 8
            while job.observe_members().process_ids and monotonic() < deadline:
                sleep(0.01)
            assert job.observe_members().complete and not job.observe_members().process_ids
            job.close()


def connect(guard, **changed):
    arguments = {
        'backend_sid': guard.sid,
        'server_sid': guard.sid,
        'expected_guard': guard.process.identity,
        'program': guard.program,
    }
    arguments.update(changed)
    return GuardPipeClient(guard.ref, **arguments)


def test_actual_client_checks_guard_owner_image_then_uses_original_duplex_io(guard):
    with connect(guard) as client:
        client.verify()
        assert client._peer.verify() == guard.process.identity
        with pytest.raises(ExecutablePinError, match='IN_USE'):
            guard.program.close()
        with GuardPipeIO(client) as io:
            assert io._connected
            io.write_all(b'ping', timeout_ms=3000, cancelled=lambda: False)
            assert io.read_exact(4, timeout_ms=3000, cancelled=lambda: False) == b'pong'
        client.verify()


def test_client_rejects_other_creation_time_on_same_guard_pid(guard):
    expected = replace(guard.process.identity, creation_time_hex='0' * 16)
    with pytest.raises(ProcessObservationError, match='EXPECTED_PROCESS_IDENTITY_DIFFERS'):
        connect(guard, expected_guard=expected)


def test_client_cannot_adopt_another_valid_registered_program(guard):
    path = ROOT / 'backend/runtime/git/2.56.0.windows.4/win-x64/cmd/git.exe'
    raw = path.read_bytes()
    with ExecutablePin(
        path, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
    ) as other:
        with pytest.raises(windows_pipe_peer.PipePeerError, match='IMAGE_DIFFERS'):
            connect(guard, program=other)


def test_no_server_is_created_by_client_and_user_registration_is_not_replaced(guard):
    with pytest.raises(GuardPipeError, match='USERS_DIFFER'):
        connect(guard, server_sid='S-1-5-18')
    with pytest.raises(GuardPipeError, match='USERS_DIFFER'):
        connect(guard, backend_sid='S-1-5-18')
    with pytest.raises(GuardPipeError, match='UNAVAILABLE'):
        GuardPipeClient(
            uuid4().hex + uuid4().hex,
            backend_sid=guard.sid,
            server_sid=guard.sid,
            expected_guard=guard.process.identity,
            program=guard.program,
        )


def test_guard_exit_cannot_rebind_client_by_pid(guard):
    client = connect(guard)
    try:
        guard.job.terminate_owned(1)
        assert guard.process._kernel.WaitForSingleObject(guard.process._handle, 8000) == 0
        with patch.object(
            windows_pipe_peer, 'ObservedProcess', side_effect=AssertionError('No PID reopen')
        ):
            with pytest.raises((windows_pipe_peer.PipePeerError, ProcessObservationError)):
                client.verify()
    finally:
        client.close()


@pytest.mark.parametrize('value', [None, 1, {'pid': 1}])
def test_client_requires_trusted_program_and_process_not_serialized_claim(value):
    with pytest.raises(TypeError):
        GuardPipeClient(
            'a' * 64,
            backend_sid='S-1-0-0',
            server_sid='S-1-0-0',
            expected_guard=value,
            program=value,
        )
