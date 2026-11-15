"""Real owned suspended roots and descendant Jobs, no installed Guard or Git run."""

import ctypes
import os
import subprocess
from ctypes import wintypes
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

import pytest

from backend.app.infrastructure import windows_job as jobs
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('reserved', wintypes.LPWSTR),
        ('desktop', wintypes.LPWSTR),
        ('title', wintypes.LPWSTR),
        ('x', wintypes.DWORD),
        ('y', wintypes.DWORD),
        ('x_size', wintypes.DWORD),
        ('y_size', wintypes.DWORD),
        ('x_count', wintypes.DWORD),
        ('y_count', wintypes.DWORD),
        ('fill', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('show', wintypes.WORD),
        ('reserved_size', wintypes.WORD),
        ('reserved_bytes', wintypes.LPVOID),
        ('stdin', wintypes.HANDLE),
        ('stdout', wintypes.HANDLE),
        ('stderr', wintypes.HANDLE),
    ]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [('startup', StartupInfo), ('attributes', wintypes.LPVOID)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [
        ('process', wintypes.HANDLE),
        ('thread', wintypes.HANDLE),
        ('pid', wintypes.DWORD),
        ('tid', wintypes.DWORD),
    ]


class TestSuspendedRoot:
    __test__ = False

    def __init__(
        self,
        job,
        directory,
        code,
        *,
        stdio_handles=(),
        driver_result_handle=None,
        executable=None,
        environment_values=None,
    ):
        kernel = job._kernel
        kernel.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            wintypes.LPVOID,
            ctypes.POINTER(ProcessInfo),
        ]
        kernel.CreateProcessW.restype = wintypes.BOOL
        kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel.ResumeThread.restype = wintypes.DWORD
        self.kernel, self.info = kernel, ProcessInfo()
        values = {
            'SystemRoot': os.environ['SystemRoot'],
            'TEMP': str(directory),
            'TMP': str(directory),
        }
        if environment_values is not None:
            values.update(environment_values)
        environment = ctypes.create_unicode_buffer(
            '\0'.join(key + '=' + str(value) for key, value in sorted(values.items())) + '\0\0'
        )
        executable = executable or str(ROOT / '.venv/Scripts/python.exe')
        command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([executable, '-I', '-u', '-B', '-c', code])
        )
        with job.process_creation_attributes(
            stdio_handles=stdio_handles, driver_result_handle=driver_result_handle
        ) as attributes:
            startup = StartupInfoEx()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.flags = 1
            startup.startup.show = 0
            if stdio_handles:
                startup.startup.flags |= 0x100
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = (
                    stdio_handles
                )
            startup.attributes = attributes
            flags = 0x4 | 0x80000 | 0x400 | 0x08000000
            if not kernel.CreateProcessW(
                executable,
                command,
                None,
                None,
                bool(stdio_handles or driver_result_handle is not None),
                flags,
                environment,
                str(directory),
                ctypes.byref(startup),
                ctypes.byref(self.info),
            ):
                raise ctypes.WinError(ctypes.get_last_error())

    @property
    def pid(self):
        return self.info.pid

    def resume(self):
        assert self.kernel.ResumeThread(self.info.thread) == 1

    def close(self):
        if self.info.thread:
            self.kernel.CloseHandle(self.info.thread)
            self.info.thread = None
        if self.info.process:
            self.kernel.CloseHandle(self.info.process)
            self.info.process = None


def owned_job():
    return jobs.OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)


@pytest.mark.parametrize(
    'count,memory', [(0, 1), (-1, 1), (True, 1), (4097, 1), (1, 0), (1, False), (1, -1)]
)
def test_invalid_resource_limits_fail_before_native_creation(count, memory):
    with patch.object(jobs, '_api', side_effect=AssertionError('No native allocation')):
        with pytest.raises(jobs.JobBoundaryError):
            jobs.OwnedJob(active_process_limit=count, job_memory_limit_bytes=memory)


