"""Persistent capability-owned idempotency (SHR-IDEMPOTENCY / D-003).

Only parsed/defaulted business input is accepted here. Endpoint adapters own
normalization and success projection. No Provider call belongs in execute().
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
import sqlite3
from typing import Callable
from uuid import UUID

from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import reject, MAX_SAFE_INTEGER
from .database import Database, CommitOutcomeUnknown
from .identifiers import require_write_transaction
from .process_lock import ProcessLock


def request_key(value: object, field: str = 'Idempotency-Key') -> str:
    if type(value) is not str:
        reject(field, 'INVALID_TYPE', '必须为UUID v4字符串')
    if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value) is None:
        reject(field, 'INVALID_FORMAT', '必须为含连字符的UUID v4')
    parsed = UUID(value)
    if parsed.version != 4:
        reject(field, 'INVALID_FORMAT', '必须为UUID v4')
    return str(parsed)


def _json_value(value: object) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        value.encode('utf-8', errors='strict')
        return
    if type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError('JSON integer exceeds the shared exact range')
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for key, item in value.items():
            _json_value(key)
            _json_value(item)
        return
    raise ValueError('Only complete finite JSON values are accepted')


def canonical_input(value: dict) -> str:
    if type(value) is not dict:
        raise ValueError('Parsed business input must be an object')
    _json_value(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


class IdempotencyConflict(RuntimeError):
    code = 'IDEMPOTENCY_CONFLICT'


class RequestInProgress(RuntimeError):
    code = 'REQUEST_IN_PROGRESS'


class ClaimLost(RuntimeError):
    """Owner/state inconsistency must stop all business writes."""


@dataclass(frozen=True)
class Scope:
    capability_id: str
    target_identity: str
    key: str

    def __post_init__(self):
        if type(self.capability_id) is not str or re.fullmatch(r'APP-[A-Z]+-CMD-C[0-9]{2}', self.capability_id) is None:
            raise ValueError('A complete registered command capability ID is required')
        if type(self.target_identity) is not str or not self.target_identity:
            raise ValueError('Complete target identity is required')
        object.__setattr__(self, 'key', request_key(self.key))

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.capability_id, self.target_identity, self.key


@dataclass(frozen=True)
class Success:
    result: dict
    http_status: int

    def encoded(self) -> str:
        if type(self.http_status) is not int or not 200 <= self.http_status <= 299:
            raise ValueError('Only successful HTTP status can be stored')
        if type(self.result) is not dict or set(self.result) != {'code', 'data', 'details'}:
            raise ValueError('Complete application result required')
        if type(self.result['code']) is not str or not self.result['code'] or type(self.result['data']) is not dict or self.result['details'] is not None:
            raise ValueError('Only successful application payload can be stored')
        return canonical_input(self.result)


@dataclass(frozen=True)
class Replay:
    success: Success


@dataclass(frozen=True)
class Claim:
    scope: Scope
    input_json: str
    owner_epoch: str


class Idempotency:
    def __init__(self, database: Database, process_lock: ProcessLock, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path:
            raise ValueError('Execution lock must be bound to this exact database')
        self.database = database
        self.process_lock = process_lock
        self.owner_epoch = process_lock.owner_epoch
        self.clock = clock

    def _owned(self) -> None:
        self.process_lock.assert_owned()
        if self.owner_epoch != self.process_lock.owner_epoch:
            raise ClaimLost('Process epoch changed; old execution cannot resume')

    def _time(self) -> str:
        return utc_milliseconds(self.clock())

    def claim(self, scope: Scope, business_input: dict) -> Claim | Replay:
        self._owned()
        input_json = canonical_input(business_input)
        with self.database.transaction(write=True) as connection:
            row = connection.execute('SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?', scope.identity).fetchone()
            if row is not None:
                if row['business_input_json'] != input_json:
                    raise IdempotencyConflict('同一幂等键对应了不同请求')
                if row['status'] == 'PROCESSING':
                    raise RequestInProgress('同一请求仍在处理中')
                if row['status'] != 'SUCCEEDED':
                    raise ClaimLost('Invalid persisted idempotency state')
                success = Success(json.loads(row['success_result_json']), row['http_status'])
                success.encoded()  # Corrupt persisted result must never become success.
                return Replay(success)
            time = self._time()
            connection.execute('INSERT INTO idempotency_records(capability_id,target_identity,idempotency_key,business_input_json,status,owner_epoch,created_at,updated_at,success_result_json,http_status) VALUES (?,?,?,?,?,?,?,?,?,?)', (*scope.identity, input_json, 'PROCESSING', self.owner_epoch, time, time, None, None))
        return Claim(scope, input_json, self.owner_epoch)

    def assert_claim(self, connection: sqlite3.Connection, claim: Claim) -> None:
        self._owned()
        require_write_transaction(connection)
        row = connection.execute('SELECT business_input_json,status,owner_epoch FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?', claim.scope.identity).fetchone()
        if claim.owner_epoch != self.owner_epoch or row is None or tuple(row) != (claim.input_json, 'PROCESSING', self.owner_epoch):
            raise ClaimLost('Claim no longer belongs to this execution')

    def succeed(self, connection: sqlite3.Connection, claim: Claim, success: Success) -> None:
        self.assert_claim(connection, claim)
        encoded = success.encoded()
        connection.execute("UPDATE idempotency_records SET status='SUCCEEDED',success_result_json=?,http_status=?,updated_at=? WHERE capability_id=? AND target_identity=? AND idempotency_key=?", (encoded, success.http_status, self._time(), *claim.scope.identity))

    def abandon(self, claim: Claim) -> None:
        """Only after a known rejection/rollback, never after an unknown commit."""
        self._owned()
        if claim.owner_epoch != self.owner_epoch:
            raise ClaimLost('Cannot abandon a different process claim')
        with self.database.transaction(write=True) as connection:
            connection.execute("DELETE FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=? AND business_input_json=? AND status='PROCESSING' AND owner_epoch=?", (*claim.scope.identity, claim.input_json, claim.owner_epoch))

    def recover_previous_process(self) -> int:
        """Startup only, holding OS lock. Success facts are never pruned/replayed."""
        self._owned()
        with self.database.transaction(write=True) as connection:
            cursor = connection.execute("DELETE FROM idempotency_records WHERE status='PROCESSING' AND owner_epoch<>?", (self.owner_epoch,))
            return cursor.rowcount

    def execute(self, scope: Scope, business_input: dict, operation: Callable[[sqlite3.Connection], Success]) -> Success:
        claimed = self.claim(scope, business_input)
        if isinstance(claimed, Replay):
            return claimed.success
        try:
            with self.database.transaction(write=True) as connection:
                self.assert_claim(connection, claimed)
                success = operation(connection)
                if not isinstance(success, Success):
                    raise ValueError('Operation must explicitly produce a successful application result')
                self.succeed(connection, claimed, success)
        except CommitOutcomeUnknown:
            # A future call first observes SUCCEEDED/PROCESSING. Never run twice
            # merely because a commit acknowledgment was lost.
            raise
        except BaseException:
            self.abandon(claimed)
            raise
        return success
