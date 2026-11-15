"""Explicit real prepared Guard binary checks; no service registration or SYSTEM role."""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.program_manifest import GUARD_PROGRAM_POLICY
from backend.app.infrastructure.program_package import ProgramPackageLease
from tools.quality_gate import environment, stop_owned


def execute(command, values, cwd, timeout=120):
    process = subprocess.Popen(
        command, cwd=cwd, env=values, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output
    finally:
        if process.poll() is None:
            stop_owned(process)


def exercise(package, digest):
    raw = (package / GUARD_PROGRAM_POLICY.manifest_name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    with (
        ProgramPackageLease(package, expected_sha256=digest, policy=GUARD_PROGRAM_POLICY) as held,
        TemporaryDirectory(prefix='we-guard-executable-') as temporary,
    ):
        target = Path(temporary)
        values = environment(temporary)
        image = str(package / held.spec.entry)
        probes = (
            (['--verify-runtime'], 0, b'GUARD_RUNTIME_VERIFIED'),
            (['--verify-package', '--program-sha256', digest], 0, b'GUARD_PACKAGE_VERIFIED'),
            (['--verify-package', '--program-sha256', 'b' * 64], 1, b'GUARD_PROGRAM_REJECTED'),
            (['--verify-package'], 2, b'--program-sha256'),
            (['--verify-runtime', '--installation-ref', 'a' * 64], 2, b'--program-sha256'),
            (
                [
                    '--program-sha256',
                    digest,
                    '--installation-ref',
                    'a' * 64,
                    '--manifest',
                    str(target / 'not-created-deployment.json'),
                    '--sha256',
                    'b' * 64,
                ],
                1,
                b'',
            ),
        )
        for arguments, expected, marker in probes:
            code, output = execute([image, *arguments], values, temporary)
            assert code == expected, ('guard executable exit', arguments[0], code, output[-2000:])
            assert marker in output, ('guard executable marker', arguments[0], output[-2000:])
        held.verify()
        assert not (target / 'not-created-deployment.json').exists()
        assert (package / GUARD_PROGRAM_POLICY.manifest_name).read_bytes() == raw
        print(
            'FROZEN_GUARD_PROGRAM_CHECKED probes=6 original_package_bytes_verified '
            'no_service_installed no_system_role',
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    values = parser.parse_args()
    exercise(values.package.resolve(strict=True), values.sha256)


if __name__ == '__main__':
    main()
