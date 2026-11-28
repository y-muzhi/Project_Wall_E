"""Generate and sync a native Linux runtime index in a new build-owned prefix."""

import argparse
import os
import re
import runpy
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path

here = Path(__file__).resolve().parent
runtime = runpy.run_path(str(here / 'runtime.py'))

ENVIRONMENT = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}


def artifact(root, path):
    return {
        'path': path.relative_to(root).as_posix(),
        'sha256': runtime['sha256'](path),
        'bytes': path.stat().st_size,
    }


def write_resource(path, value):
    with path.open('xb') as output:
        output.write(runtime['canonical'](value))
        output.flush()
        os.fsync(output.fileno())


def is_elf(path):
    with path.open('rb') as stream:
        return stream.read(4) == b'\x7fELF'


def host_closure(root, files):
    hosts = set()
    for binary in files:
        if not is_elf(binary):
            continue
        dynamic = subprocess.check_output(
            ['/usr/bin/readelf', '-d', str(binary)], env=ENVIRONMENT, text=True
        )
        if '(NEEDED)' not in dynamic:
            continue
        output = subprocess.check_output(
            ['/usr/bin/ldd', str(binary)], env=ENVIRONMENT, stderr=subprocess.STDOUT, text=True
        )
        for line in output.splitlines():
            entry = line.strip()
            if '=> not found' in entry:
                raise ValueError(f'Unresolved ELF dependency in {binary.name}: {entry}')
            match = re.search(r'(?:^|=> )(/[^ ]+) \(', entry)
            if match is None:
                if entry.startswith('linux-vdso.so.1'):
                    continue
                raise ValueError(f'Unrecognized ELF dependency in {binary.name}: {entry}')
            host = Path(match[1]).resolve(strict=True)
            if not host.is_relative_to(root):
                hosts.add(host)
    return sorted(hosts, key=str)


def package_record(path):
    choices = [str(path)]
    if str(path).startswith('/usr/'):
        choices.append(str(path)[4:])
    for spelling in choices:
        try:
            package = runtime['dpkg_query']('-S', '--', spelling).split(': ', 1)[0]
        except subprocess.CalledProcessError:
            continue
        if re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?', package):
            version = runtime['dpkg_query']('-W', '-f=${Version}', '--', package)
            return {
                'absolute_path': str(path),
                'sha256': runtime['sha256'](path),
                'bytes': path.stat().st_size,
                'package_name': package,
                'package_version': version,
            }
    raise ValueError(f'Missing host package for {path}')


