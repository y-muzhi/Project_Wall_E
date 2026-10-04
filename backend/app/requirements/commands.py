"""APP-REQ-CMD-C02/C03 atomic property and initialization commands."""
from datetime import datetime, timezone
import sqlite3
from typing import Callable

from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import InvalidInput
from .contracts import update_requirement_input, update_requirement_result

from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.guards import assert_idle, current_at_version
from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.snapshot import Provenance, create_snapshot, validate_snapshot, validate_template_lock
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.resources import ResourceCatalog, TemplateInvalid
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from .contracts import complete_initialization_input, complete_initialization_result


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


def complete_initialization(executor: Idempotency, payload: object, *, catalog: ResourceCatalog | None = None,
                            clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = complete_initialization_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection: sqlite3.Connection) -> Success:
        requirements, revisions = RequirementRepository(connection), RevisionRepository(connection)
        root = requirements.get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['status'] != 'INITIALIZING' or revisions.has_baseline(request.requirement_id):
            raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
        current = current_at_version(connection, request.requirement_id, request.expected_content_version)
        resources = catalog if catalog is not None else ResourceCatalog()
        try:
            template = resources.template(root['requirement_type'], root['template_key'], root['template_version'])
        except TemplateInvalid:
            raise Rejected('TEMPLATE_INVALID') from None
        sources = DocumentSources(connection, request.requirement_id, resources)
        try:
            model = get_current_document_result(current, sources)
            snapshot = validate_snapshot(model['markdown_content'], model['block_state_json'], sources)
        except (DocumentInvalid, InvalidInput, ValueError):
            raise Rejected('DOCUMENT_INVALID') from None
        # Original template IDs are allocated by the approved create_snapshot
        # algorithm, not selected from current headings by similar text.
        initial = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), current['created_at'], sources)
        locked = tuple(metadata['block_id'] for block, metadata in zip(initial.parsed.blocks, initial.state['blocks']) if block.block_type == 'heading')
        try:
            validate_template_lock(snapshot, template, locked)
        except DocumentInvalid:
            raise Rejected('TEMPLATE_INVALID') from None
        at = operation_time(clock)
        revision = revisions.insert_snapshot(entity_id(connection, EntityKind.REVISION), request.requirement_id, 1, 'BASELINE', current, '初始化基线', at)
        active = requirements.activate_initialization(request.requirement_id, at)
        data = complete_initialization_result(active, revision, current)
        return Success({'code': 'INITIALIZATION_COMPLETED', 'data': data, 'details': None}, 200)
    return execute_idempotent(executor, 'APP-REQ-CMD-C03', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT',
        'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID', 'TEMPLATE_INVALID',
    }))
