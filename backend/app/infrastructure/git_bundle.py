"""Fixed MinGit archive preparation; no process execution or user Git access.

Archive bytes and extraction inventory are independent of Q20-GIT/Guard runtime
admission. This module never installs system software or changes PATH/ACLs.
"""

import hashlib
import json
import os
import shutil
import stat
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import mkdtemp
from urllib.request import Request, urlopen
from zipfile import ZipFile

from .content_paths import ContentPathIndex, materialized_path, relative_content_path
from .windows_config_source import ConfigReadError, LockedFileSource
from .windows_file_streams import FileStreamError, require_default_data_stream
from .windows_local_paths import LocalPathGuard

VERSION = '2.56.0.windows.4'
SOURCE_COMMIT = '581291682ad5a238c08c93d1f5bd4518382a3230'
TAG_OBJECT = 'e878704e2f40adc59f4b0d4e15424511456163db'
ARCHIVE_BYTES = 39846926
GIT_MANIFEST_SHA256 = '4e888e998f1f08e8b78559c212d30c51aaa3cc30e85b9cdafcf7b44249a4e215'
ARCHIVE_SHA256 = 'e3bf78351fe777fba47ddee5950082f8a98bb0f02604fdc7ba3ee2cb68ffa877'
SOURCE_URL = 'https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.4/MinGit-2.56.0.4-64-bit.zip'
RELEASE_URL = 'https://github.com/git-for-windows/git/releases/tag/v2.56.0.windows.4'
BUNDLE_PARENT = Path(__file__).resolve().parents[2] / 'runtime/git' / VERSION
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 20000


class GitBundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class BundleMember:
    path: str
    byte_count: int
    sha256: str


def _download(target):
    digest = hashlib.sha256()
    count = 0
    request = Request(SOURCE_URL, headers={'User-Agent': 'WALL-E-fixed-runtime-preparation'})
    with urlopen(request, timeout=60) as response, target.open('xb') as output:
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > ARCHIVE_BYTES:
                raise GitBundleError('MINGIT_ARCHIVE_SIZE_DIFFERS')
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if count != ARCHIVE_BYTES or digest.hexdigest() != ARCHIVE_SHA256:
        raise GitBundleError('MINGIT_ARCHIVE_DIGEST_DIFFERS')


def _inventory(archive, root):
    infos = archive.infolist()
    if not infos or len(infos) > MAX_MEMBERS:
        raise GitBundleError('MINGIT_ARCHIVE_ENTRY_LIMIT')
    namespace = ContentPathIndex(materialization_root=root)
    names = set()
    total = 0
    result = []
    for info in infos:
        path = info.filename[:-1] if info.is_dir() else info.filename
        relative_content_path(path)
        materialized_path(root, path)
        if path in names or path in ('source.zip', 'manifest.json'):
            raise GitBundleError('MINGIT_ARCHIVE_DUPLICATE_OR_RESERVED')
        names.add(path)
        file_type = stat.S_IFMT(info.external_attr >> 16)
        expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
        if file_type not in (0, expected) or info.flag_bits & 1:
            raise GitBundleError('MINGIT_ARCHIVE_MEMBER_TYPE_UNSUPPORTED')
        if info.is_dir():
            if info.file_size != 0:
                raise GitBundleError('MINGIT_ARCHIVE_DIRECTORY_HAS_BYTES')
            namespace.add_directory(path)
        else:
            namespace.add_file(path, '100644')
            total += info.file_size
            if total > MAX_EXPANDED_BYTES:
                raise GitBundleError('MINGIT_ARCHIVE_EXPANSION_LIMIT')
        result.append((info, path))
    return tuple(result), total


def _extract(archive, root, inventory):
    members = []
    for info, relative in inventory:
        path = root.joinpath(*relative.split('/'))
        if info.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        count = 0
        with archive.open(info, 'r') as source, path.open('xb') as output:
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > info.file_size:
                    raise GitBundleError('MINGIT_MEMBER_SIZE_DIFFERS')
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if count != info.file_size:
            raise GitBundleError('MINGIT_MEMBER_SIZE_DIFFERS')
        members.append(BundleMember(relative, count, digest.hexdigest()))
    return tuple(sorted(members, key=lambda member: member.path.encode('utf-8')))


