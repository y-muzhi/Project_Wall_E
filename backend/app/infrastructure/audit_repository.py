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
from .model_profile import ModelProfile
from .requirement_repository import RequirementRepository
from backend.app.documents.snapshot import _time
from backend.app.guide.context_builder import assemble_input, restore_transport_input
from backend.app.guide.counted_context import CountedContext, verify_counting_evidence, counting_snapshot
from backend.app.guide.model_context import read_context
from backend.app.guide.initialization_protocol import NO_PROGRESS_MESSAGE
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_integer, strict_json_object


def _owned(connection, run):
    if run is None: raise Rejected('NOT_FOUND')
    if run['status'] != 'RUNNING': raise Rejected('STATE_CONFLICT')
    root = RequirementRepository(connection).get(run['requirement_id'])
    if root is None or root['document_work_state'] != 'GUIDE_ACTIVE' or root['active_operation_type'] != 'GUIDE_RUN' or root['active_operation_id'] != run['id'] or MessageRepository(connection).activities(root['id']) != {'MANUAL_DRAFT':[],'GUIDE_RUN':[run['id']],'SUGGESTION_BATCH':[]}:
        raise Rejected('WORK_STATE_INCONSISTENT')
    return root


def verify_actual_context(connection, run_id, function, supplied_input, system_text, manifest_json, catalog, *, counting=None, input_json=None, counting_summary=False, profile=None, basis=None):
    """Recheck exactly the real C03 facts and permitted whole-field trimming."""
    actual = read_context(connection,run_id,catalog)['data']
    expected = assemble_input(actual,function)
    try: supplied = restore_transport_input(supplied_input,function,basis=basis)
    except ValueError: raise Rejected('SOURCE_INVALID') from None
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
    if counting is None:
        system = function.prompt+'\n'+json.dumps(json.loads(function.output_schema_json),ensure_ascii=False,separators=(',',':'))
        if system_text != system: raise Rejected('CONFIG_INVALID')
    else:
        verify_counting_evidence(actual,function,system=system_text,input_json=input_json,manifest_json=manifest_json,evidence=counting,summary=counting_summary,profile=profile)
    return actual, supplied


