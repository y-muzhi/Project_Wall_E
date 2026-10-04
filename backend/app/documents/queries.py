"""Current/draft read capabilities, actual source lookup and no write effects."""
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import InvalidInput, MISSING
from .contracts import (
    get_current_document_input, get_current_document_result,
    get_manual_draft_input, get_manual_draft_result,
)
from .sources import DocumentSources


def _read_document(database: Database, identity: object, *, manual: bool, catalog: ResourceCatalog | None) -> dict:
    try:
        requirement_id = (get_manual_draft_input if manual else get_current_document_input)(identity)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            root = RequirementRepository(connection).get(requirement_id)
            code, data = 'READ_OK', None
            if root is None:
                code = 'NOT_FOUND'
            else:
                kind = 'MANUAL_DRAFT' if manual else 'CURRENT'
                rows = DocumentRepository(connection).by_requirement(requirement_id, kind)
                if not manual:
                    if len(rows) != 1:
                        code = 'WORK_STATE_INCONSISTENT'
                elif not rows:
                    code = 'WORK_STATE_INCONSISTENT' if root['active_operation_type'] == 'MANUAL_DRAFT' else 'MANUAL_DRAFT_NOT_FOUND'
                elif (len(rows) != 1 or root['document_work_state'] != 'MANUAL_EDITING' or
                      root['active_operation_type'] != 'MANUAL_DRAFT' or root['active_operation_id'] != rows[0]['id']):
                    code = 'WORK_STATE_INCONSISTENT'
                if code == 'READ_OK':
                    sources = DocumentSources(connection, requirement_id, catalog if catalog is not None else ResourceCatalog())
                    data = (get_manual_draft_result if manual else get_current_document_result)(rows[0], sources)
            result = {'code': code, 'data': data, 'details': None}
        return result
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def get_current_document(database: Database, requirement_id: object = MISSING, *, catalog: ResourceCatalog | None = None) -> dict:
    return _read_document(database, requirement_id, manual=False, catalog=catalog)


def get_manual_draft(database: Database, requirement_id: object = MISSING, *, catalog: ResourceCatalog | None = None) -> dict:
    return _read_document(database, requirement_id, manual=True, catalog=catalog)
