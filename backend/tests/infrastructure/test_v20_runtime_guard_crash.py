"""Actual Guard-host crash: original controller stays alive, no Job handle escapes."""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchScope
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import (
    ObservedProcess,
    NativeProcessIdentity,
    _identity,
)
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.infrastructure.test_v20_windows_stdio import peer, wait_file
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]


def test_guard_process_crash_kills_original_suspended_git_and_restart_seals_original_nonce(peer):
    backend, _, _, directory = peer
    nonce = uuid4().hex
    with (directory / '.guard-proof-owner').open('x', encoding='ascii') as marker:
        marker.write(nonce)
    owner_job = OwnedJob(active_process_limit=32, job_memory_limit_bytes=1024 * 1024 * 1024)
    launcher = None
    retained = {}
    kernel = owner_job._kernel
    try:
        code = (
            'import sys;sys.path.insert(0,' + repr(str(ROOT)) + ');'
            'from backend.tests.infrastructure.v20_guard_crash_worker import main;'
            'main(' + repr(str(directory)) + ',' + repr(nonce) + ')'
        )
        launcher = TestSuspendedRoot(owner_job, directory, code)
        launcher.resume()
        wait_file(directory / 'guard-held-root.json')
        packet = json.loads((directory / 'guard-held-root.json').read_bytes())
        assert packet['nonce'] == nonce
        guard_identity = NativeProcessIdentity(**packet['guard_identity'])
        git_identity = NativeProcessIdentity(**packet['root_identity'])
        guard = ObservedProcess(guard_identity.pid, expected=guard_identity)
        retained[guard.identity.pid] = guard
        git = ObservedProcess(git_identity.pid, expected=git_identity)
        retained[git.identity.pid] = git
        assert owner_job.contains_process(guard) and owner_job.contains_process(git)
        assert git.observe().state == 'RUNNING' and backend.observe().state == 'RUNNING'
        for pid in owner_job.observe_members().process_ids:
            if pid not in retained:
                original = ObservedProcess(pid)
                assert owner_job.contains_process(original)
                retained[pid] = original
        # Only the original Guard process has the inner controlling Job handle.
        # The parent retains QUERY/SYNCHRONIZE process handles, never its Job.
        terminator = kernel.OpenProcess(0x1 | 0x1000 | 0x100000, False, guard.identity.pid)
        assert terminator
        try:
            assert (
                _identity(kernel, guard._security, terminator, guard.identity.pid) == guard.identity
            )
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.TerminateProcess.restype = wintypes.BOOL
            assert kernel.TerminateProcess(terminator, 91)
            assert kernel.WaitForSingleObject(terminator, 8000) == 0
        finally:
            assert kernel.CloseHandle(terminator)
        assert guard.observe().state == 'EXITED' and guard.observe().exit_code == 91
        # Outer Job stays open and no outer termination has been requested yet.
        assert kernel.WaitForSingleObject(git._handle, 8000) == 0
        assert git.observe().state == 'EXITED'
        assert backend.observe().state == 'RUNNING'
        original_scope = LaunchScope(**packet['scope'])
        with LaunchJournal(directory / 'crash-guard-journal') as recovered:
            fence = recovered.inspect(original_scope)
            assert fence.stop_closed and fence.create_state == 'RESOURCE_RECORDED'
            assert fence.resume_state == 'NONE' and fence.resource_ref == packet['resource_ref']

            def forbidden():
                raise AssertionError('No restart/replacement for old Guard nonce')

            assert (
                recovered.dispatch_create(
                    original_scope,
                    packet['input_sha256'],
                    forbidden,
                )
                == fence
            )
            assert (
                recovered.dispatch_resume(
                    original_scope,
                    packet['resource_ref'],
                    forbidden,
                )
                == fence
            )
        # This is actual native crash evidence, not an installed SYSTEM service,
        # protected runtime bundle, task LPAC or whole-product STOP assertion.
    finally:
        owner_job.terminate_owned(1)
        for original in retained.values():
            assert kernel.WaitForSingleObject(original._handle, 8000) == 0
        if launcher is not None:
            assert kernel.WaitForSingleObject(launcher.info.process, 8000) == 0
        deadline = monotonic() + 8
        while owner_job.observe_members().process_ids and monotonic() < deadline:
            sleep(0.01)
        assert owner_job.observe_members().complete and not owner_job.observe_members().process_ids
        for original in retained.values():
            original.close()
        if launcher is not None:
            launcher.close()
        owner_job.close()
