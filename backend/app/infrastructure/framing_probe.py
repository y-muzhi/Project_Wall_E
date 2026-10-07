"""Private, bounded Provider observations; never a production proof loader.

Plans are offline. Executing requires explicit authorization of their exact
canonical hash. Six finite observations cannot prove a bound for all inputs.
No business database, C07, environment activation, retry or recovery replay.
"""
import asyncio
import hashlib
import os
from pathlib import Path

from .audit_data import audit_json, MAX_AUDIT_BYTES
from .database import StorageUnavailable
from .idempotency import canonical_input
from .model_gateway import ModelGateway, TransportResult
from .model_profile import ModelProfile, MODEL_ID
from .resources import ResourceCatalog, ConfigInvalid, FUNCTIONS
from .schema_transport import compact, function_schema
from .tokenization import TokenizationGateway, TokenCounts, restore_measurement, integer, measurement_summary
from backend.app.documents.snapshot import _time
from backend.app.guide.context_builder import BuiltContext
from backend.app.guide.counted_context import counting_release, RELEASE_SHA256
from backend.app.shared.validation import strict_json_object
from backend.app.shared.time import utc_milliseconds
from datetime import datetime, timezone, timedelta
from uuid import uuid4


def digest(value):
    return hashlib.sha256(canonical_input(value).encode('utf-8')).hexdigest()


def build_plan(inputs, *, catalog=None):
    """Six validated model-input fixtures, with no claim of storage ownership."""
    resources = ResourceCatalog() if catalog is None else catalog
    try:
        if type(inputs) is not list or len(inputs) != 6: raise ValueError('Six cases required')
        cases, seen, versions = [], set(), set()
        for item in inputs:
            if type(item) is not dict or set(item) != {'function_type','version','input'}: raise ValueError('Case fields')
            function = resources.restore(item['function_type'], item['version'])
            if function.function_type in seen: raise ValueError('Duplicate Function')
            seen.add(function.function_type); versions.add(function.version)
            value = function.validate_input(item['input']); manifest = value['read_manifest']
            if value['function_type'] != function.function_type or value['action_type'] != function.action_type or value['source_type'] != function.source_type or manifest['function_type'] != function.function_type:
                raise ValueError('Case Function binding')
            for field, reference in (('prompt',function.prompt_reference),('context_template',function.context_template)):
                key, version = reference.split('@')
                if manifest[field] != {'key':key,'version':version}: raise ValueError('Case frozen protocol')
            transport = function_schema(function)
            system = function.prompt+'\n'+transport.schema_json
            encoded = compact({key:value[key] for key in function.context_policy['field_order']})
            texts = (system, encoded, *(compact(value[key]) for key in ('user_input','source','template','history')))
            cases.append({'function_type':function.function_type,'version':function.version,'input_json':encoded,
                'system':system,'schema':transport.evidence,'manifest_sha256':function.manifest_sha256,
                'text_sha256':[hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts],
                'text_bytes':[len(text.encode('utf-8')) for text in texts]})
        if seen != {entry[0] for entry in FUNCTIONS.values()} or len(versions) != 1: raise ValueError('Whole single-version protocol required')
        release = counting_release()
        plan = {'schema_version':1,'kind':'six_function_framing_observations_v1',
            'provenance':'Explicit diagnostic model-input fixtures; no business-storage or model-effect claim',
            'release_sha256':RELEASE_SHA256,'profile':ModelProfile('offline-plan-no-credential').snapshot,
            'budget':release['budget'],'framing_reserve_candidate':release['framing_reserve_candidate'],
            'limits':{'count_adapter_invocations':6,'chat_adapter_invocations':6,'retries':0,
                'maximum_requested_completion_tokens':6*release['budget']['output_tokens']},
            'production_compatibility_proved':False,'cases':sorted(cases,key=lambda case:case['function_type'])}
        # Same bounded private audit capacity; no key or live configuration read.
        audit_json(plan)
        return plan
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        raise ConfigInvalid('Framing observation plan is invalid') from error


def validate_plan(plan, *, catalog=None):
    try:
        inputs = [{'function_type':case['function_type'],'version':case['version'],
                   'input':strict_json_object(case['input_json'])} for case in plan['cases']]
        rebuilt = build_plan(inputs,catalog=catalog)
        if canonical_input(plan) != canonical_input(rebuilt): raise ValueError('Plan changed')
        return rebuilt
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        raise ConfigInvalid('Framing observation plan does not reproduce frozen inputs') from error


