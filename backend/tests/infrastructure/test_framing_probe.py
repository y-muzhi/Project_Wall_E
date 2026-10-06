"""Bounded observation tooling on real local TCP/files; no paid or proof claim."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app.infrastructure.framing_probe import build_plan,validate_plan,digest,collect_observations,ProbeJournal,prune_raw
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.time import utc_milliseconds
from backend.tests.infrastructure.framing_probe_cases import cases
from backend.tests.infrastructure import test_tokenization as count_tcp
from backend.tests.infrastructure import test_model_gateway as chat_tcp
from backend.tests.requirements.test_create_requirement import INSTANT


@lru_cache(maxsize=1)
def prepared():
    return build_plan(cases())


class FramingPlanTests(unittest.TestCase):
    def test_six_native_c03_inputs_frozen_protocols_unicode_and_no_live_configuration_or_network(self):
        with patch('socket.socket.connect',side_effect=AssertionError('No Provider')):
            plan=deepcopy(prepared());self.assertEqual(validate_plan(plan),plan)
        self.assertEqual(len(plan['cases']),6);self.assertEqual({case['version'] for case in plan['cases']},{'v2'})
        self.assertEqual(plan['limits'],{'count_adapter_invocations':6,'chat_adapter_invocations':6,'retries':0,'maximum_requested_completion_tokens':49152})
        self.assertFalse(plan['production_compatibility_proved']);self.assertNotIn('api_key',plan['profile'])
        for case in plan['cases']:
            self.assertIn('😀',case['input_json']);self.assertIn('\\n',case['input_json']);self.assertEqual(len(case['text_sha256']),6)
            self.assertEqual(case['text_bytes'][:2],[len(case['system'].encode('utf-8')),len(case['input_json'].encode('utf-8'))])

    def test_changed_model_limits_system_schema_fields_or_order_rejected_without_fallback(self):
        base=deepcopy(prepared())
        changes=[lambda p:p['profile'].update(model_name='another-model'),lambda p:p['limits'].update(chat_adapter_invocations=7),
            lambda p:p.update(production_compatibility_proved=True),lambda p:p.update(unrecognized=True),
            lambda p:p['cases'][0].update(system='changed'),lambda p:p['cases'][0]['schema'].update(derived_schema_sha256='0'*64),
            lambda p:p['cases'].reverse(),lambda p:p['cases'][0].update(input_json='{}')]
        for change in changes:
            plan=deepcopy(base);change(plan)
            with self.subTest(plan_hash=digest(plan)),self.assertRaises(ConfigInvalid):validate_plan(plan)

    def test_missing_duplicate_or_mixed_function_version_is_not_a_whole_plan(self):
        items=[{'function_type':case['function_type'],'version':case['version'],'input':json.loads(case['input_json'])} for case in prepared()['cases']]
        for candidate in (items[:-1],[items[0]]*6,[{**items[0],'version':'v1'},*items[1:]]):
            with self.assertRaises(ConfigInvalid):build_plan(candidate)


class FramingCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plan=deepcopy(prepared());self.directory=tempfile.TemporaryDirectory(prefix='walle-framing-probe-');self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'new-run';self.now=INSTANT
        self.count=count_tcp.TokenizationTests();self.count.setUp();self.addCleanup(self.count.tearDown)
        envelope=count_tcp.envelope();envelope['data']=[{**deepcopy(envelope['data'][0]),'index':index} for index in range(6)]
        self.count.server.body=json.dumps(envelope).encode()
        self.chat=chat_tcp.ModelGatewayTests();await self.chat.asyncSetUp();self.addAsyncCleanup(self.chat.asyncTearDown)

    def queue(self,**changes):
        value=chat_tcp.envelope(**({'object':'chat.completion','created':1791289200,'usage':{'prompt_tokens':260,'completion_tokens':10,'total_tokens':270}} | changes))
        self.chat.queue(value=value)

    async def run_probe(self,**changes):
        return await collect_observations(self.plan,self.chat.profile,self.path,authorized_plan_sha256=digest(self.plan),
            counter=self.count.gateway,gateway=self.chat.gateway(),clock=lambda:self.now,**changes)

    def load(self,name):return json.loads((self.path/(name+'.json')).read_bytes())

    async def test_exact_count_to_chat_six_actual_requests_usage_boundary_stays_not_proved(self):
        for _ in range(6):self.queue()
        report=await self.run_probe();self.assertTrue(report['complete_observations']);self.assertTrue(report['within_candidate_reserve_on_observed_cases'])
        self.assertFalse(report['production_compatibility_proved']);self.assertFalse(report['model_effects_proved'])
        self.assertEqual(len(self.count.server.receipts),6);self.assertEqual(len(self.chat.server.receipts),6)
        for index,(count,chat) in enumerate(zip(self.count.server.receipts,self.chat.server.receipts),1):
            counted=json.loads(count['body']);sent=json.loads(chat['body'])
            self.assertEqual(counted['text'][:2],[message['content'] for message in sent['messages']])
            self.assertEqual(sent['max_tokens'],8192);self.assertEqual(sent['thinking'],{'type':'disabled'})
            self.assertEqual(self.load(f'{index:02d}-chat-prepared')['request'],sent)
            self.assertEqual(report['observations'][index-1]['observed_framing_delta'],256)
        for file in self.path.glob('*.json'):
            text=file.read_text(encoding='utf-8');self.assertNotIn(self.chat.profile.api_key,text);self.assertNotIn('excluded private thought',text)
        self.assertTrue(all(transport.closed for transport in self.count.transports))

    async def test_missing_or_other_plan_authorization_blocks_all_io_and_directory(self):
        for permit in (None,True,'0'*64):
            with self.assertRaises(ConfigInvalid):await collect_observations(self.plan,self.chat.profile,self.path,
                authorized_plan_sha256=permit,counter=self.count.gateway,gateway=self.chat.gateway())
        self.assertFalse(self.path.exists());self.assertEqual(self.count.server.receipts,[]);self.assertEqual(self.chat.server.receipts,[])

    async def test_count_failure_one_call_no_chat_or_automatic_retry_unknown_preserved(self):
        self.count.server.status=503
        report=await self.run_probe();self.assertFalse(report['complete_observations']);self.assertEqual(report['count_adapter_invocations'],1)
        self.assertEqual(report['chat_adapter_invocations'],0);self.assertEqual(len(self.count.server.receipts),1)
        self.assertEqual(self.load('01-count-finished')['phase'],'FAILED');self.assertEqual(self.chat.server.receipts,[])

    async def test_chat_retryable_429_is_one_call_and_never_nested_probe_retry(self):
        self.chat.queue(status=429,value={'error':{'code':'RateLimitExceeded.EndpointRPMExceeded'}})
        report=await self.run_probe();self.assertFalse(report['complete_observations'])
        self.assertEqual((report['count_adapter_invocations'],report['chat_adapter_invocations']),(1,1))
        self.assertEqual((len(self.count.server.receipts),len(self.chat.server.receipts)),(1,1))
        self.assertEqual(self.load('01-chat-finished')['http_status'],429)

    async def test_model_usage_role_and_unknown_count_rejected_not_measured_as_zero(self):
        variants=[{'model':'wrong-model'},{'usage':{}},{'usage':{'prompt_tokens':True,'completion_tokens':1}},
            {'usage':{'prompt_tokens':260,'completion_tokens':10,'total_tokens':999}},
            {'choices':[{'message':{'role':'user','content':'invalid'},'finish_reason':'stop'}]}]
        original=self.path
        for index,changes in enumerate(variants):
            self.path=original.with_name('case-'+str(index));self.queue(**changes)
            report=await self.run_probe();self.assertFalse(report['complete_observations']);self.assertEqual(report['observations'],[])
        self.assertEqual((len(self.count.server.receipts),len(self.chat.server.receipts)),(len(variants),len(variants)))

    async def test_first_excess_reserve_is_preserved_stops_plan_and_cannot_enable_production(self):
        self.queue(usage={'prompt_tokens':261,'completion_tokens':10,'total_tokens':271})
        report=await self.run_probe();self.assertEqual(report['observations'][0]['observed_framing_delta'],257)
        self.assertFalse(report['within_candidate_reserve_on_observed_cases']);self.assertFalse(report['production_compatibility_proved'])
        self.assertEqual(len(self.chat.server.receipts),1)

    async def test_required_budget_overflow_keeps_count_result_and_never_sends_chat(self):
        raw=json.loads(self.count.server.body);row=raw['data'][0];row.update(total_tokens=4097,token_ids=[10]*4097,offset_mapping=[[0,0]]*4097)
        self.count.server.body=json.dumps(raw).encode()
        report=await self.run_probe();self.assertEqual(self.load('01-count-finished')['phase'],'SUCCEEDED')
        self.assertFalse(report['complete_observations']);self.assertEqual(self.chat.server.receipts,[])

    async def test_actual_socket_cancel_preserves_unknown_and_existing_directory_cannot_resume(self):
        self.count.server.hold=True;task=asyncio.create_task(self.run_probe())
        self.assertTrue(await asyncio.to_thread(self.count.server.entered.wait,3));task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(await asyncio.to_thread(self.count.server.peer_closed.wait,3))
        self.assertEqual(self.load('01-count-finished')['physical_outcome'],'UNKNOWN');self.assertFalse((self.path/'report.json').exists())
        with self.assertRaises(StorageUnavailable):await self.run_probe()
        self.assertEqual(len(self.count.server.receipts),1);self.assertEqual(self.chat.server.receipts,[])

    async def test_prepared_fsync_failure_denies_counter_io_and_keeps_partial_unknown_file(self):
        calls=0
        def sync(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('controlled fsync failure')
        with patch('backend.app.infrastructure.framing_probe.os.fsync',side_effect=sync),self.assertRaises(StorageUnavailable):await self.run_probe()
        self.assertTrue((self.path/'01-count-prepared.json').exists());self.assertFalse((self.path/'01-count-finished.json').exists())
        self.assertEqual(self.count.server.receipts,[]);self.assertEqual(self.chat.server.receipts,[])

    async def test_thirty_day_raw_boundary_summary_identity_requests_and_unknown_files_preserved(self):
        for _ in range(6):self.queue()
        await self.run_probe();prepared_bytes=(self.path/'01-chat-prepared.json').read_bytes();report=(self.path/'report.json').read_bytes()
        (self.path/'unknown.txt').write_text('preserved',encoding='utf-8')
        self.assertEqual(prune_raw(self.path,utc_milliseconds(self.now+timedelta(days=30))),0)
        self.assertEqual(prune_raw(self.path,utc_milliseconds(self.now+timedelta(days=30,milliseconds=1))),12)
        count=self.load('01-count-finished');chat=self.load('01-chat-finished')
        self.assertNotIn('response',count['measurement']);self.assertIn('response_sha256',count['measurement'])
        self.assertNotIn('raw_response',chat);self.assertIn('raw_response_sha256',chat)
        self.assertEqual((self.path/'01-chat-prepared.json').read_bytes(),prepared_bytes);self.assertEqual((self.path/'report.json').read_bytes(),report)
        self.assertEqual(prune_raw(self.path,utc_milliseconds(self.now+timedelta(days=31))),0)

    async def test_raw_replace_failure_preserves_original_response_and_does_not_fabricate_prune_success(self):
        self.queue();self.queue(model='wrong')
        await self.run_probe();before=(self.path/'01-count-finished.json').read_bytes()
        with patch('backend.app.infrastructure.framing_probe.os.replace',side_effect=OSError('controlled replace failure')),self.assertRaises(StorageUnavailable):
            prune_raw(self.path,utc_milliseconds(self.now+timedelta(days=31)))
        self.assertEqual((self.path/'01-count-finished.json').read_bytes(),before)
