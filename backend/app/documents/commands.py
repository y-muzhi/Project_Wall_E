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


def _editing_target(connection, request, *, start=False):
    root = RequirementRepository(connection).get(request.requirement_id)
    if root is None:
        raise Rejected('NOT_FOUND')
    current = DocumentRepository(connection).get_current(root['id'], request.document_id)
    if current is None:
        raise Rejected('NOT_FOUND')
    if current['archived_at'] is not None:
        raise Rejected('STATE_CONFLICT')
    if start:
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
        if current['content_version'] != request.expected_version:
            raise Rejected('CONTENT_VERSION_CONFLICT')
        return root, current, None
    draft = active_manual_draft(connection, root, document_id=request.document_id, draft_id=request.draft_id)
    if draft['content_version'] != request.expected_version:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    return root, current, draft


DRAFT_FAILURES = frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT',
    'MANUAL_DRAFT_NOT_FOUND', 'CONTENT_VERSION_CONFLICT', 'DOCUMENT_INVALID', 'SOURCE_INVALID', 'TEMPLATE_INVALID', 'CONFIG_INVALID'})


def start_manual_draft(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try:
        request = start_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        from .snapshot import assign_identities, FIELDS
        from .content import validate_structure
        from .queries import current_document_view
        from .markdown import parse_markdown
        from backend.app.infrastructure.idempotency import canonical_input
        root, current, _ = _editing_target(connection, request, start=True)
        resources = catalog if catalog is not None else ResourceCatalog()
        sources = DocumentSources(connection, root['id'], resources, document_id=current['id'])
        current_document_view(connection, current, resources)
        prior = validate_snapshot(current['markdown_content'], strict_json_object(current['block_state_json']), sources)
        at = operation_time(clock)
        if at < max(current['updated_at'], root['updated_at']):
            raise ValueError('Editing cannot precede existing activity')
        documents = DocumentRepository(connection)
        draft = documents.create_manual_draft(entity_id(connection, EntityKind.DOCUMENT), current, at)
        register_edit_session(connection, draft['id'], at)
        occupied = RequirementRepository(connection).occupy_manual_draft(root['id'], draft['id'], at)
        if request.restore_revision_id is not None:
            historical = connection.execute("SELECT * FROM revisions WHERE id=? AND requirement_id=? AND document_id=? AND revision_type='CONTENT'", (request.restore_revision_id, root['id'], current['id'])).fetchone()
            if historical is None:
                raise Rejected('SOURCE_INVALID')
            old = validate_snapshot(historical['markdown_snapshot'], strict_json_object(historical['block_state_snapshot_json']), sources)
            identities, next_id = [], prior.next_block_id
            for identity, (block, metadata) in old.by_id.items():
                known = prior.by_id.get(identity)
                if known is not None and all(known[1][field] == metadata[field] for field in FIELDS if field.startswith('created_')):
                    identities.append(identity)
                else:
                    identities.append(next_id)
                    next_id = increment(next_id)
            candidate = assign_identities(old.parsed.markdown, identities, next_id, prior,
                Provenance('USER', 'MANUAL_EDIT', draft['id']), at, sources)
            validate_structure(candidate, prior, current, resources)
            proofs = ManualIdentityProofs(connection, draft['id'])
            baseline = proofs.baseline(sources)
            restored = proofs.derive(candidate, prior, baseline, at, sources)
            draft = documents.save_manual_draft(draft, restored, 1, at)
            refs = [{'kind': 'REVISION', 'document_id': current['id'], 'revision_id': historical['id'], 'block_ids': None}]
            canonical_input({'refs': refs})
            from backend.app.infrastructure.schema_transport import compact
            connection.execute('UPDATE manual_draft_context SET source_refs_json=? WHERE draft_id=?', (compact(refs), draft['id']))
        return Success({'code': 'DRAFT_STARTED', 'data': start_manual_draft_result(draft, occupied, sources), 'details': None}, 201)

    return execute_idempotent(executor, 'APP-DOC-CMD-C01', request, operation, allowed_failures=DRAFT_FAILURES)


def cancel_manual_draft(executor: Idempotency, payload: object, *, clock=None) -> dict:
    try:
        request = cancel_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        root, current, draft = _editing_target(connection, request)
        at = operation_time(clock)
        if at < max(draft['updated_at'], root['updated_at']):
            raise ValueError('Cancellation cannot precede existing activity')
        DocumentRepository(connection).delete_manual_draft(draft)
        RequirementRepository(connection).release_manual_draft(root['id'], draft['id'], at)
        close_edit_session(connection, draft['id'], 'CANCELLED', at)
        return Success({'code': 'DRAFT_CANCELLED', 'data': cancel_manual_draft_result(root['id'], current['id'], draft['id']), 'details': None}, 200)

    return execute_idempotent(executor, 'APP-DOC-CMD-C04', request, operation, allowed_failures=DRAFT_FAILURES)


def save_manual_draft(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try:
        request = save_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        from .content import validate_structure
        root, current, draft = _editing_target(connection, request)
        resources = catalog if catalog is not None else ResourceCatalog()
        sources = DocumentSources(connection, root['id'], resources, document_id=current['id'])
        persisted = get_manual_draft_result(draft, sources)
        prior = validate_snapshot(persisted['markdown_content'], persisted['block_state_json'], sources)
        proofs = ManualIdentityProofs(connection, draft['id'])
        baseline = proofs.baseline(sources)
        proofs.verify_persisted(prior, baseline, draft['updated_at'])
        at = operation_time(clock)
        if at < draft['updated_at']:
            raise ValueError('Autosave cannot precede persisted draft')
        try:
            candidate = validate_snapshot(request.markdown_content, request.block_state_json, sources)
            authoritative = proofs.derive(candidate, prior, baseline, at, sources)
            base = validate_snapshot(current['markdown_content'], strict_json_object(current['block_state_json']), sources)
            validate_structure(authoritative, base, current, resources)
        except DocumentInvalid:
            raise Rejected('DOCUMENT_INVALID') from None
        updated = DocumentRepository(connection).save_manual_draft(draft, authoritative, increment(draft['content_version']), at)
        return Success({'code': 'DRAFT_SAVED', 'data': save_manual_draft_result(updated, sources), 'details': None}, 200)

    return execute_idempotent(executor, 'APP-DOC-CMD-C02', request, operation, allowed_failures=DRAFT_FAILURES)


def complete_manual_draft(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try:
        request = complete_manual_draft_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        from .content import commit_content
        import json
        root, current, draft = _editing_target(connection, request)
        context = connection.execute('SELECT * FROM manual_draft_context WHERE draft_id=?', (draft['id'],)).fetchone()
        if context is None or context['current_document_id'] != current['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        if current['content_version'] != context['base_content_version']:
            raise Rejected('CONTENT_VERSION_CONFLICT')
        if strict_json_object(current['block_state_json']) != strict_json_object(context['baseline_block_state_json']):
            raise ValueError('Document baseline changed without a content version')
        resources = catalog if catalog is not None else ResourceCatalog()
        sources = DocumentSources(connection, root['id'], resources, document_id=current['id'])
        persisted = get_manual_draft_result(draft, sources)
        snapshot = validate_snapshot(persisted['markdown_content'], persisted['block_state_json'], sources)
        proofs = ManualIdentityProofs(connection, draft['id'])
        baseline = proofs.baseline(sources)
        proofs.verify_persisted(snapshot, baseline, draft['updated_at'])
        at = operation_time(clock)
        if at < max(current['updated_at'], draft['updated_at'], root['updated_at']):
            raise ValueError('Completion cannot precede existing activity')
        effect = commit_content(connection, current, snapshot, resources=resources, source_type='MANUAL_EDIT',
            source_id=draft['id'], source_refs=json.loads(context['source_refs_json']), summary='人工编辑完成', key=request.idempotency_key, at=at)
        DocumentRepository(connection).delete_manual_draft(draft)
        RequirementRepository(connection).release_manual_draft(root['id'], draft['id'], at)
        close_edit_session(connection, draft['id'], 'COMPLETED', at)
        return Success({'code': 'DRAFT_COMPLETED', 'data': complete_manual_draft_result(effect), 'details': None}, 200)

    return execute_idempotent(executor, 'APP-DOC-CMD-C03', request, operation, allowed_failures=DRAFT_FAILURES)


def create_document(executor, payload, *, catalog=None, clock=None):
    """C05 user-created blank/fixed framework, V1 and event in one commit."""
    from .contracts import create_document_input
    from .queries import current_document_view
    from backend.app.infrastructure.revision_repository import RevisionRepository
    from backend.app.infrastructure.message_repository import MessageRepository
    from backend.app.infrastructure.audit_repository import AuditRepository
    try:
        request = create_document_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        root = RequirementRepository(connection).get(request.requirement_id)
        if root is None:
            raise Rejected('NOT_FOUND')
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
        resources = catalog if catalog is not None else ResourceCatalog()
        markdown = ''
        reference = request.template_ref
        if reference is not None:
            kind = {'REQUIREMENT_BRIEF': 'brief', 'DESIGN': 'design', 'SPECIFICATION': 'specification'}[request.document_kind]
            profile = resources.collaboration.structure(kind)
            if reference == resources.collaboration.reference(profile['key'], profile['version']):
                if kind == 'specification':
                    template = resources.template('NEW', profile['template_ref']['key'], profile['template_ref']['version'])
                    markdown = template.markdown
                else:
                    markdown = '\n\n'.join('# ' + heading for heading in profile['headings']) + '\n'
            else:
                import hashlib
                if kind != 'specification' or reference['key'] != 'new-requirement' or reference['version'] != 'v4':
                    raise Rejected('TEMPLATE_INVALID')
                template = resources.template('NEW', reference['key'], reference['version'])
                if hashlib.sha256(template.markdown.encode('utf-8')).hexdigest() != reference['digest']:
                    raise Rejected('TEMPLATE_INVALID')
                markdown = template.markdown
        at = operation_time(clock)
        document_id = entity_id(connection, EntityKind.DOCUMENT)
        message_id = entity_id(connection, EntityKind.MESSAGE)
        MessageRepository(connection).create_user_text(message_id, root['id'], None, '新建文档：' + request.name, request.idempotency_key, at)
        origin = {'kind': 'MESSAGE', 'message_id': message_id}
        sources = DocumentSources(connection, root['id'], resources, document_id=document_id, template_ref=reference)
        snapshot = create_snapshot(markdown, Provenance('SYSTEM', 'TEMPLATE', None), at, sources)
        document = DocumentRepository(connection).create_current(document_id, root['id'], snapshot, at,
            name=request.name, document_kind=request.document_kind, template_ref=reference, origin=origin)
        revision_id = entity_id(connection, EntityKind.REVISION)
        RevisionRepository(connection).insert_content(revision_id, document, [origin], '用户新建文档', at)
        AuditRepository(connection).record_document_event(document, 'CONTENT_COMMITTED',
            {'creation_message_id': message_id, 'template_ref': reference, 'idempotency_key': request.idempotency_key}, at, revision_id=revision_id)
        return Success({'code': 'CREATED', 'data': {'document': current_document_view(connection, document, resources), 'revision_id': revision_id}, 'details': None}, 201)

    def guarded(connection):
        from backend.app.infrastructure.resources import ConfigInvalid
        try:
            return operation(connection)
        except ConfigInvalid:
            raise Rejected('CONFIG_INVALID') from None
        except TemplateInvalid:
            raise Rejected('TEMPLATE_INVALID') from None

    return execute_idempotent(executor, 'APP-DOC-CMD-C05', request, guarded,
        allowed_failures=frozenset({'NOT_FOUND', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'TEMPLATE_INVALID', 'CONFIG_INVALID'}))


def update_document_metadata(executor, payload, *, catalog=None, clock=None):
    """C06 metadata/confirmation remains independent of content and status."""
    from .contracts import document_metadata_input
    from backend.app.infrastructure.audit_repository import AuditRepository
    try:
        request = document_metadata_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}

    def operation(connection):
        documents = DocumentRepository(connection)
        document = connection.execute("SELECT * FROM requirement_documents WHERE id=? AND document_type='CURRENT'", (request.document_id,)).fetchone()
        if document is None:
            raise Rejected('NOT_FOUND')
        root = RequirementRepository(connection).get(document['requirement_id'])
        if root is None:
            raise Rejected('NOT_FOUND')
        if document['metadata_version'] != request.expected_metadata_version:
            raise Rejected('METADATA_VERSION_CONFLICT', details={'expected_version': request.expected_metadata_version,
                'actual_version': document['metadata_version'], 'resource_kind': 'RequirementDocument', 'resource_id': document['id']})
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
        kind = request.change['type']
        if document['archived_at'] is not None and kind not in ('RESTORE', 'ARCHIVE'):
            raise Rejected('STATE_CONFLICT')
        at = operation_time(clock)
        changes = {}
        event_type = {'RENAME': 'DOCUMENT_RENAMED', 'ARCHIVE': 'DOCUMENT_ARCHIVED', 'RESTORE': 'DOCUMENT_RESTORED', 'CONFIRM': 'DOCUMENT_CONFIRMED'}[kind]
        event_payload = {'idempotency_key': request.idempotency_key}
        revision_id = None
        if kind == 'RENAME' and document['name'] != request.change['name']:
            changes['name'] = request.change['name']
            event_payload.update(before=document['name'], after=request.change['name'])
        elif kind == 'ARCHIVE' and document['archived_at'] is None:
            changes['archived_at'] = at
        elif kind == 'RESTORE' and document['archived_at'] is not None:
            changes['archived_at'] = None
        elif kind == 'CONFIRM':
            if request.change['expected_content_version'] != document['content_version']:
                raise Rejected('CONTENT_VERSION_CONFLICT')
            revision = connection.execute("SELECT * FROM revisions WHERE id=? AND document_id=? AND requirement_id=? AND revision_type='CONTENT' AND source_content_version=?", (request.change['revision_id'], document['id'], root['id'], document['content_version'])).fetchone()
            if revision is None:
                raise Rejected('SOURCE_INVALID')
            revision_id = revision['id']
            if document['confirmed_revision_id'] != revision_id:
                changes['confirmed_revision_id'] = revision_id
                event_payload.update(revision_id=revision_id, content_version=document['content_version'])
        event_id = None
        if changes:
            if at < document['updated_at']:
                raise ValueError('Document metadata event cannot precede existing activity')
            document = documents.update_metadata(document, changes, at)
            event_id = AuditRepository(connection).record_document_event(document, event_type, event_payload, at, revision_id=revision_id)
        summary = next(item for item in documents.list_current_summaries(root['id']) if item['id'] == document['id'])
        return Success({'code': 'UPDATED' if changes else 'NO_CHANGE', 'data': {'document': summary, 'event_id': event_id}, 'details': None}, 200)

    return execute_idempotent(executor, 'APP-DOC-CMD-C06', request, operation, target_identity=f'Document:{request.document_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'METADATA_VERSION_CONFLICT', 'CONTENT_VERSION_CONFLICT', 'SOURCE_INVALID'}))
