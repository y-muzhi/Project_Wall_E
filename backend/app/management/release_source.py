"""Materialize independent build inputs from an explicit V2.2 integration commit."""

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from hashlib import sha1, sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.content_paths import ContentPathIndex
from backend.app.infrastructure.environment_files import canonical
from backend.app.infrastructure.git_fixed_content import reject_lfs_pointer
from backend.app.infrastructure.schema_v20_release import DESIGN_SOURCE, SOURCE_NAMES
from backend.app.infrastructure.schema_v22_publish import publish_directory
from backend.app.infrastructure.schema_v22_release import ENVIRONMENT_DESIGN, V22_SOURCES

APPLICATION = (
    'backend/__init__.py',
    'backend/app',
    'backend/requirements.lock',
    'backend/resources',
    DESIGN_SOURCE,
    ENVIRONMENT_DESIGN,
    'shared',
    'tools',
)
FRONTEND_BUILD = ('backend/resources', 'frontend', 'shared')
REQUIRED = {
    *SOURCE_NAMES,
    *V22_SOURCES,
    DESIGN_SOURCE,
    ENVIRONMENT_DESIGN,
    'backend/__init__.py',
    'backend/requirements.lock',
    'frontend/package.json',
    'frontend/package-lock.json',
    'frontend/tsconfig.json',
    'frontend/vite.config.ts',
    *(
        'backend/app/infrastructure/schemas/v2_0/db20-r50/' + name
        for name in ('manifest.json', 'fresh.v1.sql', 'objects.v1.json', 'upgrade-151.v1.sql')
    ),
}
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 384 * 1024 * 1024
MAX_FILES = 12_000
MANIFEST = 'release-source.v1.json'
MANIFEST_LIMIT = 4 * 1024 * 1024
BUILD_OUTPUTS = {'frontend/dist', 'frontend/node_modules'}
PROGRAM_SNAPSHOT = 'program-snapshot.v1.json'


class SourceError(ValueError):
    pass


@dataclass(frozen=True)
class Blob:
    mode: str
    oid: str
    size: int


