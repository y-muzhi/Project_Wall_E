"""APP-GUIDE-CMD-C09: deterministic recovery under the actual OS process lock."""
from datetime import datetime, timedelta
import sqlite3
from backend.app.documents.guards import active_manual_draft, assert_idle
from backend.app.documents.snapshot import _time
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.shared.command_execution import Rejected, execute_idempotent, operation_time
from backend.app.infrastructure.idempotency import Idempotency, Success
from backend.app.shared.validation import InvalidInput
from .contracts import recover_runs_input, recover_runs_result
from .contracts import cancel_guide_run_input, cancel_guide_run_result
from .contracts import fail_guide_run_input, fail_guide_run_result
from .contracts import create_guide_run_input, create_guide_run_result, continue_guide_run_input, continue_guide_run_result, get_guide_run_result
from backend.app.documents.guards import current_at_version
from backend.app.documents.contracts import get_current_document_result
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.documents.scopes import resolve_scope, ScopeInvalid
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, TemplateInvalid, ProtocolInvalid
from backend.app.shared.validation import strict_json_object
from .contracts import submit_card_responses_input, submit_card_responses_result
from backend.app.messages.cards import CardsInvalid, decode_cards, validate_responses, formal_answer_text
from backend.app.messages.queries import card_state, project_message
from .contracts import modify_from_comment_input, modify_from_comment_result
from backend.app.infrastructure.comment_repository import CommentRepository
from backend.app.infrastructure.idempotency import CommentAnchorRejected
from backend.app.comments.contracts import get_comment_result
from backend.app.documents.anchors import locate
from backend.app.infrastructure.document_repository import DocumentRepository
from .contracts import retry_guide_run_input, retry_guide_run_result


def persist_ai_result(database, payload, *, process_lock, profile, catalog=None, clock=None):
    from .result_persistence import persist_ai_result as persist
    return persist(database,payload,process_lock=process_lock,profile=profile,catalog=catalog,clock=clock)
from types import SimpleNamespace

RECOVERY_ERRORS = {'INTERRUPTED': '运行因进程中断而结束', 'EXECUTION_TIMEOUT': '运行连续15分钟没有进展'}
TERMINAL_RUNS = frozenset({'COMPLETED', 'FAILED', 'CANCELLED'})


def _owned_guide(connection, root, run):
    if root is None: raise Rejected('WORK_STATE_INCONSISTENT')
    if root['document_work_state'] != 'GUIDE_ACTIVE' or root['active_operation_type'] != 'GUIDE_RUN' or root['active_operation_id'] != run['id']:
        # Distinguish a legitimate other activity from dangling ownership.
        assert_idle(connection, root, remaining_conflicts=frozenset())
        raise Rejected('WORK_STATE_CONFLICT')
    try: assert_idle(connection, root, remaining_conflicts=frozenset())
    except Rejected as error:
        if error.code != 'WORK_STATE_CONFLICT': raise
    else: raise Rejected('WORK_STATE_INCONSISTENT')


def _review_source(connection, resources, request):
    if request.source_type == 'USER_INSTRUCTION': return
    if request.action_type != 'MODIFY': raise Rejected('SOURCE_INVALID')
    guides = GuideRepository(connection)
    source = guides.get_status(request.source_id)
    if source is None or source['requirement_id'] != request.requirement_id or source['action_type'] != 'REVIEW' or source['status'] != 'COMPLETED':
        raise Rejected('SOURCE_INVALID')
    try:
        message, batches = guides.status_references(source)
        get_guide_run_result(connection, source, message, batches, catalog=resources)
        effects = strict_json_object(source['final_result_json'])
        if effects.get('review_result') is None: raise ValueError('Missing formal review result')
        resources.freeze('REVIEW', 'USER_INSTRUCTION').validate_review_result(effects['review_result'])
    except ConfigInvalid: raise
    except (ValueError, InvalidInput, ProtocolInvalid): raise Rejected('SOURCE_INVALID') from None


