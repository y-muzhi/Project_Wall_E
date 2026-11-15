"""Build a dedicated, uninstalled Guard administrative tool from fixed local inputs."""

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from tools.windows_guard_install_contract import INSTALLER_POLICY
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


def input_files(root):
    sources = {}
    for area in ('backend/app/infrastructure', 'backend/app/shared'):
        for path in (root / area).rglob('*.py'):
            if '__pycache__' not in path.parts:
                sources[path.relative_to(root).as_posix()] = path
    for area in ('backend', 'backend/app'):
        sources[area + '/__init__.py'] = root / area / '__init__.py'
    for path in (root / 'tools').glob('windows_guard_install*.py'):
        sources[path.relative_to(root).as_posix()] = path
    for name in (
        'backend/frozen_guard_installer_entry.py',
        'backend/requirements.lock',
        'backend/requirements-build.lock',
        'tools/windows_guard_inspection.py',
        'tools/windows_guard_plan.py',
        'tools/windows_guard_bootstrap.py',
        'tools/windows_program_package.py',
        'tools/windows_guard_installer_package.py',
        'tools/quality_gate.py',
        'docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md',
        'docs/design/v2.0/WALL-E.前端设计文档_V_2.0.md',
    ):
        sources[name] = root / name
    return dict(sorted(sources.items()))


def build(root, output, program_ref):
    root, output = local_absolute_path(root), local_absolute_path(output)
    require_build_environment(root)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise ProgramBuildError('NEW_INSTALLER_PACKAGE_REQUIRED')
    for area in (
        'backend/app',
        'backend/resources',
        'backend/runtime',
        'tools',
        'docs',
        'frontend',
    ):
        source = root / area
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ProgramBuildError('INSTALLER_OUTPUT_OVERLAPS_SOURCE')
    with (
        LocalPathGuard(output.parent, directory=True),
        TemporaryDirectory(prefix='.we-i-', dir=output.parent) as temporary,
    ):
        base = Path(temporary)
        snapshot = base / 's'
        snapshot.mkdir()
        original = snapshot_files(input_files(root), snapshot)
        package, environment, _ = freeze_onedir(
            snapshot,
            base,
            name='walle-guard-installer',
            entry='backend/frozen_guard_installer_entry.py',
            modules=('tools.windows_guard_installation',),
            data_areas=(),
            timeout=900,
            excluded_modules=(
                'PyInstaller',
                'pip',
                'setuptools',
                'sqlite3',
                '_sqlite3',
                'backend.app.infrastructure.database',
                'backend.app.service',
                'backend.app.code_tasks',
            ),
        )
        code, output_text = run_owned(
            [str(package / INSTALLER_POLICY.entry_name), '--verify-runtime'],
            cwd=base / 'tmp',
            environment=environment,
            timeout=90,
        )
        if code or b'GUARD_INSTALLER_RUNTIME_VERIFIED' not in output_text:
            print(output_text[-4000:].decode('utf-8', 'replace'))
            raise ProgramBuildError('FROZEN_INSTALLER_RUNTIME_UNVERIFIED')
        raw, manifest, count, total = package_manifest(
            package, program_ref, policy=INSTALLER_POLICY
        )
        validate_program_destination(output, raw, manifest, policy=INSTALLER_POLICY)
        write_new_verified_file(package / INSTALLER_POLICY.manifest_name, raw)
        with ProgramPackageLease(
            package, expected_sha256=manifest, policy=INSTALLER_POLICY
        ) as held:
            held.verify()
        if snapshot_files(input_files(root)) != original:
            raise ProgramBuildError('INSTALLER_BUILD_SOURCE_CHANGED')
        if output.exists():
            raise ProgramBuildError('NEW_INSTALLER_PACKAGE_REQUIRED')
        os.rename(package, output)
        return manifest, source_digest(original), count, total


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--program-ref', required=True)
    values = parser.parse_args(arguments)
    manifest, sources, count, total = build(ROOT, values.output, values.program_ref)
    print(
        f'GUARD_INSTALLER_PACKAGE_PREPARED manifest={manifest} sources={sources} '
        f'members={count} bytes={total}',
        flush=True,
    )
    print('NO_SYSTEM_INSTALLATION_OR_SERVICE_CONTROL', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