@dataclass(frozen=True)
class GitReader:
    executable: Path
    repository: Path

    def run(self, *args, output=subprocess.PIPE, timeout=45):
        env = {
            'LC_ALL': 'C',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_NO_REPLACE_OBJECTS': '1',
            'GIT_NO_LAZY_FETCH': '1',
            'GIT_OPTIONAL_LOCKS': '0',
            'GIT_TERMINAL_PROMPT': '0',
            **{name: os.environ[name] for name in ('SystemRoot', 'WINDIR') if name in os.environ},
        }
        result = subprocess.run(
            [
                self.executable,
                '--no-pager',
                '--literal-pathspecs',
                '-c',
                'protocol.allow=never',
                '-c',
                'core.hooksPath=/dev/null',
                '-c',
                'core.fsmonitor=false',
                *args,
            ],
            cwd=self.repository,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise SourceError('Git could not read the requested source objects')
        return result.stdout


def contains(path, roots):
    return any(path == root or path.startswith(root + '/') for root in roots)


def require_commit(reader, oid, tree):
    format = reader.run('rev-parse', '--show-object-format').decode('ascii').strip()
    git_oid(oid, format)
    git_oid(tree, format)
    if reader.run('cat-file', '-t', oid) != b'commit\n':
        raise SourceError('An explicit commit object is required')
    if reader.run('rev-parse', '--verify', oid + '^{tree}').decode('ascii').strip() != tree:
        raise SourceError('The commit tree differs from the selected delivery')
    return format


def blobs_from_tree(raw, format):
    if not raw.endswith(b'\x00'):
        raise SourceError('Incomplete Git tree listing')
    namespace = ContentPathIndex()
    blobs = {}
    total = 0
    for entry in raw[:-1].split(b'\x00'):
        facts, path = entry.split(b'\t', 1)
        mode, kind, oid, size = facts.decode('ascii').split()
        path = path.decode('utf-8')
        if kind != 'blob' or not contains(path, (*APPLICATION, *FRONTEND_BUILD)):
            raise SourceError('Unsupported source entry')
        namespace.add_file(path, mode)
        git_oid(oid, format)
        size = int(size)
        total += size
        if not 0 <= size <= MAX_FILE_BYTES or total > MAX_SOURCE_BYTES or len(blobs) >= MAX_FILES:
            raise SourceError('Source exceeds the fixed build limits')
        blobs[path] = Blob(mode, oid, size)
    if not REQUIRED <= blobs.keys():
        raise SourceError('The commit is missing required V2.2 build or Schema inputs')
    return blobs


def write_new(path, raw, mode):
    path.parent.mkdir(mode=0o700, exist_ok=True, parents=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        if os.name != 'nt':
            os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())
    if os.name == 'nt':
        os.chmod(path, mode)


def extract_inputs(archive, output, blobs, format):
    copied = {}
    with tarfile.open(archive, mode='r:') as tar:
        for member in tar:
            path = member.name
            if member.isdir():
                if not any(source.startswith(path + '/') for source in blobs):
                    raise SourceError('Unexpected Git archive directory')
                continue
            blob = blobs.get(path)
            if blob is None or not member.isreg() or path in copied:
                raise SourceError('Unexpected Git archive member')
            executable = blob.mode == '100755'
            if member.size != blob.size or bool(member.mode & 0o111) != executable:
                raise SourceError('Git archive mode or length differs')
            with tar.extractfile(member) as stream:
                raw = stream.read(blob.size + 1)
            if len(raw) != blob.size:
                raise SourceError('Git archive member ended early')
            reject_lfs_pointer(raw)
            object_hash = sha256() if format == 'sha256' else sha1(usedforsecurity=False)
            object_hash.update(f'blob {blob.size}\0'.encode('ascii'))
            object_hash.update(raw)
            if object_hash.hexdigest() != blob.oid:
                raise SourceError('Git archive bytes differ from the pinned blob')
            if contains(path, APPLICATION):
                write_new(output / 'application' / path, raw, 0o555 if executable else 0o444)
            if contains(path, FRONTEND_BUILD):
                write_new(output / 'build' / path, raw, 0o755 if executable else 0o644)
            copied[path] = {
                'path': path,
                'oid': blob.oid,
                'mode': blob.mode,
                'bytes': blob.size,
                'sha256': sha256(raw).hexdigest(),
            }
    if copied.keys() != blobs.keys():
        raise SourceError('Git archive omitted one or more tracked build inputs')
    return [copied[path] for path in sorted(copied, key=lambda item: item.encode('utf-8'))]


def program_sha256(rows):
    facts = [
        {key: row[key] for key in ('path', 'sha256', 'bytes')}
        for row in rows
        if contains(row['path'], APPLICATION)
    ]
    record = {
        'format_version': 1,
        'file_count': len(facts),
        'tree_sha256': sha256(canonical(facts)).hexdigest(),
    }
    return sha256(canonical(record)).hexdigest()


def sync_directory(path):
    descriptor = os.open(path, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_inputs(staged, output):
    if os.name == 'nt':
        os.rename(staged, output)
        return
    for directory, _, _ in os.walk(staged, topdown=False):
        sync_directory(directory)
    publish_directory(staged, output)
    try:
        sync_directory(staged.parent)
        sync_directory(output.parent)
    except OSError as error:
        raise SourceError(
            'Build inputs were placed but directory synchronization is unverified'
        ) from error


def prepare(reader, oid, tree, output):
    if os.name != 'nt' and os.geteuid() == 0:
        raise SourceError('Use a non-privileged build identity')
    if not output.is_absolute() or output != output.parent.resolve(strict=True) / output.name:
        raise SourceError('An explicit new build directory is required')
    repo = reader.repository
    if (
        not repo.is_absolute()
        or repo != repo.resolve(strict=True)
        or not reader.executable.is_absolute()
        or not reader.executable.is_file()
    ):
        raise SourceError('An explicit source worktree and Git executable are required')
    registered = reader.run('rev-parse', '--show-toplevel').decode('utf-8').strip()
    object_directory = (
        reader.run('rev-parse', '--path-format=absolute', '--git-common-dir')
        .decode('utf-8')
        .strip()
    )
    checkout_metadata = reader.run('rev-parse', '--absolute-git-dir').decode('utf-8').strip()
    roots = (
        repo,
        Path(object_directory).resolve(strict=True),
        Path(checkout_metadata).resolve(strict=True),
    )
    if Path(registered).resolve(strict=True) != repo or any(
        output.is_relative_to(root) for root in roots
    ):
        raise SourceError('The build destination must be separate from the source worktree')
    if os.path.lexists(output):
        raise SourceError('The requested build destination already exists')

    format = require_commit(reader, oid, tree)
    roots = tuple(dict.fromkeys((*APPLICATION, *FRONTEND_BUILD)))
    blobs = blobs_from_tree(reader.run('ls-tree', '-r', '-l', '-z', oid, '--', *roots), format)
    with TemporaryDirectory(prefix='.release-source-', dir=output.parent) as temporary:
        scratch = Path(temporary)
        staged = scratch / 'inputs'
        staged.mkdir(mode=0o700)
        archive = scratch / 'source.tar'
        with archive.open('xb') as stream:
            reader.run('archive', '--format=tar', oid, '--', *roots, output=stream, timeout=180)
        entries = extract_inputs(archive, staged, blobs, format)
        manifest = canonical(
            {
                'format_version': 1,
                'object_format': format,
                'commit': oid,
                'tree': tree,
                'files': entries,
            }
        )
        if len(manifest) > MANIFEST_LIMIT:
            raise SourceError('Source manifest exceeds the fixed build limit')
        write_new(staged / MANIFEST, manifest, 0o444)
        require_commit(reader, oid, tree)
        publish_inputs(staged, output)
    return {
        'status': 'RELEASE_SOURCE_PREPARED',
        'commit': oid,
        'tree': tree,
        'files': len(entries),
        'manifest_sha256': sha256(manifest).hexdigest(),
        'program_sha256': program_sha256(entries),
        'application': str(output / 'application'),
        'build': str(output / 'build'),
    }


def read_source_manifest(output, expected):
    if not output.is_absolute() or output.resolve(strict=True) != output:
        raise SourceError('An explicit prepared source directory is required')
    path = output / MANIFEST
    require_regular_file(path)
    with path.open('rb') as stream:
        raw = stream.read(MANIFEST_LIMIT + 1)
    return parse_source_manifest(raw, expected)


def parse_source_manifest(raw, expected):
    if len(raw) > MANIFEST_LIMIT or sha256(raw).hexdigest() != expected:
        raise SourceError('The fixed source manifest differs')
    record = json.loads(raw)
    if (
        type(record) is not dict
        or set(record) != {'format_version', 'object_format', 'commit', 'tree', 'files'}
        or type(record['format_version']) is not int
        or record['format_version'] != 1
        or canonical(record) != raw
        or type(record['files']) is not list
        or len(record['files']) > MAX_FILES
    ):
        raise SourceError('Invalid fixed source manifest')
    format = record['object_format']
    git_oid(record['commit'], format)
    git_oid(record['tree'], format)
    return record


def indexed_sources(rows, format):
    namespace = ContentPathIndex()
    files = {}
    total = 0
    for row in rows:
        if type(row) is not dict or set(row) != {'path', 'mode', 'oid', 'bytes', 'sha256'}:
            raise SourceError('Invalid fixed source entry')
        name = namespace.add_file(row['path'], row['mode']).path
        git_oid(row['oid'], format)
        if (
            not contains(name, (*APPLICATION, *FRONTEND_BUILD))
            or type(row['bytes']) is not int
            or not 0 <= row['bytes'] <= MAX_FILE_BYTES
            or type(row['sha256']) is not str
            or re.fullmatch('[a-f0-9]{64}', row['sha256']) is None
        ):
            raise SourceError('Invalid fixed source entry')
        total += row['bytes']
        if total > MAX_SOURCE_BYTES:
            raise SourceError('Source exceeds the fixed build limits')
        files[name] = row
    if not REQUIRED <= files.keys() or list(files) != sorted(files, key=lambda item: item.encode()):
        raise SourceError('Incomplete or unordered fixed source inputs')
    return files


def require_regular_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.resolve(strict=True) != path:
        raise SourceError('A fixed source file was redirected or shared')
    return info


def file_facts(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def verify_source_file(path, row, *, build):
    initial = require_regular_file(path)
    executable = row['mode'] == '100755'
    expected_mode = (0o755 if executable else 0o644) if build else (0o555 if executable else 0o444)
    if initial.st_size != row['bytes'] or (
        os.name != 'nt' and stat.S_IMODE(initial.st_mode) != expected_mode
    ):
        raise SourceError('A fixed source file has changed')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        # Windows reports a different change time for a pathname and an open handle.
        if file_facts(opened)[:4] != file_facts(initial)[:4]:
            raise SourceError('A fixed source file changed while reading')
        measured = sha256()
        size = 0
        while block := stream.read(128 * 1024):
            size += len(block)
            if size > row['bytes']:
                raise SourceError('A fixed source file changed while reading')
            measured.update(block)
        if (
            size != row['bytes']
            or measured.hexdigest() != row['sha256']
            or file_facts(os.fstat(stream.fileno())) != file_facts(opened)
        ):
            raise SourceError('A fixed source file has changed')
    if file_facts(require_regular_file(path)) != file_facts(initial):
        raise SourceError('A fixed source path changed while reading')


def report_walk_error(error):
    raise error


def verify_source_layer(root, files, *, build):
    names = set(files)
    directories = {
        str(parent)
        for name in names
        for parent in PurePosixPath(name).parents
        if str(parent) != '.'
    }
    if root.resolve(strict=True) != root or not root.is_dir():
        raise SourceError('A source directory was redirected')
    checked = set()
    for raw, children, filenames in os.walk(root, followlinks=False, onerror=report_walk_error):
        base = Path(raw)
        for name in tuple(children):
            directory = base / name
            relative = directory.relative_to(root).as_posix()
            if directory.resolve(strict=True) != directory:
                raise SourceError('A source directory was redirected')
            if build and relative in BUILD_OUTPUTS:
                children.remove(name)
            elif relative not in directories:
                raise SourceError('An unexpected input directory was added')
        for name in filenames:
            file = base / name
            relative = file.relative_to(root).as_posix()
            if relative not in files:
                raise SourceError('An unexpected input file was added')
            verify_source_file(file, files[relative], build=build)
            checked.add(relative)
    if checked != names:
        raise SourceError('One or more fixed input files are missing')
    return len(checked)


def verify(output, expected):
    record = read_source_manifest(output, expected)
    if {item.name for item in output.iterdir()} != {'application', 'build', MANIFEST}:
        raise SourceError('The prepared source directory contains unexpected entries')
    files = indexed_sources(record['files'], record['object_format'])
    counts = {}
    for role, roots in (('application', APPLICATION), ('build', FRONTEND_BUILD)):
        subset = {name: row for name, row in files.items() if contains(name, roots)}
        counts[role] = verify_source_layer(output / role, subset, build=role == 'build')
    if read_source_manifest(output, expected) != record:
        raise SourceError('The fixed source manifest changed during verification')
    return {
        'status': 'RELEASE_SOURCE_VERIFIED',
        'commit': record['commit'],
        'tree': record['tree'],
        'manifest_sha256': expected,
        'program_sha256': program_sha256(files.values()),
        'application_files': counts['application'],
        'build_files': counts['build'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git', type=Path)
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--commit')
    parser.add_argument('--tree')
    parser.add_argument('--verify-manifest-sha256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source_args = (args.git, args.repository, args.commit, args.tree)
    checking = args.verify_manifest_sha256 is not None
    if (checking and any(source_args)) or (not checking and not all(source_args)):
        parser.error('Provide the Git source arguments or the verification manifest pin')
    try:
        if checking:
            receipt = verify(args.output, args.verify_manifest_sha256)
        else:
            receipt = prepare(
                GitReader(args.git, args.repository), args.commit, args.tree, args.output
            )
    except (
        OSError,
        ValueError,
        RuntimeError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as error:
        print(f'Release source preparation failed: {error}', file=sys.stderr)
        return 2
    sys.stdout.buffer.write(canonical(receipt))
    return 0
