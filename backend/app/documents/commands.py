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
    get_current_document_result, get_manual_draft_result, start_manual_draft_input, start_manual_draft_result,
    cancel_manual_draft_input, cancel_manual_draft_result,
)
from .guards import active_manual_draft, assert_idle, current_at_version
from .sources import DocumentSources, close_edit_session, register_edit_session

from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.identifiers import increment, CapacityExhausted
from .contracts import save_manual_draft_input, save_manual_draft_result
from .markdown import DocumentInvalid
from .snapshot import Provenance, create_snapshot, validate_snapshot, validate_template_lock
from .manual_identity import ManualIdentityProofs
from .contracts import complete_manual_draft_input, complete_manual_draft_result
from backend.app.comments.commands import revalidate_anchors
from backend.app.infrastructure.resources import TemplateInvalid
from backend.app.shared.validation import strict_json_object


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


def save_manual_draft(database: Database, payload: object, *, catalog: ResourceCatalog | None = None,
                      clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = save_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        with database.transaction(write=True) as connection:
            root = RequirementRepository(connection).get(request.requirement_id)
            if root is None:
                raise Rejected('NOT_FOUND')
            draft = active_manual_draft(connection, root)
            if draft['content_version'] != request.expected_version:
                raise Rejected('CONTENT_VERSION_CONFLICT')
            resources = catalog if catalog is not None else ResourceCatalog()
            sources = DocumentSources(connection, request.requirement_id, resources)
            # Stored corruption is an internal failure; client pair failures are DOCUMENT_INVALID.
            persisted = get_manual_draft_result(draft, sources)
            prior = validate_snapshot(persisted['markdown_content'], persisted['block_state_json'], sources)
            proofs = ManualIdentityProofs(connection, draft['id'])
            baseline = proofs.baseline(sources)
            proofs.verify_persisted(prior, baseline, draft['updated_at'])
            at = operation_time(clock)
            if at < draft['updated_at']:
                raise ValueError('Operation clock predates persisted draft')
            locked_template = None
            locked_ids = ()
            if root['status'] == 'INITIALIZING':
                locked_template = resources.template(root['requirement_type'], root['template_key'], root['template_version'])
                current = connection.execute('SELECT p.created_at FROM manual_draft_context c JOIN requirement_documents p ON p.id=c.current_document_id WHERE c.draft_id=?', (draft['id'],)).fetchone()
                initial = create_snapshot(locked_template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), current['created_at'], sources)
                locked_ids = tuple(metadata['block_id'] for block, metadata in zip(initial.parsed.blocks, initial.state['blocks']) if block.block_type == 'heading')
            try:
                candidate = validate_snapshot(request.markdown_content, request.block_state_json, sources)
                authoritative = proofs.derive(candidate, prior, baseline, at, sources)
                if locked_template is not None:
                    validate_template_lock(authoritative, locked_template, locked_ids)
            except DocumentInvalid:
                raise Rejected('DOCUMENT_INVALID') from None
            updated = DocumentRepository(connection).save_manual_draft(draft, authoritative, increment(draft['content_version']), at)
            result = {'code': 'DRAFT_SAVED', 'data': save_manual_draft_result(updated, sources), 'details': None}
        return result
    except Rejected as error:
        code = error.code if error.code in {'NOT_FOUND', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID'} else 'INTERNAL_ERROR'
    except (StorageUnavailable, sqlite3.Error):
        code = 'STORAGE_UNAVAILABLE'
    except CapacityExhausted:
        code = 'CAPACITY_EXHAUSTED'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}


def complete_manual_draft(executor: Idempotency, payload: object, *, catalog: ResourceCatalog | None = None,
                          clock: Callable[[], datetime] | None = None) -> dict:
    try:
        request = complete_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection: sqlite3.Connection) -> Success:
        requirements, documents = RequirementRepository(connection), DocumentRepository(connection)
        root = requirements.get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        if root['status'] not in ('INITIALIZING', 'ACTIVE'):
            raise Rejected('STATE_CONFLICT')
        draft = active_manual_draft(connection, root)
        if draft['content_version'] != request.expected_version:
            raise Rejected('CONTENT_VERSION_CONFLICT')
        context = connection.execute('SELECT current_document_id,base_content_version,baseline_block_state_json FROM manual_draft_context WHERE draft_id=?', (draft['id'],)).fetchone()
        current = current_at_version(connection, request.requirement_id, context['base_content_version'])
        if current['id'] != context['current_document_id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        resources = catalog if catalog is not None else ResourceCatalog()
        sources = DocumentSources(connection, request.requirement_id, resources)
        current_model = get_current_document_result(current, sources)
        if current_model['block_state_json'] != strict_json_object(context['baseline_block_state_json'], 'baseline_block_state_json'):
            raise ValueError('CURRENT baseline changed without its version changing')
        try:
            model = get_manual_draft_result(draft, sources)
            snapshot = validate_snapshot(model['markdown_content'], model['block_state_json'], sources)
        except (DocumentInvalid, InvalidInput, ValueError):
            raise Rejected('DOCUMENT_INVALID') from None
        proofs = ManualIdentityProofs(connection, draft['id'])
        baseline = proofs.baseline(sources)
        proofs.verify_persisted(snapshot, baseline, draft['updated_at'])
        if root['status'] == 'INITIALIZING':
            try:
                template = resources.template(root['requirement_type'], root['template_key'], root['template_version'])
            except TemplateInvalid:
                raise Rejected('TEMPLATE_INVALID') from None
            initial = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), current['created_at'], sources)
            locked = tuple(metadata['block_id'] for block, metadata in zip(initial.parsed.blocks, initial.state['blocks']) if block.block_type == 'heading')
            try:
                validate_template_lock(snapshot, template, locked)
            except DocumentInvalid:
                raise Rejected('TEMPLATE_INVALID') from None
        at = operation_time(clock)
        if at < max(draft['updated_at'], current['updated_at'], root['updated_at']):
            raise ValueError('Completion clock predates persisted activity')
        updated = documents.replace_current(current, snapshot, increment(current['content_version']), at)
        revalidate_anchors(connection, {'requirement_id': request.requirement_id,
            'new_document': {'markdown_content': snapshot.parsed.markdown, 'block_state_json': snapshot.state}}, catalog=resources)
        # D-004: audit an actual ACTIVE body change, using the real completed session.
        if root['status'] == 'ACTIVE' and snapshot.parsed.markdown != current['markdown_content']:
            connection.execute("INSERT INTO document_change_audits VALUES (?,?,?,'MANUAL_EDIT',?,'USER_MANUAL_EDIT',?,?,?)",
                (entity_id(connection, EntityKind.DOCUMENT_AUDIT), request.requirement_id, current['id'], draft['id'], current['content_version'], updated['content_version'], at))
        documents.delete_manual_draft(draft)
        requirements.release_manual_draft(root['id'], draft['id'], at)
        close_edit_session(connection, draft['id'], 'COMPLETED', at)
        data = complete_manual_draft_result(updated, sources)
        return Success({'code': 'DRAFT_COMPLETED', 'data': data, 'details': None}, 200)

    return execute_idempotent(executor, 'APP-DOC-CMD-C03', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT',
        'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID', 'TEMPLATE_INVALID',
    }))
