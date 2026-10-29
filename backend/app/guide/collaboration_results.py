"""C07 V1.5 actual audited return -> independent results in one transaction."""
import json

from backend.app.infrastructure.audit_repository import AuditRepository, _owned
from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.practical_usage import validate_collaboration_usage
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.collaboration_resources import OUTPUTS
from backend.app.infrastructure.resources import ProtocolInvalid, ConfigInvalid
from backend.app.shared.command_execution import Rejected, operation_time
from .collaboration_counting import restore_counted, verify_counted
from .collaboration_context import read_canonical
from .progress_application import apply_progress, ProgressInvalid, carried_aliases
from .response_display import response_text


def persist_collaboration_result(database, identity, *, process_lock, profile, catalog, clock=None, recovery_updated_at=None):
    process_lock.assert_owned()
    if process_lock.path != ProcessLock.for_database(database.path).path:
        raise RuntimeError('C07 must own this database')
    at = operation_time(clock)
    with database.transaction(write=True) as connection:
        return _persist_in_transaction(connection, identity, profile=profile, catalog=catalog, at=at, recovery_updated_at=recovery_updated_at)


def _persist_in_transaction(connection, identity, *, profile, catalog, at, recovery_updated_at=None):
    from backend.app.infrastructure.identifiers import require_write_transaction
    require_write_transaction(connection)
    audits = AuditRepository(connection);row = audits.get(identity)
    if row is None:
        raise Rejected('NOT_FOUND')
    run = GuideRepository(connection).get(row['guide_run_id']);root = _owned(connection, run)
    if recovery_updated_at is not None and run['updated_at'] != recovery_updated_at:
        raise Rejected('STATE_CONFLICT')
    if run['function_type'] != 'collaboration_v1' or row['ended_at'] is None or run['current_step'] not in ('VALIDATING', 'CALLING_MODEL'):
        raise Rejected('STATE_CONFLICT')
    if at < max(run['updated_at'], root['updated_at'], row['ended_at']):
        raise ValueError('C07 cannot precede actual activity')
    latest = connection.execute('SELECT id FROM llm_uses WHERE guide_run_id=? ORDER BY id DESC LIMIT 1', (run['id'],)).fetchone()
    if latest is None or latest['id'] != identity:
        raise Rejected('STATE_CONFLICT')
    snapshot = json.loads(row['request_snapshot_json'])
    catalog = catalog.for_collaboration_release(snapshot['protocol']['release'])
    context = restore_counted(snapshot, catalog, profile)
    frozen = read_canonical(connection, run['id'], catalog, require_current=False)
    verify_counted(context, catalog, profile, expected_canonical=frozen)
    raw = json.loads(row['raw_response_json']) if row['raw_response_json'] is not None else None
    original = response_text(raw)
    if original is None:
        raise Rejected('OUTPUT_INVALID')
    resources = catalog.collaboration
    primary = None;progress = None;cards = None;validation_error = None;header_valid = False
    progress_result, progress_error = 'NOT_REQUESTED', None
    reference_map = {}
    application = 'NOT_APPLIED' if run['operation'] in ('GENERATE', 'REVISE', 'PROPOSE_CHANGES') else 'NOT_REQUESTED'
    effect = None;batch_id = None;analysis = None
    try:
        validate_collaboration_usage(raw, profile=profile, context=context, catalog=catalog, input_tokens=row['input_tokens'], output_tokens=row['output_tokens'])
        if row['call_status'] != 'SUCCEEDED' or row['parse_status'] != 'SUCCEEDED' or row['finish_reason'] != 'stop':
            raise ValueError('A normal single-object return is required')
        parsed = json.loads(row['parsed_output_json'])
        keys = {'schema_version', 'response_type', 'message', 'basis_ref', 'progress_delta', 'cards', 'document_result', 'suggestions', 'analysis'}
        if set(parsed) != keys or type(parsed['schema_version']) is not int or parsed['schema_version'] != 1:
            raise ValueError('Response header fields differ')
        resources.validate('BasisRef', parsed['basis_ref'])
        from backend.app.shared.validation import raw_text
        raw_text(parsed['message'], 'message', 1, 100000)
        types = {'DISCUSS': ('DISCUSSION', 'ANALYSIS'), 'GENERATE': ('DOCUMENT_RESULT', 'ANALYSIS'),
            'REVISE': ('DOCUMENT_RESULT', 'ANALYSIS'), 'PROPOSE_CHANGES': ('CHANGE_PROPOSALS', 'ANALYSIS'),
            'COMPARE': ('ANALYSIS',), 'REVIEW': ('ANALYSIS',)}
        if parsed['basis_ref'] != context.input['current_request']['basis_ref'] or parsed['response_type'] not in types[run['operation']]:
            raise ValueError('Response header differs from its accepted operation/basis')
        header_valid = True;progress, cards = parsed['progress_delta'], parsed['cards']
        # Public header and main result have an independent Schema check.
        # An invalid progress component cannot veto an authorized document.
        candidate = {**parsed, 'progress_delta': None, 'cards': None}
        primary = resources.validate(OUTPUTS[run['operation']], candidate)
        if primary['basis_ref'] != context.input['current_request']['basis_ref']:
            raise ValueError('Response basis differs from the frozen round')
        if primary['analysis'] is not None:
            allowed = carried_aliases(context)
            covered = primary['analysis']['covered_refs']
            if len(set(covered)) != len(covered) or any(ref not in allowed for ref in covered):
                raise ValueError('Analysis coverage names unavailable material')
            analysis = primary['analysis']
            if analysis['conclusion'] == 'NO_CHANGE':
                application = 'NO_CHANGE' if run['operation'] in ('REVISE', 'PROPOSE_CHANGES') else application
    except (ValueError, KeyError, TypeError, ConfigInvalid, ProtocolInvalid):
        primary = None;validation_error = '返回未通过本轮结构、依据或实际用量校验，未应用业务变更。'
        if row['finish_reason'] == 'length':
            validation_error = ('输出不完整，未写入。请新建固定框架文档，选择章节分次生成。' if run['operation'] == 'GENERATE'
                else '输出不完整，未写入。原文档及已保存章节保持不变，请选择更小的章节范围后重新发送。')
    assistant_id = entity_id(connection, EntityKind.MESSAGE)
    if header_valid and progress is not None:
        try:
            changed, reference_map = apply_progress(root['discussion_state_json'], progress, context, assistant_id, resources, return_mapping=True)
            if changed != root['discussion_state_json']:
                root = RequirementRepository(connection).update_discussion(root, changed, at);progress_result = 'APPLIED'
            else:
                progress_result = 'NO_CHANGE'
        except ProgressInvalid:
            progress_result = 'REJECTED';progress_error = '讨论增量的结构、引用或来源不符合本轮依据，未更新讨论进度。'
    if primary is not None and primary['document_result'] is not None:
        from .document_application import prepare_document_result
        from backend.app.documents.markdown import DocumentInvalid
        from backend.app.documents.patch_errors import PatchInvalid, TargetStale
        from backend.app.documents.scopes import ScopeInvalid
        try:
            commit_document = prepare_document_result(connection, run, context, primary['document_result'], catalog, at)
        except (Rejected, DocumentInvalid, PatchInvalid, TargetStale, ScopeInvalid):
            application = 'NOT_APPLIED'
            validation_error = '文档结果未通过目标、原文或授权范围校验，未写入正文。'
        else:
            # All semantic checks precede mutation. Repositories retain
            # the original shared-transaction no-commit/no-savepoint guard.
            effect = commit_document()
            application = 'NO_CHANGE' if effect['result'] == 'NO_CHANGE' else 'APPLIED'
    if primary is not None and primary['suggestions'] is not None:
        from .proposal_application import prepare_proposal_batch
        from backend.app.documents.markdown import DocumentInvalid
        from backend.app.documents.patch_errors import PatchInvalid, TargetStale
        from backend.app.documents.scopes import ScopeInvalid
        try:
            commit_batch = prepare_proposal_batch(connection, run, context, primary['suggestions'], catalog, at)
        except (Rejected, DocumentInvalid, PatchInvalid, TargetStale, ScopeInvalid):
            application = 'NOT_APPLIED'
            validation_error = '候选修改未通过固定目标和补丁校验，未建立审阅批次。'
        else:
            batch_id = commit_batch();application = 'APPLIED'
    stored_cards = None
    if primary is not None and cards is not None:
        try:
            from .card_binding import bind_cards
            stored_cards = bind_cards(connection, root, run, context, cards, catalog, reference_map=reference_map)
        except (Rejected, ValueError):
            validation_error = '卡片未通过用途、范围或引用校验，保留原始返回供阅读。'
    content = original if primary is None else primary['message']
    MessageRepository(connection).create_assistant(assistant_id, root['id'], run['id'], content, stored_cards, at,
        phase_ref=context.canonical['discussion']['phase']['phase_ref'],
        topic_refs=() if root['discussion_state_json']['focus_topic_ref'] is None else (root['discussion_state_json']['focus_topic_ref'],),
        document_ids=() if context.canonical['authorization']['target_document_id'] is None else (context.canonical['authorization']['target_document_id'],))
    # Preserve the actual return separately whenever a component was
    # rejected; the readable message must not masquerade as an applied one.
    summary = primary['message'][:10000] if primary is not None else validation_error if row['finish_reason'] == 'length' else '模型返回已保存；业务变更未应用。'
    effects = {'summary': summary, 'assistant_message_id': assistant_id, 'application_result': application,
        'progress_result': progress_result, 'progress_error': progress_error, 'document_effect': effect,
        'suggestion_batch_id': batch_id, 'analysis': analysis, 'validation_error': validation_error}
    if row['parse_status'] == 'SUCCEEDED':
        connection.execute('UPDATE llm_uses SET validation_status=?,validation_error=?,trusted_output_json=?,error_code=?,error_message=? WHERE id=?',
            ('SUCCEEDED' if validation_error is None and progress_error is None else 'FAILED', validation_error or progress_error,
             audit_json(parsed, credentials=(profile.api_key,)) if primary is not None and validation_error is None and progress_error is None else None, None if validation_error is None and progress_error is None else 'OUTPUT_INVALID',
             validation_error or progress_error, identity))
    gate = connection.execute("UPDATE guide_runs SET current_step='PERSISTING' WHERE id=? AND status='RUNNING' AND current_step IN ('VALIDATING','CALLING_MODEL')", (run['id'],))
    if gate.rowcount != 1:
        raise Rejected('STATE_CONFLICT')
    connection.execute("UPDATE guide_runs SET status='COMPLETED',current_step='FINISHED',final_result_json=?,ended_at=?,updated_at=? WHERE id=? AND status='RUNNING' AND current_step='PERSISTING'", (canonical_input(effects), at, at, run['id']))
    RequirementRepository(connection).recover_occupancy(root, batch_id, at if batch_id is not None else None, at)
    return {'code': 'AI_RESULT_PERSISTED', 'data': {'guide_run_id': run['id'], 'status': 'COMPLETED', 'assistant_message_id': assistant_id}, 'details': None}
