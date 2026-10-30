"""INF-DOC-REP fixed document-kind reads on the caller's SQLite snapshot."""

import sqlite3

from backend.app.documents.contracts import DOCUMENT_FIELDS
from .identifiers import require_write_transaction


class DocumentRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def list_current_summaries(self, requirement_id: int) -> list[dict]:
        from backend.app.documents.contracts import document_summary
        import json

        rows = self.connection.execute(
            "SELECT d.*,r.id AS current_revision_id,r.source_refs_json FROM requirement_documents d LEFT JOIN revisions r ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.requirement_id=? AND d.document_type='CURRENT' ORDER BY d.created_at,d.id",
            (requirement_id,),
        ).fetchall()
        result = []
        for row in rows:
            status = 'UNCHANGED'
            sources = (
                json.loads(row['source_refs_json']) if row['source_refs_json'] is not None else []
            )
            for source in sources:
                if source['kind'] != 'REVISION' or source['document_id'] == row['id']:
                    continue
                previous = self.connection.execute(
                    'SELECT requirement_id,document_id,source_content_version FROM revisions WHERE id=?',
                    (source['revision_id'],),
                ).fetchone()
                head = self.connection.execute(
                    "SELECT requirement_id,content_version FROM requirement_documents WHERE id=? AND document_type='CURRENT'",
                    (source['document_id'],),
                ).fetchone()
                if (
                    previous is None
                    or head is None
                    or previous['document_id'] != source['document_id']
                    or head['requirement_id'] != requirement_id
                    or previous['requirement_id'] != requirement_id
                ):
                    status = 'UNAVAILABLE'
                    break
                if head['content_version'] != previous['source_content_version']:
                    status = 'UPDATED'
            keys = (
                'id',
                'requirement_id',
                'name',
                'document_kind',
                'document_type',
                'metadata_version',
                'content_version',
                'current_revision_id',
                'confirmed_revision_id',
                'archived_at',
                'updated_at',
            )
            result.append(
                document_summary({**{key: row[key] for key in keys}, 'source_status': status})
            )
        return result

    def by_requirement(self, requirement_id: int, document_type: str) -> list[sqlite3.Row]:
        if document_type not in ('CURRENT', 'MANUAL_DRAFT'):
            raise ValueError('Unregistered document type')
        # A query never chooses arbitrarily if persisted uniqueness is broken.
        return self.connection.execute(
            'SELECT d.*,c.base_content_version FROM requirement_documents d LEFT JOIN manual_draft_context c ON c.draft_id=d.id WHERE d.requirement_id=? AND d.document_type=? ORDER BY d.created_at,d.id',
            (requirement_id, document_type),
        ).fetchall()

    def get_current(self, requirement_id: int, document_id: int):
        return self.connection.execute(
            "SELECT * FROM requirement_documents WHERE id=? AND requirement_id=? AND document_type='CURRENT'",
            (document_id, requirement_id),
        ).fetchone()

    def create_current(
        self,
        identity: int,
        requirement_id: int,
        snapshot,
        at: str,
        *,
        name: str,
        document_kind: str,
        template_ref,
        origin,
    ) -> sqlite3.Row:
        from .idempotency import canonical_input

        require_write_transaction(self.connection)
        self.connection.execute(
            "INSERT INTO requirement_documents(id,requirement_id,document_type,markdown_content,block_state_json,content_version,created_at,updated_at,name,document_kind,metadata_version,archived_at,confirmed_revision_id,target_document_id,template_ref,origin) VALUES (?,?,'CURRENT',?,?,1,?,?,?,?,1,NULL,NULL,NULL,?,?)",
            (
                identity,
                requirement_id,
                snapshot.parsed.markdown,
                snapshot.state_json,
                at,
                at,
                name,
                document_kind,
                None if template_ref is None else canonical_input(template_ref),
                canonical_input(origin),
            ),
        )
        return self.get_current(requirement_id, identity)

    def update_metadata(self, current, changes: dict, at: str):
        from .identifiers import increment

        require_write_transaction(self.connection)
        if not changes or not set(changes) <= {'name', 'archived_at', 'confirmed_revision_id'}:
            raise ValueError('Invalid document metadata fields')
        values = {
            **changes,
            'metadata_version': increment(current['metadata_version']),
            'updated_at': at,
        }
        result = self.connection.execute(
            'UPDATE requirement_documents SET '
            + ','.join(key + '=?' for key in values)
            + " WHERE id=? AND requirement_id=? AND document_type='CURRENT' AND metadata_version=?",
            (
                *values.values(),
                current['id'],
                current['requirement_id'],
                current['metadata_version'],
            ),
        )
        if result.rowcount != 1:
            raise ValueError('Document metadata changed inside shared transaction')
        return self.get_current(current['requirement_id'], current['id'])

    def create_manual_draft(self, identity: int, current: sqlite3.Row, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        if current['document_type'] != 'CURRENT' or identity == current['id']:
            raise ValueError('Draft must have an independent identity from real CURRENT')
        self.connection.execute(
            "INSERT INTO requirement_documents(id,requirement_id,document_type,markdown_content,block_state_json,content_version,created_at,updated_at,name,document_kind,metadata_version,archived_at,confirmed_revision_id,target_document_id,template_ref,origin) VALUES (?,?,'MANUAL_DRAFT',?,?,1,?,?,?,?,1,NULL,NULL,?,?,?)",
            (
                identity,
                current['requirement_id'],
                current['markdown_content'],
                current['block_state_json'],
                at,
                at,
                current['name'],
                current['document_kind'],
                current['id'],
                current['template_ref'],
                current['origin'],
            ),
        )
        self.connection.execute(
            "INSERT INTO manual_draft_context(draft_id,current_document_id,base_content_version,baseline_block_state_json,operation_time,source_refs_json) VALUES (?,?,?,?,?,'[]')",
            (identity, current['id'], current['content_version'], current['block_state_json'], at),
        )
        rows = self.by_requirement(current['requirement_id'], 'MANUAL_DRAFT')
        if len(rows) != 1 or rows[0]['id'] != identity:
            raise ValueError('Inserted draft is not unique')
        return rows[0]

    def delete_manual_draft(self, draft: sqlite3.Row) -> None:
        require_write_transaction(self.connection)
        if draft['document_type'] != 'MANUAL_DRAFT':
            raise ValueError('Draft deletion cannot delete CURRENT')
        self.connection.execute('DELETE FROM manual_block_origins WHERE draft_id=?', (draft['id'],))
        self.connection.execute(
            'DELETE FROM manual_block_allocation_ranges WHERE draft_id=?', (draft['id'],)
        )
        context = self.connection.execute(
            'DELETE FROM manual_draft_context WHERE draft_id=?', (draft['id'],)
        )
        document = self.connection.execute(
            "DELETE FROM requirement_documents WHERE id=? AND requirement_id=? AND document_type='MANUAL_DRAFT'",
            (draft['id'], draft['requirement_id']),
        )
        if context.rowcount != 1 or document.rowcount != 1:
            raise ValueError('Draft or its context disappeared in shared transaction')

    def save_manual_draft(self, draft: sqlite3.Row, snapshot, version: int, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        result = self.connection.execute(
            "UPDATE requirement_documents SET markdown_content=?,block_state_json=?,content_version=?,updated_at=? WHERE id=? AND requirement_id=? AND document_type='MANUAL_DRAFT' AND content_version=?",
            (
                snapshot.parsed.markdown,
                snapshot.state_json,
                version,
                at,
                draft['id'],
                draft['requirement_id'],
                draft['content_version'],
            ),
        )
        if result.rowcount != 1:
            raise ValueError('Draft version changed within the shared write transaction')
        rows = self.by_requirement(draft['requirement_id'], 'MANUAL_DRAFT')
        if len(rows) != 1 or rows[0]['id'] != draft['id']:
            raise ValueError('Updated draft is not unique')
        return rows[0]

    def replace_current(self, current: sqlite3.Row, snapshot, version: int, at: str) -> sqlite3.Row:
        require_write_transaction(self.connection)
        if current['document_type'] != 'CURRENT':
            raise ValueError('Replacement must preserve actual CURRENT identity')
        result = self.connection.execute(
            "UPDATE requirement_documents SET markdown_content=?,block_state_json=?,content_version=?,updated_at=? WHERE id=? AND requirement_id=? AND document_type='CURRENT' AND content_version=?",
            (
                snapshot.parsed.markdown,
                snapshot.state_json,
                version,
                at,
                current['id'],
                current['requirement_id'],
                current['content_version'],
            ),
        )
        if result.rowcount != 1:
            raise ValueError('CURRENT changed within the shared write transaction')
        return self.get_current(current['requirement_id'], current['id'])
