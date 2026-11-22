"""Verify and launch the fixed Linux runtime before importing WALL-E."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory

PLATFORM = dict(
    os='linux', architecture='aarch64', distribution_id='ubuntu', distribution_version='24.04'
)
SOURCE_ID = '2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76'
PYTHON_VERSION = '3.13.18'
SQLITE_VERSION = '3.54.1'
FLAGS = ['-I', '-B', '-S']
FEATURES = ['FOREIGN_KEYS', 'STRICT', 'JSON', 'WAL', 'FULL_SYNCHRONOUS']
LIMITS = {'trigger_depth': 100}
FILE_MODES = {0o400, 0o440, 0o444, 0o500, 0o550, 0o555}
RUNTIME_MANIFEST = 'runtime-manifest.v1.json'
INDEX = 'runtime-files.v1.json'
DEPENDENCIES = 'metadata/python-wheels.v1.json'
BUILD_INPUTS = 'metadata/build-inputs.v1.json'


class AdmissionError(ValueError):
    pass


def demand(condition, message):
    if not condition:
        raise AdmissionError(message)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(value):
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
        )
        + '\n'
    ).encode('utf-8')


def object_fields(value, *names):
    demand(type(value) is dict and set(value) == set(names), 'Unexpected manifest fields')


def unique_object(pairs):
    result = dict(pairs)
    demand(len(pairs) == len(result), 'Duplicate manifest key')
    return result


def reject_number(value):
    raise AdmissionError(f'Unsupported manifest number: {value[:24]}')


def safe_integer(value):
    number = int(value)
    demand(abs(number) <= 9007199254740991, 'Manifest integer outside exact range')
    return number


def load_json(path, digest):
    validate_hash(digest)
    with path.open('rb') as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    demand(len(data) <= 4 * 1024 * 1024, 'Manifest too large')
    demand(hashlib.sha256(data).hexdigest() == digest, 'Manifest digest mismatch')
    value = json.loads(
        data.decode('utf-8'),
        object_pairs_hook=unique_object,
        parse_float=reject_number,
        parse_constant=reject_number,
        parse_int=safe_integer,
    )
    demand(canonical(value) == data, 'Noncanonical manifest')
    return value


def validate_hash(value):
    demand(type(value) is str and re.fullmatch('[a-f0-9]{64}', value), 'Invalid SHA-256')


def manifest_path(value):
    demand(type(value) is str and '\\' not in value and '\0' not in value, 'Invalid manifest path')
    demand(
        all(part not in ('', '.', '..') for part in value.split('/')),
        'Invalid relative manifest path',
    )
    return PurePosixPath(value)


def file_entry(root, relative):
    path = root / relative
    info = path.lstat()
    demand(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Unsafe runtime file')
    return path, info


def artifact(root, ref, *, allow_empty=False):
    object_fields(ref, 'path', 'sha256', 'bytes')
    relative = manifest_path(ref['path'])
    validate_hash(ref['sha256'])
    demand(
        type(ref['bytes']) is int and ref['bytes'] >= (0 if allow_empty else 1),
        'Invalid artifact size',
    )
    path, info = file_entry(root, relative)
    demand(
        info.st_size == ref['bytes'] and sha256(path) == ref['sha256'],
        f'Artifact mismatch: {relative}',
    )
    return path


def protected_directory(path):
    demand(path.is_absolute() and path.resolve(strict=True) == path, 'Unexpected runtime path')
    for directory in (path, *path.parents):
        info = directory.lstat()
        demand(
            stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o022 == 0,
            f'Unprotected runtime directory: {directory}',
        )


def protected_file(path, info):
    demand(
        info.st_uid == 0 and stat.S_IMODE(info.st_mode) in FILE_MODES,
        f'Unsealed runtime file: {path.name}',
    )


def inventory(root):
    for base, folders, files in os.walk(root, followlinks=False):
        for name in folders:
            path = Path(base) / name
            info = path.lstat()
            demand(stat.S_ISDIR(info.st_mode), f'Unsafe runtime directory: {name}')
            yield path, info
        for name in files:
            path = Path(base) / name
            yield file_entry(root, path.relative_to(root))


def os_release():
    with Path('/etc/os-release').open(encoding='utf-8') as stream:
        fields = dict(line.rstrip('\n').split('=', 1) for line in stream if '=' in line)
    return dict(
        os=sys.platform,
        architecture=os.uname().machine,
        distribution_id=fields['ID'].strip('"'),
        distribution_version=fields['VERSION_ID'].strip('"'),
    )


def verify_files(root, manifest):
    ref = manifest['files_ref']
    path = artifact(root, ref)
    demand(path == root / INDEX, 'Unexpected runtime file index')
    index = load_json(path, ref['sha256'])
    object_fields(index, 'format_version', 'files')
    demand(
        type(index['format_version']) is int and index['format_version'] == 1,
        'Unsupported runtime index',
    )
    rows = {}
    directories = set()
    demand(type(index['files']) is list, 'Invalid runtime index')
    for row in index['files']:
        object_fields(row, 'path', 'sha256', 'bytes', 'mode')
        name = str(manifest_path(row['path']))
        demand(name not in rows and name not in (INDEX, RUNTIME_MANIFEST), 'Duplicate file')
        demand(
            type(row['mode']) is str and row['mode'] in {f'{m:04o}' for m in FILE_MODES},
            'Invalid file mode',
        )
        rows[name] = row
        directories.update(
            str(parent) for parent in PurePosixPath(name).parents if str(parent) != '.'
        )
    demand(list(rows) == sorted(rows), 'Unsorted runtime index')
    seen = set()
    for candidate, info in inventory(root):
        name = candidate.relative_to(root).as_posix()
        if stat.S_ISDIR(info.st_mode):
            demand(
                info.st_uid == 0 and info.st_mode & 0o022 == 0 and name in directories,
                f'Unexpected runtime directory: {name}',
            )
            continue
        protected_file(candidate, info)
        if name in (INDEX, RUNTIME_MANIFEST):
            continue
        demand(name in rows, f'Unregistered runtime file: {name}')
        row = rows[name]
        demand(stat.S_IMODE(info.st_mode) == int(row['mode'], 8), f'Incorrect file mode: {name}')
        artifact(
            root, {field: row[field] for field in ('path', 'sha256', 'bytes')}, allow_empty=True
        )
        seen.add(name)
    demand(seen == rows.keys(), 'Missing runtime file')
    return rows, directories


def dpkg_query(*args):
    return subprocess.check_output(
        ['/usr/bin/dpkg-query', *args],
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()


def verify_host_libraries(rows):
    demand(type(rows) is list and bool(rows), 'Missing host library closure')
    libraries = {}
    for row in rows:
        object_fields(row, 'absolute_path', 'sha256', 'bytes', 'package_name', 'package_version')
        path = Path(row['absolute_path'])
        demand(
            path.is_absolute() and path.resolve(strict=True) == path and path not in libraries,
            'Invalid host library path',
        )
        protected_directory(path.parent)
        info = path.lstat()
        demand(
            stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o022 == 0,
            'Unprotected host library',
        )
        validate_hash(row['sha256'])
        demand(
            type(row['bytes']) is int
            and info.st_size == row['bytes']
            and sha256(path) == row['sha256'],
            'Host library bytes differ',
        )
        demand(
            re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?', row['package_name']),
            'Invalid host package',
        )
        version = dpkg_query('-W', '-f=${Version}', '--', row['package_name'])
        demand(version and version == row['package_version'], 'Host package version differs')
        libraries[path] = info
    demand(list(libraries) == sorted(libraries), 'Unsorted host library list')
    return libraries


def verify_runtime(root, digest):
    protected_directory(root)
    manifest_path_on_disk, info = file_entry(root, RUNTIME_MANIFEST)
    protected_file(manifest_path_on_disk, info)
    manifest = load_json(manifest_path_on_disk, digest)
    object_fields(
        manifest,
        'format_version',
        'runtime_id',
        'platform',
        'installation_prefix',
        'python',
        'sqlite',
        'files_ref',
        'dependencies_ref',
        'host_libraries',
        'build_ref',
        'launch_flags',
    )
    demand(
        type(manifest['format_version']) is int and manifest['format_version'] == 1,
        'Unsupported runtime manifest',
    )
    demand(
        re.fullmatch('[a-z0-9][a-z0-9-]{0,95}', manifest['runtime_id'])
        and manifest['installation_prefix'] == str(root),
        'Unexpected runtime installation',
    )
    demand(manifest['platform'] == PLATFORM == os_release(), 'Runtime platform differs')
    demand(manifest['launch_flags'] == FLAGS, 'Unexpected interpreter options')
    files, directories = verify_files(root, manifest)
    py = manifest['python']
    object_fields(
        py,
        'implementation',
        'version',
        'cache_tag',
        'soabi',
        'executable_ref',
        'sqlite_extension_ref',
        'site_packages_ref',
    )
    demand(
        py['implementation'] == 'cpython'
        and py['version'] == PYTHON_VERSION
        and py['cache_tag'] == 'cpython-313'
        and py['soabi'] == 'cpython-313-aarch64-linux-gnu',
        'Unsupported CPython ABI',
    )
    sql = manifest['sqlite']
    object_fields(
        sql,
        'version',
        'source_id',
        'library_ref',
        'compile_options',
        'required_features',
        'required_limits',
    )
    demand(
        sql['version'] == SQLITE_VERSION
        and sql['source_id'] == SOURCE_ID
        and sql['required_features'] == FEATURES
        and sql['required_limits'] == LIMITS,
        'Unexpected SQLite identity or feature contract',
    )
    options = sql['compile_options']
    demand(
        type(options) is list
        and options == sorted(set(options))
        and 'THREADSAFE=1' in options
        and 'MAX_TRIGGER_DEPTH=100' in options,
        'Unexpected SQLite compile options',
    )
    demand(
        {
            py['executable_ref'],
            py['sqlite_extension_ref'],
            sql['library_ref'],
            'metadata/runtime.py',
            'lib/walle_environment_lock.so',
        }
        <= files.keys(),
        'Runtime entry absent from index',
    )
    demand(py['site_packages_ref'] in directories, 'Private site-packages missing')
    for key, expected in (('dependencies_ref', DEPENDENCIES), ('build_ref', BUILD_INPUTS)):
        ref = manifest[key]
        demand(
            artifact(root, ref) == root / expected and expected in files,
            'Unexpected runtime metadata artifact',
        )
    return manifest, verify_host_libraries(manifest['host_libraries'])


def executable_mappings():
    mappings = {}
    with Path('/proc/self/maps').open(encoding='utf-8') as stream:
        for line in stream:
            parts = line.rstrip('\n').split(maxsplit=5)
            if len(parts) != 6 or 'x' not in parts[1] or not parts[5].startswith('/'):
                continue
            major, minor = (int(part, 16) for part in parts[3].split(':'))
            path = Path(parts[5])
            info = path.stat()
            identity = (major, minor, int(parts[4]))
            demand(
                identity == (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino),
                'Mapped executable identity differs',
            )
            mappings[path] = identity
    return mappings


@dataclass(frozen=True)
class ActiveSQLite:
    runtime_manifest_sha256: str
    executable: Path
    extension: Path
    library: Path
    identities: tuple
    version: str
    source_id: str
    sha256: str
    bundle_ref: str


_ACTIVE_SQLITE = None


def require_active():
    active = _ACTIVE_SQLITE
    demand(active is not None, 'Fixed Linux SQLite has not been admitted')
    mappings = executable_mappings()
    paths = (active.executable, active.extension, active.library)
    demand(
        tuple(mappings.get(path) for path in paths) == active.identities
        and {path for path in mappings if path.name.startswith('libsqlite3.so')} == {active.library}
        and getattr(sys.modules.get('_sqlite3'), '__file__', None) == str(active.extension)
        and getattr(sys.modules.get('sqlite3'), 'sqlite_version', None) == active.version,
        'Admitted bindings no longer match this process',
    )
    return active


def probe_sqlite(sqlite, temporary):
    with TemporaryDirectory(prefix='walle-runtime-probe-', dir=temporary) as folder:
        connection = sqlite.connect(Path(folder) / 'probe.sqlite')
        try:
            demand(
                connection.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',),
                'SQLite WAL unavailable',
            )
            connection.execute('PRAGMA synchronous=FULL')
            demand(
                connection.execute('PRAGMA synchronous').fetchone() == (2,),
                'SQLite FULL synchronous unavailable',
            )
            connection.execute('PRAGMA foreign_keys=ON')
            demand(
                connection.execute('PRAGMA foreign_keys').fetchone() == (1,),
                'SQLite foreign keys unavailable',
            )
            connection.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY) STRICT')
            connection.execute(
                'CREATE TABLE child(id INTEGER REFERENCES parent(id), body TEXT) STRICT'
            )
            connection.execute('INSERT INTO parent VALUES (1)')
            connection.execute("INSERT INTO child VALUES (1, '{}')")
            demand(
                connection.execute('SELECT json_valid(body) FROM child').fetchone() == (1,),
                'SQLite JSON unavailable',
            )
            for statement in (
                "INSERT INTO child VALUES (2, '{}')",
                "INSERT INTO parent VALUES ('not an integer')",
            ):
                try:
                    connection.execute(statement)
                except sqlite.IntegrityError:
                    continue
                raise AdmissionError('SQLite did not enforce STRICT or foreign keys')
            connection.commit()
            demand(
                connection.getlimit(sqlite.SQLITE_LIMIT_TRIGGER_DEPTH) == LIMITS['trigger_depth'],
                'SQLite trigger depth differs',
            )
            return connection.execute('SELECT sqlite_source_id()').fetchone()[0], sorted(
                row[0] for row in connection.execute('PRAGMA compile_options')
            )
        finally:
            connection.close()


def admit_target(root, digest, temporary):
    global _ACTIVE_SQLITE
    demand(
        sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
        'Target requires -I -B -S',
    )
    demand(
        not {'sqlite3', '_sqlite3', 'site', 'sitecustomize', 'usercustomize'} & sys.modules.keys(),
        'Runtime imported SQLite or site before admission',
    )
    manifest, host_libraries = verify_runtime(root, digest)
    py, sql = manifest['python'], manifest['sqlite']
    executable = root / py['executable_ref']
    extension = root / py['sqlite_extension_ref']
    library = root / sql['library_ref']
    demand(
        sys.implementation.name == py['implementation']
        and sys.implementation.cache_tag == py['cache_tag']
        and sysconfig.get_config_var('SOABI') == py['soabi']
        and '.'.join(map(str, sys.version_info[:3])) == py['version']
        and Path(sys.executable) == executable
        and Path(sys.base_prefix) == root,
        'Target CPython differs',
    )
    sys.path.append(str(root / py['site_packages_ref']))
    import _sqlite3
    import sqlite3

    source, options = probe_sqlite(sqlite3, temporary)
    demand(
        Path(_sqlite3.__file__) == extension
        and sqlite3.sqlite_version == sql['version']
        and sqlite3.threadsafety == 3
        and source == sql['source_id']
        and options == sql['compile_options'],
        'Loaded SQLite differs',
    )
    paths = (executable, extension, library)
    identities = validate_mappings(root, paths, host_libraries)
    _ACTIVE_SQLITE = ActiveSQLite(
        digest, *paths, identities, sql['version'], source, sha256(library), manifest['runtime_id']
    )
    return manifest, host_libraries, paths


def validate_mappings(root, required, hosts):
    mappings = executable_mappings()
    demand(all(path in mappings for path in required), 'Missing executable mapping')
    outside = {path for path in mappings if not path.is_relative_to(root)}
    demand(outside <= hosts.keys(), 'Unregistered mapped host library')
    for path in outside:
        expected = hosts[path]
        demand(
            mappings[path]
            == (os.major(expected.st_dev), os.minor(expected.st_dev), expected.st_ino),
            'Host library mapping differs',
        )
    return tuple(mappings[path] for path in required)


def minimum_environment(home, temporary):
    for path in (home, temporary):
        info = path.lstat()
        demand(
            path.is_absolute()
            and path.resolve(strict=True) == path
            and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.geteuid()
            and info.st_mode & 0o077 == 0,
            'Expected a private HOME/TMPDIR',
        )
    demand(
        home != temporary
        and not home.is_relative_to(temporary)
        and not temporary.is_relative_to(home),
        'HOME and TMPDIR must be separate',
    )
    return {
        'HOME': str(home),
        'TMPDIR': str(temporary),
        'PATH': '/usr/bin:/bin',
        'LANG': 'C.UTF-8',
        'TZ': 'UTC',
    }


def verify_target_imports(root, manifest):
    import importlib.metadata

    import fastapi
    import httpx
    import jsonschema
    import markdown_it
    import pydantic_core
    import rpds
    import uvicorn
    from packaging.tags import sys_tags
    from packaging.utils import canonicalize_name, parse_wheel_filename

    site = root / manifest['python']['site_packages_ref']
    for module in (fastapi, httpx, jsonschema, markdown_it, pydantic_core, rpds, uvicorn):
        demand(Path(module.__file__).is_relative_to(site), 'Dependency loaded outside its pin')
    ref = manifest['dependencies_ref']
    wheel_manifest = load_json(root / DEPENDENCIES, ref['sha256'])
    object_fields(
        wheel_manifest,
        'format_version',
        'platform',
        'python_version',
        'input_lock',
        'install_lock',
        'installer',
        'wheels',
    )
    demand(
        type(wheel_manifest['format_version']) is int
        and wheel_manifest['format_version'] == 1
        and wheel_manifest['platform'] == PLATFORM
        and wheel_manifest['python_version'] == PYTHON_VERSION,
        'Dependency manifest platform differs',
    )
    source_lock = artifact(root, wheel_manifest['input_lock'])
    install_lock = artifact(root, wheel_manifest['install_lock'])
    installer = wheel_manifest['installer']
    object_fields(installer, 'name', 'version', 'bootstrap_wheel')
    demand(installer['name'] == 'pip' and installer['version'] == '26.2.2', 'Unexpected installer')
    bootstrap = artifact(root, installer['bootstrap_wheel'])
    demand(bootstrap.name == 'pip-26.2.2-py3-none-any.whl', 'Unexpected installer artifact')
    tags = set(sys_tags())
    records = {}
    install_rows = []
    demand(type(wheel_manifest['wheels']) is list, 'Invalid wheel manifest list')
    for row in wheel_manifest['wheels']:
        object_fields(row, 'name', 'version', 'filename', 'sha256', 'bytes', 'tags', 'source_url')
        name, version, _, wheel_tags = parse_wheel_filename(row['filename'])
        demand(
            name == row['name']
            and str(version) == row['version']
            and name not in records
            and wheel_tags & tags
            and sorted(map(str, wheel_tags)) == row['tags'],
            'Incorrect target wheel identity',
        )
        demand(type(row['bytes']) is int and row['bytes'] > 0, 'Invalid wheel size')
        validate_hash(row['sha256'])
        records[name] = str(version)
        install_rows.append(f'{name}=={version} --hash=sha256:{row["sha256"]}\n')
    expected = []
    for line in source_lock.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            name, version = line.split('==')
            expected.append((canonicalize_name(name), version))
    installed = [
        (canonicalize_name(dist.metadata['Name']), dist.version)
        for dist in importlib.metadata.distributions(path=[str(site)])
    ]
    demand(
        len(records) == 31
        and list(records) == sorted(records)
        and sorted(records.items()) == sorted(expected) == sorted(installed)
        and install_lock.read_bytes() == ''.join(install_rows).encode('utf-8'),
        'Installed dependencies differ from the locked wheel set',
    )


def program_facts(project):
    """Hash every file in the root-controlled immutable program snapshot."""
    protected_directory(project)
    entries = []
    for path, info in inventory(project):
        name = path.relative_to(project).as_posix()
        if stat.S_ISDIR(info.st_mode):
            protected_directory(path)
        elif name != 'program-snapshot.v1.json':
            protected_file(path, info)
            entries.append({'path': name, 'sha256': sha256(path), 'bytes': info.st_size})
    names = {entry['path'] for entry in entries}
    demand(
        'backend/app/infrastructure/environment_command.py' in names, 'Incomplete project snapshot'
    )
    entries.sort(key=lambda entry: entry['path'])
    return {
        'format_version': 1,
        'file_count': len(entries),
        'tree_sha256': hashlib.sha256(canonical(entries)).hexdigest(),
    }


def verify_program(project):
    path, info = file_entry(project, 'program-snapshot.v1.json')
    protected_file(path, info)
    raw = path.read_bytes()
    demand(raw == canonical(program_facts(project)), 'PROGRAM_SNAPSHOT_MISMATCH')
    return hashlib.sha256(raw).hexdigest()


def run_target(args, environment):
    demand(dict(os.environ) == environment, 'Target environment differs')
    demand(Path(__file__) == args.root / 'metadata/runtime.py', 'Target entry differs')
    manifest, hosts, paths = admit_target(args.root, args.sha256, args.temporary)
    verify_target_imports(args.root, manifest)
    validate_mappings(args.root, paths, hosts)
    active = require_active()
    if args.stage == '_environment':
        project_sha = verify_program(args.project)
        sys.path.append(str(args.project))
        from backend.app.infrastructure.environment_command import run_command

        return run_command(args, active, project_sha)
    if args.stage == '_schema':
        project = args.project
        demand(
            project.is_absolute() and project.resolve(strict=True) == project,
            'The project snapshot must be an explicit absolute directory',
        )
        sys.path.append(str(project))
        from backend.app.infrastructure.schema_v22_publish import build_and_publish

        release = build_and_publish(args.output, args.release_id, active.runtime_manifest_sha256)
        validate_mappings(args.root, paths, hosts)
        print(
            f'SCHEMA_CANDIDATE {release.release_id} {release.manifest_sha256} '
            f'{release.schema_contract_sha256}'
        )
        return 0
    print(
        f'ADMITTED {active.bundle_ref} {active.runtime_manifest_sha256} '
        f'Python {manifest["python"]["version"]} SQLite {active.version} wheels=31'
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stages = {'probe': '_target', 'build-schema': '_schema', 'environment': '_environment'}
    parser.add_argument('stage', choices=(*stages, *stages.values()))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--home', required=True, type=Path)
    parser.add_argument('--temporary', required=True, type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--release-id')
    parser.add_argument('--anchor', type=Path)
    parser.add_argument('--anchor-sha256')
    parser.add_argument('--action', choices=('prepare', 'continue', 'check', 'diagnose', 'observe'))
    parser.add_argument('--operation-id')
    parser.add_argument('--intent-sha256')
    args = parser.parse_args()
    try:
        demand(
            sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
            'Host and target require -I -B -S',
        )
        schema_request = args.stage in ('build-schema', '_schema')
        environment_request = args.stage in ('environment', '_environment')
        schema_values = (args.output, args.release_id)
        control_values = (args.anchor, args.anchor_sha256, args.action)
        demand(
            bool(args.project) == (schema_request or environment_request)
            and (all(schema_values) if schema_request else not any(schema_values))
            and (
                all(control_values)
                if environment_request
                else not any((*control_values, args.operation_id, args.intent_sha256))
            ),
            'Unexpected startup stage inputs',
        )
        demand(os.geteuid() != 0, 'Use an unprivileged verification identity')
        environment = minimum_environment(args.home, args.temporary)
        demand(
            all(
                not (name.startswith(('LD_', 'PYTHON', 'PIP_')) or name.lower().endswith('_proxy'))
                for name in os.environ
            ),
            'Untrusted loader or proxy variable; use a clean host invocation',
        )
        if args.stage not in stages:
            return run_target(args, environment)
        manifest, _ = verify_runtime(args.root, args.sha256)
        receipt = subprocess.run(
            [
                str(args.root / manifest['python']['executable_ref']),
                *FLAGS,
                str(args.root / 'metadata/runtime.py'),
                stages[args.stage],
                *sys.argv[2:],
            ],
            check=False,
            env=environment,
            cwd=args.temporary,
        )
        if receipt.returncode in (0, 2, 3):
            return receipt.returncode
        print('Runtime target terminated without a verified result', file=sys.stderr)
        return 3
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        ImportError,
        subprocess.SubprocessError,
    ) as error:
        if args.stage in ('environment', '_environment'):
            print(json.dumps({'status': 'BLOCKED', 'reason_code': 'RUNTIME_NOT_ADMITTED'}))
        else:
            print(f'Runtime admission rejected: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
