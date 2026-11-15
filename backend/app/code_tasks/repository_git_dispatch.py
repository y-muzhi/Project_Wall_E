"""Original repository scopes and immutable private Guard dispatch evidence."""

import hashlib
import re
from abc import ABC, abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from uuid import uuid4

from backend.app.infrastructure.content_manifest import git_oid
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_config_command import ParsedRepositoryConfig
from backend.app.infrastructure.git_metadata_command import decode_metadata_output
from backend.app.infrastructure.git_object_batch import BatchCompletion
from backend.app.infrastructure.git_repository_location import RepositoryLocationLease
from backend.app.infrastructure.git_repository_metadata import RepositoryMetadataLease
from backend.app.infrastructure.guard_action_records import MUTATIONS, mutation_input_sha256
from backend.app.infrastructure.guard_control_git_input import (
    CONFIG_COMMAND_REF,
    METADATA_COMMANDS,
    OBJECT_BATCH_COMMAND_REF,
    PrepareControlGit,
    decode_control_git_action,
)
from backend.app.infrastructure.guard_control_git_reply import GuardReply
from backend.app.infrastructure.guard_control_git_transport import (
    GuardExchangeUnknown,
    _endpoint,
    exchange_guard_control_git,
)
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding, owner_epoch
from backend.app.infrastructure.guard_request_header import GuardRequestHeader, _parse
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchScope
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_guard_pipe import GuardPipeClient
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadLease
from backend.app.shared.command_execution import operation_time
from backend.app.shared.validation import strict_integer, strict_json_object

from .configuration_identities import require_schema
from .repository_baseline_validation import BaselineValidationProof, original_baseline
from .repository_observation_publish import (
    _original as _original_observation,
)
from .repository_observation_publish import (
    capture_repository_observation,
    publish_repository_observation,
)
from .repository_registration import (
    _original,
    capture_repository_registration,
    publish_repository_registration,
)

OBSERVATION_COMMANDS = (CONFIG_COMMAND_REF, *METADATA_COMMANDS)
PREDECESSORS = {
    'CREATE_SUSPENDED': 'PREPARE',
    'RESUME': 'CREATE_SUSPENDED',
    'RELEASE': 'STOP',
}
MAX_RECORD_BYTES = 32768
VALIDATION_FAILURES = frozenset(
    {
        'SOURCE_BUSY',
        'SOURCE_CHANGED',
        'SOURCE_UNSUPPORTED',
        'REPOSITORY_UNSUPPORTED',
    }
)


@dataclass(frozen=True)
class RepositoryGitScope:
    scope: LaunchScope
    owner_epoch: str
    command_ref: str = CONFIG_COMMAND_REF


def _registration_active(connection, operation_id, *, allow_unknown=False):
    operation, _, steps = _original(connection, operation_id)
    states = ('RUNNING', 'UNKNOWN') if allow_unknown else ('RUNNING',)
    if operation['status'] not in states or steps[0]['status'] not in states:
        raise StorageUnavailable('Original registration VALIDATE step is not active')
    return steps[0]


def mark_repository_read_unknown(connection, operation, step):
    if operation['status'] == 'RUNNING' and step['status'] == 'RUNNING':
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operations SET status='UNKNOWN',failure_code='EXTERNAL_RESULT_UNKNOWN' WHERE id=?",
            (operation['id'],),
        )
        connection.execute(
            "UPDATE code_operation_steps SET status='UNKNOWN',last_observed_at=? WHERE operation_id=? AND step_no=?",
            (at, operation['id'], step['step_no']),
        )


