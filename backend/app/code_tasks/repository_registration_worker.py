"""Dedicated backend thread for the original durable repository registration queue."""

import sqlite3
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock
from time import monotonic

from backend.app.infrastructure.check_case_pack import RegisteredCasePack
from backend.app.infrastructure.git_local_config import GitConfigError
from backend.app.infrastructure.git_ref_metadata import RefMetadataError
from backend.app.infrastructure.git_ref_protocol import RefProtocolError
from backend.app.infrastructure.guard_controller_binding import (
    GuardBindingError,
    bind_backend_controller,
)
from backend.app.infrastructure.guard_pipe_frames import GuardPipeFrames
from backend.app.infrastructure.opencode_binary import OpenCodeBinarySource
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_guard_pipe import pipe_name
from backend.app.infrastructure.windows_guard_pipe_io import GuardPipeIO
from backend.app.infrastructure.windows_guard_service import connect_registered_guard
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.shared.validation import strict_integer
from backend.app.testing.cli_plan import (
    TestingBrowserAdmission,
    TestingCliAdmission,
    TestingCliRuntime,
)
from backend.app.testing.run_worker import TestingCliWorker

from .coding_model_gateway import CodingModelDeployment, CodingModelGateway
from .coding_model_ledger import recover_interrupted_calls
from .coding_model_listener import CodingModelListener
from .coding_project_check_scope import CodingProjectCheckAdmission
from .configuration_identities import require_schema
from .repository_git_runner import BASELINE_INPUT_ERRORS, RegistrationReadLimits
from .repository_registration_actor import RepositoryRegistrationActor
from .task_candidate_worker import CandidateCaptureWorker
from .task_delivery_finalize import (
    advance_delivery_finalization_resume,
    advance_owned_delivery_finalization,
)
from .task_delivery_window import advance_delivery_window_resume
from .task_instance_driver import TaskInstanceDriver, TaskLaunchInstallation
from .task_live_configuration import advance_live_configuration
from .task_native_issues import advance_native_issue_observation
from .task_permission_response import advance_permission_responses
from .task_project_check_worker import CodingProjectCheckWorker
from .task_question_response import advance_question_responses
from .task_repair_runtime import advance_repairs
from .task_resume_runtime import advance_model_resumes
from .task_role_handoff import advance_role_handoff
from .task_role_reconciliation import (
    advance_role_reconciliation,
    finish_delivery_reconciliation,
    next_delivery_reconciliation,
)
from .task_runtime_stop import advance_owned_stops
from .task_start_basis import advance_start_basis
from .task_start_conditions import advance_start_conditions
from .task_start_instance import advance_start_instance
from .task_start_session import advance_start_session
from .task_start_workspace import advance_workspace_start, workspace_start_pending

QUEUE_RECHECK_SECONDS = 1
SHUTDOWN_CLEANUP_MS = 5000
MAX_OBSERVATION_HINTS = 256
MAX_SNAPSHOT_QUERIES = 8


class SnapshotQueryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class _SnapshotQuery:
    snapshot_id: int
    deadline: float
    cancelled: Event
    result: Future
    finish: object
    consume_file: object