def _verify_pe_x64(path):
    with path.open('rb') as source:
        header = source.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise GitBundleError('MINGIT_ENTRYPOINT_NOT_PE')
        offset = struct.unpack_from('<I', header, 0x3C)[0]
        if not 64 <= offset <= 1024 * 1024:
            raise GitBundleError('MINGIT_ENTRYPOINT_HEADER_INVALID')
        source.seek(offset)
        if source.read(6) != b'PE\0\0\x64\x86':
            raise GitBundleError('MINGIT_ENTRYPOINT_NOT_X64')


def _manifest(members):
    return {
        'schema_version': 1,
        'entrypoint': 'cmd/git.exe',
        'expected_version': VERSION,
        'architecture': 'win-x64',
        'source_commit': SOURCE_COMMIT,
        'tag_object': TAG_OBJECT,
        'source_url': SOURCE_URL,
        'release_url': RELEASE_URL,
        'archive_bytes': ARCHIVE_BYTES,
        'archive_sha256': ARCHIVE_SHA256,
        'members': [asdict(member) for member in members],
        'state': 'ARCHIVE_BYTES_VERIFIED',
        'runtime_admitted': False,
    }


def prepare_bundle():
    """Publish a NEW project-local archive and inventory; never run git.exe."""
    if os.name != 'nt':
        raise GitBundleError('WINDOWS_RESOURCE_PREPARATION_REQUIRED')
    BUNDLE_PARENT.mkdir(parents=True, exist_ok=True)
    target = BUNDLE_PARENT / 'win-x64'
    with LocalPathGuard(BUNDLE_PARENT, directory=True):
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise GitBundleError('NEW_IMMUTABLE_MINGIT_BUNDLE_REQUIRED')
        staged = Path(mkdtemp(prefix='.mingit-stage-', dir=BUNDLE_PARENT))
        try:
            source = staged / 'source.zip'
            _download(source)
            with ZipFile(source) as archive:
                inventory, expanded = _inventory(archive, staged)
                if shutil.disk_usage(staged).free < expanded + 64 * 1024 * 1024:
                    raise GitBundleError('MINGIT_SPACE_INSUFFICIENT')
                members = _extract(archive, staged, inventory)
            _verify_pe_x64(staged / 'cmd/git.exe')
            manifest = _manifest(members)
            encoded = (
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                    allow_nan=False,
                )
                + '\n'
            ).encode('utf-8')
            with (staged / 'manifest.json').open('xb') as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.rename(staged, target)
            return len(members), expanded, hashlib.sha256(encoded).hexdigest()
        finally:
            if staged.exists():
                resolved = staged.resolve(strict=True)
                if (
                    resolved.parent != BUNDLE_PARENT.resolve(strict=True)
                    or staged.is_symlink()
                    or staged.is_junction()
                    or not staged.name.startswith('.mingit-stage-')
                ):
                    raise GitBundleError('MINGIT_TEMP_CLEANUP_BOUNDARY_DIFFERS')
                shutil.rmtree(resolved)


