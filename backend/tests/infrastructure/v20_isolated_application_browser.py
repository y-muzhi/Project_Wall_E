"""Actual fixed LPAC browser against a new frozen backend and current frontend.

The HTTP service is an explicit ordinary owned test role. This does not claim
formal LPAC SERVICE admission or SYSTEM/WFP installation.
"""

import argparse
import json
import socket
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.guard_backend_program import decode_backend_program_manifest
from backend.tests.infrastructure.v20_frozen_backend_http_worker import exercise
from tools.quality_gate import environment, stop_owned
from tools.windows_browser_package import verify_prepared_package


def verify_backend_bytes(backend, raw, spec):
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_config_source import LockedFileSource
    from backend.app.infrastructure.windows_file_streams import require_default_data_stream

    assert (backend / 'backend-program.v1.json').read_bytes() == raw
    expected = {member.path: member for member in spec.files}
    files = {path.relative_to(backend).as_posix() for path in backend.rglob('*') if path.is_file()}
    directories = {
        path.relative_to(backend).as_posix() for path in backend.rglob('*') if path.is_dir()
    }
    assert files == set(expected) | {'backend-program.v1.json'} and directories == spec.directories
    total = 0
    with LocalPathGuard(backend, directory=True):
        for name, member in expected.items():
            with LockedFileSource(
                backend / name, max_file_bytes=512 * 1024**2, capture_raw=False
            ) as source:
                require_default_data_stream(source._kernel, source._handle, directory=False)
                assert (source.snapshot.sha256, source.snapshot.byte_count) == (
                    member.sha256,
                    member.byte_count,
                )
                total += source.snapshot.byte_count
    return len(expected), total


def inspect_application(backend, expected, browser):
    raw = (backend / 'backend-program.v1.json').read_bytes()
    spec = decode_backend_program_manifest(raw, expected_sha256=expected)
    count, size = verify_backend_bytes(backend, raw, spec)
    verify_prepared_package(browser)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]

    def check(package, target):
        number, identity = target
        with TemporaryDirectory(prefix='we-isolated-app-check-') as temporary:
            values = environment(temporary)
            values['WALLE_TEST_CHECK_BROWSER_PACKAGE'] = str(package)
            values['WALLE_TEST_BROWSER_APPLICATION'] = json.dumps(
                {
                    'port': number,
                    'process': asdict(identity),
                }
            )
            from tempfile import gettempdir

            base = gettempdir()
            values.update(TEMP=base, TMP=base, TMPDIR=base)
            process = subprocess.Popen(
                [
                    sys.executable,
                    '-B',
                    'tools/python-v20.py',
                    'tools/quality_python.py',
                    'backend/tests/infrastructure/test_v20_real_browser_package.py::test_fixed_actual_chromium_in_original_check_driver_lpac[application]',
                    '-q',
                    '-s',
                    '-p',
                    'no:cacheprovider',
                    '--tb=short',
                    '--basetemp',
                    temporary + '/pytest',
                ],
                env=values,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                output, _ = process.communicate(timeout=660)
                print(output.decode('utf-8', 'replace')[:18000], flush=True)
                assert process.returncode == 0, 'Actual isolated browser application failed'
            finally:
                if process.poll() is None:
                    stop_owned(process)

    exercise(backend, expected, port, browser_package=browser, browser_check=check)
    verify_backend_bytes(backend, raw, spec)
    print('ACTUAL_APPLICATION_BYTES_AND_ISOLATED_BROWSER_VERIFIED', count, size, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--browser', type=Path, required=True)
    args = parser.parse_args()
    inspect_application(
        args.backend.resolve(strict=True),
        args.manifest_sha256,
        args.browser.resolve(strict=True),
    )


if __name__ == '__main__':
    main()