def _accept_collaboration(connection, request, catalog, at, *, parent=None, retry_of=None, reuse_message=None, formal_answer=None, comment_source=None):
    from copy import deepcopy
    from .accepted_context import capture_inputs
    from backend.app.requirements.contracts import requirement_read_model
    requirements = RequirementRepository(connection)
    root = requirements.get(request.requirement_id)
    if root is None:
        raise Rejected('NOT_FOUND')
    if root['discussion_version'] != request.expected_discussion_version:
        raise Rejected('DISCUSSION_VERSION_CONFLICT', details={'expected_version': request.expected_discussion_version,
            'actual_version': root['discussion_version'], 'resource_kind': 'Requirement', 'resource_id': root['id']})
    assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
    if at < root['updated_at']:
        raise ValueError('Acceptance cannot precede persisted activity')
    inputs = capture_inputs(connection, root, request, catalog)
    run_id = entity_id(connection, EntityKind.GUIDE_RUN)
    discussion = deepcopy(root['discussion_state_json'])
    if reuse_message is None:
        message_id = entity_id(connection, EntityKind.MESSAGE)
        associations = {'phase_ref': discussion['phase']['phase_ref'], 'topic_refs': () if discussion['focus_topic_ref'] is None else (discussion['focus_topic_ref'],),
            'document_ids': () if inputs['authorization']['target_document_id'] is None else (inputs['authorization']['target_document_id'],)}
        if formal_answer is None:
            message = MessageRepository(connection).create_user_text(message_id, root['id'], run_id, request.instruction, request.idempotency_key, at, **associations)
        else:
            message = MessageRepository(connection).create_card_response(message_id, root['id'], run_id, formal_answer['original'],
                request.instruction, formal_answer['answers'], request.idempotency_key, at, **associations)
    else:
        message, message_id = reuse_message, reuse_message['id']
    if message_id not in discussion['pending_user_message_ids']:
        discussion['pending_user_message_ids'].append(message_id)
    updated = requirements.update_discussion(root, discussion, at) if discussion != root['discussion_state_json'] else root
    occupied = requirements.occupy_guide(root['id'], run_id, at)
    user_message = {key: message[key] for key in message.keys() if key != 'idempotency_key'}
    basis = {'schema_version': 1, **inputs, 'requirement': requirement_read_model(occupied), 'discussion': discussion,
        'request': request.business_input(), 'user_message': user_message, 'parent_guide_run_id': parent,
        'discussion_version': updated['discussion_version']}
    if comment_source is not None:
        basis['comment_source'] = comment_source
    GuideRepository(connection).accept_collaboration(run_id, occupied, message, request, basis, at, parent=parent, retry_of=retry_of,
        trigger_type='RETRY' if retry_of is not None else 'MODIFY_FROM_COMMENT' if comment_source is not None else 'CARD_RESPONSE' if formal_answer is not None else None)
    return {'processing': 'MODEL', 'guide_run_id': run_id, 'user_message_id': message_id}


def create_guide_run(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try:
        request = create_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        try:
            data = _accept_collaboration(connection, request, catalog or ResourceCatalog(), operation_time(clock))
        except ConfigInvalid:
            raise Rejected('CONFIG_INVALID') from None
        return Success({'code': 'GUIDE_ACCEPTED', 'data': data, 'details': None}, 202)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C01', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'DISCUSSION_VERSION_CONFLICT',
        'CONTENT_VERSION_CONFLICT', 'SOURCE_VERSION_CONFLICT', 'SOURCE_INVALID', 'SCOPE_INVALID', 'CONFIG_INVALID'}))


