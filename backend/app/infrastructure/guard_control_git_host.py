"""Own the first Guard endpoint, registered image and controller lifetimes."""

from threading import get_ident

from .guard_backend_program import open_registered_backend_image
from .guard_control_git_transport import GuardControlGitServer
from .guard_pipe_frames import GuardPipeFrames, _remaining
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_guard_pipe import GuardPipeServer
from .windows_guard_pipe_io import GuardPipeIO, PipeIOError, _deadline
from .windows_local_paths import local_absolute_path
from .windows_pipe_peer import discover_registered_pipe_client
from .windows_process import ObservedProcess
from .windows_task_directories import TaskRuntimeRoot


class GuardControlGitHost:
    """Own original authenticated sessions, including kernel-discovered backend peers."""

    def __init__(
        self,
        records,
        installation_ref,
        *,
        backend_sid,
        package_root,
        manifest_sha256,
        task_network=None,
        task_source_parent=None,
        task_runtime_root=None,
        task_runtime_bundle=None,
        task_program=None,
        project_checks=(),
    ):
        self._thread = get_ident()
        if task_runtime_root is not None and (
            type(task_runtime_root) is not TaskRuntimeRoot
            or task_runtime_root.backend_sid != backend_sid
        ):
            raise LaunchOutcomeUnknown('REGISTERED_TASK_RUNTIME_BACKEND_DIFFERS')
        self._server = GuardControlGitServer(
            records,
            installation_ref,
            package_root=package_root,
            manifest_sha256=manifest_sha256,
            task_network=task_network,
            task_source_parent=task_source_parent,
            task_runtime_root=task_runtime_root,
            task_runtime_bundle=task_runtime_bundle,
            task_program=task_program,
            project_checks=project_checks,
        )
        self._image = None
        self._endpoint = None
        self._backend = None
        self._io = None
        self._frames = None
        self._session = None
        self._orphans = []
        self._closed = False
        try:
            self._image = self._acquire(
                open_registered_backend_image, package_root, manifest_sha256=manifest_sha256
            )
            self._endpoint = self._acquire(
                GuardPipeServer, installation_ref, backend_sid=backend_sid
            )
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                raise cleanup from original
            raise

    @property
    def name(self):
        self._check()
        return self._endpoint.name

    def _check_thread(self):
        if get_ident() != self._thread:
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_HOST_THREAD_DIFFERS')

    def _check(self):
        self._check_thread()
        if self._closed or self._server._closed or self._server._retained or self._orphans:
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_HOST_UNAVAILABLE')

    def _acquire(self, factory, *args, **kwargs):
        try:
            return factory(*args, **kwargs)
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if retained is not None:
                self._orphans.append(retained)
                error.retained_owner = self
            raise

    def accept(self, backend, *, timeout_ms, cancelled):
        self._check()
        deadline = _deadline(timeout_ms)
        if self._session is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_SESSION_RETIREMENT_REQUIRED')
        if type(backend) is not ObservedProcess:
            raise TypeError('Trusted original backend process owner required')
        if not callable(cancelled):
            raise TypeError('Explicit Guard host cancellation required')
        original = backend.observe()
        identity = original.identity
        if (
            original.state != 'RUNNING'
            or identity.user_sid != self._endpoint.backend_sid
            or identity.is_elevated
            or identity.is_appcontainer
            or identity.appcontainer_sid is not None
            or identity.is_lpac is not False
            or str(local_absolute_path(identity.image_path)).casefold()
            != str(self._image.path).casefold()
        ):
            raise LaunchOutcomeUnknown('REGISTERED_GUARD_BACKEND_DIFFERS')
        self._image.verify()
        if cancelled():
            self._session = 'ABORTED'
            raise LaunchOutcomeUnknown('GUARD_HOST_ACCEPT_CANCELLED')
        remaining = _remaining(deadline)
        self._session = 'ACCEPTING'
        try:
            self._backend = self._acquire(backend.duplicate)
            self._connect_session(timeout_ms=remaining, cancelled=cancelled)
            self._admit_session()
        except PipeIOError as error:
            self._record_accept_failure(error)
            error.retained_owner = self
            raise
        except BaseException as error:
            self._retain_accept_failure(error)
            raise

    def _connect_session(self, *, timeout_ms, cancelled):
        self._io = self._acquire(GuardPipeIO, self._endpoint)
        self._io.connect(timeout_ms=timeout_ms, cancelled=cancelled)
        self._session = 'UNADMITTED'

    def _admit_session(self):
        self._frames = GuardPipeFrames(self._io)
        self._session = 'CONNECTED'

    def accept_registered(self, *, timeout_ms, cancelled):
        """Discover the kernel-connected backend before admitting any protocol frame."""
        self._check()
        if self._session is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_SESSION_RETIREMENT_REQUIRED')
        if not callable(cancelled):
            raise TypeError('Explicit Guard host cancellation required')
        deadline = _deadline(timeout_ms)
        self._image.verify()
        if cancelled():
            self._session = 'ABORTED'
            raise LaunchOutcomeUnknown('GUARD_HOST_ACCEPT_CANCELLED')
        self._session = 'ACCEPTING'
        try:
            self._connect_session(timeout_ms=_remaining(deadline), cancelled=cancelled)
            with (
                self._endpoint.endpoint() as handle,
                discover_registered_pipe_client(
                    handle,
                    program=self._image,
                    expected_user_sid=self._endpoint.backend_sid,
                ) as backend,
            ):
                if cancelled():
                    raise LaunchOutcomeUnknown('GUARD_HOST_ACCEPT_CANCELLED')
                self._backend = self._acquire(backend.duplicate)
            self._admit_session()
        except PipeIOError as error:
            self._record_accept_failure(error)
            self._retain_accept_failure(error)
            raise
        except BaseException as error:
            self._retain_accept_failure(error)
            raise

    def _retain_accept_failure(self, error):
        retained = getattr(error, 'retained_owner', None)
        if (
            retained is not None
            and retained is not self
            and all(owner is not retained for owner in self._orphans)
        ):
            self._orphans.append(retained)
        error.retained_owner = self

    def _record_accept_failure(self, error):
        if self._io is None or self._io._pending is not None:
            return
        if error.code == 'PIPE_IO_CANCELLED_BEFORE_DISPATCH' or (
            error.native_error == 995
            and error.code in ('PIPE_IO_CANCELLED_OR_TIMED_OUT', 'PIPE_IO_FAILED')
        ):
            self._session = 'ABORTED'
        elif (error.code == 'PIPE_IO_CANCELLED_OR_TIMED_OUT' and error.transferred == 0) or (
            error.code in ('PIPE_IO_DISPATCH_FAILED', 'PIPE_IO_FAILED')
            and error.native_error in (109, 232)
        ):
            # The pipe may have connected, but this attempt never owns a frame parser.
            self._session = 'CONNECTED'

    def serve(self, *, timeout_ms, cancelled):
        self._check()
        if self._session != 'CONNECTED' or self._frames is None:
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_SESSION_REQUIRED')
        if self._backend.observe().state != 'RUNNING':
            self._frames.invalidate()
            self._session = 'FAILED'
            raise LaunchOutcomeUnknown('REGISTERED_GUARD_BACKEND_EXITED')
        try:
            self._server.serve(
                self._frames,
                expected_backend=self._backend.identity,
                backend_image=self._image,
                timeout_ms=timeout_ms,
                cancelled=cancelled,
            )
        except BaseException:
            if self._frames._failed:
                self._session = 'FAILED'
            raise

    def _close_io(self):
        if self._frames is not None:
            self._frames.close()
            self._frames = None
            self._io = None
        elif self._io is not None:
            self._io.close()
            self._io = None

    def _close_backend(self):
        if self._backend is not None:
            self._backend.close()
            self._backend = None

    def retire_session(self):
        """Keep the first endpoint for the next independently registered session."""
        self._check()
        if self._session not in ('ABORTED', 'UNADMITTED', 'CONNECTED', 'DISCONNECTED'):
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_SESSION_NOT_REUSABLE')
        try:
            unadmitted = self._session == 'UNADMITTED'
            if unadmitted and self._frames is not None:
                raise LaunchOutcomeUnknown('ORIGINAL_GUARD_UNADMITTED_FRAME_DIFFERS')
            self._close_io()
            if unadmitted:
                self._endpoint._disconnect_unusable_connection()
            if self._session == 'CONNECTED':
                self._endpoint.disconnect_closed_peer()
                self._session = 'DISCONNECTED'
            self._close_backend()
            self._session = None
        except BaseException as error:
            error.retained_owner = self
            raise

    def retire_failed_session(self):
        """Discard only this poisoned stream; durable requests/owners stay unchanged."""
        self._check_thread()
        if (
            self._closed
            or self._server._closed
            or self._orphans
            or self._session != 'FAILED'
            or self._frames is None
            or not self._frames._failed
            or self._io is None
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_FAILED_STREAM_REQUIRED')
        io = self._io
        if any(owner is not io for owner in self._server._retained):
            raise LaunchOutcomeUnknown('ORIGINAL_GUARD_RESOURCE_OWNER_UNVERIFIED')
        try:
            self._close_io()
            if not io._closed or io._pending is not None:
                raise LaunchOutcomeUnknown('ORIGINAL_GUARD_IO_CLOSURE_UNVERIFIED')
            self._server._retained = [owner for owner in self._server._retained if owner is not io]
            self._endpoint._disconnect_unusable_connection()
            self._close_backend()
            self._session = None
        except BaseException as error:
            self._retain_accept_failure(error)
            raise

    def stop_owned(self, *, timeout_ms):
        self._check_thread()
        if self._closed:
            return
        try:
            self._server.stop_owned(timeout_ms=timeout_ms)
        except BaseException as error:
            self._retain_accept_failure(error)
            raise

    def close(self):
        self._check_thread()
        if self._closed:
            return
        try:
            self._server.close()
            self._close_io()
            self._close_backend()
            for orphan in tuple(self._orphans):
                orphan.close()
                self._orphans.remove(orphan)
            if self._endpoint is not None:
                self._endpoint.close()
                self._endpoint = None
            if self._image is not None:
                self._image.close()
                self._image = None
            self._closed = True
        except BaseException as error:
            error.retained_owner = self
            raise
