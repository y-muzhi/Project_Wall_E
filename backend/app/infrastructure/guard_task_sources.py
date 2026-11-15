"""Attribute-only custody of the original TASK workspace and private seals."""

import re
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic

from .guard_action_journal import GuardActionJournal
from .guard_request_header import GuardRequestHeader, parse_guard_request_header
from .opencode_runtime_bundle import is_opencode_runtime_bundle_ref
from .opencode_task_launch import TaskExecutionPlan
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_access_check import NativeAccessError
from .windows_attribute_handles import GuardAttributeHandles
from .windows_local_paths import (
    FileIdentity,
    LocalPathGuard,
    PathBoundaryError,
    local_absolute_path,
)
from .windows_private_package import PackageSecurityError
from .windows_stdio import _handle, _handle_text

ROLES = ('parent', 'workspace', 'workspace_tree', 'basis_seal')
DIRECTORIES = frozenset(('parent', 'workspace'))


class TaskSourceError(LaunchOutcomeUnknown):
    def __init__(self, code, native_error=None):
        self.native_error = native_error
        super().__init__(code)


def _hex(value, length):
    return type(value) is str and re.fullmatch(f'[0-9a-f]{{{length}}}', value) is not None


def validate_task_source_parent(parent):
    if (
        type(parent) is not FileIdentity
        or parent.is_directory is not True
        or parent.filesystem != 'NTFS'
        or not _hex(parent.volume_serial, 16)
        or not _hex(parent.file_id, 32)
        or local_absolute_path(parent.canonical_path).parent
        == local_absolute_path(parent.canonical_path)
    ):
        raise TaskSourceError('ORIGINAL_TASK_SOURCE_PARENT_REQUIRED')


def _paths(parent, nonce):
    validate_task_source_parent(parent)
    if not _hex(nonce, 32):
        raise TaskSourceError('ORIGINAL_TASK_SOURCE_NONCE_INVALID')
    path = local_absolute_path(parent.canonical_path)
    return {
        'parent': path,
        'workspace': path / ('working-' + nonce),
        'workspace_tree': path / (nonce + '.workspace-tree.json'),
        'basis_seal': path / (nonce + '.basis-seal.json'),
    }


def _verify_cohort(parent, paths, identities):
    file_ids = set()
    for role, file in identities.items():
        if (
            type(file) is not FileIdentity
            or file.is_directory is not (role in DIRECTORIES)
            or file.filesystem != 'NTFS'
            or file.volume_serial != parent.volume_serial
            or not _hex(file.file_id, 32)
            or file.file_id in file_ids
            or local_absolute_path(file.canonical_path) != paths[role]
            or (role == 'parent' and file != parent)
        ):
            raise TaskSourceError('ORIGINAL_TASK_SOURCE_IDENTITY_DIFFERS')
        file_ids.add(file.file_id)


