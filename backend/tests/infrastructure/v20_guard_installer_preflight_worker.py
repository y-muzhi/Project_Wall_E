"""Actual frozen installer preflight and ordinary-user refusal; no system writes."""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.v20_backend_guard_probe_worker import finish, launch, read_ready
from tools.quality_gate import environment, stop_owned
from tools.windows_guard_install_contract import INSTALLER_POLICY


def exercise(
    installer, installer_sha, request, request_sha, backend, backend_sha, *, boundaries=False
):
    original_request = request.read_bytes()
    assert hashlib.sha256(original_request).hexdigest() == request_sha
    with (
        ProgramPackageLease(
            installer, expected_sha256=installer_sha, policy=INSTALLER_POLICY
        ) as package,
        TemporaryDirectory(prefix='we-installer-preflight-') as temporary,
    ):
        reader_process = launch(
            backend, ['--hold-installation-reader', '--program-sha256', backend_sha], temporary
        )
        try:
            _, pid, created = read_ready(reader_process)
            with ObservedProcess(pid) as reader:
                assert not reader.identity.is_elevated and not reader.identity.is_appcontainer
                base = [
                    str(installer / INSTALLER_POLICY.entry_name),
                    '--program-sha256',
                    installer_sha,
                    '--request',
                    str(request),
                    '--request-sha256',
                    request_sha,
                    '--reader-pid',
                    str(pid),
                    '--reader-created-at',
                    created,
                ]
                cases = [
                    ('--inspect', [], 0, b'INSTALLATION_REQUEST_INSPECTED'),
                    ('--install', [], 1, b'GUARD_INSTALLATION_REJECTED'),
                ]
                if boundaries:
                    changed_created = created[:-1] + ('1' if created[-1] != '1' else '2')
                    cases = [
                        (
                            '--inspect',
                            ['--reader-created-at', changed_created],
                            1,
                            b'GUARD_INSTALLATION_REJECTED',
                        ),
                        (
                            '--inspect',
                            ['--request-sha256', 'b' * 64],
                            1,
                            b'GUARD_INSTALLATION_REJECTED',
                        ),
                        (
                            '--inspect',
                            ['--program-sha256', 'b' * 64],
                            1,
                            b'GUARD_INSTALLATION_REJECTED',
                        ),
                        ('--inspect', ['--install'], 2, b'not allowed'),
                        ('--start-stop', [], 2, b'private probe channel'),
                        ('--inspect', ['--probe-channel', temporary], 2, b'private probe channel'),
                    ]
                for mode, overrides, result, marker in cases:
                    process = subprocess.Popen(
                        [*base, mode, *overrides],
                        cwd=temporary,
                        env=environment(temporary),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    try:
                        output, _ = process.communicate(timeout=180)
                        assert process.returncode == result and marker in output, (
                            mode,
                            process.returncode,
                            output[-4000:],
                        )
                    finally:
                        if process.poll() is None:
                            stop_owned(process)
                    assert reader.observe().state == 'RUNNING'
                    if boundaries:
                        print(
                            'ACTUAL_FROZEN_INSTALLER_BOUNDARY_REJECTED',
                            mode,
                            overrides[0] if overrides else 'missing-channel',
                            flush=True,
                        )
                    else:
                        print(
                            'ACTUAL_FROZEN_INSTALLER_'
                            + (
                                'INSPECTION_PASSED'
                                if result == 0
                                else 'ORDINARY_INSTALLATION_REJECTED'
                            ),
                            flush=True,
                        )
                if boundaries:
                    surrogate = subprocess.Popen(
                        [sys._base_executable, '-B', '-c', 'import time;time.sleep(180)'],
                        cwd=temporary,
                        env=environment(temporary),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    try:
                        with ObservedProcess(surrogate.pid) as wrong_reader:
                            invalid = [
                                *base,
                                '--inspect',
                                '--reader-pid',
                                str(wrong_reader.identity.pid),
                                '--reader-created-at',
                                wrong_reader.identity.creation_time_hex,
                            ]
                            test = subprocess.Popen(
                                invalid,
                                cwd=temporary,
                                env=environment(temporary),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                            )
                            try:
                                output, _ = test.communicate(timeout=180)
                                assert (
                                    test.returncode == 1
                                    and b'GUARD_INSTALLATION_REJECTED' in output
                                ), output[-2000:]
                            finally:
                                if test.poll() is None:
                                    stop_owned(test)
                            assert wrong_reader.observe().state == 'RUNNING'
                            print(
                                'ACTUAL_FROZEN_INSTALLER_SAME_USER_PYTHON_READER_REJECTED',
                                flush=True,
                            )
                    finally:
                        if surrogate.poll() is None:
                            stop_owned(surrogate)
                        surrogate.communicate(timeout=15)
                reader_process.stdin.write(b'STOP\n')
                reader_process.stdin.flush()
                reader_process.stdin.close()
                reader_process.stdin = None
                tail, _ = reader_process.communicate(timeout=30)
                assert reader_process.returncode == 0, tail[-2000:]
                assert reader.observe().state == 'EXITED'
        finally:
            finish(reader_process)
        package.verify()
        assert request.read_bytes() == original_request
        assert not list(Path(temporary).iterdir()), 'Probe unexpectedly generated business data'
    print('ACTUAL_INSTALLER_AND_BACKEND_SOURCE_BYTES_UNCHANGED_NO_SYSTEM_WRITES', flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ('installer', 'request', 'backend'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--negative-boundaries', action='store_true')
    values = parser.parse_args()
    exercise(
        values.installer.resolve(strict=True),
        values.installer_sha256,
        values.request.resolve(strict=True),
        values.request_sha256,
        values.backend.resolve(strict=True),
        values.backend_sha256,
        boundaries=values.negative_boundaries,
    )


if __name__ == '__main__':
    main()
