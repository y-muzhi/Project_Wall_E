"""Serial execution owner for the durable repository registration and observation queue."""

from dataclasses import dataclass
from threading import get_ident

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_control_git_transport import _endpoint
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from backend.app.infrastructure.windows_guard_pipe import GuardPipeClient
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard

from .configuration_identities import require_schema
from .repository_baseline_validation import can_observe_baseline_pin, original_baseline
from .repository_git_recovery import RepositoryRestartRecovery
from .repository_git_runner import (
    RegistrationReadLimits,
    RepositoryBaselinePinRun,
    RepositoryBaselineQueryRun,
    RepositoryBaselineRecoveryRun,
    RepositoryBaselineValidationRun,
    RepositoryBaselineVerifyRun,
    RepositoryObservationRun,
    RepositoryRegistrationRun,
)
from .repository_observation_publish import _original as _original_observation
from .repository_registration import _original
from .workspace_materialization import FixedWorkspaceStage, WorkspaceMaterializationError


@dataclass(frozen=True)
class RegistrationOutcome:
    operation_id: int
    repository_id: int


@dataclass(frozen=True)
class ObservationOutcome:
    operation_id: int
    observation_id: int


@dataclass(frozen=True)
class BaselineOutcome:
    operation_id: int
    snapshot_id: int


_BASELINE_RUNNERS = (
    RepositoryBaselineValidationRun,
    RepositoryBaselinePinRun,
    RepositoryBaselineVerifyRun,
)