def continue_guide_run(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try:
        request = continue_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        previous = GuideRepository(connection).get(request.guide_run_id)
        if previous is None:
            raise Rejected('NOT_FOUND')
        if previous['status'] not in TERMINAL_RUNS:
            raise Rejected('STATE_CONFLICT')
        root = RequirementRepository(connection).get(previous['requirement_id'])
        if root is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
        binding = root['discussion_state_json']['binding']
        target = None
        if binding['target_document_id'] is not None:
            current = DocumentRepository(connection).get_current(root['id'], binding['target_document_id'])
            if current is None:
                raise Rejected('STATE_CONFLICT')
            target = {'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': current['content_version']}
        internal = create_guide_run_input({'requirement_id': root['id'], 'expected_discussion_version': request.expected_discussion_version,
            'operation': 'DISCUSS', 'instruction': request.instruction, 'target': target, 'scope': binding['scope'],
            'source_refs': binding['source_refs'], 'proposal_ref': None, 'acknowledge_source_changes': False, 'idempotency_key': request.idempotency_key})
        try:
            data = _accept_collaboration(connection, internal, catalog or ResourceCatalog(), operation_time(clock), parent=previous['id'])
        except ConfigInvalid:
            raise Rejected('CONFIG_INVALID') from None
        except Rejected as error:
            if error.code in ('SOURCE_INVALID', 'SCOPE_INVALID', 'CONTENT_VERSION_CONFLICT'):
                raise Rejected('STATE_CONFLICT') from None
            raise
        return Success({'code': 'GUIDE_CONTINUED', 'data': data, 'details': None}, 202)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C02', request, operation, target_identity=f'GuideRun:{request.guide_run_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'DISCUSSION_VERSION_CONFLICT', 'CONFIG_INVALID'}))


def _answer_summary(cards, answers):
    return formal_answer_text(cards, answers)


def submit_card_responses(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    from .card_commands import submit
    return submit(executor, payload, catalog=catalog, clock=clock)


def modify_from_comment(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try:
        request = modify_from_comment_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        row = CommentRepository(connection).get(request.comment_id)
        if row is None:
            raise Rejected('NOT_FOUND')
        comment = get_comment_result(row);root = RequirementRepository(connection).get(comment['requirement_id'])
        if root is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
        if comment['status'] != 'OPEN' or comment['deleted_at'] is not None:
            raise Rejected('STATE_CONFLICT')
        if root['discussion_version'] != request.expected_discussion_version:
            raise Rejected('DISCUSSION_VERSION_CONFLICT', details={'expected_version': request.expected_discussion_version,
                'actual_version': root['discussion_version'], 'resource_kind': 'Requirement', 'resource_id': root['id']})
        assert_idle(connection, root, remaining_conflicts=frozenset({'MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'}))
        current = DocumentRepository(connection).get_current(root['id'], comment['document_id'])
        if current is None:
            raise Rejected('SOURCE_INVALID')
        if current['archived_at'] is not None:
            raise Rejected('STATE_CONFLICT')
        if current['content_version'] != request.expected_content_version:
            raise Rejected('CONTENT_VERSION_CONFLICT')
        resources = catalog or ResourceCatalog();at = operation_time(clock)
        if at < max(root['updated_at'], current['updated_at'], comment['updated_at']):
            raise ValueError('Comment request cannot precede actual activity')
        snapshot = validate_snapshot(current['markdown_content'], strict_json_object(current['block_state_json']),
            DocumentSources(connection, root['id'], resources, document_id=current['id']))
        location = locate(snapshot, comment['anchor_type'], comment['block_id'], comment['anchor_ref'])
        if comment['anchor_status'] != 'ATTACHED' or not location.attached:
            if comment['anchor_status'] != 'ORPHANED':
                CommentRepository(connection).set_anchor_status(root['id'], comment['id'], 'ORPHANED')
                return CommentAnchorRejected(comment['id'])
            raise Rejected('COMMENT_ORPHANED')
        scope = {'scope_type': comment['anchor_type'], 'scope_ref': {'block_id': comment['block_id']} |
            ({} if comment['anchor_type'] == 'BLOCK' else comment['anchor_ref'])}
        internal = create_guide_run_input({'requirement_id': root['id'], 'expected_discussion_version': request.expected_discussion_version,
            'operation': 'PROPOSE_CHANGES', 'instruction': comment['content'],
            'target': {'kind': 'EXISTING', 'document_id': current['id'], 'expected_content_version': current['content_version']},
            'scope': scope, 'source_refs': [], 'proposal_ref': None, 'acknowledge_source_changes': False, 'idempotency_key': request.idempotency_key})
        data = _accept_collaboration(connection, internal, resources, at, comment_source=comment)
        return Success({'code': 'GUIDE_ACCEPTED', 'data': data, 'details': None}, 202)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C05', request, operation, target_identity='Comment:'+str(request.comment_id),
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'DISCUSSION_VERSION_CONFLICT',
            'CONTENT_VERSION_CONFLICT', 'COMMENT_ORPHANED', 'SOURCE_INVALID', 'SCOPE_INVALID', 'CONFIG_INVALID'}))


