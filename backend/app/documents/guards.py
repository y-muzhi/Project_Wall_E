"""SHR-CONCURRENCY checks on actual activity and current rows in a write transaction."""

import sqlite3

from backend.app.infrastructure.batch_repository import BatchRepository
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.shared.command_execution import Rejected


def validate_manual_occupancy(connection, root, rows):
    if (
        root['document_work_state'] != 'MANUAL_EDITING'
        or root['active_operation_type'] != 'MANUAL_DRAFT'
    ):
        raise Rejected('WORK_STATE_INCONSISTENT')
    if root['active_operation_id'] not in {row['id'] for row in rows}:
        raise Rejected('WORK_STATE_INCONSISTENT')
    bound = connection.execute(
        """SELECT s.draft_id,p.id FROM manual_edit_sessions s
           JOIN manual_draft_context c ON c.draft_id=s.draft_id AND c.current_document_id=s.current_document_id
           JOIN requirement_documents p ON p.id=c.current_document_id
           WHERE s.requirement_id=? AND p.requirement_id=? AND p.document_type='CURRENT' AND s.status='EDITING'""",
        (root['id'], root['id']),
    )
    if {tuple(row) for row in bound} != {(row['id'], row['target_document_id']) for row in rows}:
        raise Rejected('WORK_STATE_INCONSISTENT')


def assert_idle(
    connection: sqlite3.Connection, root: dict, *, remaining_conflicts: frozenset[str]
) -> None:
    require_write_transaction(connection)
    inspect_idle(connection, root, remaining_conflicts=remaining_conflicts)


def inspect_idle(
    connection: sqlite3.Connection, root: dict, *, remaining_conflicts: frozenset[str]
) -> None:
    """The same actual occupancy checks, also usable by a read-only availability projection."""
    identity = root['id']
    drafts = DocumentRepository(connection).by_requirement(identity, 'MANUAL_DRAFT')
    activities = {
        'MANUAL_DRAFT': [row['id'] for row in drafts],
        'GUIDE_RUN': [
            row[0] for row in GuideRepository(connection).occupying_runs(identity, waiting=True)
        ],
        'SUGGESTION_BATCH': [
            row[0] for row in BatchRepository(connection).occupancy_batches(identity)
        ],
    }
    present = {kind for kind, ids in activities.items() if ids}
    if root['document_work_state'] == 'IDLE':
        if present:
            # Each command's explicit remaining-object rejection takes precedence.
            raise Rejected(
                'WORK_STATE_CONFLICT'
                if present <= remaining_conflicts
                else 'WORK_STATE_INCONSISTENT'
            )
        return
    kind = root['active_operation_type']
    if kind not in activities or present != {kind}:
        raise Rejected('WORK_STATE_INCONSISTENT')
    if kind == 'MANUAL_DRAFT':
        validate_manual_occupancy(connection, root, drafts)
    elif activities[kind] != [root['active_operation_id']]:
        raise Rejected('WORK_STATE_INCONSISTENT')
    if kind == 'SUGGESTION_BATCH':
        binding = connection.execute(
            'SELECT 1 FROM suggestion_batches b JOIN guide_runs g ON g.id=b.guide_run_id WHERE b.id=? AND g.requirement_id=b.requirement_id',
            (root['active_operation_id'],),
        ).fetchone()
        if binding is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
    raise Rejected('WORK_STATE_CONFLICT')


def assert_guide_available(connection, root, document_id, *, document_scoped):
    guides = GuideRepository(connection)
    if guides.scoped_running(root['id'], document_id):
        raise Rejected('WORK_STATE_CONFLICT')
    try:
        assert_idle(
            connection,
            root,
            remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}),
        )
    except Rejected as error:
        if (
            error.code != 'WORK_STATE_CONFLICT'
            or not document_scoped
            or root['active_operation_id'] is None
        ):
            raise
        if root['active_operation_type'] == 'MANUAL_DRAFT':
            drafts = DocumentRepository(connection).by_requirement(root['id'], 'MANUAL_DRAFT')
            if any(row['target_document_id'] == document_id for row in drafts):
                raise
            return
        table, field = {
            'GUIDE_RUN': ('guide_runs', 'document_id'),
            'SUGGESTION_BATCH': ('suggestion_batches', 'target_document_id'),
        }[root['active_operation_type']]
        owner = connection.execute(
            f'SELECT {field} FROM {table} WHERE id=? AND requirement_id=?',
            (root['active_operation_id'], root['id']),
        ).fetchone()
        if owner is None or owner[0] in (None, document_id):
            raise


def assert_document_idle(connection, root, document_id, *, remaining_conflicts):
    try:
        assert_idle(connection, root, remaining_conflicts=remaining_conflicts)
    except Rejected as error:
        from backend.app.infrastructure.review_schema import supports_review_layout

        if (
            error.code != 'WORK_STATE_CONFLICT'
            or root['active_operation_type'] != 'MANUAL_DRAFT'
            or not supports_review_layout(connection)
        ):
            raise
        drafts = DocumentRepository(connection).by_requirement(root['id'], 'MANUAL_DRAFT')
        if any(row['target_document_id'] == document_id for row in drafts):
            raise


def current_at_version(
    connection: sqlite3.Connection, requirement_id: int, expected_version: int, *, document_id: int
) -> sqlite3.Row:
    require_write_transaction(connection)
    current = DocumentRepository(connection).get_current(requirement_id, document_id)
    if current is None:
        raise Rejected('NOT_FOUND')
    if current['content_version'] != expected_version:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    return current


def active_manual_draft(
    connection: sqlite3.Connection,
    root: dict,
    *,
    document_id: int | None = None,
    draft_id: int | None = None,
) -> sqlite3.Row:
    require_write_transaction(connection)
    rows = DocumentRepository(connection).by_requirement(root['id'], 'MANUAL_DRAFT')
    if root['document_work_state'] != 'MANUAL_EDITING':
        if rows:
            raise Rejected('WORK_STATE_INCONSISTENT')
        # Also distinguish a valid other occupancy from a dangling one.
        assert_idle(connection, root, remaining_conflicts=frozenset())
        raise Rejected('WORK_STATE_CONFLICT')
    selected = next((row for row in rows if row['id'] == root['active_operation_id']), None)
    if document_id is not None:
        selected = next((row for row in rows if row['target_document_id'] == document_id), None)
    if selected is None or (draft_id is not None and selected['id'] != draft_id):
        validate_manual_occupancy(connection, root, rows)
        raise Rejected('MANUAL_DRAFT_NOT_FOUND')
    try:
        assert_idle(connection, root, remaining_conflicts=frozenset())
    except Rejected as error:
        if error.code != 'WORK_STATE_CONFLICT':
            raise
        # The root and all activity/context/source relationships are consistent;
        # this capability owns that existing occupancy rather than requiring IDLE.
        return selected
    raise Rejected('WORK_STATE_INCONSISTENT')
