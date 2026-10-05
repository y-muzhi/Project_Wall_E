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
from backend.app.messages.cards import CardsInvalid, decode_cards, validate_responses
from backend.app.messages.queries import card_state, project_message

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


def create_guide_run(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    """C01 real accepted USER/run/occupancy transaction; dispatch is separate."""
    try: request = create_guide_run_input(payload)
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        requirements = RequirementRepository(connection)
        root = requirements.get(request.requirement_id)
        if root is None: raise Rejected('NOT_FOUND')
        allowed = {'INITIALIZING': ('INITIALIZE',), 'ACTIVE': ('ASK', 'REVIEW', 'MODIFY'), 'COMPLETED': ('ASK',)}
        if request.action_type not in allowed[root['status']]: raise Rejected('STATE_CONFLICT')
        assert_idle(connection, root, remaining_conflicts=frozenset())
        current = current_at_version(connection, root['id'], request.expected_content_version)
        try:
            resources = catalog if catalog is not None else ResourceCatalog()
            _review_source(connection, resources, request)
            function = resources.freeze(request.action_type, request.source_type)
            template = resources.template(root['requirement_type'], root['template_key'], root['template_version'])
        except (ConfigInvalid, TemplateInvalid): raise Rejected('CONFIG_INVALID') from None
        sources = DocumentSources(connection, root['id'], resources)
        try:
            model = get_current_document_result(current, sources)
            snapshot = validate_snapshot(model['markdown_content'], model['block_state_json'], sources)
        except ValueError: raise Rejected('WORK_STATE_INCONSISTENT') from None
        try: scope = resolve_scope(snapshot, request.action_type, request.scope_type, request.scope_ref)
        except ScopeInvalid: raise Rejected('SCOPE_INVALID') from None
        at = operation_time(clock)
        if root['updated_at'] > at or current['updated_at'] > at: raise ValueError('Acceptance cannot precede persisted activity')
        guide_id, message_id = entity_id(connection, EntityKind.GUIDE_RUN), entity_id(connection, EntityKind.MESSAGE)
        message = MessageRepository(connection).create_user_text(message_id, root['id'], guide_id, request.instruction, request.idempotency_key, at)
        context_key, context_version = function.context_template.split('@')
        prompt_key, prompt_version = function.prompt_reference.split('@')
        manifest = {'document_id': current['id'], 'content_version': current['content_version'], 'block_ids': list(scope.read_ids), 'message_ids': [message_id],
            'template': {'key': template.key, 'version': template.version}, 'source': {'source_type': request.source_type, 'source_id': request.source_id},
            'context_template': {'key': context_key, 'version': context_version}, 'prompt': {'key': prompt_key, 'version': prompt_version}, 'function_type': function.function_type}
        function.validate_allowed_targets({'schema_version': 1, 'targets': scope.targets_json})
        manifest = function.validate_read_manifest(manifest)
        run = GuideRepository(connection).accept(guide_id, root, message, function, scope, manifest, at)
        requirements.occupy_guide(root['id'], guide_id, at)
        return Success(create_guide_run_result(run, message), 202)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C01', request, operation, allowed_failures=frozenset({
        'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'SOURCE_INVALID', 'SCOPE_INVALID', 'CONFIG_INVALID'}))


def continue_guide_run(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    """C02 ordinary text resumes the existing frozen run, never formal answers."""
    try: request = continue_guide_run_input(payload)
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        guides = GuideRepository(connection)
        run = guides.get(request.guide_run_id)
        if run is None: raise Rejected('NOT_FOUND')
        if run['action_type'] not in ('ASK', 'REVIEW', 'MODIFY') or run['status'] != 'WAITING_USER': raise Rejected('STATE_CONFLICT')
        root = RequirementRepository(connection).get(run['requirement_id'])
        _owned_guide(connection, root, run)
        try:
            resources = catalog if catalog is not None else ResourceCatalog()
            function = resources.restore(run['function_type'], run['prompt_version'], prompt_version=run['prompt_version'], context_template=run['context_template_key']+'@'+run['context_template_version'])
        except ConfigInvalid: raise Rejected('CONFIG_INVALID') from None
        if function.action_type != run['action_type'] or function.source_type != run['source_type']: raise Rejected('WORK_STATE_INCONSISTENT')
        at = operation_time(clock)
        if run['updated_at'] > at or root['updated_at'] > at: raise ValueError('Continuation cannot precede persisted activity')
        message = MessageRepository(connection).create_user_text(entity_id(connection, EntityKind.MESSAGE), root['id'], run['id'], request.instruction, request.idempotency_key, at)
        resumed = guides.continue_run(run['id'], message, at)
        return Success(continue_guide_run_result(resumed), 202)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C02', request, operation, target_identity=f'GuideRun:{request.guide_run_id}',
        allowed_failures=frozenset({'NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT', 'WORK_STATE_INCONSISTENT', 'CONFIG_INVALID'}))


def _answer_summary(cards, answers):
    by_key = {answer['card_key']: answer for answer in answers['responses']}
    lines = []
    for card in cards['cards']:
        answer = by_key[card['card_key']]
        lines.append(card['question'])
        if answer['skipped']: lines.append('已跳过')
        else:
            options = {option['option_key']: option for option in card['options']}
            lines.extend(options[key]['label'] for key in answer['selected_option_keys'])
            if answer['custom_answer'] is not None: lines.append(answer['custom_answer'])
    return '\n'.join(lines)


def submit_card_responses(executor: Idempotency, payload: object, *, catalog=None, clock=None) -> dict:
    """C06 one formal whole-group answer and exactly one accepted run transition."""
    try: request = submit_card_responses_input(payload)
    except InvalidInput as error: return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    def operation(connection):
        messages, guides, requirements = MessageRepository(connection), GuideRepository(connection), RequirementRepository(connection)
        original = messages.get(request.message_id)
        if original is None: raise Rejected('NOT_FOUND')
        if original['role'] != 'ASSISTANT' or original['message_type'] != 'INTERACTION_CARDS': raise Rejected('SOURCE_INVALID')
        source = guides.get(original['guide_run_id']) if original['guide_run_id'] is not None else None
        if source is None: raise Rejected('NOT_FOUND')
        root = requirements.get(original['requirement_id'])
        if root is None or source['requirement_id'] != root['id']: raise Rejected('WORK_STATE_INCONSISTENT')
        try:
            resources = catalog if catalog is not None else ResourceCatalog()
            protocol = resources.restore(source['function_type'], source['prompt_version'], prompt_version=source['prompt_version'], context_template=source['context_template_key']+'@'+source['context_template_version'])
        except ConfigInvalid: raise Rejected('CONFIG_INVALID') from None
        if protocol.action_type != source['action_type'] or protocol.source_type != source['source_type']: raise Rejected('WORK_STATE_INCONSISTENT')
        try: cards = decode_cards(original['structured_content_json'], protocol)
        except (CardsInvalid, InvalidInput, ProtocolInvalid): raise Rejected('SOURCE_INVALID') from None
        try: state = card_state(messages, root, original, protocol, resources)
        except ConfigInvalid: raise Rejected('CONFIG_INVALID') from None
        except (ValueError, InvalidInput, ProtocolInvalid): raise Rejected('WORK_STATE_INCONSISTENT') from None
        if state == 'ANSWERED':
            raise Rejected('CARD_ALREADY_ANSWERED', details={'response_message_id': messages.formal_responses(original['id'])[0]['id']})
        if state != 'AVAILABLE': raise Rejected('CARD_EXPIRED')
        try: answers = validate_responses(request.answers, cards, protocol)
        except (CardsInvalid, InvalidInput, ProtocolInvalid):
            raise Rejected('INVALID_INPUT', details={'field_errors': [{'field': 'responses', 'reason': 'INVALID_FORMAT', 'message': '回答必须满足原卡片的完整组、选项、必答及数量约束'}]}) from None
        at = operation_time(clock)
        if original['created_at'] > at or source['updated_at'] > at or root['updated_at'] > at: raise ValueError('Answer cannot precede persisted activity')
        initialize = source['action_type'] == 'INITIALIZE'
        guide_id = entity_id(connection, EntityKind.GUIDE_RUN) if initialize else source['id']
        response = messages.create_card_response(entity_id(connection, EntityKind.MESSAGE), root['id'], guide_id, original, _answer_summary(cards, answers), answers, request.idempotency_key, at)
        if initialize:
            # Availability already proves an idle initialization and matching
            # CURRENT identity/version. Recheck and derive actual authority.
            current = current_at_version(connection, root['id'], messages.current_identity(root['id'])[0]['content_version'])
            if current['updated_at'] > at: raise ValueError('Answer cannot precede actual document activity')
            try:
                function = resources.freeze('INITIALIZE', 'USER_INSTRUCTION')
                template = resources.template(root['requirement_type'], root['template_key'], root['template_version'])
            except (ConfigInvalid, TemplateInvalid): raise Rejected('CONFIG_INVALID') from None
            sources = DocumentSources(connection, root['id'], resources)
            try:
                model = get_current_document_result(current, sources)
                snapshot = validate_snapshot(model['markdown_content'], model['block_state_json'], sources)
                reference = None if source['scope_ref_json'] is None else strict_json_object(source['scope_ref_json'])
                scope = resolve_scope(snapshot, 'INITIALIZE', source['scope_type'], reference)
            except (ValueError, InvalidInput): raise Rejected('WORK_STATE_INCONSISTENT') from None
            context_key, context_version = function.context_template.split('@'); prompt_key, prompt_version = function.prompt_reference.split('@')
            manifest = {'document_id': current['id'], 'content_version': current['content_version'], 'block_ids': list(scope.read_ids), 'message_ids': [original['id'], response['id']],
                'template': {'key': template.key, 'version': template.version}, 'source': {'source_type': 'USER_INSTRUCTION', 'source_id': None},
                'context_template': {'key': context_key, 'version': context_version}, 'prompt': {'key': prompt_key, 'version': prompt_version}, 'function_type': function.function_type}
            function.validate_allowed_targets({'schema_version': 1, 'targets': scope.targets_json})
            run = guides.accept(guide_id, root, response, function, scope, function.validate_read_manifest(manifest), at, trigger_type='CARD_RESPONSE')
            root = requirements.occupy_guide(root['id'], guide_id, at)
        else:
            _owned_guide(connection, root, source)
            run = guides.continue_run(guide_id, response, at, trigger_type='CARD_RESPONSE')
        projected = project_message(messages, root, response, protocol, resources)
        return Success(submit_card_responses_result(run, projected), 202)
    return execute_idempotent(executor, 'APP-GUIDE-CMD-C06', request, operation, target_identity=f'Message:{request.message_id}',
        allowed_failures=frozenset({'INVALID_INPUT', 'NOT_FOUND', 'SOURCE_INVALID', 'CARD_ALREADY_ANSWERED', 'CARD_EXPIRED', 'WORK_STATE_INCONSISTENT', 'CONFIG_INVALID'}))


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


def recover_runs(database: Database, payload: object, *, process_lock: ProcessLock) -> dict:
    try:
        request = recover_runs_input(payload)
    except InvalidInput as error:
        return {'code': 'INVALID_INPUT', 'data': None, 'details': error.details}
    try:
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path:
            raise RuntimeError('Recovery lock must own the same actual database')
        with database.transaction(write=True) as connection:
            guides, requirements = GuideRepository(connection), RequirementRepository(connection)
            recovered, repaired, unchanged = [], [], []
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
            result = recover_runs_result(request, recovered, repaired, unchanged)
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
        if run['status'] not in ('RUNNING', 'WAITING_USER') or run['current_step'] == 'PERSISTING':
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
