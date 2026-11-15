"""Own independent Testing project checks, observation and recovery."""

from contextlib import ExitStack
from datetime import UTC, datetime
from time import monotonic

from backend.app.code_tasks.task_candidate_commit import (
    check_stored_candidate_seal,
    read_stored_candidate_package,
)
from backend.app.infrastructure.content_package import verify_candidate_package
from backend.app.infrastructure.content_package_publish import PublishedCandidate
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.owned_check_http import allocate_http_endpoint
from backend.app.infrastructure.project_check_dispatch import ProjectCheckDispatch
from backend.app.infrastructure.project_check_journal import ProjectCheckJournal
from backend.app.infrastructure.project_check_recovery import ProjectCheckRecovery
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_project_check_command import ProjectCheckCommand
from backend.app.infrastructure.windows_task_directories import SnapshotCheckInput
from backend.app.shared.command_execution import operation_time

from .browser_run import BrowserCaseRun
from .cli_plan import TestingCliRuntime, read_fixed_profile, select_cli_plan
from .pack_definitions import compiled_definition, hold_compiled_pack_assets
from .pack_seal import RESOURCE_ERRORS
from .pack_validation import find_registered_reference, original_validation, validation_schedule
from .reference_resources import SOURCE_ERRORS, hold_reference_set
from .run_ownership import read_original_run, require_dispatch
from .run_settlement import (
    begin_browser_application,
    begin_case,
    finish_run,
    mark_unknown,
    prepared_case,
    settle_browser_case,
    settle_case,
)
from .run_target import prepare_snapshot_source
from .task_recovery import (
    finish_pending_reconcile,
    finish_pending_resume,
    native_reconcile_source,
    next_recovery,
    recovery_source,
    resume_available,
)

_CLEANUP_SECONDS = 30


