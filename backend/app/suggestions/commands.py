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
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.documents.markdown import parse_markdown, DocumentInvalid
from backend.app.documents.tables import validate_cells
from backend.app.documents.patch_errors import PatchInvalid
from backend.app.shared.validation import strict_json_object
from .contracts import decide_suggestion_input, decide_suggestion_result, suggestion_from_row
from .contracts import complete_batch_input, complete_batch_result, stored_patch
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.identifiers import increment
from backend.app.documents.guards import current_at_version
from backend.app.documents.sources import DocumentSources
from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.scopes import restore_authority, ScopeInvalid
from backend.app.documents.patch_validation import validate_patch, validate_combination
from backend.app.documents.patch_application import Adoption, apply_adoptions
from backend.app.documents.patch_errors import TargetStale
from backend.app.comments.commands import revalidate_anchors
from backend.app.documents.patch_errors import PATCH_MESSAGES


def _pending_owned_batch(connection, repository, row):
    batch = batch_metadata({field: row[field] for field in METADATA_FIELDS})
    root = RequirementRepository(connection).get(batch['requirement_id'])
    if root is None: raise Rejected('NOT_FOUND')
    if root['status'] != 'ACTIVE' or batch['status'] != 'PENDING': raise Rejected('STATE_CONFLICT')
    parent = repository.parent(row)
    if parent is None or parent['requirement_id'] != root['id'] or parent['action_type'] != 'MODIFY' or parent['status'] != 'COMPLETED' or parent['source_type'] != batch['source_type'] or parent['source_id'] != batch['source_id'] or parent['function_type'] != FUNCTIONS.get(('MODIFY', batch['source_type']), (None,))[0]:
        raise Rejected('WORK_STATE_INCONSISTENT')
    try: assert_idle(connection, root, remaining_conflicts=frozenset())
    except Rejected as error:
        if error.code != 'WORK_STATE_CONFLICT': raise
    if root['document_work_state'] != 'SUGGESTION_REVIEWING' or root['active_operation_type'] != 'SUGGESTION_BATCH' or root['active_operation_id'] != batch['id']:
        raise Rejected('WORK_STATE_CONFLICT')
    return batch, root


