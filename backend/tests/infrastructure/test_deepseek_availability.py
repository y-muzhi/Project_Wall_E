"""D-015 local TCP/SQLite/CLI safety checks; no real Provider credentials/I/O."""
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from time import monotonic
from unittest.mock import patch

from backend.app.guide.context_builder import build_context
from backend.app.guide.counted_context import (
    counting_release, PRACTICAL_MODE,
    PRACTICAL_RELEASE_SHA256, DEEPSEEK_RELEASE_SHA256)
from backend.app.infrastructure import production_ai as admission
from backend.app.infrastructure.framing_probe import (
    build_plan, validate_plan, digest, MemoryProbeJournal, collect_observations)
from backend.app.infrastructure.model_profile import ModelProfile, DEFAULT_PROFILE, DEEPSEEK_MODEL_ID
from backend.app.infrastructure.practical_usage import validate_practical_usage
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.infrastructure.local_credentials import read_local_credential
from backend.tests.infrastructure import test_framing_probe as old_probe
from backend.tests.infrastructure import test_tokenization as count_tcp
from backend.tests.guide import test_counted_orchestrator as counted

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ModelProfile('offline-deepseek-test-key', DEFAULT_PROFILE)


def plan():
    source = old_probe.prepared()
    inputs = [{'function_type':case['function_type'],'version':case['version'],
               'input':json.loads(case['input_json'])} for case in source['cases']]
    return build_plan(inputs, profile=PROFILE)


class AvailabilityPolicyTests(unittest.TestCase):
    def test_exact_old_and_new_plan_identities_do_not_transfer_authorization(self):
        self.assertEqual(digest(old_probe.prepared()), '01be318a5a3197c009b924588e6aada8064d7d7a45185afb1d3daf81999b3d41')
        candidate = plan()
        self.assertEqual(digest(candidate), admission.OBSERVATION_PLAN_SHA256)
        self.assertEqual(validate_plan(candidate), candidate)
        self.assertEqual(candidate['release_sha256'], DEEPSEEK_RELEASE_SHA256)
        self.assertEqual(candidate['framing_reserve_candidate'], 1024)
        for mutate in (lambda p:p.update(framing_reserve_candidate=256),
                       lambda p:p['profile'].update(model_name='another-model'),
                       lambda p:p.update(release_sha256=PRACTICAL_RELEASE_SHA256)):
            value = deepcopy(candidate);mutate(value)
            with self.assertRaises(ConfigInvalid):validate_plan(value)

    def test_new_default_does_not_replace_historical_pending_v2_or_legacy(self):
        current = counting_release(PROFILE)
        historic = counting_release(PROFILE,release_sha256=DEEPSEEK_RELEASE_SHA256)
        self.assertEqual(current['framing_reserve_candidate'],1024)
        self.assertIsNone(historic['framing_reserve_candidate'])
        self.assertFalse(current['provider_compatibility_proved'])
        with self.assertRaises(ConfigInvalid):counting_release(ModelProfile('offline-key'),release_sha256=PRACTICAL_RELEASE_SHA256)

    def test_admission_requires_exact_resource_hash_and_approved_identity(self):
        value = {'decision':'D-015','status':'ENABLED_AFTER_APPROVED_CHECKS',
                 'adoption_sha256':admission.ADOPTION_SHA256,'plan_sha256':admission.OBSERVATION_PLAN_SHA256,
                 'release_sha256':PRACTICAL_RELEASE_SHA256,'admission_mode':PRACTICAL_MODE,
                 'model':DEEPSEEK_MODEL_ID,'provider_compatibility_proved':False}
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'admission.json';raw=json.dumps(value).encode();target.write_bytes(raw)
            with patch.object(admission,'ADMISSION_PATH',target),patch.object(admission,'ADMISSION_SHA256',hashlib.sha256(raw).hexdigest()):
                self.assertTrue(admission.admitted())
                function=ResourceCatalog().freeze('INITIALIZE','USER_INSTRUCTION')
                self.assertTrue(admission.before_count(PROFILE,function,counting_release(PROFILE)))
                target.write_bytes(raw+b' ')
                self.assertFalse(admission.admitted())
            with patch.object(admission,'ADMISSION_SHA256',None):
                self.assertFalse(admission.admitted())

    def test_local_key_is_data_and_duplicate_or_invalid_assignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'.env.local'
            target.write_text('IGNORED=$(no-execution)\nWALLE_MODEL_API_KEY="offline-key"\n',encoding='utf-8')
            self.assertEqual(read_local_credential(target),'offline-key')
            for text in ('WALLE_MODEL_API_KEY=x\nWALLE_MODEL_API_KEY=y','WALLE_MODEL_API_KEY="bad key"','OTHER=x'):
                target.write_text(text,encoding='utf-8')
                with self.assertRaises(ValueError):read_local_credential(target)

    def test_interrupted_cli_claim_is_markdown_only_and_cannot_repeat(self):
        spec=importlib.util.spec_from_file_location('deepseek_observation_cli',ROOT/'tools/deepseek-observation.py')
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        entered=[]
        async def interrupted(*args,**kwargs):
            entered.append(True)
            journal=kwargs['journal_factory'](None)
            journal.write('01-count-prepared',{'phase':'PREPARED'},PROFILE)
            raise asyncio.CancelledError()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'docs/verification').mkdir(parents=True)
            key=root/'.env.local';key.write_text('WALLE_MODEL_API_KEY=offline-key',encoding='utf-8')
            argv=['probe','--execute','--authorized-plan-sha256',admission.OBSERVATION_PLAN_SHA256,'--credential-file',str(key)]
            with patch.object(cli,'ROOT',root),patch.object(cli,'collect_observations',interrupted),patch('sys.argv',argv):
                with self.assertRaises(asyncio.CancelledError):cli.main()
                with self.assertRaises(FileExistsError):cli.main()
            self.assertEqual(len(entered),1)
            notes=list((root/'docs/verification').iterdir())
            self.assertEqual([p.suffix for p in notes],['.md'])
            text=notes[0].read_text(encoding='utf-8')
            self.assertIn('中断或异常',text);self.assertIn('1/6',text);self.assertNotIn('offline-key',text)


