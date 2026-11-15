"""Explicitly authorized SYSTEM bootstrap probe; administrator approval remains interactive.

This driver uses the real fixed installer and real backend. It cannot admit WFP,
TASK/CHECK_DRIVER or models, repair existing resources, or update user services.
"""

import argparse
import ctypes
import os
import subprocess
from contextlib import ExitStack
from ctypes import wintypes
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from backend.app.infrastructure.deployment_manifest import absolute_path, digest
from backend.app.infrastructure.guard_service_diagnostics import decode_service_diagnostic
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.app.infrastructure.windows_process import ObservedProcess, _creation_time, _image_path
from backend.app.infrastructure.windows_process import _api as process_api
from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_json_object
from backend.tests.infrastructure.v20_backend_guard_probe_worker import finish, launch, read_ready
from tools.quality_gate import environment, stop_owned
from tools.windows_guard_inspection import GuardBootstrapSources
from tools.windows_guard_install_contract import INSTALLER_POLICY, verify_installation_request
from tools.windows_guard_installation import require_backend_reader
from tools.windows_program_package import write_new_verified_file


class ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ('size', wintypes.DWORD),
        ('mask', wintypes.DWORD),
        ('window', wintypes.HWND),
        ('verb', wintypes.LPCWSTR),
        ('file', wintypes.LPCWSTR),
        ('parameters', wintypes.LPCWSTR),
        ('directory', wintypes.LPCWSTR),
        ('show', ctypes.c_int),
        ('instance', wintypes.HINSTANCE),
        ('id_list', wintypes.LPVOID),
        ('class_name', wintypes.LPCWSTR),
        ('class_key', wintypes.HKEY),
        ('hot_key', wintypes.DWORD),
        ('icon_or_monitor', wintypes.HANDLE),
        ('process', wintypes.HANDLE),
    ]


class AdministratorAction:
    """Hold the original ShellExecute process handle; never terminate by guessed PID."""

    def __init__(self, program, arguments, cwd):
        if type(program) is not ProgramPackageLease or program.policy != INSTALLER_POLICY:
            raise RuntimeError('Original dedicated installer lease required')
        program.verify()
        self._kernel, _ = process_api()
        self._handle = None
        self._close_failed = False
        if ctypes.sizeof(ShellExecuteInfo) != 112:
            raise RuntimeError('Unsupported native elevation layout')
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
        shell.ShellExecuteExW.restype = wintypes.BOOL
        ole = ctypes.WinDLL('ole32', use_last_error=True)
        ole.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
        ole.CoInitializeEx.restype = ctypes.c_long
        ole.CoUninitialize.argtypes = []
        ole.CoUninitialize.restype = None
        initialized = ole.CoInitializeEx(None, 2)
        if initialized not in (0, 1):
            raise RuntimeError('Native administrator launcher initialization rejected')
        try:
            info = ShellExecuteInfo()
            info.size = ctypes.sizeof(info)
            info.mask = 0x140  # NOCLOSEPROCESS | NOASYNC; explicit EXE, no shell text.
            info.verb = 'runas'
            info.file = str(program.root / INSTALLER_POLICY.entry_name)
            info.parameters = subprocess.list2cmdline(arguments)
            info.directory = str(cwd)
            info.show = 0
            ctypes.set_last_error(0)
            accepted = shell.ShellExecuteExW(ctypes.byref(info))
            native_error = ctypes.get_last_error()
            self._handle = info.process
            if not accepted or not self._handle:
                raise RuntimeError(
                    'WINDOWS_ADMINISTRATOR_LAUNCH_REJECTED '
                    f'native_error={native_error} accepted={bool(accepted)} '
                    f'original_handle={bool(self._handle)}'
                )
            self.pid = self._kernel.GetProcessId(self._handle)
            self.created = _creation_time(self._kernel, self._handle)
            if (
                not self.pid
                or absolute_path(_image_path(self._kernel, self._handle))
                != program.root / INSTALLER_POLICY.entry_name
            ):
                raise RuntimeError('Original administrator process differs')
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            raise
        finally:
            ole.CoUninitialize()

    def poll(self):
        if self._handle is None or self._close_failed:
            raise RuntimeError('Administrator action original owner unavailable')
        result = self._kernel.WaitForSingleObject(self._handle, 0)
        if result == 258:
            return None
        if result != 0:
            raise RuntimeError('Administrator action original wait unverified')
        code = wintypes.DWORD()
        if not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            raise RuntimeError('Administrator action exit unavailable')
        return code.value

    def wait(self, timeout):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            result = self.poll()
            if result is not None:
                return result
            sleep(0.1)
        error = RuntimeError('Administrator action still running; no retry or guessed termination')
        error.retained_owner = self
        raise error

    def close(self):
        if self._close_failed:
            error = RuntimeError('Administrator original handle closure previously unverified')
            error.retained_owner = self
            raise error
        if self._handle is not None:
            if not self._kernel.CloseHandle(self._handle):
                self._close_failed = True
                error = RuntimeError('Administrator original handle closure unverified')
                error.retained_owner = self
                raise error
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.close()


