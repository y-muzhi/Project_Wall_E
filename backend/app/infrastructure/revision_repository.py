"""INF-REV-REP fixed historical projections on the shared read connection."""
import sqlite3

from backend.app.revisions.contracts import SUMMARY_FIELDS, ListRevisionsInput, list_revisions_result
from backend.app.shared.pagination import PAGE_SIZE, page_offset
from .identifiers import require_write_transaction


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

    def has_baseline(self, requirement_id: int) -> bool:
        return self.connection.execute("SELECT id FROM revisions WHERE requirement_id=? AND revision_type='BASELINE' LIMIT 1", (requirement_id,)).fetchone() is not None

    def insert_snapshot(self, identity: int, requirement_id: int, version: int, kind: str, document: sqlite3.Row,
                        description: str | None, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        if kind not in ('BASELINE', 'MANUAL') or document['requirement_id'] != requirement_id or document['document_type'] != 'CURRENT':
            raise ValueError('Revision must copy this requirement current snapshot')
        self.connection.execute('INSERT INTO revisions(id,requirement_id,version_no,revision_type,markdown_snapshot,block_state_snapshot_json,description,source_content_version,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                                (identity, requirement_id, version, kind, document['markdown_content'], document['block_state_json'], description, document['content_version'], at))
        row = self.get(identity)
        if row is None:
            raise ValueError('Inserted revision is missing')
        return row
