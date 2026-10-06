"""Real audited output -> sealed internal receipt, without business adoption.

Only this transaction produces validation SUCCEEDED. It re-reads original raw
assistant content, frozen Schema and actual C03 facts; scrubbed parsed audit
JSON is never a repaired candidate. Receipts are not an HTTP input type.
"""
from dataclasses import dataclass, field
import json

from backend.app.documents.markdown import DocumentInvalid
from backend.app.documents.patch_application import preview_patches
from backend.app.documents.patch_errors import PatchInvalid, TargetStale
from backend.app.documents.scopes import restore_authority
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.audit_repository import AuditRepository, _owned, verify_actual_context
from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.guide_repository import GuideRepository
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID, MODEL_VERSION
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog, ProtocolInvalid
from backend.app.messages.cards import CardsInvalid
from backend.app.shared.command_execution import Rejected, operation_time
from backend.app.shared.validation import strict_integer, strict_json_object
from .context_builder import BuiltContext
from .output_evidence import OutputEvidenceInvalid, validate_card_output, validate_fact_patches

_SEAL=object()


@dataclass(frozen=True,init=False)
class TrustedOutput:
    guide_run_id: int
    llm_use_id: int
    trigger_message_id: int
    document_id: int
    content_version: int
    function_type: str
    prompt_version: str
    context_template: str
    manifest_json: str = field(repr=False)
    output_json: str = field(repr=False)
    _seal: object = field(repr=False,compare=False)

    @property
    def output(self):return strict_json_object(self.output_json)

    @property
    def manifest(self):return strict_json_object(self.manifest_json)


def _receipt(run,row,function,manifest,output):
    receipt=object.__new__(TrustedOutput)
    values={'guide_run_id':run['id'],'llm_use_id':row['id'],'trigger_message_id':run['trigger_message_id'],
        'document_id':manifest['document_id'],'content_version':manifest['content_version'],
        'function_type':function.function_type,'prompt_version':function.version,'context_template':function.context_template,
        'manifest_json':canonical_input(manifest),'output_json':canonical_input(output),'_seal':_SEAL}
    for name,value in values.items():object.__setattr__(receipt,name,value)
    return receipt


def require_receipt(value):
    if type(value) is not TrustedOutput or getattr(value,'_seal',None) is not _SEAL:
        raise Rejected('OUTPUT_INVALID')
    return value


def audited_context(connection, row, catalog, profile):
    """No request or budget authorization; verify an already persisted attempt."""
    run=GuideRepository(connection).get(row['guide_run_id']);root=_owned(connection,run)
    latest=connection.execute('SELECT id FROM llm_uses WHERE guide_run_id=? ORDER BY call_no DESC,attempt_no DESC LIMIT 1',(run['id'],)).fetchone()
    if latest is None or latest['id'] != row['id'] or run['current_step'] != 'VALIDATING':raise Rejected('STATE_CONFLICT')
    function=catalog.restore(run['function_type'],run['prompt_version'],prompt_version=run['prompt_version'],context_template=run['context_template_key']+'@'+run['context_template_version'])
    if type(profile) is not ModelProfile or (row['provider'],row['model_name'],row['model_version'],row['function_type'],row['prompt_config']) != ('volcengine',MODEL_ID,MODEL_VERSION,function.function_type,function.prompt_reference):
        raise Rejected('CONFIG_INVALID')
    request_snapshot=strict_json_object(row['request_snapshot_json'])
    if 'counting' in request_snapshot and type(request_snapshot['counting']) is not dict:raise Rejected('CONFIG_INVALID')
    protocol={'function_type':function.function_type,'input_schema':function.input_schema,'output_schema':function.output_schema,
        'context_template':function.context_template,'prompt':function.prompt_reference,'manifest_sha256':function.manifest_sha256}
    if set(request_snapshot) not in ({'profile','request','protocol'},{'profile','request','protocol','counting'}) or request_snapshot['profile'] != profile.snapshot or request_snapshot['protocol'] != protocol:
        raise Rejected('CONFIG_INVALID')
    request=request_snapshot['request']
    if type(request) is not dict:raise Rejected('SOURCE_INVALID')
    messages=request.get('messages')
    if type(messages) is not list or len(messages) != 2 or any(type(message) is not dict for message in messages) or [message.get('role') for message in messages] != ['system','user'] or any(set(message) != {'role','content'} for message in messages):
        raise Rejected('SOURCE_INVALID')
    system,content=messages[0]['content'],messages[1]['content']
    supplied=strict_json_object(content)
    context=BuiltContext(system,content,row['context_manifest_json'],len(content.encode('utf-8')),(),())
    if request != profile.request(context):raise Rejected('CONFIG_INVALID')
    actual,supplied=verify_actual_context(connection,run['id'],function,supplied,system,row['context_manifest_json'],catalog,counting=request_snapshot.get('counting'),input_json=content,counting_summary=True)
    return run,root,function,actual,supplied


