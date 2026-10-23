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


def current_document_view(connection, row, catalog):
    from .contracts import document_view
    from .snapshot import validate_snapshot
    from backend.app.shared.validation import strict_json_object
    source = DocumentSources(connection, row['requirement_id'], catalog, document_id=row['id'])
    state = strict_json_object(row['block_state_json'])
    validate_snapshot(row['markdown_content'], state, source)
    summary = next(item for item in DocumentRepository(connection).list_current_summaries(row['requirement_id']) if item['id'] == row['id'])
    return document_view({**summary, 'markdown_content': row['markdown_content'], 'block_state_json': state,
        'template_ref': None if row['template_ref'] is None else strict_json_object(row['template_ref']), 'created_at': row['created_at']})


def get_current_document(database: Database, requirement_id: object = MISSING, document_id: object = MISSING, *, catalog: ResourceCatalog | None = None) -> dict:
    from backend.app.shared.validation import strict_integer
    try:
        requirement_id = strict_integer(requirement_id, 'requirement_id')
        document_id = strict_integer(document_id, 'document_id')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            row = DocumentRepository(connection).get_current(requirement_id, document_id)
            data = None if row is None else current_document_view(connection, row, catalog if catalog is not None else ResourceCatalog())
        return {'code': 'NOT_FOUND' if data is None else 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def get_manual_draft(database: Database, requirement_id: object = MISSING, document_id: object = MISSING, *, catalog=None) -> dict:
    from backend.app.shared.validation import strict_integer
    try:
        requirement_id = strict_integer(requirement_id, 'requirement_id')
        document_id = strict_integer(document_id, 'document_id')
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            root = RequirementRepository(connection).get(requirement_id)
            documents = DocumentRepository(connection)
            current = documents.get_current(requirement_id, document_id)
            if root is None or current is None:
                return {'code': 'NOT_FOUND', 'data': None, 'details': None}
            rows = documents.by_requirement(requirement_id, 'MANUAL_DRAFT')
            if not rows:
                code = 'WORK_STATE_INCONSISTENT' if root['active_operation_type'] == 'MANUAL_DRAFT' else 'MANUAL_DRAFT_NOT_FOUND'
                return {'code': code, 'data': None, 'details': None}
            if len(rows) != 1 or root['document_work_state'] != 'MANUAL_EDITING' or root['active_operation_type'] != 'MANUAL_DRAFT' or root['active_operation_id'] != rows[0]['id']:
                return {'code': 'WORK_STATE_INCONSISTENT', 'data': None, 'details': None}
            if rows[0]['target_document_id'] != document_id:
                return {'code': 'MANUAL_DRAFT_NOT_FOUND', 'data': None, 'details': None}
            sources = DocumentSources(connection, requirement_id, catalog if catalog is not None else ResourceCatalog(), document_id=document_id)
            data = get_manual_draft_result(rows[0], sources)
        return {'code': 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
