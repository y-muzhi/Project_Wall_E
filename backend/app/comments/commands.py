"""APP-COMMENT-CMD-C06 joins its caller's actual CURRENT write transaction."""
import sqlite3
from backend.app.documents.anchors import locate
from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.comment_repository import CommentRepository
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import strict_json_object
from backend.app.infrastructure.idempotency import canonical_input
from .contracts import revalidate_anchors_input, revalidate_anchors_result


def revalidate_anchors(connection: sqlite3.Connection, payload: object, *, catalog: ResourceCatalog | None = None) -> dict:
    # No own transaction, error conversion, or commit: corruption aborts the outer command.
    require_write_transaction(connection)
    requirement_id, document = revalidate_anchors_input(payload)
    rows = DocumentRepository(connection).by_requirement(requirement_id, 'CURRENT')
    if len(rows) != 1:
        raise ValueError('Internal reanchoring requires unique actual CURRENT')
    sources = DocumentSources(connection, requirement_id, catalog if catalog is not None else ResourceCatalog())
    current = get_current_document_result(rows[0], sources)
    if document != {key: current[key] for key in ('markdown_content', 'block_state_json')}:
        raise ValueError('Internal snapshot must be the CURRENT written in this transaction')
    snapshot = validate_snapshot(document['markdown_content'], document['block_state_json'], sources)
    repository = CommentRepository(connection)
    attached, orphaned = [], []
    for comment in repository.live_anchors(requirement_id):
        anchor = strict_json_object(comment['anchor_ref_json'], 'anchor_ref_json')
        canonical_input(anchor)  # Reject invalid Unicode even when the original block is absent.
        found = locate(snapshot, comment['anchor_type'], comment['block_id'], anchor).attached
        repository.set_anchor_status(requirement_id, comment['id'], 'ATTACHED' if found else 'ORPHANED')
        (attached if found else orphaned).append(comment['id'])
    return revalidate_anchors_result(requirement_id, current['id'], current['content_version'], attached, orphaned)
