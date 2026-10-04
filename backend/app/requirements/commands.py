"""APP-REQ-CMD-C02 short atomic attribute update, independent of HTTP."""
from datetime import datetime, timezone
import sqlite3
from typing import Callable

from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import InvalidInput
from .contracts import update_requirement_input, update_requirement_result


def update_requirement(database: Database, payload: object, *, clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = update_requirement_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
    try:
        with database.transaction(write=True) as connection:
            repository = RequirementRepository(connection)
            current = repository.get(request.requirement_id)
            code = None
            if current is None:
                code = 'NOT_FOUND'
            elif ('title' in request.changes and current['status'] not in ('INITIALIZING', 'ACTIVE') or
                  'initialization_mode' in request.changes and current['status'] != 'INITIALIZING'):
                code = 'STATE_CONFLICT'
            elif 'initialization_mode' in request.changes and current['document_work_state'] != 'IDLE':
                code = 'WORK_STATE_CONFLICT'
            if code is not None:
                result = {'code': code, 'data': None, 'details': None}
            else:
                changes = {field: value for field, value in request.changes.items() if current[field] != value}
                if changes:
                    at = utc_milliseconds(clock() if clock is not None else datetime.now(timezone.utc))
                    if at is None:
                        raise ValueError('Operation clock must provide a real instant')
                    current = repository.update_attributes(request.requirement_id, changes, at)
                result = {'code': 'UPDATED', 'data': update_requirement_result(current), 'details': None}
        # The only success exit follows the outer transaction's actual commit.
        return result
    except (StorageUnavailable, sqlite3.Error):
        return {'code': 'STORAGE_UNAVAILABLE', 'data': None, 'details': None}
    except Exception:
        return {'code': 'INTERNAL_ERROR', 'data': None, 'details': None}