def decide_suggestion(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try: request = decide_suggestion_input(payload)
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        repository = BatchRepository(connection)
        row = repository.suggestion(request.suggestion_id)
        if row is None: raise Rejected('NOT_FOUND')
        stored_batch = repository.get(row['batch_id'])
        if stored_batch is None: raise Rejected('NOT_FOUND')
        batch, root = _pending_owned_batch(connection, repository, stored_batch)
        protocol = (catalog if catalog is not None else ResourceCatalog()).freeze('MODIFY', batch['source_type'])
        item = suggestion_from_row(row, protocol=protocol)
        if request.decision == 'EDITED':
            try:
                if item['patch_operation'] == 'DELETE_BLOCK': raise PatchInvalid('删除建议不能编辑')
                if item['patch_operation'] == 'REPLACE_TABLE_ROW':
                    # Generated proposals already proved their baseline width;
                    # deciding preserves that width without a fresh CURRENT read.
                    validate_cells(strict_json_object(request.edited_content), len(item['proposed_data']['cells']))
                elif len(parse_markdown(request.edited_content).blocks) != 1:
                    raise PatchInvalid('编辑内容必须为恰好一个顶层区块')
            except (InvalidInput, PatchInvalid, DocumentInvalid): raise Rejected('PATCH_INVALID') from None
        items = repository.suggestions(batch['id'])
        counts_model(suggestion_counts(items))
        at = operation_time(clock)
        if at < max(batch['updated_at'], root['updated_at'], *(entry['updated_at'] for entry in items)):
            raise ValueError('Decision cannot predate aggregate activity')
        updated = repository.decide(row, request.decision, request.edited_content, at)
        return Success(decide_suggestion_result(updated, repository.suggestions(batch['id']), protocol=protocol), 200)
    return execute_idempotent(executor, 'APP-BATCH-CMD-C01', request, operation, target_identity=f'Suggestion:{request.suggestion_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'PATCH_INVALID'}))


def discard_batch(executor: Idempotency, payload: object, *, clock=None) -> dict:
    try:
        request = discard_batch_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        repository = BatchRepository(connection)
        row = repository.get(request.batch_id)
        if row is None: raise Rejected('NOT_FOUND')
        batch, root = _pending_owned_batch(connection, repository, row)
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


def complete_batch(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try: request = complete_batch_input(payload)
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        repository = BatchRepository(connection)
        row = repository.get(request.batch_id)
        if row is None: raise Rejected('NOT_FOUND')
        batch, root = _pending_owned_batch(connection, repository, row)
        current = current_at_version(connection, root['id'], request.expected_content_version)
        if current['content_version'] != batch['base_content_version']: raise Rejected('CONTENT_VERSION_CONFLICT')
        resources = catalog if catalog is not None else ResourceCatalog()
        protocol = resources.freeze('MODIFY', batch['source_type'])
        items = [suggestion_from_row(item, protocol=protocol) for item in repository.suggestions(batch['id'])]
        counts = counts_model(suggestion_counts(items))
        if counts['pending']: raise Rejected('BATCH_PENDING')
        sources = DocumentSources(connection, root['id'], resources)
        model = get_current_document_result(current, sources)
        snapshot = validate_snapshot(model['markdown_content'], model['block_state_json'], sources)
        parent = repository.authority(row)
        try:
            reference = None if parent['scope_ref_json'] is None else strict_json_object(parent['scope_ref_json'])
            authority = restore_authority(snapshot, 'MODIFY', parent['scope_type'], reference, parent['allowed_targets_json'])
        except (ScopeInvalid, InvalidInput): raise Rejected('TARGET_STALE') from None
        adoptions, checked, errors = [], [], []
        for item in items:
            if item['status'] == 'REJECTED': continue
            patch = stored_patch(item)
            try: checked.append(validate_patch(snapshot, patch, authority, edited_content=item['user_edited_content']))
            except (PatchInvalid, TargetStale) as error:
                errors.append({'suggestion_id': item['id'], 'code': error.code, 'message': PATCH_MESSAGES[error.code]})
            adoptions.append(Adoption(item['order_no'], patch, item['status'], item['user_edited_content']))
        if errors: raise Rejected(errors[0]['code'], details={'suggestion_errors': errors})
        try: validate_combination(tuple(checked))
        except PatchInvalid: raise Rejected('PATCH_INVALID') from None
        at = operation_time(clock)
        if at < max(batch['updated_at'], root['updated_at'], current['updated_at'], *(item['updated_at'] for item in items)):
            raise ValueError('Completion cannot predate aggregate activity')
        try: adopted = apply_adoptions(snapshot, adoptions, authority, batch['id'], at, sources)
        except (PatchInvalid, TargetStale) as error: raise Rejected(error.code) from None
        except DocumentInvalid: raise Rejected('DOCUMENT_INVALID') from None
        changed = adopted is not snapshot
        if changed:
            current = DocumentRepository(connection).replace_current(current, adopted, increment(current['content_version']), at)
            revalidate_anchors(connection, {'requirement_id': root['id'], 'new_document': {'markdown_content': adopted.parsed.markdown, 'block_state_json': adopted.state}}, catalog=resources)
        completed = repository.complete(batch['id'], current['content_version'] if changed else None, at)
        RequirementRepository(connection).recover_occupancy(root, None, None, at)
        return Success(complete_batch_result(completed, items, current, sources), 200)
    return execute_idempotent(executor, 'APP-BATCH-CMD-C02', request, operation, target_identity=f'SuggestionBatch:{request.batch_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'BATCH_PENDING', 'TARGET_STALE', 'PATCH_INVALID', 'DOCUMENT_INVALID'}))
