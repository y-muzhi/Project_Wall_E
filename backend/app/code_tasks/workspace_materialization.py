"""Materialize a fixed baseline in the caller's original private allocation."""

import os
import re
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.infrastructure.content_manifest import ContentEntry
from backend.app.infrastructure.content_paths import ContentPathIndex
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_local_paths import FileIdentity, LocalPathGuard
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.shared.validation import strict_integer, strict_json_object


class WorkspaceMaterializationError(RuntimeError):
    code = 'CONTENT_NOT_READY'


@dataclass(frozen=True)
class PublishedWorkspace:
    snapshot_id: int
    location_key: str
    directory: FileIdentity = field(repr=False)
    entries: tuple[ContentEntry, ...] = field(repr=False)


def _same_file(actual, expected):
    return (
        actual.volume_serial == expected.volume_serial
        and actual.file_id == expected.file_id
        and actual.is_directory == expected.is_directory
    )


@dataclass(frozen=True)
class FixedWorkspaceSource:
    path: Path = field(repr=False)
    directory: FileIdentity = field(repr=False)
    entries: tuple[ContentEntry, ...] = field(repr=False)
    manifest_sha256: str


def read_workspace_manifest(parent, allocation, receipt, checkpoint, limits):
    data = strict_json_object(receipt)
    expected_keys = {'workspace_id', 'directory', 'content_sha256', 'tree_record'}
    if set(data) != expected_keys or data['workspace_id'] != allocation.workspace_id:
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TREE_RECORD_REQUIRED')
    reference = data['tree_record']
    name = allocation.nonce + '.workspace-tree.json'
    if (
        set(reference) != {'filename', 'sha256', 'byte_count', 'file'}
        or reference['filename'] != name
        or reference['sha256'] != data['content_sha256']
    ):
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TREE_RECORD_DIFFERS')
    file = parent.verify_member(name, directory=False)
    if file != FileIdentity(**reference['file']):
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TREE_FILE_DIFFERS')
    length = strict_integer(reference['byte_count'], 'byte_count')
    with LockedFileSource(parent.path / name, max_file_bytes=length, expected_file=file) as lease:
        observed = lease.snapshot
        if observed.byte_count != length or observed.sha256 != reference['sha256']:
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TREE_BYTES_DIFFER')
        manifest = strict_json_object(observed.raw)
    if set(manifest) != {'entries'} or type(manifest['entries']) is not list:
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TREE_SHAPE_DIFFERS')
    if len(manifest['entries']) > limits['max_snapshot_files']:
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_FILE_LIMIT_EXCEEDED')
    entries = [ContentEntry(**entry) for entry in manifest['entries']]
    total = 0
    for entry in entries:
        checkpoint()
        length = strict_integer(entry.byte_count, 'byte_count', minimum=0)
        total += length
        if length > limits['max_file_bytes'] or total > limits['max_snapshot_bytes']:
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_BYTES_LIMIT_EXCEEDED')
        if type(entry.sha256) is not str or re.fullmatch('[a-f0-9]{64}', entry.sha256) is None:
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_ENTRY_SHA_DIFFERS')
    target = parent.path / allocation.key
    expected = FileIdentity(**data['directory'])
    return FixedWorkspaceSource(target, expected, tuple(entries), data['content_sha256'])


def _scan_workspace_tree(
    path,
    identity,
    entries,
    checkpoint,
    verify_member,
    *,
    file_ids=None,
    directory_ids=None,
    consume=None,
):
    namespace = ContentPathIndex(materialization_root=path)
    files = {}
    directories = set()
    for entry in entries:
        namespace.add_file(entry.path, entry.mode)
        files[entry.path] = entry
        parts = entry.path.split('/')
        directories.update('/'.join(parts[:count]) for count in range(1, len(parts)))

    seen_files, seen_dirs = {}, {}
    pending = [('', path, identity)]
    while pending:
        prefix, directory, directory_id = pending.pop()
        with (
            LocalPathGuard(directory, directory=True) as held,
            os.scandir(directory) as listing,
        ):
            if not _same_file(held.verify(), directory_id):
                raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_SUBDIRECTORY_DIFFERS')
            for child in listing:
                checkpoint()
                relative = prefix + child.name
                if relative in directories:
                    member = verify_member(relative, directory=True)
                    if directory_ids is not None and not _same_file(
                        member, directory_ids[relative]
                    ):
                        raise WorkspaceMaterializationError(
                            'ORIGINAL_WORKSPACE_SUBDIRECTORY_DIFFERS'
                        )
                    seen_dirs[relative] = member
                    pending.append((relative + '/', path / relative, member))
                    continue
                entry = files.get(relative)
                if entry is None:
                    raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TREE_DIFFERS')
                file = verify_member(relative, directory=False)
                if file_ids is not None and not _same_file(file, file_ids[relative]):
                    raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_FILE_DIFFERS')
                with LockedFileSource(
                    path / relative,
                    max_file_bytes=max(1, entry.byte_count),
                    expected_file=file,
                ) as lease:
                    blob = lease.snapshot
                    if blob.byte_count != entry.byte_count or blob.sha256 != entry.sha256:
                        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_BYTES_DIFFER')
                    if consume is not None:
                        consume(entry, blob.raw)
                seen_files[relative] = file
    if seen_files.keys() != files.keys() or seen_dirs.keys() != directories:
        raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TREE_DIFFERS')
    checkpoint()
    return seen_files, seen_dirs


