"""Prepare a fixed CHECK20 browser closure; no service or OS admission."""

import argparse
import hashlib
import io
import os
import re
import stat
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from backend.app.infrastructure.check_runner_bundle import CHECK_PROTOCOL, decode_runner_manifest
from backend.app.infrastructure.content_paths import ContentPathIndex
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_file_streams import require_default_data_stream
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_object
from tools.quality_gate import environment, stop_owned
from tools.windows_backend_package import source_digest

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 300 * 1024**2
MAX_TOTAL_BYTES = 2 * 1024**3
MAX_MEMBERS = 16000
SOURCE_LOCK = 'backend/browser-headless-runtime.lock.json'
CHROMIUM_ARCHIVE = 'chrome-headless-shell-win64.zip'
CHROMIUM_ENTRY = 'chrome-headless-shell-win64/chrome-headless-shell.exe'
BOOTSTRAP = b'from backend.app.infrastructure.check_driver_browser import main\nmain()\n'
PTH = b'python313.zip\r\n.\r\nvendor\r\napplication.zip\r\n'


def decode_browser_lock(raw):
    value = strict_json_object(raw)
    if (
        set(value) != {'schema_version', 'python', 'playwright', 'chromium', 'revision', 'archives'}
        or type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or tuple(value[key] for key in ('python', 'playwright', 'chromium', 'revision'))
        != ('3.13.5', '1.58.0', '145.0.7632.6', '1208')
        or type(value['archives']) is not list
        or len(value['archives']) != 9
    ):
        raise ValueError('FIXED_BROWSER_SOURCE_LOCK_REQUIRED')
    seen = set()
    for row in value['archives']:
        if (
            type(row) is not dict
            or set(row) != {'filename', 'url', 'sha256'}
            or type(row['filename']) is not str
            or re.fullmatch(r'[A-Za-z0-9_.-]+\.(whl|zip)', row['filename']) is None
            or row['filename'].casefold() in seen
            or type(row['sha256']) is not str
            or re.fullmatch('[a-f0-9]{64}', row['sha256']) is None
            or type(row['url']) is not str
            or not row['url'].startswith(
                (
                    'https://files.pythonhosted.org/packages/',
                    'https://www.python.org/ftp/python/3.13.5/',
                    'https://cdn.playwright.dev/chrome-for-testing-public/145.0.7632.6/win64/',
                )
            )
            or not row['url'].endswith('/' + row['filename'])
        ):
            raise ValueError('FIXED_BROWSER_ARCHIVE_REQUIRED')
        seen.add(row['filename'].casefold())
    if not {CHROMIUM_ARCHIVE, 'python-3.13.5-embed-amd64.zip'}.issubset(seen):
        raise ValueError('FIXED_BROWSER_ARCHIVE_REQUIRED')
    return value


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def extract_archive(raw, destination, *, prefix=None):
    namespace = ContentPathIndex(materialization_root=destination)
    total = 0
    with ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_MEMBERS:
            raise ValueError('BROWSER_ARCHIVE_MEMBER_LIMIT')
        # Validate all names and types before any output.
        files = []
        for entry in entries:
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                raise ValueError('BROWSER_ARCHIVE_TYPE_UNSUPPORTED')
            if entry.is_dir():
                namespace.add_directory(entry.filename.rstrip('/'))
                continue
            name = namespace.add_file(entry.filename, '100644').path
            total += entry.file_size
            if total > MAX_TOTAL_BYTES or entry.file_size > 512 * 1024**2:
                raise ValueError('BROWSER_ARCHIVE_SIZE_LIMIT')
            files.append((entry, name))
        for entry, name in files:
            if prefix is not None and not name.startswith(prefix):
                continue
            raw_member = archive.read(entry)
            if len(raw_member) != entry.file_size:
                raise ValueError('BROWSER_ARCHIVE_SIZE_DIFFERS')
            write_new(destination / name, raw_member)


def fixed_archive(path, expected):
    with LockedFileSource(path, max_file_bytes=MAX_ARCHIVE_BYTES) as source:
        require_default_data_stream(source._kernel, source._handle, directory=False)
        if source.snapshot.sha256 != expected:
            raise ValueError('BROWSER_ARCHIVE_SHA256_DIFFERS')
        return source.snapshot.raw