def test_empty_job_has_actual_limits_no_members_and_closed_handle_is_not_a_recoverable_name():
    with owned_job() as job:
        assert job.verify_limits()
        assert job.observe_members() == jobs.JobMembers((), 0, True)
        with ObservedProcess(os.getpid()) as current:
            assert not job.contains_process(current)
        with pytest.raises(jobs.JobBoundaryError, match='HELD_PROCESS_REQUIRED'):
            job.contains_process(os.getpid())
    with pytest.raises(jobs.JobBoundaryError, match='JOB_HANDLE_CLOSED'):
        job.observe_members()
    with pytest.raises(jobs.JobBoundaryError, match='JOB_HANDLE_CLOSED'):
        with job.process_creation_attributes():
            pytest.fail('No attributes for a closed Job')


def test_atomic_creation_is_already_in_job_and_suspended_before_any_product_code(tmp_path):
    marker = tmp_path / 'started'
    code = (
        'from pathlib import Path; import time; p=Path('
        + repr(str(marker))
        + "); p.open('x').close(); time.sleep(60)"
    )
    with owned_job() as job:
        root = TestSuspendedRoot(job, tmp_path, code)
        try:
            members = job.observe_members()
            assert members.complete and root.pid in members.process_ids
            assert not marker.exists()
            with ObservedProcess(root.pid) as process:
                assert process.observe().state == 'RUNNING'
                # Native termination is a request; observation remains separate.
                job.terminate_owned(123)
                deadline = monotonic() + 5
                while process.observe().state == 'RUNNING' and monotonic() < deadline:
                    sleep(0.01)
                assert process.observe().state == 'EXITED'
                assert process.observe().exit_code == 123
                assert job.observe_members() == jobs.JobMembers((), 0, True)
            assert not marker.exists()
        finally:
            job.close()
            root.close()


def test_last_guard_job_handle_close_kills_root_and_real_spawned_descendants(tmp_path):
    marker = tmp_path / 'tree.ready'
    code = (
        'import os,sys,subprocess,time; '
        "p=subprocess.Popen([sys.executable,'-I','-B','-c','import time; time.sleep(60)'],creationflags=0x08000000); "
        'f=open('
        + repr(str(marker) + '.tmp')
        + ",'x'); f.write(str(p.pid)); f.flush(); os.fsync(f.fileno()); f.close(); "
        'os.rename(' + repr(str(marker) + '.tmp') + ',' + repr(str(marker)) + '); time.sleep(60)'
    )
    with owned_job() as job:
        root = TestSuspendedRoot(job, tmp_path, code)
        try:
            root.resume()
            deadline = monotonic() + 8
            while not marker.exists() and monotonic() < deadline:
                sleep(0.01)
            assert marker.exists()
            descendant_pid = int(marker.read_text(encoding='ascii'))
            with ObservedProcess(root.pid) as parent, ObservedProcess(descendant_pid) as descendant:
                before = job.observe_members()
                assert (
                    before.complete
                    and root.pid in before.process_ids
                    and descendant_pid in before.process_ids
                )
                job.close()
                deadline = monotonic() + 5
                while (
                    parent.observe().state == 'RUNNING' or descendant.observe().state == 'RUNNING'
                ) and monotonic() < deadline:
                    sleep(0.01)
                assert parent.observe().state == descendant.observe().state == 'EXITED'
        finally:
            job.close()
            root.close()


def test_native_lpac_attributes_are_constructible_without_starting_a_process():
    assert jobs.probe_lpac_creation_attributes() is True


def test_lpac_opt_out_refusal_does_not_yield_ordinary_attributes(monkeypatch):
    with jobs.OwnedJob(active_process_limit=1, job_memory_limit_bytes=16 * 1024 * 1024) as job:
        original_update = job._kernel.UpdateProcThreadAttribute

        def update(attributes, flags, kind, *parameters):
            if kind == jobs.ALL_APPLICATION_PACKAGES_POLICY_ATTRIBUTE:
                ctypes.set_last_error(50)
                return False
            return original_update(attributes, flags, kind, *parameters)

        monkeypatch.setattr(job._kernel, 'UpdateProcThreadAttribute', update)
        with pytest.raises(jobs.JobBoundaryError, match='JOB_LPAC_POLICY_OPT_OUT_UNSUPPORTED'):
            with job.process_creation_attributes(lpac_profile='walle-win20-' + 'a' * 32):
                pytest.fail('LPAC refusal must stop the creation path')
        assert job.observe_members() == jobs.JobMembers((), 0, True)
