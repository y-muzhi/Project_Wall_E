"""Run the original repository commands through an authenticated Guard pipe."""

import re
import sqlite3
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from time import monotonic, sleep

from backend.app.infrastructure.content_manifest import ContentManifestError
from backend.app.infrastructure.content_paths import ContentPathError
from backend.app.infrastructure.content_secret_policy import SecretRestricted
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_baseline_ref_guard import BaselineRefConflict, BaselineRefGuard
from backend.app.infrastructure.git_baseline_ref_transaction import (
    BaselineRefTransaction,
    DeliveryRefTransaction,
)
from backend.app.infrastructure.git_commit_closure import GitClosureError
from backend.app.infrastructure.git_config_command import (
    ConfigCommandError,
    parse_original_config_output,
)
from backend.app.infrastructure.git_local_config import GitConfigError
from backend.app.infrastructure.git_object_batch import GitObjectBatch
from backend.app.infrastructure.git_object_graph import GitObjectGraphError
from backend.app.infrastructure.git_object_read import GitObjectReadError
from backend.app.infrastructure.git_ref_metadata import RefMetadataError
from backend.app.infrastructure.git_repository_location import (
    RepositoryLocationError,
    RepositoryLocationLease,
)
from backend.app.infrastructure.git_repository_metadata import (
    MetadataTreeError,
    RepositoryMetadataLease,
)
from backend.app.infrastructure.git_worktrees import WorktreeError
from backend.app.infrastructure.guard_action_records import MUTATIONS
from backend.app.infrastructure.guard_control_git_input import (
    baseline_ref_prepare_input,
    config_prepare_input,
    delivery_ancestry_prepare_input,
    delivery_object_prepare_input,
    delivery_ref_prepare_input,
    delivery_target_prepare_input,
    repository_read_prepare_input,
)
from backend.app.infrastructure.guard_git_config_source import open_config_export
from backend.app.infrastructure.guard_git_metadata_source import export_metadata_directories
from backend.app.infrastructure.guard_pipe_frames import _remaining
from backend.app.infrastructure.guard_request_header import build_guard_request_header
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope
from backend.app.infrastructure.windows_config_source import ConfigReadError
from backend.app.infrastructure.windows_guard_pipe_io import _deadline
from backend.app.infrastructure.windows_local_paths import PathBoundaryError
from backend.app.infrastructure.windows_pipe_capture import BoundedOutputCapture
from backend.app.infrastructure.windows_process import NativeProcessIdentity
from backend.app.infrastructure.windows_process_input import (
    MAX_TYPED_INPUT_BYTES,
    OriginalProcessInput,
)
from backend.app.infrastructure.windows_stdio import BackendStandardIO, GuardStdioBinding
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadError
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_integer

from .repository_baseline_pin import BaselinePinGitDispatch
from .repository_baseline_query import (
    BaselineQueryGitDispatch,
    BaselineQueryResult,
    load_baseline_query,
)
from .repository_baseline_validation import (
    inspect_baseline_ref,
    inspect_baseline_source,
    original_baseline,
    pending_baseline_pin_observation,
    start_baseline_pin,
    start_baseline_validation,
    start_baseline_verify,
    verify_baseline_ref,
)
from .repository_baseline_verify import (
    BaselineRecoveredVerifyGitDispatch,
    BaselineVerifyGitDispatch,
)
from .repository_git_dispatch import (
    BaselineGitDispatch,
    ObservationGitDispatch,
    RegistrationGitDispatch,
    mark_repository_read_unknown,
)
from .repository_observation_publish import _original as _original_observation
from .repository_observation_publish import start_repository_observation
from .repository_registration import _original, start_repository_registration

BASELINE_INPUT_ERRORS = (
    GitObjectReadError,
    GitObjectGraphError,
    GitClosureError,
    ContentManifestError,
    ContentPathError,
    SecretRestricted,
)


@dataclass(frozen=True)
class RegistrationReadLimits:
    max_file_bytes: int
    max_metadata_entries: int
    max_open_handles: int
    max_metadata_bytes: int
    max_git_output_bytes: int
    max_git_seconds: int

    def __post_init__(self):
        for field in self.__dataclass_fields__:
            strict_integer(getattr(self, field), field)
        if self.max_git_seconds > 300:
            raise ValueError('Registration Git deadline must fit the bounded pipe protocol')