def inspect_service(
    request, *, expected_state, allow_never_started=False, require_never_started=False
):
    from tools.windows_guard_install_service import _ServiceStatusProcess, service_api

    api = service_api()
    manager = api.OpenSCManagerW(None, None, 1)
    if not manager:
        raise RuntimeError('Original SCM unavailable')
    service = None
    try:
        service = api.OpenServiceW(manager, request['service']['name'], 4)
        if expected_state is None:
            if service or ctypes.get_last_error() != 1060:
                raise RuntimeError('Installation requires the exact new absent service')
            return
        if not service:
            raise RuntimeError('Original installed service unavailable')
        status, needed = _ServiceStatusProcess(), wintypes.DWORD()
        if not api.QueryServiceStatusEx(
            service, 0, ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(needed)
        ):
            raise RuntimeError('Original service status unavailable')
        diagnostic = decode_service_diagnostic(status.win32_exit_code, status.service_exit_code)
        print(
            f'GUARD_READ_ONLY_STATUS state={status.state} pid={status.pid} '
            f'win32={status.win32_exit_code} specific={status.service_exit_code} '
            f'stage={diagnostic.stage.name if diagnostic else "UNCLASSIFIED"} '
            f'reason={diagnostic.reason.name if diagnostic else "UNCLASSIFIED"} '
            f'native={diagnostic.native_error if diagnostic and diagnostic.native_error else "UNAVAILABLE"}',
            flush=True,
        )
        if status.service_type != 16 or status.state != expected_state or status.flags != 0:
            raise RuntimeError('Original service state differs')
        allowed_exit_codes = (0, 1077) if allow_never_started else (0,)
        if expected_state == 1 and (
            status.pid
            or status.win32_exit_code not in allowed_exit_codes
            or status.service_exit_code
        ):
            raise RuntimeError('Original service did not stop cleanly')
        if require_never_started and (
            status.state != 1
            or status.pid != 0
            or status.win32_exit_code != 1077
            or status.service_exit_code != 0
        ):
            raise RuntimeError('Continuation requires the original never-started service')
    finally:
        if service and not api.CloseServiceHandle(service):
            raise RuntimeError('Original service query handle closure unverified')
        if not api.CloseServiceHandle(manager):
            raise RuntimeError('Original SCM query handle closure unverified')


def verify_ready(channel, action):
    ready = channel / 'READY'
    try:
        ready.lstat()
    except FileNotFoundError:
        return False
    with LockedFileSource(ready, max_file_bytes=4096) as source:
        value = exact(strict_json_object(source.snapshot.raw), ('pid', 'created_at'))
        if (
            type(value['pid']) is not int
            or not 1 <= value['pid'] <= 0xFFFFFFFF
            or _bytes(value) != source.snapshot.raw
        ):
            raise RuntimeError('Original SYSTEM probe readiness invalid')
        created = value['created_at']
        if (
            type(created) is not str
            or len(created) != 16
            or any(char not in '0123456789abcdef' for char in created)
            or created == '0' * 16
            or action.poll() is not None
        ):
            raise RuntimeError('Original startup coordinator readiness differs')
        # A READY marker only coordinates the probe. The real ordinary backend
        # independently opens and verifies the original SYSTEM process and pipe.
    return True


