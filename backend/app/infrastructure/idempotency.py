"""Persistent capability-owned idempotency (SHR-IDEMPOTENCY / D-003).

Only parsed/defaulted business input is accepted here. Endpoint adapters own
normalization and success projection. No Provider call belongs in execute().
"""

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .command_receipts import Rejection
from uuid import UUID

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import MAX_SAFE_INTEGER, reject

from .database import CommitOutcomeUnknown, Database
from .identifiers import require_write_transaction
from .process_lock import ProcessLock, matches_database


def request_key(value: object, field: str = 'Idempotency-Key') -> str:
    if type(value) is not str:
        reject(field, 'INVALID_TYPE', '必须为UUID v4字符串')
    if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value) is None:
        reject(field, 'INVALID_FORMAT', '必须为含连字符的UUID v4')
    parsed = UUID(value)
    if parsed.version != 4:
        reject(field, 'INVALID_FORMAT', '必须为UUID v4')
    return str(parsed)


def generation_namespace(generation: str | None) -> str:
    return '' if generation is None else f'@generation:{generation}:'


def storage_identity(database, scope) -> tuple[str, str, str]:
    prefix = generation_namespace(getattr(database, 'idempotency_generation', None))
    return scope.capability_id, prefix + scope.target_identity, scope.key


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
        if (
            type(self.capability_id) is not str
            or re.fullmatch(r'APP-[A-Z]+-CMD-C[0-9]{2}', self.capability_id) is None
        ):
            raise ValueError('A complete registered command capability ID is required')
        if type(self.target_identity) is not str or not self.target_identity:
            raise ValueError('Complete target identity is required')
        normalized = request_key(self.key)
        if (
            self.capability_id.startswith(('APP-CODE-CMD-', 'APP-TEST-CMD-'))
            and self.key != normalized
        ):
            raise ValueError('V2 command keys must be lowercase UUID v4')
        object.__setattr__(self, 'key', normalized)

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
        if (
            type(self.result['code']) is not str
            or not self.result['code']
            or type(self.result['data']) is not dict
            or self.result['details'] is not None
        ):
            raise ValueError('Only successful application payload can be stored')
        return canonical_input(self.result)


@dataclass(frozen=True)
class CommentAnchorRejected:
    """C05's explicit committed anchor correction, never a stored success."""

    comment_id: int

    @property
    def result(self):
        return {'code': 'COMMENT_ORPHANED', 'data': None, 'details': None}


@dataclass(frozen=True)
class Replay:
    success: Success


@dataclass(frozen=True)
class Claim:
    scope: Scope
    input_json: str
    owner_epoch: str


