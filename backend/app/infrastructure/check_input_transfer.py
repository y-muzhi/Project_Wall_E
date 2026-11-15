"""Transfer only verified candidate bytes through a bound read-only Windows handle."""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from struct import Struct
from time import monotonic

from backend.app.shared.validation import strict_json_object

from .check_runner_bundle import valid_sha256
from .content_manifest import (
    ContentLimits,
    decode_manifest,
    encode_manifest,
    fixed_entries_sha256,
    manifest_sha256,
)
from .content_package import verify_candidate_package
from .content_package_publish import PublishedCandidate
from .guard_git_config_source import _copy_original_read_source
from .runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope, TestingLaunchScope
from .windows_config_source import LockedFileSource
from .windows_local_paths import FileIdentity, local_absolute_path
from .windows_private_package import PrivatePackageGuard
from .windows_process import NativeProcessIdentity, ObservedProcess
from .windows_stdio import _handle, _handle_text
from .windows_task_directories import SnapshotCheckInput

_HEADER = Struct('<8sQ')
_MAGIC = b'WALLECK1'
_MAX_TOTAL_BYTES = 2 * 1024**3 + 1024**2 + _HEADER.size


class CheckInputTransferError(LaunchOutcomeUnknown):
    pass


@dataclass(frozen=True)
class CheckInputReadDescriptor:
    owner: NativeProcessIdentity = field(repr=False)
    scope: LaunchScope
    file: FileIdentity = field(repr=False)
    sha256: str
    byte_count: int
    handle: str = field(repr=False)


@dataclass(frozen=True)
class SnapshotCheckSource:
    target: SnapshotCheckInput
    manifest: object
    read_original_files: object = field(repr=False)


def _snapshot_manifest_matches(target, manifest):
    return (
        manifest.content_tree_oid == target.tree_oid
        and manifest.object_format == target.object_format
        and manifest.content_profile_version_id == target.content_profile_version_id
        and fixed_entries_sha256(manifest.entries) == target.content_sha256
    )


class CheckInputExport:
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self._offered = self._received = False

    def mark_offered(self):
        if self._offered:
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_ALREADY_OFFERED')
        self._offered = True

    def mark_received(self, scope, sha256):
        if not self._offered or (scope, sha256) != (self.descriptor.scope, self.descriptor.sha256):
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_RECEIPT_DIFFERS')
        self._received = True


def _name(scope):
    original = scope.key if type(scope) is TestingLaunchScope else scope.nonce
    return 'check-input-' + original + '.bin'


def _maximum(limits):
    if type(limits) is not ContentLimits:
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_LIMITS_REQUIRED')
    return min(
        _MAX_TOTAL_BYTES, _HEADER.size + limits.max_manifest_bytes + limits.max_snapshot_bytes
    )


def _delete_owned(parent, member, identity):
    from .windows_task_directory_release import OwnedTreeDeletion, OwnedTreeEntry

    deletion = OwnedTreeDeletion(parent.verify())
    if parent.verify_member(member, directory=False) != identity:
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_CLEANUP_IDENTITY_DIFFERS')
    try:
        deletion.delete(OwnedTreeEntry(identity, parent.verify()), lambda: None)
    finally:
        deletion.close()