def _validation_code(error):
    if getattr(error, 'retained_owner', None) is not None:
        return None
    if isinstance(
        error,
        (
            RepositoryLocationError,
            ConfigReadError,
            GitConfigError,
            MetadataTreeError,
            WorktreeHeadError,
        ),
    ):
        return error.code
    if isinstance(error, BaselineRefConflict):
        return error.code
    if isinstance(error, BASELINE_INPUT_ERRORS):
        return getattr(error, 'code', 'SOURCE_UNSUPPORTED')
    if isinstance(error, (RefMetadataError, WorktreeError)):
        return 'REPOSITORY_UNSUPPORTED'
    if isinstance(error, PathBoundaryError):
        if error.code in ('WINDOWS_PATH_API_REQUIRED', 'PATH_HANDLE_CLOSE_UNVERIFIED'):
            return None
        if error.native_error in (32, 33):
            return 'SOURCE_BUSY'
        return 'SOURCE_CHANGED' if error.code == 'FILE_IDENTITY_CHANGED' else 'SOURCE_UNSUPPORTED'
    if isinstance(error, ConfigCommandError) and error.args == ('CONFIG_RESULT_SOURCE_DIFFERS',):
        return 'SOURCE_CHANGED'
    return None


class _ResourceOwner:
    def __init__(self):
        self._owners = []

    def _keep(self, factory, *args, **kwargs):
        owner = self._open(factory, *args, **kwargs)
        self._owners.append(owner)
        return owner

    def _open(self, factory, *args, **kwargs):
        try:
            return factory(*args, **kwargs)
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if retained is not None:
                self._owners.append(retained)
            raise

    def close(self):
        for owner in reversed(tuple(self._owners)):
            owner.close()
            self._owners.remove(owner)


