"""APP-DOC-CMD-C01/C04: independent drafts and durable edit sessions together."""
from datetime import datetime
import sqlite3
from typing import Callable

from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput
from .contracts import (
    get_current_document_result, start_manual_draft_input, start_manual_draft_result,
    cancel_manual_draft_input, cancel_manual_draft_result,
)
from .guards import active_manual_draft, assert_idle, current_at_version
from .sources import DocumentSources, close_edit_session, register_edit_session


def start_manual_draft(executor: Idempotency, payload: object, *, catalog: ResourceCatalog | None = None,
                        clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = start_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection: sqlite3.Connection) -> Success:
        requirements = RequirementRepository(connection)
        root = requirements.get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['status'] not in ('INITIALIZING', 'ACTIVE'):
            raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
        current = current_at_version(connection, request.requirement_id, request.expected_content_version)
        sources = DocumentSources(connection, request.requirement_id, catalog if catalog is not None else ResourceCatalog())
        get_current_document_result(current, sources)
        at = operation_time(clock)
        draft = DocumentRepository(connection).create_manual_draft(entity_id(connection, EntityKind.DOCUMENT), current, at)
        register_edit_session(connection, draft['id'], at)
        occupied = requirements.occupy_manual_draft(request.requirement_id, draft['id'], at)
        data = start_manual_draft_result(draft, occupied, sources)
        return Success({'code': 'DRAFT_STARTED', 'data': data, 'details': None}, 201)
    return execute_idempotent(executor, 'APP-DOC-CMD-C01', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT',
    }))


def cancel_manual_draft(executor: Idempotency, payload: object, *, clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = cancel_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection: sqlite3.Connection) -> Success:
        requirements = RequirementRepository(connection)
        root = requirements.get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        draft = active_manual_draft(connection, root)
        if draft['content_version'] != request.expected_version:
            raise Rejected('CONTENT_VERSION_CONFLICT')
        at = operation_time(clock)
        DocumentRepository(connection).delete_manual_draft(draft)
        requirements.release_manual_draft(root['id'], draft['id'], at)
        close_edit_session(connection, draft['id'], 'CANCELLED', at)
        data = cancel_manual_draft_result(root['id'], draft['id'])
        return Success({'code': 'DRAFT_CANCELLED', 'data': data, 'details': None}, 200)
    return execute_idempotent(executor, 'APP-DOC-CMD-C04', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT',
    }))
