"""INF-COMMENT-REP reads all live anchors and changes only anchor status."""
import sqlite3
from .identifiers import require_write_transaction
from backend.app.shared.pagination import PAGE_SIZE, page_offset

COMMENT_COLUMNS = 'id,requirement_id,content,anchor_type,block_id,anchor_ref_json,anchor_status,status,resolved_at,deleted_at,created_at,updated_at'


class CommentRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identity: int) -> sqlite3.Row | None:
        return self.connection.execute('SELECT '+COMMENT_COLUMNS+' FROM comments WHERE id=?', (identity,)).fetchone()

    def _count_live(self, requirement_id: int) -> int:
        return self.connection.execute('SELECT count(*) FROM comments WHERE requirement_id=? AND deleted_at IS NULL', (requirement_id,)).fetchone()[0]

    def list_page(self, request):
        total = self._count_live(request.requirement_id)
        rows = self.connection.execute('SELECT '+COMMENT_COLUMNS+' FROM comments WHERE requirement_id=? AND deleted_at IS NULL ORDER BY created_at,id LIMIT ? OFFSET ?',
            (request.requirement_id, PAGE_SIZE, page_offset(request.page))).fetchall()
        return total, rows

    def all_live(self, requirement_id: int) -> list[sqlite3.Row]:
        return self.connection.execute('SELECT '+COMMENT_COLUMNS+' FROM comments WHERE requirement_id=? AND deleted_at IS NULL ORDER BY created_at,id', (requirement_id,)).fetchall()

    def create(self, identity: int, request, anchor: dict, at: str) -> sqlite3.Row:
        from .idempotency import canonical_input
        require_write_transaction(self.connection)
        self.connection.execute("INSERT INTO comments(id,requirement_id,content,anchor_type,block_id,anchor_ref_json,anchor_status,status,resolved_at,deleted_at,created_at,updated_at) VALUES (?,?,?,?,?,?,'ATTACHED','OPEN',NULL,NULL,?,?)",
            (identity, request.requirement_id, request.content, request.anchor_type, request.block_id, canonical_input(anchor), at, at))
        return self.get(identity)

    def update(self, identity: int, changes: dict, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        if not changes or not set(changes) <= {'content', 'status', 'resolved_at', 'deleted_at'}:
            raise ValueError('Only submitted comment text or lifecycle may change')
        fields = tuple(changes)
        result = self.connection.execute('UPDATE comments SET '+','.join(field+'=?' for field in fields)+',updated_at=? WHERE id=?',
            (*[changes[field] for field in fields], at, identity))
        if result.rowcount != 1: raise ValueError('Comment disappeared inside the shared write transaction')
        return self.get(identity)

    def live_anchors(self, requirement_id: int) -> list[sqlite3.Row]:
        return self.connection.execute('SELECT id,anchor_type,block_id,anchor_ref_json FROM comments WHERE requirement_id=? AND deleted_at IS NULL ORDER BY created_at,id', (requirement_id,)).fetchall()

    def set_anchor_status(self, requirement_id: int, identity: int, status: str) -> None:
        require_write_transaction(self.connection)
        if status not in ('ATTACHED', 'ORPHANED'):
            raise ValueError('Unregistered anchor status')
        result = self.connection.execute('UPDATE comments SET anchor_status=? WHERE id=? AND requirement_id=? AND deleted_at IS NULL', (status, identity, requirement_id))
        if result.rowcount != 1:
            raise ValueError('Comment disappeared within the shared transaction')