@contextmanager
def export_check_input(parent, scope, candidate, *, limits, git_limits, active, on_allocate=None):
    """Create one original capsule, with no overwrite or cleanup of an unknown send."""
    if (
        type(parent) is not PrivatePackageGuard
        or parent.is_control_git_read_package
        or not isinstance(scope, LaunchScope)
        or type(candidate) not in (PublishedCandidate, SnapshotCheckSource)
        or not callable(active)
        or (on_allocate is not None and not callable(on_allocate))
    ):
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_REQUIRED')
    parent_identity = parent.verify()
    started = monotonic()

    def checkpoint():
        if active() is not None or parent.verify() != parent_identity:
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_FENCED')

    name = _name(scope)
    checkpoint()
    if type(candidate) is SnapshotCheckSource:
        candidate.target.require_scope(scope)
        manifest = candidate.manifest
        if not callable(candidate.read_original_files) or not _snapshot_manifest_matches(
            candidate.target, manifest
        ):
            raise CheckInputTransferError('ORIGINAL_SNAPSHOT_CHECK_EXPORT_DIFFERS')
    else:
        candidate_path = local_absolute_path(candidate.directory.canonical_path)
        output_path = parent.path / name
        if candidate_path.is_relative_to(output_path) or output_path.is_relative_to(candidate_path):
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_SOURCE_OVERLAP')
        manifest = candidate.seal.manifest
    raw = encode_manifest(manifest, limits)
    total = _HEADER.size + len(raw) + manifest.byte_count
    if total > _maximum(limits) or (
        type(candidate) is PublishedCandidate
        and manifest_sha256(raw) != candidate.seal.manifest_sha256
    ):
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_MANIFEST_DIFFERS')
    identity = export = None
    try:
        with (parent.path / name).open('xb') as output:
            identity = parent.verify_member(name, directory=False)
            if on_allocate is not None:
                on_allocate(identity)
            output.write(_HEADER.pack(_MAGIC, len(raw)))
            output.write(raw)
            position = 0

            def append(entry, data):
                nonlocal position
                checkpoint()
                if (
                    position >= len(manifest.entries)
                    or manifest.entries[position] != entry
                    or len(data) != entry.byte_count
                    or sha256(data).hexdigest() != entry.sha256
                    or output.write(data) != len(data)
                ):
                    raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_WRITE_INCOMPLETE')
                position += 1

            if type(candidate) is SnapshotCheckSource:
                candidate.read_original_files(append, checkpoint)
            else:
                _copy_candidate(
                    candidate, parent.path / name, limits, git_limits, started, checkpoint, append
                )
            if position != len(manifest.entries):
                raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_WRITE_INCOMPLETE')
            output.flush()
            os.fsync(output.fileno())
        with (
            LockedFileSource(
                parent.path / name,
                max_file_bytes=total,
                expected_file=identity,
                capture_raw=False,
                checkpoint=checkpoint,
            ) as source,
            ObservedProcess(os.getpid()) as backend,
        ):
            snapshot = source.snapshot
            if snapshot.byte_count != total:
                raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_SIZE_DIFFERS')
            export = CheckInputExport(
                CheckInputReadDescriptor(
                    backend.identity,
                    scope,
                    snapshot.file,
                    snapshot.sha256,
                    snapshot.byte_count,
                    _handle_text(source._handle),
                )
            )
            checkpoint()
            yield export
            checkpoint()
    finally:
        if identity is not None and (export is None or not export._offered or export._received):
            _delete_owned(parent, name, identity)


def _copy_candidate(candidate, output, limits, git_limits, started, checkpoint, consume):
    with PrivatePackageGuard(candidate.directory.canonical_path) as package:
        if package.verify() != candidate.directory or package.path.name != (
            candidate.seal.binding.package_name(staged=False)
        ):
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_PACKAGE_DIFFERS')
        if package.path.is_relative_to(output) or output.is_relative_to(package.path):
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_SOURCE_OVERLAP')
        verify_candidate_package(
            package,
            candidate.seal.binding,
            limits=limits,
            git_limits=git_limits,
            started_at=started,
            active=checkpoint,
            expected=candidate.seal,
            consume_file=consume,
        )


class _CheckInputDecoder:
    def __init__(self, limits, expected_sha256, materialization_root, consume):
        self._limits = limits
        self._expected = expected_sha256
        self._root = materialization_root
        self._consume = consume
        self._buffer = bytearray()
        self._manifest_bytes = None
        self.manifest = None
        self._next = 0

    def feed(self, chunk):
        self._buffer.extend(chunk)
        if self._manifest_bytes is None:
            if len(self._buffer) < _HEADER.size:
                return
            magic, size = _HEADER.unpack_from(self._buffer)
            if magic != _MAGIC or not 1 <= size <= self._limits.max_manifest_bytes:
                raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_HEADER_INVALID')
            self._manifest_bytes = size
            del self._buffer[: _HEADER.size]
        if self.manifest is None:
            if len(self._buffer) < self._manifest_bytes:
                return
            raw = bytes(self._buffer[: self._manifest_bytes])
            del self._buffer[: self._manifest_bytes]
            baseline = type(self._expected) is SnapshotCheckInput
            if not baseline and manifest_sha256(raw) != self._expected:
                raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_MANIFEST_DIFFERS')
            document = strict_json_object(raw)
            self.manifest = decode_manifest(
                raw,
                limits=self._limits,
                expected_sha256=None if baseline else self._expected,
                expected_format=self._expected.object_format
                if baseline
                else document.get('object_format'),
                expected_profile_version_id=(
                    self._expected.content_profile_version_id
                    if baseline
                    else document.get('content_profile_version_id')
                ),
                materialization_root=self._root,
            )
            if baseline and not _snapshot_manifest_matches(self._expected, self.manifest):
                raise CheckInputTransferError('ORIGINAL_SNAPSHOT_CHECK_EXPORT_DIFFERS')
        entries = self.manifest.entries
        while self._next < len(entries):
            entry = entries[self._next]
            if len(self._buffer) < entry.byte_count:
                return
            raw = bytes(self._buffer[: entry.byte_count])
            del self._buffer[: entry.byte_count]
            if sha256(raw).hexdigest() != entry.sha256:
                raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_BLOB_DIFFERS')
            self._consume(entry, raw)
            self._next += 1
        if self._buffer:
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_TRAILING_DATA')

    def finish(self):
        if self.manifest is None or self._next != len(self.manifest.entries) or self._buffer:
            raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_INCOMPLETE')
        return self.manifest


