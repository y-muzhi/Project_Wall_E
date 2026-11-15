"""Publish one original fixed workspace into the Guard's private writable role."""

import hashlib
import os
import re
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field

from backend.app.infrastructure.content_paths import ContentPathIndex
from backend.app.infrastructure.guard_action_records import mutation_input_sha256
from backend.app.infrastructure.guard_control_git_transport import exchange_guard_task_files
from backend.app.infrastructure.guard_pipe_frames import _remaining
from backend.app.infrastructure.guard_request_header import (
    GuardRequestHeader,
    build_guard_request_header,
)
from backend.app.infrastructure.guard_task_workspace_protocol import (
    WORKSPACE_STAGE_STATUS,
    workspace_stage_destination,
)
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_guard_pipe_io import _deadline
from backend.app.infrastructure.windows_local_paths import (
    FileIdentity,
    LocalDirectoryPin,
    LocalPathGuard,
    local_absolute_path,
)
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.infrastructure.windows_task_directories import TaskWorkspaceDestination
from backend.app.infrastructure.windows_task_workspace_lease import (
    BackendWorkspaceWriteLease,
    WorkspaceWriteError,
)
from backend.app.infrastructure.windows_task_workspace_tree import workspace_tree_sha256
from backend.app.shared.validation import strict_json_object

from .task_start_workspace import WorkspaceAllocation
from .workspace_materialization import (
    WorkspaceMaterializationError,
    _scan_workspace_tree,
    read_workspace_manifest,
    verify_workspace_tree,
)

_MAX_RECORD_BYTES = 16 * 1024
_START_INSTANCE_STEP = 4


@dataclass(frozen=True)
class RuntimeWorkspacePublication:
    destination: TaskWorkspaceDestination = field(repr=False)
    manifest_sha256: str
    tree_identity_sha256: str


