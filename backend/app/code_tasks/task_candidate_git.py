"""Original CommandExecution and Guard facts for each fixed package invocation."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import monotonic
from uuid import uuid4

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_bundle import GIT_MANIFEST_SHA256
from backend.app.infrastructure.git_content_command import (
    CONTENT_COMMAND_REF,
    ContentGitIntent,
    hold_content_git_source,
)
from backend.app.infrastructure.guard_control_git_input import content_prepare_input
from backend.app.infrastructure.guard_controller_binding import owner_epoch
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown, LaunchScope
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_pipe_capture import require_complete_output
from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.shared.command_execution import operation_time
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import strict_json_object

from .repository_git_dispatch import RepositoryGitScope, _RepositoryGitDispatch
from .repository_git_runner import RepositoryGitScopeActions, _FixedGitRun
from .task_candidate_commit import capture_task_current, load_candidate_capture
from .task_content_limits import authorized_content_settings

_RECORD_LIMIT = 16384


class CandidateGitDispatch(_RepositoryGitDispatch):
    """Reuse the same original Guard pipe, dispatch log, job and exit checks."""

    _step_no = 2

    def __init__(self, runtime, frames, binding, journal, operation_id, parent, *, cancelled):
        if (
            type(parent) is not PrivatePackageGuard
            or parent.is_control_git_read_package
            or not callable(cancelled)
        ):
            raise TypeError('Original candidate Git parent required')
        super().__init__(runtime, frames, binding, journal, content_parent=parent.verify())
        self._parent, self._operation_id, self._cancelled = parent, operation_id, cancelled
        self._original, self._intent, self._command_id, self._run = None, None, None, None

    def _active_step(self, connection, operation_id, *, allow_unknown=False):
        if operation_id != self._operation_id:
            raise StorageUnavailable('Original candidate Git scope differs')
        prepared, task, operation, steps = load_candidate_capture(connection, operation_id)
        step = steps[1]
        if allow_unknown:
            if step['status'] not in ('RUNNING', 'UNKNOWN', 'SUCCEEDED'):
                raise StorageUnavailable('Original candidate Git cleanup scope differs')
        elif (
            operation['status'] != 'RUNNING'
            or step['status'] != 'RUNNING'
            or not capture_task_current(prepared, task)
        ):
            raise StorageUnavailable('Original candidate Git step is fenced')
        return step

    def _resolve_scope(self, scope, epoch):
        original = self._original
        if original is None or scope != original.scope or epoch != original.owner_epoch:
            raise StorageUnavailable('Original candidate Git command scope differs')
        return original

    def _require_preparation(self, original, request, decoded):
        if (
            request.input['command_ref'] != CONTENT_COMMAND_REF
            or decoded.content is None
            or decoded.content[0] != self._intent
            or original != self._original
            or decoded.content[1]['parent'][0] != self._parent.verify()
        ):
            raise StorageUnavailable('Original candidate Git preparation differs')

    def _package_owner(self, connection):
        prepared, _, _, _ = load_candidate_capture(connection, self._operation_id)
        return prepared.task_id, prepared.session_id, prepared.binding

    def _reserve(self, intent):
        with self._runtime.database.transaction(write=True) as connection:
            self._active_step(connection, self._operation_id)
            task_id, session_id, binding = self._package_owner(connection)
            if (
                intent.content_store_key != binding.content_store_key
                or intent.object_format != binding.object_format
                or connection.execute(
                    """SELECT 1 FROM code_commands WHERE task_id=?
                       AND status IN ('PENDING','RUNNING','UNKNOWN') LIMIT 1""",
                    (task_id,),
                ).fetchone()
            ):
                raise StorageUnavailable('Original candidate Git requires reconciliation')
            command_id = entity_id(connection, EntityKind.COMMAND_EXECUTION)
            connection.execute(
                """INSERT INTO code_commands(id,task_id,operation_id,purpose,command_ref,
                   config_version_id,status,created_at,session_id)
                   VALUES(?,?,?,'CONTROL_GIT',?,?,'PENDING',?,?)""",
                (
                    command_id,
                    task_id,
                    self._operation_id,
                    CONTENT_COMMAND_REF,
                    binding.content_profile_version_id,
                    operation_time(None),
                    session_id,
                ),
            )
        return command_id

    def _scope_record(self, command_id):
        key = sha256(
            f'CANDIDATE-CONTROL-GIT:{self._operation_id}:{command_id}'.encode()
        ).hexdigest()[:32]
        return key + '.git.json'

    def _persist_scope(self, command_id, original, intent):
        raw = canonical_input(
            {
                'command_id': command_id,
                'scope': asdict(original.scope),
                'owner_epoch': original.owner_epoch,
                'intent': asdict(intent),
            }
        ).encode()
        with PrivateRecordAppend(
            self._journal._package,
            self._scope_record(command_id),
            raw,
            max_record_bytes=_RECORD_LIMIT,
        ) as record:
            record.publish()
        with self._runtime.database.transaction(write=True) as connection:
            self._active_step(connection, self._operation_id)
            if (
                connection.execute(
                    """UPDATE code_commands SET status='RUNNING',started_at=?
                   WHERE id=? AND operation_id=? AND status='PENDING'""",
                    (operation_time(None), command_id, self._operation_id),
                ).rowcount
                != 1
            ):
                raise StorageUnavailable('Original candidate Git dispatch claim differs')

    def _complete(self, command_id, original, exit_code, *, output_verified):
        create = self.read_action(original, 'CREATE_SUSPENDED', 'ACKNOWLEDGED')
        release = self.read_action(original, 'RELEASE', 'ACKNOWLEDGED')
        if (
            create is None
            or release is None
            or release['result']['native']['cleanup_verified'] is not True
        ):
            raise StorageUnavailable('Original candidate Git cleanup missing')
        native = create['result']['native']
        process = native['original_process_identity']
        created = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=int(process['creation_time_hex'], 16) // 10,
        )
        identity = {
            'pid': process['pid'],
            'created_at': utc_milliseconds(created),
            'ownership_ref': native['resource_ref'],
        }
        binding = {
            'runtime_policy_version': 'WIN20-ISOLATION-1',
            'run_kind': 'CONTROL_GIT',
            'guard_run_ref': native['guard_run_ref'],
            'appcontainer_profile_ref': None,
            'job_refs': [native['job_ref']],
            'manifest_ref': GIT_MANIFEST_SHA256,
        }
        with self._runtime.database.transaction(write=True) as connection:
            if (
                connection.execute(
                    """UPDATE code_commands SET status=?,exit_code=?,process_identity=?,
                   runtime_binding=?,ended_at=? WHERE id=? AND operation_id=? AND status='RUNNING'""",
                    (
                        'SUCCEEDED' if exit_code == 0 and output_verified else 'FAILED',
                        exit_code,
                        canonical_input(identity),
                        canonical_input(binding),
                        operation_time(None),
                        command_id,
                        self._operation_id,
                    ),
                ).rowcount
                != 1
            ):
                raise StorageUnavailable('Original candidate Git result changed')

    def exchange(self, intent, repo, raw, maximum, remaining):
        self._binding.assert_backend(self._runtime.commands().process_lock)
        if (
            type(intent) is not ContentGitIntent
            or self._run is not None
            or self._original is not None
            or repo != intent.paths(self._parent.path)['repository']
            or self._parent.verify() != self._content_parent
            or self._cancelled()
        ):
            raise LaunchOutcomeUnknown('Original candidate Git input is not current')
        intent.verify_input(raw)
        with self._runtime.database.transaction() as connection:
            self._active_step(connection, self._operation_id)
            task_id, _, binding = self._package_owner(connection)
            limits = authorized_content_settings(
                connection, binding.content_profile_version_id, task_id
            )
        remaining = min(remaining, limits['max_git_seconds'])
        maximum = min(maximum, limits['max_git_output_bytes'])
        command_id = self._reserve(intent)
        original = RepositoryGitScope(
            self._binding.scope(self._operation_id, self._step_no, uuid4().hex),
            self._binding.owner_epoch,
            CONTENT_COMMAND_REF,
        )
        self._command_id, self._original, self._intent = command_id, original, intent
        self._persist_scope(command_id, original, intent)
        run = _FixedGitRun(self._runtime, self._binding, self, original)
        self._run = run
        try:
            with hold_content_git_source(self._parent, intent) as pins:
                output, io_nonce, exit_code = run.run(
                    lambda stdio: content_prepare_input(
                        stdio,
                        intent,
                        pins,
                        expected_parent=self._content_parent,
                    ),
                    deadline=monotonic() + remaining,
                    cancelled=self._cancelled,
                    max_output_bytes=maximum,
                    input_bytes=raw,
                )
            verified = False
            try:
                result = require_complete_output(
                    output,
                    scope=original.scope,
                    io_nonce=io_nonce,
                    exit_code=exit_code,
                    max_output_bytes=maximum,
                )
                verified = True
            finally:
                self._complete(command_id, original, exit_code, output_verified=verified)
                self._command_id, self._original, self._intent, self._run = None, None, None, None
        except BaseException as error:
            # An unacknowledged Git write must be observed, never dispatched again.
            if self._original is not None:
                error.retained_owner = self
            raise
        return result.stdout

    def reconcile_cleanup(self, frames, *, timeout_ms, cancelled):
        """Observe and release the one retained original command; never send its input again."""
        if self._run is None or self._original is None or self._command_id is None:
            raise LaunchOutcomeUnknown('ORIGINAL_CANDIDATE_GIT_RECONCILIATION_REQUIRED')
        run, original, command_id = self._run, self._original, self._command_id
        try:
            run.reconcile_cleanup(frames, timeout_ms=timeout_ms, cancelled=cancelled)
            stopped = self.read_action(original, 'STOP', 'ACKNOWLEDGED')
            observed = None if stopped is None else stopped['result']['native'].get('observation')
            if (
                type(observed) is not dict
                or observed.get('state') != 'EXITED'
                or type(observed.get('exit_code')) is not int
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_CANDIDATE_GIT_EXIT_UNVERIFIED')
            self._complete(command_id, original, observed['exit_code'], output_verified=False)
        except BaseException as error:
            error.retained_owner = self
            raise
        self._command_id, self._original, self._intent, self._run = None, None, None, None

    def recover_released(self, command_id):
        """Recover a released original Job after process output was lost."""
        self._binding.assert_backend(self._runtime.commands().process_lock)
        with self._runtime.database.transaction() as connection:
            step = self._active_step(connection, self._operation_id, allow_unknown=True)
            if step['status'] == 'SUCCEEDED':
                raise StorageUnavailable('Sealed candidate still has an unfinished Git command')
            task_id, session_id, binding = self._package_owner(connection)
            row = connection.execute(
                """SELECT 1 FROM code_commands WHERE id=? AND operation_id=? AND task_id=?
                   AND session_id=? AND purpose='CONTROL_GIT' AND command_ref=?
                   AND config_version_id=? AND status='RUNNING' AND started_at IS NOT NULL
                   AND process_identity IS NULL AND runtime_binding IS NULL
                   AND ended_at IS NULL AND exit_code IS NULL""",
                (
                    command_id,
                    self._operation_id,
                    task_id,
                    session_id,
                    CONTENT_COMMAND_REF,
                    binding.content_profile_version_id,
                ),
            ).fetchone()
            if row is None:
                return False
        name = self._scope_record(command_id)
        identity = self._journal._package.verify_member(name, directory=False)
        try:
            with LockedConfigSource(
                self._journal.root / name, max_file_bytes=_RECORD_LIMIT, expected_file=identity
            ) as source:
                raw = source.verify().raw
                data = strict_json_object(raw)
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if type(retained) is LockedConfigSource:
                self._retained_reads.append(retained)
                error.retained_owner = self
            raise
        if (
            set(data) != {'command_id', 'scope', 'owner_epoch', 'intent'}
            or type(data['command_id']) is not int
            or data['command_id'] != command_id
            or canonical_input(data).encode() != raw
        ):
            raise StorageUnavailable('Original candidate Git journal binding differs')
        try:
            scope = LaunchScope(**data['scope'])
            intent = ContentGitIntent(**data['intent'])
        except (TypeError, ValueError) as error:
            raise StorageUnavailable('Original candidate Git journal input differs') from error
        if (
            scope.operation_id != self._operation_id
            or scope.step_no != self._step_no
            or intent.content_store_key != binding.content_store_key
            or intent.object_format != binding.object_format
        ):
            raise StorageUnavailable('Original candidate Git journal scope differs')
        original = RepositoryGitScope(scope, owner_epoch(data['owner_epoch']), CONTENT_COMMAND_REF)
        release = self.read_action(original, 'RELEASE', 'ACKNOWLEDGED')
        if release is None:
            return False
        actions = RepositoryGitScopeActions(self._runtime, self._binding, self, original)
        if actions.cleanup_pending():
            return False
        created = self.read_action(original, 'CREATE_SUSPENDED', 'ACKNOWLEDGED')
        create_intent = self.read_action(original, 'CREATE_SUSPENDED', 'MAY_HAVE_BEEN_SENT')
        stopped = self.read_action(original, 'STOP', 'ACKNOWLEDGED')
        stop_intent = self.read_action(original, 'STOP', 'MAY_HAVE_BEEN_SENT')
        actions._verify_cleanup_ack('STOP', stop_intent, stopped)
        if (
            created is None
            or create_intent is None
            or created['input_sha256'] != create_intent['input_sha256']
            or created['result']['binding_ref'] != stopped['result']['binding_ref']
        ):
            raise StorageUnavailable('Original candidate Git creation is unverified')
        native = created['result']['native']
        final = stopped['result']['native']
        observed = final.get('observation')
        if (
            type(observed) is not dict
            or observed.get('state') != 'EXITED'
            or type(observed.get('exit_code')) is not int
            or any(
                final.get(key) != native[key]
                for key in ('original_process_identity', 'resource_ref', 'guard_run_ref', 'job_ref')
            )
        ):
            raise StorageUnavailable('Original candidate Git exit is unverified')
        self._complete(command_id, original, observed['exit_code'], output_verified=False)
        return True

    def close(self):
        if self._run is not None:
            self._run.close()
        if self._original is not None:
            raise LaunchOutcomeUnknown('ORIGINAL_CANDIDATE_GIT_REQUIRES_OBSERVATION')
        super().close()
