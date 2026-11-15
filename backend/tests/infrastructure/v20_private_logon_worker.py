"""Owned ordinary diagnostic controller in a fresh synthetic-credential logon.

The product TASK/CHECK_DRIVER still uses original LPAC/Job creation in the tests.
No candidate code, real credentials, profile load or network logon is used here.
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from backend.app.infrastructure.windows_job import OwnedJob, JobMembers
from backend.app.infrastructure.windows_native_process import StartupInfo, ProcessInfo, _api
from backend.app.infrastructure.windows_controller_token import _read_token
from tools.quality_gate import environment


def run_in_private_logon(source, *, timeout=180):
    kernel, security = _api()
    security.CreateProcessWithLogonW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(StartupInfo),
        ctypes.POINTER(ProcessInfo),
    ]
    security.CreateProcessWithLogonW.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    with (
        TemporaryDirectory(prefix='we-private-logon-') as temporary,
        OwnedJob(active_process_limit=96, job_memory_limit_bytes=4 * 1024**3) as job,
    ):
        output = Path(temporary) / 'temporary-diagnostic-output'
        program = (
            'import sys,os\n'
            f"stream=open({str(output)!r},'xb',buffering=0)\n"
            'os.dup2(stream.fileno(),1);os.dup2(stream.fileno(),2)\n'
            'import io\n'
            "sys.stdout=io.TextIOWrapper(os.fdopen(os.dup(1),'wb',buffering=0),encoding='utf-8',write_through=True)\n"
            'sys.stderr=sys.stdout\n' + source.replace('PRIVATE_LOGON_TEMP', repr(temporary))
        )
        from tools.windows_backend_package import _replace_owned_build_file

        script = Path(temporary) / 'owned-controller.py'
        program = (
            'import sys\nsys.path.insert(0,'
            + repr(str(Path(__file__).resolve().parents[3]))
            + ')\n'
            + program
        )
        _replace_owned_build_file(script, program.encode('utf-8'))
        command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([sys.executable, '-B', str(script)])
        )
        assert len(command) < 1024
        values = environment(temporary)
        block = ctypes.create_unicode_buffer(
            '\0'.join(key + '=' + values[key] for key in sorted(values, key=str.upper)) + '\0\0'
        )
        password = ctypes.create_unicode_buffer(uuid4().hex + uuid4().hex)
        startup = StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.flags = 1
        info = ProcessInfo()
        created = False
        try:
            assert security.CreateProcessWithLogonW(
                'wallecheck-' + uuid4().hex[:12],
                '.',
                password,
                2,
                sys.executable,
                command,
                0x4 | 0x400 | 0x08000000,
                block,
                str(Path(__file__).resolve().parents[3]),
                ctypes.byref(startup),
                ctypes.byref(info),
            ), ctypes.get_last_error()
            created = True
            assert kernel.AssignProcessToJobObject(job._require_handle(), info.process), (
                ctypes.get_last_error()
            )
            token = wintypes.HANDLE()
            assert security.OpenProcessToken(info.process, 8, ctypes.byref(token))
            try:
                identity = _read_token(kernel, security, token)
                assert identity.user_sid not in ('S-1-5-18', 'S-1-5-19', 'S-1-5-20')
            finally:
                assert kernel.CloseHandle(token)
            assert kernel.ResumeThread(info.thread) == 1
            assert kernel.WaitForSingleObject(info.process, timeout * 1000) == 0, (
                'private-logon deadline'
            )
            code = wintypes.DWORD()
            assert kernel.GetExitCodeProcess(info.process, ctypes.byref(code))
            return code.value, output.read_bytes()[
                :64000
            ] if output.exists() else b'NO_DIAGNOSTIC_OUTPUT'
        finally:
            ctypes.memset(ctypes.addressof(password), 0, ctypes.sizeof(password))
            if created:
                job.terminate_owned(0)
                assert kernel.WaitForSingleObject(info.process, 8000) == 0
                assert job.observe_members() == JobMembers((), 0, True)
                assert kernel.CloseHandle(info.thread)
                assert kernel.CloseHandle(info.process)
