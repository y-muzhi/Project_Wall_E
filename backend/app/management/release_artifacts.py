"""Read-only verification of the fixed application and browser artifact closure."""

from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import sys

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    decode,
    exact,
    no_acl,
    protected_directory,
    relative,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

MANIFEST = 'release-manifest.v1.json'
INDEX_LIMIT = 4 * 1024 * 1024
INVALID = 'RELEASE_MANIFEST_INVALID'
MISMATCH = 'RELEASE_ARTIFACT_MISMATCH'
FILE_MODES = {'0444': 0o444, '0555': 0o555}
MANIFEST_FIELDS = (
    'format_version',
    'release_id',
    'source_commit',
    'target_os',
    'target_arch',
    'application_index_ref',
    'frontend_index_ref',
    'runtime_manifest_sha256',
    'schema_manifest_sha256',
    'resource_refs',
    'binding_protocol',
    'management_protocol',
    'maintenance_contract',
    'compatibility_refs',
    'verification_refs',
)


def snapshot_file(path, expected_mode, expected_bytes=None, *, capture=False, copy_to=None):
    with protected_directory(path.parent) as parent:
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path.name, flags, dir_fd=parent)
        with os.fdopen(fd, 'rb') as reader:
            before = os.fstat(fd)
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == 0
                and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == expected_mode
                and (expected_bytes is None or before.st_size == expected_bytes)
                and (not capture or 0 < before.st_size <= INDEX_LIMIT),
                MISMATCH,
            )
            no_acl(fd)
            hashed = sha256()
            size = 0
            content = bytearray() if capture else None
            while block := reader.read(128 * 1024):
                size += len(block)
                require(size <= before.st_size, MISMATCH)
                hashed.update(block)
                if content is not None:
                    content.extend(block)
                if copy_to is not None:
                    copy_to.write(block)
            after = os.fstat(fd)
            require(
                size == before.st_size
                and (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns),
                MISMATCH,
            )
            return hashed.hexdigest(), None if content is None else bytes(content)


def index_entries(index, role):
    exact(index, ('format_version', 'role', 'files'), INVALID)
    require(
        type(index['format_version']) is int
        and index['format_version'] == 1
        and index['role'] == role
        and type(index['files']) is list
        and index['files'],
        INVALID,
    )
    entries = {}
    directories = set()
    for row in index['files']:
        exact(row, ('path', 'mode', 'bytes', 'sha256'), INVALID)
        key = row['path']
        locator = relative(key, INVALID)
        require(
            key not in entries
            and row['mode'] in FILE_MODES
            and type(row['bytes']) is int
            and 0 <= row['bytes'] <= MAX_REVISION
            and sha_value(row['sha256']),
            INVALID,
        )
        entries[key] = (FILE_MODES[row['mode']], row['bytes'], row['sha256'])
        directories.update(str(parent) for parent in locator.parents if str(parent) != '.')
    require(list(entries) == sorted(entries, key=lambda key: key.encode('utf-8')), INVALID)
    require(not (set(entries) & directories), INVALID)
    return entries, directories


def indexed_files(index, root, role):
    entries, directories = index_entries(index, role)

    def report_error(error):
        raise error

    checked = set()
    for directory, children, files in os.walk(root, followlinks=False, onerror=report_error):
        directory = Path(directory)
        with protected_directory(directory):
            pass
        require(
            all(
                (directory / child).relative_to(root).as_posix() in directories
                for child in children
            ),
            MISMATCH,
        )
        for name in children:
            require(not (directory / name).is_symlink(), MISMATCH)
        for name in files:
            path = directory / name
            key = path.relative_to(root).as_posix()
            require(key in entries, MISMATCH)
            mode, size, expected = entries[key]
            actual, _ = snapshot_file(path, mode, size)
            require(actual == expected, MISMATCH)
            checked.add(key)
    require(checked == set(entries), MISMATCH)
    return len(entries)


def external_references(values):
    require(type(values) is list, INVALID)
    identifiers = set()
    for item in values:
        exact(item, ('ref', 'sha256'), INVALID)
        name = item['ref']
        require(
            type(name) is str
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.-]{0,159}', name) is not None
            and all(part not in ('', '.', '..') for part in name.split('/'))
            and name not in identifiers
            and sha_value(item['sha256']),
            INVALID,
        )
        identifiers.add(name)


def verify_release(anchor, expected_manifest, actual_runtime):
    receipt, _manifest = verify_release_details(anchor, expected_manifest, actual_runtime)
    return receipt


def verify_release_details(anchor, expected_manifest, actual_runtime):
    require(
        anchor.is_absolute()
        and anchor.name == MANIFEST
        and sha_value(expected_manifest)
        and sha_value(actual_runtime),
        INVALID,
    )
    observed, raw = snapshot_file(anchor, 0o444, capture=True)
    require(observed == expected_manifest, MISMATCH)
    manifest = exact(decode(raw, INVALID), MANIFEST_FIELDS, INVALID)
    require(
        all(
            type(manifest[key]) is int and manifest[key] == 1
            for key in (
                'format_version',
                'binding_protocol',
                'management_protocol',
                'maintenance_contract',
            )
        )
        and uuid_value(manifest['release_id'])
        and sha_value(manifest['schema_manifest_sha256']),
        INVALID,
    )
    commit = manifest['source_commit']
    require(
        type(commit) is str and len(commit) in (40, 64) and any(char != '0' for char in commit),
        INVALID,
    )
    git_oid(commit, 'sha1' if len(commit) == 40 else 'sha256')
    require(
        manifest['target_os'] == sys.platform
        and manifest['target_arch'] == os.uname().machine
        and manifest['runtime_manifest_sha256'] == actual_runtime,
        'RELEASE_PLATFORM_MISMATCH',
    )
    for key in ('resource_refs', 'compatibility_refs', 'verification_refs'):
        external_references(manifest[key])
    root = anchor.parent
    roles = ('application', 'frontend')
    members = {MANIFEST, *roles, *(role + '-index.v1.json' for role in roles)}
    require({path.name for path in root.iterdir()} == members, MISMATCH)
    counts = {}
    for role in roles:
        spec = exact(manifest[role + '_index_ref'], ('path', 'sha256', 'bytes'), INVALID)
        require(
            spec['path'] == role + '-index.v1.json'
            and sha_value(spec['sha256'])
            and type(spec['bytes']) is int
            and 1 <= spec['bytes'] <= INDEX_LIMIT,
            INVALID,
        )
        index_digest, index = snapshot_file(root / spec['path'], 0o444, spec['bytes'], capture=True)
        require(index_digest == spec['sha256'], MISMATCH)
        counts[role] = indexed_files(decode(index, INVALID), root / role, role)
    require(snapshot_file(anchor, 0o444, capture=True)[0] == observed, MISMATCH)
    return {
        'status': 'RELEASE_ARTIFACTS_VERIFIED',
        'release_id': manifest['release_id'],
        'manifest_sha256': expected_manifest,
        'source_commit': commit,
        'target_os': manifest['target_os'],
        'target_arch': manifest['target_arch'],
        'runtime_manifest_sha256': actual_runtime,
        'schema_manifest_sha256': manifest['schema_manifest_sha256'],
        'application_files': counts['application'],
        'frontend_files': counts['frontend'],
        'verification_state': 'NOT_EVALUATED',
    }, manifest
