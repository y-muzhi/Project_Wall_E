"""Guard-owned controller lifetime independent of any one pipe connection.

This is an internal CONTROL_GIT owner, not a server, scheduler or installation.
One actor thread retains original token/process/registry owners. Pipe reconnects
must authenticate again; they never replace the old controller identity.
"""

from contextlib import contextmanager
from threading import get_ident

from .guard_backend_program import ProtectedBackendProgram
from .guard_controller_binding import GuardControllerBinding
from .guard_controller_records import GuardControllerRecords
from .runtime_control_git import ControlGitRegistry
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_controller_token import ControllerPrimaryToken


class GuardControllerOwnerError(LaunchOutcomeUnknown):
    pass


class GuardControllerOwner:
    def __init__(self, records, binding, *, peer, program, timeout_ms, cancelled):
        if (
            type(records) is not GuardControllerRecords
            or type(binding) is not GuardControllerBinding
            or type(program) is not ProtectedBackendProgram
            or program.peer is not peer
        ):
            raise GuardControllerOwnerError('ACTUAL_CONTROLLER_PROGRAM_AND_RECORDS_REQUIRED')
        self._owner_thread = get_ident()
        self._records, self._binding = records, binding
        self._registration = None
        self._source = None
        self._token = None
        self._registry = None
        self._orphans = []
        self._task_directories = {}
        self._task_source_parent = None
        self._task_profiles = {}
        self._initialized = False
        self._closing = False
        self._closed = False
        self._users = 0
        try:
            # No native execution owner is published before original admitted
            # program provenance is durably recorded and acknowledged.
            self._registration = records.register_admitted(
                binding,
                peer=peer,
                program=program,
                timeout_ms=timeout_ms,
                cancelled=cancelled,
            )
            if (
                self._registration.binding != binding
                or self._registration.backend_admission is None
            ):
                raise GuardControllerOwnerError('ORIGINAL_ADMITTED_CONTROLLER_RECORD_REQUIRED')
            binding.assert_peer(peer)
            with peer.original_process() as original:
                self._source = self._acquire(original.duplicate)
            if self._source.identity != binding.controller:
                raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_SOURCE_DIFFERS')
            self._token = self._acquire(
                ControllerPrimaryToken, self._source, expected=binding.controller
            )
            self._registry = self._acquire(
                ControlGitRegistry,
                records._journal,
                self._token,
                controller_ref=binding.controller_ref,
            )
            self._registry.start_controller_watch()
            self._initialized = True
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                cleanup.retained_owner = self
                raise cleanup from original
            retained = getattr(original, 'retained_owner', None)
            if retained is not None:
                original.retained_owner = self
            raise

    def _check_thread(self):
        if get_ident() != self._owner_thread:
            raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_ACTOR_THREAD_DIFFERS')

    def _acquire(self, factory, *args, **kwargs):
        try:
            return factory(*args, **kwargs)
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if retained is not None:
                self._orphans.append(retained)
                error.retained_owner = self
            raise

    @property
    def binding(self):
        return self._binding

    @property
    def registration(self):
        return self._registration

    @property
    def registry(self):
        # Native recovery still needs the original object even after current
        # admission is closed. The narrow recovery permission gate is separate.
        self._check_thread()
        if self._registry is None:
            raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_REGISTRY_UNAVAILABLE')
        return self._registry

    @contextmanager
    def current_registry(self, binding, *, peer, program, timeout_ms, cancelled):
        self._check_thread()
        if self._closing or self._closed or not self._initialized:
            raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_ADMISSION_CLOSED')
        if (
            binding != self._binding
            or type(program) is not ProtectedBackendProgram
            or program.peer is not peer
        ):
            raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_RECONNECT_DIFFERS')
        binding.assert_peer(peer)
        with program.admission(timeout_ms=timeout_ms, cancelled=cancelled) as admission:
            actual = self._records.read(binding.controller_ref, binding.owner_epoch)
            if (
                actual != self._registration
                or actual.backend_admission != admission
                or peer._program.verify() != actual.image
            ):
                raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_PROGRAM_RECORD_DIFFERS')
            with self._token.creation_handle():
                self._users += 1
                try:
                    yield self._registry
                finally:
                    self._users -= 1

    def stop_owned_for_shutdown(self, *, deadline):
        """Security shutdown closes original authority, never a business TERMINATE."""
        self._check_thread()
        if self._users:
            raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_ACTION_STILL_ACTIVE')
        if self._registry is None:
            return
        failure = None
        with self._registry.pause_task_watch_for_close():
            try:
                self._records.seal_controller(
                    self._binding.controller_ref, self._binding.owner_epoch
                )
            except (RuntimeError, OSError) as error:
                failure = error
            try:
                self._registry.stop_owned_for_shutdown(deadline=deadline)
            except (RuntimeError, OSError) as error:
                failure = failure or error
        if failure is not None:
            error = GuardControllerOwnerError('ORIGINAL_GUARD_SHUTDOWN_UNVERIFIED')
            error.retained_owner = self
            raise error from failure

    def close(self):
        self._check_thread()
        if self._users:
            raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_ACTION_STILL_ACTIVE')
        if self._closed:
            return
        self._closing = True
        try:
            if self._registry is not None:
                with self._registry.pause_task_watch_for_close():
                    if self._initialized:
                        self._records.seal_controller(
                            self._binding.controller_ref, self._binding.owner_epoch
                        )
                    elif self._registry._entries:
                        raise GuardControllerOwnerError(
                            'UNPUBLISHED_CONTROLLER_RESOURCE_UNVERIFIED'
                        )
                    # This verifies original nonce closure, Job emptiness and root
                    # exit before stopping the watch. It does not release external
                    # Job/IO/config/pin owners or claim complete RELEASE.
                    self._registry.close_watch()
            for key, directories in tuple(self._task_directories.items()):
                directories.close()
                del self._task_directories[key]
            for key, execution in tuple(self._task_profiles.items()):
                # Persistent profile records survive controller shutdown for reconciliation.
                execution.close_job()
                del self._task_profiles[key]
            if self._token is not None:
                self._token.close()
                self._token = None
            if self._source is not None:
                self._source.close()
                self._source = None
            for orphan in tuple(self._orphans):
                orphan.close()
                self._orphans.remove(orphan)
            self._closed = True
        except BaseException as error:
            error.retained_owner = self
            raise

    def __enter__(self):
        self._check_thread()
        if self._closing or not self._initialized:
            raise GuardControllerOwnerError('ORIGINAL_CONTROLLER_ADMISSION_CLOSED')
        return self

    def __exit__(self, kind, error, traceback):
        self.close()
