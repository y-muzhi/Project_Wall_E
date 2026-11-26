"""Prepare a new onedir backend package from a verified local source snapshot.

No service installation, ACL mutation, database initialization, model calls or Git
execution. The resulting protected-program manifest is not an OS admission.
"""

import argparse
import hashlib
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.infrastructure.guard_backend_program import MANIFEST_NAME
from backend.app.infrastructure.program_manifest import BACKEND_PROGRAM_POLICY, MAX_FILE_BYTES
from backend.app.infrastructure.program_package import ProgramPackageLease
from backend.app.infrastructure.runtime_launch_journal import _resource
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_file_streams import require_default_data_stream
from backend.app.infrastructure.windows_local_paths import LocalPathGuard, local_absolute_path
from tools.windows_program_package import (
    freeze_onedir,
    require_build_environment,
    run_owned,
    snapshot_files,
    source_digest,
    validate_program_destination,
    write_new_verified_file,
)
from tools.windows_program_package import package_manifest as prepare_program_manifest

ROOT = Path(__file__).resolve().parents[1]
_EXCLUDED = {'__pycache__', '.pytest_cache', 'node_modules'}


class BackendBuildError(RuntimeError):
    pass


def input_files(root, frontend):
    from backend.app.infrastructure.formation_schema_release import (
        SOURCE_NAMES as FORMATION_SOURCE_NAMES,
    )
    from backend.app.infrastructure.schema_v20_release import SOURCE_NAMES

    areas = [
        root / 'backend/app',
        root / 'backend/resources',
        root / 'backend/runtime/sqlite/3.54.1/win-x64',
        root / 'backend/runtime/git/2.56.0.windows.4/win-x64',
    ]
    result = {}
    for area in areas:
        if not area.is_dir():
            raise BackendBuildError('FIXED_BUILD_RESOURCE_MISSING')
        for path in area.rglob('*'):
            if any(part in _EXCLUDED for part in path.parts):
                continue
            if path.is_file() or path.is_symlink() or path.is_junction():
                result[path.relative_to(root).as_posix()] = path
    for relative in {
        *SOURCE_NAMES,
        *FORMATION_SOURCE_NAMES,
        'backend/__init__.py',
        'backend/frozen_backend_entry.py',
        'backend/requirements.lock',
        'backend/requirements-build.lock',
        'tools/windows_backend_package.py',
        'tools/windows_backend_guard_probe.py',
        'tools/windows_program_package.py',
        'tools/build-windows-backend.py',
        'tools/quality_gate.py',
        'docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md',
        'docs/design/v2.0/WALL-E.前端设计文档_V_2.0.md',
    }:
        result[relative] = root / relative
    if frontend is not None:
        for path in frontend.rglob('*'):
            if path.is_file() or path.is_symlink() or path.is_junction():
                result['frontend/dist/' + path.relative_to(frontend).as_posix()] = path
    return dict(sorted(result.items()))


def snapshot_sources(root, frontend, destination=None):
    return snapshot_files(input_files(root, frontend), destination)


def frontend_sources(root):
    frontend = root / 'frontend'
    files = set(frontend.glob('*.json')) | set(frontend.glob('*config*'))
    files.add(frontend / 'index.html')
    for area in ('src', 'public'):
        files.update(path for path in (frontend / area).rglob('*') if path.is_file())
    result = {}
    for path in sorted(files):
        if not path.is_file():
            continue
        with LockedFileSource(path, max_file_bytes=MAX_FILE_BYTES, capture_raw=False) as source:
            value = source.snapshot
            require_default_data_stream(source._kernel, source._handle, directory=False)
            result['frontend-source/' + path.relative_to(frontend).as_posix()] = (
                value.file,
                value.byte_count,
                value.sha256,
            )
    if not result:
        raise BackendBuildError('FRONTEND_SOURCE_MISSING')
    return result


