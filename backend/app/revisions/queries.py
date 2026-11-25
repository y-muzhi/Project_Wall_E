"""Historical reads; never substitute current body, comments or source versions."""

from backend.app.documents.sources import DocumentSources
from backend.app.documents.drawing import is_drawing, validate_drawing
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.shared.validation import InvalidInput, MISSING
from .contracts import get_revision_input, get_revision_result, list_revisions_input


def list_revisions(database: Database, payload: object = MISSING) -> dict:
    try:
        request = list_revisions_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            repository = RevisionRepository(connection)
            if not repository.document_exists(request.requirement_id, request.document_id):
                result = {'code': 'NOT_FOUND', 'data': None, 'details': None}
            else:
                result = {'code': 'READ_OK', 'data': repository.list_page(request), 'details': None}
        return result
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def get_revision(
    database: Database, revision_id: object = MISSING, *, catalog: ResourceCatalog | None = None
) -> dict:
    try:
        identity = get_revision_input(revision_id)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            row = RevisionRepository(connection).get(identity)
            if row is None:
                result = {'code': 'NOT_FOUND', 'data': None, 'details': None}
            else:
                document = DocumentRepository(connection).get_current(
                    row['requirement_id'], row['document_id']
                )
                if document is not None and is_drawing(document):
                    validate_drawing(row['markdown_snapshot'])
                sources = DocumentSources(
                    connection,
                    row['requirement_id'],
                    catalog if catalog is not None else ResourceCatalog(),
                    document_id=row['document_id'],
                )
                result = {
                    'code': 'READ_OK',
                    'data': get_revision_result(row, sources),
                    'details': None,
                }
        return result
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
