"""Actual short-transaction LLM attempt preparation/transport/parse facts.

No Provider I/O, business adoption or manufactured trusted-output success.
The caller owns the process lock and the shared write transaction.
"""
from datetime import datetime, timedelta
import json

from .audit_data import audit_json
from .guide_repository import GuideRepository
from .identifiers import EntityKind, entity_id, increment, require_write_transaction
from .idempotency import canonical_input
from .message_repository import MessageRepository
from .model_profile import ModelProfile, MODEL_ID, MODEL_VERSION
from .requirement_repository import RequirementRepository
from backend.app.documents.snapshot import _time
from backend.app.guide.context_builder import assemble_input
from backend.app.guide.model_context import read_context
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_integer, strict_json_object


def _owned(connection, run):
    if run is None: raise Rejected('NOT_FOUND')
    if run['status'] != 'RUNNING': raise Rejected('STATE_CONFLICT')
    root = RequirementRepository(connection).get(run['requirement_id'])
    if root is None or root['document_work_state'] != 'GUIDE_ACTIVE' or root['active_operation_type'] != 'GUIDE_RUN' or root['active_operation_id'] != run['id'] or MessageRepository(connection).activities(root['id']) != {'MANUAL_DRAFT':[],'GUIDE_RUN':[run['id']],'SUGGESTION_BATCH':[]}:
        raise Rejected('WORK_STATE_INCONSISTENT')
    return root


def verify_actual_context(connection, run_id, function, supplied_input, system_text, manifest_json, catalog):
    """Recheck exactly the real C03 facts and permitted whole-field trimming."""
    actual = read_context(connection,run_id,catalog)['data']
    expected = assemble_input(actual,function);supplied = function.validate_input(supplied_input)
    if any(supplied[key] != expected[key] for key in expected if key not in ('current_document','history','read_manifest')):
        raise Rejected('SOURCE_INVALID')
    expected_blocks = {item['metadata']['block_id']:item for item in expected['current_document']['read_blocks']}
    blocks = supplied['current_document']['read_blocks'];block_ids = [item['metadata']['block_id'] for item in blocks]
    if len(set(block_ids)) != len(block_ids) or block_ids != [identity for identity in expected_blocks if identity in block_ids] or any(expected_blocks.get(item['metadata']['block_id']) != item for item in blocks):
        raise Rejected('SOURCE_INVALID')
    required = set(actual['scope']['required_read_block_ids']) | {item['block_id'] for item in supplied['allowed_targets']}
    if not required.issubset(block_ids) or supplied['current_document']['id'] != expected['current_document']['id'] or supplied['current_document']['content_version'] != expected['current_document']['content_version']:
        raise Rejected('SOURCE_INVALID')
    history = supplied['history'];suffix = expected['history'][-len(history):] if history else []
    if history != suffix: raise Rejected('SOURCE_INVALID')
    selected = [actual['user_input'],*(item for item in actual['history'] if item['id'] in {entry['id'] for entry in history})]
    message_ids = {item['id'] for item in selected}
    message_ids.update(item['reply_to_message_id'] for item in selected if item['message_type']=='CARD_RESPONSE')
    manifest = {**expected['read_manifest'],'block_ids':block_ids,'message_ids':[identity for identity in expected['read_manifest']['message_ids'] if identity in message_ids]}
    if supplied['read_manifest'] != manifest or strict_json_object(manifest_json) != manifest:
        raise Rejected('SOURCE_INVALID')
    system = function.prompt+'\n'+json.dumps(json.loads(function.output_schema_json),ensure_ascii=False,separators=(',',':'))
    if system_text != system: raise Rejected('CONFIG_INVALID')
    return actual, supplied


