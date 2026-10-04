"""INF-BATCH-REP complete aggregate reads on the caller shared snapshot."""
import sqlite3
from .identifiers import require_write_transaction


class BatchRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identity: int) -> sqlite3.Row | None:
        return self.connection.execute('SELECT * FROM suggestion_batches WHERE id=?', (identity,)).fetchone()

    def suggestions(self, identity: int) -> list[sqlite3.Row]:
        # The stored aggregate cap is validated after reading, never truncated.
        return self.connection.execute('SELECT * FROM suggestions WHERE batch_id=? ORDER BY order_no,id', (identity,)).fetchall()

    def parent(self, row: sqlite3.Row) -> sqlite3.Row | None:
        return self.connection.execute('SELECT id,requirement_id,action_type,function_type,status,source_type,source_id FROM guide_runs WHERE id=?', (row['guide_run_id'],)).fetchone()

    def discard(self, identity: int, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=?,updated_at=? WHERE id=? AND status='PENDING'", (at, at, identity))
        if result.rowcount != 1: raise ValueError('Batch lost its shared write transaction state gate')
        return self.get(identity)
