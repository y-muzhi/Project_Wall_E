"""Advance an already accepted original CHECK on the owned backend thread."""

from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from backend.app.infrastructure.content_package import verify_candidate_package
from backend.app.infrastructure.content_package_publish import PublishedCandidate
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.project_check_dispatch import ProjectCheckDispatch
from backend.app.infrastructure.project_check_journal import ProjectCheckJournal
from backend.app.infrastructure.project_check_recovery import ProjectCheckRecovery
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .authorizations import project_grant
from .coding_check_plan import CodingCheckPlanError, read_coding_handoff_plan
from .coding_project_check_scope import require_project_check_admissions
from .task_candidate_commit import check_stored_candidate_seal, read_stored_candidate_package
from .task_project_check import (
    accept_restored_check_copy,
    close_idle_project_check,
    fail_unprepared_project_check,
    finish_coding_project_check,
    mark_coding_project_check_unknown,
    prepare_coding_project_check,
    read_idle_project_check,
    read_interrupted_project_check,
    start_following_project_check,
    verify_coding_project_check_active,
)
from .task_testing_publication import restore_published_task_after_check

_CLEANUP_SECONDS = 30


class CodingProjectCheckWorker:
    def __init__(self, runtime, parent, binding, journal, connect, admissions, *, cancelled):
        self._runtime, self._parent, self._binding, self._journal = (
            runtime,
            parent,
            binding,
            journal,
        )
        self._connect, self._admissions, self._cancelled = connect, admissions, cancelled
        self._deferred = {}
        self._recovery_cursor = 0
        self._recovery_due = 0.0
        self._retained = None

    @property
    def has_retained_command(self):
        return self._retained is not None

    def _next(self):
        with self._runtime.database.transaction() as connection:
            rows = connection.execute(
                """SELECT o.id,t.id AS task_id,t.current_candidate_id,s.step_no,s.external_identity
                   FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
                   JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_type='CHECK'
                   JOIN code_candidates c ON c.task_id=t.id AND c.id=t.current_candidate_id
                   WHERE t.status='VERIFYING' AND t.phase IN ('BACKEND','FRONTEND','INTEGRATION')
                     AND t.control_generation=o.control_generation AND t.stop_requested_at IS NULL
                     AND ((o.operation_type='CAPTURE_AND_CHECK' AND o.status='RUNNING'
                           AND c.capture_operation_id=o.id AND s.step_no=4)
                          OR (o.operation_type='VERIFY_CANDIDATE' AND o.status IN ('PENDING','RUNNING')
                           AND c.id=json_extract(o.fixed_input,'$.candidate_id') AND s.step_no=3))
                     AND ((s.status='PENDING' AND s.external_identity IS NULL)
                          OR (s.status='RUNNING' AND s.external_identity IS NOT NULL
                              AND EXISTS (SELECT 1 FROM code_commands c WHERE c.operation_id=o.id
                                          AND c.purpose='CHECK' AND c.status='PENDING')
                              AND NOT EXISTS (SELECT 1 FROM code_commands c WHERE c.operation_id=o.id
                                              AND c.purpose='CHECK' AND c.status IN ('RUNNING','UNKNOWN'))))
                   ORDER BY o.id""",
            ).fetchall()
        return next((row for row in rows if self._deferred.get(row['id'], 0) <= monotonic()), None)

    def _plan(self, connection, task_id, candidate_id):
        plan = read_coding_handoff_plan(connection, self._runtime.catalog, task_id, candidate_id)
        return plan, require_project_check_admissions(plan.selection(), self._admissions)

    def _read_candidate(self, row):
        with self._runtime.database.transaction() as connection:
            plan, _ = self._plan(connection, row['task_id'], row['current_candidate_id'])
            task = connection.execute(
                'SELECT * FROM code_tasks WHERE id=?', (plan.task_id,)
            ).fetchone()
            candidate = connection.execute(
                'SELECT * FROM code_candidates WHERE id=? AND task_id=?',
                (plan.candidate_id, plan.task_id),
            ).fetchone()
            profile = connection.execute(
                'SELECT limits FROM code_execution_profile_versions WHERE id=?',
                (plan.profile_version_id,),
            ).fetchone()
            grant = connection.execute(
                "SELECT * FROM code_authorizations WHERE id=? AND status='EFFECTIVE'",
                (task['authorization_id'],),
            ).fetchone()
            if candidate is None or profile is None or grant is None:
                raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')
            settings = strict_json_object(profile['limits'])
            granted = project_grant(grant)['scope']['limits']
            elapsed = max(
                0, (datetime.now(UTC) - datetime.fromisoformat(task['started_at'])).total_seconds()
            )
            timeout = min(settings['max_active_seconds'], granted['max_active_seconds']) - elapsed
            maximum = min(settings['max_check_output_bytes'], granted['max_check_output_bytes'])
            original = read_stored_candidate_package(connection, candidate)
        if timeout <= 0:
            raise CodingCheckPlanError('CHECK_CONFIGURATION_INVALID')

        def active():
            self._runtime.commands().process_lock.assert_owned()
            if self._cancelled():
                raise CodingCheckPlanError('VERIFICATION_STAGE_NOT_READY')

        with PrivatePackageGuard(original.directory.canonical_path) as package:
            if package.verify() != original.directory:
                raise CodingCheckPlanError('CONTENT_NOT_READY')
            sealed = verify_candidate_package(
                package,
                original.binding,
                limits=original.limits,
                git_limits=original.git_limits,
                started_at=monotonic(),
                active=active,
            )
            check_stored_candidate_seal(original, sealed)
        return original, PublishedCandidate(sealed, original.directory), timeout, maximum

    def _recover_one(self):
        if monotonic() < self._recovery_due:
            return False
        lock = self._runtime.commands().process_lock
        self._binding.assert_backend(lock)
        with self._runtime.database.transaction() as connection:
            row = connection.execute(
                """SELECT o.id FROM code_operations o
                   JOIN code_operation_steps s ON s.operation_id=o.id AND s.step_type='CHECK'
                   WHERE o.id>? AND o.operation_type IN ('CAPTURE_AND_CHECK','VERIFY_CANDIDATE')
                     AND s.external_identity IS NOT NULL
                     AND (s.status IN ('RUNNING','UNKNOWN') OR
                          (o.operation_type='VERIFY_CANDIDATE' AND s.status='PENDING'))
                   ORDER BY o.id LIMIT 1""",
                (self._recovery_cursor,),
            ).fetchone()
            if row is None:
                self._recovery_cursor = 0
                self._recovery_due = monotonic() + 2
                return False
            self._recovery_cursor = row['id']
            original = read_interrupted_project_check(connection, row['id'])
            idle = None if original is not None else read_idle_project_check(connection, row['id'])
        if original is None:
            if idle is not None:
                (_, _, _, _, _, _, (following, _), current) = idle
                if (
                    not current
                    or not self._admissions
                    or following.scope.controller_ref != self._binding.controller_ref
                    or following.owner_epoch != self._binding.owner_epoch
                ):
                    with self._runtime.database.transaction(write=True) as connection:
                        return close_idle_project_check(
                            connection,
                            row['id'],
                            failure='EVIDENCE_INCOMPLETE',
                            at=operation_time(None),
                        )
            return False
        claim, status = original
        if status == 'RUNNING':
            with self._runtime.database.transaction(write=True) as connection:
                mark_coding_project_check_unknown(connection, claim, at=operation_time(None))
        if claim.owner_epoch is None:
            # Older private claims can still be fenced. They carry no durable
            # terminal receipt or historical controller selector.
            return True
        evidence = ProjectCheckJournal(self._journal, claim.scope, claim.owner_epoch, lambda: None)
        completion = evidence.read_completion(claim.check, claim.max_output_bytes)
        if completion is None:
            recovery = ProjectCheckRecovery(
                self._binding, lock, claim.scope, claim.owner_epoch, evidence
            )
            try:
                if evidence.intent_saved('PREPARE'):
                    with self._connect() as frames:
                        completion = recovery.close_original(
                            frames,
                            self._parent,
                            claim.check,
                            claim.max_output_bytes,
                            deadline=monotonic() + _CLEANUP_SECONDS,
                            cancelled=self._cancelled,
                        )
                else:
                    completion = recovery.close_undispatched(self._parent, claim.check)
            except (OSError, LaunchOutcomeUnknown):
                # Keep the original ownership reserved and let unrelated work proceed.
                return True
        self._finish(claim, completion)
        return True

    def advance(self):
        if self._cancelled():
            return False
        if self._retained is not None:
            return self.reconcile(cancelled=self._cancelled)
        if self._recover_one():
            return True
        row = self._next()
        if row is None:
            return False
        try:
            if not self._admissions:
                raise CodingCheckPlanError('CONFIG_NOT_READY')
            original, candidate, timeout, maximum = self._read_candidate(row)
            with self._connect() as frames:
                self._execute(frames, row, original, candidate, timeout, maximum)
        except CodingCheckPlanError as error:
            failure = (
                error.code
                if error.code
                in ('CONTENT_NOT_READY', 'CONFIG_NOT_READY', 'VERIFICATION_STAGE_NOT_READY')
                else 'CHECK_CONFIGURATION_INVALID'
            )
            with self._runtime.database.transaction(write=True) as connection:
                at = operation_time(None)
                if row['external_identity'] is None:
                    fail_unprepared_project_check(connection, row['id'], failure, at=at)
                else:
                    close_idle_project_check(connection, row['id'], failure=failure, at=at)
        except (OSError, RuntimeError, ValueError):
            self._deferred[row['id']] = monotonic() + 2
        else:
            self._deferred.pop(row['id'], None)
        return True

    def _execute(self, frames, row, original, candidate, timeout, maximum):
        following = row['external_identity'] is not None
        with self._runtime.database.transaction(write=True) as connection:
            plan, selection = self._plan(connection, row['task_id'], row['current_candidate_id'])
            at = operation_time(None)
            if following:
                claim, selected = start_following_project_check(
                    connection,
                    row['id'],
                    selection,
                    self._binding,
                    max_output_bytes=maximum,
                    at=at,
                )
            else:
                scopes = tuple(
                    self._binding.scope(row['id'], row['step_no'], uuid4().hex) for _ in selection
                )
                claim = prepare_coding_project_check(
                    connection,
                    scopes,
                    plan,
                    selection,
                    owner_epoch=self._binding.owner_epoch,
                    max_output_bytes=maximum,
                    at=at,
                )
                selected = selection[0]
        scope = claim.scope
        admission = selected.admission
        timeout = min(timeout, selected.timeout_seconds)

        def active():
            self._binding.assert_backend(self._runtime.commands().process_lock)
            with self._runtime.database.transaction() as connection:
                verify_coding_project_check_active(connection, claim)

        def restored(descriptor):
            with self._runtime.database.transaction(write=True) as connection:
                accept_restored_check_copy(connection, claim, descriptor, at=operation_time(None))

        next_task_check = 0.0

        def cancelled():
            nonlocal next_task_check
            if self._cancelled():
                return True
            if monotonic() < next_task_check:
                return False
            next_task_check = monotonic() + 0.05
            try:
                active()
            except StorageUnavailable:
                return True
            return False

        evidence = ProjectCheckJournal(self._journal, scope, self._binding.owner_epoch, active)
        dispatch = ProjectCheckDispatch(
            self._binding,
            self._runtime.commands().process_lock,
            scope,
            claim.check,
            definition=admission.command,
            runner_ref=admission.runner_ref,
            active_process_limit=admission.active_process_limit,
            job_memory_limit_bytes=admission.job_memory_limit_bytes,
            journal=evidence,
        )
        try:
            result = dispatch.run(
                frames,
                self._parent,
                candidate,
                limits=original.limits,
                git_limits=original.git_limits,
                max_output_bytes=maximum,
                deadline=monotonic() + timeout,
                cleanup_seconds=_CLEANUP_SECONDS,
                active=active,
                cancelled=cancelled,
                on_restored=restored if scope.step_no == 3 and not following else None,
            )
        except BaseException as error:
            if getattr(error, 'retained_owner', None) is dispatch:
                self._retained = (claim, dispatch, maximum, None)
            with self._runtime.database.transaction(write=True) as connection:
                mark_coding_project_check_unknown(connection, claim, at=operation_time(None))
            raise
        self._retained = (claim, dispatch, maximum, result)
        self._finish(claim, result)

    def _finish(self, claim, result):
        with self._runtime.database.transaction(write=True) as connection:
            at = operation_time(None)
            finish_coding_project_check(
                connection,
                claim,
                result,
                at=at,
                allow_following=claim.scope.controller_ref == self._binding.controller_ref
                and claim.owner_epoch == self._binding.owner_epoch,
            )
            restore_published_task_after_check(
                connection, self._runtime.catalog, self._admissions, claim, at=at
            )
        self._retained = None

    def reconcile(self, *, cancelled):
        if self._retained is None:
            return False
        claim, dispatch, maximum, result = self._retained
        if result is None:
            with self._connect() as frames:
                result = dispatch.reconcile(
                    frames,
                    maximum=maximum,
                    deadline=monotonic() + _CLEANUP_SECONDS,
                    cancelled=cancelled,
                )
            self._retained = (claim, dispatch, maximum, result)
        self._finish(claim, result)
        return True
