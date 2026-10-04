"""INF-DOC-REP fixed document-kind reads on the caller's SQLite snapshot."""
import sqlite3

from backend.app.documents.contracts import DOCUMENT_FIELDS


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