def application_sources(root, destination=None):
    sources = {}
    for path in sorted((root / 'backend/app').rglob('*.py')):
        sources[path.relative_to(root).as_posix()] = path
    sources['backend/__init__.py'] = root / 'backend/__init__.py'
    for path in sorted((root / 'backend/app').rglob('*.cjs')):
        sources[path.relative_to(root).as_posix()] = path
    result = {}
    for name, path in sources.items():
        with LockedFileSource(path, max_file_bytes=16 * 1024**2) as source:
            require_default_data_stream(source._kernel, source._handle, directory=False)
            value = source.snapshot
            result[name] = value.file, value.byte_count, value.sha256
            if destination is not None:
                write_new(destination / name, value.raw)
    return result


def runner_manifest(root, evidence):
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            with LockedFileSource(path, max_file_bytes=512 * 1024**2, capture_raw=False) as source:
                require_default_data_stream(source._kernel, source._handle, directory=False)
                value = source.snapshot
                files.append(
                    {
                        'path': path.relative_to(root).as_posix(),
                        'byte_count': value.byte_count,
                        'sha256': value.sha256,
                    }
                )
    value = {
        'schema_version': 1,
        'protocol_version': CHECK_PROTOCOL,
        'bundle_id': 'walle-check-browser-win-x64',
        'version': '1.0.0',
        'entry_ref': 'python.exe',
        'runtime_refs': [
            'python:3.13.5',
            'playwright:1.58.0',
            'chromium:145.0.7632.6',
            'chromium-headless-shell:145.0.7632.6',
        ],
        'file_entries': files,
        'capabilities': ['BROWSER', 'CONTENT_INTEGRITY'],
        'platform_refs': ['windows:x64'],
        'admission_evidence_refs': ['preparation:import-' + evidence],
    }
    raw = canonical_input(value).encode('utf-8')
    decode_runner_manifest(raw)
    return raw


