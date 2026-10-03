"""D-003 allocations inside the caller's shared SQLite write transaction."""
from enum import StrEnum
import sqlite3

from backend.app.shared.validation import MAX_SAFE_INTEGER


class CapacityExhausted(RuntimeError):
    code = 'CAPACITY_EXHAUSTED'

    def __init__(self):
        super().__init__('编号或版本容量已用尽')


class EntityKind(StrEnum):
    REQUIREMENT = 'Requirement'
    DOCUMENT = 'RequirementDocument'
    REVISION = 'Revision'
    MESSAGE = 'ConversationMessage'
    GUIDE_RUN = 'GuideRun'
    LLM_USE = 'LLMUse'
    BATCH = 'SuggestionBatch'
    SUGGESTION = 'Suggestion'
    COMMENT = 'Comment'
    DOCUMENT_AUDIT = 'DocumentChangeAudit'


def require_write_transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction or connection.execute('PRAGMA query_only').fetchone()[0] != 0:
        raise RuntimeError('Allocation or mutation requires the shared write transaction')


def increment(value: int, *, maximum: int = MAX_SAFE_INTEGER) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('Stored positive integer is invalid')
    if value == maximum:
        raise CapacityExhausted()
    return value + 1


def _allocate(connection: sqlite3.Connection, kind: str, maximum: int) -> int:
    require_write_transaction(connection)
    row = connection.execute('SELECT last_value FROM sequences WHERE entity_kind=?', (kind,)).fetchone()
    previous = row[0] if row else 0
    if type(previous) is not int or not 0 <= previous <= maximum:
        raise ValueError('Stored sequence is invalid')
    if previous == maximum:
        raise CapacityExhausted()
    value = previous + 1
    if row is None:
        connection.execute('INSERT INTO sequences(entity_kind,last_value) VALUES (?,?)', (kind, value))
    else:
        connection.execute('UPDATE sequences SET last_value=? WHERE entity_kind=?', (value, kind))
    return value


def entity_id(connection: sqlite3.Connection, kind: EntityKind) -> int:
    if not isinstance(kind, EntityKind):
        raise ValueError('Entity identity must name a registered kind')
    return _allocate(connection, kind.value, MAX_SAFE_INTEGER)


def requirement_number(connection: sqlite3.Connection) -> str:
    return f'REQ{_allocate(connection, "RequirementNumber", 999_999):06d}'


def _next_for_requirement(connection: sqlite3.Connection, table: str, column: str, requirement_id: int) -> int:
    require_write_transaction(connection)
    if type(requirement_id) is not int or not 1 <= requirement_id <= MAX_SAFE_INTEGER:
        raise ValueError('Positive requirement identity required')
    # Both identifiers come only from the two functions below, never user input.
    maximum = connection.execute(f'SELECT MAX({column}) FROM {table} WHERE requirement_id=?', (requirement_id,)).fetchone()[0]
    return 1 if maximum is None else increment(maximum)


def message_sequence(connection: sqlite3.Connection, requirement_id: int) -> int:
    return _next_for_requirement(connection, 'conversation_messages', 'sequence_no', requirement_id)


def revision_number(connection: sqlite3.Connection, requirement_id: int) -> int:
    return _next_for_requirement(connection, 'revisions', 'version_no', requirement_id)


def block_id(next_block_id: int) -> tuple[int, int]:
    """Return assigned ID and new high-water mark; MAX itself cannot be consumed."""
    return next_block_id, increment(next_block_id)
