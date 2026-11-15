"""Actual named-pipe endpoints and held peers inside owned Jobs; no Guard install."""

import ctypes
import hashlib
import os
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_pipe_peer as module
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_executable_pin import ExecutablePin, ExecutablePinError
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess, ProcessObservationError
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_API = """
import ctypes,os,time
from ctypes import wintypes
from pathlib import Path
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateNamedPipeW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]
k.CreateNamedPipeW.restype=wintypes.HANDLE
k.ConnectNamedPipe.argtypes=[wintypes.HANDLE,wintypes.LPVOID]
k.ConnectNamedPipe.restype=wintypes.BOOL
k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
k.CreateFileW.restype=wintypes.HANDLE
"""


def native_api():
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR] + [wintypes.DWORD] * 6 + [wintypes.LPVOID]
    k.CreateNamedPipeW.restype = wintypes.HANDLE
    k.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    k.ConnectNamedPipe.restype = wintypes.BOOL
    k.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    k.DisconnectNamedPipe.restype = wintypes.BOOL
    k.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    k.CreateFileW.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


@pytest.fixture(params=('CLIENT', 'SERVER'))
def connection(tmp_path, request):
    role = request.param
    k = native_api()
    name = r'\\.\pipe\WalleFixture-' + uuid4().hex
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    root = None
    endpoint = None
    observed = {}
    pin = None
    try:
        if role == 'CLIENT':
            endpoint = k.CreateNamedPipeW(name, 3 | 0x80000, 8, 1, 4096, 4096, 1000, None)
            assert endpoint not in (None, ctypes.c_void_p(-1).value)
            setup = f'h=k.CreateFileW({name!r},0xC0000000,0,None,3,0,None)\nassert h not in (None,ctypes.c_void_p(-1).value)\n'
        else:
            setup = f'h=k.CreateNamedPipeW({name!r},3|0x80000,8,1,4096,4096,1000,None)\nassert h not in (None,ctypes.c_void_p(-1).value)\n'
        marker = """
with Path('peer-ready.tmp').open('x',encoding='ascii') as stream:
    stream.write(str(os.getpid()))
    stream.flush()
    os.fsync(stream.fileno())
os.replace('peer-ready.tmp','peer-ready')
"""
        connect = (
            ''
            if role == 'CLIENT'
            else '\nif not k.ConnectNamedPipe(h,None) and ctypes.get_last_error()!=535: raise ctypes.WinError(ctypes.get_last_error())\n'
        )
        root = TestSuspendedRoot(
            job, tmp_path, SCRIPT_API + setup + marker + connect + '\ntime.sleep(60)\n'
        )
        root.resume()
        ready = tmp_path / 'peer-ready'
        deadline = monotonic() + 10
        while not ready.exists() and monotonic() < deadline:
            sleep(0.01)
        assert ready.exists(), 'Owned named-pipe fixture did not prepare'
        actual_pid = int(ready.read_text(encoding='ascii'))
        held = ObservedProcess(actual_pid)
        observed[actual_pid] = held
        assert job.contains_process(held)
        assert not held.identity.is_appcontainer and not held.identity.is_elevated
        if role == 'CLIENT':
            assert k.ConnectNamedPipe(endpoint, None) or ctypes.get_last_error() == 535
        else:
            endpoint = k.CreateFileW(name, 0xC0000000, 0, None, 3, 0, None)
            assert endpoint not in (None, ctypes.c_void_p(-1).value)
        path = Path(held.identity.image_path)
        raw = path.read_bytes()
        # Fixture program bytes are explicit here; this is no deployment/package admission.
        pin = ExecutablePin(
            path, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
        )
        yield SimpleNamespace(
            role=role, kernel=k, handle=endpoint, process=held, program=pin, job=job
        )
    finally:
        if pin is not None:
            pin.close()
        if endpoint not in (None, ctypes.c_void_p(-1).value):
            assert k.CloseHandle(endpoint)
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


def peer(data, expected=None, program=None):
    return module.NamedPipePeerLease(
        data.handle,
        peer_kind=data.role,
        expected=data.process.identity if expected is None else expected,
        program=data.program if program is None else program,
        expected_user_sid=data.process.identity.user_sid,
    )


