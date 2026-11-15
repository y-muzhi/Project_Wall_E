"""Shared fixed-tool, source snapshot and onedir program preparation primitives."""

import hashlib
import importlib.metadata
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from backend.app.infrastructure.content_paths import ContentPathIndex
from backend.app.infrastructure.program_manifest import (
    MAX_FILE_BYTES,
    MAX_MEMBERS,
    MAX_TOTAL_BYTES,
    decode_program_manifest,
)
from backend.app.infrastructure.runtime_launch_journal import _bytes, _resource
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_file_streams import require_default_data_stream
from backend.app.infrastructure.windows_local_paths import LocalPathGuard

_TOOL_ROW = re.compile(r'([A-Za-z0-9_.-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})')
_RUNTIME_ROW = re.compile(r'([A-Za-z0-9_.-]+)==([^ ]+)')


class ProgramBuildError(RuntimeError):
    pass


def require_build_environment(root, *, error_type=ProgramBuildError):
    if (
        os.name != 'nt'
        or platform.machine().lower() not in ('amd64', 'x86_64')
        or sys.version_info[:3] != (3, 13, 5)
    ):
        raise error_type('FIXED_WINDOWS_PYTHON_BUILD_REQUIRED')
    for filename, expression in (
        ('requirements.lock', _RUNTIME_ROW),
        ('requirements-build.lock', _TOOL_ROW),
    ):
        rows = []
        for line in (root / 'backend' / filename).read_text(encoding='utf-8').splitlines():
            if not line or line.startswith('#'):
                continue
            match = expression.fullmatch(line)
            if match is None:
                raise error_type('BUILD_DEPENDENCY_LOCK_INVALID')
            rows.append((match[1], match[2]))
        if not rows:
            raise error_type('BUILD_DEPENDENCY_LOCK_EMPTY')
        for name, expected in rows:
            try:
                observed = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError as error:
                raise error_type('LOCKED_BUILD_DEPENDENCY_MISSING') from error
            if observed != expected:
                raise error_type('LOCKED_BUILD_DEPENDENCY_VERSION_DIFFERS')


def snapshot_files(files, destination=None):
    namespace = ContentPathIndex(materialization_root=destination)
    observed = {}
    for relative, original in files.items():
        namespace.add_file(relative, '100644')
        with LockedFileSource(original, max_file_bytes=MAX_FILE_BYTES, capture_raw=False) as source:
            snapshot = source.snapshot
            require_default_data_stream(source._kernel, source._handle, directory=False)
            observed[relative] = snapshot.file, snapshot.byte_count, snapshot.sha256
            if destination is not None:
                copy_source_to_new_target(source, destination / relative)
    return observed


