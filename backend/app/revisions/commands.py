"""APP-REV-CMD-C01 immutable current snapshot and persistent success together."""
from datetime import datetime
import sqlite3
from typing import Callable

from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.guards import assert_idle, current_at_version
from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id, revision_number
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog, TemplateInvalid
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput
from .contracts import create_manual_revision_input, create_manual_revision_result


def create_manual_revision(executor: Idempotency, payload: object, *, catalog: ResourceCatalog | None = None,
                           clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = create_manual_revision_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection: sqlite3.Connection) -> Success:
        root = RequirementRepository(connection).get(request.current.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['status'] != 'ACTIVE':
            raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT'}))
        revisions = RevisionRepository(connection)
        if not revisions.has_baseline(root['id']):
            raise Rejected('WORK_STATE_INCONSISTENT')
        current = current_at_version(connection, request.current.requirement_id, request.current.expected_content_version)
        sources = DocumentSources(connection, request.current.requirement_id, catalog if catalog is not None else ResourceCatalog())
        try:
            get_current_document_result(current, sources)
        except (DocumentInvalid, InvalidInput, ValueError, TemplateInvalid):
            raise Rejected('DOCUMENT_INVALID') from None
        number = revision_number(connection, request.current.requirement_id)
        if number == 1:
            # ACTIVE without a baseline is a broken relation, not a substitute baseline.
            raise Rejected('WORK_STATE_INCONSISTENT')
        row = revisions.insert_snapshot(entity_id(connection, EntityKind.REVISION), root['id'], number, 'MANUAL', current, request.description, operation_time(clock))
        return Success({'code': 'REVISION_CREATED', 'data': create_manual_revision_result(row), 'details': None}, 201)
    return execute_idempotent(executor, 'APP-REV-CMD-C01', request.current, operation,
                              business_input=request.business_input(), allowed_failures=frozenset({
                                  'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT',
                                  'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID',
                              }))
