"""INF-REV-REP fixed historical projections on the shared read connection."""
import sqlite3

from backend.app.revisions.contracts import SUMMARY_FIELDS, ListRevisionsInput, list_revisions_result
from backend.app.shared.pagination import PAGE_SIZE, page_offset


class RevisionRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def requirement_exists(self, identity: int) -> bool:
        return self.connection.execute('SELECT id FROM requirements WHERE id=?', (identity,)).fetchone() is not None

    def _count(self, identity: int) -> int:
        return self.connection.execute('SELECT count(*) FROM revisions WHERE requirement_id=?', (identity,)).fetchone()[0]

    def list_page(self, request: ListRevisionsInput) -> dict:
        total = self._count(request.requirement_id)
        rows = self.connection.execute(
            'SELECT ' + ','.join(SUMMARY_FIELDS) + ' FROM revisions WHERE requirement_id=? ORDER BY version_no DESC,id DESC LIMIT ? OFFSET ?',
            (request.requirement_id, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        return list_revisions_result(rows, request.page, total)

    def get(self, identity: int) -> sqlite3.Row | None:
        return self.connection.execute(
            'SELECT ' + ','.join(SUMMARY_FIELDS) + ',markdown_snapshot,block_state_snapshot_json FROM revisions WHERE id=?', (identity,),
        ).fetchone()
