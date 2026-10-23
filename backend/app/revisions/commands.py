"""Mark an existing CONTENT version; never duplicate or mutate its snapshot."""
from backend.app.documents.guards import assert_idle, current_at_version
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.idempotency import Success
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput
from .contracts import create_manual_revision_input, create_manual_revision_result

def create_manual_revision(executor, payload, *, catalog=None, clock=None):
    try:
        request = create_manual_revision_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        root = RequirementRepository(connection).get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        assert_idle(connection, root, remaining_conflicts=frozenset())
        current = current_at_version(connection, request.requirement_id, request.expected_version, document_id=request.document_id)
        if current['archived_at'] is not None:
            raise Rejected('STATE_CONFLICT')
        revision = RevisionRepository(connection).current(request.document_id, request.expected_version)
        if revision is None or revision['requirement_id'] != root['id']:
            raise Rejected('DOCUMENT_INVALID')
        at = operation_time(clock)
        if at < max(current['updated_at'], root['updated_at']):
            raise ValueError('A version marker cannot precede its authoritative document')
        event_id = AuditRepository(connection).record_document_event(current, 'VERSION_MARKED', {'description': request.description, 'idempotency_key': request.idempotency_key}, at, revision_id=revision['id'])
        data = create_manual_revision_result({'revision_id': revision['id'], 'event_id': event_id, 'marked': True})
        return Success({'code': 'VERSION_MARKED', 'data': data, 'details': None}, 200)
    return execute_idempotent(executor, 'APP-REV-CMD-C01', request, operation, allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID'}))
