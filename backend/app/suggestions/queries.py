"""APP-BATCH-QUERY-C01: complete immutable read, no Patch application."""
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.batch_repository import BatchRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import MISSING, InvalidInput
from .contracts import get_batch_input, get_batch_result


def get_batch(database: Database, batch_id: object = MISSING, *, catalog: ResourceCatalog | None = None) -> dict:
    try:
        identity = get_batch_input(batch_id)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction() as connection:
            repository = BatchRepository(connection)
            row = repository.get(identity)
            if row is None:
                result = {'code': 'NOT_FOUND', 'data': None, 'details': None}
            else:
                parent = repository.parent(row)
                if parent is None or parent['requirement_id'] != row['requirement_id'] or parent['action_type'] != 'MODIFY' or parent['status'] != 'COMPLETED' or parent['source_type'] != row['source_type'] or parent['source_id'] != row['source_id']:
                    raise ValueError('Batch must belong to its actual completed MODIFY source run')
                if connection.execute('SELECT 1 FROM requirements WHERE id=?', (row['requirement_id'],)).fetchone() is None:
                    raise ValueError('Batch requirement is missing')
                if row['source_type'] != 'USER_INSTRUCTION':
                    if row['source_type'] == 'COMMENT':
                        source = connection.execute('SELECT requirement_id FROM comments WHERE id=?', (row['source_id'],)).fetchone()
                    else:
                        source = connection.execute("SELECT requirement_id FROM guide_runs WHERE id=? AND action_type='REVIEW' AND status='COMPLETED'", (row['source_id'],)).fetchone()
                    if source is None or source['requirement_id'] != row['requirement_id']:
                        raise ValueError('Historical source must belong to the same requirement')
                resources = catalog if catalog is not None else ResourceCatalog()
                protocol = resources.freeze('MODIFY', row['source_type'])
                if parent['function_type'] != protocol.function_type:
                    raise ValueError('Batch source must match its parent frozen Function')
                result = {'code': 'READ_OK', 'data': get_batch_result(row, repository.suggestions(identity), protocol=protocol), 'details': None}
        return result
    except StorageUnavailable:
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}
