"""Prepare an unadmitted dedicated RuntimeGuard package; never install or start it."""

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.program_manifest import GUARD_PROGRAM_POLICY
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.runtime_launch_journal import _resource
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from tools.windows_program_package import (
    ProgramBuildError,
    freeze_onedir,
    package_manifest,
    require_build_environment,
    run_owned,
    snapshot_files,
    source_digest,
    validate_program_destination,
    write_new_verified_file,
)

ROOT = Path(__file__).resolve().parents[1]
_EXCLUDED = {'__pycache__', '.pytest_cache'}


def input_files(root):
    files = {}
    git_root = root / 'backend/runtime/git/2.56.0.windows.4/win-x64'
    if not git_root.is_dir():
        raise ProgramBuildError('GUARD_FIXED_GIT_SOURCE_REQUIRED')
    for path in git_root.rglob('*'):
        if path.is_file() or path.is_symlink() or path.is_junction():
            files[path.relative_to(root).as_posix()] = path
    files['backend/resources/code/secret-policies/content20-secrets-1.json'] = (
        root / 'backend/resources/code/secret-policies/content20-secrets-1.json'
    )
    for name in ('backend/app/infrastructure', 'backend/app/shared', 'backend/runtime_guard'):
        directory = root / name
        if not directory.is_dir():
            raise ProgramBuildError('GUARD_SOURCE_DIRECTORY_REQUIRED')
        for path in directory.rglob('*.py'):
            if not any(part in _EXCLUDED for part in path.parts):
                files[path.relative_to(root).as_posix()] = path
    for name in (
        'backend/__init__.py',
        'backend/app/__init__.py',
        'backend/frozen_guard_entry.py',
        'backend/requirements.lock',
        'backend/requirements-build.lock',
        'tools/windows_guard_package.py',
        'tools/windows_program_package.py',
        'tools/build-windows-guard.py',
        'tools/quality_gate.py',
        'docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md',
        'docs/design/v2.0/WALL-E.前端设计文档_V_2.0.md',
    ):
        files[name] = root / name
    return dict(sorted(files.items()))


def verify_package(package, expected_sha256):
    with ProgramPackageLease(
        local_absolute_path(package), expected_sha256=expected_sha256, policy=GUARD_PROGRAM_POLICY
    ) as held:
        return held.spec


def build_guard(root, output, program_ref, *, timeout=900):
    root, output = local_absolute_path(root), local_absolute_path(output)
    _resource(program_ref)
    require_build_environment(root)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise ProgramBuildError('NEW_GUARD_PACKAGE_DIRECTORY_REQUIRED')
    for relative in (
        'backend/app',
        'backend/runtime_guard',
        'backend/resources',
        'backend/runtime',
        'tools',
        'docs',
        'frontend',
    ):
        protected = root / relative
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ProgramBuildError('BUILD_OUTPUT_OVERLAPS_SOURCE')
    with (
        LocalPathGuard(output.parent, directory=True),
        TemporaryDirectory(prefix='.we-g-', dir=output.parent) as temporary,
    ):
        base = Path(temporary)
        snapshot = base / 's'
        snapshot.mkdir()
        original = snapshot_files(input_files(root), snapshot)
        package, environment, _ = freeze_onedir(
            snapshot,
            base,
            name='walle-runtime-guard',
            entry='backend/frozen_guard_entry.py',
            modules=('backend.runtime_guard',),
            data_areas=(
                'backend/runtime/git/2.56.0.windows.4/win-x64',
                'backend/resources/code/secret-policies',
            ),
            timeout=timeout,
            excluded_modules=(
                'sqlite3',
                '_sqlite3',
                'backend.app.infrastructure.database',
                'backend.app.code_tasks',
                'backend.app.service',
            ),
        )
        code, output_text = run_owned(
            [str(package / GUARD_PROGRAM_POLICY.entry_name), '--verify-runtime'],
            cwd=base / 'tmp',
            environment=environment,
            timeout=60,
        )
        marker = b'GUARD_RUNTIME_VERIFIED protocol=WIN20-ISOLATION-1 no_service_started'
        if code or marker not in output_text:
            print(output_text[-5000:].decode('utf-8', 'replace'))
            raise ProgramBuildError('FROZEN_GUARD_RUNTIME_NOT_VERIFIED')
        raw, digest, count, size = package_manifest(
            package, program_ref, policy=GUARD_PROGRAM_POLICY
        )
        spec = validate_program_destination(output, raw, digest, policy=GUARD_PROGRAM_POLICY)
        if any(
            member.path.casefold() in ('_internal/sqlite3.dll', '_internal/_sqlite3.pyd')
            for member in spec.files
        ):
            raise ProgramBuildError('GUARD_BUSINESS_DATABASE_RUNTIME_FORBIDDEN')
        write_new_verified_file(package / GUARD_PROGRAM_POLICY.manifest_name, raw)
        with ProgramPackageLease(
            package, expected_sha256=digest, policy=GUARD_PROGRAM_POLICY
        ) as held:
            held.verify()
        code, output_text = run_owned(
            [
                str(package / GUARD_PROGRAM_POLICY.entry_name),
                '--verify-package',
                '--program-sha256',
                digest,
            ],
            cwd=base / 'tmp',
            environment=environment,
            timeout=120,
        )
        if code or b'GUARD_PACKAGE_VERIFIED no_service_started no_os_admission' not in output_text:
            print(output_text[-5000:].decode('utf-8', 'replace'))
            raise ProgramBuildError('FROZEN_GUARD_PACKAGE_NOT_VERIFIED')
        if snapshot_files(input_files(root)) != original:
            raise ProgramBuildError('GUARD_BUILD_SOURCE_CHANGED')
        if output.exists() or output.is_symlink() or output.is_junction():
            raise ProgramBuildError('NEW_GUARD_PACKAGE_DIRECTORY_REQUIRED')
        os.rename(package, output)
        return digest, source_digest(original), count, size


def main(arguments=None):
    parser = argparse.ArgumentParser(description='Prepare or inspect a fixed local Guard package.')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--program-ref')
    parser.add_argument('--verify-package', type=Path)
    parser.add_argument('--sha256')
    values = parser.parse_args(arguments)
    try:
        if values.verify_package is not None:
            if values.output is not None or values.program_ref is not None or values.sha256 is None:
                parser.error('Package inspection needs only a fixed package and digest')
            spec = verify_package(values.verify_package, values.sha256)
            print('GUARD_PACKAGE_BYTES_VERIFIED', spec.program_ref, spec.manifest_sha256)
        else:
            if values.output is None or values.program_ref is None or values.sha256 is not None:
                parser.error('Preparation needs a new output directory and fixed program reference')
            digest, sources, count, size = build_guard(
                values.source_root, values.output, values.program_ref
            )
            print(
                f'GUARD_PACKAGE_PREPARED manifest={digest} sources={sources} '
                f'members={count} bytes={size}'
            )
        print('INSTALLATION_AND_OS_ADMISSION_NOT_PERFORMED')
        return 0
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        print('GUARD_PACKAGE_PREPARATION_REJECTED')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
