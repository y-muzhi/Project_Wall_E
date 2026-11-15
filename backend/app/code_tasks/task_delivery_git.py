"""Owned Git command records for one original local delivery operation."""

from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.guard_control_git_input import (
    CONFIG_COMMAND_REF,
    DELIVERY_ANCESTOR_COMMAND_REF,
    DELIVERY_OBJECT_COMMAND_REF,
    DELIVERY_REF_COMMAND_REF,
    DELIVERY_TARGET_COMMAND_REF,
    OBJECT_BATCH_COMMAND_REF,
    REPOSITORY_COMMANDS,
)
from backend.app.infrastructure.guard_controller_binding import owner_epoch
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_json_object

from .repository_git_dispatch import RepositoryGitScope, _RepositoryGitDispatch
from .repository_git_runner import RepositoryGitScopeActions
from .task_candidate_git import CandidateGitDispatch
from .task_delivery_write import load_original_delivery, require_live_delivery


@dataclass(frozen=True)
class DeliveryGitInput:
    command_ref: str
    intent_sha256: str | None
    target_ref: str | None = None


_COMMANDS = {
    2: frozenset((CONFIG_COMMAND_REF, OBJECT_BATCH_COMMAND_REF, DELIVERY_OBJECT_COMMAND_REF)),
    4: frozenset((CONFIG_COMMAND_REF, OBJECT_BATCH_COMMAND_REF, DELIVERY_REF_COMMAND_REF)),
    5: frozenset((CONFIG_COMMAND_REF, DELIVERY_TARGET_COMMAND_REF)),
    7: frozenset(
        (
            CONFIG_COMMAND_REF,
            OBJECT_BATCH_COMMAND_REF,
            DELIVERY_TARGET_COMMAND_REF,
            DELIVERY_ANCESTOR_COMMAND_REF,
        )
    ),
}


