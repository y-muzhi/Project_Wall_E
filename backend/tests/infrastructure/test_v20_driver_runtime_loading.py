"""Read-only runtime probes under an original suspended LPAC, without extra capabilities."""

import ctypes
import os
import shutil
import sys

import pytest
from pathlib import Path

from backend.app.infrastructure.windows_local_paths import _api as file_api
from backend.app.infrastructure.windows_lpac_token import LpacProcessToken
from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
    controller,
    lpac_scope,
    ordinary_controller,
    suspended_lpac,
    tmp_path,
)


def test_original_lpac_can_read_execute_copied_python_and_required_system_libraries(suspended_lpac):
    directories, job, profile, info, pin = suspended_lpac
    base = Path(sys.base_prefix)
    runtime = directories.root / 'runtime'
    copied = []
    for name in (
        'python313.dll',
        'python3.dll',
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'zlib.dll',
    ):
        source = base / name
        if source.is_file():
            target = runtime / name
            shutil.copyfile(source, target)
            copied.append(target)
    system = Path(os.environ['SystemRoot']) / 'System32'
    libraries = [
        system / name
        for name in (
            'ntdll.dll',
            'kernel32.dll',
            'kernelbase.dll',
            'advapi32.dll',
            'version.dll',
            'ws2_32.dll',
            'bcrypt.dll',
            'ucrtbase.dll',
        )
    ]
    paths = [pin.path, *copied, *libraries]
    kernel = file_api()
    rows = []

    def inspect():
        for path in paths:
            handle = kernel.CreateFileW(str(path), 0x001200A9, 7, None, 3, 0x02200000, None)
            if not handle or handle == ctypes.c_void_p(-1).value:
                rows.append((path.name, False, ctypes.get_last_error()))
            else:
                assert kernel.CloseHandle(handle)
                rows.append((path.name, True, 0))

    token = LpacProcessToken(info, job, profile, pin)
    try:
        token.with_restricted_token(inspect)
    finally:
        token.close()
    print('LPAC_RUNTIME_READ_EXECUTE', rows)
    assert len(rows) == len(paths)
    assert all(allowed for _, allowed, _ in rows), rows


@pytest.mark.parametrize('suspended_lpac', ['base_runtime_debug'], indirect=True)
def test_zero_capability_runtime_retains_actual_bounded_startup_evidence(suspended_lpac):
    from backend.tests.infrastructure.v20_owned_debug_events import (
        collect_owned_startup,
        probe_activation_contexts,
    )

    directories, job, profile, info, pin = suspended_lpac
    token = LpacProcessToken(info, job, profile, pin)
    try:
        token.verify()
        print(
            'LPAC_RUNTIME_ACTIVATION',
            probe_activation_contexts(token, directories.root / 'runtime'),
        )
    finally:
        token.close()
    trace = collect_owned_startup(info, job)
    print('LPAC_RUNTIME_STARTUP', trace)
    # This diagnostic distinguishes host support from verified failure evidence.
    # Actual positive driver-frame acceptance is required separately, without skip.
    assert trace.exit_code in (91, 0xC0000022), trace
    if trace.exit_code == 0xC0000022:
        assert any('BasepSxsCreateStreams' in message for message in trace.messages), trace
    else:
        assert not trace.stderr, trace


@pytest.mark.parametrize('suspended_lpac', ['base_runtime_registry_read_debug'], indirect=True)
def test_explicit_capability_is_exactly_verified_and_keeps_private_files_denied(
    suspended_lpac, tmp_path
):
    from backend.app.infrastructure.windows_lpac_token import LpacTokenError
    from backend.tests.infrastructure.v20_owned_debug_events import collect_owned_startup

    directories, job, profile, info, pin = suspended_lpac
    # An unconfigured caller must continue rejecting this broader token.
    with pytest.raises(LpacTokenError, match='ORIGINAL_LPAC_TOKEN_CAPABILITIES_DIFFERS'):
        LpacProcessToken(info, job, profile, pin)
    from backend.app.infrastructure.windows_private_package import create_private_package
    from backend.tests.infrastructure.v20_owned_debug_events import probe_activation_contexts

    protected = create_private_package(tmp_path / 'protected-host-data') / 'not-for-driver.txt'
    with protected.open('xb') as stream:
        stream.write(b'private fixture; never read by the child')
    token = LpacProcessToken(info, job, profile, pin, capability_names=('registryRead',))
    try:
        token.verify()
        activation = probe_activation_contexts(token, directories.root / 'runtime')
        print('LPAC_EXPLICIT_POLICY_ACTIVATION', activation)
        assert all(row[2] for row in activation), activation

        def require_denied():
            kernel = file_api()
            for desired in (0x00120089, 0x00120116):
                handle = kernel.CreateFileW(str(protected), desired, 7, None, 3, 0, None)
                if handle and handle != ctypes.c_void_p(-1).value:
                    kernel.CloseHandle(handle)
                    raise AssertionError('Explicit OS read capability exposed private host file')
                assert ctypes.get_last_error() == 5

        token.with_restricted_token(require_denied)
    finally:
        token.close()
    trace = collect_owned_startup(info, job)
    print('LPAC_REGISTRY_READ_DIAGNOSTIC_STARTUP', trace)
    assert trace.exit_code == 91, trace


def test_minimal_driver_runtime_can_run_fixed_command_without_development_search_path(tmp_path):
    import subprocess

    from backend.tests.infrastructure.v20_browser_driver_native_worker import make_runner

    runtime = tmp_path / 'fixed-python'
    runtime.mkdir()
    make_runner(runtime, Path(os.environ['SystemRoot']) / 'System32/findstr.exe')
    environment = {'SystemRoot': os.environ['SystemRoot'], 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run(
        [str(runtime / 'python.exe'), '-I', '-B', '-c', 'raise SystemExit(91)'],
        cwd=runtime,
        env=environment,
        capture_output=True,
        timeout=10,
    )
    assert (result.returncode, result.stdout, result.stderr) == (91, b'', b'')