def _verify_package_tree(root, expected_files, expected_directories):
    """One actual traversal, with every original file fully read on every invocation."""
    seen_files = set()
    seen_directories = set()

    def streams(kernel, handle, *, directory):
        try:
            require_default_data_stream(kernel, handle, directory=directory)
        except FileStreamError as error:
            raise GitBundleError('MINGIT_PACKAGE_' + str(error)) from error

    def visit(directory):
        with LocalPathGuard(directory, directory=True) as held:
            streams(held._kernel, held._held[-1][0], directory=True)
            with os.scandir(directory) as listing:
                for entry in listing:
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    if entry.is_dir(follow_symlinks=False):
                        if relative not in expected_directories or relative in seen_directories:
                            raise GitBundleError('MINGIT_PACKAGE_OBJECTS_DIFFER')
                        seen_directories.add(relative)
                        visit(path)
                        continue
                    if relative not in expected_files or relative in seen_files:
                        raise GitBundleError('MINGIT_PACKAGE_OBJECTS_DIFFER')
                    expected_count, expected_digest = expected_files[relative]
                    try:
                        # Construction locks the actual data handle, hashes every byte and
                        # checks original identities before/after. No second path walk.
                        source = LockedFileSource(
                            path,
                            max_file_bytes=max(1, expected_count),
                            capture_raw=False,
                        )
                    except ConfigReadError as original:
                        reason = (
                            'MINGIT_MEMBER_BYTES_DIFFER'
                            if str(original)
                            in (
                                'CONFIG_READ_BYTES_EXCEEDED',
                                'CONFIG_READ_SOURCE_CHANGED',
                            )
                            else 'MINGIT_MEMBER_READ_UNVERIFIED'
                        )
                        error = GitBundleError(reason)
                        if getattr(original, 'retained_owner', None) is not None:
                            error.retained_owner = original.retained_owner
                        raise error from original
                    try:
                        streams(source._kernel, source._handle, directory=False)
                        actual = source.snapshot
                        if (actual.byte_count, actual.sha256) != (expected_count, expected_digest):
                            raise GitBundleError('MINGIT_MEMBER_BYTES_DIFFER')
                    finally:
                        source.close()
                    seen_files.add(relative)
            held.verify()

    visit(root)
    if seen_files != set(expected_files) or seen_directories != set(expected_directories):
        raise GitBundleError('MINGIT_PACKAGE_OBJECTS_DIFFER')


def verify_bundle_bytes():
    """Reconstruct authority from the pinned source ZIP, never a self-reported version."""
    root = BUNDLE_PARENT / 'win-x64'
    with LocalPathGuard(root, directory=True):
        with (
            LocalPathGuard(root / 'source.zip', directory=False),
            (root / 'source.zip').open('rb') as stream,
        ):
            archive_data = stream.read(ARCHIVE_BYTES + 1)
        if (
            len(archive_data) != ARCHIVE_BYTES
            or hashlib.sha256(archive_data).hexdigest() != ARCHIVE_SHA256
        ):
            raise GitBundleError('MINGIT_ARCHIVE_DIGEST_DIFFERS')
        expected_members = []
        import io

        with ZipFile(io.BytesIO(archive_data)) as archive:
            inventory, expanded = _inventory(archive, root)
            for info, relative in inventory:
                if info.is_dir():
                    continue
                digest = hashlib.sha256()
                count = 0
                with archive.open(info, 'r') as stream:
                    while chunk := stream.read(1024 * 1024):
                        count += len(chunk)
                        digest.update(chunk)
                if count != info.file_size:
                    raise GitBundleError('MINGIT_MEMBER_SIZE_DIFFERS')
                expected_members.append(BundleMember(relative, count, digest.hexdigest()))
        members = tuple(sorted(expected_members, key=lambda member: member.path.encode('utf-8')))
        expected = _manifest(members)
        encoded = (
            json.dumps(
                expected, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
            )
            + '\n'
        ).encode('utf-8')
        with (
            LocalPathGuard(root / 'manifest.json', directory=False),
            (root / 'manifest.json').open('rb') as stream,
        ):
            actual = stream.read(len(encoded) + 1)
        if actual != encoded:
            raise GitBundleError('MINGIT_MANIFEST_DIFFERS_FROM_ARCHIVE')
        expected_files = {member.path: (member.byte_count, member.sha256) for member in members}
        expected_files['source.zip'] = (ARCHIVE_BYTES, ARCHIVE_SHA256)
        expected_files['manifest.json'] = (len(encoded), hashlib.sha256(encoded).hexdigest())
        expected_directories = set()
        for info, path in inventory:
            parts = path.split('/')
            count = len(parts) if info.is_dir() else len(parts) - 1
            expected_directories.update('/'.join(parts[:length]) for length in range(1, count + 1))
        _verify_package_tree(root, expected_files, expected_directories)
        _verify_pe_x64(root / 'cmd/git.exe')
        return len(members), expanded, hashlib.sha256(encoded).hexdigest()