class _RepositoryGitDispatch(ABC):
    def __init__(self, runtime, frames, binding, journal, *, content_parent=None):
        require_schema(runtime)
        if type(binding) is not GuardControllerBinding or type(journal) is not LaunchJournal:
            raise TypeError('Original backend binding and private journal required')
        binding.assert_backend(runtime.commands().process_lock)
        journal._verify()
        self._runtime, self._frames = runtime, frames
        self._binding, self._journal = binding, journal
        self._pending, self._retained_reads = [], []
        self._content_parent = content_parent

    def reconnect(self, frames):
        self._binding.assert_backend(self._runtime.commands().process_lock)
        _endpoint(frames, GuardPipeClient, self._binding.installation_ref)
        self._frames = frames

    @abstractmethod
    def _active_step(self, connection, operation_id, *, allow_unknown=False):
        """Read this kind of original active step."""

    @abstractmethod
    def _resolve_scope(self, scope, epoch):
        """Resolve the requested scope against the saved original operation."""

    @abstractmethod
    def _require_preparation(self, original, request, decoded):
        """Check the operation-specific command and predecessors."""

    def _path(self, original, action, status):
        if (
            type(original) is not RepositoryGitScope
            or action not in MUTATIONS
            or status not in ('MAY_HAVE_BEEN_SENT', 'ACKNOWLEDGED')
        ):
            raise TypeError('Original repository Guard action required')
        key = compact(
            {
                'scope': asdict(original.scope),
                'owner_epoch': original.owner_epoch,
                'action': action,
                'status': status,
            }
        ).encode('utf-8')
        return self._journal.root / (hashlib.sha256(key).hexdigest()[:32] + '.git.json')

    def read_action(self, original, action, status):
        path = self._path(original, action, status)
        with self._journal._scope(original.scope), self._journal._gate:
            self._journal._verify()
            try:
                path.lstat()
            except FileNotFoundError:
                return None
            identity = self._journal._package.verify_member(path.name, directory=False)
            try:
                with LockedConfigSource(
                    path, max_file_bytes=MAX_RECORD_BYTES, expected_file=identity
                ) as held:
                    snapshot = held.verify()
                    value = strict_json_object(snapshot.raw)
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if type(retained) is LockedConfigSource:
                    self._retained_reads.append(retained)
                    error.retained_owner = self
                raise
            if (
                set(value)
                != {'kind', 'scope', 'owner_epoch', 'action', 'status', 'input_sha256', 'result'}
                or value['kind'] != 'GIT_LAUNCH_ACTION'
                or value['scope'] != asdict(original.scope)
                or value['owner_epoch'] != original.owner_epoch
                or value['action'] != action
                or value['status'] != status
                or type(value['input_sha256']) is not str
                or re.fullmatch('[0-9a-f]{64}', value['input_sha256']) is None
                or status == 'MAY_HAVE_BEEN_SENT'
                and value['result'] is not None
                or status == 'ACKNOWLEDGED'
                and type(value['result']) is not dict
                or compact(value).encode('utf-8') != snapshot.raw
            ):
                raise StorageUnavailable('Original repository Guard evidence differs')
            return value

    def _append(self, original, action, digest, status, result):
        if self._pending or self._retained_reads:
            raise StorageUnavailable('Original repository Guard evidence requires observation')
        path = self._path(original, action, status)
        raw = compact(
            {
                'kind': 'GIT_LAUNCH_ACTION',
                'scope': asdict(original.scope),
                'owner_epoch': original.owner_epoch,
                'action': action,
                'status': status,
                'input_sha256': digest,
                'result': result,
            }
        ).encode('utf-8')
        with self._journal._scope(original.scope), self._journal._gate:
            if self.read_action(original, action, status) is not None:
                raise StorageUnavailable('Original repository Guard action requires observation')
            writer = None
            try:
                writer = PrivateRecordAppend(
                    self._journal._package, path.name, raw, max_record_bytes=MAX_RECORD_BYTES
                )
                self._pending.append(writer)
                writer.publish()
                writer.close()
                self.read_action(original, action, status)
                self._pending.remove(writer)
            except BaseException as error:
                retained = getattr(error, 'retained_owner', None)
                if writer is None and type(retained) is PrivateRecordAppend:
                    self._pending.append(retained)
                error.retained_owner = self
                raise

    def _before(self, request, original):
        action = request.action
        with self._journal._scope(original.scope), self._journal._gate:
            with self._runtime.database.transaction() as connection:
                self._active_step(
                    connection,
                    request.scope.operation_id,
                    allow_unknown=action in ('STOP', 'RELEASE'),
                )
            if self.read_action(original, action, 'MAY_HAVE_BEEN_SENT') is not None:
                raise StorageUnavailable('Original repository Guard action requires observation')
            predecessor = PREDECESSORS.get(action)
            previous = (
                None
                if predecessor is None
                else self.read_action(original, predecessor, 'ACKNOWLEDGED')
            )
            if predecessor is not None and previous is None:
                raise StorageUnavailable('Original repository Guard prerequisite is unverified')
            prepared = self.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
            if request.binding_ref is not None and (
                prepared is None or request.binding_ref != prepared['result']['binding_ref']
            ):
                raise StorageUnavailable('Original repository Guard resource differs')
            if (
                action in ('CREATE_SUSPENDED', 'RESUME')
                and self.read_action(original, 'STOP', 'MAY_HAVE_BEEN_SENT') is not None
            ):
                raise StorageUnavailable('Original repository Guard scope is closing')
            if (
                action == 'STOP'
                and self.read_action(original, 'PREPARE', 'MAY_HAVE_BEEN_SENT') is None
            ):
                raise StorageUnavailable('Original repository has no possibly sent Guard action')
            self._append(
                original, request.action, mutation_input_sha256(request), 'MAY_HAVE_BEEN_SENT', None
            )
        return original

    def _check_ack(self, original, request, result):
        if type(result) is not dict:
            raise StorageUnavailable('Original repository Guard result is unverified')
        if request.action == 'PREPARE':
            if any(
                type(result.get(field)) is not str
                or re.fullmatch('[0-9a-f]{32}', result[field]) is None
                for field in ('binding_ref', 'guard_run_ref')
            ):
                raise StorageUnavailable('Original repository Guard preparation is unverified')
            return
        prepared = self.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
        native = result.get('native')
        if type(native) is not dict or result.get('binding_ref') != request.binding_ref:
            raise StorageUnavailable('Original repository Guard result binding differs')
        if request.action in ('CREATE_SUSPENDED', 'RESUME'):
            identity = native.get('original_process_identity')
            if (
                prepared is None
                or native.get('guard_run_ref') != prepared['result']['guard_run_ref']
                or native.get('job_ref') != prepared['result']['binding_ref']
                or type(identity) is not dict
                or type(identity.get('pid')) is not int
                or not 1 <= identity['pid'] <= 0xFFFFFFFF
                or type(identity.get('creation_time_hex')) is not str
                or re.fullmatch('[0-9a-f]{16}', identity['creation_time_hex']) is None
                or int(identity['creation_time_hex'], 16) == 0
                or type(native.get('resource_ref')) is not str
                or re.fullmatch('[0-9a-f]{32}', native['resource_ref']) is None
            ):
                raise StorageUnavailable('Original repository Guard process is unverified')
            fence = native.get('fence', {})
            if request.action == 'CREATE_SUSPENDED':
                if (
                    fence.get('create_state') != 'RESOURCE_RECORDED'
                    or fence.get('resume_state') != 'NONE'
                ):
                    raise StorageUnavailable(
                        'Original repository Guard suspended creation is unverified'
                    )
            else:
                created = self.read_action(original, 'CREATE_SUSPENDED', 'ACKNOWLEDGED')
                actual = created['result']['native']
                if (
                    identity != actual.get('original_process_identity')
                    or native['resource_ref'] != actual.get('resource_ref')
                    or fence.get('resume_state') != 'ACKNOWLEDGED'
                ):
                    raise StorageUnavailable('Original repository Guard resumed process differs')
        if request.action == 'STOP' and native.get('fence', {}).get('stop_closed') is not True:
            raise StorageUnavailable('Original repository Guard stop is unverified')
        if request.action == 'RELEASE' and native.get('cleanup_verified') is not True:
            raise StorageUnavailable('Original repository Guard cleanup is unverified')

    def dispatch(self, request, *, timeout_ms, cancelled):
        lock = self._runtime.commands().process_lock
        self._binding.assert_backend(lock)
        if (
            type(request) is not GuardRequestHeader
            or request.action not in MUTATIONS
            or request.recovery is not None
            and request.action not in ('STOP', 'RELEASE')
            or _parse(request.wire, self._binding) != request
        ):
            raise TypeError('Original repository Guard mutation required')
        decoded = decode_control_git_action(
            request, self._binding, content_parent=self._content_parent
        )
        epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
        original = self._resolve_scope(request.target_scope, epoch)
        if type(decoded) is PrepareControlGit:
            self._require_preparation(original, request, decoded)
        self._before(request, original)
        reply = exchange_guard_control_git(
            self._frames,
            self._binding,
            lock,
            request,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
            content_parent=self._content_parent,
        )
        if type(reply) is not GuardReply or reply.status != 'ACKNOWLEDGED':
            raise GuardExchangeUnknown(request)
        self._check_ack(original, request, reply.result)
        self._append(
            original, request.action, mutation_input_sha256(request), 'ACKNOWLEDGED', reply.result
        )
        return reply

    def observe(self, request, *, timeout_ms, cancelled):
        lock = self._runtime.commands().process_lock
        self._binding.assert_backend(lock)
        if (
            type(request) is not GuardRequestHeader
            or request.action != 'OBSERVE'
            or _parse(request.wire, self._binding) != request
        ):
            raise TypeError('Original repository Guard observation required')
        decode_control_git_action(request, self._binding)
        epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
        original = self._resolve_scope(request.target_scope, epoch)
        action = request.input['observed_action']
        intent = self.read_action(original, action, 'MAY_HAVE_BEEN_SENT')
        if intent is None:
            raise StorageUnavailable('Original repository Guard intent is missing')
        reply = exchange_guard_control_git(
            self._frames,
            self._binding,
            lock,
            request,
            timeout_ms=timeout_ms,
            cancelled=cancelled,
        )
        if type(reply) is not GuardReply or reply.status != 'OBSERVED':
            raise GuardExchangeUnknown(request)
        observed = reply.result
        if observed['input_sha256'] != intent['input_sha256']:
            raise StorageUnavailable('Original repository Guard observed input differs')
        if observed['action_phase'] == 'ACKNOWLEDGED':
            acknowledged = self.read_action(original, action, 'ACKNOWLEDGED')
            result = observed['acknowledgement']
            if acknowledged is None:
                self._append(original, action, intent['input_sha256'], 'ACKNOWLEDGED', result)
            elif acknowledged['result'] != result:
                raise StorageUnavailable(
                    'Original repository Guard observed acknowledgement differs'
                )
        return reply

    @contextmanager
    def _validation_cleanup(self, originals, code, *, allowed=VALIDATION_FAILURES):
        if code not in allowed:
            raise ValueError('Known original validation failure required')
        if self._pending or self._retained_reads:
            raise StorageUnavailable('Original repository evidence remains unverified')
        with ExitStack() as locks:
            for original in originals:
                locks.enter_context(self._journal._scope(original.scope))
                prepare = self.read_action(original, 'PREPARE', 'MAY_HAVE_BEEN_SENT')
                if prepare is not None:
                    release = self.read_action(original, 'RELEASE', 'ACKNOWLEDGED')
                    native = None if release is None else release['result'].get('native')
                    if type(native) is not dict or native.get('cleanup_verified') is not True:
                        raise StorageUnavailable('Original repository cleanup remains unverified')
            yield

    @staticmethod
    def _finish_validation_failure(connection, operation_id, code):
        at = operation_time(None)
        connection.execute(
            "UPDATE code_operation_steps SET status='FAILED',ended_at=?,last_observed_at=? "
            'WHERE operation_id=? AND step_no=1',
            (at, at, operation_id),
        )
        connection.execute(
            "UPDATE code_operations SET status='FAILED',ended_at=?,failure_code=? WHERE id=?",
            (at, code, operation_id),
        )

    def close(self):
        for source in tuple(self._retained_reads):
            source.close()
            self._retained_reads.remove(source)
        for writer in self._pending:
            writer.close()
        # Unresolved original publication still requires observation, never dispatch.