def retry_guide_run(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    try:
        request = retry_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        previous = GuideRepository(connection).get(request.guide_run_id)
        if previous is None:
            raise Rejected('NOT_FOUND')
        if previous['status'] != 'FAILED':
            raise Rejected('STATE_CONFLICT')
        root = RequirementRepository(connection).get(previous['requirement_id'])
        if root is None or root['discussion_version'] != previous['discussion_version_snapshot']:
            raise Rejected('STATE_CONFLICT')
        basis = strict_json_object(previous['execution_basis_json'])
        message = MessageRepository(connection).get(previous['trigger_message_id'])
        if message is None or message['requirement_id'] != root['id'] or message['role'] != 'USER':
            raise Rejected('SOURCE_INVALID')
        # This explicit retry recalculates authority from the fixed request;
        # none of the predecessor's allowed_targets or one-shot proof is reused.
        internal = create_guide_run_input({**basis['request'], 'expected_discussion_version': root['discussion_version'],
            'proposal_ref': None, 'acknowledge_source_changes': False, 'idempotency_key': request.idempotency_key})
        comment_source = basis.get('comment_source')
        if comment_source is not None:
            actual_comment = CommentRepository(connection).get(comment_source['id'])
            if actual_comment is None or get_comment_result(actual_comment) != comment_source:
                raise Rejected('SOURCE_INVALID')
        try:
            data = _accept_collaboration(connection, internal, catalog or ResourceCatalog(), operation_time(clock),
                retry_of=previous['id'], reuse_message=message, comment_source=comment_source)
        except ConfigInvalid:
            raise Rejected('CONFIG_INVALID') from None
        return Success({'code': 'GUIDE_RETRY_ACCEPTED', 'data': data, 'details': None}, 202)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C04', request, operation, target_identity=f'GuideRun:{request.guide_run_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT',
            'CONTENT_VERSION_CONFLICT', 'SOURCE_INVALID', 'SCOPE_INVALID', 'CONFIG_INVALID'}))


def _pending_batches(connection, requirement_id):
    rows = connection.execute("SELECT b.id,b.requirement_id,b.guide_run_id,b.source_type,b.source_id,b.created_at,g.requirement_id AS run_requirement_id,g.action_type,g.status AS run_status,g.source_type AS run_source_type,g.source_id AS run_source_id FROM suggestion_batches b LEFT JOIN guide_runs g ON g.id=b.guide_run_id WHERE b.requirement_id=? AND b.status='PENDING' ORDER BY b.id", (requirement_id,)).fetchall()
    for row in rows:
        if row['run_requirement_id'] != requirement_id or row['action_type'] != 'MODIFY' or row['run_status'] != 'COMPLETED' or row['source_type'] != row['run_source_type'] or row['source_id'] != row['run_source_id'] or connection.execute('SELECT 1 FROM suggestions WHERE batch_id=? LIMIT 1', (row['id'],)).fetchone() is None:
            raise Rejected('WORK_STATE_INCONSISTENT')
        _time(row['created_at'])
    if len(rows) > 1:
        raise Rejected('WORK_STATE_INCONSISTENT')
    return rows


