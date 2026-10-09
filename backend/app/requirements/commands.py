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
from .contracts import (
    complete_initialization_input, complete_initialization_result,
    complete_requirement_input, complete_requirement_result,
    reactivate_requirement_input, reactivate_requirement_result,
)
from .contracts import create_requirement_input, create_requirement_result
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.identifiers import requirement_number
from backend.app.documents.scopes import resolve_scope


def create_requirement(executor: Idempotency, payload: object, *, catalog: ResourceCatalog | None = None,
                       clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = create_requirement_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection: sqlite3.Connection) -> Success:
        try:
            resources = catalog if catalog is not None else ResourceCatalog()
            template = resources.template(request.requirement_type, request.template_key, request.template_version)
            function = resources.freeze('INITIALIZE', 'USER_INSTRUCTION')
        except TemplateInvalid:
            raise Rejected('TEMPLATE_INVALID') from None
        except ConfigInvalid:
            raise Rejected('CONFIG_INVALID') from None
        at = operation_time(clock)
        identity = entity_id(connection, EntityKind.REQUIREMENT)
        document_id = entity_id(connection, EntityKind.DOCUMENT)
        message_id = entity_id(connection, EntityKind.MESSAGE)
        guide_id = entity_id(connection, EntityKind.GUIDE_RUN)
        root = RequirementRepository(connection).create(identity, requirement_number(connection), request, guide_id, at)
        sources = DocumentSources(connection, identity, resources)
        snapshot = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), at, sources)
        current = DocumentRepository(connection).create_current(document_id, identity, snapshot, at)
        get_current_document_result(current, sources)
        message = MessageRepository(connection).create_user_text(message_id, identity, guide_id, request.initial_idea, request.idempotency_key, at)
        scope = resolve_scope(snapshot, 'INITIALIZE', 'DOCUMENT')
        context_key, context_version = function.context_template.split('@')
        prompt_key, prompt_version = function.prompt_reference.split('@')
        manifest = {'document_id': document_id, 'content_version': current['content_version'], 'block_ids': list(scope.read_ids),
            'message_ids': [message_id], 'template': {'key': template.key, 'version': template.version},
            'source': {'source_type': 'USER_INSTRUCTION', 'source_id': None},
            'context_template': {'key': context_key, 'version': context_version},
            'prompt': {'key': prompt_key, 'version': prompt_version}, 'function_type': function.function_type}
        function.validate_allowed_targets({'schema_version': 1, 'targets': scope.targets_json})
        manifest = function.validate_read_manifest(manifest)
        GuideRepository(connection).accept_initialization(guide_id, root, message, function, scope, manifest, at)
        data = create_requirement_result(root, document_id, guide_id)
        return Success({'code': 'CREATED', 'data': data, 'details': None}, 201)

    return execute_idempotent(executor, 'APP-REQ-CMD-C01', request, operation,
        allowed_failures=frozenset({'TEMPLATE_INVALID', 'CONFIG_INVALID'}), target_identity='Requirements')


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
            elif current['status'] not in ('INITIALIZING', 'ACTIVE'):
                code = 'STATE_CONFLICT'
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


def complete_requirement(executor: Idempotency, payload: object, *, clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = complete_requirement_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection: sqlite3.Connection) -> Success:
        repository = RequirementRepository(connection)
        root = repository.get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['status'] != 'ACTIVE':
            raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
        current_at_version(connection, request.requirement_id, request.expected_content_version)
        row = repository.change_lifecycle(request.requirement_id, 'ACTIVE', 'COMPLETED', operation_time(clock))
        return Success({'code': 'REQUIREMENT_COMPLETED', 'data': complete_requirement_result(row), 'details': None}, 200)
    return execute_idempotent(executor, 'APP-REQ-CMD-C04', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT',
    }))


def reactivate_requirement(executor: Idempotency, payload: object, *, clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = reactivate_requirement_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection: sqlite3.Connection) -> Success:
        repository = RequirementRepository(connection)
        root = repository.get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['status'] != 'COMPLETED':
            raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset())
        row = repository.change_lifecycle(request.requirement_id, 'COMPLETED', 'ACTIVE', operation_time(clock))
        return Success({'code': 'REACTIVATED', 'data': reactivate_requirement_result(row), 'details': None}, 200)
    return execute_idempotent(executor, 'APP-REQ-CMD-C05', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT',
    }))