@dataclass(frozen=True)
class RegistrationInstallation:
    """Private startup inputs from the trusted installation, never HTTP fields."""

    installation_ref: str
    backend_sid: str = field(repr=False)
    guard_image: Path = field(repr=False)
    guard_image_bytes: int
    guard_image_sha256: str
    journal_root: Path = field(repr=False)
    private_roots: tuple[Path, ...] = field(repr=False)
    limits: RegistrationReadLimits
    workspace_root: Path | None = field(default=None, repr=False)
    executor_binary: OpenCodeBinarySource | None = field(default=None, repr=False)
    task_launch: TaskLaunchInstallation | None = field(default=None, repr=False)
    coding_models: CodingModelDeployment | None = field(default=None, repr=False)
    project_checks: tuple[CodingProjectCheckAdmission, ...] = field(default=(), repr=False)
    case_packs: tuple[RegisteredCasePack, ...] = field(default=(), repr=False)
    testing_cli: tuple[TestingCliAdmission, ...] = field(default=(), repr=False)
    testing_browser: tuple[TestingBrowserAdmission, ...] = field(default=(), repr=False)
    delivery_runtime_admitted: bool = False

    def __post_init__(self):
        pipe_name(self.installation_ref)
        if type(self.delivery_runtime_admitted) is not bool or (
            self.delivery_runtime_admitted and (self.task_launch is None or not self.project_checks)
        ):
            raise TypeError('Trusted delivery runtime and Coding check installation required')
        if type(self.private_roots) is not tuple or type(self.limits) is not RegistrationReadLimits:
            raise TypeError('Original registration installation roots and limits required')
        if (
            self.executor_binary is not None
            and type(self.executor_binary) is not OpenCodeBinarySource
        ):
            raise TypeError('Trusted OpenCode binary installation required')
        if self.task_launch is not None and (
            type(self.task_launch) is not TaskLaunchInstallation
            or self.workspace_root is None
            or self.executor_binary is None
            or not self.executor_binary.matches(self.task_launch.plan.executor)
        ):
            raise TypeError('Trusted original TASK launch installation required')
        if (
            type(self.project_checks) is not tuple
            or len(self.project_checks) > 32
            or any(type(item) is not CodingProjectCheckAdmission for item in self.project_checks)
            or self.project_checks
            and self.task_launch is None
        ):
            raise TypeError('Trusted Coding project check installation required')
        if (
            type(self.testing_cli) is not tuple
            or len(self.testing_cli) > 32
            or any(type(item) is not TestingCliAdmission for item in self.testing_cli)
            or type(self.testing_browser) is not tuple
            or len(self.testing_browser) > 32
            or any(type(item) is not TestingBrowserAdmission for item in self.testing_browser)
            or (self.testing_cli or self.testing_browser)
            and self.workspace_root is None
        ):
            raise TypeError('Trusted independent Testing installation required')
        if (
            type(self.case_packs) is not tuple
            or len(self.case_packs) > 256
            or any(type(item) is not RegisteredCasePack for item in self.case_packs)
            or len({(item.case_pack_ref, item.manifest_sha256) for item in self.case_packs})
            != len(self.case_packs)
        ):
            raise TypeError('Trusted original CasePack installations required')
        if self.coding_models is not None and (
            type(self.coding_models) is not CodingModelDeployment
            or self.task_launch is None
            or self.task_launch.coding is None
        ):
            raise TypeError('Trusted original Coding model installation required')


@contextmanager
def _frames(installation, program):
    with (
        connect_registered_guard(
            installation.installation_ref, backend_sid=installation.backend_sid, program=program
        ) as endpoint,
        GuardPipeIO(endpoint) as io,
        GuardPipeFrames(io) as frames,
    ):
        yield frames


