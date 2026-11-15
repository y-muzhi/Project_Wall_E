"""Private Guard scopes for read-only queries of completed baseline registrations."""

import hashlib
import re
from dataclasses import asdict, dataclass, field
from uuid import uuid4

from backend.app.infrastructure.content_manifest import ContentEntry
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_private_record import PrivateRecordAppend
from backend.app.shared.validation import InvalidInput, strict_integer, strict_json_object

from .configuration_identities import require_schema
from .repository_baseline_validation import (
    _source,
    baseline_pinned_ref,
    baseline_proof,
    original_baseline,
    read_registered_baseline,
)
from .repository_git_dispatch import BaselineGitDispatch

_PLAN_NAME = re.compile(r'([a-f0-9]{32})\.snapshot-query\.json')
_MAX_QUERY_RECORDS = 100000
_MAX_QUERY_BYTES = 4096


class BaselineSnapshotMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class BaselineQueryResult:
    snapshot: dict = field(repr=False)
    entries: tuple[ContentEntry, ...] = field(repr=False)


def load_baseline_query(runtime, snapshot_id):
    require_schema(runtime)
    strict_integer(snapshot_id, 'snapshot_id')
    with runtime.database.transaction() as connection:
        row = read_registered_baseline(connection, snapshot_id)
        if row is None:
            raise BaselineSnapshotMissing('Original baseline snapshot is missing')
        _, fixed, steps = original_baseline(connection, row['registration_operation_id'])
        source = _source(connection, runtime.catalog, fixed)
        _, location = baseline_pinned_ref(steps[1]['result_ref'])
        proof = baseline_proof(steps[2]['result_ref'], source.commit_oid, source.format)
        return dict(row), source, proof, location