class ProbeJournal:
    """New exclusive directory per run; partial/unknown runs never resume."""
    def __init__(self, path):
        candidate = Path(path).absolute()
        if candidate.is_symlink() or candidate.resolve() != candidate: raise StorageUnavailable('Probe audit path redirected')
        try: candidate.mkdir(parents=True,exist_ok=False)
        except OSError as error: raise StorageUnavailable('Probe audit needs a new directory') from error
        self.path = candidate

    def write(self, name, value, profile):
        if name not in {'plan','report'} and name not in {f'{index:02d}-{kind}-{phase}' for index in range(1,7) for kind in ('count','chat') for phase in ('prepared','finished')}:
            raise ValueError('Probe record name')
        encoded = audit_json(value,credentials=(profile.api_key,)).encode('utf-8')
        try:
            path = self.path/(name+'.json')
            if self.path.is_symlink() or self.path.resolve()!=self.path or path.is_symlink() or path.resolve().parent!=self.path:
                raise StorageUnavailable('Probe audit path redirected')
            with path.open('xb') as handle:
                handle.write(encoded);handle.flush();os.fsync(handle.fileno())
        except OSError as error: raise StorageUnavailable('Probe audit could not be saved') from error


def _texts(case):
    value = strict_json_object(case['input_json'])
    return (case['system'],case['input_json'],*(compact(value[key]) for key in ('user_input','source','template','history')))


def _observe(wire, receipt, case):
    """Actual usage/version only. Output business validation is a separate task."""
    if type(wire) is not TransportResult or not wire.succeeded or wire.category is not None: raise ConfigInvalid('Chat transport did not succeed')
    raw = wire.raw_response
    if type(raw) is not dict or raw.get('model') != MODEL_ID or raw.get('object') != 'chat.completion': raise ConfigInvalid('Chat model/envelope differs')
    created = integer(raw.get('created'))
    identity = raw.get('id')
    if type(identity) is not str or not identity or identity != wire.provider_request_id or len(identity)>1024 or any(ord(char)<32 or ord(char)==127 for char in identity): raise ConfigInvalid('Chat identity unavailable')
    usage = raw.get('usage')
    if type(usage) is not dict: raise ConfigInvalid('Chat actual usage unavailable')
    prompt = integer(usage.get('prompt_tokens')); completion = integer(usage.get('completion_tokens'))
    if prompt != wire.input_tokens or completion != wire.output_tokens or completion > 8192: raise ConfigInvalid('Chat usage differs')
    if 'total_tokens' in usage and integer(usage['total_tokens']) != prompt+completion: raise ConfigInvalid('Chat total usage differs')
    choices = raw.get('choices')
    if type(choices) is not list or len(choices)!=1 or type(choices[0]) is not dict or choices[0].get('finish_reason')!='stop' or wire.finish_reason!='stop': raise ConfigInvalid('Chat completion unavailable')
    message = choices[0].get('message')
    if type(message) is not dict or message.get('role')!='assistant' or type(message.get('content')) is not str or not message['content'] or message.get('tool_calls') or message.get('function_call') or message.get('refusal'):
        raise ConfigInvalid('Chat two-role response unavailable')
    delta = prompt-receipt.counts[0]-receipt.counts[1]
    return {'function_type':case['function_type'],'version':case['version'],'model':MODEL_ID,
            'count_request_id':receipt.request_id,'chat_request_id':identity,'chat_created':created,
            'counted_system_tokens':receipt.counts[0],'counted_user_tokens':receipt.counts[1],
            'actual_prompt_tokens':prompt,'actual_completion_tokens':completion,
            'observed_framing_delta':delta,'candidate_reserve_exceeded':delta>256,
            'actual_input_budget_exceeded':prompt>24576,'production_compatibility_proved':False}


