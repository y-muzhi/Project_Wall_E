"""Immutable document CONTENT snapshots with separate version marker events."""

import json
from backend.app.revisions.contracts import list_revisions_result
from backend.app.shared.pagination import PAGE_SIZE, page_offset
from .identifiers import require_write_transaction


class RevisionRepository:
    def __init__(self, connection):
        self.connection = connection

    def insert_content(self, identity, document, source_refs, change_summary, at):
        from .idempotency import canonical_input
        from .schema_transport import compact

        require_write_transaction(self.connection)
        canonical_input({'refs': source_refs})
        if document['document_type'] != 'CURRENT':
            raise ValueError('Only actual CURRENT content may be snapshotted')
        self.connection.execute(
            "INSERT INTO revisions(id,requirement_id,document_id,version_no,revision_type,markdown_snapshot,block_state_snapshot_json,description,source_content_version,created_at,source_refs_json,change_summary) VALUES (?,?,?,?,'CONTENT',?,?,NULL,?,?,?,?)",
            (
                identity,
                document['requirement_id'],
                document['id'],
                document['content_version'],
                document['markdown_content'],
                document['block_state_json'],
                document['content_version'],
                at,
                compact(source_refs),
                change_summary,
            ),
        )
        return self.get(identity)

    def document_exists(self, requirement_id, document_id):
        return (
            self.connection.execute(
                "SELECT 1 FROM requirement_documents WHERE id=? AND requirement_id=? AND document_type='CURRENT'",
                (document_id, requirement_id),
            ).fetchone()
            is not None
        )

    def _project(self, row):
        if row is None:
            return None
        if row['revision_type'] != 'CONTENT' or row['description'] is not None:
            raise ValueError('Only immutable CONTENT snapshots are valid in the new data model')
        data = dict(row)
        data['source_refs'] = json.loads(data['source_refs_json'])
        events = self.connection.execute(
            "SELECT id,created_at,payload_json FROM document_change_audits WHERE requirement_id=? AND document_id=? AND revision_id=? AND event_type='VERSION_MARKED' ORDER BY created_at,id",
            (row['requirement_id'], row['document_id'], row['id']),
        ).fetchall()
        data['markers'] = []
        for event in events:
            payload = json.loads(event['payload_json'])
            if set(payload) != {'description', 'idempotency_key'}:
                raise ValueError('Invalid marker event payload')
            data['markers'].append(
                {
                    'event_id': event['id'],
                    'description': payload['description'],
                    'created_at': event['created_at'],
                }
            )
        return data

    def list_page(self, request):
        total = self.connection.execute(
            'SELECT count(*) FROM revisions WHERE requirement_id=? AND document_id=?',
            (request.requirement_id, request.document_id),
        ).fetchone()[0]
        rows = self.connection.execute(
            'SELECT * FROM revisions WHERE requirement_id=? AND document_id=? ORDER BY source_content_version DESC,id DESC LIMIT ? OFFSET ?',
            (request.requirement_id, request.document_id, PAGE_SIZE, page_offset(request.page)),
        ).fetchall()
        return list_revisions_result([self._project(row) for row in rows], request.page, total)

    def get(self, identity):
        return self._project(
            self.connection.execute('SELECT * FROM revisions WHERE id=?', (identity,)).fetchone()
        )

    def current(self, document_id, version):
        return self._project(
            self.connection.execute(
                'SELECT * FROM revisions WHERE document_id=? AND source_content_version=?',
                (document_id, version),
            ).fetchone()
        )