def import_check_input(
    controller,
    descriptor,
    parent,
    scope,
    expected_sha256,
    *,
    limits,
    materialization_root,
    checkpoint,
    consume,
):
    """Guard never opens the supplied backend path for data."""
    if (
        type(descriptor) is not CheckInputReadDescriptor
        or type(parent) is not FileIdentity
        or not parent.is_directory
        or parent.filesystem != 'NTFS'
        or not isinstance(scope, LaunchScope)
        or descriptor.scope != scope
        or type(descriptor.file) is not FileIdentity
        or descriptor.file.is_directory
        or descriptor.file.volume_serial != parent.volume_serial
        or descriptor.file.filesystem != 'NTFS'
        or type(descriptor.byte_count) is not int
        or not _HEADER.size < descriptor.byte_count <= _maximum(limits)
        or not valid_sha256(descriptor.sha256)
        or (type(expected_sha256) is not SnapshotCheckInput and not valid_sha256(expected_sha256))
        or not callable(checkpoint)
        or not callable(consume)
    ):
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_DESCRIPTOR_REQUIRED')
    if type(expected_sha256) is SnapshotCheckInput:
        expected_sha256.require_scope(scope)
    path = local_absolute_path(descriptor.file.canonical_path)
    if path != local_absolute_path(parent.canonical_path) / _name(scope):
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_PATH_DIFFERS')
    decoder = _CheckInputDecoder(limits, expected_sha256, materialization_root, consume)
    checkpoint()
    with _copy_original_read_source(
        controller,
        descriptor,
        _handle(descriptor.handle),
        scope=scope,
        max_file_bytes=descriptor.byte_count,
        source_type=LockedFileSource,
        checkpoint=checkpoint,
    ) as source:
        source.consume_verified(decoder.feed)
        manifest = decoder.finish()
    checkpoint()
    return manifest


def retire_allocated_check_input(parent, scope, original_file):
    """Caller must first prove the original receiver is closed or was never sent."""
    if type(parent) is not PrivatePackageGuard or parent.is_control_git_read_package:
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_CLEANUP_SCOPE_DIFFERS')
    name = _name(scope)
    parent.verify()
    try:
        (parent.path / name).lstat()
    except FileNotFoundError:
        return
    if (
        type(original_file) is not FileIdentity
        or original_file.is_directory
        or local_absolute_path(original_file.canonical_path) != parent.path / name
    ):
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_CLEANUP_IDENTITY_DIFFERS')
    _delete_owned(parent, name, original_file)


def retire_check_input_export(parent, descriptor, completed):
    """Delete only the held source from an original Guard scope known to be released."""
    from .project_check_result import ProjectCheckResult

    if (
        type(parent) is not PrivatePackageGuard
        or parent.is_control_git_read_package
        or type(descriptor) is not CheckInputReadDescriptor
        or type(completed) is not ProjectCheckResult
        or completed.scope != descriptor.scope
        or not valid_sha256(completed.cleanup_ref)
        or local_absolute_path(descriptor.file.canonical_path)
        != parent.path / _name(descriptor.scope)
    ):
        raise CheckInputTransferError('ORIGINAL_CHECK_EXPORT_CLEANUP_SCOPE_DIFFERS')
    retire_allocated_check_input(parent, descriptor.scope, descriptor.file)
