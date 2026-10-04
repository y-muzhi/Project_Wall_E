"""APP-COMMENT-CMD-C06 joins its caller's actual CURRENT write transaction."""
import sqlite3
from backend.app.documents.anchors import locate
from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.comment_repository import CommentRepository
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.shared.validation import strict_json_object
from backend.app.infrastructure.idempotency import canonical_input
from .contracts import revalidate_anchors_input, revalidate_anchors_result
from .contracts import create_comment_input, create_comment_result, edit_comment_input, edit_comment_result, resolve_comment_input, resolve_comment_result, reopen_comment_input, reopen_comment_result, delete_comment_input, delete_comment_result, get_comment_result
from backend.app.documents.anchors import AnchorInvalid, create_block_anchor, create_selection_anchor
from backend.app.documents.guards import assert_idle, current_at_version
from backend.app.documents.snapshot import _time
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.shared.validation import InvalidInput


def revalidate_anchors(connection: sqlite3.Connection, payload: object, *, catalog: ResourceCatalog | None = None) -> dict:
    # No own transaction, error conversion, or commit: corruption aborts the outer command.
    require_write_transaction(connection)
    requirement_id, document = revalidate_anchors_input(payload)
    rows = DocumentRepository(connection).by_requirement(requirement_id, 'CURRENT')
    if len(rows) != 1:
        raise ValueError('Internal reanchoring requires unique actual CURRENT')
    sources = DocumentSources(connection, requirement_id, catalog if catalog is not None else ResourceCatalog())
    current = get_current_document_result(rows[0], sources)
    if document != {key: current[key] for key in ('markdown_content', 'block_state_json')}:
        raise ValueError('Internal snapshot must be the CURRENT written in this transaction')
    snapshot = validate_snapshot(document['markdown_content'], document['block_state_json'], sources)
    repository = CommentRepository(connection)
    attached, orphaned = [], []
    for comment in repository.live_anchors(requirement_id):
        anchor = strict_json_object(comment['anchor_ref_json'], 'anchor_ref_json')
        canonical_input(anchor)  # Reject invalid Unicode even when the original block is absent.
        found = locate(snapshot, comment['anchor_type'], comment['block_id'], anchor).attached
        repository.set_anchor_status(requirement_id, comment['id'], 'ATTACHED' if found else 'ORPHANED')
        (attached if found else orphaned).append(comment['id'])
    return revalidate_anchors_result(requirement_id, current['id'], current['content_version'], attached, orphaned)


def create_comment(executor: Idempotency, payload: object, *, catalog: ResourceCatalog | None = None, clock=None) -> dict:
    try:
        request = create_comment_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        root = RequirementRepository(connection).get(request.requirement_id)
        if root is None: raise Rejected('NOT_FOUND')
        if root['status'] != 'ACTIVE': raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset())
        current = current_at_version(connection, root['id'], request.expected_content_version)
        sources = DocumentSources(connection, root['id'], catalog if catalog is not None else ResourceCatalog())
        document = get_current_document_result(current, sources)
        snapshot = validate_snapshot(document['markdown_content'], document['block_state_json'], sources)
        try:
            if request.anchor_type == 'BLOCK':
                anchor = create_block_anchor(snapshot, request.block_id)
            else:
                create_selection_anchor(snapshot, request.block_id, request.selection)
                found = locate(snapshot, 'SELECTION', request.block_id, request.selection)
                text = snapshot.by_id[request.block_id][0].plain_text
                anchor = {'selected_text': text[found.start_offset:found.end_offset],
                    'prefix_text': text[found.start_offset-len(request.selection['prefix_text']):found.start_offset],
                    'suffix_text': text[found.end_offset:found.end_offset+len(request.selection['suffix_text'])]}
        except AnchorInvalid:
            raise Rejected('ANCHOR_INVALID') from None
        at = operation_time(clock)
        if root['updated_at'] > at or _time(current['updated_at']) > at: raise ValueError('Comment cannot precede the authoritative snapshot')
        identity = entity_id(connection, EntityKind.COMMENT)
        return Success(create_comment_result(CommentRepository(connection).create(identity, request, anchor, at)), 201)
    return execute_idempotent(executor, 'APP-COMMENT-CMD-C01', request, operation,
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'ANCHOR_INVALID'}))


def _comment_action(executor, payload, *, action, parse, build, capability, clock):
    try:
        request = parse(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        repository = CommentRepository(connection)
        row = repository.get(request.comment_id)
        if row is None: raise Rejected('NOT_FOUND')
        comment = get_comment_result(row)
        root = RequirementRepository(connection).get(comment['requirement_id'])
        if root is None: raise Rejected('NOT_FOUND')
        if action == 'DELETE' and comment['deleted_at'] is not None:
            return Success(build(row), 200)
        if root['status'] != 'ACTIVE' or comment['deleted_at'] is not None: raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset())
        if action == 'EDIT' and comment['status'] != 'OPEN': raise Rejected('STATE_CONFLICT')
        if (action == 'RESOLVE' and comment['status'] == 'RESOLVED') or (action == 'REOPEN' and comment['status'] == 'OPEN'):
            return Success(build(row), 200)
        at = operation_time(clock)
        if comment['updated_at'] > at or root['updated_at'] > at: raise ValueError('Comment action cannot precede its persisted activity')
        changes = {'content': request.content} if action == 'EDIT' else {'status': 'RESOLVED', 'resolved_at': at} if action == 'RESOLVE' else {'status': 'OPEN', 'resolved_at': None} if action == 'REOPEN' else {'deleted_at': at}
        return Success(build(repository.update(comment['id'], changes, at)), 200)
    return execute_idempotent(executor, capability, request, operation, target_identity=f'Comment:{request.comment_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT'}))


def edit_comment(executor: Idempotency, payload: object, *, clock=None) -> dict:
    return _comment_action(executor, payload, action='EDIT', parse=edit_comment_input, build=edit_comment_result, capability='APP-COMMENT-CMD-C02', clock=clock)


def resolve_comment(executor: Idempotency, payload: object, *, clock=None) -> dict:
    return _comment_action(executor, payload, action='RESOLVE', parse=resolve_comment_input, build=resolve_comment_result, capability='APP-COMMENT-CMD-C03', clock=clock)


def reopen_comment(executor: Idempotency, payload: object, *, clock=None) -> dict:
    return _comment_action(executor, payload, action='REOPEN', parse=reopen_comment_input, build=reopen_comment_result, capability='APP-COMMENT-CMD-C04', clock=clock)


def delete_comment(executor: Idempotency, payload: object, *, clock=None) -> dict:
    return _comment_action(executor, payload, action='DELETE', parse=delete_comment_input, build=delete_comment_result, capability='APP-COMMENT-CMD-C05', clock=clock)