class BaselineQueryGitDispatch(BaselineGitDispatch):
    """Use the original completed step as an anchor without updating its row."""

    _external_key = 'git_baseline_query'
    _step_no = 3

    def __init__(self, runtime, frames, binding, journal):
        super().__init__(runtime, frames, binding, journal)
        self.query_id = None
        self._new = False
        self._plan = None

    @property
    def operation_id(self):
        return None if self._plan is None else self._plan['operation_id']

    @property
    def snapshot_id(self):
        return None if self._plan is None else self._plan['snapshot_id']

    def _filename(self, *, closed=False):
        if type(self.query_id) is not str or re.fullmatch('[a-f0-9]{32}', self.query_id) is None:
            raise StorageUnavailable('Original baseline query identity required')
        suffix = 'snapshot-query-closed' if closed else 'snapshot-query'
        return self.query_id + '.' + suffix + '.json'

    def _read(self, *, closed=False):
        filename = self._filename(closed=closed)
        self._journal._verify()
        path = self._journal.root / filename
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        identity = self._journal._package.verify_member(filename, directory=False)
        try:
            with LockedConfigSource(
                path, max_file_bytes=_MAX_QUERY_BYTES, expected_file=identity
            ) as held:
                return held.verify().raw
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if type(retained) is LockedConfigSource:
                self._retained_reads.append(retained)
                error.retained_owner = self
            raise

    def _append_query_record(self, raw, *, closed=False):
        if self._pending or self._retained_reads:
            raise StorageUnavailable('Original baseline query evidence requires observation')
        filename = self._filename(closed=closed)
        writer = None
        try:
            writer = PrivateRecordAppend(
                self._journal._package, filename, raw, max_record_bytes=_MAX_QUERY_BYTES
            )
            self._pending.append(writer)
            writer.publish()
            writer.close()
            if self._read(closed=closed) != raw:
                raise StorageUnavailable('Original baseline query publication differs')
            self._pending.remove(writer)
        except BaseException as error:
            retained = getattr(error, 'retained_owner', None)
            if writer is None and type(retained) is PrivateRecordAppend:
                self._pending.append(retained)
            error.retained_owner = self
            raise

    def _read_plan(self):
        raw = self._read()
        if raw is None:
            raise StorageUnavailable('Original baseline query plan is missing')
        try:
            plan = strict_json_object(raw)
            strict_integer(plan['snapshot_id'], 'snapshot_id')
            strict_integer(plan['operation_id'], 'operation_id')
        except (ValueError, KeyError, InvalidInput) as error:
            raise StorageUnavailable('Original baseline query plan is invalid') from error
        if (
            set(plan) != {'query_id', 'snapshot_id', 'operation_id', 'installation_ref', 'external'}
            or plan['query_id'] != self.query_id
            or plan['installation_ref'] != self._binding.installation_ref
            or compact(plan).encode('utf-8') != raw
            or type(plan['external']) is not dict
            or set(plan['external']) != {self._external_key}
        ):
            raise StorageUnavailable('Original baseline query plan differs')
        if self._plan is not None and plan != self._plan:
            raise StorageUnavailable('Original baseline query plan changed')
        return plan

    def _closed_bytes(self):
        return compact(
            {'query_sha256': hashlib.sha256(compact(self._plan).encode('utf-8')).hexdigest()}
        ).encode('utf-8')

    def already_closed(self):
        if self._plan is None:
            raise StorageUnavailable('Original baseline query plan required')
        raw = self._read(closed=True)
        if raw is None:
            return False
        if raw != self._closed_bytes():
            raise StorageUnavailable('Original baseline query closure differs')
        return True

    @staticmethod
    def saved_ids(journal):
        journal._verify()
        ids = []
        for path in journal.root.iterdir():
            if path.name.endswith('.snapshot-query.json'):
                match = _PLAN_NAME.fullmatch(path.name)
                if match is None or len(ids) >= _MAX_QUERY_RECORDS:
                    raise StorageUnavailable('Original baseline query record set differs')
                ids.append(match[1])
        return tuple(sorted(ids))

    def reopen(self, query_id):
        if self.query_id is not None:
            raise StorageUnavailable('Original baseline query already bound')
        self.query_id = query_id
        self._plan = self._read_plan()

    def reserve_query(self, snapshot_id, operation_id):
        if self.query_id is not None or len(self.saved_ids(self._journal)) >= _MAX_QUERY_RECORDS:
            raise StorageUnavailable('Original baseline query capacity or identity differs')
        self._binding.assert_backend(self._runtime.commands().process_lock)
        with self._runtime.database.transaction() as connection:
            self._require_snapshot(connection, snapshot_id, operation_id)
        self.query_id = uuid4().hex
        self._plan = {
            'query_id': self.query_id,
            'snapshot_id': snapshot_id,
            'operation_id': operation_id,
            'installation_ref': self._binding.installation_ref,
            'external': {
                self._external_key: {
                    'controller_ref': self._binding.controller_ref,
                    'owner_epoch': self._binding.owner_epoch,
                    'journal_root': asdict(self._journal._package.verify()),
                    'commands': [
                        {'command_ref': command, 'nonce': uuid4().hex} for command in self._commands
                    ],
                },
            },
        }
        self._append_query_record(compact(self._plan).encode('utf-8'))
        self._new = True

    def reserve(self, operation_id):
        if not self._new:
            raise StorageUnavailable('A newly authorized baseline query is required')
        return self.original(operation_id)

    @staticmethod
    def _require_snapshot(connection, snapshot_id, operation_id):
        snapshot = read_registered_baseline(connection, snapshot_id)
        if snapshot is None or snapshot['registration_operation_id'] != operation_id:
            raise StorageUnavailable('Original baseline query snapshot differs')

    def _active_step(self, connection, operation_id, *, allow_unknown=False):
        plan = self._read_plan()
        if (
            operation_id != plan['operation_id']
            or self.already_closed()
            or not allow_unknown
            and not self._new
        ):
            raise StorageUnavailable('Original baseline query is not authorized for this action')
        self._require_snapshot(connection, plan['snapshot_id'], operation_id)
        return {'external_identity': compact(plan['external'])}

    def actions(self):
        from .repository_git_runner import RepositoryGitScopeActions

        return tuple(
            RepositoryGitScopeActions(self._runtime, self._binding, self, scope)
            for scope in self.original(self.operation_id)
        )

    def retire(self):
        if self.already_closed():
            return
        if any(action.cleanup_pending() for action in self.actions()):
            raise StorageUnavailable('Original baseline query cleanup is pending')
        self._append_query_record(self._closed_bytes(), closed=True)
        self._new = False
