"""INF-DOC-REP fixed document-kind reads on the caller's SQLite snapshot."""
import sqlite3

from backend.app.documents.contracts import DOCUMENT_FIELDS
from .identifiers import require_write_transaction


class DocumentRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def by_requirement(self, requirement_id: int, document_type: str) -> list[sqlite3.Row]:
        if document_type not in ('CURRENT', 'MANUAL_DRAFT'):
            raise ValueError('Unregistered document type')
        # A query never chooses arbitrarily if persisted uniqueness is broken.
        return self.connection.execute(
            'SELECT ' + ','.join(DOCUMENT_FIELDS) + ' FROM requirement_documents WHERE requirement_id=? AND document_type=? LIMIT 2',
            (requirement_id, document_type),
        ).fetchall()

    def create_manual_draft(self, identity: int, current: sqlite3.Row, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        if current['document_type'] != 'CURRENT' or identity == current['id']:
            raise ValueError('Draft must have an independent identity from real CURRENT')
        self.connection.execute("INSERT INTO requirement_documents(id,requirement_id,document_type,markdown_content,block_state_json,content_version,created_at,updated_at) VALUES (?,?,'MANUAL_DRAFT',?,?,1,?,?)",
                                (identity, current['requirement_id'], current['markdown_content'], current['block_state_json'], at, at))
        self.connection.execute('INSERT INTO manual_draft_context(draft_id,current_document_id,base_content_version,baseline_block_state_json,operation_time) VALUES (?,?,?,?,?)',
                                (identity, current['id'], current['content_version'], current['block_state_json'], at))
        rows = self.by_requirement(current['requirement_id'], 'MANUAL_DRAFT')
        if len(rows) != 1 or rows[0]['id'] != identity:
            raise ValueError('Inserted draft is not unique')
        return rows[0]

    def delete_manual_draft(self, draft: sqlite3.Row) -> None:
        require_write_transaction(self.connection)
        if draft['document_type'] != 'MANUAL_DRAFT':
            raise ValueError('Draft deletion cannot delete CURRENT')
        self.connection.execute('DELETE FROM manual_block_origins WHERE draft_id=?', (draft['id'],))
        self.connection.execute('DELETE FROM manual_block_allocation_ranges WHERE draft_id=?', (draft['id'],))
        context = self.connection.execute('DELETE FROM manual_draft_context WHERE draft_id=?', (draft['id'],))
        document = self.connection.execute("DELETE FROM requirement_documents WHERE id=? AND requirement_id=? AND document_type='MANUAL_DRAFT'", (draft['id'], draft['requirement_id']))
        if context.rowcount != 1 or document.rowcount != 1:
            raise ValueError('Draft or its context disappeared in shared transaction')

    def save_manual_draft(self, draft: sqlite3.Row, snapshot, version: int, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        result = self.connection.execute("UPDATE requirement_documents SET markdown_content=?,block_state_json=?,content_version=?,updated_at=? WHERE id=? AND requirement_id=? AND document_type='MANUAL_DRAFT' AND content_version=?",
            (snapshot.parsed.markdown, snapshot.state_json, version, at, draft['id'], draft['requirement_id'], draft['content_version']))
        if result.rowcount != 1:
            raise ValueError('Draft version changed within the shared write transaction')
        rows = self.by_requirement(draft['requirement_id'], 'MANUAL_DRAFT')
        if len(rows) != 1 or rows[0]['id'] != draft['id']:
            raise ValueError('Updated draft is not unique')
        return rows[0]