class RegistrationGitDispatch(_RepositoryGitDispatch):
    _active_step = staticmethod(_registration_active)

    def _resolve_scope(self, scope, epoch):
        original = self.original(scope.operation_id)
        if original != RepositoryGitScope(scope, epoch):
            raise StorageUnavailable('Original registration Guard scope differs')
        return original

    def _require_preparation(self, original, request, decoded):
        if decoded.config_export is None or decoded.metadata is not None:
            raise StorageUnavailable('Original registration requires fixed config parsing')

    def reserve(self, operation_id):
        strict_integer(operation_id, 'operation_id')
        self._binding.assert_backend(self._runtime.commands().process_lock)
        root = self._journal._package.verify()
        with self._runtime.database.transaction(write=True) as connection:
            step = self._active_step(connection, operation_id)
            if step['external_identity'] is not None:
                raise StorageUnavailable('Original registration Guard scope requires observation')
            scope = self._binding.scope(operation_id, 1, uuid4().hex)
            value = {
                'git_launch': {
                    'command_ref': CONFIG_COMMAND_REF,
                    'controller_ref': scope.controller_ref,
                    'owner_epoch': self._binding.owner_epoch,
                    'nonce': scope.nonce,
                    'journal_root': asdict(root),
                }
            }
            connection.execute(
                'UPDATE code_operation_steps SET external_identity=?,last_observed_at=? '
                'WHERE operation_id=? AND step_no=1',
                (compact(value), operation_time(None), operation_id),
            )
        return RepositoryGitScope(scope, self._binding.owner_epoch)

    def original(self, operation_id):
        strict_integer(operation_id, 'operation_id')
        with self._runtime.database.transaction() as connection:
            step = self._active_step(connection, operation_id, allow_unknown=True)
            if step['external_identity'] is None:
                raise StorageUnavailable('Original registration Guard scope is missing')
            external = strict_json_object(step['external_identity'])
        if set(external) != {'git_launch'}:
            raise StorageUnavailable('Original registration Guard identity differs')
        value = external['git_launch']
        if (
            type(value) is not dict
            or set(value)
            != {'command_ref', 'controller_ref', 'owner_epoch', 'nonce', 'journal_root'}
            or value['command_ref'] != CONFIG_COMMAND_REF
            or value['journal_root'] != asdict(self._journal._package.verify())
        ):
            raise StorageUnavailable('Original registration Guard scope differs')
        return RepositoryGitScope(
            LaunchScope(value['controller_ref'], operation_id, 1, value['nonce']),
            owner_epoch(value['owner_epoch']),
        )

    def fail_validation(self, operation_id, code):
        with (
            self._validation_cleanup((self.original(operation_id),), code),
            self._runtime.database.transaction(write=True) as connection,
        ):
            operation, _, steps = _original(connection, operation_id)
            if (
                operation['status'] != 'RUNNING'
                or steps[0]['status'] != 'RUNNING'
                or steps[1]['status'] != 'PENDING'
                or any(row['result_ref'] is not None for row in steps)
                or connection.execute(
                    'SELECT 1 FROM code_repositories WHERE id=?', (operation['resource_id'],)
                ).fetchone()
                is not None
            ):
                raise StorageUnavailable('Original registration cannot record validation failure')
            self._finish_validation_failure(connection, operation_id, code)

    def publish_registration(
        self,
        operation_id,
        location,
        parsed,
        *,
        max_entries,
        max_open_handles,
        max_file_bytes,
        max_metadata_bytes,
    ):
        if (
            type(location) is not RepositoryLocationLease
            or type(parsed) is not ParsedRepositoryConfig
        ):
            raise TypeError('Original location and parsed config required')
        original = self.original(operation_id)
        prepared = self.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
        released = self.read_action(original, 'RELEASE', 'ACKNOWLEDGED')
        if (
            prepared is None
            or released is None
            or released['result'].get('native', {}).get('cleanup_verified') is not True
            or parsed.scope != original.scope
        ):
            raise StorageUnavailable(
                'Original registration Git validation or cleanup is unverified'
            )
        source = location.verify()
        copied = prepared['result'].get('config_export')
        if (
            copied
            != {
                'file': asdict(parsed.source_file),
                'sha256': parsed.source_sha256,
                'byte_count': location.config_source.verify().byte_count,
            }
            or parsed.source_file != source.config
            or parsed.source_sha256 != source.config_sha256
        ):
            raise StorageUnavailable('Original registration config source differs')
        with RepositoryMetadataLease(
            location,
            format=parsed.local.object_format,
            max_entries=max_entries,
            max_open_handles=max_open_handles,
            max_file_bytes=max_file_bytes,
            max_metadata_bytes=max_metadata_bytes,
        ) as metadata:
            capture = capture_repository_registration(metadata)
            result = publish_repository_registration(self._runtime, operation_id, capture)
            metadata.verify()
            return result


