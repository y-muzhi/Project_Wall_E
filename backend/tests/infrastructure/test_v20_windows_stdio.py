"""Native pipes/handle whitelist; copied primary token never starts a process."""

from dataclasses import asdict, replace
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import windows_stdio as stdio
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_job import OwnedJob, JobBoundaryError
from backend.app.infrastructure.windows_process import NativeProcessIdentity, ObservedProcess
from backend.app.infrastructure.runtime_launch_journal import LaunchFence, LaunchScope
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path
from backend.tests.infrastructure.v20_stdio_worker import publish

ROOT = Path(__file__).resolve().parents[3]


def scope(number=1):
    return LaunchScope('a' * 64, number, 1, 'stdio-original-nonce-0001')


def closed(original):
    # Explicit private-protocol fact double; journal durability has a separate test.
    return LaunchFence(1, original, None, 'NONE', 'NONE', None, True, 1, '2026-11-05T00:00:00.000Z')


def wait_file(path):
    deadline = monotonic() + 8
    while not path.exists() and monotonic() < deadline:
        sleep(0.01)
    assert path.exists(), path.name


def test_fresh_backend_owns_six_noninheritable_directional_pipes_and_descriptor_has_only_child_ends():
    with stdio.BackendStandardIO(scope()) as streams:
        descriptor = streams.descriptor()
        assert descriptor.scope == scope() and descriptor.owner.pid == os.getpid()
        assert len(streams._ends) == 6
        assert {
            stdio._handle(value)
            for value in (
                descriptor.stdin_handle,
                descriptor.stdout_handle,
                descriptor.stderr_handle,
            )
        } == {streams._ends[name] for name in stdio.CHILD_ENDS}
        for name, handle in streams._ends.items():
            stdio._verify_pipe(streams._kernel, streams._native, handle, name, inheritable=False)
        with streams.parent_endpoint('STDOUT'):
            # Reader lifetime must not block unrelated child-release metadata.
            with pytest.raises(stdio.StdioBoundaryError, match='ENDPOINT_IN_USE'):
                streams.close()
        with pytest.raises(stdio.StdioBoundaryError, match='COPY_ACK_REQUIRED'):
            streams.release_child_copies()
    with pytest.raises(stdio.StdioBoundaryError, match='ENDPOINT_CLOSED'):
        streams.descriptor()


def test_unknown_handoff_retains_original_handles_until_copy_or_closed_scope_fact():
    streams = stdio.BackendStandardIO(scope())
    descriptor = streams.begin_handoff()
    try:
        with pytest.raises(stdio.StdioBoundaryError, match='ORIGINAL_OBSERVATION'):
            streams.begin_handoff()
        with pytest.raises(stdio.StdioBoundaryError, match='HANDOFF_UNVERIFIED') as unknown:
            streams.close()
        assert unknown.value.retained_owner is streams and len(streams._ends) == 6
        with pytest.raises(stdio.StdioBoundaryError, match='COPY_BINDING_DIFFERS'):
            streams.acknowledge_copy(
                stdio.GuardStdioBinding(
                    descriptor.owner, scope(2), descriptor.io_nonce, uuid4().hex
                )
            )
        streams.acknowledge_closed_scope(closed(scope()))
        streams.release_child_copies()
        assert set(streams._ends) == set(stdio.PARENT_ENDS.values())
    finally:
        streams.acknowledge_closed_scope(closed(scope()))
        streams.close()


def test_copy_ack_is_exact_idempotent_and_does_not_rebind_an_io_resource():
    with stdio.BackendStandardIO(scope()) as streams:
        descriptor = streams.begin_handoff()
        binding = stdio.GuardStdioBinding(
            descriptor.owner, descriptor.scope, descriptor.io_nonce, uuid4().hex
        )
        streams.acknowledge_copy(binding)
        streams.acknowledge_copy(binding)
        with pytest.raises(stdio.StdioBoundaryError, match='CANNOT_REBIND'):
            streams.acknowledge_copy(replace(binding, guard_io_ref=uuid4().hex))
        streams.release_child_copies()
        with streams.parent_endpoint('STDOUT'):
            assert set(streams._ends) == set(stdio.PARENT_ENDS.values())


@pytest.mark.parametrize('value', [None, False, 0, '', 'f' * 16, '0' * 16, '1', 'A' * 16])
def test_private_handle_wire_encoding_is_strict_and_never_accepts_pseudo_handles(value):
    with pytest.raises(stdio.StdioBoundaryError):
        stdio._handle(value)


def test_failed_close_keeps_only_actual_unclosed_endpoints_for_cleanup():
    streams = stdio.BackendStandardIO(scope())
    original = streams._kernel
    first = streams._ends['STDIN_READ']

    def close(handle):
        if handle == first:
            ctypes.set_last_error(5)
            return False
        return original.CloseHandle(handle)

    streams._kernel = SimpleNamespace(CloseHandle=close)
    try:
        with pytest.raises(stdio.StdioBoundaryError) as error:
            streams.close()
        assert error.value.retained_owner is streams
        assert streams._ends == {'STDIN_READ': first}
    finally:
        streams._kernel = original
        streams.close()


