"""Application rejection and persistent command execution, no HTTP delivery."""
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from typing import Callable

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.idempotency import Idempotency, IdempotencyConflict, RequestInProgress, Scope, Success, request_key
from backend.app.infrastructure.identifiers import CapacityExhausted
from .time import utc_milliseconds
from .validation import strict_integer


class Rejected(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExpectedCurrentInput:
    requirement_id: int
    expected_content_version: int
    idempotency_key: str

    @classmethod
    def from_fields(cls, data: dict) -> 'ExpectedCurrentInput':
        return cls(strict_integer(data['requirement_id'], 'requirement_id'),
                   strict_integer(data['expected_content_version'], 'expected_content_version'),
                   request_key(data['idempotency_key'], 'idempotency_key'))

    def business_input(self) -> dict:
        return {'requirement_id': self.requirement_id, 'expected_content_version': self.expected_content_version}


@dataclass(frozen=True)
class RequirementActionInput:
    requirement_id: int
    idempotency_key: str

    @classmethod
    def from_fields(cls, data: dict) -> 'RequirementActionInput':
        return cls(strict_integer(data['requirement_id'], 'requirement_id'), request_key(data['idempotency_key'], 'idempotency_key'))

    def business_input(self) -> dict:
        return {'requirement_id': self.requirement_id}


@dataclass(frozen=True)
class ExpectedDraftInput:
    requirement_id: int
    expected_version: int
    idempotency_key: str

    @classmethod
    def from_fields(cls, data: dict) -> 'ExpectedDraftInput':
        return cls(strict_integer(data['requirement_id'], 'requirement_id'),
                   strict_integer(data['expected_version'], 'expected_version'),
                   request_key(data['idempotency_key'], 'idempotency_key'))

    def business_input(self) -> dict:
        return {'requirement_id': self.requirement_id, 'expected_version': self.expected_version}


def operation_time(clock: Callable[[], datetime] | None) -> str:
    at = utc_milliseconds(clock() if clock is not None else datetime.now(timezone.utc))
    if at is None:
        raise ValueError('A real operation instant is required')
    return at


def execute_idempotent(executor: Idempotency, capability: str, request: ExpectedCurrentInput | RequirementActionInput | ExpectedDraftInput,
                       operation: Callable[[sqlite3.Connection], Success], *, allowed_failures: frozenset[str],
                       business_input: dict | None = None) -> dict:
    try:
        scope = Scope(capability, f'Requirement:{request.requirement_id}', request.idempotency_key)
        return executor.execute(scope, request.business_input() if business_input is None else business_input, operation).result
    except Rejected as error:
        code = error.code if error.code in allowed_failures else 'INTERNAL_ERROR'
    except (IdempotencyConflict, RequestInProgress, CapacityExhausted) as error:
        code = error.code
    except (StorageUnavailable, sqlite3.Error):
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}