class RepositoryRegistrationActor:
    """Own at most one original run on the thread owning its native resources."""

    def __init__(self, runtime, binding, journal, *, private_roots, limits):
        if type(binding) is not GuardControllerBinding or type(journal) is not LaunchJournal:
            raise TypeError('Original registration actor binding and journal required')
        if type(limits) is not RegistrationReadLimits:
            raise TypeError('Explicit registration actor limits required')
        require_schema(runtime)
        binding.assert_backend(runtime.commands().process_lock)
        journal._verify()
        self._thread = get_ident()
        self._runtime = runtime
        self._binding = binding
        self._journal = journal
        self._private_roots = private_roots
        self._limits = limits
        self._active = None
        self._restart = RepositoryRestartRecovery(runtime, binding, journal)
        self._closed = False

    def _check_thread(self):
        if get_ident() != self._thread:
            raise LaunchOutcomeUnknown('ORIGINAL_REGISTRATION_ACTOR_THREAD_DIFFERS')

    def _require_current(self):
        self._check_thread()
        if self._closed:
            raise LaunchOutcomeUnknown('ORIGINAL_REGISTRATION_ACTOR_CLOSED')
        self._binding.assert_backend(self._runtime.commands().process_lock)

    def _next_operation(self):
        with self._runtime.database.transaction() as connection:
            row = connection.execute(
                "SELECT id,operation_type FROM code_operations WHERE resource_kind='REPOSITORY' "
                "AND operation_type IN ('REGISTER_REPOSITORY','REFRESH_REPOSITORY','REGISTER_BASE') "
                "AND (status='PENDING' OR (operation_type='REGISTER_BASE' AND status='RUNNING' "
                'AND NOT EXISTS (SELECT 1 FROM code_operation_steps s WHERE s.operation_id=code_operations.id '
                "AND s.status='RUNNING') "
                'AND EXISTS (SELECT 1 FROM code_operation_steps s WHERE s.operation_id=code_operations.id '
                "AND s.status='PENDING'))) "
                'ORDER BY id LIMIT 1'
            ).fetchone()
            if row is None:
                return None
            if row['operation_type'] == 'REGISTER_BASE':
                return self._next_baseline(connection, row['id'])
            if row['operation_type'] == 'REGISTER_REPOSITORY':
                operation, _, steps = _original(connection, row['id'])
            else:
                operation, steps = _original_observation(connection, row['id'])
            if operation['started_at'] is not None or any(
                step['status'] != 'PENDING'
                or step['external_identity'] is not None
                or step['result_ref'] is not None
                or step['started_at'] is not None
                for step in steps
            ):
                raise StorageUnavailable(
                    'Original pending repository operation has execution history'
                )
            runner = (
                RepositoryRegistrationRun
                if row['operation_type'] == 'REGISTER_REPOSITORY'
                else RepositoryObservationRun
            )
            return operation['id'], runner

    @staticmethod
    def _next_baseline(connection, operation_id):
        operation, _, steps = original_baseline(connection, operation_id)
        for index, runner in enumerate(_BASELINE_RUNNERS):
            step = steps[index]
            if step['status'] == 'SUCCEEDED':
                if step['external_identity'] is None or step['result_ref'] is None:
                    break
                continue
            expected = 'PENDING' if index == 0 else 'RUNNING'
            if operation['status'] == expected and all(
                later['status'] == 'PENDING'
                and all(
                    later[key] is None
                    for key in (
                        'external_identity',
                        'result_ref',
                        'started_at',
                        'ended_at',
                        'last_observed_at',
                    )
                )
                for later in steps[index:]
            ):
                return operation_id, runner
            break
        raise StorageUnavailable('Original baseline queue checkpoint differs')

    @property
    def cleanup_required(self):
        self._check_thread()
        return self._active is not None

    def has_work(self):
        self._require_current()
        return (
            self.cleanup_required
            or self._restart_requires_connection()
            or bool(self._restart.observations)
            or self._next_operation() is not None
        )

    def _restart_requires_connection(self):
        try:
            return self._restart.requires_connection()
        except (OSError, RuntimeError) as error:
            if getattr(error, 'retained_owner', None) is not None:
                error.retained_owner = self
            raise

    def run_next(self, frames, *, cancelled):
        self._require_current()
        if self._active is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_REGISTRATION_ACTOR_RECONCILIATION_REQUIRED')
        if not callable(cancelled):
            raise TypeError('Explicit registration cancellation required')
        if cancelled():
            return None
        if self._restart_requires_connection():
            try:
                self._restart.reconcile(
                    frames, timeout_ms=self._limits.max_git_seconds * 1000, cancelled=cancelled
                )
            except (OSError, RuntimeError) as error:
                if getattr(error, 'retained_owner', None) is not None:
                    error.retained_owner = self
                raise
            return None
        observe = bool(self._restart.observations)
        next_operation = (
            (self._restart.observations[0], RepositoryBaselineRecoveryRun)
            if observe
            else self._next_operation()
        )
        if next_operation is None:
            return None
        operation_id, runner_type = next_operation
        _endpoint(frames, GuardPipeClient, self._binding.installation_ref)
        if cancelled():
            return None
        if observe:
            self._restart.observations.popleft()
        if runner_type in _BASELINE_RUNNERS:
            for stage in _BASELINE_RUNNERS[_BASELINE_RUNNERS.index(runner_type) :]:
                if cancelled():
                    return None
                result_id = self._run(operation_id, stage, frames, cancelled=cancelled)
            return BaselineOutcome(operation_id, result_id)
        result_id = self._run(operation_id, runner_type, frames, cancelled=cancelled)
        if runner_type is RepositoryRegistrationRun:
            return RegistrationOutcome(operation_id, result_id)
        if runner_type is RepositoryObservationRun:
            return ObservationOutcome(operation_id, result_id)
        return BaselineOutcome(operation_id, result_id)

    def snapshot_reads_ready(self):
        self._require_current()
        return not self.cleanup_required and not self._restart_requires_connection()

    def query_snapshot(self, snapshot_id, frames, *, cancelled, finish=None, consume_file=None):
        self._require_current()
        if not self.snapshot_reads_ready():
            raise LaunchOutcomeUnknown(
                'Original repository cleanup must finish before snapshot reads'
            )
        _endpoint(frames, GuardPipeClient, self._binding.installation_ref)
        return self._run(
            snapshot_id,
            RepositoryBaselineQueryRun,
            frames,
            cancelled=cancelled,
            finish=finish,
            consume_file=consume_file,
        )

    def restore_snapshot(
        self, snapshot_id, frames, *, parent, nonce, check_active, cancelled, record_stage=None
    ):
        """Internal fixed-content restore for a caller-owned original allocation."""
        self._require_current()
        if self.cleanup_required or self._restart_requires_connection():
            raise LaunchOutcomeUnknown('Original repository cleanup must finish before restore')
        _endpoint(frames, GuardPipeClient, self._binding.installation_ref)
        if type(parent) is not PrivatePackageGuard or not all(
            callable(check) for check in (check_active, cancelled)
        ):
            raise WorkspaceMaterializationError('ORIGINAL_WORKSPACE_ALLOCATION_REQUIRED')
        if cancelled():
            raise LaunchOutcomeUnknown('ORIGINAL_BASELINE_CANCELLED')

        def new_stage(check_source_active, query_id):
            def check_restore():
                check_source_active()
                return check_active()

            def record_identity(identity):
                if record_stage is not None:
                    record_stage(identity, query_id)

            return FixedWorkspaceStage(parent, nonce, check_restore, record_stage=record_identity)

        return self._run(
            snapshot_id,
            RepositoryBaselineQueryRun,
            frames,
            cancelled=cancelled,
            new_stage=new_stage,
            restore_parent=parent,
        )

    def _run(self, operation_id, runner_type, frames, *, cancelled, **options):
        runner = runner_type(
            self._runtime,
            operation_id,
            frames,
            self._binding,
            self._journal,
            private_roots=self._private_roots,
            limits=self._limits,
            **options,
        )
        self._active = runner
        try:
            result_id = runner.run(cancelled=cancelled)
        except BaseException as error:
            try:
                runner.close()
            except BaseException as cleanup:
                error.retained_owner = self
                raise error from cleanup
            self._active = None
            self._schedule_pin_observation(runner)
            if getattr(error, 'retained_owner', None) is runner:
                del error.retained_owner
            raise
        self._active = None
        return result_id

    def request_pin_observation(self, operation_id):
        self._require_current()
        if operation_id in self._restart.observations:
            return
        with self._runtime.database.transaction() as connection:
            operation, _, steps = original_baseline(connection, operation_id)
            if can_observe_baseline_pin(operation, steps):
                self._restart.observations.append(operation_id)

    def _schedule_pin_observation(self, runner):
        if type(runner) is RepositoryBaselinePinRun:
            self.request_pin_observation(runner._operation_id)

    def reconcile_cleanup(self, frames, *, timeout_ms, cancelled):
        self._require_current()
        if self._active is None:
            raise LaunchOutcomeUnknown('ORIGINAL_REGISTRATION_ACTOR_HAS_NO_ACTIVE_RUN')
        try:
            self._active.reconcile_cleanup(frames, timeout_ms=timeout_ms, cancelled=cancelled)
        except BaseException as error:
            error.retained_owner = self
            raise
        cleaned, self._active = self._active, None
        self._schedule_pin_observation(cleaned)

    def close(self):
        self._check_thread()
        if self._active is not None:
            try:
                self._active.close()
            except BaseException as error:
                error.retained_owner = self
                raise
            self._active = None
        try:
            self._restart.close()
        except BaseException as error:
            error.retained_owner = self
            raise
        self._closed = True