def sync_directory(path):
    descriptor = os.open(path, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime_id')
    parser.add_argument('--architecture', choices=runtime['BUILD_ARCHITECTURES'], default='aarch64')
    args = parser.parse_args()
    root = Path(sys.base_prefix)
    if (
        not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode)
        or os.geteuid() == 0
        or root.stat().st_uid != os.geteuid()
        or root.stat().st_mode & 0o077
        or Path(sys.executable) != root / 'bin/python3.13'
        or not re.fullmatch('[a-z0-9][a-z0-9-]{0,95}', args.runtime_id)
    ):
        raise ValueError('Expected the unprivileged builder, a private prefix and -I -B -S')
    platform = runtime['require_build_target'](args.architecture)

    for name in ('build-inputs.v1.json', 'python-wheels.v1.json'):
        if not (root / 'metadata' / name).is_file():
            raise ValueError(f'Missing build input: {name}')
    dependency_reference = artifact(root, root / runtime['DEPENDENCIES'])
    runtime['read_wheel_manifest'](root, dependency_reference['sha256'], platform)
    for name in (runtime['INDEX'], runtime['RUNTIME_MANIFEST']):
        if (root / name).exists():
            raise ValueError('Runtime release already exists')
    native = root / 'lib/walle_environment_lock.so'
    native_source = here / 'environment_lock.c'
    if native.exists():
        raise ValueError('Native lock binding is already prepared')
    subprocess.run(
        [
            '/usr/bin/gcc',
            '-std=c17',
            '-Wall',
            '-Wextra',
            '-Werror',
            '-O2',
            '-fPIC',
            '-shared',
            '-Wl,-z,relro,-z,now',
            '-o',
            str(native),
            str(native_source),
        ],
        env=ENVIRONMENT,
        check=True,
    )
    with (root / 'metadata/environment-lock-source.sha256').open('x', encoding='ascii') as stamp:
        stamp.write(runtime['sha256'](native_source) + '\n')
    installed_entry = root / 'metadata/runtime.py'
    entry_bytes = (here / 'runtime.py').read_bytes()
    if installed_entry.exists():
        if installed_entry.is_symlink() or installed_entry.read_bytes() != entry_bytes:
            raise ValueError('Existing preparation entry differs from the build input')
    else:
        with installed_entry.open('xb') as target:
            target.write(entry_bytes)

    sys.path.append(sysconfig.get_path('purelib'))
    import _sqlite3
    import sqlite3

    source, options = runtime['probe_sqlite'](sqlite3, Path(os.environ['TMPDIR']))
    if sqlite3.sqlite_version != runtime['SQLITE_VERSION'] or source != runtime['SOURCE_ID']:
        raise ValueError('Incorrect SQLite source identity')

    # Remove only empty directories just created by this build.
    for base, _, _ in os.walk(root, topdown=False):
        directory = Path(base)
        if directory != root and not any(directory.iterdir()):
            directory.rmdir()

    files = []
    directories = []
    for path, info in runtime['inventory'](root):
        if stat.S_ISDIR(info.st_mode):
            directories.append(path)
        else:
            files.append(path)
    libraries = [package_record(path) for path in host_closure(root, files)]
    index = []
    for path in sorted(files, key=lambda file: file.relative_to(root).as_posix()):
        mode = 0o555 if path.stat().st_mode & 0o111 else 0o444
        path.chmod(mode)
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
        index.append({**artifact(root, path), 'mode': f'{mode:04o}'})
    index_file = root / runtime['INDEX']
    write_resource(index_file, {'format_version': 1, 'files': index})

    def relative(path):
        return Path(path).relative_to(root).as_posix()

    manifest = {
        'format_version': 1,
        'runtime_id': args.runtime_id,
        'platform': platform,
        'installation_prefix': str(root),
        'python': {
            'implementation': sys.implementation.name,
            'version': '.'.join(map(str, sys.version_info[:3])),
            'cache_tag': sys.implementation.cache_tag,
            'soabi': sysconfig.get_config_var('SOABI'),
            'executable_ref': relative(sys.executable),
            'sqlite_extension_ref': relative(_sqlite3.__file__),
            'site_packages_ref': relative(sysconfig.get_path('purelib')),
        },
        'sqlite': {
            'version': sqlite3.sqlite_version,
            'source_id': source,
            'library_ref': 'lib/libsqlite3.so.0',
            'compile_options': options,
            'required_features': runtime['FEATURES'],
            'required_limits': runtime['LIMITS'],
        },
        'files_ref': artifact(root, index_file),
        'dependencies_ref': dependency_reference,
        'host_libraries': libraries,
        'build_ref': artifact(root, root / runtime['BUILD_INPUTS']),
        'launch_flags': runtime['FLAGS'],
    }
    manifest_path = root / runtime['RUNTIME_MANIFEST']
    runtime['verify_target_imports'](root, manifest)
    runtime['validate_mappings'](
        root,
        (Path(sys.executable), Path(_sqlite3.__file__), root / manifest['sqlite']['library_ref']),
        runtime['verify_host_libraries'](libraries),
    )
    write_resource(manifest_path, manifest)
    for path in (index_file, manifest_path):
        path.chmod(0o444)
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o755)
        sync_directory(directory)
    sync_directory(root)
    print(
        f'CANDIDATE {runtime["sha256"](manifest_path)} files={len(files)} host_libs={len(libraries)}'
    )


if __name__ == '__main__':
    main()
