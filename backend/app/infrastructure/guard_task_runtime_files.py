"""Collect closed file preparation for the original authenticated TASK scope."""

from dataclasses import asdict
from time import monotonic

from .guard_action_journal import GuardActionJournal
from .guard_request_header import parse_guard_request_header
from .guard_task_files import (
    _publish_original,
    _read_original,
    _verify_held_directories,
    find_task_file_reservation,
)
from .guard_task_runtime_protocol import RuntimeFilesStageResult, decode_runtime_files_stage
from .opencode_runtime_bundle import OpenCodeRuntimeBundleError
from .runtime_launch_journal import LaunchFenceError, _bytes
from .windows_config_source import ConfigReadError
from .windows_local_paths import PathBoundaryError
from .windows_private_package import PackageSecurityError
from .windows_private_record import PrivateRecordError
from .windows_task_runtime_bundle import TaskRuntimeBundlePublication, TaskRuntimeFilesError
from .windows_task_runtime_environment import TaskRuntimeEnvironment

_MAX_RECORD_BYTES = 16384


def _closed_files(directories, checkpoint):
    group = directories._basis_group
    workspace = directories._workspace_publication
    if group is None or workspace is None:
        raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_SOURCE_FILES_UNVERIFIED')

    def check_group():
        checkpoint()
        return False

    with group.action(check_group):
        basis = group.verify()
    destination = workspace.verify(checkpoint)
    return basis.receipts_sha256, destination['tree_identity_sha256']


class _RuntimeFilePreparation:
    def __init__(self, directories, source, reference):
        self._dirs = directories
        self._journal = directories._actions._journal
        self._bundle = TaskRuntimeBundlePublication(directories, source, reference)
        self._environment = TaskRuntimeEnvironment(directories, self._bundle)
        self._intent = {
            'schema_version': 1,
            'scope': directories.scope.key,
            'owner_epoch': directories._original.owner_epoch,
            'prepare_input_sha256': directories._original.input_sha256,
            'binding_ref': directories.binding_ref,
            'runtime_bundle_ref': reference,
            'root': asdict(directories.verify()[0].file),
        }

    def _name(self, suffix):
        return self._dirs.scope.key + '.task-runtime-' + suffix + '.json'

    def _read(self, suffix):
        return _read_original(self._journal._package, self._name(suffix), _MAX_RECORD_BYTES)

    def _publish(self, suffix, raw):
        _publish_original(self._journal._package, self._name(suffix), raw, _MAX_RECORD_BYTES)

    def _evidence(self, inputs, bundle, environment):
        basis, workspace = inputs
        return {
            'binding_ref': self._dirs.binding_ref,
            'runtime_bundle_ref': bundle.runtime_bundle_ref,
            'runtime_member_count': bundle.member_count,
            'runtime_tree_identity_sha256': bundle.tree_identity_sha256,
            'environment_sha256': environment.environment_sha256,
            'basis_receipts_sha256': basis,
            'workspace_tree_identity_sha256': workspace,
        }

    def prepare(self, inputs, checkpoint, *, deadline, cancelled):
        with self._journal._gate:
            checkpoint()
            if self._read('intent') is not None or self._read('files') is not None:
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILES_ALREADY_DISPATCHED')
            raw = _bytes(self._intent)
            self._publish('intent', raw)
            if self._read('intent') != raw:
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILE_INTENT_UNVERIFIED')
        bundle = self._bundle.publish(deadline=deadline, cancelled=cancelled)
        environment = self._environment.prepare(checkpoint)
        if _closed_files(self._dirs, checkpoint) != inputs:
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_SOURCE_FILES_DIFFERS')
        result = self._evidence(inputs, bundle, environment)
        with self._journal._gate:
            checkpoint()
            self._publish('files', _bytes({'intent': self._intent, 'evidence': result}))
        return self.verify(checkpoint)

    def verify(self, checkpoint):
        raw = self._read('files')
        if raw is None or self._read('intent') != _bytes(self._intent):
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILE_EVIDENCE_UNVERIFIED')
        inputs = _closed_files(self._dirs, checkpoint)
        bundle = self._bundle.verify(checkpoint)
        environment = self._environment.verify(checkpoint)
        result = self._evidence(inputs, bundle, environment)
        if raw != _bytes({'intent': self._intent, 'evidence': result}):
            raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILE_EVIDENCE_DIFFERS')
        checkpoint()
        return result

    def close(self):
        self._environment.close()
        self._bundle.close()


def run_guard_task_runtime_files(
    owner, request, deployment, *, peer, program, timeout_ms, cancelled
):
    binding = owner.binding
    if parse_guard_request_header(request.wire, binding, peer=peer) != request:
        raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_REQUEST_DIFFERS')
    stage, reference, original_digest, bundle = decode_runtime_files_stage(request)
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
            if reservation is None or deployment is None:
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_DEPLOYMENT_REQUIRED')
            original, basis_digest = reservation
            if (
                reference != original.allocated_binding_ref
                or original_digest != original.input_sha256
                or original.owner_epoch != request.owner_epoch
            ):
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_BINDING_DIFFERS')
            directories = owner._task_directories.get(scope.key)
            try:
                _verify_held_directories(journal, original, basis_digest, directories, interrupted)
                if bundle != directories._runtime_bundle_ref or bundle != deployment.reference:
                    raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_REFERENCE_DIFFERS')

                def checkpoint():
                    directories._require_open(interrupted)

                preparation = directories._runtime_preparation
                if stage == 'PREPARE_FILES':
                    if preparation is not None:
                        raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILES_ALREADY_DISPATCHED')
                    inputs = _closed_files(directories, checkpoint)
                    preparation = _RuntimeFilePreparation(directories, deployment.source, bundle)
                    directories._runtime_preparation = preparation
                    result = preparation.prepare(
                        inputs, checkpoint, deadline=deadline, cancelled=interrupted
                    )
                elif preparation is None:
                    raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_FILE_EVIDENCE_UNVERIFIED')
                else:
                    result = preparation.verify(checkpoint)
                return RuntimeFilesStageResult(result)
            except (
                LaunchFenceError,
                ConfigReadError,
                OpenCodeRuntimeBundleError,
                OSError,
                PackageSecurityError,
                PathBoundaryError,
                PrivateRecordError,
            ) as error:
                retained = getattr(error, 'retained_owner', None)
                preparation = None if directories is None else directories._runtime_preparation
                if retained is not None and (
                    preparation is None
                    or retained not in (preparation._bundle, preparation._environment)
                ):
                    raise
                raise TaskRuntimeFilesError('ORIGINAL_RUNTIME_STAGE_UNVERIFIED') from error