def _recover_root(connection, repository, root, at):
    state, identity = root['document_work_state'], root['active_operation_id']
    if state == 'IDLE':
        assert_idle(connection, root, remaining_conflicts=frozenset())
        return False
    if state == 'MANUAL_EDITING':
        active_manual_draft(connection, root)
        return False
    if state == 'GUIDE_ACTIVE':
        run = connection.execute('SELECT id,requirement_id,status FROM guide_runs WHERE id=?', (identity,)).fetchone()
        if run is None or run['requirement_id'] != root['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        if run['status'] in ('RUNNING', 'WAITING_USER'):
            try:
                assert_idle(connection, root, remaining_conflicts=frozenset())
            except Rejected as error:
                if error.code != 'WORK_STATE_CONFLICT':
                    raise
                return False
            raise Rejected('WORK_STATE_INCONSISTENT')
        if run['status'] not in TERMINAL_RUNS:
            raise Rejected('WORK_STATE_INCONSISTENT')
        batches = _pending_batches(connection, root['id'])
        if batches and batches[0]['guide_run_id'] != run['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
    elif state == 'SUGGESTION_REVIEWING':
        batch = connection.execute('SELECT b.requirement_id,b.guide_run_id,b.status,g.requirement_id AS run_requirement_id FROM suggestion_batches b LEFT JOIN guide_runs g ON g.id=b.guide_run_id WHERE b.id=?', (identity,)).fetchone()
        if batch is None or batch['requirement_id'] != root['id'] or batch['run_requirement_id'] != root['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        batches = _pending_batches(connection, root['id'])
        if batch['status'] == 'PENDING':
            if not batches or batches[0]['id'] != identity:
                raise Rejected('WORK_STATE_INCONSISTENT')
            try:
                assert_idle(connection, root, remaining_conflicts=frozenset())
            except Rejected as error:
                if error.code != 'WORK_STATE_CONFLICT':
                    raise
                return False
            raise Rejected('WORK_STATE_INCONSISTENT')
        if batch['status'] not in ('COMPLETED', 'DISCARDED') or batches:
            raise Rejected('WORK_STATE_INCONSISTENT')
    else:
        raise Rejected('WORK_STATE_INCONSISTENT')
    # A terminal pointer alone cannot prove ownership of another live activity.
    if connection.execute("SELECT 1 FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT'", (root['id'],)).fetchone() or connection.execute("SELECT 1 FROM guide_runs WHERE requirement_id=? AND status IN ('RUNNING','WAITING_USER')", (root['id'],)).fetchone():
        raise Rejected('WORK_STATE_INCONSISTENT')
    candidate = batches[0] if batches else None
    repository.recover_occupancy(root, None if candidate is None else candidate['id'], None if candidate is None else candidate['created_at'], at)
    return True


def recover_runs(database: Database, payload: object, *, process_lock: ProcessLock, catalog=None) -> dict:
    try:
        request = recover_runs_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path:
            raise RuntimeError('Recovery lock must own the same actual database')
        from .collaboration_recovery import complete_saved_returns
        completed = complete_saved_returns(database, request, process_lock, ResourceCatalog() if catalog is None else catalog)
        with database.transaction(write=True) as connection:
            guides, requirements = GuideRepository(connection), RequirementRepository(connection)
            recovered, repaired, unchanged = list(completed), [], []
            now = datetime.fromisoformat(request.operation_time[:-1] + '+00:00')
            for run in guides.running():
                created, updated = _time(run['created_at']), _time(run['updated_at'])
                if created > updated or updated > request.operation_time:
                    raise ValueError('Persisted run progress clock is invalid')
                interrupted = request.recovery_reason == 'STARTUP' and run['id'] not in request.live_run_ids
                timed_out = request.recovery_reason == 'NO_PROGRESS' and now - datetime.fromisoformat(updated[:-1] + '+00:00') >= timedelta(minutes=15)
                if interrupted or timed_out:
                    if requirements.get(run['requirement_id']) is None:
                        raise Rejected('WORK_STATE_INCONSISTENT')
                    code = 'INTERRUPTED' if interrupted else 'EXECUTION_TIMEOUT'
                    guides.recover_failed(run['id'], code, RECOVERY_ERRORS[code], request.operation_time)
                    recovered.append(run['id'])
            for root in requirements.all_roots():
                if root['updated_at'] > request.operation_time:
                    raise ValueError('Recovery cannot precede persisted requirement activity')
                (repaired if _recover_root(connection, requirements, root, request.operation_time) else unchanged).append(root['id'])
            result = recover_runs_result(request, sorted(recovered), repaired, unchanged)
        return result
    except Rejected:
        code = 'WORK_STATE_INCONSISTENT'
    except (StorageUnavailable, sqlite3.Error):
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}


def cancel_guide_run(executor: Idempotency, payload: object, *, clock=None) -> dict:
    """C03 atomic logical cancellation; no network I/O in the transaction."""
    try:
        request = cancel_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        guides = GuideRepository(connection)
        run = guides.get_status(request.guide_run_id)
        if run is None:
            raise Rejected('NOT_FOUND')
        if run['status'] == 'CANCELLED':
            # A new cancellation key still observes the original result; the
            # requirement may legitimately own a newer operation by now.
            return Success(cancel_guide_run_result(run), 200)
        if run['status'] == 'COMPLETED':
            message, batches = guides.status_references(run)
            return Success({'code': 'GUIDE_ALREADY_COMPLETED', 'data': get_guide_run_result(connection, run, message, batches), 'details': None}, 200)
        if run['status'] != 'RUNNING':
            raise Rejected('STATE_CONFLICT')
        requirements = RequirementRepository(connection)
        root = requirements.get(run['requirement_id'])
        if root is None or root['document_work_state'] != 'GUIDE_ACTIVE' or root['active_operation_type'] != 'GUIDE_RUN' or root['active_operation_id'] != run['id']:
            raise Rejected('WORK_STATE_INCONSISTENT')
        try:
            assert_idle(connection, root, remaining_conflicts=frozenset())
        except Rejected as error:
            if error.code != 'WORK_STATE_CONFLICT':
                raise
        else:
            raise Rejected('WORK_STATE_INCONSISTENT')
        at = operation_time(clock)
        if _time(run['created_at']) > _time(run['updated_at']) or run['updated_at'] > at or root['updated_at'] > at:
            raise ValueError('Cancellation cannot precede persisted activity')
        cancelled = guides.cancel(run['id'], at)
        requirements.recover_occupancy(root, None, None, at)
        return Success(cancel_guide_run_result(cancelled), 200)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C03', request, operation,
        target_identity=f'GuideRun:{request.guide_run_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_INCONSISTENT'}))