def test_job_attribute_builder_rejects_nonstdio_shape_job_handle_and_noninheritable_handles():
    with OwnedJob(active_process_limit=8, job_memory_limit_bytes=128 * 1024 * 1024) as job:
        for values in ([], (1,), (True, 2, 3), (1, 1, 2)):
            with pytest.raises(JobBoundaryError, match='STDIO_HANDLE_LIST_INVALID'):
                with job.process_creation_attributes(stdio_handles=values):
                    pytest.fail('No invalid inherited set')
        with stdio.BackendStandardIO(scope()) as streams:
            original = tuple(streams._ends[name] for name in stdio.CHILD_ENDS)
            with pytest.raises(JobBoundaryError, match='STDIO_INHERITANCE_UNVERIFIED'):
                with job.process_creation_attributes(stdio_handles=original):
                    pytest.fail('Backend originals stay noninheritable')
            with pytest.raises(JobBoundaryError, match='JOB_HANDLE_MUST_NOT_BE_INHERITED'):
                with job.process_creation_attributes(
                    stdio_handles=(job._handle, original[1], original[2])
                ):
                    pytest.fail('Never inherit Job control')


@pytest.fixture
def peer(tmp_path):
    yield from owned_stdio_peer(tmp_path)


def owned_stdio_peer(tmp_path, *, bound_version=False):
    if bound_version:
        with (tmp_path / 'bound-controller-epoch').open('x', encoding='ascii') as stream:
            stream.write(str(uuid4()))
    nonce = uuid4().hex
    with (tmp_path / '.stdio-owner').open('x', encoding='ascii') as stream:
        stream.write(nonce)
    worker = ROOT / 'backend/tests/infrastructure/v20_stdio_worker.py'
    code = '\n'.join(
        (
            'import runpy,sys',
            'sys.path.insert(0,' + repr(str(ROOT)) + ')',
            'sys.argv=' + repr([str(worker), str(tmp_path), nonce]),
            'runpy.run_path(' + repr(str(worker)) + ',run_name="__main__")',
        )
    )
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    root = None
    retained = {}
    try:
        root = TestSuspendedRoot(job, tmp_path, code)
        root.resume()
        wait_file(tmp_path / 'stdio-ready.json')
        packet = json.loads((tmp_path / 'stdio-ready.json').read_bytes())
        assert packet['nonce'] == nonce
        source = ObservedProcess(packet['pid'])
        retained[source.identity.pid] = source
        assert job.contains_process(source)
        for pid in job.observe_members().process_ids:
            if pid not in retained:
                held = ObservedProcess(pid)
                assert job.contains_process(held)
                retained[pid] = held
        raw = packet['descriptor']
        descriptor = stdio.ChildStdioDescriptor(
            NativeProcessIdentity(**raw['owner']),
            LaunchScope(**raw['scope']),
            raw['io_nonce'],
            raw['stdin_handle'],
            raw['stdout_handle'],
            raw['stderr_handle'],
        )
        assert descriptor.owner == source.identity
        if os.environ.get('WALLE_TEST_CONTROLLER_POSITIVE') == '1':
            assert not source.identity.is_appcontainer and not source.identity.is_elevated
        elif source.identity.is_appcontainer or source.identity.is_elevated:
            pytest.skip('Guard pipe copy needs approved ordinary non-AppContainer peer')
        yield source, descriptor, packet, tmp_path
    finally:
        job.terminate_owned(1)
        for held in retained.values():
            assert held._kernel.WaitForSingleObject(held._handle, 8000) == 0
        if root is not None:
            assert job._kernel.WaitForSingleObject(root.info.process, 8000) == 0
        deadline = monotonic() + 8
        while job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        assert job.observe_members().complete and not job.observe_members().process_ids
        for held in retained.values():
            held.close()
        if root is not None:
            root.close()
        job.close()


def test_guard_copies_only_original_owner_child_pipes_and_never_a_file_or_opposite_direction(peer):
    source, descriptor, packet, _ = peer
    with ControllerPrimaryToken(source, expected=source.identity) as controller:
        with stdio.GuardStandardIO(controller, descriptor, scope=scope()) as copy:
            assert copy.binding.owner == descriptor.owner
            with copy.creation_handles() as handles:
                assert len(set(handles)) == 3
                for name, handle in zip(stdio.CHILD_ENDS, handles, strict=True):
                    stdio._verify_pipe(copy._kernel, copy._native, handle, name, inheritable=True)
        for bad in (
            replace(descriptor, stdin_handle=packet['file_handle']),
            replace(
                descriptor,
                stdin_handle=descriptor.stdout_handle,
                stdout_handle=descriptor.stdin_handle,
            ),
        ):
            with pytest.raises(stdio.StdioBoundaryError):
                stdio.GuardStandardIO(controller, bad, scope=scope())
        with patch.object(stdio, '_api', side_effect=AssertionError('No foreign scope duplicate')):
            with pytest.raises(stdio.StdioBoundaryError, match='OWNER_OR_SCOPE_DIFFERS'):
                stdio.GuardStandardIO(
                    controller, replace(descriptor, scope=scope(2)), scope=scope()
                )