class RepositoryRegistrationWorker:
    """All native owners live on this worker thread under the backend ProcessLock."""

    def __init__(self, runtime, installation):
        if type(installation) is not RegistrationInstallation:
            raise TypeError('Trusted registration installation inputs required')
        self._runtime = runtime
        self._installation = installation
        self._initialized = Event()
        self._stop = Event()
        self._wake = Event()
        self._observation_lock = Lock()
        self._observation_hints = {}
        self._snapshot_lock = Lock()
        self._snapshot_queries = Queue(MAX_SNAPSHOT_QUERIES)
        self._retained = None
        self._testing_binding = None
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix='walle-repository-registration'
        )
        self._task = None

    def start(self):
        if self._task is not None:
            raise RuntimeError('Registration worker already started')
        self._task = self._executor.submit(self._run)
        self._task.add_done_callback(lambda _: self._initialized.set())
        self._initialized.wait()
        if self._task.done():
            self._task.result()

    @property
    def accepting(self):
        return (
            self._initialized.is_set()
            and self._task is not None
            and not self._task.done()
            and not self._stop.is_set()
        )

    @property
    def accepts_workspace_starts(self):
        return self.accepting and self._installation.workspace_root is not None

    @property
    def accepts_model_resumes(self):
        return (
            self.accepts_workspace_starts
            and self._installation.task_launch is not None
            and self._installation.coding_models is not None
        )

    @property
    def accepts_live_configuration(self):
        return self.accepts_native_responses

    @property
    def accepts_native_permission_updates(self):
        return self.accepts_native_responses

    @property
    def accepts_native_responses(self):
        installation = self._installation.task_launch
        return (
            self.accepts_workspace_starts
            and installation is not None
            and installation.coding is not None
        )

    @property
    def accepts_candidate_capture(self):
        return self.accepts_native_responses and bool(self._installation.project_checks)

    @property
    def delivery_epoch(self):
        return (
            self._testing_binding.owner_epoch if self.accepting and self._testing_binding else None
        )

    @property
    def accepts_delivery_previews(self):
        return self.accepts_workspace_starts and self.delivery_epoch is not None

    @property
    def delivery_writes_ready(self):
        return self.accepts_delivery_previews and self._installation.delivery_runtime_admitted

    @property
    def delivery_finalization_ready(self):
        return self.delivery_writes_ready and self._installation.task_launch is not None

    def observe_delivery_plan(self, task_id, plan_id):
        from .task_delivery_plan_runtime import observe_saved_delivery_target

        epoch = self.delivery_epoch
        if epoch is None:
            return None
        return observe_saved_delivery_target(
            self._runtime,
            task_id,
            plan_id,
            epoch,
            self._installation.private_roots,
            self._installation.limits,
        )

    @property
    def project_check_admissions(self):
        return self._installation.project_checks if self.accepting else ()

    @property
    def testing_cli_resources(self):
        installation = self._installation
        if (
            self.accepting
            and self._testing_binding is not None
            and (installation.testing_cli or installation.testing_browser)
        ):
            return TestingCliRuntime(
                self._testing_binding,
                installation.testing_cli,
                snapshots=True,
                browser_admissions=installation.testing_browser,
            )
        return None

    @property
    def case_pack_admissions(self):
        return self._installation.case_packs

    def wake(self):
        """An acceleration after commit; the SQLite queue remains authoritative."""
        self._wake.set()

    def hint_pin_observation(self, operation_id):
        """Request a bounded recheck of an already accepted operation."""
        with self._observation_lock:
            if len(self._observation_hints) < MAX_OBSERVATION_HINTS:
                self._observation_hints[operation_id] = None

    def _forward_observation_hint(self, actor):
        with self._observation_lock:
            operation_id = next(iter(self._observation_hints), None)
        if operation_id is None:
            return False
        actor.request_pin_observation(operation_id)
        with self._observation_lock:
            self._observation_hints.pop(operation_id)
        return True

    def read_snapshot(self, snapshot_id, *, cancelled, finish=None, consume_file=None):
        strict_integer(snapshot_id, 'snapshot_id')
        if any(
            callback is not None and not callable(callback) for callback in (finish, consume_file)
        ):
            raise TypeError('Expected trusted snapshot callbacks')
        if type(cancelled) is not Event or cancelled.is_set():
            raise SnapshotQueryUnavailable('Snapshot read was cancelled')
        timeout = self._installation.limits.max_git_seconds + QUEUE_RECHECK_SECONDS
        job = _SnapshotQuery(
            snapshot_id, monotonic() + timeout, cancelled, Future(), finish, consume_file
        )
        with self._snapshot_lock:
            if not self.accepting:
                raise SnapshotQueryUnavailable('Snapshot read worker is unavailable')
            try:
                self._snapshot_queries.put_nowait(job)
            except Full as error:
                raise SnapshotQueryUnavailable('Snapshot read queue is full') from error
        self.wake()
        try:
            return job.result.result(timeout=timeout)
        except TimeoutError as error:
            job.cancelled.set()
            job.result.cancel()
            raise SnapshotQueryUnavailable('Snapshot read deadline exceeded') from error

    def close(self):
        with self._snapshot_lock:
            self._stop.set()
        self.wake()
        try:
            if self._task is not None:
                self._task.result()
        finally:
            self._executor.shutdown()
            while True:
                try:
                    job = self._snapshot_queries.get_nowait()
                except Empty:
                    break
                if job.result.set_running_or_notify_cancel():
                    job.result.set_exception(
                        SnapshotQueryUnavailable('Snapshot read worker closed')
                    )

    def _run(self):
        installation = self._installation
        resources = ExitStack()
        actor = driver = capture = checks = testing = None
        try:
            require_schema(self._runtime)
            binding = bind_backend_controller(
                self._runtime.commands().process_lock, installation.installation_ref
            )
            if binding.controller.user_sid != installation.backend_sid:
                raise GuardBindingError('REGISTRATION_INSTALLATION_BACKEND_SID_DIFFERS')
            program = resources.enter_context(
                ExecutablePin(
                    installation.guard_image,
                    expected_byte_count=installation.guard_image_bytes,
                    expected_sha256=installation.guard_image_sha256,
                )
            )
            journal = resources.enter_context(LaunchJournal(installation.journal_root))
            actor = RepositoryRegistrationActor(
                self._runtime,
                binding,
                journal,
                private_roots=(journal.root, *installation.private_roots),
                limits=installation.limits,
            )
            workspace_parent = None
            if installation.workspace_root is not None:
                workspace_parent = resources.enter_context(
                    PrivatePackageGuard(installation.workspace_root)
                )
            model_listener = None
            if installation.coding_models is not None:
                with self._runtime.database.transaction(write=True) as connection:
                    recover_interrupted_calls(connection)
                model_gateway = CodingModelGateway(self._runtime, installation.coding_models)
                model_listener = resources.enter_context(
                    CodingModelListener(
                        installation.task_launch.plan.network['model'][0],
                        model_gateway,
                    )
                )
            if installation.task_launch is not None:
                driver = TaskInstanceDriver(
                    installation.task_launch,
                    workspace_parent,
                    binding,
                    self._runtime.commands().process_lock,
                    lambda: _frames(installation, program),
                    model_listener=model_listener,
                    database=self._runtime.database,
                )
            if driver is not None:
                capture = CandidateCaptureWorker(
                    self._runtime,
                    driver,
                    workspace_parent,
                    binding,
                    journal,
                    lambda: _frames(installation, program),
                    cancelled=self._stop.is_set,
                    cleanup_timeout_ms=SHUTDOWN_CLEANUP_MS,
                )
            if workspace_parent is not None:
                checks = CodingProjectCheckWorker(
                    self._runtime,
                    workspace_parent,
                    binding,
                    journal,
                    lambda: _frames(installation, program),
                    installation.project_checks,
                    cancelled=self._stop.is_set,
                )
                testing = TestingCliWorker(
                    self._runtime,
                    workspace_parent,
                    binding,
                    journal,
                    lambda: _frames(installation, program),
                    installation.testing_cli,
                    browser_admissions=installation.testing_browser,
                    cancelled=self._stop.is_set,
                    query_snapshot=actor.query_snapshot,
                    snapshot_reads_ready=actor.snapshot_reads_ready,
                )
                self._testing_binding = binding
            self._initialized.set()
            self._serve(actor, program, workspace_parent, driver, capture, checks, testing)
            if testing is not None:
                testing.reconcile(cancelled=lambda: False)
            if checks is not None:
                checks.reconcile(cancelled=lambda: False)
            if capture is not None:
                capture.reconcile_command(cancelled=lambda: False)
            if driver is not None:
                driver.close()
            if actor.cleanup_required:
                with _frames(installation, program) as frames:
                    actor.reconcile_cleanup(
                        frames, timeout_ms=SHUTDOWN_CLEANUP_MS, cancelled=lambda: False
                    )
            actor.close()
        finally:
            self._retained = (resources, actor, driver, capture, checks, testing)
            error = sys.exception()
            if (
                getattr(error, 'retained_owner', None) is None
                and (actor is None or not actor.cleanup_required)
                and (driver is None or not driver.has_owners)
                and (capture is None or not capture.has_retained_command)
                and (checks is None or not checks.has_retained_command)
                and (testing is None or not testing.has_retained_command)
            ):
                resources.close()
                self._retained = None

    def _serve(
        self,
        actor,
        program,
        workspace_parent=None,
        driver=None,
        capture=None,
        checks=None,
        testing=None,
    ):
        deployment = self._installation.coding_models
        admissions = (
            {}
            if deployment is None
            else {value.evidence_ref: value for value in deployment.admissions}
        )
        issue_due = 0.0
        issue_cursor = 0
        delivery_recheck = {}
        delivery_write_recheck = {}
        while not self._stop.is_set():
            self._wake.clear()
            try:
                if actor.cleanup_required:
                    self._advance(actor, program)
                    continue
                if workspace_parent is not None and self._advance_delivery_preview(
                    actor, program, workspace_parent, delivery_recheck, stopping=True
                ):
                    continue
                if self.delivery_writes_ready and advance_delivery_window_resume(
                    self._runtime, self.delivery_epoch
                ):
                    continue
                if self.delivery_writes_ready and self._advance_delivery_write(
                    actor, program, delivery_write_recheck
                ):
                    continue
                if driver is not None and advance_owned_stops(
                    self._runtime, driver, cancelled=self._stop.is_set
                ):
                    continue
                if (
                    self.delivery_finalization_ready
                    and driver is not None
                    and (
                        advance_delivery_finalization_resume(self._runtime)
                        or advance_owned_delivery_finalization(
                            self._runtime, driver, workspace_parent, cancelled=self._stop.is_set
                        )
                    )
                ):
                    continue
                if driver is not None and advance_question_responses(
                    self._runtime,
                    driver,
                    cancelled=self._stop.is_set,
                ):
                    continue
                if driver is not None and advance_permission_responses(
                    self._runtime, driver, cancelled=self._stop.is_set
                ):
                    continue
                if (
                    driver is not None
                    and admissions
                    and advance_model_resumes(
                        self._runtime, driver, admissions, cancelled=self._stop.is_set
                    )
                ):
                    continue
                if driver is not None and advance_live_configuration(
                    self._runtime,
                    driver,
                    cancelled=self._stop.is_set,
                    check_admissions=self.project_check_admissions,
                ):
                    continue
                if capture is not None and capture.advance():
                    continue
                if checks is not None and checks.advance():
                    continue
                if testing is not None and testing.advance():
                    continue
                if (
                    driver is not None
                    and admissions
                    and capture is not None
                    and advance_repairs(
                        self._runtime,
                        driver,
                        workspace_parent,
                        admissions,
                        cancelled=self._stop.is_set,
                    )
                ):
                    continue
                if driver is not None and advance_role_reconciliation(
                    self._runtime, driver, cancelled=self._stop.is_set
                ):
                    continue
                if driver is not None and advance_role_handoff(
                    self._runtime,
                    driver,
                    self._installation.project_checks,
                    cancelled=self._stop.is_set,
                ):
                    continue
                if workspace_parent is not None and self._advance_delivery_preview(
                    actor, program, workspace_parent, delivery_recheck
                ):
                    continue
                forwarded = self._forward_observation_hint(actor)
                if actor.has_work() and not self._stop.is_set():
                    self._advance(actor, program)
                    continue
                if workspace_parent is not None and advance_start_basis(
                    self._runtime, workspace_parent, cancelled=self._stop.is_set
                ):
                    continue
                if workspace_parent is not None and advance_start_conditions(
                    self._runtime,
                    workspace_parent,
                    cancelled=self._stop.is_set,
                    executor_binary=self._installation.executor_binary,
                    launch_installation=self._installation.task_launch,
                ):
                    continue
                if workspace_parent is not None and advance_start_instance(
                    self._runtime,
                    workspace_parent,
                    cancelled=self._stop.is_set,
                    driver=driver,
                ):
                    continue
                if workspace_parent is not None and advance_start_session(
                    self._runtime,
                    workspace_parent,
                    cancelled=self._stop.is_set,
                    driver=driver,
                ):
                    continue
                if (
                    workspace_parent is not None
                    and not self._stop.is_set()
                    and workspace_start_pending(self._runtime)
                ):
                    with _frames(self._installation, program) as frames:
                        advance_workspace_start(
                            self._runtime,
                            actor,
                            frames,
                            workspace_parent,
                            cancelled=self._stop.is_set,
                        )
                    continue
                if driver is not None and monotonic() >= issue_due:
                    issue_due = monotonic() + 2
                    issue_cursor = advance_native_issue_observation(
                        self._runtime, driver, issue_cursor, cancelled=self._stop.is_set
                    )
                if not self._stop.is_set() and self._read_next_snapshot(actor, program):
                    continue
            except (
                GitConfigError,
                RefMetadataError,
                RefProtocolError,
                OSError,
                RuntimeError,
                sqlite3.Error,
                *BASELINE_INPUT_ERRORS,
            ) as error:
                retained = getattr(error, 'retained_owner', None)
                if (
                    retained is not None
                    and retained is not actor
                    and (capture is None or retained is not capture._dispatch)
                    and (
                        checks is None
                        or not checks.has_retained_command
                        or retained is not checks._retained[1]
                    )
                ):
                    raise
                # In particular, Guard not running is not evidence to retire an
                # old run. Recheck on a bounded cadence, before any next item.
                self._stop.wait(QUEUE_RECHECK_SECONDS)
                continue
            if not forwarded:
                self._wake.wait(QUEUE_RECHECK_SECONDS)

    def _advance_delivery_preview(self, actor, program, parent, deferred, *, stopping=False):
        from .task_delivery_plan_runtime import DeliveryPlanRun

        if not actor.snapshot_reads_ready():
            return False
        with self._runtime.database.transaction() as connection:
            rows = connection.execute(
                """SELECT o.id FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
                   WHERE o.operation_type='PREPARE_DELIVERY' AND o.status IN ('PENDING','RUNNING','UNKNOWN')
                   AND ((? AND t.stop_requested_at IS NOT NULL)
                     OR (NOT ? AND t.stop_requested_at IS NULL AND t.control_generation=o.control_generation))
                   ORDER BY o.id""",
                (int(stopping), int(stopping)),
            ).fetchall()
        now = monotonic()
        identity = next((row['id'] for row in rows if deferred.get(row['id'], 0) <= now), None)
        if identity is None:
            return False
        deferred[identity] = now + 3
        with _frames(self._installation, program) as frames:
            actor._require_current()
            actor._run(
                identity,
                DeliveryPlanRun,
                frames,
                parent=parent,
                admissions=self._installation.project_checks,
                cancelled=self._stop.is_set,
            )
        return True

    def _advance_delivery_write(self, actor, program, deferred):
        from .task_delivery_write_runtime import DeliveryRecoveryRun, DeliveryWriteRun

        if not actor.snapshot_reads_ready():
            return False
        with self._runtime.database.transaction() as connection:
            requested = next_delivery_reconciliation(connection)
            rows = connection.execute(
                """SELECT o.id,o.status,d.current_window_id FROM code_operations o
                   JOIN code_deliveries d ON d.operation_id=o.id
                   JOIN code_tasks t ON t.id=o.task_id
                   WHERE o.operation_type='DELIVER'
                     AND ((o.status='PENDING' AND t.stop_requested_at IS NULL)
                       OR o.status='RUNNING' OR (o.status='UNKNOWN' AND
                         (d.git_write_status IN ('MAY_HAVE_BEEN_SENT','UNKNOWN')
                           OR EXISTS(SELECT 1 FROM code_operation_steps s WHERE s.operation_id=o.id
                             AND s.step_no=1 AND s.status='UNKNOWN' AND s.started_at IS NOT NULL)
                           OR EXISTS(SELECT 1 FROM code_commands c WHERE c.operation_id=o.id
                             AND c.status IN ('PENDING','RUNNING','UNKNOWN')))))
                   ORDER BY CASE o.status WHEN 'PENDING' THEN 1 ELSE 0 END,o.id"""
            ).fetchall()
        if requested is not None:
            identity, runner = requested['original_id'], DeliveryRecoveryRun
        else:
            item = next(
                (
                    row
                    for row in rows
                    if (row['id'], row['status'] == 'PENDING', row['current_window_id'])
                    not in deferred
                ),
                None,
            )
            if item is None:
                return False
            identity = item['id']
            is_pending = item['status'] == 'PENDING'
            deferred[(identity, is_pending, item['current_window_id'])] = True
            runner = DeliveryWriteRun if is_pending else DeliveryRecoveryRun
        try:
            with _frames(self._installation, program) as frames:
                actor._require_current()
                actor._run(
                    identity,
                    runner,
                    frames,
                    admissions=self._installation.project_checks,
                    cancelled=self._stop.is_set,
                )
        except (OSError, RuntimeError, sqlite3.Error):
            if requested is None or actor.cleanup_required:
                raise
        if requested is not None:
            with self._runtime.database.transaction(write=True) as connection:
                finish_delivery_reconciliation(connection, requested['id'], identity)
        return True

    def _read_next_snapshot(self, actor, program):
        try:
            job = self._snapshot_queries.get_nowait()
        except Empty:
            return False
        if not job.result.set_running_or_notify_cancel():
            return True

        def cancelled():
            return self._stop.is_set() or job.cancelled.is_set() or monotonic() >= job.deadline

        try:
            if cancelled():
                raise SnapshotQueryUnavailable('Snapshot read deadline exceeded')
            with _frames(self._installation, program) as frames:
                data = actor.query_snapshot(
                    job.snapshot_id,
                    frames,
                    cancelled=cancelled,
                    finish=job.finish,
                    consume_file=job.consume_file,
                )
        except Exception as error:
            job.result.set_exception(error)
            if getattr(error, 'retained_owner', None) is not None:
                raise
        else:
            job.result.set_result(data)
        return True

    def _advance(self, actor, program):
        with _frames(self._installation, program) as frames:
            if actor.cleanup_required:
                actor.reconcile_cleanup(
                    frames,
                    timeout_ms=self._installation.limits.max_git_seconds * 1000,
                    cancelled=self._stop.is_set,
                )
            else:
                actor.run_next(frames, cancelled=self._stop.is_set)