@pytest.mark.parametrize('handle', [None, True, 0, -1, '1', 0x8000000000000000])
def test_invalid_or_serialized_handle_fails_before_native_api(handle):
    with patch.object(module, '_api', side_effect=AssertionError('No native access')):
        with pytest.raises(module.PipePeerError, match='HANDLE_REQUIRED'):
            module.NamedPipePeerLease(
                handle, peer_kind='CLIENT', expected=None, program=None, expected_user_sid=None
            )


def test_actual_both_endpoint_roles_hold_original_process_and_program(connection):
    data = connection
    with peer(data) as lease:
        assert lease.verify() == data.process.identity
        assert lease._pipe != data.handle
        with lease.original_process() as original:
            assert original is lease._process and original.identity == data.process.identity
            with pytest.raises(module.PipePeerError, match='IN_USE'):
                lease.close()
            with pytest.raises(ExecutablePinError, match='IN_USE'):
                data.program.close()
            if data.role == 'CLIENT':
                with ControllerPrimaryToken(original, expected=original.identity) as token:
                    assert token.identity.user_sid == original.identity.user_sid
    with pytest.raises(module.PipePeerError, match='CLOSED'):
        lease.verify()
    assert data.process.observe().state == 'RUNNING'


def test_original_creation_identity_mismatch_is_not_reopened_or_accepted(connection):
    data = connection
    with pytest.raises(ProcessObservationError, match='EXPECTED_PROCESS_IDENTITY_DIFFERS'):
        peer(data, expected=replace(data.process.identity, creation_time_hex='0' * 16))
    with peer(data) as lease:
        with patch.object(
            module, 'ObservedProcess', side_effect=AssertionError('Never reopen an old PID')
        ):
            assert lease.verify() == data.process.identity


def test_registered_image_cannot_be_replaced_by_another_valid_image(connection):
    path = ROOT / 'backend/runtime/git/2.56.0.windows.4/win-x64/cmd/git.exe'
    raw = path.read_bytes()
    with ExecutablePin(
        path, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
    ) as other:
        with pytest.raises(module.PipePeerError, match='IMAGE_DIFFERS'):
            peer(connection, program=other)
    assert connection.process.observe().state == 'RUNNING'


def test_owner_role_or_user_claim_does_not_change_actual_peer(connection):
    data = connection
    wrong_role = 'SERVER' if data.role == 'CLIENT' else 'CLIENT'
    with pytest.raises(module.PipePeerError, match='ROLE_DIFFERS'):
        module.NamedPipePeerLease(
            data.handle,
            peer_kind=wrong_role,
            expected=data.process.identity,
            program=data.program,
            expected_user_sid=data.process.identity.user_sid,
        )
    with pytest.raises(module.PipePeerError, match='USER_DIFFERS'):
        module.NamedPipePeerLease(
            data.handle,
            peer_kind=data.role,
            expected=data.process.identity,
            program=data.program,
            expected_user_sid='S-1-0-0',
        )


def test_pipe_peer_exit_cannot_become_a_new_identity(connection):
    data = connection
    with peer(data) as lease:
        data.job.terminate_owned(1)
        assert data.process._kernel.WaitForSingleObject(data.process._handle, 8000) == 0
        with patch.object(
            module, 'ObservedProcess', side_effect=AssertionError('Never reopen an exited PID')
        ):
            with pytest.raises((module.PipePeerError, ProcessObservationError)):
                lease.verify()


def test_disconnected_server_end_does_not_authorize_original_peer(connection):
    data = connection
    if data.role != 'CLIENT':
        return
    with peer(data) as lease:
        assert data.kernel.DisconnectNamedPipe(data.handle)
        with pytest.raises(module.PipePeerError):
            lease.verify()


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_controller_process_copy_survives_original_pipe_lease_release_and_tracks_same_exit(
    connection,
):
    from backend.app.infrastructure import windows_process as processes

    with peer(connection) as lease:
        with lease.original_process() as original:
            copied = original.duplicate()
        expected = copied.identity
    try:
        assert copied.observe().identity == expected
        with patch.object(processes, '_api', side_effect=AssertionError('No old PID reopen')):
            with ControllerPrimaryToken(copied, expected=expected) as token:
                assert token.identity.user_sid == expected.user_sid
                with token.creation_handle():
                    pass
                connection.job.terminate_owned(1)
                assert copied._kernel.WaitForSingleObject(copied._handle, 8000) == 0
                assert copied.observe().state == 'EXITED'
                with pytest.raises(RuntimeError, match='CONTROLLER_EXITED'):
                    with token.creation_handle():
                        pytest.fail('No creation after original controller exit')
    finally:
        copied.close()