class _RepositoryReadDispatch(_RepositoryGitDispatch):
    """Persist one ordered set of original read scopes for a repository step."""

    _step_no = 1

    def reserve(self, operation_id):
        strict_integer(operation_id, 'operation_id')
        self._binding.assert_backend(self._runtime.commands().process_lock)
        root = self._journal._package.verify()
        scopes = tuple(
            RepositoryGitScope(
                self._binding.scope(operation_id, self._step_no, uuid4().hex),
                self._binding.owner_epoch,
                command,
            )
            for command in self._commands
        )
        with self._runtime.database.transaction(write=True) as connection:
            step = self._active_step(connection, operation_id)
            if step['external_identity'] is not None:
                raise StorageUnavailable('Original repository read Git scopes require observation')
            value = {
                self._external_key: {
                    'controller_ref': self._binding.controller_ref,
                    'owner_epoch': self._binding.owner_epoch,
                    'journal_root': asdict(root),
                    'commands': [
                        {'command_ref': entry.command_ref, 'nonce': entry.scope.nonce}
                        for entry in scopes
                    ],
                }
            }
            connection.execute(
                'UPDATE code_operation_steps SET external_identity=?,last_observed_at=? '
                'WHERE operation_id=? AND step_no=?',
                (compact(value), operation_time(None), operation_id, self._step_no),
            )
        return scopes

    def original(self, operation_id):
        strict_integer(operation_id, 'operation_id')
        with self._runtime.database.transaction() as connection:
            step = self._active_step(connection, operation_id, allow_unknown=True)
            if step['external_identity'] is None:
                raise StorageUnavailable('Original repository read Git scopes are missing')
            external = strict_json_object(step['external_identity'])
        if set(external) != {self._external_key}:
            raise StorageUnavailable('Original repository read Git identity differs')
        value = external[self._external_key]
        if (
            type(value) is not dict
            or set(value) != {'controller_ref', 'owner_epoch', 'journal_root', 'commands'}
            or value['journal_root'] != asdict(self._journal._package.verify())
            or type(value['commands']) is not list
            or len(value['commands']) != len(self._commands)
        ):
            raise StorageUnavailable('Original repository read Git scopes differ')
        epoch = owner_epoch(value['owner_epoch'])
        scopes = []
        for entry, command in zip(value['commands'], self._commands, strict=True):
            if (
                type(entry) is not dict
                or set(entry) != {'command_ref', 'nonce'}
                or entry['command_ref'] != command
            ):
                raise StorageUnavailable('Original repository read Git command differs')
            scope = LaunchScope(
                value['controller_ref'], operation_id, self._step_no, entry['nonce']
            )
            scopes.append(RepositoryGitScope(scope, epoch, command))
        if len({item.scope.nonce for item in scopes}) != len(scopes):
            raise StorageUnavailable('Original repository read Git scopes must be distinct')
        return tuple(scopes)

    def _resolve_scope(self, scope, epoch):
        for original in self.original(scope.operation_id):
            if original.scope == scope and original.owner_epoch == epoch:
                return original
        raise StorageUnavailable('Original observation Guard scope differs')

    def _require_preparation(self, original, request, decoded):
        if decoded.config_export is None or request.input['command_ref'] != original.command_ref:
            raise StorageUnavailable('Original repository read fixed Git command differs')
        plan = self.original(original.scope.operation_id)
        index = plan.index(original)
        if index == 0:
            return
        if decoded.metadata is None or decoded.metadata.parsed.scope != plan[0].scope:
            raise StorageUnavailable('Original repository read config scope differs')
        release = self.read_action(plan[index - 1], 'RELEASE', 'ACKNOWLEDGED')
        if (
            release is None
            or release['result'].get('native', {}).get('cleanup_verified') is not True
        ):
            raise StorageUnavailable('Original repository read previous Git cleanup is unverified')

    def _completed_query(self, original, *, require_zero_exit=True):
        prepare = self.read_action(original, 'PREPARE', 'ACKNOWLEDGED')
        stop = self.read_action(original, 'STOP', 'ACKNOWLEDGED')
        release = self.read_action(original, 'RELEASE', 'ACKNOWLEDGED')
        if prepare is None or stop is None or release is None:
            raise StorageUnavailable('Original repository read Git result or cleanup is unverified')
        prepared = prepare['result']
        stopped = stop['result'].get('native', {})
        observation = stopped.get('observation')
        fence = stopped.get('fence', {})
        reference = prepared['binding_ref']
        if (
            stop['result'].get('binding_ref') != reference
            or release['result'].get('binding_ref') != reference
            or fence.get('stop_closed') is not True
            or fence.get('resume_state') != 'ACKNOWLEDGED'
            or type(observation) is not dict
            or observation.get('state') != 'EXITED'
            or type(observation.get('exit_code')) is not int
            or require_zero_exit
            and observation['exit_code'] != 0
            or release['result'].get('native', {}).get('cleanup_verified') is not True
        ):
            raise StorageUnavailable('Original repository read Git exit or cleanup differs')
        return prepared