def _nonce(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{32}', value) is not None


def _workspace_target(parent, allocation, destination):
    if (
        type(parent) is not PrivatePackageGuard
        or parent.is_control_git_read_package
        or type(allocation) is not WorkspaceAllocation
        or not _nonce(allocation.nonce)
        or parent.verify() != allocation.parent
        or type(destination) is not TaskWorkspaceDestination
        or type(destination.scope) is not LaunchScope
        or destination.scope.operation_id != allocation.operation_id
        or destination.scope.step_no != _START_INSTANCE_STEP
        or not _nonce(destination.directory_nonce)
        or not _nonce(destination.binding_ref)
        or type(destination.directory) is not FileIdentity
        or destination.directory.is_directory is not True
        or destination.directory.filesystem != 'NTFS'
    ):
        raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_DESTINATION_REQUIRED')
    target = local_absolute_path(destination.directory.canonical_path)
    source = parent.path / allocation.key
    if (
        target.name != 'workspace'
        or target.parent.name != 'task-' + destination.directory_nonce
        or target.is_relative_to(source)
        or source.is_relative_to(target)
    ):
        raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_LOCATION_DIFFERS')
    return target


def _read_record(parent, name):
    target = parent.path / name
    try:
        target.lstat()
    except FileNotFoundError:
        return None
    original = parent.verify_member(name, directory=False)
    with LockedFileSource(
        target, max_file_bytes=_MAX_RECORD_BYTES, expected_file=original
    ) as record:
        return record.snapshot.raw


def _publish_record(parent, name, raw):
    with PrivateRecordAppend(parent, name, raw, max_record_bytes=_MAX_RECORD_BYTES) as record:
        record.publish()
    if _read_record(parent, name) != raw:
        raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_RECORD_UNVERIFIED')


def _record_bytes(value):
    return canonical_input(value).encode('utf-8')


class _WorkspaceWriter:
    def __init__(self, root, entries, checkpoint):
        self.root, self.checkpoint = root, checkpoint
        self.files, self.directories = {}, {}
        namespace = ContentPathIndex(materialization_root=root)
        for entry in entries:
            namespace.add_file(entry.path, entry.mode)

    def consume(self, entry, raw):
        self.checkpoint()
        parts = entry.path.split('/')
        with ExitStack() as pins:
            for count in range(1, len(parts)):
                relative = '/'.join(parts[:count])
                path = self.root / relative
                expected = self.directories.get(relative)
                if expected is None:
                    path.mkdir()
                pin = pins.enter_context(LocalDirectoryPin(path, expected=expected))
                self.directories[relative] = pin.verify()
            target = self.root.joinpath(*parts)
            self.checkpoint()
            with target.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                with LocalPathGuard(target, directory=False) as file:
                    self.files[entry.path] = file.verify()


def _inspect_target(target, expected, entries, checkpoint, *, writer=None):
    def member(relative, *, directory):
        with LocalPathGuard(target / relative, directory=directory) as guard:
            return guard.verify()

    files, directories = _scan_workspace_tree(
        target,
        expected,
        entries,
        checkpoint,
        member,
        file_ids=None if writer is None else writer.files,
        directory_ids=None if writer is None else writer.directories,
    )
    contents = {
        entry.path: (files[entry.path], entry.byte_count, entry.sha256) for entry in entries
    }
    return workspace_tree_sha256(contents, directories)


def publish_runtime_workspace(
    parent, allocation, receipt, destination, checkpoint, limits, *, observe_only=False
):
    """Publish once before launch; an original uncertain intent permits reads only."""
    target = _workspace_target(parent, allocation, destination)
    checkpoint()
    source = read_workspace_manifest(parent, allocation, receipt, checkpoint, limits)
    if (source.directory.volume_serial, source.directory.file_id) == (
        destination.directory.volume_serial,
        destination.directory.file_id,
    ):
        raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_LOCATION_DIFFERS')
    intent_name = allocation.nonce + '.runtime-workspace-intent.json'
    seal_name = allocation.nonce + '.runtime-workspace.json'
    intent = _record_bytes(
        {
            'schema_version': 1,
            'task_id': allocation.task_id,
            'workspace_id': allocation.workspace_id,
            'generation': allocation.generation,
            'manifest_sha256': source.manifest_sha256,
            'destination': asdict(destination),
        }
    )
    intent_sha256 = hashlib.sha256(intent).hexdigest()
    with LocalDirectoryPin(target, expected=destination.directory) as root:
        prior = _read_record(parent, intent_name)
        seal = _read_record(parent, seal_name)

        def check_current():
            checkpoint()
            root.verify()
            if parent.verify() != allocation.parent:
                raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_SOURCE_DIFFERS')

        if prior is None:
            if observe_only:
                raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_OUTCOME_UNVERIFIED')
            if seal is not None or any(target.iterdir()):
                raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_TARGET_NOT_EMPTY')
            writer = _WorkspaceWriter(target, source.entries, check_current)
            check_current()
            _publish_record(parent, intent_name, intent)
            verify_workspace_tree(
                source.path, source.directory, source.entries, check_current, consume=writer.consume
            )
            identity = _inspect_target(
                target, destination.directory, source.entries, check_current, writer=writer
            )
            check_current()
            _publish_record(
                parent,
                seal_name,
                _record_bytes(
                    {
                        'intent_sha256': intent_sha256,
                        'tree_identity_sha256': identity,
                    }
                ),
            )
        else:
            if prior != intent or seal is None:
                raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_OUTCOME_UNVERIFIED')
            record = strict_json_object(seal)
            identity = _inspect_target(target, destination.directory, source.entries, check_current)
            if record != {'intent_sha256': intent_sha256, 'tree_identity_sha256': identity}:
                raise WorkspaceMaterializationError('ORIGINAL_RUNTIME_WORKSPACE_RECEIPT_DIFFERS')
        check_current()
        return RuntimeWorkspacePublication(destination, source.manifest_sha256, identity)


class WorkspacePublicationUnknown(WorkspaceWriteError):
    def __init__(self, expected):
        super().__init__('ORIGINAL_WORKSPACE_STAGE_COMPLETION_UNKNOWN')
        self.expected = expected


class RuntimeWorkspaceTransfer:
    def __init__(self, frames, controller, process_lock, original, binding_ref):
        if (
            type(original) is not GuardRequestHeader
            or original.action != 'PREPARE'
            or original.scope.step_no != _START_INSTANCE_STEP
            or original.input.get('run_kind') != 'TASK'
            or original.input.get('reserve_files') is not True
        ):
            raise WorkspaceWriteError('ORIGINAL_TASK_FILE_RESERVATION_INPUT_REQUIRED')
        self._frames, self._controller, self._lock = frames, controller, process_lock
        self._scope, self._binding_ref = original.scope, binding_ref
        self._prepare_sha256 = mutation_input_sha256(original)
        data = original.input
        self._manifest = data.get('workspace_manifest_sha256')
        self._nonce = data['workspace_nonce']
        self._sources = data['sources']

    def _stage(self, stage, payload, *, deadline, cancelled):
        scope = self._scope
        request = build_guard_request_header(
            self._controller,
            self._lock,
            action='PREPARE',
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=None,
            action_input={
                'run_kind': 'TASK',
                'workspace_stage': stage,
                'workspace_binding_ref': self._binding_ref,
                'prepare_input_sha256': self._prepare_sha256,
                'manifest_sha256': self._manifest,
                'payload': payload,
            },
        )
        if request.scope != scope:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_SCOPE_DIFFERS')
        reply = exchange_guard_task_files(
            self._frames,
            self._controller,
            self._lock,
            request,
            timeout_ms=_remaining(deadline),
            cancelled=cancelled,
        )
        if reply.status != WORKSPACE_STAGE_STATUS:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_UNVERIFIED')
        return reply.result

    def _source(self, parent, allocation, receipt, checkpoint, limits):
        source = read_workspace_manifest(parent, allocation, receipt, checkpoint, limits)
        tree = FileIdentity(**strict_json_object(receipt)['tree_record']['file'])
        if (
            allocation.operation_id != self._scope.operation_id
            or allocation.nonce != self._nonce
            or source.manifest_sha256 != self._manifest
        ):
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_SOURCE_DIFFERS')
        for role, identity in (
            ('parent', allocation.parent),
            ('workspace', source.directory),
            ('workspace_tree', tree),
        ):
            expected = self._sources[role]
            if (
                identity.file_id != expected['file_id']
                or identity.volume_serial != expected['volume_serial']
            ):
                raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_SOURCE_DIFFERS')

    def _checkpoint(self, check_active, deadline, cancelled):
        check_active()
        if cancelled():
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_INTERRUPTED')
        _remaining(deadline)

    def publish(self, parent, allocation, receipt, check_active, limits, *, timeout_ms, cancelled):
        deadline = _deadline(timeout_ms)

        def checkpoint():
            self._checkpoint(check_active, deadline, cancelled)

        self._source(parent, allocation, receipt, checkpoint, limits)
        offered = self._stage('BEGIN', {}, deadline=deadline, cancelled=cancelled)
        with BackendWorkspaceWriteLease(offered['writer']):
            destination = workspace_stage_destination(self._scope, offered)
            result = publish_runtime_workspace(
                parent, allocation, receipt, destination, checkpoint, limits
            )
        checkpoint()
        try:
            actual = self._stage(
                'FINISH',
                {'tree_identity_sha256': result.tree_identity_sha256},
                deadline=deadline,
                cancelled=cancelled,
            )
        except LaunchOutcomeUnknown as error:
            unknown = WorkspacePublicationUnknown(result)
            if getattr(error, 'retained_owner', None) is not None:
                unknown.retained_owner = error.retained_owner
            raise unknown from error
        return self._check_result(result, actual)

    def _check_result(self, expected, actual):
        observed = RuntimeWorkspacePublication(
            workspace_stage_destination(self._scope, actual),
            actual['manifest_sha256'],
            actual['tree_identity_sha256'],
        )
        if observed != expected:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_RECEIPT_DIFFERS')
        return observed

    def verify(
        self, parent, allocation, receipt, expected, check_active, limits, *, timeout_ms, cancelled
    ):
        deadline = _deadline(timeout_ms)

        def checkpoint():
            self._checkpoint(check_active, deadline, cancelled)

        self._source(parent, allocation, receipt, checkpoint, limits)
        if (
            type(expected) is not RuntimeWorkspacePublication
            or expected.destination.scope != self._scope
            or expected.destination.binding_ref != self._binding_ref
        ):
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_RECEIPT_DIFFERS')
        observed = publish_runtime_workspace(
            parent,
            allocation,
            receipt,
            expected.destination,
            checkpoint,
            limits,
            observe_only=True,
        )
        if observed != expected:
            raise WorkspaceWriteError('ORIGINAL_WORKSPACE_STAGE_RECEIPT_DIFFERS')
        actual = self._stage('VERIFY', {}, deadline=deadline, cancelled=cancelled)
        return self._check_result(expected, actual)
