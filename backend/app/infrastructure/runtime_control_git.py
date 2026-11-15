"""Guard-internal original native resource ownership, never business scheduling.

Only fixed probes, typed private config parses and typed repository reads are registered. The authenticated-controller,
program/IO/directory/Job owners retain their original objects until release.
No record can authorize execution, reopen a PID or reconstruct a lost Job.
"""

import hashlib
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from threading import Event, RLock, Thread
from time import monotonic
from uuid import uuid4

from backend.app.shared.validation import strict_json_object

from .git_config_command import ConfigCommandError
from .git_local_config import GitConfigError
from .git_metadata_command import MetadataCommandError
from .git_ref_metadata import RefMetadataError
from .git_repository_location import RepositoryLocationError
from .git_repository_metadata import MetadataTreeError
from .git_repository_read import RepositoryReadError
from .guard_action_journal import GuardActionJournal
from .guard_action_records import GuardActionStart
from .runtime_control_git_preparation import ControlGitPreparation
from .runtime_launch_journal import (
    LaunchFenceError,
    LaunchJournal,
    LaunchOutcomeUnknown,
    LaunchScope,
    _bytes,
)
from .windows_config_copy import ConfigCopyError
from .windows_config_source import ConfigReadError
from .windows_controller_token import ControllerPrimaryToken
from .windows_job import JobBoundaryError
from .windows_local_paths import PathBoundaryError
from .windows_native_process import NativeLaunchError, SuspendedControlGit, control_git_input_sha256
from .windows_private_package import PackageSecurityError
from .windows_private_record import PrivateRecordAppend, PrivateRecordError
from .windows_process import ObservedProcess, ProcessObservationError
from .windows_stdio import StdioBoundaryError

MAX_RESOURCE_RECORD_BYTES = 64 * 1024
MAX_RESOURCE_RECORDS = 100000
MAX_CONTROLLER_SCOPES = 128


class NativeRegistryError(RuntimeError):
    pass


NATIVE_RESOURCE_ERRORS = (
    NativeRegistryError,
    NativeLaunchError,
    StdioBoundaryError,
    ConfigCommandError,
    MetadataCommandError,
    RepositoryReadError,
    MetadataTreeError,
    RepositoryLocationError,
    RefMetadataError,
    ConfigCopyError,
    ConfigReadError,
    GitConfigError,
    ProcessObservationError,
    JobBoundaryError,
    LaunchFenceError,
    PathBoundaryError,
    PackageSecurityError,
    PrivateRecordError,
    OSError,
    ValueError,
)


@dataclass(frozen=True)
class NativeReceipt:
    filename: str
    sha256: str


class _Entry:
    def __init__(self, scope, pin, job, streams, directory, digest, arguments, preparation=None):
        self.gate = RLock()
        self.scope, self.pin, self.job = scope, pin, job
        self.streams, self.directory, self.digest = streams, directory, digest
        self.arguments = arguments
        self.preparation = preparation
        self.job_ref = uuid4().hex if preparation is None else preparation.binding_ref
        self.root = None
        self.released = False
        self.stop_requested = False
        self.watch_settled = False
        self.receipt = None
        self.last_record_facts = None
        self.pending_record = None
        self.pending_record_facts = None
        self.creation_stdio_closed = False


