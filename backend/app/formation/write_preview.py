"""Read-only exact write proof shared by publication and later explicit adoption."""

from backend.app.documents.content import validate_structure
from backend.app.documents.markdown import parse_markdown
from backend.app.documents.patch_application import preview_patches
from backend.app.documents.scopes import resolve_scope
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import strict_json_object


def prepare_write(connection, root, payload, catalog, *, carried_block_ids=None):
    current = DocumentRepository(connection).get_current(root['id'], root['assistant_document_id'])
    revision = (
        connection.execute(
            'SELECT id FROM revisions WHERE document_id=? AND source_content_version=?',
            (current['id'], current['content_version']),
        ).fetchone()
        if current is not None
        else None
    )
    if current is None or current['archived_at'] is not None or revision is None:
        raise Rejected('SOURCE_INVALID')
    if (payload['document_revision_id'], payload['content_version']) != (
        revision['id'],
        current['content_version'],
    ):
        raise Rejected('CONTENT_VERSION_CONFLICT')
    prior = validate_snapshot(
        current['markdown_content'],
        strict_json_object(current['block_state_json']),
        DocumentSources(connection, root['id'], catalog, document_id=current['id']),
    )
    scope = payload['scope']
    reference = scope['scope_ref']
    if scope['scope_type'] == 'SECTION':
        reference = {'block_id': reference['heading_block_id']}
    authority = resolve_scope(prior, 'MODIFY', scope['scope_type'], reference)
    if carried_block_ids is not None and not set(authority.focus_ids) <= set(carried_block_ids):
        raise Rejected('SOURCE_INVALID')
    if payload['write_mode'] == 'FILL_EMPTY':
        if (
            current['markdown_content'].strip()
            or prior.by_id
            or not parse_markdown(payload['markdown_content']).blocks
        ):
            raise Rejected('DOCUMENT_INVALID')
        preview = None
        markdown = payload['markdown_content']
    else:
        if not prior.by_id:
            raise Rejected('DOCUMENT_INVALID')
        preview = preview_patches(prior, payload['patches'], authority)
        validate_structure(preview, prior, current, catalog)
        markdown = preview.markdown
    return current, prior, authority, markdown