def verify_workspace_tree(
    path,
    identity,
    entries,
    checkpoint,
    *,
    file_ids=None,
    directory_ids=None,
    consume=None,
):
    with PrivatePackageGuard(path) as package:
        if not _same_file(package.verify(), identity):
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_DIRECTORY_DIFFERS')
        _scan_workspace_tree(
            path,
            identity,
            entries,
            checkpoint,
            package.verify_member,
            file_ids=file_ids,
            directory_ids=directory_ids,
            consume=consume,
        )
        return package.verify()


class FixedWorkspaceStage:
    """One pre-reserved nonce. Failed or uncertain allocations stay private."""

    def __init__(self, parent, nonce, check_active, *, record_stage=None):
        if (
            type(parent) is not PrivatePackageGuard
            or parent.is_control_git_read_package
            or type(nonce) is not str
            or re.fullmatch('[0-9a-f]{32}', nonce) is None
            or not callable(check_active)
            or (record_stage is not None and not callable(record_stage))
        ):
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_ALLOCATION_REQUIRED')
        self._parent, self._check_active = parent, check_active
        self._parent_identity = parent.verify()
        self._stage = parent.path / ('staging-' + nonce)
        self.target = parent.path / ('working-' + nonce)
        self._paths = ContentPathIndex(materialization_root=self.target)
        self._entries = {}
        self._directories = {}
        self._files = {}
        self._used = False
        self._checkpoint()
        try:
            self.target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_TARGET_ALREADY_EXISTS')
        create_private_package(self._stage)
        with PrivatePackageGuard(self._stage) as package:
            self._stage_identity = package.verify()
            if record_stage is not None:
                record_stage(self._stage_identity)

    def _checkpoint(self):
        if self._check_active() is not None or self._parent.verify() != self._parent_identity:
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_ALLOCATION_UNVERIFIED')

    def consume(self, entry, raw):
        self._checkpoint()
        if self._used or type(entry) is not ContentEntry or type(raw) is not bytes:
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_BLOB_REQUIRED')
        self._paths.add_file(entry.path, entry.mode)
        parts = entry.path.split('/')
        with PrivatePackageGuard(self._stage) as package, ExitStack() as directories:
            if package.verify() != self._stage_identity:
                raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_STAGE_DIFFERS')
            for count in range(1, len(parts)):
                relative = '/'.join(parts[:count])
                path = self._stage / relative
                if relative not in self._directories:
                    path.mkdir()
                    self._directories[relative] = package.verify_member(relative, directory=True)
                guard = directories.enter_context(LocalPathGuard(path, directory=True))
                if guard.verify() != self._directories[relative]:
                    raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_SUBDIRECTORY_DIFFERS')
            with self._stage.joinpath(*parts).open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                self._files[entry.path] = package.verify_member(entry.path, directory=False)
            self._entries[entry.path] = entry

    def _verify_tree(self, path, identity):
        return verify_workspace_tree(
            path,
            identity,
            self._entries.values(),
            self._checkpoint,
            file_ids=self._files,
            directory_ids=self._directories,
        )

    def publish_entries(self, entries, verify_active_source):
        self._checkpoint()
        if (
            self._used
            or tuple(sorted(self._entries.values(), key=lambda entry: entry.path.encode('utf-8')))
            != entries
        ):
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_FIXED_ENTRIES_DIFFER')
        self._used = True
        self._verify_tree(self._stage, self._stage_identity)
        verify_active_source()
        self._checkpoint()
        # This component requires NTFS. Windows rename fails if the target exists.
        os.rename(self._stage, self.target)
        identity = self._verify_tree(self.target, self._stage_identity)
        self._checkpoint()
        verify_active_source()
        return identity

    def publish(self, result, verify_active_source):
        identity = self.publish_entries(result.entries, verify_active_source)
        return PublishedWorkspace(result.snapshot['id'], self.target.name, identity, result.entries)
