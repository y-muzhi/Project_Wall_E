"""C07 sealed real audit -> atomic business result on the owned file DB."""
import sqlite3

from backend.app.comments.commands import revalidate_anchors
from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.patch_application import apply_confirmed_facts
from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.scopes import restore_authority
from backend.app.documents.snapshot import validate_snapshot, validate_template_lock
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment, message_sequence, CapacityExhausted
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.resources import ResourceCatalog, ConfigInvalid, ProtocolInvalid
from backend.app.messages.cards import CardsInvalid
from backend.app.shared.command_execution import Rejected, operation_time
from backend.app.shared.validation import InvalidInput, strict_json_object
from .output_evidence import OutputEvidenceInvalid
from .trusted_output import audited_context, validate_business_output, _original_content
from .contracts import persist_ai_result_input, persist_ai_result_result


def _batch(connection,run,output,version,at):
    identity=entity_id(connection,EntityKind.BATCH)
    fields={'id':identity,'requirement_id':run['requirement_id'],'guide_run_id':run['id'],'source_type':run['source_type'],'source_id':run['source_id'],
        'title':output['title'],'summary':output['summary'],'status':'PENDING','completion_result':None,'error_message':None,
        'base_content_version':version,'applied_content_version':None,'created_at':at,'completed_at':None,'updated_at':at}
    connection.execute('INSERT INTO suggestion_batches('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',tuple(fields.values()))
    for order,patch in enumerate(output['suggestions'],1):
        item={'id':entity_id(connection,EntityKind.SUGGESTION),'batch_id':identity,'order_no':order,'title':patch['title'],'explanation':patch['explanation'],
            'impact':patch['impact'],'patch_operation':patch['patch_operation'],'target_ref_json':canonical_input(patch['target_ref']),
            'selector_json':None if patch['selector_json'] is None else canonical_input(patch['selector_json']),'original_content':patch['original_content'],
            'proposed_markdown':patch['proposed_markdown'],'proposed_data_json':None if patch['proposed_data_json'] is None else canonical_input(patch['proposed_data_json']),
            'user_edited_content':None,'status':'PENDING','validation_status':'VALID','validation_error':None,'created_at':at,'decided_at':None,'updated_at':at}
        connection.execute('INSERT INTO suggestions('+','.join(item)+') VALUES ('+','.join('?' for _ in item)+')',tuple(item.values()))
    return identity


def persist_ai_result(database,payload,*,process_lock,profile,catalog=None,clock=None):
    try:request=persist_ai_result_input(payload)
    except InvalidInput as error:return {'code':'INVALID_INPUT','data':None,'details':error.details}
    except Rejected as error:return {'code':error.code,'data':None,'details':None}
    try:
        process_lock.assert_owned()
        if process_lock.path != ProcessLock.for_database(database.path).path:raise RuntimeError('C07 lock must own this database')
        resources=ResourceCatalog() if catalog is None else catalog;at=operation_time(clock)
        with database.transaction(write=True) as connection:
            audits=AuditRepository(connection);row=audits.get(request.llm_use_id)
            if row is None:raise Rejected('NOT_FOUND')
            receipt=request.trusted_output
            if row['guide_run_id'] != request.guide_run_id or (receipt.guide_run_id,receipt.llm_use_id) != (request.guide_run_id,request.llm_use_id):raise Rejected('OUTPUT_INVALID')
            if row['call_status'] != 'SUCCEEDED' or row['parse_status'] != 'SUCCEEDED' or row['validation_status'] != 'SUCCEEDED' or row['trusted_output_json'] is None:raise Rejected('OUTPUT_INVALID')
            run,root,function,actual,supplied=audited_context(connection,row,resources,profile)
            if (receipt.trigger_message_id,receipt.document_id,receipt.content_version,receipt.function_type,receipt.prompt_version,receipt.context_template) != (
                run['trigger_message_id'],supplied['read_manifest']['document_id'],supplied['read_manifest']['content_version'],function.function_type,function.version,function.context_template):raise Rejected('OUTPUT_INVALID')
            output=receipt.output
            if receipt.manifest != supplied['read_manifest'] or strict_json_object(row['trusted_output_json']) != output or function.parse_output(_original_content(row)) != output:raise Rejected('OUTPUT_INVALID')
            current=DocumentRepository(connection).by_requirement(root['id'],'CURRENT')[0]
            if at < max(run['updated_at'],root['updated_at'],current['updated_at'],row['ended_at']):raise ValueError('C07 cannot precede real persisted activity')
            gate=connection.execute("UPDATE guide_runs SET current_step='PERSISTING' WHERE id=? AND status='RUNNING' AND current_step='VALIDATING'",(run['id'],))
            if gate.rowcount != 1:raise Rejected('STATE_CONFLICT')
            validate_business_output(connection,output=output,function=function,actual=actual,supplied=supplied,catalog=resources)
            branch=output['response_type'];batch_id=None;current_effect=None
            if function.action_type == 'INITIALIZE':
                sources=DocumentSources(connection,root['id'],resources)
                snapshot=validate_snapshot(current['markdown_content'],strict_json_object(current['block_state_json']),sources)
                reference=None if run['scope_ref_json'] is None else strict_json_object(run['scope_ref_json'])
                authority=restore_authority(snapshot,'INITIALIZE',run['scope_type'],reference,run['allowed_targets_json'])
                adopted=apply_confirmed_facts(snapshot,[fact['patch'] for fact in output['confirmed_fact_patches']],authority,run['id'],at,sources)
                template=resources.template(root['requirement_type'],root['template_key'],root['template_version'])
                validate_template_lock(adopted,template,tuple(actual['template']['locked_heading_block_ids']))
                if adopted is not snapshot:
                    current=DocumentRepository(connection).replace_current(current,adopted,increment(current['content_version']),at)
                    revalidate_anchors(connection,{'requirement_id':root['id'],'new_document':{'markdown_content':adopted.parsed.markdown,'block_state_json':adopted.state}},catalog=resources)
                current_effect={'id':current['id'],'content_version':current['content_version']}
            elif branch == 'SUGGESTIONS':batch_id=_batch(connection,run,output,current['content_version'],at)
            assistant_id=entity_id(connection,EntityKind.MESSAGE)
            cards=output.get('cards')
            connection.execute("INSERT INTO conversation_messages VALUES (?,?,?,?,'ASSISTANT',?,?,?,NULL,NULL,?)",
                (assistant_id,root['id'],run['id'],message_sequence(connection,root['id']),
                    output['message'],'TEXT' if cards is None else 'INTERACTION_CARDS',None if cards is None else canonical_input(cards),at))
            waiting=branch in ('CLARIFY_TEXT','CLARIFY_CARDS')
            status='WAITING_USER' if waiting else 'COMPLETED'
            effects={'guide_run_id':run['id'],'status':status,'assistant_message_id':assistant_id,'current_document':current_effect,'suggestion_batch_id':batch_id}
            final=None
            if not waiting:
                final={**effects}
                if branch == 'REVIEW_RESULT':final['review_result']=output['review_result']
            changed=connection.execute("UPDATE guide_runs SET status=?,current_step=?,final_result_json=?,waiting_user_at=?,ended_at=?,updated_at=?,error_code=NULL,error_message=NULL WHERE id=? AND status='RUNNING' AND current_step='PERSISTING'",
                (status,'WAITING_USER' if waiting else 'FINISHED',None if final is None else canonical_input(final),at if waiting else run['waiting_user_at'],None if waiting else at,at,run['id']))
            if changed.rowcount != 1:raise Rejected('STATE_CONFLICT')
            if not waiting:RequirementRepository(connection).recover_occupancy(root,batch_id,at if batch_id is not None else None,at)
            # Conversion is part of the same rollback boundary. The original
            # occurred audit was committed earlier and cannot be erased here.
            result=persist_ai_result_result(effects)
        return result
    except Rejected as error:code=error.code
    except (ProtocolInvalid,CardsInvalid,OutputEvidenceInvalid,PatchInvalid,TargetStale,DocumentInvalid):code='OUTPUT_INVALID'
    except ConfigInvalid:code='CONFIG_INVALID'
    except CapacityExhausted:code='CAPACITY_EXHAUSTED'
    except (StorageUnavailable,sqlite3.Error):code='STORAGE_UNAVAILABLE'
    except Exception:code='INTERNAL_ERROR'
    return {'code':code,'data':None,'details':None}
