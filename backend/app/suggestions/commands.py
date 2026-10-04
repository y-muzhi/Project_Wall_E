"""Actual batch discard; retained decisions and source, no document adoption."""
from backend.app.documents.guards import assert_idle
from backend.app.infrastructure.batch_repository import BatchRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.infrastructure.resources import FUNCTIONS
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput
from .contracts import discard_batch_input, discard_batch_result, batch_metadata, METADATA_FIELDS, counts_model, suggestion_counts, DECISIONS
from backend.app.shared.validation import strict_enum


def discard_batch(executor: Idempotency, payload: object, *, clock=None) -> dict:
    try:
        request = discard_batch_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        repository = BatchRepository(connection)
        row = repository.get(request.batch_id)
        if row is None: raise Rejected('NOT_FOUND')
        batch = batch_metadata({field: row[field] for field in METADATA_FIELDS})
        root = RequirementRepository(connection).get(batch['requirement_id'])
        if root is None: raise Rejected('NOT_FOUND')
        if root['status'] != 'ACTIVE' or batch['status'] != 'PENDING': raise Rejected('STATE_CONFLICT')
        parent = repository.parent(row)
        if parent is None or parent['requirement_id'] != root['id'] or parent['action_type'] != 'MODIFY' or parent['status'] != 'COMPLETED' or parent['source_type'] != batch['source_type'] or parent['source_id'] != batch['source_id'] or parent['function_type'] != FUNCTIONS.get(('MODIFY', batch['source_type']), (None,))[0]:
            raise Rejected('WORK_STATE_INCONSISTENT')
        try:
            assert_idle(connection, root, remaining_conflicts=frozenset())
        except Rejected as error:
            if error.code != 'WORK_STATE_CONFLICT': raise
        if root['document_work_state'] != 'SUGGESTION_REVIEWING' or root['active_operation_type'] != 'SUGGESTION_BATCH' or root['active_operation_id'] != batch['id']:
            raise Rejected('WORK_STATE_CONFLICT')
        items = repository.suggestions(batch['id'])
        for item in items: strict_enum(item['status'], 'status', DECISIONS)
        counts_model(suggestion_counts(items))
        at = operation_time(clock)
        if batch['updated_at'] > at or root['updated_at'] > at or any(item['updated_at'] > at for item in items):
            raise ValueError('Discard cannot precede persisted aggregate activity')
        discarded = repository.discard(batch['id'], at)
        RequirementRepository(connection).recover_occupancy(root, None, None, at)
        return Success(discard_batch_result(discarded, items), 200)
    return execute_idempotent(executor, 'APP-BATCH-CMD-C03', request, operation, target_identity=f'SuggestionBatch:{request.batch_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT'}))
