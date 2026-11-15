"""Exercise actual frozen backend probes and original-reader parent checks; no installation."""

import argparse
import ctypes
import hashlib
import msvcrt
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from backend.app.infrastructure.program_manifest import BACKEND_PROGRAM_POLICY
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.windows_process import ObservedProcess
from tools.quality_gate import environment, stop_owned
from tools.windows_backend_guard_probe import _control_api
from tools.windows_guard_inspection import GuardBootstrapSources

_READY = re.compile(rb'BACKEND_INSTALLATION_READER_READY pid=([0-9]+) created=([0-9a-f]{16})')


def read_ready(process, timeout=180):
    kernel = _control_api()
    handle = msvcrt.get_osfhandle(process.stdout.fileno())
    output = bytearray()
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        available = ctypes.c_ulong()
        if kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            if available.value:
                if len(output) + available.value > 65536:
                    raise AssertionError('Owned reader readiness output exceeded limit')
                output.extend(os.read(process.stdout.fileno(), available.value))
                match = _READY.search(output)
                if match:
                    return bytes(output), int(match[1]), match[2].decode('ascii')
        elif ctypes.get_last_error() not in (109, 233):
            raise AssertionError('Owned reader output pipe state unknown')
        if process.poll() is not None:
            remainder, _ = process.communicate(timeout=10)
            raise AssertionError(('Reader exited before readiness', bytes(output) + remainder))
        sleep(0.02)
    raise AssertionError('Frozen backend installation reader did not become ready')


def launch(package, arguments, temporary):
    return subprocess.Popen(
        [str(package / 'walle-backend.exe'), *arguments],
        cwd=temporary,
        env=environment(temporary),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def finish(process):
    if process.stdin is not None:
        process.stdin.close()
        process.stdin = None
    if process.poll() is None:
        stop_owned(process)
    process.communicate(timeout=15)


def exercise(package, digest, prepared, plan_digest, *, timeout_case=False):
    manifest = (package / 'backend-program.v1.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == digest
    with ProgramPackageLease(
        package, expected_sha256=digest, policy=BACKEND_PROGRAM_POLICY
    ) as original:
        original.verify()
    with TemporaryDirectory(prefix='we-frozen-backend-probe-') as temporary:
        process = launch(
            package, ['--hold-installation-reader', '--program-sha256', digest], temporary
        )
        try:
            output, pid, created = read_ready(process)
            assert pid == process.pid
            with ObservedProcess(pid) as reader:
                assert reader.identity.creation_time_hex == created
                assert Path(reader.identity.image_path) == package / 'walle-backend.exe'
                assert not reader.identity.is_appcontainer and not reader.identity.is_elevated
                with GuardBootstrapSources(prepared, plan_digest) as inputs:
                    assert inputs.plan['sources']['backend']['manifest_sha256'] == digest
                    assert inputs.backend.root == package
                    assert inputs.verify_parent_access(reader)
                try:
                    with (package / 'backend-program.v1.json').open('r+b'):
                        pass
                except PermissionError:
                    pass
                else:
                    raise AssertionError(
                        'Actual frozen reader did not retain its package write lock'
                    )
                print('ACTUAL_FROZEN_BACKEND_READER_AND_PARENT_ACCESS_VERIFIED', flush=True)
                if timeout_case:
                    process.wait(timeout=350)
                else:
                    process.stdin.write(b'STOP\n')
                    process.stdin.flush()
                    process.stdin.close()
                    process.stdin = None
                tail, _ = process.communicate(timeout=180)
                output += tail
                assert reader.observe().state == 'EXITED'
                if timeout_case:
                    assert process.returncode == 1
                    assert b'BACKEND_DEPLOYMENT_PROBE_REJECTED' in output
                    print('ACTUAL_FROZEN_BACKEND_READER_DEADLINE_REJECTED_AND_CLOSED', flush=True)
                else:
                    assert process.returncode == 0, output[-4000:]
                    assert b'BACKEND_INSTALLATION_READER_RELEASED' in output
        finally:
            finish(process)

        if not timeout_case:
            for arguments, payload, expected, ready in (
                (['--hold-installation-reader', '--program-sha256', digest], b'RUN\n', 1, True),
                (['--hold-installation-reader', '--program-sha256', 'b' * 64], b'', 1, False),
                (
                    ['--hold-installation-reader', '--program-sha256', digest, '--port', '8000'],
                    b'',
                    2,
                    False,
                ),
            ):
                process = launch(package, arguments, temporary)
                try:
                    output, _ = process.communicate(payload, timeout=180)
                    assert process.returncode == expected, output[-4000:]
                    assert (b'BACKEND_INSTALLATION_READER_READY' in output) is ready
                finally:
                    finish(process)
            print('ACTUAL_FROZEN_BACKEND_INVALID_INPUTS_REJECTED', flush=True)
        assert list(Path(temporary).iterdir()) == [], 'Read-only probe created business data'
    with ProgramPackageLease(
        package, expected_sha256=digest, policy=BACKEND_PROGRAM_POLICY
    ) as original:
        original.verify()
    assert (package / 'backend-program.v1.json').read_bytes() == manifest
    # A writer can now open the original manifest, without changing its content.
    with (package / 'backend-program.v1.json').open('r+b'):
        pass
    print('ORIGINAL_PROGRAM_BYTES_UNCHANGED_READER_RESOURCES_CLOSED_NO_INSTALLATION', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--timeout-case', action='store_true')
    values = parser.parse_args()
    exercise(
        values.package,
        values.sha256,
        values.prepared,
        values.plan_sha256,
        timeout_case=values.timeout_case,
    )


if __name__ == '__main__':
    main()