class Idempotency:
    def __init__(
        self,
        database: Database,
        process_lock: ProcessLock,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        process_lock.assert_owned()
        if not matches_database(process_lock, database):
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
        if scope.capability_id.startswith(('APP-CODE-CMD-', 'APP-TEST-CMD-')):
            raise ValueError('V2 claims must be committed atomically with real acceptance')
        input_json = canonical_input(business_input)
        with self.database.transaction(write=True) as connection:
            row = connection.execute(
                'SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?',
                storage_identity(self.database, scope),
            ).fetchone()
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
            connection.execute(
                'INSERT INTO idempotency_records(capability_id,target_identity,idempotency_key,business_input_json,status,owner_epoch,created_at,updated_at,success_result_json,http_status) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (
                    *storage_identity(self.database, scope),
                    input_json,
                    'PROCESSING',
                    self.owner_epoch,
                    time,
                    time,
                    None,
                    None,
                ),
            )
        return Claim(scope, input_json, self.owner_epoch)

    def assert_claim(self, connection: sqlite3.Connection, claim: Claim) -> None:
        self._owned()
        require_write_transaction(connection)
        row = connection.execute(
            'SELECT business_input_json,status,owner_epoch FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?',
            storage_identity(self.database, claim.scope),
        ).fetchone()
        if (
            claim.owner_epoch != self.owner_epoch
            or row is None
            or tuple(row) != (claim.input_json, 'PROCESSING', self.owner_epoch)
        ):
            raise ClaimLost('Claim no longer belongs to this execution')

    def succeed(self, connection: sqlite3.Connection, claim: Claim, success: Success) -> None:
        self.assert_claim(connection, claim)
        encoded = success.encoded()
        connection.execute(
            "UPDATE idempotency_records SET status='SUCCEEDED',success_result_json=?,http_status=?,updated_at=? WHERE capability_id=? AND target_identity=? AND idempotency_key=?",
            (
                encoded,
                success.http_status,
                self._time(),
                *storage_identity(self.database, claim.scope),
            ),
        )

    def abandon(self, claim: Claim) -> None:
        """Only after a known rejection/rollback, never after an unknown commit."""
        self._owned()
        if claim.scope.capability_id.startswith(('APP-CODE-CMD-', 'APP-TEST-CMD-')):
            raise ValueError('V2 unknown claims must never be abandoned or expired')
        if claim.owner_epoch != self.owner_epoch:
            raise ClaimLost('Cannot abandon a different process claim')
        with self.database.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=? AND business_input_json=? AND status='PROCESSING' AND owner_epoch=?",
                (
                    *storage_identity(self.database, claim.scope),
                    claim.input_json,
                    claim.owner_epoch,
                ),
            )

    def recover_previous_process(self) -> int:
        """Startup only, holding OS lock. Success facts are never pruned/replayed."""
        self._owned()
        query = (
            "DELETE FROM idempotency_records WHERE status='PROCESSING' AND owner_epoch<>? "
            "AND capability_id NOT LIKE 'APP-CODE-CMD-%' AND capability_id NOT LIKE 'APP-TEST-CMD-%'"
        )
        parameters = (self.owner_epoch,)
        prefix = generation_namespace(getattr(self.database, 'idempotency_generation', None))
        if prefix:
            query += ' AND substr(target_identity,1,?)=?'
            parameters += (len(prefix), prefix)
        with self.database.transaction(write=True) as connection:
            return connection.execute(query, parameters).rowcount

    def close_command(self, scope: Scope) -> dict:
        from .command_receipts import close_command

        return close_command(self, scope)

    def command_receipt(self, scope: Scope) -> dict:
        from .command_receipts import lookup_receipt

        self._owned()
        return lookup_receipt(self.database, scope)

    def execute(
        self,
        scope: Scope,
        business_input: dict,
        operation: Callable[[sqlite3.Connection], 'Success | CommentAnchorRejected | Rejection'],
    ) -> 'Success | CommentAnchorRejected | Rejection':
        if scope.capability_id.startswith(('APP-CODE-CMD-', 'APP-TEST-CMD-')):
            from .command_receipts import execute_registered

            return execute_registered(self, scope, business_input, operation)
        claimed = self.claim(scope, business_input)
        if isinstance(claimed, Replay):
            return claimed.success
        try:
            with self.database.transaction(write=True) as connection:
                self.assert_claim(connection, claimed)
                success = operation(connection)
                if isinstance(success, CommentAnchorRejected):
                    if (
                        type(success.comment_id) is not int
                        or not 1 <= success.comment_id <= MAX_SAFE_INTEGER
                        or scope.capability_id != 'APP-GUIDE-CMD-C05'
                        or scope.target_identity != f'Comment:{success.comment_id}'
                    ):
                        raise ValueError(
                            'Committed rejection is restricted to the actual C05 comment target'
                        )
                    row = connection.execute(
                        'SELECT anchor_status FROM comments WHERE id=?', (success.comment_id,)
                    ).fetchone()
                    if row is None or row['anchor_status'] != 'ORPHANED':
                        raise ValueError(
                            'Committed rejection requires the actual corrected comment'
                        )
                    self.assert_claim(connection, claimed)
                    removed = connection.execute(
                        "DELETE FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=? AND business_input_json=? AND status='PROCESSING' AND owner_epoch=?",
                        (
                            *storage_identity(self.database, scope),
                            claimed.input_json,
                            claimed.owner_epoch,
                        ),
                    )
                    if removed.rowcount != 1:
                        raise ClaimLost(
                            'Correction must release its own processing claim atomically'
                        )
                elif isinstance(success, Success):
                    self.succeed(connection, claimed, success)
                else:
                    raise TypeError(
                        'Operation must explicitly produce a successful application result'
                    )
        except CommitOutcomeUnknown:
            # A future call first observes SUCCEEDED/PROCESSING. Never run twice
            # merely because a commit acknowledgment was lost.
            raise
        except BaseException:
            self.abandon(claimed)
            raise
        return success