class ObservationGitDispatch(_RepositoryReadDispatch):
    """Three ordered fixed commands on one original READ_REPOSITORY step."""

    _commands = OBSERVATION_COMMANDS
    _external_key = 'git_observation'

    @staticmethod
    def _active_step(connection, operation_id, *, allow_unknown=False):
        operation, steps = _original_observation(connection, operation_id)
        states = ('RUNNING', 'UNKNOWN') if allow_unknown else ('RUNNING',)
        if (
            operation['status'] not in states
            or steps[0]['status'] not in states
            or steps[1]['status'] != 'PENDING'
        ):
            raise StorageUnavailable('Original observation READ_REPOSITORY step is not active')
        return steps[0]

    def fail_validation(self, operation_id, code):
        with (
            self._validation_cleanup(self.original(operation_id), code),
            self._runtime.database.transaction(write=True) as connection,
        ):
            self._active_step(connection, operation_id)
            _, steps = _original_observation(connection, operation_id)
            if (
                any(step['result_ref'] is not None for step in steps)
                or connection.execute(
                    'SELECT 1 FROM code_repository_observations WHERE operation_id=?',
                    (operation_id,),
                ).fetchone()
                is not None
            ):
                raise StorageUnavailable('Original observation cannot record validation failure')
            self._finish_validation_failure(connection, operation_id, code)

    def publish_observation(
        self,
        operation_id,
        metadata,
        parsed,
        *,
        worktrees_output,
        branches_output,
        private_roots,
        max_file_bytes,
        max_open_handles,
        max_output_bytes,
    ):
        if (
            type(metadata) is not RepositoryMetadataLease
            or type(parsed) is not ParsedRepositoryConfig
        ):
            raise TypeError('Original observation metadata and parsed config required')
        self._binding.assert_backend(self._runtime.commands().process_lock)
        if self._pending or self._retained_reads:
            raise StorageUnavailable('Original observation Git evidence remains unverified')
        config, worktrees, branches = self.original(operation_id)
        with self._runtime.database.transaction() as connection:
            identity = self._active_step(connection, operation_id)['external_identity']
        prepared_config = self._completed_query(config)
        source = metadata.location.verify()
        snapshot = metadata.verify()
        if (
            parsed.scope != config.scope
            or parsed.io_nonce != prepared_config['stdio_binding']['io_nonce']
            or parsed.source_file != source.config
            or parsed.source_sha256 != source.config_sha256
            or parsed.local.object_format != snapshot.object_format
            or prepared_config.get('config_export')
            != {
                'file': asdict(source.config),
                'sha256': source.config_sha256,
                'byte_count': metadata.location.config_source.verify().byte_count,
            }
        ):
            raise StorageUnavailable('Original observation config proof differs')

        def read(original, kind, output):
            prepared = self._completed_query(original)
            if prepared.get('metadata_source') != {
                'command_ref': original.command_ref,
                'location_sha256': source.fingerprint_sha256,
                'metadata_sha256': snapshot.fingerprint_sha256,
                'config_nonce': config.scope.nonce,
                'config_output_sha256': parsed.local.output_sha256,
            }:
                raise StorageUnavailable('Original observation metadata proof differs')
            return decode_metadata_output(
                metadata,
                kind,
                output,
                scope=original.scope,
                io_nonce=prepared['stdio_binding']['io_nonce'],
                exit_code=0,
                max_output_bytes=max_output_bytes,
            )

        with metadata.hold():
            worktree_listing = read(worktrees, 'WORKTREES', worktrees_output)
            local_branches = read(branches, 'LOCAL_BRANCHES', branches_output)
            with WorktreeHeadLease(
                worktree_listing,
                local_branches,
                common_directory=source.common_directory.canonical_path,
                private_roots=private_roots,
                max_file_bytes=max_file_bytes,
                max_open_handles=max_open_handles,
            ) as heads:
                capture = capture_repository_observation(metadata, heads)
                return publish_repository_observation(
                    self._runtime, operation_id, capture, original_read_identity=identity
                )


