"""APP-REQ-QUERY-C01/C02; application result triads, no HTTP or write side effects."""
from collections.abc import Callable

from backend.app.infrastructure.database import Database, SchemaMismatch, StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.validation import InvalidInput, MISSING
from .contracts import get_requirement_input, get_requirement_result, list_requirements_input


def _query(database: Database, validate: Callable, read: Callable, *, not_found: bool = False) -> dict:
    try:
        request = validate()
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
    # Validation of persisted fields must never be reported as caller input failure.
    try:
        with database.transaction() as connection:
            data = read(RequirementRepository(connection), request)
        return {'code': 'NOT_FOUND' if not_found and data is None else 'READ_OK', 'data': data, 'details': None}
    except StorageUnavailable:
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except SchemaMismatch:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}


def list_requirements(database: Database, payload: object = MISSING) -> dict:
    return _query(database, lambda: list_requirements_input({} if payload is MISSING else payload),
                  lambda repository, request: repository.list_page(request))


def get_requirement(database: Database, requirement_id: object = MISSING) -> dict:
    def read(repository: RequirementRepository, identity: int) -> dict | None:
        model = repository.get(identity)
        return None if model is None else get_requirement_result(model)
    return _query(database, lambda: get_requirement_input(requirement_id), read, not_found=True)