class TestingCliWorker:
    def __init__(
        self,
        runtime,
        parent,
        binding,
        journal,
        connect,
        admissions,
        *,
        cancelled,
        query_snapshot=None,
        snapshot_reads_ready=None,
        browser_admissions=(),
    ):
        self._runtime, self._parent, self._binding = runtime, parent, binding
        self._journal, self._connect, self._admissions = journal, connect, admissions
        self._browser_admissions = browser_admissions
        self._cancelled = cancelled
        if (query_snapshot is None) != (snapshot_reads_ready is None):
            raise TypeError('Original snapshot query and cleanup gate must be installed together')
        self._query_snapshot, self._snapshot_reads_ready = query_snapshot, snapshot_reads_ready
        self._retained = None
        self._browser_retained = None
        self._deferred = {}

    @property
    def has_retained_command(self):
        return self._retained is not None or self._browser_retained is not None

    def _read(self, operation):
        with self._runtime.database.transaction() as connection:
            run = read_original_run(connection, operation)
            if run is None:
                raise StorageUnavailable('Original Testing run disappeared')
            _, compiled = compiled_definition(connection, run.pack)
            profile = read_fixed_profile(connection, run.task['profile_version_id'])
        definitions = {row['command_id']: row for row in profile['commands']}
        cases = {case.case_id: case for group in compiled.case_packs for case in group.cases}
        return run, profile, definitions, cases

    def _definition(self, case, definitions):
        if case.applications:
            return None
        row = definitions.get(case.fixed['admission']['command_id'])
        if row is None:
            raise StorageUnavailable('Original Testing case command definition disappeared')
        definition = ProjectCheckCommand.decode(row)
        if definition.definition_sha256 != case.fixed['admission']['command_sha256']:
            raise StorageUnavailable('Original Testing case command definition changed')
        return definition

    def _next(self):
        with self._runtime.database.transaction() as connection:
            rows = connection.execute(
                """SELECT o.id FROM code_operations o JOIN code_verifications v ON v.operation_id=o.id
                   JOIN testing_tasks t ON t.id=o.testing_task_id
                   WHERE o.task_id IS NULL AND o.operation_type='RUN_TEST'
                     AND o.status IN ('RUNNING','UNKNOWN')
                     AND v.testing_task_id=o.testing_task_id AND v.ended_at IS NULL
                     AND (t.validation_id IS NULL OR NOT EXISTS(
                         SELECT 1 FROM testing_tasks prior WHERE prior.validation_id=t.validation_id
                         AND prior.id<t.id AND prior.status NOT IN ('COMPLETED','TERMINATED')
                         AND NOT EXISTS(SELECT 1 FROM code_operations settled
                              WHERE settled.id=prior.active_operation_id AND settled.testing_task_id=prior.id
                              AND settled.operation_type='RUN_TEST' AND settled.status='CANCELLED')))
                   ORDER BY o.id"""
            ).fetchall()
        now = monotonic()
        return next((row['id'] for row in rows if self._deferred.get(row['id'], 0) <= now), None)

    def _lock(self):
        lock = self._runtime.commands().process_lock
        self._binding.assert_backend(lock)
        return lock

    def _active(self, case):
        self._lock()
        with self._runtime.database.transaction() as connection:
            try:
                run = require_dispatch(connection, case)
            except StorageUnavailable as error:
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_RUN_FENCED') from error
            if run.pack['status'] not in ('SEALED', 'PUBLISHED'):
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_ASSET_REVOKED')

    def _write(self, operation, *values, **options):
        self._lock()
        with self._runtime.database.transaction(write=True) as connection:
            return operation(connection, *values, operation_time(None), **options)

    def _evidence(self, case):
        return ProjectCheckJournal(
            self._journal, case.scope, case.epoch, lambda: self._active(case)
        )

    def _browser(self, case, maximum):
        return BrowserCaseRun(
            self._binding, self._lock(), self._parent, self._evidence, case, maximum
        )

    def _close_undispatched(self, case, definition, check_case, reason):
        if case.applications:
            browser = self._browser(case, 1)
            result, apps = browser.close_undispatched(reason)
            self._write(settle_browser_case, case, result, apps, undispatched=reason)
            return
        recovery = ProjectCheckRecovery(
            self._binding, self._lock(), case.scope, case.epoch, self._evidence(case)
        )
        closed = recovery.close_undispatched(self._parent, case.check)
        self._write(settle_case, case, definition, check_case, closed, undispatched=reason)

    def _snapshot_cleanup_pending(self, case):
        return (
            type(case.check) is SnapshotCheckInput
            and self._snapshot_reads_ready is not None
            and not self._snapshot_reads_ready()
        )

    def _recover(self, run, case, definition, check_case, *, cancelled):
        evidence = self._evidence(case)
        maximum = run.facts['runtime']['max_output_bytes']
        if case.applications:
            browser = self._browser(case, maximum)
            if not browser.was_dispatched() and self._snapshot_cleanup_pending(case):
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_SNAPSHOT_CLEANUP_REQUIRED')
            self._close_browser(case, browser, cancelled=cancelled)
            return
        complete = evidence.read_completion(case.check, maximum)
        if complete is None and not evidence.intent_saved('PREPARE'):
            if self._snapshot_cleanup_pending(case):
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_SNAPSHOT_CLEANUP_REQUIRED')
            self._close_undispatched(case, definition, check_case, 'EVIDENCE_INCOMPLETE')
            return
        if complete is None:
            recovery = ProjectCheckRecovery(
                self._binding, self._lock(), case.scope, case.epoch, evidence
            )
            with self._connect() as frames:
                complete = recovery.close_original(
                    frames,
                    self._parent,
                    case.check,
                    maximum,
                    deadline=monotonic() + _CLEANUP_SECONDS,
                    cancelled=cancelled,
                )
        self._write(settle_case, case, definition, check_case, complete)

    def _candidate(self, original, active):
        with PrivatePackageGuard(original.directory.canonical_path) as package:
            if package.verify() != original.directory:
                raise LaunchOutcomeUnknown('ORIGINAL_TESTING_CANDIDATE_LOCATION_DIFFERS')
            sealed = verify_candidate_package(
                package,
                original.binding,
                limits=original.limits,
                git_limits=original.git_limits,
                started_at=monotonic(),
                active=active,
            )
            check_stored_candidate_seal(original, sealed)
        return PublishedCandidate(sealed, original.directory)

    def _hold_reference(self, connection, resources, run, compiled, installation, deadline):
        if run.task['kind'] != 'PACK_VALIDATION':
            return
        original = original_validation(connection, run.task['validation_id'])
        if original is None:
            raise StorageUnavailable('Original Testing reference group is missing')
        group, operation, fixed, children = original
        registration = find_registered_reference(
            installation, compiled.basis_sha256, group['reference_set_ref']
        )
        if (
            group['test_pack_version_id'] != run.pack['id']
            or group['ended_at'] is not None
            or operation['status'] not in ('RUNNING', 'UNKNOWN')
            or fixed['pack_sha256'] != run.pack['sha256']
            or registration is None
            or registration.sha256 != fixed['reference_sha256']
            or not any(child['id'] == run.task['id'] for child in children)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_REFERENCE_GROUP_DIFFERS')
        reference_set = resources.enter_context(
            hold_reference_set(registration, deadline=deadline, cancelled=self._cancelled)
        )
        if validation_schedule(reference_set) != fixed['samples']:
            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_REFERENCE_SCHEDULE_DIFFERS')

    def _run_case(self, run, case, profile, definition, check_case):
        maximum = run.facts['runtime']['max_output_bytes']
        starts = [part.command['started_at'] for part in run.cases if part.command['started_at']]
        elapsed = (
            0
            if not starts
            else max(0, (datetime.now(UTC) - datetime.fromisoformat(min(starts))).total_seconds())
        )
        remaining = run.facts['runtime']['max_active_seconds'] - elapsed
        if remaining <= 0:
            self._close_undispatched(case, definition, check_case, 'TIMEOUT')
            return
        budget = remaining if case.applications else min(remaining, case.fixed['timeout_seconds'])
        deadline = monotonic() + budget
        evidence = self._evidence(case)

        def active():
            self._active(case)

        check_due = 0.0
        fenced = False

        def cancelled():
            nonlocal check_due, fenced
            if self._cancelled() or fenced:
                return True
            now = monotonic()
            if now >= check_due:
                check_due = now + 0.1
                try:
                    active()
                except LaunchOutcomeUnknown:
                    fenced = True
            return fenced

        dispatch = None
        browser = None
        try:
            with ExitStack() as resources:
                installation = getattr(self._runtime.catalog, 'testing_assets', None)
                if installation is None:
                    self._close_undispatched(case, definition, check_case, 'CONFIG_NOT_READY')
                    return
                with self._runtime.database.transaction() as connection:
                    compiled = resources.enter_context(
                        hold_compiled_pack_assets(
                            connection, installation, run.pack, deadline=deadline
                        )
                    )
                    selected = select_cli_plan(
                        compiled, profile, self._admissions, self._browser_admissions
                    )
                    if selected is None or selected.facts() != run.facts['runtime']:
                        raise LaunchOutcomeUnknown('ORIGINAL_TESTING_RUNTIME_RESOURCES_CHANGED')
                    self._hold_reference(
                        connection, resources, run, compiled, installation, deadline
                    )
                    snapshot = type(case.check) is SnapshotCheckInput
                    original = None
                    if not snapshot:
                        row = connection.execute(
                            'SELECT * FROM code_candidates WHERE id=?', (case.check.candidate_id,)
                        ).fetchone()
                        if row is None or row['manifest_sha256'] != case.check.manifest_sha256:
                            raise LaunchOutcomeUnknown('ORIGINAL_TESTING_CANDIDATE_DIFFERS')
                        original = read_stored_candidate_package(connection, row)
                with self._connect() as frames:
                    self._write(begin_case, case)
                    if snapshot:
                        if self._query_snapshot is None:
                            raise LaunchOutcomeUnknown(
                                'ORIGINAL_TESTING_SNAPSHOT_QUERY_UNAVAILABLE'
                            )
                        candidate, content_limits = prepare_snapshot_source(
                            self._runtime,
                            self._query_snapshot,
                            frames,
                            case.check,
                            active=active,
                            cancelled=cancelled,
                        )
                        git_limits = None
                    else:
                        candidate = self._candidate(original, active)
                        content_limits, git_limits = original.limits, original.git_limits
                    if case.applications:
                        browser = self._browser(case, maximum)
                        selected_case = next(
                            entry for entry in selected.cases if entry.case.case_id == case.case_id
                        )
                        result, apps = browser.run(
                            frames,
                            selected_case,
                            profile,
                            candidate,
                            limits=content_limits,
                            git_limits=git_limits,
                            deadline=deadline,
                            active=active,
                            cancelled=cancelled,
                            cleanup_seconds=_CLEANUP_SECONDS,
                            on_start=lambda app: self._write(begin_browser_application, case, app),
                            on_prepared=lambda: self._write(prepared_case, case),
                        )
                        self._write(settle_browser_case, case, result, apps)
                        return
                    admission = case.fixed['admission']
                    dispatch = ProjectCheckDispatch(
                        self._binding,
                        self._lock(),
                        case.scope,
                        case.check,
                        definition=definition,
                        runner_ref=admission['runner_ref'],
                        active_process_limit=admission['active_process_limit'],
                        job_memory_limit_bytes=admission['job_memory_limit_bytes'],
                        journal=evidence,
                    )
                    endpoint_ref = case.fixed.get('endpoint_ref')
                    if endpoint_ref is None:
                        stdin = check_case.steps[0].operands[1]
                        http = None
                    else:
                        stdin = b''
                        http = (
                            check_case,
                            allocate_http_endpoint(endpoint_ref),
                            case.fixed['request_limit'],
                        )
                    complete = dispatch.run(
                        frames,
                        self._parent,
                        candidate,
                        limits=content_limits,
                        git_limits=git_limits,
                        max_output_bytes=maximum,
                        deadline=deadline,
                        cleanup_seconds=_CLEANUP_SECONDS,
                        active=active,
                        cancelled=cancelled,
                        on_prepared=lambda: self._write(prepared_case, case),
                        stdin=stdin,
                        http=http,
                        fixture_sha256=admission.get('fixture_sha256'),
                    )
                self._write(settle_case, case, definition, check_case, complete)
        except (
            LaunchOutcomeUnknown,
            OSError,
            TaskExecutionError,
            *RESOURCE_ERRORS,
            *SOURCE_ERRORS,
        ) as error:
            if getattr(error, 'retained_owner', None) is dispatch and dispatch is not None:
                self._retained = (case, definition, check_case, dispatch, maximum)
            browser_dispatched = browser is not None and browser.was_dispatched()
            if browser_dispatched:
                self._browser_retained = (case, browser)
            if (
                browser_dispatched
                or evidence.intent_saved('PREPARE')
                or self._snapshot_cleanup_pending(case)
            ):
                self._write(mark_unknown, case)
                self._deferred[run.operation['id']] = monotonic() + 2
            else:
                reason = (
                    'TIMEOUT'
                    if monotonic() >= deadline
                    else 'CANCELLED'
                    if self._cancelled()
                    else 'CONFIG_NOT_READY'
                )
                self._close_undispatched(case, definition, check_case, reason)

    def _close_browser(self, case, browser, *, cancelled):
        with self._connect() as frames:
            result, apps = browser.recover(
                frames, deadline=monotonic() + _CLEANUP_SECONDS, cancelled=cancelled
            )
        self._write(settle_browser_case, case, result, apps)

    def reconcile(self, *, cancelled):
        if self._browser_retained is not None:
            case, browser = self._browser_retained
            try:
                self._close_browser(case, browser, cancelled=cancelled)
            except (LaunchOutcomeUnknown, OSError):
                return False
            self._browser_retained = None
            return True
        if self._retained is None:
            return False
        case, definition, check_case, dispatch, maximum = self._retained
        try:
            with self._connect() as frames:
                complete = dispatch.reconcile(
                    frames,
                    maximum=maximum,
                    deadline=monotonic() + _CLEANUP_SECONDS,
                    cancelled=cancelled,
                )
            self._write(settle_case, case, definition, check_case, complete)
        except (LaunchOutcomeUnknown, OSError):
            return False
        self._retained = None
        return True

    def _observe_requested(self):
        self._lock()
        with self._runtime.database.transaction() as connection:
            request = next_recovery(connection, 'RECONCILE')
            if request is None:
                return False
            case = native_reconcile_source(connection, request)
        if case is not None:
            members = (case, *case.applications)
            for original in members:
                evidence = self._evidence(original)
                if not evidence.intent_saved('PREPARE'):
                    continue
                try:
                    reader = ProjectCheckRecovery(
                        self._binding, self._lock(), original.scope, original.epoch, evidence
                    )
                    with self._connect() as frames:
                        reader.observe_latest(
                            frames, deadline=monotonic() + 5, cancelled=self._cancelled
                        )
                except (LaunchOutcomeUnknown, OSError):
                    # The reconcile receipt stays observational even when a
                    # particular original service or driver is still unknown.
                    continue
        self._lock()
        with self._runtime.database.transaction(write=True) as connection:
            return finish_pending_reconcile(connection, request['id'])

    def _resume(self):
        self._lock()
        with self._runtime.database.transaction() as connection:
            operation = next_recovery(connection, 'RESUME')
            if operation is None:
                return False
            original = recovery_source(connection, operation)
            run = read_original_run(connection, original['id'])
            installation = getattr(self._runtime.catalog, 'testing_assets', None)
            proven = False
            pending = (
                ()
                if run is None
                else tuple(case for case in run.cases if case.command['status'] == 'PENDING')
            )
            if (
                run is not None
                and (self._admissions or self._browser_admissions)
                and installation is not None
                and pending
                and all(
                    (case.scope.controller_ref, case.epoch)
                    == (self._binding.controller_ref, self._binding.owner_epoch)
                    for case in pending
                )
            ):
                try:
                    profile = read_fixed_profile(connection, run.task['profile_version_id'])
                    with hold_compiled_pack_assets(
                        connection, installation, run.pack, deadline=monotonic() + 5
                    ) as compiled:
                        selected = select_cli_plan(
                            compiled, profile, self._admissions, self._browser_admissions
                        )
                        if selected is not None and selected.facts() == run.facts['runtime']:
                            for case in pending:
                                for member in (case, *case.applications):
                                    self._evidence(member).require_no_dispatch()
                            proven = True
                except (LaunchOutcomeUnknown, OSError, *RESOURCE_ERRORS):
                    pass
        self._lock()
        with self._runtime.database.transaction(write=True) as connection:
            return finish_pending_resume(connection, operation['id'], proven=proven)

    def advance(self):
        if self._cancelled():
            return False
        if self._observe_requested():
            return True
        if self.has_retained_command:
            return self.reconcile(cancelled=self._cancelled)
        if self._resume():
            return True
        operation = self._next()
        if operation is None:
            return False
        try:
            run, profile, definitions, cases = self._read(operation)
            active = [
                case
                for case in run.cases
                if case.command['status'] in ('RUNNING', 'UNKNOWN')
                and case.command['ended_at'] is None
            ]
            if len(active) > 1:
                raise StorageUnavailable('Original Testing case commands must be serial')
            if active:
                case = active[0]
                self._write(mark_unknown, case)
                self._recover(
                    run,
                    case,
                    self._definition(case, definitions),
                    cases[case.case_id],
                    cancelled=self._cancelled,
                )
                return True
            pending = [case for case in run.cases if case.command['status'] == 'PENDING']
            if not pending:
                self._write(finish_run, operation, cases)
                self._deferred.pop(operation, None)
                return True
            if run.task['status'] == 'WAITING':
                resources = (
                    TestingCliRuntime(
                        self._binding, self._admissions, browser_admissions=self._browser_admissions
                    )
                    if self._admissions or self._browser_admissions
                    else None
                )
                with self._runtime.database.transaction() as connection:
                    if resume_available(connection, run.task, resources):
                        self._deferred[operation] = monotonic() + 2
                        return False
            case = pending[0]
            definition = self._definition(case, definitions)
            same_controller = (case.scope.controller_ref, case.epoch) == (
                self._binding.controller_ref,
                self._binding.owner_epoch,
            )
            if (
                run.can_dispatch
                and same_controller
                and (self._admissions or self._browser_admissions)
            ):
                self._run_case(run, case, profile, definition, cases[case.case_id])
            else:
                reason = (
                    'CANCELLED'
                    if run.task['status'] == 'STOPPING'
                    else 'TEST_ASSET_REVOKED'
                    if run.pack['status'] == 'REVOKED'
                    else 'EVIDENCE_INCOMPLETE'
                    if run.operation['status'] == 'UNKNOWN'
                    else 'CONFIG_NOT_READY'
                )
                self._close_undispatched(case, definition, cases[case.case_id], reason)
        except (LaunchOutcomeUnknown, StorageUnavailable, OSError):
            self._deferred[operation] = monotonic() + 2
            return False
        return True
