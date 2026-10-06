"""Exact counting candidate with actual C03 SQLite; no compatibility/effect claim."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app.guide.context_builder import assemble_input, ContextLimitExceeded
from backend.app.guide.counted_context import compile_counted_candidate, counting_release, RELEASE_SHA256
from backend.app.infrastructure.audit_data import AuditCapacityExceeded
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.infrastructure.schema_transport import compact, function_schema
from backend.app.infrastructure.tokenization import TokenCounts
from backend.tests.guide import test_model_context as contexts
from backend.tests.infrastructure import test_tokenization as tcp


class ControlledCounter:
    """Deliberate pure counting fixture, never a Provider accuracy assertion."""
    def __init__(self, owner, measurements=None):
        self.owner = owner; self.texts = []; self.measurements = measurements

    async def count(self, profile, texts):
        self.texts.append(texts)
        # A genuine second writer can acquire/finish during the asynchronous
        # boundary: the compiler does not hold the C03 read or write txn open.
        with self.owner.database.transaction(write=True) as connection:
            self.owner.assertion(connection)
        await asyncio.sleep(0)
        counts = (1000, 5000, 100, 10, 100, 10) if self.measurements is None else self.measurements(texts)
        raw = {'id': 'controlled-count-'+str(len(self.texts)), 'object': 'list', 'model': MODEL_ID,
               'created': 1791289200, 'data': [{'index': index, 'total_tokens': count} for index, count in enumerate(counts)]}
        return TokenCounts(MODEL_ID, raw['id'], raw['created'], tuple(counts),
                           tuple(hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts),
                           hashlib.sha256(compact({'model': MODEL_ID, 'text': list(texts)}).encode('utf-8')).hexdigest(), compact(raw))


class CountedContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.helper = contexts.ModelContextTests(); self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.database = self.helper.database; self.profile = ModelProfile('offline-counted-fixture-key')
        self.assertion = lambda connection: self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.counter = ControlledCounter(self)

    def actual(self):
        result = self.helper.read(); self.assertEqual(result['code'], 'READ_OK')
        return result['data'], self.helper.catalog.freeze('INITIALIZE', 'USER_INSTRUCTION')

    async def compile(self, data, function, counter=None):
        return await compile_counted_candidate(data, function, self.profile, counter=self.counter if counter is None else counter)

    async def test_exact_unicode_serialized_fields_schema_identity_and_detached_candidate_no_writes(self):
        data, function = self.actual(); before = deepcopy(data); facts = self.helper.facts()
        result = await self.compile(data, function)
        self.assertEqual(result.input, assemble_input(data, function))
        self.assertEqual(list(json.loads(result.input_json)), function.context_policy['field_order'])
        self.assertEqual(result.system, function.prompt+'\n'+function_schema(function).schema_json)
        self.assertEqual(self.counter.texts, [(result.system, result.input_json, *(compact(result.input[key]) for key in ('user_input','source','template','history')))])
        self.assertEqual(result.input_tokens, 6256); self.assertEqual(result.removed_history_ids, ())
        evidence = result.counting_evidence
        self.assertFalse(evidence['compatibility_proved']); self.assertEqual(evidence['release_sha256'], RELEASE_SHA256)
        self.assertEqual(evidence['schema']['original_schema_sha256'], hashlib.sha256(function.output_schema_json.encode()).hexdigest())
        self.assertNotIn(self.profile.api_key, result.counting_json)
        self.assertEqual(data, before); self.assertEqual(self.helper.facts(), facts)
        result.input['read_manifest']['block_ids'].clear(); self.assertEqual(result.input['read_manifest'], data['read_manifest'])

    async def test_v2_real_run_uses_its_frozen_original_protocol_and_same_candidate(self):
        h=self.helper; h.catalog=ResourceCatalog(); created=h.create(idempotency_key='00000000-0000-4000-8000-000000000991')['data']
        data=h.read(created['guide_run_id'])['data']; function=h.catalog.freeze('INITIALIZE','USER_INSTRUCTION')
        self.assertEqual(function.version,'v2'); result=await self.compile(data,function)
        self.assertEqual(result.input['read_manifest']['prompt']['version'],'v2')
        self.assertEqual(result.system,function.prompt+'\n'+function_schema(function).schema_json)

    async def test_every_required_field_exact_limit_and_overflow_without_truncation(self):
        data,function=self.actual()
        for index in (0,2,3,4):
            for extra in (0,1):
                with self.subTest(index=index,extra=extra):
                    values=[1000,5000,100,10,100,10]; values[index]=4096+extra
                    counter=ControlledCounter(self,lambda texts, values=values:values)
                    if extra:
                        with self.assertRaises(ContextLimitExceeded):await self.compile(data,function,counter)
                    else:await self.compile(data,function,counter)
                    self.assertEqual(len(counter.texts),1)
                    self.assertEqual(json.loads(counter.texts[0][1])['user_input'],assemble_input(data,function)['user_input'])

    async def test_full_input_budget_includes_reserve_and_output_exact_boundary(self):
        data,function=self.actual()
        counter=ControlledCounter(self,lambda texts:(4096,20224,100,10,100,10))
        result=await self.compile(data,function,counter);self.assertEqual(result.input_tokens,24576)
        self.assertEqual(result.input_tokens+8192,32768)
        counter=ControlledCounter(self,lambda texts:(4096,20225,100,10,100,10))
        with self.assertRaises(ContextLimitExceeded):await self.compile(data,function,counter)
        self.assertEqual(len(counter.texts),1) # INITIALIZE every grant/heading is required.

    async def test_whole_history_then_optional_blocks_in_document_order_recount_exact_manifest(self):
        h=self.helper;h.activate()
        with self.database.transaction(write=True) as connection:
            for index in range(3):MessageRepository(connection).create_user_text(100+index,h.req,h.run,'明确历史😀'+str(index),f'00000000-0000-4000-8000-{100+index:012d}',h.at)
        identity=h.accept('MODIFY');data=h.read(identity)['data'];function=h.catalog.freeze('MODIFY','USER_INSTRUCTION')
        before=deepcopy(data);facts=h.facts();initial=assemble_input(data,function)
        required=set(data['scope']['required_read_block_ids'])|{item['block_id'] for item in initial['allowed_targets']}
        optional=[item['metadata']['block_id'] for item in initial['current_document']['read_blocks'] if item['metadata']['block_id'] not in required]
        self.assertTrue(optional)
        def measurements(texts):
            value=json.loads(texts[1]);removed=len(initial['current_document']['read_blocks'])-len(value['current_document']['read_blocks'])
            return (1000,24000 if value['history'] or removed<1 else 22000,100,10,100,2049 if value['history'] else 10)
        counter=ControlledCounter(self,measurements);result=await self.compile(data,function,counter)
        self.assertEqual(result.removed_history_ids,tuple(item['id'] for item in data['history']))
        self.assertEqual(result.removed_neighbor_ids,tuple(optional[:1]))
        self.assertEqual(result.input['allowed_targets'],initial['allowed_targets'])
        self.assertEqual(result.input['read_manifest']['message_ids'],[data['user_input']['id']])
        self.assertEqual(result.input['read_manifest']['block_ids'],[item['metadata']['block_id'] for item in result.input['current_document']['read_blocks']])
        self.assertTrue(required.issubset(result.input['read_manifest']['block_ids']))
        for texts in counter.texts[:len(data['history'])+1]:self.assertEqual(len(json.loads(texts[1])['current_document']['read_blocks']),len(initial['current_document']['read_blocks']))
        self.assertEqual(len(result.counting_evidence['count_attempts']),len(counter.texts))
        self.assertEqual(data,before);self.assertEqual(h.facts(),facts)

    async def test_formal_card_current_response_keeps_original_message_identity_when_history_removed(self):
        h=contexts.FormalModelContextTests();h.setUp();self.addCleanup(h.doCleanups)
        h.initialize_cards_fixture();accepted=h.submit();identity=accepted['data']['guide_run']['id']
        data=contexts.get_model_context(h.database,identity,catalog=h.catalog)['data'];function=h.catalog.freeze('INITIALIZE','USER_INSTRUCTION')
        counter=ControlledCounter(self,lambda texts:(1000,5000,100,10,100,2049 if json.loads(texts[5]) else 10))
        result=await self.compile(data,function,counter)
        self.assertIn(11,result.input['read_manifest']['message_ids'])
        self.assertIn(data['user_input']['id'],result.input['read_manifest']['message_ids'])
        self.assertEqual(result.input['user_input']['formal_responses'],data['user_input']['structured_content'])

    async def test_unknown_wrong_model_hash_counts_or_integer_never_falls_back(self):
        data,function=self.actual()
        valid=await self.counter.count(self.profile,(function.prompt+'\n'+function_schema(function).schema_json,compact({k:assemble_input(data,function)[k] for k in function.context_policy['field_order']}),*(compact(assemble_input(data,function)[k]) for k in ('user_input','source','template','history'))))
        for changed in (None,replace(valid,model='another-model'),replace(valid,text_sha256=('a',)*6),replace(valid,request_sha256='a'*64),replace(valid,counts=(True,5000,100,10,100,10)),replace(valid,counts=(-1,5000,100,10,100,10)),replace(valid,counts=(1,))):
            class Counter:
                async def count(self,profile,texts):return changed
            with self.subTest(changed=type(changed)),self.assertRaises(ConfigInvalid):await self.compile(data,function,Counter())

    async def test_counter_failure_and_cancellation_are_not_retried_or_fallback(self):
        data,function=self.actual();calls=[]
        for error in (ConfigInvalid('Controlled counting unavailable'),asyncio.CancelledError()):
            class Counter:
                async def count(self,profile,texts):calls.append(texts);raise error
            with self.assertRaises(type(error)):await self.compile(data,function,Counter())
        self.assertEqual(len(calls),2)

    async def test_frozen_candidate_or_budget_override_is_rejected_before_count(self):
        data,function=self.actual();policy=function.context_policy;policy['budget']['prompt_tokens']=100000
        with self.assertRaises(ConfigInvalid):await self.compile(data,replace(function,context_json=json.dumps(policy)))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'strategy.json';path.write_text('{}')
            with patch('backend.app.guide.counted_context.RELEASE_PATH',path),self.assertRaises(ConfigInvalid):await self.compile(data,function)
        self.assertEqual(self.counter.texts,[]);self.assertFalse(counting_release()['production_enabled'])

    async def test_actual_count_adapter_tcp_receipt_binds_complete_compiled_candidate(self):
        data,function=self.actual();wire=tcp.TokenizationTests();wire.setUp();self.addCleanup(wire.tearDown)
        envelope=tcp.envelope();envelope['data']=[{**envelope['data'][0],'index':index} for index in range(6)]
        wire.server.body=json.dumps(envelope).encode()
        result=await self.compile(data,function,wire.gateway)
        request=json.loads(wire.server.receipts[0]['body'])
        self.assertEqual(request['model'],MODEL_ID);self.assertEqual(request['text'][:2],[result.system,result.input_json])
        self.assertEqual(result.input_tokens,260);self.assertEqual(len(wire.server.receipts),1)
        self.assertFalse(result.counting_evidence['compatibility_proved']);self.assertTrue(all(item.closed for item in wire.transports))

    async def test_measurement_audit_capacity_failure_never_discards_evidence_to_continue(self):
        data,function=self.actual()
        with patch('backend.app.infrastructure.audit_data.MAX_AUDIT_BYTES',10),self.assertRaises(AuditCapacityExceeded):await self.compile(data,function)
        self.assertEqual(len(self.counter.texts),1)