class ControlGitRegistry:
    """One controller's original OS objects; all raw references stay in Guard."""

    def __init__(self, journal, controller, *, controller_ref):
        if type(journal) is not LaunchJournal or type(controller) is not ControllerPrimaryToken:
            raise NativeRegistryError('ORIGINAL_GUARD_OWNERS_REQUIRED')
        LaunchScope(controller_ref, 1, 1, 'controller-reference-validation')
        journal._verify()
        with controller.creation_handle():
            pass
        self._journal, self._controller = journal, controller
        self._controller_ref = controller_ref
        self._gate = RLock()
        self._entries = {}
        self._preparations = {}
        self._task_stops = {}
        self._task_watch_gate = RLock()
        self._task_watch_paused = False
        self._settled_task_stops = set()
        self._admission_closed = False
        self._watch_reason = None
        self._watch_error = None
        self._watch_stop = Event()
        self._watch_thread = None
        self._watch_source = None
        self.guard_run_ref = uuid4().hex
        with ObservedProcess(os.getpid()) as guard:
            self._guard_identity = guard.identity
        # Last allocation in the constructor: failure retains at most the
        # exact new read-only process owner, never a partially started watch.
        self._watch_source = controller._controller.duplicate()

    def _entry(self, scope):
        if not isinstance(scope, LaunchScope) or scope.controller_ref != self._controller_ref:
            raise NativeRegistryError('ORIGINAL_CONTROLLER_SCOPE_REQUIRED')
        with self._gate:
            entry = self._entries.get(scope.key)
        if entry is None:
            raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_RESOURCE_NOT_REGISTERED')
        return entry

    def begin_preparation(self, actions, start):
        if (
            type(actions) is not GuardActionJournal
            or actions._journal is not self._journal
            or type(start) is not GuardActionStart
            or start.record.scope.controller_ref != self._controller_ref
            or start.record.action != 'PREPARE'
        ):
            raise NativeRegistryError('ORIGINAL_PREPARATION_INTENT_OWNER_REQUIRED')
        scope = start.record.scope
        if actions.find(scope, 'PREPARE') != start.record:
            raise LaunchOutcomeUnknown('ORIGINAL_PREPARATION_INTENT_UNVERIFIED')
        with self._gate:
            existing = self._preparations.get(scope.key)
            if existing is not None:
                if existing.intent != start.record:
                    raise NativeRegistryError('ORIGINAL_PREPARATION_INPUT_CONFLICT')
                return existing
            if scope.key in self._entries:
                raise NativeRegistryError('ORIGINAL_NATIVE_BINDING_ALREADY_PREPARED')
            if not start.first_accepted:
                raise LaunchOutcomeUnknown('ORIGINAL_PREPARATION_OWNER_NOT_RETAINED')
            if len(self._entries.keys() | self._preparations.keys()) >= MAX_CONTROLLER_SCOPES:
                raise NativeRegistryError('CONTROLLER_SCOPE_CAPACITY_EXHAUSTED')
            preparation = ControlGitPreparation(self, start)
            self._preparations[scope.key] = preparation
            closed = self._admission_closed
        if closed:
            preparation.request_stop()
        return preparation

    def register(
        self, scope, pin, job, streams, directory, *, arguments=('--version',), preparation=None
    ):
        """Attach the original held resources BEFORE any native create callback."""
        if not isinstance(scope, LaunchScope) or scope.controller_ref != self._controller_ref:
            raise NativeRegistryError('ORIGINAL_CONTROLLER_SCOPE_REQUIRED')
        with self._gate:
            existing_preparation = self._preparations.get(scope.key)
            if existing_preparation is not preparation:
                raise NativeRegistryError('ORIGINAL_PREPARATION_TRANSFER_REQUIRED')
        if preparation is not None:
            if type(preparation) is not ControlGitPreparation or preparation.registry is not self:
                raise NativeRegistryError('ORIGINAL_PREPARATION_OWNER_REQUIRED')
            preparation.begin_transfer(
                {'PROGRAM': pin, 'JOB': job, 'STDIO': streams, 'DIRECTORY': directory},
                arguments,
            )
        completed = False
        try:
            digest = control_git_input_sha256(
                self._controller,
                pin,
                job,
                streams,
                directory,
                scope,
                arguments,
            )
            with self._gate:
                if self._admission_closed:
                    raise NativeRegistryError('CONTROLLER_ADMISSION_CLOSED')
                existing = self._entries.get(scope.key)
                if existing is not None:
                    if existing.digest != digest or any(
                        (
                            existing.pin is not pin,
                            existing.job is not job,
                            existing.streams is not streams,
                            existing.directory is not directory,
                            existing.arguments != arguments,
                        )
                    ):
                        raise NativeRegistryError('ORIGINAL_NATIVE_BINDING_CONFLICT')
                    if existing.released:
                        raise NativeRegistryError('ORIGINAL_NATIVE_BINDING_RELEASED')
                    entry = existing
                elif len(self._entries) >= MAX_CONTROLLER_SCOPES:
                    raise NativeRegistryError('CONTROLLER_SCOPE_CAPACITY_EXHAUSTED')
                else:
                    prior = self._journal.inspect(scope)
                    if prior is not None and (prior.stop_closed or prior.create_state != 'NONE'):
                        raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_BINDING_NOT_PREPARED')
                    members = job.observe_members()
                    if not members.complete or members.process_ids or members.assigned_count:
                        raise NativeRegistryError('NEW_EMPTY_ORIGINAL_JOB_REQUIRED')
                    entry = _Entry(
                        scope, pin, job, streams, directory, digest, arguments, preparation
                    )
                    # Retain even if persistence fails. Never lose cleanup ownership.
                    self._entries[scope.key] = entry
            with entry.gate:
                if entry.receipt is not None:
                    self.read_receipt(scope, entry.receipt)
                    completed = True
                    return entry.receipt
                current = self._journal.prepare(scope, digest)
                if current.stop_closed or current.create_state != 'NONE':
                    raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_BINDING_NOT_PREPARED')
                receipt = self._record(entry, 'PREPARED')
                completed = True
                return receipt

        finally:
            if preparation is not None:
                with self._gate:
                    attached = self._entries.get(scope.key)
                preparation.finish_transfer(attached, completed=completed)

    def _facts(self, entry, phase):
        fence = self._journal.inspect(entry.scope)
        if fence is None:
            raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_FENCE_NOT_FOUND')
        root = entry.root
        observation = None
        if root is not None and not entry.released:
            try:
                actual = root.observe()
                observation = {
                    'state': actual.state,
                    'identity': asdict(actual.identity),
                    'exit_code': actual.exit_code,
                }
            except (NativeLaunchError, ProcessObservationError, OSError):
                observation = {'state': 'UNKNOWN', 'identity': None, 'exit_code': None}
        return {
            'schema_version': 1,
            'guard_run_ref': self.guard_run_ref,
            'guard_identity': asdict(self._guard_identity),
            'scope': asdict(entry.scope),
            'input_sha256': entry.digest,
            'job_ref': entry.job_ref,
            'stdio_binding': asdict(entry.streams.binding),
            'program': asdict(entry.pin.identity),
            'directory': asdict(entry.directory.identity),
            'phase': phase,
            'fence': asdict(fence),
            'resource_ref': None if root is None else root.resource_ref,
            'original_process_identity': (
                None if root is None or root.identity is None else asdict(root.identity)
            ),
            'native_resume_state': None if root is None else root.resume_state,
            'native_handles_released': entry.released,
            'creation_stdio_closed': entry.creation_stdio_closed,
            'stop_requested': entry.stop_requested,
            'observation': observation,
        }

    def _record(self, entry, phase):
        self._reconcile_record(entry)
        facts = self._facts(entry, phase)
        comparable = _bytes(facts)
        if entry.receipt is not None and entry.last_record_facts == comparable:
            self.read_receipt(entry.scope, entry.receipt)
            return entry.receipt
        facts['recorded_at'] = (
            datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        )
        raw = _bytes(facts)
        strict_json_object(raw)
        if len(raw) > MAX_RESOURCE_RECORD_BYTES:
            raise LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_TOO_LARGE')
        with self._journal._scope(entry.scope):
            self._journal._verify()
            with os.scandir(self._journal.root) as listing:
                count = sum(row.name.endswith('.native.json') for row in listing)
            if count >= MAX_RESOURCE_RECORDS:
                raise LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_CAPACITY_EXHAUSTED')
            name = entry.scope.key + '.' + uuid4().hex + '.native.json'
            writer = None
            entry.pending_record_facts = comparable
            try:
                writer = PrivateRecordAppend(
                    self._journal._package,
                    name,
                    raw,
                    max_record_bytes=MAX_RESOURCE_RECORD_BYTES,
                )
                entry.pending_record = writer
                reference = writer.publish()
                writer.close()
                receipt = NativeReceipt(reference.filename, reference.sha256)
                if self._journal._package.verify_member(name, directory=False) != reference.file:
                    raise LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_IDENTITY_UNVERIFIED')
                self.read_receipt(entry.scope, receipt)
                entry.receipt = receipt
                entry.last_record_facts = comparable
                entry.pending_record = None
                entry.pending_record_facts = None
                return receipt
            except BaseException as original:
                retained = getattr(original, 'retained_owner', None)
                if writer is None and type(retained) is PrivateRecordAppend:
                    entry.pending_record = retained
                error = LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_PUBLISH_UNVERIFIED')
                error.retained_owner = self
                raise error from original

    def _reconcile_record(self, entry):
        writer = entry.pending_record
        if writer is None:
            return
        with self._journal._scope(entry.scope):
            try:
                writer.close()
                if not writer._rename_may:
                    # Exact unpublished CREATE_NEW cleanup succeeded. No
                    # native/Git callback is retried by evidence reconciliation.
                    entry.pending_record = None
                    entry.pending_record_facts = None
                    return
                if writer._identity is None:
                    raise LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_IDENTITY_UNVERIFIED')
                expected = replace(writer._identity, canonical_path=str(writer._target))
                if (
                    self._journal._package.verify_member(writer._filename, directory=False)
                    != expected
                ):
                    raise LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_IDENTITY_UNVERIFIED')
                receipt = NativeReceipt(writer._filename, writer._sha256)
                self.read_receipt(entry.scope, receipt)
                entry.receipt = receipt
                entry.last_record_facts = entry.pending_record_facts
                entry.pending_record = None
                entry.pending_record_facts = None
            except BaseException as original:
                error = LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_STILL_UNVERIFIED')
                error.retained_owner = self
                raise error from original

    def read_receipt(self, scope, receipt):
        self._entry(scope)
        if (
            type(receipt) is not NativeReceipt
            or type(receipt.filename) is not str
            or type(receipt.sha256) is not str
            or not receipt.filename.startswith(scope.key + '.')
            or not receipt.filename.endswith('.native.json')
            or len(receipt.filename) != 64 + 1 + 32 + 12
            or any(char not in '0123456789abcdef' for char in receipt.filename[65:97])
            or len(receipt.sha256) != 64
            or any(char not in '0123456789abcdef' for char in receipt.sha256)
        ):
            raise NativeRegistryError('ORIGINAL_NATIVE_RECEIPT_REQUIRED')
        with self._journal._scope(scope):
            self._journal._package.verify_member(receipt.filename, directory=False)
            path = self._journal.root / receipt.filename
            with path.open('rb') as stream:
                raw = stream.read(MAX_RESOURCE_RECORD_BYTES + 1)
            if (
                len(raw) > MAX_RESOURCE_RECORD_BYTES
                or hashlib.sha256(raw).hexdigest() != receipt.sha256
            ):
                raise LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_BYTES_UNVERIFIED')
            value = strict_json_object(raw)
            if (
                _bytes(value) != raw
                or value.get('scope') != asdict(scope)
                or value.get('guard_run_ref') != self.guard_run_ref
            ):
                raise LaunchOutcomeUnknown('NATIVE_RESOURCE_RECORD_OWNER_UNVERIFIED')
            # Private evidence only: NEVER feed these bytes to create/resume.
            return value

    def create(self, scope):
        entry = self._entry(scope)
        with entry.gate:
            if entry.stop_requested:
                fence = self._journal.inspect(scope)
                if fence is not None and fence.stop_closed:
                    return self._facts(entry, 'CLOSED')
                raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_STOP_CLOSURE_UNVERIFIED')
            if entry.released:
                raise NativeRegistryError('ORIGINAL_NATIVE_BINDING_RELEASED')
            if entry.receipt is None:
                raise LaunchOutcomeUnknown('NATIVE_PREPARE_RECEIPT_REQUIRED')
            with self._gate:
                if self._admission_closed:
                    raise NativeRegistryError('CONTROLLER_ADMISSION_CLOSED')

            def dispatch():
                try:
                    root = SuspendedControlGit(
                        self._controller,
                        entry.pin,
                        entry.job,
                        entry.streams,
                        entry.directory,
                        scope=scope,
                        fence=self._journal.inspect(scope),
                        arguments=entry.arguments,
                    )
                except BaseException as error:
                    retained = getattr(error, 'retained_owner', None)
                    if type(retained) is SuspendedControlGit:
                        entry.root = retained
                    raise
                entry.root = root
                self._record(entry, 'CREATED')
                return root.resource_ref

            fence = self._journal.dispatch_create(scope, entry.digest, dispatch)
            if fence.stop_closed:
                return self._facts(entry, 'CLOSED')
            if entry.root is None or fence.resource_ref != entry.root.resource_ref:
                raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_RESOURCE_REQUIRES_OBSERVATION')
            return self._facts(entry, 'CREATED')

    def resume(self, scope):
        entry = self._entry(scope)
        with entry.gate:
            if entry.stop_requested:
                raise LaunchOutcomeUnknown('ORIGINAL_STOP_REQUESTED')
            with self._gate:
                if self._admission_closed:
                    raise NativeRegistryError('CONTROLLER_ADMISSION_CLOSED')
            if entry.root is None or entry.released:
                raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_RESOURCE_REQUIRES_OBSERVATION')

            def dispatch():
                entry.root.resume_once(self._journal.inspect(scope))
                self._record(entry, 'RESUME_ACK')

            # The child already holds its inherited copies. Guard must release
            # its creation-only copies BEFORE resuming, otherwise backend EOF
            # can never prove output completion after the child exits.
            fence = self._journal.inspect(scope)
            if (
                fence is None
                or fence.create_state != 'RESOURCE_RECORDED'
                or fence.resource_ref != entry.root.resource_ref
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_CREATE_UNVERIFIED')
            entry.streams.close()
            entry.creation_stdio_closed = True
            self._journal.dispatch_resume(scope, entry.root.resource_ref, dispatch)
            return self._facts(entry, 'OBSERVED')

    def observe(self, scope):
        entry = self._entry(scope)
        with entry.gate:
            self._record(entry, 'OBSERVED')
            return self._facts(entry, 'OBSERVED')

    def stop(self, scope):
        if not isinstance(scope, LaunchScope) or scope.controller_ref != self._controller_ref:
            raise NativeRegistryError('ORIGINAL_CONTROLLER_SCOPE_REQUIRED')
        with self._gate:
            preparation = self._preparations.get(scope.key)
            complete = scope.key in self._entries
        if preparation is not None and not complete:
            preparation.request_stop()
            return preparation.describe()
        entry = self._entry(scope)
        if entry.preparation is not None:
            entry.preparation._stop.set()
        with entry.gate:
            entry.stop_requested = True
            closure_error = None
            try:
                self._journal.close_nonce(scope)
            except NATIVE_RESOURCE_ERRORS as error:
                closure_error = error
            # Even if durable closure failed, request termination of this original
            # already-owned Job; preserve unknown and never reopen admission.
            entry.job.terminate_owned(1)
            if closure_error is not None:
                raise LaunchOutcomeUnknown(
                    'ORIGINAL_NATIVE_STOP_CLOSURE_UNVERIFIED'
                ) from closure_error
            self._record(entry, 'STOP_REQUESTED')
            return self._facts(entry, 'STOP_REQUESTED')

    def stop_owned_for_shutdown(self, *, deadline):
        """Seal and stop this registry's original scopes; do not declare business cleanup."""
        with self._gate:
            self._admission_closed = True
            preparations = tuple(self._preparations.values())
            entries = tuple(self._entries.values())
        failures = []
        for preparation in preparations:
            if preparation.handles_released:
                continue
            try:
                preparation.request_stop()
            except (RuntimeError, OSError) as error:
                failures.append(error)
                try:
                    preparation._terminate_known_job()
                except (RuntimeError, OSError) as stopped:
                    failures.append(stopped)
        for entry in entries:
            if entry.released:
                continue
            try:
                self.stop(entry.scope)
            except (RuntimeError, OSError) as error:
                failures.append(error)
        try:
            self._sweep_task_stops(closing=True, deadline=deadline)
        except (RuntimeError, OSError) as error:
            failures.append(error)
        pause = Event()
        for preparation in preparations:
            if preparation.handles_released:
                continue
            verified = False
            while True:
                try:
                    preparation.verify_release_ready()
                    verified = True
                    break
                except (RuntimeError, OSError) as error:
                    retained = getattr(error, 'retained_owner', None)
                    if retained is not None:
                        failures.append(error)
                        break
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        failures.append(error)
                        break
                    # Repeat only read-only activity observation. Unknown native
                    # release/close is never retried by this shutdown loop.
                    pause.wait(min(remaining, 0.01))
            if not verified:
                continue
            try:
                entry = self._entries.get(preparation.scope.key)
                if entry is not None and not entry.released:
                    self.release_native_handles(preparation.scope)
                preparation.close_stopped_handles()
            except (RuntimeError, OSError) as error:
                failures.append(error)
        if failures:
            error = LaunchOutcomeUnknown('ORIGINAL_GUARD_SHUTDOWN_UNVERIFIED')
            error.retained_owner = self
            raise error from failures[0]

    def release_native_handles(self, scope):
        """Only original process handles; caller still owns Job/IO/pin/ACL cleanup."""
        entry = self._entry(scope)
        with entry.gate:
            fence = self._journal.inspect(scope)
            if fence is None or not fence.stop_closed:
                raise NativeRegistryError('ORIGINAL_STOP_CLOSURE_REQUIRED')
            if entry.root is None and fence.create_state != 'NONE':
                raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_CREATE_UNVERIFIED')
            members = entry.job.observe_members()
            if not members.complete or members.process_ids or members.assigned_count:
                raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_JOB_STILL_ACTIVE_OR_UNKNOWN')
            if entry.root is not None and not entry.released:
                entry.root.close()
            entry.released = True
            self._record(entry, 'NATIVE_HANDLES_RELEASED')
            return self._facts(entry, 'NATIVE_HANDLES_RELEASED')

    def register_task_stop(self, scope, stop):
        if scope.controller_ref != self._controller_ref or not callable(stop):
            raise NativeRegistryError('ORIGINAL_TASK_WATCH_OWNER_REQUIRED')
        with self._gate:
            if self._admission_closed or scope in self._task_stops:
                raise LaunchOutcomeUnknown('ORIGINAL_TASK_WATCH_ADMISSION_CLOSED')
            self._task_stops[scope] = stop

    @contextmanager
    def pause_task_watch_for_close(self):
        # Controller sealing requires zero in-flight journal scopes.
        with self._task_watch_gate:
            self._task_watch_paused = True
        try:
            yield
        finally:
            with self._task_watch_gate:
                self._task_watch_paused = False

    def _sweep_task_stops(self, *, closing, deadline=None):
        with self._task_watch_gate:
            if self._task_watch_paused and not closing:
                return
            self._run_task_stops(closing=closing, deadline=deadline)

    def record_task_stopped(self, scope, stop):
        with self._gate:
            if self._task_stops.get(scope) != stop:
                raise NativeRegistryError('ORIGINAL_TASK_WATCH_OWNER_REQUIRED')
            self._settled_task_stops.add(scope)

    def _run_task_stops(self, *, closing, deadline=None):
        with self._gate:
            pending = tuple(
                (scope, stop)
                for scope, stop in self._task_stops.items()
                if scope not in self._settled_task_stops
            )
        failures = []
        for scope, stop in pending:
            try:
                with self._journal._scope(scope, blocking=closing) as acquired:
                    if not acquired:
                        continue
                    with self._gate:
                        if scope in self._settled_task_stops:
                            continue
                    expires = monotonic() + (5 if closing else 0.05)
                    if deadline is not None:
                        # Even after expiry, give every known owner its one stop
                        # request. The original callback terminates before its
                        # deadline-bounded observation; no waiting is extended.
                        expires = min(expires, deadline)
                    stop(lambda: None, expires)
                    with self._gate:
                        self._settled_task_stops.add(scope)
            except NATIVE_RESOURCE_ERRORS as error:
                if closing:
                    failures.append(error)
                else:
                    self._watch_error = 'ORIGINAL_TASK_CONTROLLER_CLEANUP_UNVERIFIED'
        if failures:
            error = LaunchOutcomeUnknown('ORIGINAL_TASK_CONTROLLER_CLEANUP_UNVERIFIED')
            error.retained_owner = self
            raise error from failures[0]

    def sweep_controller(self):
        """Nonblocking across scopes; one busy create cannot block another Job."""
        source = self._watch_source
        if source is None:
            raise NativeRegistryError('ORIGINAL_CONTROLLER_WATCH_CLOSED')
        try:
            observation = source.observe()
            if observation.state == 'RUNNING':
                return None
            reason = 'CONTROLLER_EXITED'
        except (ProcessObservationError, OSError):
            reason = 'CONTROLLER_OBSERVATION_UNKNOWN'
        with self._gate:
            self._admission_closed = True
            self._watch_reason = reason
            entries = tuple(self._entries.values())
            preparations = tuple(self._preparations.values())
        settled = {entry.scope.key for entry in entries if entry.watch_settled}
        for preparation in preparations:
            if preparation.handles_released or preparation.scope.key in settled:
                continue
            try:
                preparation.request_stop()
            except NATIVE_RESOURCE_ERRORS:
                self._watch_error = 'ORIGINAL_CONTROLLER_CLEANUP_UNVERIFIED'
        for entry in entries:
            if entry.scope.key in settled or not entry.gate.acquire(blocking=False):
                continue
            try:
                if not entry.released:
                    try:
                        self.stop(entry.scope)
                    except NATIVE_RESOURCE_ERRORS:
                        self._watch_error = 'ORIGINAL_CONTROLLER_CLEANUP_UNVERIFIED'
                    else:
                        if entry.preparation is not None:
                            try:
                                entry.preparation.verify_no_activity()
                            except NATIVE_RESOURCE_ERRORS:
                                pass  # The original Job can still be exiting.
                            else:
                                # The durable fence prevents new writes. Keep the original
                                # handles available for a verified recovery RELEASE.
                                entry.watch_settled = True
            finally:
                entry.gate.release()
        self._sweep_task_stops(closing=False)
        return reason

    def start_controller_watch(self):
        with self._gate:
            if self._watch_thread is not None:
                raise NativeRegistryError('CONTROLLER_WATCH_ALREADY_STARTED')
            if self._watch_stop.is_set():
                raise NativeRegistryError('CONTROLLER_WATCH_ALREADY_CLOSED')

            def watch():
                while not self._watch_stop.wait(0.05):
                    self.sweep_controller()

            self._watch_thread = Thread(
                target=watch, name='walle-original-controller-watch', daemon=False
            )
            self._watch_thread.start()

    def close_watch(self):
        """Caller may stop monitoring only after each original scope is closed."""
        with self._gate:
            self._admission_closed = True
            entries = tuple(self._entries.values())
            preparations = tuple(self._preparations.values())
        for preparation in preparations:
            if not preparation.handles_released:
                preparation.verify_no_activity()
        for entry in entries:
            if entry.preparation is not None and entry.preparation.handles_released:
                continue
            with entry.gate:
                fence = self._journal.inspect(entry.scope)
                if fence is None or not fence.stop_closed:
                    raise NativeRegistryError('ACTIVE_CONTROLLER_WATCH_REQUIRED')
                members = entry.job.observe_members()
                if not members.complete or members.process_ids or members.assigned_count:
                    raise LaunchOutcomeUnknown('ACTIVE_CONTROLLER_WATCH_REQUIRED')
                if entry.root is None and fence.create_state != 'NONE':
                    raise LaunchOutcomeUnknown('ORIGINAL_NATIVE_CREATE_UNVERIFIED')
                if (
                    entry.root is not None
                    and not entry.released
                    and entry.root.observe().state != 'EXITED'
                ):
                    raise LaunchOutcomeUnknown('ACTIVE_CONTROLLER_WATCH_REQUIRED')
        self._sweep_task_stops(closing=True)
        self._watch_stop.set()
        thread = self._watch_thread
        if thread is not None and thread.ident is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise LaunchOutcomeUnknown('CONTROLLER_WATCH_STILL_ACTIVE')
        if self._watch_source is not None:
            self._watch_source.close()
            self._watch_source = None
        # Only this watch's read-only process duplicate is released. Original
        # token, Job/IO/pin/directory and execution handles remain caller-owned.