class DeliveryGitDispatch(CandidateGitDispatch):
    """Reuse the original command ownership, pipe, completion and cleanup machinery."""

    def __init__(self, runtime, frames, binding, journal, *, content_parent=None):
        # The delivery reads and writes the registered repository, not a package repo.
        _RepositoryGitDispatch.__init__(
            self, runtime, frames, binding, journal, content_parent=content_parent
        )
        self._operation_id = self._config_scope = None
        self._command_id = self._original = self._intent = self._run = None
        self._ref_retry_window = None

    def bind(self, operation_id):
        if self._operation_id is not None:
            raise StorageUnavailable('Original delivery Git owner already bound')
        self._operation_id = operation_id

    def _active_step(self, connection, operation_id, *, allow_unknown=False):
        if operation_id != self._operation_id:
            raise StorageUnavailable('Original delivery Git operation differs')
        original = load_original_delivery(connection, operation_id)
        step = original.steps[self._step_no - 1]
        if allow_unknown:
            if step['status'] not in ('RUNNING', 'UNKNOWN', 'SUCCEEDED'):
                raise StorageUnavailable('Original delivery Git cleanup step differs')
        elif self._step_no == 7:
            if original.delivery['git_write_status'] not in (
                'MAY_HAVE_BEEN_SENT',
                'UNKNOWN',
                'CONFIRMED',
            ) or step['status'] not in ('RUNNING', 'SUCCEEDED'):
                raise StorageUnavailable('Original delivery requires a read-only reconciliation')
        else:
            require_live_delivery(
                connection, original, self._binding.owner_epoch, operation_time(None)
            )
            retry_saved_preparation = (
                self._step_no in (4, 5)
                and step['status'] == 'SUCCEEDED'
                and self._ref_retry_window is not None
                and original.window['operation_id'] == self._ref_retry_window
                and self._ref_retry_window != operation_id
                and original.delivery['git_write_status'] == 'NOT_DISPATCHED'
                and original.steps[5]['status'] == 'RUNNING'
                and original.steps[5]['external_identity'] is None
            )
            if original.operation['status'] != 'RUNNING' or (
                step['status'] != 'RUNNING' and not retry_saved_preparation
            ):
                raise StorageUnavailable('Original delivery Git dispatch is fenced')
        return step

    def _scope_record(self, command_id):
        identity = f'DELIVERY-CONTROL-GIT:{self._operation_id}:{command_id}'.encode('ascii')
        return sha256(identity).hexdigest()[:32] + '.git.json'

    def _require_preparation(self, original, request, decoded):
        command = self._intent
        metadata = decoded.metadata
        if (
            original != self._original
            or decoded.config_export is None
            or request.input['command_ref'] != command.command_ref
        ):
            raise StorageUnavailable('Original delivery Git command differs')
        if command.command_ref == CONFIG_COMMAND_REF:
            if metadata is not None:
                raise StorageUnavailable('Original delivery Git config command differs')
            return
        if (
            metadata is None
            or metadata.parsed.scope != self._config_scope
            or metadata.kind != REPOSITORY_COMMANDS[command.command_ref]
        ):
            raise StorageUnavailable('Original delivery Git config scope differs')
        actual = (
            metadata.object_intent.digest
            if metadata.object_intent is not None
            else metadata.ref_intent.input_sha256
            if metadata.ref_intent is not None
            else None
        )
        if metadata.ancestry is not None:
            actual = metadata.ancestry.digest
        if (actual, metadata.target_ref) != (command.intent_sha256, command.target_ref):
            raise StorageUnavailable('Original delivery Git fixed input differs')

    def reserve(self, step, command_ref, *, intent_sha256=None, target_ref=None):
        if self._original is not None or command_ref not in _COMMANDS[step]:
            raise StorageUnavailable('Original delivery Git command requires observation')
        self._binding.assert_backend(self._runtime.commands().process_lock)
        self._step_no = step
        intent = DeliveryGitInput(command_ref, intent_sha256, target_ref)
        scope = RepositoryGitScope(
            self._binding.scope(self._operation_id, step, uuid4().hex),
            self._binding.owner_epoch,
            command_ref,
        )
        with self._runtime.database.transaction(write=True) as connection:
            self._active_step(connection, self._operation_id)
            original = load_original_delivery(connection, self._operation_id)
            if (
                command_ref == DELIVERY_OBJECT_COMMAND_REF
                and original.steps[1]['external_identity'] is not None
            ):
                raise StorageUnavailable('Original delivery object recovery is read-only')
            # A read nested inside the prepared ref is the only permitted overlap.
            pending = connection.execute(
                """SELECT id,command_ref FROM code_commands WHERE task_id=?
                   AND status IN ('PENDING','RUNNING','UNKNOWN') ORDER BY id""",
                (original.task['id'],),
            ).fetchall()
            allowed = (
                step == 5
                and len(pending) == 1
                and pending[0]['command_ref'] == DELIVERY_REF_COMMAND_REF
            )
            if pending and not allowed:
                raise StorageUnavailable('Original delivery has an unresolved command')
            command_id = entity_id(connection, EntityKind.COMMAND_EXECUTION)
            connection.execute(
                """INSERT INTO code_commands(id,task_id,operation_id,purpose,command_ref,
                   config_version_id,status,created_at,session_id)
                   VALUES(?,?,?,'CONTROL_GIT',?,?,'PENDING',?,?)""",
                (
                    command_id,
                    original.task['id'],
                    self._operation_id,
                    command_ref,
                    original.task['execution_profile_version_id'],
                    operation_time(None),
                    original.operation['session_id'],
                ),
            )
        self._command_id, self._original, self._intent = command_id, scope, intent
        self._persist_scope(command_id, scope, intent)
        return scope

    def complete(self, exit_code, *, output_verified):
        if self._original is None or self._command_id is None:
            raise StorageUnavailable('Original delivery command completion is missing')
        original = self._original
        self._complete(self._command_id, original, exit_code, output_verified=output_verified)
        if original.command_ref == CONFIG_COMMAND_REF and output_verified:
            self._config_scope = original.scope
        self._command_id = self._original = self._intent = None

    def original_command(self, row):
        if row['operation_id'] != self._operation_id or row['purpose'] != 'CONTROL_GIT':
            raise StorageUnavailable('Original delivery command crosses operation')
        filename = self._scope_record(row['id'])
        identity = self._journal._package.verify_member(filename, directory=False)
        with LockedFileSource(
            self._journal.root / filename, max_file_bytes=16384, expected_file=identity
        ) as source:
            raw = source.verify().raw
        value = strict_json_object(raw)
        if (
            set(value) != {'command_id', 'scope', 'owner_epoch', 'intent'}
            or value['command_id'] != row['id']
            or canonical_input(value).encode() != raw
        ):
            raise StorageUnavailable('Original delivery command record differs')
        scope = LaunchScope(**value['scope'])
        intent = DeliveryGitInput(**value['intent'])
        if (
            scope.operation_id != self._operation_id
            or intent.command_ref != row['command_ref']
            or intent.command_ref not in _COMMANDS.get(scope.step_no, ())
        ):
            raise StorageUnavailable('Original delivery command identity differs')
        return RepositoryGitScope(scope, owner_epoch(value['owner_epoch']), intent.command_ref)

    def _close_unlaunched(self, row, *, status):
        with self._runtime.database.transaction(write=True) as connection:
            if (
                connection.execute(
                    """UPDATE code_commands SET status='CANCELLED',ended_at=?
                   WHERE id=? AND operation_id=? AND status=? AND process_identity IS NULL
                   AND runtime_binding IS NULL AND exit_code IS NULL""",
                    (operation_time(None), row['id'], self._operation_id, status),
                ).rowcount
                != 1
            ):
                raise StorageUnavailable('Original undispatched delivery command changed')

    def recover_original(self, row, *, deadline, cancelled):
        """Only close the original Guard scope. Never reopen input or start Git."""
        if row['status'] == 'PENDING':
            # PENDING never authorizes the Guard's original PREPARE.
            self._close_unlaunched(row, status='PENDING')
            return
        original = self.original_command(row)
        self._step_no, self._original = original.scope.step_no, original
        try:
            actions = RepositoryGitScopeActions(self._runtime, self._binding, self, original)
            actions.use_boundary(deadline, cancelled)
            if actions.cleanup_pending():
                actions.original_preparation(observe=True)
                actions.finish_cleanup()
            stop = self.read_action(original, 'STOP', 'ACKNOWLEDGED')
            if stop is None:
                if self.read_action(original, 'PREPARE', 'MAY_HAVE_BEEN_SENT') is not None:
                    raise StorageUnavailable('Original delivery command stop is missing')
                self._close_unlaunched(row, status=row['status'])
                return
            native = stop['result']['native']
            if native.get('scope_unlaunched') is True:
                self._close_unlaunched(row, status=row['status'])
                return
            evidence = native.get('observation')
            if (
                type(evidence) is not dict
                or evidence.get('state') != 'EXITED'
                or type(evidence.get('exit_code')) is not int
            ):
                raise StorageUnavailable('Original delivery command exit is missing')
            self._complete(row['id'], original, evidence['exit_code'], output_verified=False)
        finally:
            self._original = None

    def close(self):
        if self._original is not None:
            raise StorageUnavailable('Original delivery command requires cleanup')
        super().close()