class TaskSourcePins:
    """Backend owns original source objects until Guard finishes copying them."""

    def __init__(self, parent, nonce, *, workspace, workspace_tree, basis_seal):
        self._paths = _paths(parent, nonce)
        self._nonce = nonce
        self._identities = {
            'parent': parent,
            'workspace': workspace,
            'workspace_tree': workspace_tree,
            'basis_seal': basis_seal,
        }
        _verify_cohort(parent, self._paths, self._identities)
        self._guards = {}

    def __enter__(self):
        if self._guards:
            raise TaskSourceError('ORIGINAL_TASK_SOURCE_ALREADY_PINNED')
        try:
            for role, path in self._paths.items():
                guard = LocalPathGuard(path, directory=role in DIRECTORIES)
                self._guards[role] = guard
                guard.__enter__()
            self.verify()
            return self
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup:
                raise cleanup from error
            raise

    def verify(self):
        if set(self._guards) != set(ROLES):
            raise TaskSourceError('ORIGINAL_TASK_SOURCE_PINS_REQUIRED')
        for role, expected in self._identities.items():
            if self._guards[role].verify() != expected:
                raise TaskSourceError('ORIGINAL_TASK_SOURCE_FILE_CHANGED')

    def request_data(
        self,
        *,
        basis_plan_sha256=None,
        reserve_files=False,
        workspace_manifest_sha256=None,
        runtime_bundle_ref=None,
        execution=None,
        network=None,
    ):
        self.verify()
        data = {
            'run_kind': 'TASK',
            'workspace_nonce': self._nonce,
            'sources': {
                role: {
                    'file_id': file.file_id,
                    'volume_serial': file.volume_serial,
                    'handle': _handle_text(self._guards[role]._held[-1][0]),
                }
                for role, file in self._identities.items()
            },
        }

        if basis_plan_sha256 is not None:
            if not _hex(basis_plan_sha256, 64):
                raise TaskSourceError('ORIGINAL_BASIS_GROUP_PLAN_DIGEST_REQUIRED')
            data['basis_plan_sha256'] = basis_plan_sha256
        if type(reserve_files) is not bool or (reserve_files and basis_plan_sha256 is None):
            raise TaskSourceError('ORIGINAL_TASK_FILE_RESERVATION_INPUT_REQUIRED')
        if reserve_files:
            data['reserve_files'] = True
        if workspace_manifest_sha256 is not None:
            if not reserve_files or not _hex(workspace_manifest_sha256, 64):
                raise TaskSourceError('ORIGINAL_WORKSPACE_MANIFEST_DIGEST_REQUIRED')
            data['workspace_manifest_sha256'] = workspace_manifest_sha256
        if runtime_bundle_ref is not None:
            if workspace_manifest_sha256 is None or not is_opencode_runtime_bundle_ref(
                runtime_bundle_ref
            ):
                raise TaskSourceError('ORIGINAL_TASK_RUNTIME_BUNDLE_REFERENCE_REQUIRED')
            data['runtime_bundle_ref'] = runtime_bundle_ref
        if execution is not None or network is not None:
            TaskExecutionPlan.parse(execution, network, runtime_bundle_ref)
            data['execution'], data['network'] = execution, network
        return data

    def close(self):
        failure = None
        for role, guard in reversed(tuple(self._guards.items())):
            try:
                guard.close()
            except (OSError, RuntimeError) as error:
                failure = error
            else:
                del self._guards[role]
        if failure is not None:
            failure.retained_owner = self
            raise failure

    def __exit__(self, error_type, error, traceback):
        self.close()


def _decode_sources(value, parent):
    fields = {'run_kind', 'workspace_nonce', 'sources'}
    if 'basis_plan_sha256' in value:
        if not _hex(value['basis_plan_sha256'], 64):
            raise TaskSourceError('ORIGINAL_BASIS_GROUP_PLAN_DIGEST_REQUIRED')
        fields.add('basis_plan_sha256')
    if 'reserve_files' in value:
        if value['reserve_files'] is not True or 'basis_plan_sha256' not in fields:
            raise TaskSourceError('ORIGINAL_TASK_FILE_RESERVATION_INPUT_REQUIRED')
        fields.add('reserve_files')
    if 'workspace_manifest_sha256' in value:
        if 'reserve_files' not in fields or not _hex(value['workspace_manifest_sha256'], 64):
            raise TaskSourceError('ORIGINAL_WORKSPACE_MANIFEST_DIGEST_REQUIRED')
        fields.add('workspace_manifest_sha256')
    if 'runtime_bundle_ref' in value:
        if 'workspace_manifest_sha256' not in fields or not is_opencode_runtime_bundle_ref(
            value['runtime_bundle_ref']
        ):
            raise TaskSourceError('ORIGINAL_TASK_RUNTIME_BUNDLE_REFERENCE_REQUIRED')
        fields.add('runtime_bundle_ref')
    if 'execution' in value or 'network' in value:
        TaskExecutionPlan.parse(
            value.get('execution'), value.get('network'), value.get('runtime_bundle_ref')
        )
        fields.update(('execution', 'network'))
    if set(value) != fields or value['run_kind'] != 'TASK':
        raise TaskSourceError('ORIGINAL_TASK_SOURCE_FIELDS_REQUIRED')
    paths = _paths(parent, value['workspace_nonce'])
    sources = value['sources']
    if type(sources) is not dict or set(sources) != set(ROLES):
        raise TaskSourceError('ORIGINAL_TASK_SOURCE_ROLES_REQUIRED')
    entries = {}
    for role, path in paths.items():
        row = sources[role]
        if type(row) is not dict or set(row) != {'file_id', 'volume_serial', 'handle'}:
            raise TaskSourceError('ORIGINAL_TASK_SOURCE_FIELDS_REQUIRED')
        try:
            _handle(row['handle'])
        except RuntimeError as error:
            raise TaskSourceError('ORIGINAL_TASK_SOURCE_HANDLE_INVALID') from error
        canonical = parent.canonical_path if role == 'parent' else str(path)
        file = replace(
            parent,
            canonical_path=canonical,
            file_id=row['file_id'],
            volume_serial=row['volume_serial'],
            is_directory=role in DIRECTORIES,
        )
        entries[role] = file, row['handle']
    _verify_cohort(parent, paths, {role: source[0] for role, source in entries.items()})
    return entries