class BaselineGitDispatch(_RepositoryReadDispatch):
    """Only VALIDATE_COMMIT may start this fixed read scope pair."""

    _commands = (CONFIG_COMMAND_REF, OBJECT_BATCH_COMMAND_REF)
    _external_key = 'git_baseline_validation'

    @staticmethod
    def _active_step(connection, operation_id, *, allow_unknown=False):
        operation, _, steps = original_baseline(connection, operation_id)
        expected = ('RUNNING', 'UNKNOWN') if allow_unknown else ('RUNNING',)
        if (
            operation['status'] not in expected
            or steps[0]['status'] != operation['status']
            or any(step['status'] != 'PENDING' for step in steps[1:])
        ):
            raise StorageUnavailable('Original baseline VALIDATE_COMMIT is not active')
        return steps[0]

    def fail_validation(self, operation_id, code):
        with (
            self._validation_cleanup(
                self.original(operation_id),
                code,
                allowed=VALIDATION_FAILURES | {'CONTENT_NOT_READY'},
            ),
            self._runtime.database.transaction(write=True) as connection,
        ):
            step = self._active_step(connection, operation_id)
            if step['result_ref'] is not None:
                raise StorageUnavailable('Original baseline validation already has a result')
            self._finish_validation_failure(connection, operation_id, code)

    def _verify_completed_batch(self, operation_id, source, metadata, parsed, proof, batch_output):
        self._binding.assert_backend(self._runtime.commands().process_lock)
        if (
            self._pending
            or self._retained_reads
            or type(proof) is not BaselineValidationProof
            or type(batch_output) is not BatchCompletion
        ):
            raise StorageUnavailable('Original baseline validation evidence is unverified')
        original = self.original(operation_id)
        config, batch = original[0], original[-1]
        prepared_config = self._completed_query(config)
        prepared_batch = self._completed_query(batch)
        location = metadata.location.verify()
        snapshot = metadata.verify()
        if (
            parsed.scope != config.scope
            or parsed.io_nonce != prepared_config['stdio_binding']['io_nonce']
            or parsed.source_file != location.config
            or parsed.source_sha256 != location.config_sha256
            or parsed.local.object_format != source.format
            or source.root != location.root.canonical_path
            or source.common_directory != location.common_directory.canonical_path
            or prepared_config.get('config_export')
            != {
                'file': asdict(location.config),
                'sha256': location.config_sha256,
                'byte_count': metadata.location.config_source.verify().byte_count,
            }
            or batch_output.scope != batch.scope
            or batch_output.io_nonce != prepared_batch['stdio_binding']['io_nonce']
            or batch_output.request_count < 2
            or not 1 <= batch_output.output_bytes <= source.output_budget
            or proof.repository_sha256 != snapshot.fingerprint_sha256
            or proof.commit_oid != source.commit_oid
            or prepared_batch.get('metadata_source')
            != {
                'command_ref': batch.command_ref,
                'location_sha256': location.fingerprint_sha256,
                'metadata_sha256': snapshot.fingerprint_sha256,
                'config_nonce': config.scope.nonce,
                'config_output_sha256': parsed.local.output_sha256,
            }
        ):
            raise StorageUnavailable('Original baseline validation source differs')
        git_oid(proof.tree_oid, source.format)
        for digest in (proof.repository_sha256, proof.closure_sha256, proof.content_sha256):
            if type(digest) is not str or re.fullmatch('[0-9a-f]{64}', digest) is None:
                raise StorageUnavailable('Original baseline validation digest differs')

    def complete_validation(self, operation_id, source, metadata, parsed, proof, batch_output):
        self._verify_completed_batch(operation_id, source, metadata, parsed, proof, batch_output)
        with self._runtime.database.transaction(write=True) as connection:
            step = self._active_step(connection, operation_id)
            _, fixed, _ = original_baseline(connection, operation_id)
            if step['result_ref'] is not None or (
                fixed['repository_id'],
                fixed['commit_oid'],
                fixed['execution_profile_version_id'],
            ) != (source.repository_id, source.commit_oid, source.profile_version_id):
                raise StorageUnavailable('Original baseline validation input differs')
            at = operation_time(None)
            connection.execute(
                "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=? "
                'WHERE operation_id=? AND step_no=1',
                (compact(asdict(proof)), at, at, operation_id),
            )
        return proof
