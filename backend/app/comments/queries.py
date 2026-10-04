"""Comment reads and D-004 I37 full index in one actual SQLite snapshot."""
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.comment_repository import CommentRepository
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.sources import DocumentSources
from backend.app.documents.snapshot import validate_snapshot
from backend.app.shared.validation import MISSING, InvalidInput
from backend.app.shared.command_execution import Rejected
from .contracts import get_comment_input, get_comment_result, list_comments_input, list_comments_result, get_comment_index_input, get_comment_index_result, locate_comment


def get_comment(database: Database, comment_id: object = MISSING) -> dict:
    try:
        identity = get_comment_input(comment_id)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            row = CommentRepository(connection).get(identity)
            result = {'code': 'NOT_FOUND', 'data': None, 'details': None} if row is None else {'code': 'READ_OK', 'data': get_comment_result(row), 'details': None}
        return result
    except StorageUnavailable:
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}


def _current(connection, requirement_id, catalog):
    rows = DocumentRepository(connection).by_requirement(requirement_id, 'CURRENT')
    if len(rows) != 1:
        raise Rejected('WORK_STATE_INCONSISTENT')
    sources = DocumentSources(connection, requirement_id, catalog if catalog is not None else ResourceCatalog())
    document = get_current_document_result(rows[0], sources)
    snapshot = validate_snapshot(document['markdown_content'], document['block_state_json'], sources)
    return document, snapshot


def _collection(database, payload, *, index: bool, catalog):
    try:
        request = get_comment_index_input(payload) if index else list_comments_input(payload)
        requirement_id = request if index else request.requirement_id
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            if connection.execute('SELECT 1 FROM requirements WHERE id=?', (requirement_id,)).fetchone() is None:
                raise Rejected('NOT_FOUND')
            document, snapshot = _current(connection, requirement_id, catalog)
            repository = CommentRepository(connection)
            if index:
                items = [locate_comment(row, snapshot) for row in repository.all_live(requirement_id)]
                data = get_comment_index_result(requirement_id, document, snapshot, items)
            else:
                total, rows = repository.list_page(request)
                data = list_comments_result([locate_comment(row, snapshot) for row in rows], request, total)
            result = {'code': 'READ_OK', 'data': data, 'details': None}
        return result
    except Rejected as error:
        code = error.code if index or error.code == 'NOT_FOUND' else 'INTERNAL_ERROR'
    except StorageUnavailable:
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}


def list_comments(database: Database, payload: object, *, catalog: ResourceCatalog | None = None) -> dict:
    return _collection(database, payload, index=False, catalog=catalog)


def get_comment_index(database: Database, requirement_id: object = MISSING, *, catalog: ResourceCatalog | None = None) -> dict:
    return _collection(database, requirement_id, index=True, catalog=catalog)