def verify_guard_task_source_request(
    owner, request, parent, *, peer, program, timeout_ms, cancelled, runtime_root=None
):
    """Verify PREPARE's originals without allocating or acknowledging a task."""
    with hold_guard_task_sources(
        owner,
        request,
        parent,
        peer=peer,
        program=program,
        timeout_ms=timeout_ms,
        cancelled=cancelled,
        runtime_root=runtime_root,
    ):
        pass


@contextmanager
def hold_guard_task_sources(
    owner, request, parent, *, peer, program, timeout_ms, cancelled, runtime_root=None
):
    binding = owner.binding
    if (
        type(request) is not GuardRequestHeader
        or request.action != 'PREPARE'
        or parse_guard_request_header(request.wire, binding, peer=peer) != request
    ):
        raise TaskSourceError('ORIGINAL_TASK_SOURCE_REQUEST_DIFFERS')
    entries = _decode_sources(request.input, parent)
    scope = request.target_scope
    deadline = monotonic() + timeout_ms / 1000

    def interrupted():
        return cancelled() or monotonic() >= deadline

    def checkpoint():
        if interrupted():
            raise TaskSourceError('ORIGINAL_TASK_SOURCE_SCOPE_FENCED')
        journal._require_controller_open(scope)

    with owner.current_registry(
        binding, peer=peer, program=program, timeout_ms=timeout_ms, cancelled=cancelled
    ) as registry:
        journal = registry._journal
        actions = GuardActionJournal(journal)
        with journal._scope(scope):
            journal._require_controller_open(scope)
            if (
                cancelled()
                or journal.inspect(scope) is not None
                or scope.key in journal._volatile_closed
                or actions.find(scope, 'STOP') is not None
                or actions.find(scope, 'PREPARE') is not None
            ):
                raise TaskSourceError('ORIGINAL_TASK_SOURCE_SCOPE_FENCED')
            with GuardAttributeHandles(
                registry._controller,
                binding.controller,
                entries,
                error_type=TaskSourceError,
                error_prefix='ORIGINAL_TASK_SOURCE',
            ) as pins:
                pins.verify()
                checkpoint()
                if runtime_root is not None:
                    try:
                        runtime_root.verify_controller(registry._controller, checkpoint=checkpoint)
                    except (NativeAccessError, PackageSecurityError, PathBoundaryError) as error:
                        if getattr(error, 'retained_owner', None) is not None:
                            raise
                        raise TaskSourceError('TASK_RUNTIME_PARENT_ACCESS_UNVERIFIED') from error
                checkpoint()
                yield registry, actions, checkpoint, interrupted