def compile_frontend(root, temporary):
    import shutil

    from tools.quality_gate import environment, stop_owned

    node = shutil.which('node')
    if node is None:
        raise BackendBuildError('FIXED_FRONTEND_BUILD_TOOL_REQUIRED')
    destination = temporary / 'frontend-dist'
    prefix = [node, '--require', str(root / 'tools/quality_node.cjs')]
    commands = [
        [*prefix, str(root / 'frontend/node_modules/typescript/bin/tsc'), '--noEmit'],
        [
            *prefix,
            str(root / 'frontend/node_modules/vite/bin/vite.js'),
            'build',
            '--outDir',
            str(destination),
            '--emptyOutDir',
        ],
    ]
    for command in commands:
        process = subprocess.Popen(
            command,
            cwd=root / 'frontend',
            env=environment(temporary),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            output, _ = process.communicate(timeout=180)
        finally:
            if process.poll() is None:
                stop_owned(process)
        if process.returncode:
            print(output[-5000:].decode('utf-8', 'replace'))
            raise BackendBuildError('CURRENT_FRONTEND_BUILD_FAILED')
    if not (destination / 'index.html').is_file():
        raise BackendBuildError('FRONTEND_BUILD_ENTRY_REQUIRED')
    return destination


def package_manifest(package, program_ref):
    return prepare_program_manifest(
        package, program_ref, policy=BACKEND_PROGRAM_POLICY, error_type=BackendBuildError
    )


def _replace_owned_build_file(target, raw):
    import tempfile

    original = target.read_bytes() if target.exists() else None
    descriptor, temporary = tempfile.mkstemp(prefix='.build-member-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if (target.read_bytes() if target.exists() else None) != original:
            raise BackendBuildError('BUILD_OUTPUT_CHANGED')
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def build_backend(root, output, program_ref, *, frontend=None, build_frontend=False, timeout=900):
    from backend.app.infrastructure.sqlite_runtime import DLL_SHA256, activate

    root, output = local_absolute_path(root), local_absolute_path(output)
    frontend = None if frontend is None else local_absolute_path(frontend)
    _resource(program_ref)
    if build_frontend and frontend is not None:
        raise BackendBuildError('ONE_FRONTEND_INPUT_REQUIRED')
    if frontend is not None:
        with LocalPathGuard(frontend, directory=True):
            if not (frontend / 'index.html').is_file():
                raise BackendBuildError('FRONTEND_BUILD_ENTRY_REQUIRED')
    require_build_environment(root, error_type=BackendBuildError)
    activate()
    from backend.app.infrastructure.review_schema import LAYOUT_NAME

    if output.exists() or output.is_symlink() or output.is_junction():
        raise BackendBuildError('NEW_BACKEND_PACKAGE_DIRECTORY_REQUIRED')
    for protected in (
        root / 'backend/app',
        root / 'backend/resources',
        root / 'backend/runtime',
        root / 'tools',
        root / 'docs',
        frontend,
    ):
        if protected is not None and (
            output.is_relative_to(protected) or protected.is_relative_to(output)
        ):
            raise BackendBuildError('BUILD_OUTPUT_OVERLAPS_SOURCE')
    with (
        LocalPathGuard(output.parent, directory=True),
        TemporaryDirectory(prefix='.we-build-', dir=output.parent) as temporary,
    ):
        base = Path(temporary)
        front_original = frontend_sources(root) if build_frontend else {}
        if build_frontend:
            frontend = compile_frontend(root, base)
            if frontend_sources(root) != front_original:
                raise BackendBuildError('FRONTEND_SOURCE_CHANGED')
        snapshot = base / 's'
        snapshot.mkdir()
        original = snapshot_sources(root, frontend, snapshot)
        package, environment, log = freeze_onedir(
            snapshot,
            base,
            name='walle-backend',
            entry='backend/frozen_backend_entry.py',
            modules=('backend.app',),
            data_areas=('backend', 'tools', 'docs', 'frontend'),
            timeout=timeout,
        )
        temporary_path = base / 'tmp'
        pinned_sqlite = snapshot / 'backend/runtime/sqlite/3.54.1/win-x64/sqlite3.dll'
        raw = pinned_sqlite.read_bytes()
        if hashlib.sha256(raw).hexdigest() != DLL_SHA256:
            raise BackendBuildError('PINNED_BUILD_SQLITE_DIFFERS')
        _replace_owned_build_file(package / '_internal/sqlite3.dll', raw)
        for schema_version, layout in ((200, None), (210, None), (210, LAYOUT_NAME)):
            probe_environment = environment.copy()
            probe_environment.pop('WALLE_FORMATION_SCHEMA_LAYOUT', None)
            if layout is not None:
                probe_environment['WALLE_FORMATION_SCHEMA_LAYOUT'] = layout
            status, probe_output = run_owned(
                [
                    str(package / 'walle-backend.exe'),
                    '--verify-runtime',
                    '--schema-version',
                    str(schema_version),
                ],
                cwd=temporary_path,
                environment=probe_environment,
                timeout=60,
            )
            expected = f'BACKEND_RUNTIME_VERIFIED schema={schema_version} sqlite=3.54.1'
            if layout is not None:
                expected += f' release={layout}'
            if status or expected.encode('ascii') not in probe_output:
                print(probe_output[-5000:].decode('utf-8', 'replace'))
                warnings = [
                    line
                    for line in log.decode('utf-8', 'replace').splitlines()
                    if 'not found' in line.lower() or 'could not resolve' in line.lower()
                ]
                for line in warnings[-16:]:
                    print(line[:500])
                raise BackendBuildError('FROZEN_BACKEND_RUNTIME_NOT_VERIFIED')
        if snapshot_sources(root, frontend) != original:
            raise BackendBuildError('BUILD_SOURCE_CHANGED')
        if build_frontend and frontend_sources(root) != front_original:
            raise BackendBuildError('FRONTEND_SOURCE_CHANGED')
        raw, digest, count, total = package_manifest(package, program_ref)
        validate_program_destination(output, raw, digest, policy=BACKEND_PROGRAM_POLICY)
        write_new_verified_file(package / MANIFEST_NAME, raw)
        with ProgramPackageLease(
            package, expected_sha256=digest, policy=BACKEND_PROGRAM_POLICY
        ) as held:
            held.verify()
        if output.exists():
            raise BackendBuildError('NEW_BACKEND_PACKAGE_DIRECTORY_REQUIRED')
        # Same filesystem, no replacement of an existing directory on Windows.
        os.rename(package, output)
        return digest, source_digest({**original, **front_original}), count, total


def main(arguments=None):
    parser = argparse.ArgumentParser(
        description='Build a new unadmitted Windows onedir backend package.'
    )
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument(
        '--program-ref',
        required=True,
        help='Fixed program identity: 16-128 ASCII letters, digits, underscores or hyphens.',
    )
    frontend = parser.add_mutually_exclusive_group()
    frontend.add_argument('--frontend-dist', type=Path)
    frontend.add_argument('--build-frontend', action='store_true')
    values = parser.parse_args(arguments)
    try:
        digest, sources, count, total = build_backend(
            values.source_root,
            values.output,
            values.program_ref,
            frontend=values.frontend_dist,
            build_frontend=values.build_frontend,
        )
    except (OSError, RuntimeError, ValueError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        print('BACKEND_PACKAGE_BUILD_FAILED', str(error))
        return 1
    print(
        f'BACKEND_PACKAGE_PREPARED manifest={digest} sources={sources} members={count} bytes={total}'
    )
    print('INSTALLATION_AND_OS_ADMISSION_NOT_PERFORMED')
    return 0
