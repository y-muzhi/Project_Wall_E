"""SHR-CONCURRENCY checks on actual activity and current rows in a write transaction."""
import sqlite3

from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.shared.command_execution import Rejected


def assert_idle(connection: sqlite3.Connection, root: dict, *, remaining_conflicts: frozenset[str]) -> None:
    require_write_transaction(connection)
    identity = root['id']
    activities = {
        'MANUAL_DRAFT': [row[0] for row in connection.execute("SELECT id FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT' LIMIT 2", (identity,))],
        'GUIDE_RUN': [row[0] for row in connection.execute("SELECT id FROM guide_runs WHERE requirement_id=? AND status IN ('RUNNING','WAITING_USER') LIMIT 2", (identity,))],
        'SUGGESTION_BATCH': [row[0] for row in connection.execute("SELECT id FROM suggestion_batches WHERE requirement_id=? AND status='PENDING' LIMIT 2", (identity,))],
    }
    present = {kind for kind, ids in activities.items() if ids}
    if root['document_work_state'] == 'IDLE':
        if present:
            # Each command's explicit remaining-object rejection takes precedence.
            raise Rejected('WORK_STATE_CONFLICT' if present <= remaining_conflicts else 'WORK_STATE_INCONSISTENT')
        return
    kind = root['active_operation_type']
    if kind not in activities or present != {kind} or activities[kind] != [root['active_operation_id']]:
        raise Rejected('WORK_STATE_INCONSISTENT')
    if kind == 'MANUAL_DRAFT':
        binding = connection.execute("SELECT 1 FROM manual_draft_context c JOIN requirement_documents p ON p.id=c.current_document_id JOIN manual_edit_sessions s ON s.draft_id=c.draft_id WHERE c.draft_id=? AND p.requirement_id=? AND p.document_type='CURRENT' AND s.requirement_id=p.requirement_id AND s.current_document_id=p.id AND s.status='EDITING'", (root['active_operation_id'], identity)).fetchone()
        if binding is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
    elif kind == 'SUGGESTION_BATCH':
        binding = connection.execute('SELECT 1 FROM suggestion_batches b JOIN guide_runs g ON g.id=b.guide_run_id WHERE b.id=? AND g.requirement_id=b.requirement_id', (root['active_operation_id'],)).fetchone()
        if binding is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
    raise Rejected('WORK_STATE_CONFLICT')


def current_at_version(connection: sqlite3.Connection, requirement_id: int, expected_version: int) -> sqlite3.Row:
    require_write_transaction(connection)
    rows = DocumentRepository(connection).by_requirement(requirement_id, 'CURRENT')
    if len(rows) != 1:
        raise Rejected('WORK_STATE_INCONSISTENT')
    if rows[0]['content_version'] != expected_version:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    return rows[0]


def active_manual_draft(connection: sqlite3.Connection, root: dict) -> sqlite3.Row:
    require_write_transaction(connection)
    rows = DocumentRepository(connection).by_requirement(root['id'], 'MANUAL_DRAFT')
    if root['document_work_state'] != 'MANUAL_EDITING':
        if rows:
            raise Rejected('WORK_STATE_INCONSISTENT')
        # Also distinguish a valid other occupancy from a dangling one.
        assert_idle(connection, root, remaining_conflicts=frozenset())
        raise Rejected('WORK_STATE_CONFLICT')
    if len(rows) != 1 or root['active_operation_type'] != 'MANUAL_DRAFT' or root['active_operation_id'] != rows[0]['id']:
        raise Rejected('WORK_STATE_INCONSISTENT')
    try:
        assert_idle(connection, root, remaining_conflicts=frozenset())
    except Rejected as error:
        if error.code != 'WORK_STATE_CONFLICT':
            raise
        # The root and all activity/context/source relationships are consistent;
        # this capability owns that existing occupancy rather than requiring IDLE.
        return rows[0]
    raise Rejected('WORK_STATE_INCONSISTENT')