class PracticalUsageTests(unittest.TestCase):
    def fixture(self):
        counting={'release_sha256':PRACTICAL_RELEASE_SHA256,'admission_mode':PRACTICAL_MODE,
                  'compatibility_proved':False,'input_tokens_candidate':1324,
                  'count_attempts':[{'measurement':{'counts':[100,200,1,1,1,1]}}]}
        raw={'model':DEEPSEEK_MODEL_ID,'object':'chat.completion',
             'usage':{'prompt_tokens':1324,'completion_tokens':8192,'total_tokens':9516}}
        return counting,raw

    def check(self,counting,raw):
        validate_practical_usage(raw,profile=PROFILE,counting=counting,
            input_tokens=raw.get('usage',{}).get('prompt_tokens'),
            output_tokens=raw.get('usage',{}).get('completion_tokens'))

    def test_inclusive_reserve_and_output_limits_do_not_claim_universal_proof(self):
        counting,raw=self.fixture();self.check(counting,raw)
        raw['usage'].update(prompt_tokens=300,total_tokens=8492);self.check(counting,raw)
        self.assertFalse(counting['compatibility_proved'])

    def test_unknown_inconsistent_over_budget_or_cross_model_usage_fails(self):
        mutations=[lambda r:r.pop('usage'),lambda r:r['usage'].pop('total_tokens'),
                   lambda r:r['usage'].update(prompt_tokens=True),lambda r:r['usage'].update(total_tokens=1),
                   lambda r:r['usage'].update(prompt_tokens=299,total_tokens=8491),
                   lambda r:r['usage'].update(prompt_tokens=1325,total_tokens=9517),
                   lambda r:r['usage'].update(completion_tokens=8193,total_tokens=9517),
                   lambda r:r.update(model='wrong-model')]
        for mutate in mutations:
            counting,raw=self.fixture();mutate(raw)
            with self.subTest(raw=raw),self.assertRaises(ConfigInvalid):self.check(counting,raw)

    def test_old_audit_without_usage_retains_its_frozen_contract(self):
        validate_practical_usage({},profile=PROFILE,counting={'release_sha256':DEEPSEEK_RELEASE_SHA256},input_tokens=None,output_tokens=None)


class PracticalOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=counted.CountedOrchestratorTests();await self.fixture.asyncSetUp()
        self.h=self.fixture.h;self.f=self.fixture.f
        self.addCleanup(lambda:self.assertTrue(self.h.helper.doCleanups()))
        self.addCleanup(self.fixture.w.tearDown)
        self.addAsyncCleanup(self.h.asyncTearDown)
        self.h.helper.helper.v2();self.f.profile=PROFILE
        envelope=count_tcp.envelope();envelope['model']=DEEPSEEK_MODEL_ID
        envelope['data']=[{**deepcopy(envelope['data'][0]),'index':index} for index in range(6)]
        self.fixture.w.server.body=json.dumps(envelope).encode()

    def queue(self,usage=None):
        self.h.queue();status,body,headers,behavior=self.h.server.responses.pop()
        value=json.loads(body);value.update(model=DEEPSEEK_MODEL_ID,object='chat.completion')
        value['usage']={'prompt_tokens':20,'completion_tokens':10,'total_tokens':30} if usage is None else usage
        self.h.server.responses.append((status,json.dumps(value).encode(),headers,behavior))

    async def advance(self):
        with patch.object(admission,'admitted',return_value=True):
            return await self.h.advance(context_compiler=build_context,counting_counter=self.fixture.counter,
                compatibility_check=admission.before_send,
                counting_compatibility_check=admission.before_count)

    async def test_real_local_tcp_counts_audit_and_native_c07_under_v3(self):
        self.queue();result=await self.advance();self.assertEqual(result['code'],'AI_FINISHED',result)
        self.assertEqual(len(self.h.server.receipts),1);self.assertEqual(len(self.fixture.w.server.receipts),1)
        row=self.h.attempts()[0];snapshot=json.loads(row['request_snapshot_json'])
        self.assertEqual(snapshot['counting']['release_sha256'],PRACTICAL_RELEASE_SHA256)
        self.assertEqual(snapshot['counting']['admission_mode'],PRACTICAL_MODE)
        self.assertFalse(snapshot['counting']['compatibility_proved'])
        self.assertEqual(row['validation_status'],'SUCCEEDED')
        self.assertEqual(self.f.row('guide_runs',self.f.run)['status'],'COMPLETED')

    async def test_actual_overflow_keeps_usage_but_never_parses_adopts_or_retries(self):
        before=self.f.row('requirement_documents',self.f.created['current_document_id'])
        self.queue({'prompt_tokens':24577,'completion_tokens':10,'total_tokens':24587})
        result=await self.advance();self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(len(self.h.server.receipts),1);self.assertEqual(self.h.delays,[])
        row=self.h.attempts()[0]
        self.assertEqual(row['input_tokens'],24577);self.assertEqual(row['parse_status'],'NOT_STARTED')
        self.assertEqual(row['call_status'],'SUCCEEDED');self.assertEqual(row['error_code'],'CONFIG_INVALID')
        self.assertIsNone(row['trusted_output_json']);self.assertEqual(self.f.row('requirement_documents',before['id']),before)

    async def test_missing_admission_refuses_before_count_or_chat(self):
        with patch.object(admission,'admitted',return_value=False):
            result=await self.h.advance(context_compiler=build_context,counting_counter=self.fixture.counter,
                compatibility_check=admission.before_send,
                counting_compatibility_check=admission.before_count)
        self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(self.fixture.w.server.receipts,[]);self.assertEqual(self.h.server.receipts,[])

    async def test_independent_trust_gate_rechecks_usage_after_parse(self):
        from backend.app.guide import orchestrator
        original=orchestrator._parse
        def tamper(database,identity,clock):
            result=original(database,identity,clock)
            with database.transaction(write=True) as connection:
                raw=json.loads(self.f.row('llm_uses',identity)['raw_response_json'])
                raw['usage']['total_tokens']=1
                connection.execute('UPDATE llm_uses SET raw_response_json=? WHERE id=?',(json.dumps(raw),identity))
            return result
        self.queue()
        with patch.object(orchestrator,'_parse',side_effect=tamper):result=await self.advance()
        self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(len(self.h.server.receipts),1);self.assertEqual(self.h.delays,[])
        self.assertIsNone(self.h.attempts()[0]['trusted_output_json'])

    async def test_default_service_http_worker_count_chat_audit_and_c07_uses_real_admission(self):
        from backend.tests.test_service import ServiceTests
        from backend.tests.requirements import test_create_requirement as creation
        from backend.app.guide import orchestrator
        service=ServiceTests();await service.asyncSetUp()
        self.addCleanup(service.directory.cleanup)
        self.assertTrue(admission.admitted())
        self.queue()
        with patch.dict(os.environ,{'WALLE_MODEL_API_KEY':PROFILE.api_key},clear=True),\
             patch.object(admission,'TokenizationGateway',return_value=self.fixture.counter),\
             patch.object(orchestrator,'ModelGateway',return_value=self.h.gateway):
            async with service.app.router.lifespan_context(service.app):
                async with await service.client() as client:
                    accepted=await client.post('/api/v1/requirements',json=service.payload(),
                        headers={'Idempotency-Key':creation.KEY})
                    self.assertEqual(accepted.status_code,201,accepted.text)
                    identity=accepted.json()['data']['guide_run_id'];due=monotonic()+10
                    while monotonic()<due:
                        read=await client.get('/api/v1/guide-runs/'+str(identity))
                        status=read.json()['data']['status']
                        if status in ('COMPLETED','FAILED','CANCELLED'):break
                        await asyncio.sleep(0.01)
                    self.assertEqual(status,'COMPLETED',read.text)
                    with service.database.transaction() as connection:
                        row=connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=?',(identity,)).fetchone()
                        snapshot=json.loads(row['request_snapshot_json'])
                        self.assertEqual(snapshot['counting']['release_sha256'],PRACTICAL_RELEASE_SHA256)
                        self.assertEqual(row['validation_status'],'SUCCEEDED')
                        self.assertEqual(connection.execute('SELECT count(*) FROM conversation_messages WHERE guide_run_id=? AND role=\'ASSISTANT\'',(identity,)).fetchone()[0],1)
        self.assertEqual(len(self.h.server.receipts),1);self.assertEqual(len(self.fixture.w.server.receipts),1)


class DeepSeekObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f=old_probe.FramingCollectorTests();await self.f.asyncSetUp()
        self.addCleanup(self.f.directory.cleanup);self.addCleanup(self.f.count.tearDown)
        self.addAsyncCleanup(self.f.chat.asyncTearDown)
        self.f.plan=plan();self.f.chat.profile=PROFILE;self.journal=MemoryProbeJournal()
        value=json.loads(self.f.count.server.body);value['model']=DEEPSEEK_MODEL_ID
        self.f.count.server.body=json.dumps(value).encode()

    def queue(self,case,invalid=False):
        content={'schema_version':1,'response_type':'CLARIFY_TEXT','message':'请补充。'}
        if case['function_type']=='INITIALIZE_REQUIREMENT':
            content.update(response_type='INITIALIZE_TEXT',confirmed_fact_patches=[])
        if invalid:content['unrecognized']=True
        raw={'model':DEEPSEEK_MODEL_ID,'object':'chat.completion','id':'controlled-probe-chat',
             'created':1791289200,'usage':{'prompt_tokens':260,'completion_tokens':10,'total_tokens':270},
             'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(content)}}]}
        self.f.chat.queue(value=raw)

    async def collect(self):
        return await collect_observations(self.f.plan,PROFILE,None,
            authorized_plan_sha256=digest(self.f.plan),counter=self.f.count.gateway,
            gateway=self.f.chat.gateway(),journal_factory=lambda _:self.journal)

    async def test_all_six_model_specific_tcp_outputs_schema_checked_without_disk_journal(self):
        for case in self.f.plan['cases']:self.queue(case)
        report=await self.collect()
        self.assertTrue(report['complete_observations'])
        self.assertTrue(all(item['output_schema_valid'] for item in report['observations']))
        self.assertEqual(len(self.f.count.server.receipts),6);self.assertEqual(len(self.f.chat.server.receipts),6)
        self.assertFalse(self.f.path.exists());self.assertFalse(report['production_compatibility_proved'])

    async def test_first_schema_failure_consumes_one_count_and_chat_without_retry_or_files(self):
        self.queue(self.f.plan['cases'][0],invalid=True)
        report=await self.collect()
        self.assertEqual(report['stopped_reason'],'OUTPUT_INVALID');self.assertFalse(report['complete_observations'])
        self.assertEqual(len(self.f.count.server.receipts),1);self.assertEqual(len(self.f.chat.server.receipts),1)
        self.assertFalse(self.f.path.exists())
