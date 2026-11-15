"""Original mutation intent/ACK inside the existing private Guard journal.

This component dispatches nothing. Only first_accepted after durable MAY may
enter an action's one original allocation/dispatch path. Existing MAY requires
observation, never replay. NO_RECORD is not evidence of non-execution.
"""

import os
from dataclasses import asdict, replace
from uuid import uuid4

from .guard_action_records import (
    MAX_ACTION_BYTES,
    GuardActionError,
    GuardActionRecord,
    GuardActionStart,
    action_result_json,
    decode_action_record,
    mutation_action,
    mutation_input_sha256,
)
from .guard_request_header import GuardRequestHeader
from .runtime_launch_journal import LaunchJournal, LaunchScope, _bytes, _now
from .windows_local_paths import LocalPathGuard
from .windows_private_record import PrivateRecordError

MAX_ACTION_RECORDS = 100000


class GuardActionJournal:
    def __init__(self, journal):
        if type(journal) is not LaunchJournal:
            raise TypeError('Original Guard journal required')
        journal._verify()
        self._journal = journal

    def _path(self, scope, action):
        if not isinstance(scope, LaunchScope):
            raise GuardActionError('ORIGINAL_GUARD_ACTION_SCOPE_REQUIRED')
        return self._journal.root / (
            scope.key + '.' + mutation_action(action).lower() + '.guard-action.json'
        )

    def _read(self, scope, action):
        self._journal._verify()
        path = self._path(scope, action)
        try:
            path.lstat()
        except FileNotFoundError:
            return None, None
        self._journal._package.verify_member(path.name, directory=False)
        with LocalPathGuard(path, directory=False), path.open('rb') as stream:
            raw = stream.read(MAX_ACTION_BYTES + 1)
        return decode_action_record(raw, scope, action), raw

    def find(self, scope, action):
        with self._journal._scope(scope), self._journal._gate:
            return self._read(scope, action)[0]

    def _save(self, record, old_raw):
        raw = _bytes(asdict(record))
        decode_action_record(raw, record.scope, record.action)
        path = self._path(record.scope, record.action)
        temporary = None
        try:
            name = '.guard-action-' + uuid4().hex + '.tmp'
            self._journal._package.publish_new_file(name, raw, max_file_bytes=MAX_ACTION_BYTES)
            temporary = self._journal.root / name
            self._journal._verify()
            if self._read(record.scope, record.action)[1] != old_raw:
                raise GuardActionError('ORIGINAL_GUARD_ACTION_CHANGED_CONCURRENTLY')
            os.replace(temporary, path)
            actual, actual_raw = self._read(record.scope, record.action)
            if actual_raw != raw:
                raise GuardActionError('ORIGINAL_GUARD_ACTION_SAVE_UNVERIFIED')
            return actual
        except (OSError, ValueError, PrivateRecordError) as error:
            unknown = GuardActionError('ORIGINAL_GUARD_ACTION_SAVE_UNVERIFIED')
            if getattr(error, 'retained_owner', None) is not None:
                unknown.retained_owner = error.retained_owner
            raise unknown from error
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def _capacity(self):
        with os.scandir(self._journal.root) as rows:
            count = 0
            for row in rows:
                if row.name.endswith('.guard-action.json'):
                    count += 1
                    if count >= MAX_ACTION_RECORDS:
                        raise GuardActionError('GUARD_ACTION_CAPACITY_EXHAUSTED')

    def _require_original_preparation(self, scope, binding_ref, *, acknowledged):
        prepared, _ = self._read(scope, 'PREPARE')
        if (
            prepared is None
            or prepared.allocated_binding_ref != binding_ref
            or acknowledged
            and prepared.phase != 'ACKNOWLEDGED'
        ):
            raise GuardActionError('ORIGINAL_GUARD_PREPARATION_UNVERIFIED')

    def begin(self, request):
        if type(request) is not GuardRequestHeader:
            raise TypeError('Original parsed Guard mutation required')
        action = mutation_action(request.action)
        scope = request.target_scope
        digest = mutation_input_sha256(request)
        epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
        with self._journal._scope(scope), self._journal._gate:
            current, _ = self._read(scope, action)
            if current is not None:
                if (
                    current.input_sha256 != digest
                    or current.owner_epoch != epoch
                    or current.binding_ref != request.binding_ref
                ):
                    raise GuardActionError('ORIGINAL_GUARD_ACTION_INPUT_CONFLICT')
                return GuardActionStart(current, False)
            if action in ('PREPARE', 'CREATE_SUSPENDED', 'RESUME'):
                self._journal._require_controller_open(scope)
            fence = self._journal.inspect(scope)
            if action == 'PREPARE' and fence is not None:
                raise GuardActionError('ORIGINAL_PREPARATION_INTENT_MISSING')
            if action == 'CREATE_SUSPENDED':
                self._require_original_preparation(scope, request.binding_ref, acknowledged=True)
                if fence is None or fence.create_state != 'NONE' or fence.stop_closed:
                    raise GuardActionError('ORIGINAL_CREATE_INTENT_OR_FENCE_UNVERIFIED')
            elif action == 'RESUME':
                self._require_original_preparation(scope, request.binding_ref, acknowledged=True)
                created, _ = self._read(scope, 'CREATE_SUSPENDED')
                if (
                    created is None
                    or created.phase != 'ACKNOWLEDGED'
                    or created.binding_ref != request.binding_ref
                    or fence is None
                    or fence.create_state != 'RESOURCE_RECORDED'
                    or fence.resume_state != 'NONE'
                    or fence.stop_closed
                ):
                    raise GuardActionError('ORIGINAL_RESUME_INTENT_OR_FENCE_UNVERIFIED')
            elif action == 'RELEASE':
                self._require_original_preparation(scope, request.binding_ref, acknowledged=False)
                if fence is None or not fence.stop_closed:
                    raise GuardActionError('ORIGINAL_RELEASE_STOP_CLOSURE_REQUIRED')
            elif action == 'STOP' and request.binding_ref is not None:
                self._require_original_preparation(scope, request.binding_ref, acknowledged=False)
            self._capacity()
            now = _now()
            record = GuardActionRecord(
                1,
                scope,
                epoch,
                action,
                digest,
                request.binding_ref,
                uuid4().hex if action == 'PREPARE' else None,
                uuid4().hex if action == 'PREPARE' else None,
                request.scope.controller_ref,
                request.owner_epoch,
                'MAY_HAVE_BEEN_SENT',
                None,
                1,
                now,
                now,
            )
            return GuardActionStart(self._save(record, None), True)

    def acknowledge(self, expected, result):
        if type(expected) is not GuardActionRecord:
            raise TypeError('Original Guard mutation record required')
        snapshot = action_result_json(result)
        with self._journal._scope(expected.scope), self._journal._gate:
            current, raw = self._read(expected.scope, expected.action)
            if current is None:
                raise GuardActionError('ORIGINAL_GUARD_ACTION_RECORD_MISSING')
            immutable = replace(
                current,
                phase=expected.phase,
                result_json=expected.result_json,
                revision=expected.revision,
                updated_at=expected.updated_at,
            )
            if immutable != expected:
                raise GuardActionError('ORIGINAL_GUARD_ACTION_RECORD_DIFFERS')
            if current.phase == 'ACKNOWLEDGED':
                if current.result_json != snapshot:
                    raise GuardActionError('ORIGINAL_GUARD_ACTION_RESULT_CONFLICT')
                return current
            updated = replace(
                current,
                phase='ACKNOWLEDGED',
                result_json=snapshot,
                revision=2,
                updated_at=_now(),
            )
            return self._save(updated, raw)