class AuditRepository:
    def __init__(self, connection): self.connection = connection

    def get(self, identity):
        return self.connection.execute('SELECT * FROM llm_uses WHERE id=?', (identity,)).fetchone()

    def prepare(self, run_id, function, profile, context, at, *, catalog, call_no=None):
        """Record the exact prepared request before the caller sends it once.

        Budget/compatibility is an upstream Builder gate. This repository
        separately rechecks actual facts; passing it alone cannot send a call.
        """
        require_write_transaction(self.connection);strict_integer(run_id,'guide_run_id');_time(at)
        guides = GuideRepository(self.connection);run = guides.get(run_id);root = _owned(self.connection,run)
        frozen = catalog.restore(run['function_type'],run['prompt_version'],prompt_version=run['prompt_version'],context_template=run['context_template_key']+'@'+run['context_template_version'])
        if function != frozen or type(profile) is not ModelProfile: raise Rejected('CONFIG_INVALID')
        if run['updated_at'] > at or root['updated_at'] > at: raise ValueError('Attempt cannot precede persisted activity')
        actual, supplied = verify_actual_context(self.connection,run_id,function,context.input,context.system,context.manifest_json,catalog)
        manifest = supplied['read_manifest']
        last = self.connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=? ORDER BY call_no DESC,attempt_no DESC LIMIT 1',(run_id,)).fetchone()
        if call_no is None:
            if run['current_step'] != 'PREPARING' or last is not None and last['ended_at'] is None: raise Rejected('STATE_CONFLICT')
            call_no = 1 if last is None else increment(last['call_no']);attempt_no = 1
            if last is not None:
                old = strict_json_object(last['request_snapshot_json'])
                old_input = strict_json_object(old['request']['messages'][1]['content'])
                if old_input['user_input']['message_id'] == supplied['user_input']['message_id']: raise Rejected('STATE_CONFLICT')
        else:
            strict_integer(call_no,'call_no')
            if last is None or last['call_no'] != call_no or last['ended_at'] is None or last['attempt_no'] >= 3 or last['trusted_output_json'] is not None or not (last['call_status']=='FAILED' or last['parse_status']=='FAILED' or last['validation_status']=='FAILED'):
                raise Rejected('STATE_CONFLICT')
            attempt_no = last['attempt_no']+1
        snapshot = {'profile':profile.snapshot,'request':profile.request(context),
            'protocol':{'function_type':function.function_type,'input_schema':function.input_schema,'output_schema':function.output_schema,
                'context_template':function.context_template,'prompt':function.prompt_reference,'manifest_sha256':function.manifest_sha256}}
        fields = {'id':entity_id(self.connection,EntityKind.LLM_USE),'guide_run_id':run_id,'call_no':call_no,'attempt_no':attempt_no,
            'provider':'volcengine','model_name':MODEL_ID,'model_version':MODEL_VERSION,'function_type':function.function_type,'prompt_config':function.prompt_reference,
            'request_snapshot_json':audit_json(snapshot,credentials=(profile.api_key,)),'parsed_output_json':None,'trusted_output_json':None,
            'input_summary':supplied['user_input']['content'],'context_manifest_json':canonical_input(manifest),'raw_response_json':None,'finish_reason':None,
            'parse_status':'NOT_STARTED','parse_error':None,'validation_status':'NOT_STARTED','validation_error':None,'call_status':'RUNNING',
            'input_tokens':None,'output_tokens':None,'cache_info_json':None,'provider_request_id':None,'started_at':at,'ended_at':None,'duration_ms':None,
            'error_code':None,'error_message':None,'cost':None,'cost_currency':None}
        # Summary is sensitive too: scrub credential occurrences, while the
        # request remains the complete authorized audit representation.
        fields['input_summary'] = json.loads(audit_json({'content':fields['input_summary']},credentials=(profile.api_key,)))['content']
        self.connection.execute('INSERT INTO llm_uses('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',tuple(fields.values()))
        self.connection.execute("UPDATE guide_runs SET current_step='CALLING_MODEL',started_at=coalesce(started_at,?),updated_at=? WHERE id=? AND status='RUNNING'",(at,at,run_id))
        return self.get(fields['id'])

    def record_transport(self, identity, raw_response, at, *, profile, succeeded, duration_ms=None, input_tokens=None, output_tokens=None, provider_request_id=None, finish_reason=None, cache_info=None):
        require_write_transaction(self.connection);strict_integer(identity,'llm_use_id');_time(at)
        row = self.get(identity)
        if row is None: raise Rejected('NOT_FOUND')
        if row['raw_response_json'] is not None: raise Rejected('STATE_CONFLICT')
        if type(succeeded) is not bool: raise ValueError('Transport result must be explicit')
        if row['started_at'] > at: raise ValueError('Transport finish cannot precede attempt')
        for value in (duration_ms,input_tokens,output_tokens):
            if value is not None: strict_integer(value,'provider_measurement',0,MAX_SAFE_INTEGER)
        if provider_request_id is not None and (type(provider_request_id) is not str or len(provider_request_id)>1024): raise ValueError('Provider trace ID exceeds its approved capacity')
        if provider_request_id is not None and profile.api_key in provider_request_id: raise ValueError('Provider trace ID cannot contain credentials')
        if finish_reason is not None and type(finish_reason) is not str: raise ValueError('Finish reason must be text or unknown')
        if finish_reason is not None:
            finish_reason = json.loads(audit_json({'value':finish_reason},credentials=(profile.api_key,)))['value']
        if row['call_status'] not in ('RUNNING','CANCELLED','FAILED'): raise Rejected('STATE_CONFLICT')
        response = None if raw_response is None else audit_json(raw_response,credentials=(profile.api_key,))
        cache = None if cache_info is None else audit_json(cache_info,credentials=(profile.api_key,))
        # A late response can add actual usage to its own interrupted attempt;
        # it cannot replace logical cancellation/failure or mutate the Run.
        status = ('SUCCEEDED' if succeeded else 'FAILED') if row['call_status']=='RUNNING' else row['call_status']
        ended = at if row['ended_at'] is None else row['ended_at']
        code = row['error_code'] if row['call_status']!='RUNNING' else None if succeeded else 'MODEL_ERROR'
        message = row['error_message'] if row['call_status']!='RUNNING' else None if succeeded else '模型请求未能完成'
        self.connection.execute('UPDATE llm_uses SET raw_response_json=?,finish_reason=?,call_status=?,input_tokens=?,output_tokens=?,cache_info_json=?,provider_request_id=?,ended_at=?,duration_ms=?,error_code=?,error_message=? WHERE id=?',
            (response,finish_reason,status,input_tokens,output_tokens,cache,provider_request_id,ended,duration_ms,code,message,identity))
        run = GuideRepository(self.connection).get(row['guide_run_id'])
        if run is not None and run['status']=='RUNNING' and row['call_status']=='RUNNING':
            _owned(self.connection,run)
            if run['updated_at'] > at: raise ValueError('Progress cannot precede the Run')
            self.connection.execute("UPDATE guide_runs SET current_step=?,updated_at=? WHERE id=? AND status='RUNNING'",('VALIDATING' if succeeded else 'CALLING_MODEL',at,run['id']))
        return self.get(identity)

    def parse_response(self, identity, at):
        """Single-object parse only; never repair unknown fields or run Schema."""
        require_write_transaction(self.connection);strict_integer(identity,'llm_use_id');_time(at)
        row = self.get(identity)
        if row is None: raise Rejected('NOT_FOUND')
        run = GuideRepository(self.connection).get(row['guide_run_id']);_owned(self.connection,run)
        if row['call_status']!='SUCCEEDED' or row['parse_status']!='NOT_STARTED' or run['current_step']!='VALIDATING': raise Rejected('STATE_CONFLICT')
        if run['updated_at'] > at or row['ended_at'] > at: raise ValueError('Parse cannot precede transport')
        parsed = None
        try:
            raw = strict_json_object(row['raw_response_json'])
            if raw.get('model') != MODEL_ID or type(raw.get('choices')) is not list or len(raw['choices']) != 1: raise ValueError('Wrong model or response cardinality')
            choice = raw['choices'][0];message = choice['message']
            if type(choice) is not dict or type(message) is not dict: raise ValueError('Malformed assistant envelope')
            if row['finish_reason'] != 'stop' or choice.get('finish_reason') != 'stop' or message.get('role')!='assistant' or message.get('refusal') or message.get('tool_calls') or message.get('function_call'):
                raise ValueError('Response is not usable non-tool assistant output')
            content = message.get('content')
            if type(content) is not str or not content or len(content.encode('utf-8')) > 1024*1024: raise ValueError('Content missing or exceeds capacity')
            parsed = strict_json_object(content)
        except (ValueError,KeyError,TypeError,UnicodeError): pass
        self.connection.execute('UPDATE llm_uses SET parsed_output_json=?,parse_status=?,parse_error=?,error_code=?,error_message=? WHERE id=?',
            (None if parsed is None else audit_json(parsed),'FAILED' if parsed is None else 'SUCCEEDED',
                '响应未通过单一JSON对象解析门禁' if parsed is None else None,'OUTPUT_INVALID' if parsed is None else None,
                '模型输出未能通过程序校验' if parsed is None else None,identity))
        self.connection.execute('UPDATE guide_runs SET updated_at=? WHERE id=? AND status=\'RUNNING\'',(at,run['id']))
        return parsed

    def record_validation_failure(self, identity, at):
        require_write_transaction(self.connection);strict_integer(identity,'llm_use_id');_time(at)
        row = self.get(identity)
        if row is None: raise Rejected('NOT_FOUND')
        run = GuideRepository(self.connection).get(row['guide_run_id']);_owned(self.connection,run)
        if row['call_status']!='SUCCEEDED' or row['parse_status']!='SUCCEEDED' or row['validation_status']!='NOT_STARTED' or run['current_step']!='VALIDATING': raise Rejected('STATE_CONFLICT')
        if run['updated_at'] > at: raise ValueError('Validation cannot precede prior progress')
        self.connection.execute("UPDATE llm_uses SET validation_status='FAILED',trusted_output_json=NULL,validation_error='输出未通过结构或业务校验',error_code='OUTPUT_INVALID',error_message='模型输出未能通过程序校验' WHERE id=?",(identity,))
        self.connection.execute('UPDATE guide_runs SET updated_at=? WHERE id=? AND status=\'RUNNING\'',(at,run['id']))
        return self.get(identity)

    def prune_raw(self, at):
        require_write_transaction(self.connection);_time(at)
        cutoff = (datetime.fromisoformat(at[:-1]+'+00:00')-timedelta(days=30)).isoformat(timespec='milliseconds').replace('+00:00','Z')
        return self.connection.execute('UPDATE llm_uses SET raw_response_json=NULL,parsed_output_json=NULL WHERE ended_at IS NOT NULL AND ended_at<? AND (raw_response_json IS NOT NULL OR parsed_output_json IS NOT NULL)',(cutoff,)).rowcount