def copy_source_to_new_target(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:

        def write_chunk(raw):
            count = stream.write(raw)
            if type(count) is not int or count != len(raw):
                raise ProgramBuildError('SOURCE_SNAPSHOT_WRITE_INCOMPLETE')

        source.consume_verified(write_chunk)
        stream.flush()
        os.fsync(stream.fileno())
    with LockedFileSource(
        target, max_file_bytes=max(1, source.snapshot.byte_count), capture_raw=False
    ) as copied:
        actual = copied.snapshot
        require_default_data_stream(copied._kernel, copied._handle, directory=False)
        if (actual.byte_count, actual.sha256) != (
            source.snapshot.byte_count,
            source.snapshot.sha256,
        ):
            raise ProgramBuildError('SOURCE_SNAPSHOT_COPY_BYTES_DIFFER')


def write_new_verified_file(path, raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_FILE_BYTES:
        raise ProgramBuildError('PREPARED_FILE_BYTES_INVALID')
    with path.open('xb') as stream:
        count = stream.write(raw)
        if type(count) is not int or count != len(raw):
            raise ProgramBuildError('PREPARED_FILE_WRITE_INCOMPLETE')
        stream.flush()
        os.fsync(stream.fileno())
    with LockedFileSource(path, max_file_bytes=len(raw), capture_raw=False) as written:
        require_default_data_stream(written._kernel, written._handle, directory=False)
        actual = written.snapshot
        if (actual.byte_count, actual.sha256) != (len(raw), hashlib.sha256(raw).hexdigest()):
            raise ProgramBuildError('PREPARED_FILE_BYTES_DIFFER')


def package_manifest(package, program_ref, *, policy, error_type=ProgramBuildError):
    namespace = ContentPathIndex(materialization_root=package)
    namespace.add_file(policy.manifest_name, '100644')
    members = []
    total = 0
    directories = set()
    for directory, subdirectories, filenames in os.walk(package, followlinks=False):
        path = Path(directory)
        if path != package:
            directories.add(path.relative_to(package).as_posix())
        with LocalPathGuard(path, directory=True) as held:
            require_default_data_stream(held._kernel, held._held[-1][0], directory=True)
            for name in subdirectories:
                with LocalPathGuard(path / name, directory=True):
                    pass
            for name in filenames:
                target = path / name
                relative = namespace.add_file(target.relative_to(package).as_posix(), '100644').path
                if len(members) >= MAX_MEMBERS:
                    raise error_type(f'{policy.kind}_PACKAGE_MEMBER_LIMIT')
                with LockedFileSource(
                    target, max_file_bytes=MAX_FILE_BYTES, capture_raw=False
                ) as source:
                    value = source.snapshot
                    require_default_data_stream(source._kernel, source._handle, directory=False)
                    total += value.byte_count
                    if total > MAX_TOTAL_BYTES:
                        raise error_type(f'{policy.kind}_PACKAGE_TOTAL_SIZE_LIMIT')
                    members.append(
                        {'path': relative, 'byte_count': value.byte_count, 'sha256': value.sha256}
                    )
    members.sort(key=lambda member: member['path'].encode('utf-8'))
    value = {
        'policy_version': policy.version,
        'program_ref': _resource(program_ref),
        'entry': policy.entry_name,
        'files': members,
    }
    raw = _bytes(value)
    digest = hashlib.sha256(raw).hexdigest()
    spec = decode_program_manifest(raw, expected_sha256=digest, policy=policy)
    if directories != spec.directories:
        raise error_type(f'{policy.kind}_PACKAGE_EMPTY_OR_EXTRA_DIRECTORY')
    entry = next(member for member in spec.files if member.path == spec.entry)
    with ExecutablePin(
        package / spec.entry,
        expected_byte_count=entry.byte_count,
        expected_sha256=entry.sha256,
    ):
        pass
    return raw, digest, len(members), total


def build_environment(snapshot, base):
    import PyInstaller

    tools = Path(PyInstaller.__file__).resolve().parents[1]
    temporary = base / 'tmp'
    temporary.mkdir()
    for folder in ('home', 'appdata', 'localappdata'):
        (temporary / folder).mkdir()
    return {
        'SystemRoot': os.environ['SystemRoot'],
        'SystemDrive': os.environ.get('SystemDrive', 'C:'),
        'PATH': os.pathsep.join(
            (
                str(Path(sys.executable).parent),
                str(Path(sys.base_prefix)),
                str(Path(sys.base_prefix) / 'Library/bin'),
                str(Path(os.environ['SystemRoot']) / 'System32'),
            )
        ),
        'TEMP': str(temporary),
        'TMP': str(temporary),
        'USERPROFILE': str(temporary / 'home'),
        'APPDATA': str(temporary / 'appdata'),
        'LOCALAPPDATA': str(temporary / 'localappdata'),
        'PYTHONPATH': os.pathsep.join((str(tools), str(snapshot))),
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONUTF8': '1',
        'PYI_CONFIG_DIR': str(base / 'cache'),
    }


def run_owned(command, *, cwd, environment, timeout):
    from tools.quality_gate import stop_owned

    process = subprocess.Popen(
        command, cwd=cwd, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ProgramBuildError('PROGRAM_BUILD_DEADLINE_EXCEEDED') from None
        return process.returncode, output
    finally:
        if process.poll() is None:
            stop_owned(process)


def freeze_onedir(
    snapshot, base, *, name, entry, modules, data_areas, timeout, excluded_modules=()
):
    environment = build_environment(snapshot, base)
    command = [
        sys.executable,
        '-B',
        '-m',
        'PyInstaller',
        '--clean',
        '--noconfirm',
        '--onedir',
        '--name',
        name,
        '--contents-directory',
        '_internal',
        '--distpath',
        str(base / 'd'),
        '--workpath',
        str(base / 'w'),
        '--specpath',
        str(base / 't'),
        '--paths',
        str(snapshot),
    ]
    for module in excluded_modules:
        command.extend(('--exclude-module', module))
    for module in modules:
        command.extend(('--collect-submodules', module))
    for area in data_areas:
        if (snapshot / area).exists():
            command.extend(('--add-data', str(snapshot / area) + ';' + area))
    command.append(str(snapshot / entry))
    code, log = run_owned(command, cwd=snapshot, environment=environment, timeout=timeout)
    if code:
        print(log[-5000:].decode('utf-8', 'replace'))
        raise ProgramBuildError('PROGRAM_FREEZE_FAILED')
    return base / 'd' / name, environment, log


def source_digest(observed):
    values = [(name, count, sha) for name, (_, count, sha) in observed.items()]
    return hashlib.sha256(_bytes(values)).hexdigest()


def validate_program_destination(root, raw, expected_sha256, *, policy):
    spec = decode_program_manifest(raw, expected_sha256=expected_sha256, policy=policy)
    namespace = ContentPathIndex(materialization_root=root)
    namespace.add_file(policy.manifest_name, '100644')
    for member in spec.files:
        namespace.add_file(member.path, '100644')
    return spec
