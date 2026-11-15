"""Reconcile original repository resources at the next backend epoch."""

from collections import deque

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown
from backend.app.infrastructure.windows_guard_pipe_io import _deadline
from backend.app.shared.command_execution import operation_time

from .repository_baseline_pin import BaselinePinGitDispatch
from .repository_baseline_query import BaselineQueryGitDispatch
from .repository_baseline_validation import original_baseline
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
from .repository_git_runner import RepositoryGitScopeActions
from .repository_observation_publish import _original as _original_observation
from .repository_registration import _original as _original_registration

_BASELINE_DISPATCHERS = (BaselineGitDispatch, BaselinePinGitDispatch, BaselineVerifyGitDispatch)


def _recover_baseline_step(connection, operation_id):
    operation, _, steps = original_baseline(connection, operation_id)
    if operation['status'] == 'SUCCEEDED':
        return None
    if (
        operation['status'] == 'UNKNOWN'
        and steps[0]['status'] == 'SUCCEEDED'
        and steps[1]['status'] == 'UNKNOWN'
        and steps[2]['status'] in ('RUNNING', 'UNKNOWN')
        and steps[3]['status'] == 'PENDING'
    ):
        BaselineRecoveredVerifyGitDispatch._active_step(
            connection, operation_id, allow_unknown=True
        )
        step = steps[2]
        if step['result_ref'] is not None:
            raise StorageUnavailable('Original baseline observation has an unexpected result')
        if step['status'] == 'RUNNING':
            connection.execute(
                "UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=? "
                'WHERE operation_id=? AND step_no=3',
                (operation_time(None), operation_id),
            )
        return BaselineRecoveredVerifyGitDispatch if step['external_identity'] is not None else None
    for index, step in enumerate(steps[:3]):
        if step['status'] == 'SUCCEEDED':
            if step['result_ref'] is None or step['external_identity'] is None:
                raise StorageUnavailable('Original completed baseline evidence is missing')
            continue
        after = steps[index + 1 :]
        if any(
            later['status'] != 'PENDING'
            or any(
                later[key] is not None
                for key in (
                    'external_identity',
                    'result_ref',
                    'started_at',
                    'ended_at',
                    'last_observed_at',
                )
            )
            for later in after
        ):
            raise StorageUnavailable('Original later baseline step has evidence')
        if (
            index > 0
            and operation['status'] == 'RUNNING'
            and step['status'] == 'PENDING'
            and all(
                step[key] is None
                for key in (
                    'external_identity',
                    'result_ref',
                    'started_at',
                    'ended_at',
                    'last_observed_at',
                )
            )
        ):
            return None
        if (
            operation['status'] not in ('RUNNING', 'UNKNOWN')
            or step['status'] != operation['status']
            or step['result_ref'] is not None
        ):
            raise StorageUnavailable('Original baseline recovery step differs')
        mark_repository_read_unknown(connection, operation, step)
        return _BASELINE_DISPATCHERS[index] if step['external_identity'] is not None else None
    raise StorageUnavailable('Original baseline publication is incomplete')


class RepositoryRestartRecovery:
    """Hold original evidence until safe cleanup, without starting repository work."""

    def __init__(self, runtime, binding, journal):
        self._runtime, self._binding, self._journal = runtime, binding, journal
        self._dispatch = None
        self._scopes = None
        self.observations = deque()
        with runtime.database.transaction() as connection:
            self._pending = deque(
                (row['id'], row['operation_type'])
                for row in connection.execute(
                    "SELECT id,operation_type FROM code_operations WHERE resource_kind='REPOSITORY' "
                    "AND operation_type IN ('REGISTER_REPOSITORY','REFRESH_REPOSITORY','REGISTER_BASE') "
                    "AND status IN ('RUNNING','UNKNOWN') ORDER BY id"
                )
            )

        self._pending.extend(
            (query_id, 'SNAPSHOT_QUERY') for query_id in BaselineQueryGitDispatch.saved_ids(journal)
        )

    def _load_original(self, operation_id, operation_type):
        if operation_type == 'SNAPSHOT_QUERY':
            if self._dispatch is None:
                self._dispatch = BaselineQueryGitDispatch(
                    self._runtime, None, self._binding, self._journal
                )
                self._dispatch.reopen(operation_id)
            if self._dispatch.already_closed():
                return ()
            return self._old_scope_actions(self._dispatch.original(self._dispatch.operation_id))
        if operation_type == 'REGISTER_BASE':
            with self._runtime.database.transaction(write=True) as connection:
                kind = _recover_baseline_step(connection, operation_id)
            if kind is None:
                return ()
        else:
            kind = self._repository_read_dispatch(operation_id, operation_type)
            if kind is None:
                return ()
        if self._dispatch is None:
            self._dispatch = kind(self._runtime, None, self._binding, self._journal)
        saved = self._dispatch.original(operation_id)
        scopes = (saved,) if kind is RegistrationGitDispatch else saved
        return self._old_scope_actions(scopes)

    def _old_scope_actions(self, scopes):
        actions = []
        for scope in scopes:
            if (
                scope.scope.controller_ref == self._binding.controller_ref
                or scope.owner_epoch == self._binding.owner_epoch
            ):
                raise LaunchOutcomeUnknown('DISTINCT_ORIGINAL_REPOSITORY_EPOCH_REQUIRED')
            actions.append(
                RepositoryGitScopeActions(self._runtime, self._binding, self._dispatch, scope)
            )
        return tuple(actions)

    def _repository_read_dispatch(self, operation_id, operation_type):
        registration = operation_type == 'REGISTER_REPOSITORY'
        with self._runtime.database.transaction(write=True) as connection:
            if registration:
                operation, _, steps = _original_registration(connection, operation_id)
            else:
                operation, steps = _original_observation(connection, operation_id)
            if operation['status'] == 'SUCCEEDED':
                return None
            first, second = steps
            if (
                operation['status'] not in ('RUNNING', 'UNKNOWN')
                or first['status'] != operation['status']
                or second['status'] != 'PENDING'
                or any(step['result_ref'] is not None for step in steps)
            ):
                raise StorageUnavailable('Original repository recovery steps differ')
            mark_repository_read_unknown(connection, operation, first)
            if first['external_identity'] is None:
                return None
        return RegistrationGitDispatch if registration else ObservationGitDispatch

    def requires_connection(self):
        while self._pending:
            if self._scopes is None:
                self._scopes = self._load_original(*self._pending[0])
            if any(actions.cleanup_pending() for actions in self._scopes):
                return True
            self._finish()
        return False

    def reconcile(self, frames, *, timeout_ms, cancelled):
        if not self.requires_connection():
            return
        deadline = _deadline(timeout_ms)
        self._dispatch.reconnect(frames)
        for actions in self._scopes:
            if actions.cleanup_pending():
                actions.use_boundary(deadline, cancelled)
                actions.original_preparation(observe=True)
                actions.finish_cleanup()
        self._finish()

    def _finish(self):
        if type(self._dispatch) is BaselineQueryGitDispatch:
            self._dispatch.retire()
        observe = type(self._dispatch) is BaselinePinGitDispatch
        self.close()
        operation_id, _ = self._pending.popleft()
        if observe and operation_id not in self.observations:
            self.observations.append(operation_id)

    def close(self):
        if self._dispatch is not None:
            self._dispatch.close()
            self._dispatch = None
        self._scopes = None