def test_real_suspended_root_gets_only_stdio_and_job_attributes_not_an_extra_inheritable_object(
    peer,
):
    source, descriptor, _, directory = peer
    child_job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    root = None
    kernel = child_job._kernel
    kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    event_name = 'Local\\walle-stdio-unlisted-' + uuid4().hex
    extra = kernel.CreateEventW(None, True, False, event_name)
    assert extra and kernel.SetHandleInformation(extra, 1, 1)
    code = '\n'.join(
        (
            'import ctypes,os,json',
            'from pathlib import Path',
            'from ctypes import wintypes',
            'k=ctypes.WinDLL("kernel32",use_last_error=True)',
            'k.OpenEventW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]',
            'k.OpenEventW.restype=wintypes.HANDLE',
            'base=ctypes.WinDLL("kernelbase",use_last_error=True)',
            'base.CompareObjectHandles.argtypes=[wintypes.HANDLE,wintypes.HANDLE]',
            'base.CompareObjectHandles.restype=wintypes.BOOL',
            'k.GetCurrentProcess.restype=wintypes.HANDLE',
            'k.DuplicateHandle.argtypes=[wintypes.HANDLE,wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]',
            'k.DuplicateHandle.restype=wintypes.BOOL',
            'k.CloseHandle.argtypes=[wintypes.HANDLE]',
            'proof={"phase":"EVENT_SNAPSHOT","completed":False}',
            'try:',
            '    snapshot=wintypes.HANDLE()',
            # Snapshot BEFORE OpenEvent can reuse the same numeric slot in a child.
            '    existed=bool(k.DuplicateHandle(k.GetCurrentProcess(),'
            + str(extra)
            + ',k.GetCurrentProcess(),ctypes.byref(snapshot),0,False,2))',
            '    proof["extra_preexisting"]=existed',
            '    opened=k.OpenEventW(0x100000,False,' + repr(event_name) + ')',
            '    assert opened',
            '    matched=bool(existed and base.CompareObjectHandles(snapshot,opened))',
            '    proof["same_event"]=matched',
            '    if existed: k.CloseHandle(snapshot)',
            '    k.CloseHandle(opened)',
            '    assert not matched',
            '    proof["phase"]="STDIN"',
            '    incoming=os.read(0,3)',
            '    proof["input_length"]=len(incoming)',
            '    assert incoming==b"inp"',
            '    proof["phase"]="STDOUT"',
            '    os.write(1,b"OUT")',
            '    os.write(2,b"ERR")',
            '    proof["completed"]=True',
            'except BaseException as error:',
            '    proof["error"]=type(error).__name__',
            '    proof["native_error"]=ctypes.get_last_error()',
            '    raise',
            'finally:',
            '    with Path("root-proof.tmp").open("x",encoding="utf-8") as stream:',
            '        json.dump(proof,stream)',
            '        stream.flush()',
            '        os.fsync(stream.fileno())',
            '    os.replace("root-proof.tmp","root-proof.json")',
        )
    )
    try:
        with ControllerPrimaryToken(source, expected=source.identity) as controller:
            with stdio.GuardStandardIO(controller, descriptor, scope=scope()) as copy:
                # Private ACK fixture, not production Pipe authentication.
                publish(directory / 'copy-ack.json', asdict(copy.binding))
                wait_file(directory / 'copy-released.json')
                with copy.creation_handles() as handles:
                    root = TestSuspendedRoot(child_job, directory, code, stdio_handles=handles)
                assert root.pid in child_job.observe_members().process_ids
                assert not (directory / 'stdio-result.json').exists()
                (directory / 'run-reader').open('x').close()
                root.resume()
                assert kernel.WaitForSingleObject(root.info.process, 8000) == 0
                code = wintypes.DWORD()
                assert kernel.GetExitCodeProcess(root.info.process, ctypes.byref(code))
                proof_path = directory / 'root-proof.json'
                proof = json.loads(proof_path.read_bytes()) if proof_path.exists() else None
                assert code.value == 0, (code.value, proof)
                assert proof is not None and proof['completed'] and not proof['same_event']
                wait_file(directory / 'stdio-result.json')
                assert json.loads((directory / 'stdio-result.json').read_bytes()) == {
                    'STDOUT': 'OUT',
                    'STDERR': 'ERR',
                }
    finally:
        child_job.terminate_owned(1)
        if root is not None:
            assert kernel.WaitForSingleObject(root.info.process, 8000) == 0
            root.close()
        deadline = monotonic() + 8
        while child_job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        assert not child_job.observe_members().process_ids
        child_job.close()
        assert kernel.CloseHandle(extra)
