"""Per-snapshot read material cache; loading a view never counts tokens or changes state."""

from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_object

from .artifact_links import block_digest
from .availability import work_reason
from .repository import FormationRepository
from .source_semantics import source_digest


class ReadContext:
    def __init__(self, connection, root, resources):
        self.connection = connection
        self.root = root
        self.resources = resources
        self.document_id = root['assistant_document_id']
        self.repository = FormationRepository(connection)
        self.head = self.repository.head(self.document_id, required=True)
        self.busy = work_reason(connection, root)
        self._current = None
        self._blocks = None
        self._source_heads = {}

    @property
    def current(self):
        if self._current is None:
            self._current = self.connection.execute(
                'SELECT d.*,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
                'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? AND d.requirement_id=?',
                (self.document_id, self.root['id']),
            ).fetchone()
            if self._current is None:
                raise ValueError('Current document lost its immutable Revision')
        return self._current

    @property
    def blocks(self):
        if self._blocks is None:
            snapshot = validate_snapshot(
                self.current['markdown_content'],
                strict_json_object(self.current['block_state_json']),
                DocumentSources(
                    self.connection, self.root['id'], self.resources, document_id=self.document_id
                ),
            )
            self._blocks = snapshot.by_id
        return self._blocks

    def coverage_matches(self, coverage):
        return all(
            item['block_id'] in self.blocks
            and block_digest(self.blocks[item['block_id']][0].markdown) == item['block_digest']
            for item in coverage
        )

    def source_head(self, source):
        key = canonical_input(source)
        if key not in self._source_heads:
            self._source_heads[key] = source_digest(
                self.connection, self.root['id'], source, self.resources.collaboration
            )
        return self._source_heads[key]

    def source_status(self, source):
        try:
            self.source_head(source)
        except ConfigInvalid:
            return {
                'source_ref': source,
                'availability': 'UNSUPPORTED',
                'reason': 'RESOURCE_UNSUPPORTED',
            }
        except (Rejected, ValueError, TypeError):
            return {'source_ref': source, 'availability': 'MISSING', 'reason': 'SOURCE_MISSING'}
        return {'source_ref': source, 'availability': 'AVAILABLE', 'reason': None}