class AuditRepository:
    def __init__(self, connection): self.connection = connection

    def record_content_commit(self, before, after, revision_id, source_type, source_id, source_refs, summary, key, at):
        from .idempotency import request_key
        require_write_transaction(self.connection)
        request_key(key)
        if source_type not in ('MANUAL_EDIT', 'GUIDE_RUN', 'SUGGESTION_BATCH') or before['id'] != after['id'] or after['content_version'] != before['content_version'] + 1:
            raise ValueError('Invalid formal content event')
        payload = {'source_refs': source_refs, 'change_summary': summary, 'idempotency_key': key}
        self.connection.execute("INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) VALUES (?,?,?,?,?,'CONTENT_UPDATE',?,?,?,'CONTENT_COMMITTED',?,?,?)",
            (entity_id(self.connection, EntityKind.DOCUMENT_AUDIT), after['requirement_id'], after['id'], source_type, source_id,
             before['content_version'], after['content_version'], at, revision_id, source_id if source_type == 'GUIDE_RUN' else None, canonical_input(payload)))

    def record_document_event(self, document, event_type, payload, at, *, revision_id=None, before_version=None):
        require_write_transaction(self.connection)
        fields = {
            'CONTENT_COMMITTED': {'creation_message_id', 'template_ref', 'idempotency_key'},
            'DOCUMENT_RENAMED': {'before', 'after', 'idempotency_key'},
            'DOCUMENT_ARCHIVED': {'idempotency_key'}, 'DOCUMENT_RESTORED': {'idempotency_key'},
            'DOCUMENT_CONFIRMED': {'revision_id', 'content_version', 'idempotency_key'},
            'VERSION_MARKED': {'description', 'idempotency_key'}}
        if event_type not in fields or type(payload) is not dict or set(payload) != fields[event_type]:
            raise ValueError('Document event payload differs from its registered type')
        identity = entity_id(self.connection, EntityKind.DOCUMENT_AUDIT)
        version = document['content_version']
        before = before_version if event_type == 'CONTENT_COMMITTED' else version
        self.connection.execute('INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) VALUES (?,?,?,\'USER_ACTION\',?,?,?,?,?,?,?,NULL,?)',
            (identity, document['requirement_id'], document['id'], document['id'], event_type,
             before, version, at, event_type, revision_id, canonical_input(payload)))
        return identity

    def record_requirement_update(self, before, after, changes, key, at):
        """Actual user metadata event; no body/version/occupancy side effects."""
        from .idempotency import request_key
        require_write_transaction(self.connection)
        request_key(key)
        if not changes or not set(changes) <= {'title', 'status'} or after['id'] != before['id'] or after['metadata_version'] != before['metadata_version'] + 1:
            raise ValueError('Invalid requirement metadata event')
        payload = {'changes': {field: {'before': before[field], 'after': after[field]} for field in changes},
            'metadata_version_before': before['metadata_version'], 'metadata_version_after': after['metadata_version'],
            'idempotency_key': key}
        self.connection.execute("INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) VALUES (?,?,NULL,'USER_ACTION',?,'USER_METADATA_UPDATE',NULL,NULL,?,'REQUIREMENT_UPDATED',NULL,NULL,?)",
            (entity_id(self.connection, EntityKind.DOCUMENT_AUDIT), before['id'], before['id'], at, canonical_input(payload)))

    def get(self, identity):
        return self.connection.execute('SELECT * FROM llm_uses WHERE id=?', (identity,)).fetchone()

    def prepare_collaboration(self, run_id, profile, context, at, *, catalog, admission=None):
        from backend.app.guide.collaboration_context import read_canonical
        from backend.app.guide.collaboration_counting import verify_counted
        from .audit_data import collaboration_audit_json
        require_write_transaction(self.connection);_time(at)
        run = GuideRepository(self.connection).get(run_id);root = _owned(self.connection, run)
        if run['function_type'] != 'collaboration_v1' or run['current_step'] != 'PREPARING':
            raise Rejected('STATE_CONFLICT')
        if self.connection.execute('SELECT 1 FROM llm_uses WHERE guide_run_id=?', (run_id,)).fetchone():
            raise Rejected('STATE_CONFLICT')
        if at < max(run['updated_at'], root['updated_at']):
            raise ValueError('Preparation cannot precede actual activity')
        resources = catalog.collaboration
        resources.require_live(profile.snapshot, admission=admission)
        canonical = read_canonical(self.connection, run_id, catalog)
        counting = verify_counted(context, catalog, profile, expected_canonical=canonical)
        protocol = {'function_type': 'collaboration_v1', 'input_schema': 'collaboration.wire@v1',
            'output_schema': 'collaboration.output.'+run['operation'].lower()+'@v1',
            'context_template': 'collaboration_context_v1@v1', 'prompt': resources.release['prompt']['key']+'@'+resources.release['prompt']['version'],
            'manifest_sha256': resources.manifest_sha256, 'release': resources.reference('collaboration.release')}
        snapshot = {'profile': profile.snapshot, 'request': profile.request(context), 'protocol': protocol,
            'context_basis': context.basis, 'counting': counting,
            'admission': resources.validate('Admission', resources.release['admission'] if admission is None else admission.value)}
        fields = {'id': entity_id(self.connection, EntityKind.LLM_USE), 'guide_run_id': run_id, 'call_no': 1, 'attempt_no': 1,
            'provider': 'volcengine', 'model_name': profile.model_name, 'model_version': profile.model_version,
            'function_type': 'collaboration_v1', 'prompt_config': protocol['prompt'],
            'request_snapshot_json': collaboration_audit_json(snapshot, resources, credentials=(profile.api_key,)),
            'parsed_output_json': None, 'trusted_output_json': None, 'input_summary': canonical['current_message']['content'],
            'context_manifest_json': context.manifest_json, 'raw_response_json': None, 'finish_reason': None,
            'parse_status': 'NOT_STARTED', 'parse_error': None, 'validation_status': 'NOT_STARTED', 'validation_error': None,
            'call_status': 'RUNNING', 'input_tokens': None, 'output_tokens': None, 'cache_info_json': None,
            'provider_request_id': None, 'started_at': at, 'ended_at': None, 'duration_ms': None, 'error_code': None,
            'error_message': None, 'cost': None, 'cost_currency': None}
        self.connection.execute('INSERT INTO llm_uses('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', tuple(fields.values()))
        self.connection.execute("UPDATE guide_runs SET current_step='CALLING_MODEL',started_at=coalesce(started_at,?),updated_at=? WHERE id=? AND status='RUNNING' AND current_step='PREPARING'", (at, at, run_id))
        return self.get(fields['id'])

    def record_discussion_update(self, before, after, command, message_id, closed_phase, key, at):
        require_write_transaction(self.connection)
        if before['id'] != after['id'] or after['discussion_version'] != before['discussion_version'] + 1:
            raise ValueError('Invalid discussion event versions')
        message = MessageRepository(self.connection).get(message_id)
        if message is None or message['requirement_id'] != before['id'] or message['role'] != 'USER' or message['guide_run_id'] is not None:
            raise ValueError('Discussion event requires its real user action message')
        event = 'PHASE_CHANGED' if closed_phase is not None else 'DISCUSSION_UPDATED'
        payload = {'command': command, 'message_id': message_id, 'idempotency_key': key,
            'discussion_version_before': before['discussion_version'], 'discussion_version_after': after['discussion_version'],
            'phase_before': closed_phase or before['discussion_state_json']['phase'], 'phase_after': after['discussion_state_json']['phase']}
        self.connection.execute("INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) VALUES (?,?,NULL,'USER_ACTION',?,?,NULL,NULL,?,?,NULL,NULL,?)",
            (entity_id(self.connection, EntityKind.DOCUMENT_AUDIT), before['id'], message_id, event, at, event, canonical_input(payload)))

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
        counted=context.counting_evidence if type(context) is CountedContext else None
        basis = None if context.basis_json is None else strict_json_object(context.basis_json)
        actual, supplied = verify_actual_context(self.connection,run_id,function,context.input,context.system,context.manifest_json,catalog,counting=counted,input_json=context.input_json,profile=profile,basis=basis)
        manifest = supplied['read_manifest']
        last = self.connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=? ORDER BY call_no DESC,attempt_no DESC LIMIT 1',(run_id,)).fetchone()
        if call_no is None:
            if run['current_step'] != 'PREPARING' or last is not None and last['ended_at'] is None: raise Rejected('STATE_CONFLICT')
            call_no = 1 if last is None else increment(last['call_no']);attempt_no = 1
            if last is not None:
                old = strict_json_object(last['request_snapshot_json'])
                old_input = restore_transport_input(strict_json_object(old['request']['messages'][1]['content']),function,basis=old.get('context_basis'))
                if old_input['user_input']['message_id'] == supplied['user_input']['message_id']: raise Rejected('STATE_CONFLICT')
        else:
            strict_integer(call_no,'call_no')
            if last is None or last['call_no'] != call_no or last['ended_at'] is None or last['attempt_no'] >= 3 or last['trusted_output_json'] is not None or not (last['call_status']=='FAILED' or last['parse_status']=='FAILED' or last['validation_status']=='FAILED'):
                raise Rejected('STATE_CONFLICT')
            previous_profile = ModelProfile.from_snapshot(strict_json_object(last['request_snapshot_json'])['profile'])
            if previous_profile.profile_id != profile.profile_id:
                raise Rejected('CONFIG_INVALID')
            attempt_no = last['attempt_no']+1
        snapshot = {'profile':profile.snapshot,'request':profile.request(context),
            'protocol':{'function_type':function.function_type,'input_schema':function.model_input_schema,'output_schema':function.output_schema,
                'context_template':function.context_template,'prompt':function.prompt_reference,'manifest_sha256':function.manifest_sha256}}
        if counted is not None:snapshot['counting']=counting_snapshot(counted)
        if basis is not None:
            from backend.app.guide.context_projection import projected
            if not projected(function): raise Rejected('CONFIG_INVALID')
            snapshot['context_basis'] = basis
        fields = {'id':entity_id(self.connection,EntityKind.LLM_USE),'guide_run_id':run_id,'call_no':call_no,'attempt_no':attempt_no,
            'provider':'volcengine','model_name':profile.model_name,'model_version':profile.model_version,'function_type':function.function_type,'prompt_config':function.prompt_reference,
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
        stored_profile = ModelProfile.from_snapshot(strict_json_object(row['request_snapshot_json'])['profile'])
        if type(profile) is not ModelProfile or stored_profile.profile_id != profile.profile_id or (row['provider'], row['model_name'], row['model_version']) != ('volcengine', profile.model_name, profile.model_version):
            raise Rejected('CONFIG_INVALID')
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

    def record_admission_failure(self, identity, at):
        """Transport remains an occurred success; actual budget admission failed."""
        require_write_transaction(self.connection);strict_integer(identity,'llm_use_id');_time(at)
        row=self.get(identity)
        if row is None:raise Rejected('NOT_FOUND')
        run=GuideRepository(self.connection).get(row['guide_run_id']);_owned(self.connection,run)
        if row['call_status']!='SUCCEEDED' or row['parse_status']!='NOT_STARTED' or run['current_step']!='VALIDATING':
            raise Rejected('STATE_CONFLICT')
        if at < max(row['ended_at'],run['updated_at']):raise ValueError('Admission failure cannot precede transport')
        self.connection.execute('UPDATE llm_uses SET error_code=?,error_message=? WHERE id=?',
            ('CONFIG_INVALID','模型实际用量未通过已批准预算门禁',identity))
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
            stored_profile = ModelProfile.from_snapshot(strict_json_object(row['request_snapshot_json'])['profile'])
            if (row['provider'], row['model_name'], row['model_version']) != ('volcengine', stored_profile.model_name, stored_profile.model_version):
                raise ValueError('Audit model differs from its frozen profile')
            raw = strict_json_object(row['raw_response_json'])
            if raw.get('model') != stored_profile.model_name or type(raw.get('choices')) is not list or len(raw['choices']) != 1: raise ValueError('Wrong model or response cardinality')
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

    def record_validation_failure(self, identity, at, *, reason=None):
        require_write_transaction(self.connection);strict_integer(identity,'llm_use_id');_time(at)
        row = self.get(identity)
        if row is None: raise Rejected('NOT_FOUND')
        run = GuideRepository(self.connection).get(row['guide_run_id']);_owned(self.connection,run)
        if row['call_status']!='SUCCEEDED' or row['parse_status']!='SUCCEEDED' or row['validation_status']!='NOT_STARTED' or run['current_step']!='VALIDATING': raise Rejected('STATE_CONFLICT')
        if run['updated_at'] > at: raise ValueError('Validation cannot precede prior progress')
        if reason not in (None, NO_PROGRESS_MESSAGE):
            raise ValueError('Only a fixed safe validation reason is permitted')
        self.connection.execute("UPDATE llm_uses SET validation_status='FAILED',trusted_output_json=NULL,validation_error=?,error_code='OUTPUT_INVALID',error_message=? WHERE id=?",
            (reason or '输出未通过结构或业务校验', reason or '模型输出未能通过程序校验', identity))
        self.connection.execute('UPDATE guide_runs SET updated_at=? WHERE id=? AND status=\'RUNNING\'',(at,run['id']))
        return self.get(identity)

    def prune_raw(self, at):
        require_write_transaction(self.connection);_time(at)
        cutoff = (datetime.fromisoformat(at[:-1]+'+00:00')-timedelta(days=30)).isoformat(timespec='milliseconds').replace('+00:00','Z')
        return self.connection.execute('UPDATE llm_uses SET raw_response_json=NULL,parsed_output_json=NULL WHERE ended_at IS NOT NULL AND ended_at<? AND (raw_response_json IS NOT NULL OR parsed_output_json IS NOT NULL)',(cutoff,)).rowcount