def fail_guide_run(database: Database, payload: object, *, process_lock: ProcessLock, clock=None) -> dict:
    """C08 trusted failure summary; a late failure never overwrites a result."""
    try:
        request = fail_guide_run_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path:
            raise RuntimeError('Failure writer must own the same actual database')
        with database.transaction(write=True) as connection:
            guides, requirements = GuideRepository(connection), RequirementRepository(connection)
            run = guides.get_status(request.guide_run_id)
            if run is None:
                raise Rejected('NOT_FOUND')
            # P01 requires RUNNING. A committed WAITING_USER result is also
            # protected from a delayed attempt failure, just like terminal runs.
            if run['status'] != 'RUNNING':
                result = fail_guide_run_result(run, False, unchanged=True)
            else:
                root = requirements.get(run['requirement_id'])
                if root is None:
                    raise Rejected('WORK_STATE_INCONSISTENT')
                owns = root['document_work_state'] == 'GUIDE_ACTIVE' and root['active_operation_type'] == 'GUIDE_RUN' and root['active_operation_id'] == run['id']
                if owns:
                    try:
                        assert_idle(connection, root, remaining_conflicts=frozenset())
                    except Rejected as error:
                        if error.code != 'WORK_STATE_CONFLICT':
                            raise
                    else:
                        raise Rejected('WORK_STATE_INCONSISTENT')
                at = operation_time(clock)
                if _time(run['created_at']) > _time(run['updated_at']) or run['updated_at'] > at or (owns and root['updated_at'] > at):
                    raise ValueError('Failure cannot precede persisted activity')
                guides.recover_failed(run['id'], request.error_code, request.safe_message, at)
                if owns:
                    requirements.recover_occupancy(root, None, None, at)
                result = fail_guide_run_result(guides.get_status(run['id']), owns, unchanged=False)
        return result
    except Rejected as error:
        code = error.code if error.code in ('NOT_FOUND', 'WORK_STATE_INCONSISTENT') else 'INTERNAL_ERROR'
    except (StorageUnavailable, sqlite3.Error):
        code = 'STORAGE_UNAVAILABLE'
    except Exception:
        code = 'INTERNAL_ERROR'
    return {'code': code, 'data': None, 'details': None}
