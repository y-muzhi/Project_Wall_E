"""APP-GUIDE-QUERY-C01 same-snapshot status references without audit/Prompt reads."""
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import MISSING, InvalidInput
from .contracts import get_guide_run_input, get_guide_run_result
from .contracts import list_guide_runs_input, list_guide_runs_result
from .model_context import get_model_context


def get_guide_run(database: Database, guide_run_id: object = MISSING, *, catalog: ResourceCatalog | None = None) -> dict:
    try:
        identity = get_guide_run_input(guide_run_id)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            repository = GuideRepository(connection)
            row = repository.get_status(identity)
            if row is None:
                result = {'code': 'NOT_FOUND', 'data': None, 'details': None}
            else:
                message, batches = repository.status_references(row)
                result = {'code': 'READ_OK', 'data': get_guide_run_result(connection, row, message, batches, catalog=catalog), 'details': None}
        return result
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def list_guide_runs(database: Database, payload: object) -> dict:
    try:
        request = list_guide_runs_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            if connection.execute('SELECT 1 FROM requirements WHERE id=?', (request.requirement_id,)).fetchone() is None:
                result = {'code': 'NOT_FOUND', 'data': None, 'details': None}
            else:
                repository = GuideRepository(connection)
                total, rows = repository.list_history(request)
                items = []
                for row in rows:
                    message, batches = repository.status_references(row)
                    items.append(get_guide_run_result(connection, row, message, batches, summary=True))
                result = {'code': 'READ_OK', 'data': list_guide_runs_result(items, request, total), 'details': None}
        return result
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
