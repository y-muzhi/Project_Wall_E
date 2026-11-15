"""Read-attributes-only handles for the original repository metadata cohort."""

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field

from .git_repository_location import RepositoryLocationLease
from .runtime_launch_journal import LaunchScope
from .windows_attribute_handles import GuardAttributeHandles
from .windows_local_paths import FileIdentity, local_absolute_path
from .windows_process import NativeProcessIdentity, ObservedProcess
from .windows_stdio import _handle, _handle_text

ROLES = ('root', 'git_directory', 'common_directory')


class MetadataDirectoryError(RuntimeError):
    def __init__(self, code, native_error=None):
        self.code = code
        self.native_error = native_error
        super().__init__(code)


@dataclass(frozen=True)
class DirectoryHandle:
    file: FileIdentity = field(repr=False)
    handle: str = field(repr=False)


@dataclass(frozen=True)
class MetadataDirectoryExport:
    owner: NativeProcessIdentity = field(repr=False)
    scope: LaunchScope
    root: DirectoryHandle = field(repr=False)
    git_directory: DirectoryHandle = field(repr=False)
    common_directory: DirectoryHandle = field(repr=False)
    expected_bare: bool
    linked: bool
    location_sha256: str


def _digest(value, size):
    return type(value) is str and re.fullmatch(f'[0-9a-f]{{{size}}}', value) is not None


def _directory_handle(value):
    if type(value) is not DirectoryHandle or type(value.file) is not FileIdentity:
        raise MetadataDirectoryError('ORIGINAL_METADATA_DIRECTORY_EXPORT_INVALID')
    identity = value.file
    if (
        identity.is_directory is not True
        or identity.filesystem != 'NTFS'
        or type(identity.canonical_path) is not str
        or not _digest(identity.volume_serial, 16)
        or not _digest(identity.file_id, 32)
    ):
        raise MetadataDirectoryError('ORIGINAL_METADATA_DIRECTORY_IDENTITY_INVALID')
    local_absolute_path(identity.canonical_path)
    return _handle(value.handle)


def _verify_export(value):
    if (
        type(value) is not MetadataDirectoryExport
        or type(value.scope) is not LaunchScope
        or type(value.owner) is not NativeProcessIdentity
        or type(value.expected_bare) is not bool
        or type(value.linked) is not bool
        or not _digest(value.location_sha256, 64)
    ):
        raise MetadataDirectoryError('ORIGINAL_METADATA_DIRECTORY_COHORT_INVALID')
    for role in ROLES:
        _directory_handle(getattr(value, role))
    root, git, common = (getattr(value, role).file for role in ROLES)
    if (
        value.expected_bare != (root == git == common)
        or value.linked != (git != common)
        or (not value.expected_bare and root in (git, common))
    ):
        raise MetadataDirectoryError('ORIGINAL_METADATA_DIRECTORY_LAYOUT_DIFFERS')


@contextmanager
def export_metadata_directories(location, scope):
    """Keep the backend's original directory and ancestor pins during handoff."""
    if type(location) is not RepositoryLocationLease or type(scope) is not LaunchScope:
        raise TypeError('Original repository location and launch scope required')
    with location.hold() as original:
        root, git, common = (
            DirectoryHandle(guard.verify(), _handle_text(guard._held[-1][0]))
            for guard in (location._root, location._git, location._common)
        )
        if (root.file, git.file, common.file) != (
            original.root,
            original.git_directory,
            original.common_directory,
        ):
            raise MetadataDirectoryError('ORIGINAL_METADATA_DIRECTORY_EXPORT_CHANGED')
        with ObservedProcess(os.getpid()) as current:
            export = MetadataDirectoryExport(
                current.identity,
                scope,
                root,
                git,
                common,
                original.expected_bare,
                original.linked,
                original.fingerprint_sha256,
            )
        _verify_export(export)
        yield export
        if location.verify() != original:
            raise MetadataDirectoryError('ORIGINAL_METADATA_DIRECTORY_EXPORT_CHANGED')


class GuardMetadataDirectories(GuardAttributeHandles):
    """Guard ownership of the exact original repository directories."""

    def __init__(self, controller, export, *, scope):
        _verify_export(export)
        if type(scope) is not LaunchScope or export.scope != scope:
            raise MetadataDirectoryError('ORIGINAL_METADATA_DIRECTORY_SCOPE_DIFFERS')
        self._export = export
        entries = {
            role: (getattr(export, role).file, getattr(export, role).handle) for role in ROLES
        }
        super().__init__(
            controller,
            export.owner,
            entries,
            error_type=MetadataDirectoryError,
            error_prefix='ORIGINAL_METADATA_DIRECTORY',
        )

    def verify(self):
        super().verify()
        return self._export