def _prepare(root, sources, chromium, output):
    lock_path = root / SOURCE_LOCK
    lock_raw = lock_path.read_bytes()
    lock = decode_browser_lock(lock_raw)
    if output.exists():
        raise ValueError('NEW_BROWSER_PACKAGE_DIRECTORY_REQUIRED')
    with TemporaryDirectory(prefix='.check-browser-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        package = temporary / 'package'
        package.mkdir()
        application = temporary / 'application'
        original = application_sources(root, application)
        application_bytes = io.BytesIO()
        with ZipFile(application_bytes, 'w', compression=ZIP_DEFLATED) as archive:
            for path in sorted(application.rglob('*.py')):
                entry = ZipInfo(path.relative_to(application).as_posix())
                entry.compress_type = ZIP_DEFLATED
                archive.writestr(entry, path.read_bytes())
        write_new(package / 'application.zip', application_bytes.getvalue())
        write_new(
            package / 'pipe-worker.cjs',
            (application / 'backend/app/infrastructure/check_driver_pipe_worker.cjs').read_bytes(),
        )
        write_new(
            package / 'browser-broker.cjs',
            (
                application / 'backend/app/infrastructure/check_driver_browser_broker.cjs'
            ).read_bytes(),
        )
        for row in lock['archives']:
            base = chromium if row['filename'] == CHROMIUM_ARCHIVE else sources
            raw = fixed_archive(base / row['filename'], row['sha256'])
            destination = package
            if row['filename'].endswith('.whl'):
                destination = package / 'vendor'
            extract_archive(
                raw,
                destination,
                prefix='playwright/driver/' if row['filename'].startswith('playwright-') else None,
            )
        # Only owned temporary files are replaced, using same-directory atomic rename.
        from tools.windows_backend_package import _replace_owned_build_file

        _replace_owned_build_file(package / 'python313._pth', PTH)
        write_new(package / 'driver.py', BOOTSTRAP)
        write_new(
            package / 'windows-lpac-policy.json',
            canonical_input(
                {'schema_version': 1, 'capability_names': ['registryRead', 'lpacCom']}
            ).encode(),
        )
        probe = (
            'import sys,ctypes;'
            'from backend.app.infrastructure.check_driver_pipe_sdk import PipeChromium;'
            'from backend.app.infrastructure.check_driver_browser_process import BrowserPipeProcess;'
            'from backend.app.infrastructure.check_driver_browser import main;'
            'assert sys.version_info[:3]==(3,13,5);'
            "assert not {'greenlet','pyee','playwright.sync_api','asyncio'} & sys.modules.keys();"
            "print('CHECK_BROWSER_IMPORT_VERIFIED')"
        )
        values = environment(temporary)
        process = subprocess.Popen(
            [str(package / 'python.exe'), '-I', '-B', '-c', probe],
            cwd=temporary,
            env=values,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            observed, _ = process.communicate(timeout=45)
        finally:
            if process.poll() is None:
                stop_owned(process)
        if process.returncode or observed.strip() != b'CHECK_BROWSER_IMPORT_VERIFIED':
            print(ascii(observed[-5000:].decode('utf-8', 'replace')))
            raise ValueError('BROWSER_RUNTIME_IMPORT_FAILED')
        if application_sources(root) != original or lock_path.read_bytes() != lock_raw:
            raise ValueError('BROWSER_BUILD_SOURCE_CHANGED')
        raw = runner_manifest(package, hashlib.sha256(observed).hexdigest())
        write_new(package / 'manifest.json', raw)
        verify_prepared_package(package)
        if application_sources(root) != original or lock_path.read_bytes() != lock_raw:
            raise ValueError('BROWSER_BUILD_SOURCE_CHANGED')
        if output.exists():
            raise ValueError('NEW_BROWSER_PACKAGE_DIRECTORY_REQUIRED')
        os.rename(package, output)
        return hashlib.sha256(raw).hexdigest(), source_digest(original)


def prepare(root, sources, chromium, output):
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard

    with LocalPathGuard(output.parent, directory=True) as parent:
        result = _prepare(root, sources, chromium, output)
        parent.verify()
        return result


def verify_prepared_package(package):
    from backend.app.infrastructure.browser_driver_lpac_policy import runner_lpac_capability_names
    from backend.app.infrastructure.check_runner_bundle import (
        CheckRunnerClosure,
        RegisteredCheckRunner,
    )
    from backend.app.infrastructure.windows_check_driver_program import RegisteredBrowserDriver
    from backend.app.infrastructure.windows_executable_pin import ExecutablePin
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_task_workspace_tree import (
        _scan_task_workspace_tree,
        workspace_tree_sha256,
    )

    with LocalPathGuard(package, directory=True) as guard:
        manifest_raw = (package / 'manifest.json').read_bytes()
        manifest = decode_runner_manifest(manifest_raw)
        files, directories, _, _ = _scan_task_workspace_tree(package, guard.verify(), lambda: None)
        expected = {row.path: (row.byte_count, row.sha256) for row in manifest.file_entries}
        expected['manifest.json'] = len(manifest_raw), hashlib.sha256(manifest_raw).hexdigest()
        parents = {
            name[:index] for name in expected for index, char in enumerate(name) if char == '/'
        }
        if {name: (count, digest) for name, (_, count, digest) in files.items()} != expected or set(
            directories
        ) != parents:
            raise ValueError('PREPARED_BROWSER_TREE_DIFFERS')
        registration = RegisteredCheckRunner(
            guard.verify(),
            hashlib.sha256(manifest_raw).hexdigest(),
            manifest.bundle_id,
            manifest.version,
        )
        closure = CheckRunnerClosure(
            registration,
            manifest,
            files[manifest.entry_ref][0],
            workspace_tree_sha256(files, directories),
            tuple((name, row[0]) for name, row in sorted(files.items())),
        )
        RegisteredBrowserDriver(registration, 'driver.py', CHROMIUM_ENTRY).verify_closure(closure)
        runner_lpac_capability_names(closure, lambda: None)
        entry = expected[manifest.entry_ref]
        with ExecutablePin(
            package / manifest.entry_ref, expected_byte_count=entry[0], expected_sha256=entry[1]
        ):
            pass
        if (package / 'manifest.json').read_bytes() != manifest_raw:
            raise ValueError('PREPARED_BROWSER_MANIFEST_CHANGED')
        guard.verify()
        return (
            hashlib.sha256(manifest_raw).hexdigest(),
            len(files),
            sum(row[1] for row in files.values()),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-package', type=Path)
    parser.add_argument('--sources', type=Path)
    parser.add_argument('--chromium', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    from backend.app.infrastructure.windows_local_paths import local_absolute_path

    if args.verify_package is not None:
        if any(value is not None for value in (args.sources, args.chromium, args.output)):
            parser.error('verify-package does not accept build inputs')
        print(
            'BROWSER_PACKAGE_BYTES_VERIFIED',
            verify_prepared_package(local_absolute_path(args.verify_package)),
        )
        print('FORMAL_OS_ADMISSION_NOT_PERFORMED')
        return
    if any(value is None for value in (args.sources, args.chromium, args.output)):
        parser.error('build requires sources, chromium and output')
    output = local_absolute_path(args.output)
    result = prepare(
        ROOT, local_absolute_path(args.sources), local_absolute_path(args.chromium), output
    )
    print('BROWSER_PACKAGE_PREPARED manifest=' + result[0] + ' sources=' + result[1])
    print('FORMAL_OS_ADMISSION_NOT_PERFORMED')


if __name__ == '__main__':
    main()