class RepositoryGitScopeActions:
    """Calls only the original registered command scope on the current connection."""

    def __init__(self, runtime, binding, dispatch, original):
        self._runtime, self._binding, self._dispatch = runtime, binding, dispatch
        self.original = original
        self._binding_ref = None

    def use_boundary(self, deadline, cancelled):
        if not callable(cancelled):
            raise TypeError('Explicit repository cleanup cancellation required')
        self._deadline, self._cancelled = deadline, cancelled

    def bind_preparation(self, prepared):
        reference = prepared.get('binding_ref')
        if (
            type(reference) is not str
            or re.fullmatch('[0-9a-f]{32}', reference) is None
            or self._binding_ref is not None
            and self._binding_ref != reference
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_PREPARE_ACK_DIFFERS')
        self._binding_ref = reference

    def original_preparation(self, *, observe=False):
        original = self.original
        intent = self._dispatch.read_action(original, 'PREPARE', 'MAY_HAVE_BEEN_SENT')
        prepared = self._dispatch.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
        if intent is not None and (prepared is None or observe):
            reply = self.send('OBSERVE', data={'observed_action': 'PREPARE'})
            if reply.result['action_phase'] != 'ACKNOWLEDGED':
                raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_PREPARE_ACK_REQUIRED')
            prepared = self._dispatch.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
        return self._bind_original_preparation(intent, prepared)

    def _bind_original_preparation(self, intent, prepared):
        if prepared is None or intent is None or prepared['input_sha256'] != intent['input_sha256']:
            raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_PREPARE_ACK_REQUIRED')
        self.bind_preparation(prepared['result'])
        return prepared['result']

    def cleanup_pending(self):
        original = self.original
        prepare = self._dispatch.read_action(original, 'PREPARE', 'MAY_HAVE_BEEN_SENT')
        if prepare is None:
            for action in MUTATIONS:
                if self._dispatch.read_action(original, action, 'ACKNOWLEDGED') is not None or (
                    action != 'PREPARE'
                    and self._dispatch.read_action(original, action, 'MAY_HAVE_BEEN_SENT')
                    is not None
                ):
                    raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_PREPARE_INTENT_MISSING')
            return False
        release = self._dispatch.read_action(original, 'RELEASE', 'ACKNOWLEDGED')
        if release is None:
            return True
        # This local assessment never opens IPC or appends a new action.
        prepared = self._dispatch.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
        self._bind_original_preparation(prepare, prepared)
        release_intent = self._dispatch.read_action(original, 'RELEASE', 'MAY_HAVE_BEEN_SENT')
        self._verify_cleanup_ack('RELEASE', release_intent, release)
        return False

    def finish_cleanup(self):
        release = self._dispatch.read_action(self.original, 'RELEASE', 'MAY_HAVE_BEEN_SENT')
        if release is None:
            self._cleanup_action('STOP')
            self.wait_for_exit('STOP', require_empty_job=True)
        self._cleanup_action('RELEASE')

    def send(self, action, *, data=None):
        scope = self.original.scope
        action_input = data or {}
        if scope.controller_ref != self._binding.controller_ref:
            action_input = {
                **action_input,
                'recovery': {
                    'controller_ref': scope.controller_ref,
                    'owner_epoch': self.original.owner_epoch,
                },
            }
        request = build_guard_request_header(
            self._binding,
            self._runtime.commands().process_lock,
            action=action,
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=None if action == 'PREPARE' else self._binding_ref,
            action_input=action_input,
        )
        method = self._dispatch.observe if action == 'OBSERVE' else self._dispatch.dispatch
        return method(request, timeout_ms=_remaining(self._deadline), cancelled=self._cancelled)

    def wait_for_exit(self, observed_action, *, require_empty_job):
        while True:
            reply = self.send('OBSERVE', data={'observed_action': observed_action})
            facts = reply.result
            resource = facts['resource']
            observation = None if resource is None else resource['observation']
            members = facts['job_activity']
            exited = observation is not None and observation['state'] == 'EXITED'
            empty = members is not None and (
                members['complete']
                and members['assigned_count'] == 0
                and not members['process_ids']
            )
            if exited and (empty or not require_empty_job):
                return observation['exit_code']
            if require_empty_job and empty and resource is not None:
                fence = resource['fence']
                if (
                    fence['stop_closed']
                    and fence['create_state'] == 'NONE'
                    and fence['resume_state'] == 'NONE'
                    and resource['resource_ref'] is None
                    and resource['original_process_identity'] is None
                ):
                    return None
            _remaining(self._deadline)
            if self._cancelled():
                raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_CANCELLED_REQUIRES_STOP')
            sleep(0.005)

    def _cleanup_action(self, action):
        original = self.original
        acknowledged = self._dispatch.read_action(original, action, 'ACKNOWLEDGED')
        intent = self._dispatch.read_action(original, action, 'MAY_HAVE_BEEN_SENT')
        if acknowledged is None:
            if intent is None:
                self.send(action)
            else:
                self.send('OBSERVE', data={'observed_action': action})
            acknowledged = self._dispatch.read_action(original, action, 'ACKNOWLEDGED')
            intent = self._dispatch.read_action(original, action, 'MAY_HAVE_BEEN_SENT')
        self._verify_cleanup_ack(action, intent, acknowledged)

    def _verify_cleanup_ack(self, action, intent, acknowledged):
        if (
            intent is None
            or acknowledged is None
            or intent['input_sha256'] != acknowledged['input_sha256']
            or acknowledged['result'].get('binding_ref') != self._binding_ref
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_CLEANUP_ACTION_UNVERIFIED')
        native = acknowledged['result'].get('native')
        verified = False
        if type(native) is dict:
            if action == 'RELEASE':
                verified = native.get('cleanup_verified') is True
            else:
                fence = native.get('fence')
                verified = type(fence) is dict and fence.get('stop_closed') is True
        if not verified:
            raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_CLEANUP_ACTION_UNVERIFIED')


class _FixedGitRun(_ResourceOwner):
    """One original command, with no retry of an uncertain mutation."""

    def __init__(self, runtime, binding, dispatch, original):
        super().__init__()
        self._dispatch = dispatch
        self._actions = RepositoryGitScopeActions(runtime, binding, dispatch, original)
        self._scope = original.scope
        self._streams = None
        self._prepare_attempted = False
        self._released = False

    @property
    def cleanup_required(self):
        return self._prepare_attempted and not self._released

    def _prepare(self, prepare, deadline, cancelled):
        self._actions.use_boundary(deadline, cancelled)
        streams = self._keep(BackendStandardIO, self._scope)
        self._streams = streams
        descriptor = streams.descriptor()
        action_input = prepare(descriptor)
        _remaining(deadline)
        if cancelled():
            raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_CANCELLED')
        streams.begin_handoff()
        self._prepare_attempted = True
        prepared = self._actions.send('PREPARE', data=action_input).result
        self._acknowledge_prepare(prepared)
        streams.release_child_copies()
        self._actions.send('CREATE_SUSPENDED')
        return streams, descriptor.io_nonce

    def run(self, prepare, *, deadline, cancelled, max_output_bytes, input_bytes=None):
        streams, io_nonce = self._prepare(prepare, deadline, cancelled)
        capture = self._keep(
            BoundedOutputCapture,
            streams,
            scope=self._scope,
            max_output_bytes=max_output_bytes,
        )
        self._actions.send('RESUME')
        writer = None if input_bytes is None else OriginalProcessInput(streams)
        offset = 0
        while True:
            moved = 0
            if writer is not None:
                _remaining(deadline)
                if cancelled():
                    raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_INPUT_REQUIRES_STOP')
                if offset < len(input_bytes):
                    moved = writer.write_available(
                        input_bytes[offset : offset + MAX_TYPED_INPUT_BYTES]
                    )
                    offset += moved
                if offset == len(input_bytes):
                    streams.close_input()
                    writer = None
            progress = capture.poll()
            if progress.complete:
                if writer is not None:
                    raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_INPUT_INCOMPLETE')
                break
            if progress.limit_exceeded or cancelled():
                raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_OUTPUT_REQUIRES_STOP')
            _remaining(deadline)
            if moved == 0:
                sleep(0.005)
        output = capture.snapshot()
        exit_code = self._actions.wait_for_exit('RESUME', require_empty_job=False)
        self._stop_and_release()
        return output, io_nonce, exit_code

    def run_batch(
        self, prepare, consume, *, format, max_requests, max_output_bytes, deadline, cancelled
    ):
        streams, _ = self._prepare(prepare, deadline, cancelled)
        batch = self._keep(
            GitObjectBatch,
            streams,
            scope=self._scope,
            format=format,
            max_requests=max_requests,
            max_output_bytes=max_output_bytes,
            deadline=deadline,
            cancelled=cancelled,
        )
        self._actions.send('RESUME')
        try:
            result = consume(batch.read)
            evidence = batch.finish()
        except BASELINE_INPUT_ERRORS:
            self._stop_and_release()
            raise
        exit_code = self._actions.wait_for_exit('RESUME', require_empty_job=False)
        self._stop_and_release()
        if type(exit_code) is not int or exit_code != 0:
            raise GitObjectReadError('ORIGINAL_BATCH_EXIT_FAILED')
        return result, evidence

    def run_ref(
        self,
        prepare,
        ref_guard,
        intent,
        record_prepared,
        authorize_commit,
        *,
        max_output_bytes,
        deadline,
        cancelled,
    ):
        streams, _ = self._prepare(prepare, deadline, cancelled)
        transaction = self._keep(
            BaselineRefTransaction,
            streams,
            intent,
            scope=self._scope,
            max_output_bytes=max_output_bytes,
            deadline=deadline,
            cancelled=cancelled,
        )
        self._actions.send('RESUME')
        process = transaction.prepare()
        try:
            lock = ref_guard.verify_prepared()
            original = record_prepared(process, lock)
        except Exception:
            transaction.abort()
            self._actions.wait_for_exit('RESUME', require_empty_job=False)
            self._stop_and_release()
            ref_guard.verify_aborted()
            raise

        def persist_dispatch(binding):
            if ref_guard.verify_prepared() != lock:
                raise LaunchOutcomeUnknown('ORIGINAL_BASELINE_REF_LOCK_DIFFERS')
            permit = authorize_commit(binding, original)
            if ref_guard.verify_prepared() != lock:
                raise LaunchOutcomeUnknown('ORIGINAL_BASELINE_REF_LOCK_DIFFERS')
            return permit

        transaction.commit(persist_dispatch)
        exit_code = self._actions.wait_for_exit('RESUME', require_empty_job=False)
        self._stop_and_release()
        if type(exit_code) is not int or exit_code != 0:
            raise LaunchOutcomeUnknown('ORIGINAL_BASELINE_REF_EXIT_FAILED')
        return process, original, ref_guard.verify_committed(lock)

    def run_delivery_ref(
        self,
        prepare,
        intent,
        verify_prepared,
        dispatch_fence,
        confirm_ack,
        confirm_abort,
        *,
        release_read_lease,
        max_output_bytes,
        deadline,
        cancelled,
    ):
        streams, _ = self._prepare(prepare, deadline, cancelled)
        release_read_lease()
        transaction = self._keep(
            DeliveryRefTransaction,
            streams,
            intent,
            scope=self._scope,
            max_output_bytes=max_output_bytes,
            deadline=deadline,
            cancelled=cancelled,
        )
        self._actions.send('RESUME')
        process = transaction.prepare()

        def abort_original():
            transaction.abort()
            confirm_abort(process)
            self._actions.wait_for_exit('RESUME', require_empty_job=False)
            self._stop_and_release()

        try:
            verify_prepared(process)
        except Exception:
            abort_original()
            raise
        try:
            transaction.commit(dispatch_fence)
        except Exception:
            if transaction._phase == 'PREPARED':
                abort_original()
            raise
        # Persist the real ACK before waiting for Guard release or rereading Git.
        confirm_ack(process)
        exit_code = self._actions.wait_for_exit('RESUME', require_empty_job=False)
        self._stop_and_release()
        if type(exit_code) is not int or exit_code != 0:
            raise LaunchOutcomeUnknown('ORIGINAL_DELIVERY_REF_EXIT_FAILED')
        return exit_code

    def _stop_and_release(self):
        self._actions.send('STOP')
        self._actions.wait_for_exit('STOP', require_empty_job=True)
        self._actions.send('RELEASE')
        self._released = True
        self.close()

    def _acknowledge_prepare(self, prepared):
        self._actions.bind_preparation(prepared)
        copied = prepared['stdio_binding']
        self._streams.acknowledge_copy(
            GuardStdioBinding(
                NativeProcessIdentity(**copied['owner']),
                LaunchScope(**copied['scope']),
                copied['io_nonce'],
                copied['guard_io_ref'],
            )
        )

    def reconcile_cleanup(self, frames, *, timeout_ms, cancelled):
        """Reconcile the original scope while retaining this backend's STDIO."""
        if self._released:
            self.close()
            return
        try:
            if not self._prepare_attempted:
                raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_HANDOFF_UNVERIFIED')
            self._dispatch.reconnect(frames)
            self._actions.use_boundary(_deadline(timeout_ms), cancelled)
            prepared = self._actions.original_preparation()
            self._acknowledge_prepare(prepared)
            self._actions.finish_cleanup()
            self._released = True
            self.close()
        except BaseException as error:
            error.retained_owner = self
            raise

    def close(self):
        if self.cleanup_required:
            raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_GUARD_CLEANUP_UNVERIFIED')
        super().close()


class _RepositoryRun(_ResourceOwner):
    """Owns the native command and source handles for one accepted operation."""

    _records_business_progress = True

    def __init__(self, runtime, operation_id, frames, binding, journal, *, private_roots, limits):
        super().__init__()
        strict_integer(operation_id, 'operation_id')
        if type(limits) is not RegistrationReadLimits:
            raise TypeError('Explicit repository read limits required')
        self._runtime, self._operation_id = runtime, operation_id
        self._binding, self._limits, self._private_roots = binding, limits, private_roots
        self._dispatch = self._dispatcher(runtime, frames, binding, journal)
        self._attempted = False
        self._started = False
        self._command = None

    def _location(self, selected):
        return self._keep(
            RepositoryLocationLease,
            selected,
            private_roots=self._private_roots,
            max_file_bytes=self._limits.max_file_bytes,
            max_open_handles=self._limits.max_open_handles,
            max_metadata_entries=self._limits.max_metadata_entries,
        )

    def _metadata(self, location, *, format):
        limits = self._limits
        return self._keep(
            RepositoryMetadataLease,
            location,
            format=format,
            max_entries=limits.max_metadata_entries,
            max_open_handles=limits.max_open_handles,
            max_file_bytes=limits.max_file_bytes,
            max_metadata_bytes=limits.max_metadata_bytes,
        )

    def _config(self, original, location):
        output, nonce, exit_code = self._read(original, location)
        return parse_original_config_output(
            output,
            location,
            scope=original.scope,
            io_nonce=nonce,
            exit_code=exit_code,
            max_output_bytes=self._limits.max_git_output_bytes,
            max_entries=self._limits.max_metadata_entries,
        )

    @contextmanager
    def _prepared_read(
        self,
        original,
        location,
        *,
        kind=None,
        parsed=None,
        metadata=None,
        ref_intent=None,
        object_intent=None,
        reflog=None,
        target_ref=None,
        ancestry=None,
    ):
        command = self._keep(_FixedGitRun, self._runtime, self._binding, self._dispatch, original)
        self._command = command
        source, export = command._open(open_config_export, location, original.scope)
        command._owners.append(source)
        with ExitStack() as leases:
            if kind is not None:
                directories = leases.enter_context(
                    export_metadata_directories(location, original.scope)
                )

            def prepare(stdio):
                if kind is None:
                    return config_prepare_input(stdio, export)
                if kind == 'DELIVERY_REF':
                    return delivery_ref_prepare_input(
                        stdio, directories, export, parsed, metadata, ref_intent, reflog
                    )
                if kind == 'DELIVERY_ANCESTOR':
                    return delivery_ancestry_prepare_input(
                        stdio, directories, export, parsed, metadata, ancestry
                    )
                if kind == 'DELIVERY_TARGET':
                    return delivery_target_prepare_input(
                        stdio, directories, export, parsed, metadata, target_ref
                    )
                if kind == 'DELIVERY_OBJECT':
                    return delivery_object_prepare_input(
                        stdio, directories, export, parsed, metadata, object_intent
                    )
                if ref_intent is not None:
                    return baseline_ref_prepare_input(
                        stdio, directories, export, parsed, metadata, ref_intent
                    )
                return repository_read_prepare_input(
                    stdio, directories, export, parsed, metadata, kind=kind
                )

            yield command, prepare
        self._owners.remove(command)

    def _read(self, original, location, *, kind=None, parsed=None, metadata=None):
        with self._prepared_read(
            original, location, kind=kind, parsed=parsed, metadata=metadata
        ) as (command, prepare):
            return command.run(
                prepare,
                deadline=self._deadline,
                cancelled=self._cancelled,
                max_output_bytes=self._limits.max_git_output_bytes,
            )

    def run(self, *, cancelled):
        if self._attempted or not callable(cancelled):
            raise LaunchOutcomeUnknown('ORIGINAL_REPOSITORY_RUN_REQUIRES_OBSERVATION')
        self._attempted = True
        self._cancelled = cancelled
        self._started_at = monotonic()
        self._deadline = self._started_at + self._limits.max_git_seconds
        try:
            result = self._run()
            self.close()
            return result
        except BaseException as error:
            if self._started and self._records_business_progress:
                try:
                    self._record_failure(error)
                except (OSError, RuntimeError, sqlite3.Error) as state_error:
                    error.state_record_error = state_error
            error.retained_owner = self
            if isinstance(error, WorktreeError):
                rejected = RepositoryLocationError('ORIGINAL_METADATA_OUTPUT_INVALID')
                rejected.retained_owner = self
                raise rejected from error
            raise

    def _record_failure(self, error):
        if self._command is not None and self._command.cleanup_required:
            self._mark_unknown()
            return
        code = _validation_code(error)
        if code is not None:
            self.close()
            self._dispatch.fail_validation(self._operation_id, code)
        elif self._unknown_after_local_error:
            self._mark_unknown()

    def _mark_unknown(self):
        with self._runtime.database.transaction(write=True) as connection:
            operation, steps = self._read_operation(connection)
            mark_repository_read_unknown(connection, operation, steps[0])

    def reconcile_cleanup(self, frames, *, timeout_ms, cancelled):
        if self._command is not None and self._command.cleanup_required:
            self._command.reconcile_cleanup(frames, timeout_ms=timeout_ms, cancelled=cancelled)
        self.close()

    def close(self):
        super().close()
        self._dispatch.close()


class RepositoryRegistrationRun(_RepositoryRun):
    _dispatcher = RegistrationGitDispatch
    _unknown_after_local_error = False

    @property
    def _released(self):
        return self._command is not None and self._command._released

    def _read_operation(self, connection):
        operation, _, steps = _original(connection, self._operation_id)
        return operation, steps

    def _run(self):
        limits = self._limits
        start_repository_registration(self._runtime, self._operation_id)
        self._started = True
        original = self._dispatch.reserve(self._operation_id)
        with self._runtime.database.transaction() as connection:
            _, fixed, _ = _original(connection, self._operation_id)
        location = self._location(fixed['root_path'])
        parsed = self._config(original, location)
        return self._dispatch.publish_registration(
            self._operation_id,
            location,
            parsed,
            max_entries=limits.max_metadata_entries,
            max_open_handles=limits.max_open_handles,
            max_file_bytes=limits.max_file_bytes,
            max_metadata_bytes=limits.max_metadata_bytes,
        )


class RepositoryObservationRun(_RepositoryRun):
    _dispatcher = ObservationGitDispatch
    _unknown_after_local_error = True

    def _read_operation(self, connection):
        return _original_observation(connection, self._operation_id)

    def _run(self):
        source = start_repository_observation(self._runtime, self._operation_id)
        self._started = True
        config, worktrees, branches = self._dispatch.reserve(self._operation_id)
        location = self._location(source.root)
        facts = location.verify()
        if (
            facts.root.canonical_path != source.root
            or facts.common_directory.canonical_path != source.common_directory
        ):
            raise RepositoryLocationError('ORIGINAL_REPOSITORY_LOCATION_DIFFERS', changed=True)
        parsed = self._config(config, location)
        if parsed.local.object_format != source.object_format:
            raise RepositoryLocationError('ORIGINAL_REPOSITORY_FORMAT_DIFFERS', changed=True)
        metadata = self._metadata(location, format=parsed.local.object_format)
        worktrees_output, _, _ = self._read(
            worktrees, location, kind='WORKTREES', parsed=parsed, metadata=metadata
        )
        branches_output, _, _ = self._read(
            branches, location, kind='LOCAL_BRANCHES', parsed=parsed, metadata=metadata
        )
        return self._dispatch.publish_observation(
            self._operation_id,
            metadata,
            parsed,
            worktrees_output=worktrees_output,
            branches_output=branches_output,
            private_roots=self._private_roots,
            max_file_bytes=self._limits.max_file_bytes,
            max_open_handles=self._limits.max_open_handles,
            max_output_bytes=self._limits.max_git_output_bytes,
        )


class RepositoryBaselineValidationRun(_RepositoryRun):
    """Execute only the original C05 VALIDATE_COMMIT step."""

    _dispatcher = BaselineGitDispatch
    _unknown_after_local_error = True

    def _read_operation(self, connection):
        operation, _, steps = original_baseline(connection, self._operation_id)
        return operation, steps

    def _check_active(self):
        if self._cancelled():
            raise LaunchOutcomeUnknown('ORIGINAL_BASELINE_CANCELLED')
        _remaining(self._deadline)

    def _run(self):
        source = start_baseline_validation(self._runtime, self._operation_id)
        return self._read_original_objects(source)

    def _read_original_objects(
        self, source, *, pinned_ref=None, metadata=None, stage=None, consume_file=None
    ):
        self._started = True
        self._deadline = min(self._deadline, self._started_at + source.read_limits.max_seconds)
        config, objects = self._dispatch.reserve(self._operation_id)
        location = self._location(source.root) if metadata is None else metadata.location
        facts = location.verify()
        if (
            facts.root.canonical_path != source.root
            or facts.common_directory.canonical_path != source.common_directory
        ):
            raise RepositoryLocationError('ORIGINAL_BASELINE_LOCATION_DIFFERS', changed=True)
        parsed = self._config(config, location)
        if parsed.local.object_format != source.format:
            raise RepositoryLocationError('ORIGINAL_BASELINE_FORMAT_DIFFERS', changed=True)
        if metadata is None:
            metadata = self._metadata(location, format=source.format)
        if pinned_ref is not None:
            verify_baseline_ref(metadata, source, *pinned_ref)

        if stage is not None:

            def consume_file(entry, raw):
                return self._open(stage.consume, entry, raw)

        def inspect(read_object):
            return inspect_baseline_source(
                source,
                metadata,
                read_object,
                check_active=self._check_active,
                materialization_root=(
                    self._dispatch._journal.root / 'baseline-workspace'
                    if stage is None
                    else stage.target
                ),
                consume_file=consume_file,
            )

        with (
            metadata.hold(),
            self._prepared_read(
                objects, location, kind='OBJECT_BATCH', parsed=parsed, metadata=metadata
            ) as (command, prepare),
        ):
            inspection, completed = command.run_batch(
                prepare,
                inspect,
                format=source.format,
                max_requests=min(
                    MAX_SAFE_INTEGER,
                    source.read_limits.max_objects + source.read_limits.max_edges + 1,
                ),
                max_output_bytes=min(source.output_budget, self._limits.max_git_output_bytes),
                deadline=self._deadline,
                cancelled=self._cancelled,
            )
        return self._complete_objects(source, metadata, parsed, inspection, completed)

    def _complete_objects(self, source, metadata, parsed, inspection, completed):
        return self._dispatch.complete_validation(
            self._operation_id, source, metadata, parsed, inspection.proof, completed
        )


class RepositoryBaselinePinRun(_RepositoryRun):
    """Execute only the original C05 PIN_COMMIT step."""

    _dispatcher = BaselinePinGitDispatch
    _unknown_after_local_error = True

    def _read_operation(self, connection):
        operation, _, steps = original_baseline(connection, self._operation_id)
        return operation, steps

    def _mark_unknown(self):
        with self._runtime.database.transaction(write=True) as connection:
            operation, steps = self._read_operation(connection)
            mark_repository_read_unknown(connection, operation, steps[1])

    def _record_failure(self, error):
        try:
            super()._record_failure(error)
        except StorageUnavailable:
            self._mark_unknown()

    def _run(self):
        source, proof, intent = start_baseline_pin(self._runtime, self._operation_id)
        self._started = True
        self._deadline = min(self._deadline, self._started_at + source.read_limits.max_seconds)
        config, pin = self._dispatch.reserve(self._operation_id)
        location = self._location(source.root)
        facts = location.verify()
        if (
            facts.root.canonical_path != source.root
            or facts.common_directory.canonical_path != source.common_directory
        ):
            raise RepositoryLocationError('ORIGINAL_BASELINE_LOCATION_DIFFERS', changed=True)
        parsed = self._config(config, location)
        if parsed.local.object_format != source.format:
            raise RepositoryLocationError('ORIGINAL_BASELINE_FORMAT_DIFFERS', changed=True)
        metadata = self._metadata(location, format=parsed.local.object_format)

        def record_prepared(process, lock):
            return self._dispatch.record_prepared(
                self._operation_id, source, proof, intent, process, lock
            )

        def authorize_commit(process, original):
            return self._dispatch.authorize_commit(self._operation_id, process, original)

        with BaselineRefGuard(metadata, intent) as ref_guard:
            if metadata.verify().fingerprint_sha256 != proof.repository_sha256:
                raise RepositoryLocationError('ORIGINAL_BASELINE_SOURCE_DIFFERS', changed=True)
            with self._prepared_read(
                pin,
                location,
                kind='BASELINE_REF',
                parsed=parsed,
                metadata=metadata,
                ref_intent=intent,
            ) as (command, prepare):
                process, original, observed = command.run_ref(
                    prepare,
                    ref_guard,
                    intent,
                    record_prepared,
                    authorize_commit,
                    max_output_bytes=min(source.output_budget, self._limits.max_git_output_bytes),
                    deadline=self._deadline,
                    cancelled=self._cancelled,
                )
            return self._dispatch.confirm_commit(
                self._operation_id, process, original, intent, observed
            )


class RepositoryBaselineVerifyRun(RepositoryBaselineValidationRun):
    """Re-read the original pinned objects before saving the only snapshot."""

    _dispatcher = BaselineVerifyGitDispatch

    def _run(self):
        source, pinned = start_baseline_verify(self._runtime, self._operation_id)
        return self._read_original_objects(source, pinned_ref=pinned)

    def _mark_unknown(self):
        with self._runtime.database.transaction(write=True) as connection:
            operation, steps = self._read_operation(connection)
            mark_repository_read_unknown(connection, operation, steps[2])

    def _complete_objects(self, source, metadata, parsed, inspection, completed):
        return self._dispatch.publish_baseline(
            self._operation_id, source, metadata, parsed, inspection.proof, completed
        )


class RepositoryBaselineRecoveryRun(RepositoryBaselineVerifyRun):
    """Resolve an original closed write from its evidence and a read-only full closure."""

    _dispatcher = BaselineRecoveredVerifyGitDispatch

    def _run(self):
        source, proof, intent = pending_baseline_pin_observation(self._runtime, self._operation_id)
        self._deadline = min(self._deadline, self._started_at + source.read_limits.max_seconds)
        self._check_active()
        pin = self._keep(
            BaselinePinGitDispatch, self._runtime, None, self._binding, self._dispatch._journal
        )
        original = pin.reopen_commit_dispatch(self._operation_id, source, proof, intent)
        location = self._location(source.root)
        facts = location.verify()
        if (
            facts.root.canonical_path != source.root
            or facts.common_directory.canonical_path != source.common_directory
            or facts.fingerprint_sha256 != original.location_sha256
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_BASELINE_OBSERVED_LOCATION_DIFFERS')
        metadata = self._metadata(location, format=source.format)
        observed = inspect_baseline_ref(metadata, source, intent.full_ref, original.location_sha256)
        self._check_active()
        ref = (observed.file, original.location_sha256)
        checked, pinned = start_baseline_verify(
            self._runtime, self._operation_id, recovering_ref=ref
        )
        self._started = True
        if checked != source or pinned[0] != intent.full_ref:
            raise StorageUnavailable('Original baseline observation inputs differ')
        self._observation = (pin, original, intent, ref)
        return self._read_original_objects(source, pinned_ref=pinned, metadata=metadata)

    def _record_failure(self, error):
        with self._runtime.database.transaction(write=True) as connection:
            operation, steps = self._read_operation(connection)
            if operation['status'] == 'UNKNOWN' and steps[2]['status'] == 'RUNNING':
                connection.execute(
                    "UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=? "
                    'WHERE operation_id=? AND step_no=3',
                    (operation_time(None), self._operation_id),
                )

    def _complete_objects(self, source, metadata, parsed, inspection, completed):
        pin, original, intent, ref = self._observation

        def record_observation(observed):
            return pin.record_observation(original, intent, observed)

        return self._dispatch.publish_baseline(
            self._operation_id,
            source,
            metadata,
            parsed,
            inspection.proof,
            completed,
            observed_pin=(ref, record_observation),
        )


class RepositoryBaselineQueryRun(RepositoryBaselineValidationRun):
    """Read a registered snapshot through fresh, private Guard scopes."""

    _dispatcher = BaselineQueryGitDispatch
    _records_business_progress = False

    def __init__(
        self,
        runtime,
        snapshot_id,
        frames,
        binding,
        journal,
        *,
        private_roots,
        limits,
        finish=None,
        new_stage=None,
        restore_parent=None,
        consume_file=None,
    ):
        self._finish = finish
        self._consume_file = consume_file
        self._new_stage = new_stage
        self._restore_parent = restore_parent
        self._stage = None
        self._snapshot, self._source, self._proof, self._location_digest = load_baseline_query(
            runtime, snapshot_id
        )
        super().__init__(
            runtime,
            self._snapshot['registration_operation_id'],
            frames,
            binding,
            journal,
            private_roots=private_roots,
            limits=limits,
        )
        self._query_reserved = False

    def _run(self):
        source = self._source
        self._deadline = min(self._deadline, self._started_at + source.read_limits.max_seconds)
        self._check_active()
        location = self._location(source.root)
        if self._restore_parent is not None:
            # Keep the exact source evidence of the registered baseline. A
            # workspace destination is a separate bound exclusion.
            location.require_disjoint_directory(self._restore_parent.verify())
        metadata = self._metadata(location, format=source.format)
        full_ref = self._snapshot['retention_ref']
        observed = inspect_baseline_ref(metadata, source, full_ref, self._location_digest)
        self._check_active()
        self._dispatch.reserve_query(self._snapshot['id'], self._operation_id)
        self._query_reserved = True
        if self._new_stage is not None:
            self._stage = self._open(self._new_stage, self._check_active, self._dispatch.query_id)
        return self._read_original_objects(
            source,
            pinned_ref=(full_ref, observed.file, self._location_digest),
            metadata=metadata,
            stage=self._stage,
            consume_file=self._consume_file,
        )

    def _complete_objects(self, source, metadata, parsed, inspection, completed):
        proof = inspection.proof
        self._dispatch._verify_completed_batch(
            self._operation_id, source, metadata, parsed, proof, completed
        )
        if (
            proof.tree_oid != self._proof.tree_oid
            or proof.content_sha256 != self._proof.content_sha256
        ):
            raise GitObjectReadError('ORIGINAL_BASELINE_QUERY_CONTENT_DIFFERS')
        result = BaselineQueryResult(self._snapshot, inspection.entries)
        if self._finish is None and self._stage is None:
            return result

        def verify_active_source():
            self._check_active()
            metadata.verify()

        with metadata.hold():
            self._check_active()
            if self._stage is not None:
                return self._open(self._stage.publish, result, verify_active_source)
            return self._finish(result, verify_active_source)

    def close(self):
        super().close()
        if self._query_reserved:
            self._dispatch.retire()
            self._query_reserved = False
