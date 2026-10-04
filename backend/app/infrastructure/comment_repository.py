"""INF-COMMENT-REP reads all live anchors and changes only anchor status."""
import sqlite3
from .identifiers import require_write_transaction


class CommentRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def live_anchors(self, requirement_id: int) -> list[sqlite3.Row]:
        return self.connection.execute('SELECT id,anchor_type,block_id,anchor_ref_json FROM comments WHERE requirement_id=? AND deleted_at IS NULL ORDER BY created_at,id', (requirement_id,)).fetchall()

    def set_anchor_status(self, requirement_id: int, identity: int, status: str) -> None:
        require_write_transaction(self.connection)
        if status not in ('ATTACHED', 'ORPHANED'):
            raise ValueError('Unregistered anchor status')
        result = self.connection.execute('UPDATE comments SET anchor_status=? WHERE id=? AND requirement_id=? AND deleted_at IS NULL', (status, identity, requirement_id))
        if result.rowcount != 1:
            raise ValueError('Comment disappeared within the shared transaction')
