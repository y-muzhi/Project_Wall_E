"""INF-BATCH-REP complete aggregate reads on the caller shared snapshot."""
import sqlite3
from .identifiers import require_write_transaction


class BatchRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, identity: int) -> sqlite3.Row | None:
        return self.connection.execute('SELECT * FROM suggestion_batches WHERE id=?', (identity,)).fetchone()

    def suggestion(self, identity: int) -> sqlite3.Row | None:
        return self.connection.execute('SELECT * FROM suggestions WHERE id=?', (identity,)).fetchone()

    def decide(self, row: sqlite3.Row, decision: str, content: str | None, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE suggestions SET status=?,user_edited_content=?,decided_at=?,updated_at=?,validation_status='VALID',validation_error=NULL WHERE id=? AND batch_id=?", (decision, content, at, at, row['id'], row['batch_id']))
        batch = self.connection.execute("UPDATE suggestion_batches SET updated_at=? WHERE id=? AND status='PENDING'", (at, row['batch_id']))
        if result.rowcount != 1 or batch.rowcount != 1: raise ValueError('Suggestion aggregate lost its shared decision gate')
        return self.suggestion(row['id'])

    def suggestions(self, identity: int) -> list[sqlite3.Row]:
        # The stored aggregate cap is validated after reading, never truncated.
        return self.connection.execute('SELECT * FROM suggestions WHERE batch_id=? ORDER BY order_no,id', (identity,)).fetchall()

    def parent(self, row: sqlite3.Row) -> sqlite3.Row | None:
        return self.connection.execute('SELECT id,requirement_id,action_type,function_type,status,source_type,source_id FROM guide_runs WHERE id=?', (row['guide_run_id'],)).fetchone()

    def authority(self, row: sqlite3.Row) -> sqlite3.Row | None:
        return self.connection.execute('SELECT scope_type,scope_ref_json,allowed_targets_json FROM guide_runs WHERE id=?', (row['guide_run_id'],)).fetchone()

    def complete(self, identity: int, applied_version: int | None, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE suggestion_batches SET status='COMPLETED',completion_result=?,applied_content_version=?,error_message=NULL,completed_at=?,updated_at=? WHERE id=? AND status='PENDING'", ('NO_CHANGE' if applied_version is None else 'CHANGES_APPLIED', applied_version, at, at, identity))
        if result.rowcount != 1: raise ValueError('Batch lost its shared completion gate')
        return self.get(identity)

    def discard(self, identity: int, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE suggestion_batches SET status='DISCARDED',completed_at=?,updated_at=? WHERE id=? AND status='PENDING'", (at, at, identity))
        if result.rowcount != 1: raise ValueError('Batch lost its shared write transaction state gate')
        return self.get(identity)
