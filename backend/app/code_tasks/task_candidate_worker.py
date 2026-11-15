"""Advance original capture work on the existing Guard owner thread."""

from collections import deque
from contextlib import contextmanager

from backend.app.infrastructure.git_content_command import (
    CONTENT_COMMAND_REF,
    CONTENT_STORE_DIRECTORY,
)
from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.shared.command_execution import operation_time

from .task_candidate_commit import load_candidate_capture
from .task_candidate_git import CandidateGitDispatch
from .task_candidate_runtime import capture_original_candidate, reconcile_original_candidate
from .task_capture_failure import fail_unsealed_capture, local_capacity_failure
from .task_capture_quiescence import observe_capture_quiescence


class CandidateCaptureWorker:
    """Own one original capture and its in-flight Control Git resources."""

    def __init__(
        self, runtime, driver, parent, binding, journal, connect, *, cancelled, cleanup_timeout_ms
    ):
        if (
            type(parent) is not PrivatePackageGuard
            or not callable(connect)
            or not callable(cancelled)
        ):
            raise TypeError('Original capture worker resources required')
        self._runtime, self._driver, self._parent = runtime, driver, parent
        self._binding, self._journal, self._connect = binding, journal, connect
        self._cancelled, self._timeout = cancelled, cleanup_timeout_ms
        self._dispatch = None
        self._deferred = set()
        with runtime.database.transaction() as connection:
            self._interrupted = deque(
                (row['operation_id'], row['id'])
                for row in connection.execute(
                    """SELECT c.operation_id,c.id FROM code_commands c
                       JOIN code_operations o ON o.id=c.operation_id AND o.task_id=c.task_id
                       WHERE c.purpose='CONTROL_GIT' AND c.command_ref=? AND c.status='RUNNING'
                       AND o.operation_type='CAPTURE_AND_CHECK' ORDER BY c.id""",
                    (CONTENT_COMMAND_REF,),
                )
            )

    @property
    def has_retained_command(self):
        return self._dispatch is not None

    def _next(self):
        with self._runtime.database.transaction() as connection:
            rows = connection.execute(
                """SELECT o.id,q.status AS quiesce,c.status AS capture,p.status AS publication
                   FROM code_operations o JOIN code_tasks t ON t.id=o.task_id
                   JOIN code_operation_steps q ON q.operation_id=o.id AND q.step_no=1
                   JOIN code_operation_steps c ON c.operation_id=o.id AND c.step_no=2
                   JOIN code_operation_steps p ON p.operation_id=o.id AND p.step_no=3
                   WHERE o.operation_type='CAPTURE_AND_CHECK' AND o.resource_kind='TASK'
                   AND (o.status IN ('PENDING','RUNNING','UNKNOWN')
                       OR (o.status='CANCELLED' AND c.status='SUCCEEDED'))
                   AND p.status IN ('PENDING','RUNNING','UNKNOWN')
                   AND ((t.stop_requested_at IS NULL AND o.control_generation=t.control_generation)
                       OR (q.status='SUCCEEDED' AND c.status IN ('RUNNING','UNKNOWN','SUCCEEDED')))
                   ORDER BY o.id""",
            ).fetchall()
        return next((row for row in rows if row['id'] not in self._deferred), None)

    @contextmanager
    def _store(self, *, create):
        original = self._parent.verify()
        path = self._parent.path / CONTENT_STORE_DIRECTORY
        try:
            path.lstat()
        except FileNotFoundError:
            if not create:
                raise TaskExecutionError('ORIGINAL_CAPTURE_PACKAGE_LOCATION_UNVERIFIED') from None
            create_private_package(path)
        with PrivatePackageGuard(path) as store:
            if self._parent.verify() != original:
                raise TaskExecutionError('ORIGINAL_CAPTURE_STORE_CHANGED')
            yield store

    def _exchange(self, operation, intent, repo, raw, maximum, remaining):
        with self._connect() as frames:
            dispatch = CandidateGitDispatch(
                self._runtime,
                frames,
                self._binding,
                self._journal,
                operation,
                self._parent,
                cancelled=self._cancelled,
            )
            try:
                return dispatch.exchange(intent, repo, raw, maximum, remaining)
            finally:
                if dispatch._original is not None:
                    self._dispatch = dispatch
                else:
                    dispatch.close()

    def _unknown(self, operation, number):
        with self._runtime.database.transaction(write=True) as connection:
            _, task, original, steps = load_candidate_capture(connection, operation)
            if original['status'] not in ('PENDING', 'RUNNING', 'UNKNOWN'):
                return
            step = steps[number - 1]
            if step['status'] in ('PENDING', 'RUNNING', 'UNKNOWN'):
                at = max(operation_time(None), task['updated_at'])
                connection.execute(
                    """UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=?
                       WHERE operation_id=? AND step_no=?""",
                    (at, operation, number),
                )
                connection.execute(
                    """UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN'
                       WHERE id=?""",
                    (operation,),
                )

    def _fail_capacity(self, operation, error):
        if self._cancelled() or not local_capacity_failure(error):
            return False
        try:
            self._runtime.commands().process_lock.assert_owned()
            with self._runtime.database.transaction() as connection:
                prepared, _, _, _ = load_candidate_capture(connection, operation)
            with self._store(create=False) as store:
                original = store.verify()
                final = store.path / prepared.binding.package_name(staged=False)
                stage = store.path / prepared.binding.package_name(staged=True)
                try:
                    final.lstat()
                except FileNotFoundError:
                    pass
                else:
                    return False
                try:
                    stage.lstat()
                except FileNotFoundError:
                    pass
                else:
                    with PrivatePackageGuard(stage) as package:
                        package.verify()
                        try:
                            (stage / 'seal.json').lstat()
                        except FileNotFoundError:
                            pass
                        else:
                            return False
                if store.verify() != original:
                    return False
                self._runtime.commands().process_lock.assert_owned()
                if self._cancelled():
                    return False
                with self._runtime.database.transaction(write=True) as connection:
                    return fail_unsealed_capture(connection, operation)
        except (OSError, ValueError, RuntimeError):
            return False

    def reconcile_command(self, *, cancelled):
        if self._dispatch is None:
            return False
        with self._connect() as frames:
            self._dispatch.reconcile_cleanup(frames, timeout_ms=self._timeout, cancelled=cancelled)
        self._dispatch.close()
        self._dispatch = None
        return True

    def _recover_released_command(self):
        operation, command = self._interrupted.popleft()
        dispatch = CandidateGitDispatch(
            self._runtime,
            None,
            self._binding,
            self._journal,
            operation,
            self._parent,
            cancelled=self._cancelled,
        )
        try:
            if dispatch.recover_released(command):
                self._unknown(operation, 2)
        finally:
            dispatch.close()

    def advance(self):
        if self._cancelled():
            return False
        if self._dispatch is not None:
            return self.reconcile_command(cancelled=self._cancelled)
        if self._interrupted:
            self._recover_released_command()
            return True
        row = self._next()
        if row is None:
            return False
        operation = row['id']
        if row['quiesce'] != 'SUCCEEDED':
            step = 1
        else:
            step = 3 if row['capture'] == 'SUCCEEDED' else 2
        fresh_capture = False
        try:
            if step == 1:
                observe_capture_quiescence(
                    self._runtime,
                    self._driver,
                    operation,
                    cancelled=self._cancelled,
                )
            else:
                capture = row['capture'] == 'PENDING' and row['publication'] == 'PENDING'
                fresh_capture = capture
                with self._store(create=capture) as store:
                    materialization = self._parent.path / 'candidate-check-copy'
                    if capture:
                        capture_original_candidate(
                            self._runtime,
                            self._driver,
                            operation,
                            workspace_parent=self._parent,
                            store=store,
                            materialization_root=materialization,
                            exchange=lambda *values: self._exchange(operation, *values),
                            cancelled=self._cancelled,
                        )
                    else:
                        reconcile_original_candidate(
                            self._runtime,
                            operation,
                            store=store,
                            materialization_root=materialization,
                            cancelled=self._cancelled,
                        )
        except (OSError, ValueError, RuntimeError) as error:
            self._runtime.commands().process_lock.assert_owned()
            retained = getattr(error, 'retained_owner', None)
            if retained is not None and retained is not self._dispatch:
                raise
            if (
                fresh_capture
                and retained is None
                and self._dispatch is None
                and self._fail_capacity(operation, error)
            ):
                return True
            self._runtime.commands().process_lock.assert_owned()
            self._deferred.add(operation)
            self._unknown(operation, step)
        return True