def validate_business_output(connection, *, output, function, actual, supplied, catalog):
    """All six tasks, original fields, current source and whole-bundle checks."""
    current=actual['current_document'];run=actual['run'];root=actual['requirement']
    sources=DocumentSources(connection,root['id'],catalog)
    snapshot=validate_snapshot(current['markdown_content'],current['block_state_json'],sources)
    manifest=supplied['read_manifest']
    reference=None if run['scope_ref_json'] is None else strict_json_object(run['scope_ref_json'])
    authority=restore_authority(snapshot,run['action_type'],run['scope_type'],reference,run['allowed_targets_json'])
    branch=output['response_type']
    if branch in ('INITIALIZE_CARDS','CLARIFY_CARDS'):
        validate_card_output(snapshot,manifest,output,function)
    if function.action_type in ('ASK','REVIEW') and supplied['allowed_targets']:
        raise OutputEvidenceInvalid('只读任务不允许写权限')
    if function.action_type == 'INITIALIZE':
        template=catalog.template(root['requirement_type'],root['template_key'],root['template_version'])
        validate_fact_patches(connection,requirement_id=root['id'],snapshot=snapshot,authority=authority,output=output,
            manifest=manifest,protocol=function,catalog=catalog,template=template,locked_heading_ids=actual['template']['locked_heading_block_ids'])
    elif branch == 'SUGGESTIONS':
        if any(item['target_ref']['block_id'] not in manifest['block_ids'] for item in output['suggestions']):
            raise OutputEvidenceInvalid('建议目标须在实际读取范围')
        preview_patches(snapshot,output['suggestions'],authority)
    elif branch == 'REVIEW_RESULT':
        issues=output['review_result']['issues'];keys=[item['issue_key'] for item in issues]
        if len(keys) != len(set(keys)):raise OutputEvidenceInvalid('检查项键必须唯一')
        read=set(manifest['block_ids'])
        for issue in issues:
            if not set(issue['block_ids']) <= read:raise OutputEvidenceInvalid('检查只能引用实际读取区块')
            evidence=issue['evidence']
            if not evidence:
                if issue['category'] != 'MISSING':raise OutputEvidenceInvalid('非缺失项须逐字原文证据')
            elif not _review_quote(snapshot,issue['block_ids'],evidence):
                raise OutputEvidenceInvalid('检查证据必须在所引实际原文')
    return output


def _review_quote(snapshot, identities, evidence):
    """Literal source only, including exact gaps across adjacent cited blocks."""
    cited=set(identities);groups=[];group=[]
    for identity,(block,_) in snapshot.by_id.items():
        if identity in cited:group.append(block)
        elif group:groups.append(group);group=[]
    if group:groups.append(group)
    for blocks in groups:
        source=snapshot.parsed.markdown[blocks[0].start_offset:blocks[-1].end_offset]
        visible=blocks[0].plain_text
        for before,after in zip(blocks,blocks[1:]):
            visible+=snapshot.parsed.markdown[before.end_offset:after.start_offset]+after.plain_text
        if evidence in source or evidence in visible:return True
    return False


def _original_content(row):
    """Repeat the successful original-envelope gate, never use parsed audit."""
    try:
        raw=strict_json_object(row['raw_response_json'])
        if raw.get('model') != MODEL_ID or type(raw.get('choices')) is not list or len(raw['choices']) != 1:raise ValueError()
        choice=raw['choices'][0]
        if type(choice) is not dict:raise ValueError()
        message=choice['message']
        if type(message) is not dict or row['finish_reason'] != 'stop' or choice.get('finish_reason') != 'stop' or message.get('role') != 'assistant' or message.get('refusal') or message.get('tool_calls') or message.get('function_call'):raise ValueError()
        content=message.get('content')
        if type(content) is not str or not content or len(content.encode('utf-8'))>1024*1024:raise ValueError()
        return content
    except (ValueError,KeyError,TypeError,UnicodeError):raise OutputEvidenceInvalid('原响应包络不满足已解析调用') from None


def produce_trusted_output(database, llm_use_id, *, process_lock, profile, catalog=None, clock=None):
    """Return a sealed receipt only after the actual validation commit succeeds.

    None means the original candidate failed and its failure was committed.
    Missing config, ownership, current version or stage is a rejection, never a
    fabricated success. Re-reading a committed valid audit re-proves its facts.
    """
    strict_integer(llm_use_id,'llm_use_id');process_lock.assert_owned()
    if process_lock.path != ProcessLock.for_database(database.path).path:raise RuntimeError('Validation lock must own this database')
    resources=ResourceCatalog() if catalog is None else catalog;at=operation_time(clock)
    result=None
    with database.transaction(write=True) as connection:
        audits=AuditRepository(connection);row=audits.get(llm_use_id)
        if row is None:raise Rejected('NOT_FOUND')
        if row['call_status'] != 'SUCCEEDED' or row['parse_status'] != 'SUCCEEDED' or row['validation_status'] not in ('NOT_STARTED','SUCCEEDED'):
            raise Rejected('STATE_CONFLICT')
        run,root,function,actual,supplied=audited_context(connection,row,resources,profile)
        if at < max(run['updated_at'],root['updated_at'],row['ended_at']):raise ValueError('Validation cannot precede prior activity')
        try:
            content=_original_content(row)
            if profile.api_key in content:raise OutputEvidenceInvalid('候选不可包含凭据')
            output=function.parse_output(content)
            validate_business_output(connection,output=output,function=function,actual=actual,supplied=supplied,catalog=resources)
        except (ProtocolInvalid,CardsInvalid,OutputEvidenceInvalid,PatchInvalid,TargetStale,DocumentInvalid):
            if row['validation_status'] == 'SUCCEEDED':raise Rejected('OUTPUT_INVALID') from None
            audits.record_validation_failure(llm_use_id,at)
        else:
            trusted=audit_json(output,credentials=(profile.api_key,))
            if strict_json_object(trusted) != output:raise Rejected('OUTPUT_INVALID')
            if row['validation_status'] == 'SUCCEEDED':
                if row['trusted_output_json'] != trusted:raise Rejected('OUTPUT_INVALID')
            else:
                connection.execute("UPDATE llm_uses SET validation_status='SUCCEEDED',validation_error=NULL,trusted_output_json=?,error_code=NULL,error_message=NULL WHERE id=? AND validation_status='NOT_STARTED'",(trusted,llm_use_id))
                connection.execute("UPDATE guide_runs SET updated_at=? WHERE id=? AND status='RUNNING'",(at,run['id']))
            result=_receipt(run,row,function,supplied['read_manifest'],output)
    return result