def report_guard_identity_failure(installation_ref):
    from backend.app.infrastructure.windows_guard_service import _GuardServiceStatus

    try:
        with _GuardServiceStatus(installation_ref) as service:
            pid = service.running_pid()
            with ObservedProcess(pid) as original:
                value = original.observe()
                if value.identity.pid != service.running_pid():
                    raise RuntimeError('Original diagnostic SCM process changed')
                print(
                    'READ_ONLY_GUARD_IDENTITY_DIAGNOSTIC',
                    value.state,
                    'system',
                    value.identity.user_sid == 'S-1-5-18',
                    'elevated',
                    value.identity.is_elevated,
                    flush=True,
                )
    except (OSError, RuntimeError, ValueError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        print(
            'READ_ONLY_GUARD_IDENTITY_DIAGNOSTIC_REJECTED',
            type(error).__name__,
            'code',
            getattr(error, 'code', None),
            'native',
            getattr(error, 'native_error', None),
            flush=True,
        )


def run_peer(request, temporary):
    root = absolute_path(request['installation_root'])
    command = [
        str(root / 'backend' / 'walle-backend.exe'),
        '--verify-guard',
        '--program-sha256',
        request['programs']['backend']['manifest_sha256'],
        '--guard-package',
        str(root / 'guard'),
        '--guard-sha256',
        request['programs']['guard']['manifest_sha256'],
        '--installation-ref',
        request['installation_ref'],
    ]
    process = subprocess.Popen(
        command,
        cwd=temporary,
        env=environment(temporary),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        output, _ = process.communicate(timeout=100)
        if process.returncode or b'BACKEND_GUARD_PROCESS_AND_PIPE_VERIFIED' not in output:
            print('ACTUAL_ORDINARY_BACKEND_PROBE_EXIT', process.returncode, flush=True)
            report_guard_identity_failure(request['installation_ref'])
            raise RuntimeError('Actual ordinary backend Guard probe rejected; no admission granted')
        print('ACTUAL_ORDINARY_BACKEND_SYSTEM_GUARD_PROCESS_AND_PIPE_PASSED', flush=True)
    finally:
        if process.poll() is None:
            stop_owned(process)


def execute(values):
    with ObservedProcess(os.getpid()) as original:
        if original.identity.is_elevated or original.identity.is_appcontainer:
            raise RuntimeError('The integration supervisor must stay ordinary')
    with (
        ProgramPackageLease(
            values.installer, expected_sha256=values.installer_sha256, policy=INSTALLER_POLICY
        ) as program,
        LockedFileSource(values.request, max_file_bytes=256 * 1024) as source,
        TemporaryDirectory(prefix='we-system-bootstrap-') as temporary,
        ExitStack() as originals,
    ):
        if source.snapshot.sha256 != digest(values.request_sha256):
            raise RuntimeError('Original request digest differs')
        header = strict_json_object(source.snapshot.raw)
        bootstrap = exact(header.get('bootstrap'), ('root', 'plan_sha256'))
        request_program_sha = program.spec.manifest_sha256
        if values.original_installer_package is not None:
            original_program = originals.enter_context(
                ProgramPackageLease(
                    values.original_installer_package,
                    expected_sha256=digest(header.get('installer_program_sha256')),
                    policy=INSTALLER_POLICY,
                )
            )
            request_program_sha = original_program.spec.manifest_sha256
            if request_program_sha == program.spec.manifest_sha256:
                raise RuntimeError('Distinct fixed continuation tool required')
        backend_source = exact(header.get('programs'), ('guard', 'backend'))['backend']
        backend = absolute_path(backend_source['root'])
        reader_process = launch(
            backend,
            [
                '--hold-installation-reader',
                '--program-sha256',
                digest(backend_source['manifest_sha256']),
            ],
            temporary,
        )
        try:
            _, pid, created = read_ready(reader_process)
            with (
                ObservedProcess(pid) as reader,
                GuardBootstrapSources(
                    absolute_path(bootstrap['root']),
                    digest(bootstrap['plan_sha256']),
                    reader=reader,
                    allow_existing_target=values.start_stop,
                    timeout_ms=300000,
                ) as inputs,
            ):
                request = verify_installation_request(
                    source.snapshot.raw,
                    source.snapshot.sha256,
                    inputs,
                    request_program_sha,
                )
                require_backend_reader(inputs, reader)
                inputs.verify_parent_access(reader)
                inspect_service(
                    request,
                    expected_state=1 if values.start_stop else None,
                    allow_never_started=True,
                    require_never_started=values.original_installer_package is not None,
                )
                arguments = [
                    '--start-stop' if values.start_stop else '--install',
                    '--program-sha256',
                    program.spec.manifest_sha256,
                    '--request',
                    str(values.request),
                    '--request-sha256',
                    source.snapshot.sha256,
                    '--reader-pid',
                    str(pid),
                    '--reader-created-at',
                    created,
                ]
                if values.original_installer_package is not None:
                    arguments.extend(
                        ['--original-installer-package', str(values.original_installer_package)]
                    )
                if values.start_stop:
                    channel = create_private_package(Path(temporary) / 'probe-channel')
                    write_new_verified_file(
                        channel / 'channel.v1.json',
                        _bytes(
                            {
                                'request_sha256': source.snapshot.sha256,
                                'reader_pid': pid,
                                'reader_created_at': created,
                                'channel_ref': token_hex(32),
                            }
                        ),
                    )
                    arguments.extend(['--probe-channel', str(channel)])
                else:
                    channel = None
                print('REQUESTING_INTERACTIVE_WINDOWS_ADMINISTRATOR_APPROVAL', flush=True)
                with AdministratorAction(program, arguments, temporary) as action:
                    if channel is None:
                        if action.wait(330):
                            raise RuntimeError(
                                'Actual installer rejected; inspect new resources, do not retry'
                            )
                        with LocalPathGuard(inputs._target, directory=True) as newly_created:
                            inputs.bind_new_installation_root(newly_created)
                    else:
                        try:
                            deadline = monotonic() + 240
                            while monotonic() < deadline and not verify_ready(channel, action):
                                if action.poll() is not None:
                                    inspect_service(request, expected_state=1)
                                    raise RuntimeError('Actual SYSTEM Guard startup rejected')
                                if reader.observe().state != 'RUNNING':
                                    raise RuntimeError('Original ordinary reader exited')
                                sleep(0.1)
                            if not verify_ready(channel, action):
                                raise RuntimeError('Actual SYSTEM startup readiness deadline')
                            run_peer(request, temporary)
                        finally:
                            write_new_verified_file(channel / 'STOP', b'STOP\n')
                            if action.wait(200):
                                raise RuntimeError('Original Guard start/stop unverified')
                    inspect_service(
                        request, expected_state=1, allow_never_started=not values.start_stop
                    )
                    program.verify()
                    inputs.verify()
                    source.verify()
                reader_process.stdin.write(b'STOP\n')
                reader_process.stdin.flush()
                reader_process.stdin.close()
                reader_process.stdin = None
                output, _ = reader_process.communicate(timeout=30)
                if reader_process.returncode or reader.observe().state != 'EXITED':
                    raise RuntimeError(('Original ordinary reader cleanup failed', output[-1000:]))
        finally:
            finish(reader_process)
    print('OWNED_BOOTSTRAP_PHASE_COMPLETED_NO_WFP_TASK_MODEL_OR_USER_SERVICE_UPDATE', flush=True)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    phase = parser.add_mutually_exclusive_group(required=True)
    phase.add_argument('--install', action='store_true')
    phase.add_argument('--start-stop', action='store_true')
    parser.add_argument('--allow-system-changes', action='store_true')
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--installer-sha256', required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--original-installer-package', type=Path)
    values = parser.parse_args(arguments)
    if not values.allow_system_changes:
        parser.error(
            'This phase requires explicit current authorization for the pinned new resources'
        )
    if values.original_installer_package is not None:
        if not values.start_stop:
            parser.error('Original installer continuation is only for --start-stop')
        values.original_installer_package = values.original_installer_package.resolve(strict=True)
    values.installer = values.installer.resolve(strict=True)
    values.request = values.request.resolve(strict=True)
    execute(values)


if __name__ == '__main__':
    main()