async def collect_observations(plan, profile, path, *, authorized_plan_sha256=None,
                               counter=None, gateway=None, catalog=None, clock=None):
    """No retry; stop first failure. Calling this with real adapters is paid I/O.

    Authorization is the human's exact-plan execution confirmation, supplied
    explicitly by the standalone CLI, not read from HTTP/environment settings.
    The assistant must obtain that confirmation before using real adapters.
    """
    plan = validate_plan(plan,catalog=catalog)
    if type(profile) is not ModelProfile or type(authorized_plan_sha256) is not str or authorized_plan_sha256 != digest(plan):
        raise ConfigInvalid('Explicit paid authorization for this exact plan is required')
    if canonical_input(profile.snapshot) != canonical_input(plan['profile']):
        raise ConfigInvalid('Observation authorization cannot transfer to another model profile')
    counter = TokenizationGateway() if counter is None else counter
    gateway = ModelGateway() if gateway is None else gateway
    journal = ProbeJournal(path)
    now = lambda: utc_milliseconds(datetime.now(timezone.utc) if clock is None else clock())
    journal.write('plan',{'at':now(),'plan_sha256':digest(plan),'plan':plan},profile)
    report = {'plan_sha256':digest(plan),'observations':[],'count_adapter_invocations':0,'chat_adapter_invocations':0,
              'stopped_reason':None,'complete_observations':False,'production_compatibility_proved':False,
              'model_effects_proved':False,'physical_requests_or_charges_are_not_inferred_from_prepared_records':True}
    for index,case in enumerate(plan['cases'],1):
        active = None
        try:
            texts = _texts(case)
            journal.write(f'{index:02d}-count-prepared',{'at':now(),'phase':'PREPARED','plan_sha256':digest(plan),
                'request':{'model':MODEL_ID,'text':list(texts)}},profile)
            active = f'{index:02d}-count-finished';report['count_adapter_invocations'] += 1
            receipt = await counter.count(profile,texts)
            if type(receipt) is not TokenCounts: raise ConfigInvalid('Exact count receipt required')
            receipt = restore_measurement(receipt.evidence,texts)
            journal.write(active,{'at':now(),'phase':'SUCCEEDED','measurement':receipt.evidence},profile);active=None
            budget = plan['budget'];counts=receipt.counts
            if any(value>budget[limit] for value,limit in zip((counts[0],counts[2],counts[3],counts[4],counts[5]),
                    ('prompt_tokens','current_user_tokens','source_tokens','template_tokens','history_tokens'))) or counts[0]+counts[1]+256>budget['input_tokens']:
                raise ConfigInvalid('Exact fixture exceeds unchanged candidate budgets')
            value = strict_json_object(case['input_json'])
            context = BuiltContext(case['system'],case['input_json'],compact(value['read_manifest']),
                sum(case['text_bytes'][:2]),(),())
            request = profile.request(context)
            journal.write(f'{index:02d}-chat-prepared',{'at':now(),'phase':'PREPARED','plan_sha256':digest(plan),
                'count_request_id':receipt.request_id,'request':request,'request_sha256':hashlib.sha256(compact(request).encode('utf-8')).hexdigest()},profile)
            active = f'{index:02d}-chat-finished';report['chat_adapter_invocations'] += 1
            wire = await gateway.send(profile,context)
            if type(wire) is not TransportResult: raise ConfigInvalid('Actual Chat transport result required')
            journal.write(active,{'at':now(),'phase':'OBSERVED','succeeded':wire.succeeded,
                'category':wire.category,'http_status':wire.http_status,'raw_response':wire.raw_response,
                'input_tokens':wire.input_tokens,'output_tokens':wire.output_tokens},profile);active=None
            observation = _observe(wire,receipt,case);report['observations'].append(observation)
            if observation['candidate_reserve_exceeded'] or observation['actual_input_budget_exceeded']:
                raise ConfigInvalid('Observed Chat framing exceeds the candidate bound')
        except asyncio.CancelledError:
            if active is not None:
                try: journal.write(active,{'at':now(),'phase':'INTERRUPTED','physical_outcome':'UNKNOWN'},profile)
                except StorageUnavailable: pass
            raise
        except (ConfigInvalid,ValueError,TypeError,KeyError,UnicodeError):
            if active is not None: journal.write(active,{'at':now(),'phase':'FAILED','physical_outcome':'UNKNOWN'},profile)
            report['stopped_reason']='CONFIG_INVALID';break
    report['complete_observations'] = len(report['observations'])==6 and report['stopped_reason'] is None
    report['within_candidate_reserve_on_observed_cases'] = bool(report['observations']) and all(not item['candidate_reserve_exceeded'] for item in report['observations'])
    journal.write('report',{'at':now(),**report},profile)
    return report


def prune_raw(path, at):
    """Standalone evidence maintenance; no replay, business writes or deletion.

    Unknown preparations and all request/usage summaries remain. No periodic
    scheduler is installed by this standalone collector.
    """
    _time(at)
    root=Path(path).absolute()
    if root.is_symlink() or root.resolve()!=root:raise StorageUnavailable('Probe audit path redirected')
    cutoff=(datetime.fromisoformat(at[:-1]+'+00:00')-timedelta(days=30)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    def read(file):
        if file.is_symlink() or file.resolve().parent!=root:raise StorageUnavailable('Probe record redirected')
        with file.open('rb') as handle:encoded=handle.read(MAX_AUDIT_BYTES+1)
        if len(encoded)>MAX_AUDIT_BYTES:raise StorageUnavailable('Probe record exceeds capacity')
        return strict_json_object(encoded)
    changed=0
    try:
        validate_plan(read(root/'plan.json')['plan'])
        for index in range(1,7):
            for kind in ('count','chat'):
                file=root/f'{index:02d}-{kind}-finished.json'
                if not file.exists():continue
                value=read(file);_time(value['at'])
                if value['at']>=cutoff:continue
                if kind=='count' and value.get('phase')=='SUCCEEDED' and type(value.get('measurement')) is dict and 'response' in value['measurement']:
                    value['measurement']=measurement_summary(value['measurement'])
                elif kind=='chat' and value.get('phase')=='OBSERVED' and value.get('raw_response') is not None:
                    value['raw_response_sha256']=digest(value.pop('raw_response'))
                else:continue
                value['raw_pruned_at']=at
                temporary=root/(uuid4().hex+'.tmp')
                if temporary.resolve().parent!=root or file.resolve().parent!=root:raise StorageUnavailable('Probe prune path escaped')
                with temporary.open('xb') as handle:
                    handle.write(audit_json(value).encode('utf-8'));handle.flush();os.fsync(handle.fileno())
                os.replace(temporary,file);changed+=1
    except (OSError,ValueError,TypeError,KeyError) as error:raise StorageUnavailable('Probe raw maintenance failed') from error
    return changed
