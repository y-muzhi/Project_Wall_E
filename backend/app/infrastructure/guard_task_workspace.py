"""Bind one workspace publication to the original Guard directory and writer witness."""

from contextlib import contextmanager
from dataclasses import asdict
from time import monotonic

from backend.app.shared.validation import strict_json_object

from .content_paths import ContentPathError
from .guard_action_journal import GuardActionJournal
from .guard_request_header import parse_guard_request_header
from .guard_task_basis_protocol import _hex
from .guard_task_files import (
    _publish_original,
    _read_original,
    _verify_held_directories,
    find_task_file_reservation,
)
from .guard_task_workspace_protocol import WorkspaceStageResult, decode_workspace_stage
from .runtime_launch_journal import LaunchFenceError, _bytes
from .windows_config_source import ConfigReadError
from .windows_local_paths import PathBoundaryError, local_absolute_path
from .windows_private_package import PackageSecurityError
from .windows_private_record import PrivateRecordError
from .windows_process import ProcessObservationError
from .windows_stdio import StdioBoundaryError
from .windows_task_workspace_lease import GuardWorkspaceWriteLease, WorkspaceWriteError
from .windows_task_workspace_tree import hold_task_workspace_tree, observe_task_workspace_tree

_MAX_RECORD_BYTES = 16384


class _WorkspacePublication:
    def __init__(self, directories, manifest):
        self._dirs, self._manifest = directories, manifest
        self._journal = directories._actions._journal
        self._destination = directories.workspace_destination()
        self._lease = GuardWorkspaceWriteLease()
        self._finish_requested = False

    def _target(self):
        return {
            'binding_ref': self._destination.binding_ref,
            'manifest_sha256': self._manifest,
            'directory_nonce': self._destination.directory_nonce,
            'directory': asdict(self._destination.directory),
        }

    def _intent(self):
        return {
            'schema_version': 1,
            'scope': self._dirs.scope.key,
            'owner_epoch': self._dirs._original.owner_epoch,
            'prepare_input_sha256': self._dirs._original.input_sha256,
            'workspace_nonce': self._dirs._workspace_nonce,
            'target': self._target(),
        }

    def _name(self, phase):
        return self._dirs.scope.key + '.task-workspace-' + phase + '.json'

    def _read(self, phase):
        return _read_original(self._journal._package, self._name(phase), _MAX_RECORD_BYTES)

    def _publish(self, phase, value):
        _publish_original(
            self._journal._package, self._name(phase), _bytes(value), _MAX_RECORD_BYTES
        )

    def offer(self, checkpoint):
        with self._journal._gate:
            checkpoint()
            if self._read('write') is not None or self._read('published') is not None:
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_ALREADY_OFFERED')
            self._publish('write', self._intent())
            if self._read('write') != _bytes(self._intent()):
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITE_INTENT_UNVERIFIED')
        return {**self._target(), 'writer': self._lease.offer(self._dirs._controller, checkpoint)}

    def complete(self, tree, checkpoint):
        if self._finish_requested:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_FINISH_ALREADY_REQUESTED')
        self._finish_requested = True
        self._verify_tree(tree, checkpoint)
        with self._journal._gate:
            checkpoint()
            self._publish('published', {'intent': self._intent(), 'tree_identity_sha256': tree})
        return self._receipt()

    def _verify_original(self):
        if self._dirs.workspace_destination() != self._destination or self._read('write') != _bytes(
            self._intent()
        ):
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_DIRECTORY_DIFFERS')
        self._lease.verify_closed()

    def _receipt(self):
        raw = self._read('published')
        if raw is None:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_PUBLICATION_UNVERIFIED')
        data = strict_json_object(raw)
        tree = data.get('tree_identity_sha256')
        if not _hex(tree, 64) or raw != _bytes(
            {'intent': self._intent(), 'tree_identity_sha256': tree}
        ):
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_PUBLICATION_DIFFERS')
        return {**self._target(), 'tree_identity_sha256': tree}

    def _verify_tree(self, expected, checkpoint):
        self._verify_original()
        directory = self._destination.directory
        try:
            actual = observe_task_workspace_tree(
                local_absolute_path(directory.canonical_path), directory, checkpoint
            )
        except (ConfigReadError, ContentPathError, OSError, PathBoundaryError) as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_TREE_UNVERIFIED') from error
        self._verify_original()
        if actual != expected:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_TREE_DIFFERS')
        checkpoint()

    def verify(self, checkpoint):
        receipt = self._receipt()
        self._verify_tree(receipt['tree_identity_sha256'], checkpoint)
        return receipt

    @contextmanager
    def hold_launch_tree(self, checkpoint):
        self._verify_original()
        destination = self._destination.directory
        tree = self._receipt()['tree_identity_sha256']
        try:
            with hold_task_workspace_tree(
                local_absolute_path(destination.canonical_path), destination, tree, checkpoint
            ):
                checkpoint()
                yield tree
                self._verify_original()
        except (ConfigReadError, ContentPathError, OSError, PathBoundaryError) as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_LAUNCH_TREE_UNVERIFIED') from error

    def close(self):
        self._lease.close()


def run_guard_task_workspace(owner, request, *, peer, program, timeout_ms, cancelled):
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_REQUEST_DIFFERS')
    stage, reference, original_digest, manifest, tree = decode_workspace_stage(request)
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=interrupted
    ) as registry:
        scope = request.target_scope
        journal = registry._journal
        with journal._scope(scope):
            reservation = find_task_file_reservation(GuardActionJournal(journal), scope)
            if reservation is None:
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_RESERVATION_REQUIRED')
            original, basis_digest = reservation
            if (
                reference != original.allocated_binding_ref
                or original_digest != original.input_sha256
                or original.owner_epoch != request.owner_epoch
            ):
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_BINDING_DIFFERS')
            directories = owner._task_directories.get(scope.key)
            try:
                _verify_held_directories(journal, original, basis_digest, directories, interrupted)
                if manifest != directories._workspace_manifest_sha256:
                    raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_MANIFEST_DIFFERS')

                def checkpoint():
                    directories._require_open(interrupted)

                publication = directories._workspace_publication
                if stage == 'BEGIN':
                    if publication is not None:
                        raise WorkspaceWriteError('ORIGINAL_WORKSPACE_WRITER_ALREADY_OFFERED')
                    publication = _WorkspacePublication(directories, manifest)
                    directories._workspace_publication = publication
                    result = publication.offer(checkpoint)
                elif publication is None:
                    raise WorkspaceWriteError('ORIGINAL_WORKSPACE_PUBLICATION_UNVERIFIED')
                elif stage == 'FINISH':
                    result = publication.complete(tree, checkpoint)
                else:
                    result = publication.verify(checkpoint)
                checkpoint()
                return WorkspaceStageResult(result)
            except (
                LaunchFenceError,
                OSError,
                PackageSecurityError,
                PathBoundaryError,
                PrivateRecordError,
                ProcessObservationError,
                StdioBoundaryError,
            ) as error:
                retained = getattr(error, 'retained_owner', None)
                publication = None if directories is None else directories._workspace_publication
                if retained is not None and (
                    publication is None or retained is not publication._lease
                ):
                    raise
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_UNVERIFIED') from error
