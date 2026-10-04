"""APP-GUIDE-QUERY-C01 same-snapshot status references without audit/Prompt reads."""
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import MISSING, InvalidInput
from .contracts import get_guide_run_input, get_guide_run_result


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
