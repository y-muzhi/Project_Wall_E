"""Actual count TCP -> native audit -> Chat TCP -> C07; offline proof fixtures.

No actual model accuracy/framing/effect claim, budget expansion or paid request.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from backend.app.guide.context_builder import build_context, BuiltContext
from backend.app.guide.counted_context import compile_counted_candidate
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.guide.trusted_output import produce_trusted_output
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.execution_lease import ExecutionLease, ExecutionRetired, LeasedDatabase
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.command_execution import Rejected
from backend.tests.guide import test_orchestrator as original
from backend.tests.infrastructure import test_tokenization as tcp


class CountedOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.h=original.OrchestratorTests();await self.h.asyncSetUp()
        # This helper has no separate IsolatedAsyncio runner. Release its
        # native fixture directly and assert cleanup's result.
        self.addCleanup(lambda:self.assertTrue(self.h.helper.doCleanups()))
        self.addAsyncCleanup(self.h.asyncTearDown)
        self.f=self.h.fixture
        self.w=tcp.TokenizationTests();self.w.setUp();self.addCleanup(self.w.tearDown)
        envelope=tcp.envelope();envelope['data']=[{**deepcopy(envelope['data'][0]),'index':index} for index in range(6)]
        self.w.server.body=json.dumps(envelope).encode()
        self.counter=self.w.gateway
        self.journal=CountingJournal(self.f.database,self.f.lock)

    async def advance(self,**changes):
        return await self.h.advance(context_compiler=build_context,counting_counter=self.counter,
            counting_compatibility_check=lambda *args:True,**changes)

    def records(self,phase):
        return [json.loads(path.read_bytes()) for path in self.journal.root.glob('*.'+phase+'.json')]

    async def test_actual_count_and_chat_separate_audits_exact_request_native_c07_no_open_write_transaction(self):
        f=self.f;current=f.row('requirement_documents',f.created['current_document_id'])
        self.h.queue()
        def inspect():
            with f.database.transaction(write=True) as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],1)
                prepared,finished=self.records('prepared'),self.records('finished')
                self.assertEqual(len(prepared),1);self.assertEqual(finished[0]['phase'],'SUCCEEDED')
        self.h.server.inspect_request=inspect
        result=await self.advance();self.assertEqual(result['code'],'AI_FINISHED',result)
        self.assertEqual(len(self.w.server.receipts),1);self.assertEqual(len(self.h.server.receipts),1)
        count=json.loads(self.w.server.receipts[0]['body']);chat=json.loads(self.h.server.receipts[0]['body'])
        self.assertEqual(count['text'][:2],[item['content'] for item in chat['messages']])
        audit=self.h.attempts()[0];snapshot=json.loads(audit['request_snapshot_json'])
        self.assertEqual(snapshot['request'],chat);self.assertEqual(snapshot['counting']['audit_format'],'counts_summary_v1')
        self.assertFalse(snapshot['counting']['compatibility_proved'])
        measure=snapshot['counting']['count_attempts'][0]['measurement']
        self.assertNotIn('response',measure);self.assertIn('response_sha256',measure)
        self.assertEqual(measure['journal_id'],self.records('prepared')[0]['id'])
        self.assertEqual(audit['validation_status'],'SUCCEEDED');self.assertEqual(f.row('requirement_documents',current['id']),current)
        for path in self.journal.root.glob('*.json'):self.assertNotIn(f.profile.api_key,path.read_text(encoding='utf-8'))
        self.assertTrue(all(item.closed for item in self.w.transports))

    async def test_missing_pre_count_gate_prevents_count_and_chat(self):
        result=await self.h.advance(context_compiler=build_context,counting_counter=self.counter,counting_compatibility_check=None)
        self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(self.w.server.receipts,[]);self.assertEqual(self.h.server.receipts,[]);self.assertEqual(self.h.attempts(),[])

    async def test_false_pre_count_gate_prevents_all_network_and_audit_files(self):
        result=await self.h.advance(context_compiler=build_context,counting_counter=self.counter,counting_compatibility_check=lambda *args:False)
        self.assertEqual(result['details']['error_code'],'CONFIG_INVALID');self.assertFalse(self.journal.root.exists())
        self.assertEqual(self.w.server.receipts,[]);self.assertEqual(self.h.attempts(),[])

    async def test_missing_final_gate_prevents_even_counting(self):
        result=await self.h.advance(context_compiler=build_context,counting_counter=self.counter,counting_compatibility_check=lambda *args:True,compatibility_check=None)
        self.assertEqual(result['details']['error_code'],'CONFIG_INVALID');self.assertEqual(self.w.server.receipts,[])

    async def test_count_error_has_one_physical_count_and_no_chat_attempt_or_retry(self):
        self.w.server.status=503
        result=await self.advance();self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(len(self.w.server.receipts),1);self.assertEqual(self.h.server.receipts,[]);self.assertEqual(self.h.attempts(),[])
        self.assertEqual(self.h.delays,[]);self.assertEqual(len(self.records('prepared')),1)
        self.assertEqual(self.records('finished')[0]['phase'],'FAILED')

    async def test_chat_three_attempts_each_fresh_count_without_pre_backoff_count_or_nested_retry(self):
        self.h.queue({'error':{'code':'ServerOverloaded','message':'offline'}},status=429)
        self.h.queue({'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'unknown schema diagnostic','confirmed_fact_patches':[],'extra':1})
        self.h.queue()
        result=await self.advance();self.assertEqual(result['code'],'AI_FINISHED',result)
        self.assertEqual(len(self.w.server.receipts),3);self.assertEqual(len(self.h.server.receipts),3)
        self.assertEqual([(item['call_no'],item['attempt_no']) for item in self.h.attempts()],[(1,1),(1,2),(1,3)])
        self.assertEqual(self.h.delays,[2,5]);self.assertEqual(len(self.records('prepared')),3)
        self.assertEqual(len({json.loads(row['request_snapshot_json'])['counting']['count_attempts'][0]['measurement']['journal_id'] for row in self.h.attempts()}),3)

    async def test_changed_current_version_while_count_waits_rejects_before_chat_and_audit_attempt(self):
        ready,resume=asyncio.Event(),asyncio.Event();wire=self.counter
        class Counter:
            async def count(self,profile,texts):
                receipt=await wire.count(profile,texts);ready.set();await resume.wait();return receipt
        self.counter=Counter();task=asyncio.create_task(self.advance())
        await asyncio.wait_for(ready.wait(),3)
        with self.f.database.transaction(write=True) as connection:
            connection.execute('UPDATE requirement_documents SET content_version=content_version+1 WHERE id=?',(self.f.created['current_document_id'],))
        resume.set();result=await asyncio.wait_for(task,3)
        self.assertEqual(result['code'],'AI_FAILED',result);self.assertEqual(result['details']['error_code'],'CONTENT_VERSION_CONFLICT')
        self.assertEqual(len(self.w.server.receipts),1);self.assertEqual(self.h.server.receipts,[]);self.assertEqual(self.h.attempts(),[])
        self.assertEqual(self.records('finished')[0]['phase'],'SUCCEEDED')

    async def test_logical_cancel_during_count_keeps_cancelled_and_prevents_chat(self):
        ready,resume=asyncio.Event(),asyncio.Event();wire=self.counter
        class Counter:
            async def count(self,profile,texts):
                receipt=await wire.count(profile,texts);ready.set();await resume.wait();return receipt
        self.counter=Counter();task=asyncio.create_task(self.advance());await asyncio.wait_for(ready.wait(),3)
        self.h.cancel();resume.set();result=await asyncio.wait_for(task,3)
        self.assertEqual(result['code'],'AI_STOPPED',result);self.assertEqual(self.f.row('guide_runs',self.f.run)['status'],'CANCELLED')
        self.assertEqual(self.h.server.receipts,[]);self.assertEqual(self.h.attempts(),[])

    async def test_actual_count_connection_cancelled_and_lease_retired_leave_unknown_prepared_no_late_files(self):
        self.w.server.hold=True;lease=ExecutionLease();database=LeasedDatabase(self.f.database,lease)
        task=asyncio.create_task(execute_guide_run(database,{'guide_run_id':self.f.run},process_lock=self.f.lock,
            catalog=self.f.catalog,profile=self.f.profile,gateway=self.h.gateway,compatibility_check=lambda *args:True,
            counting_counter=self.counter,counting_compatibility_check=lambda *args:True,clock=self.h.clock))
        self.assertTrue(await asyncio.to_thread(self.w.server.entered.wait,3))
        self.h.cancel();lease.retire();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(await asyncio.to_thread(self.w.server.peer_closed.wait,3))
        self.assertEqual(len(self.records('prepared')),1);self.assertEqual(self.records('finished'),[])
        self.assertEqual(self.h.server.receipts,[]);self.assertEqual(self.h.attempts(),[])

    async def test_count_audit_fsync_failure_prevents_counter_send_and_preserves_no_chat(self):
        with patch('backend.app.infrastructure.counting_journal.os.fsync',side_effect=OSError('offline disk failure')):
            result=await self.advance()
        self.assertEqual(result['details']['error_code'],'STORAGE_UNAVAILABLE',result)
        self.assertEqual(self.w.server.receipts,[]);self.assertEqual(self.h.attempts(),[])

    async def test_final_compatibility_rejection_after_count_never_sends_chat(self):
        result=await self.advance(compatibility_check=lambda *args:False)
        self.assertEqual(result['details']['error_code'],'CONFIG_INVALID');self.assertEqual(len(self.w.server.receipts),1)
        self.assertEqual(self.h.server.receipts,[]);self.assertEqual(self.h.attempts(),[])

    async def test_audit_and_trusted_output_reject_tampered_count_ownership_or_removed_evidence(self):
        f=self.f
        from backend.app.guide.orchestrator import _context
        actual,function=_context(f.database,f.run,f.catalog)
        context=await compile_counted_candidate(actual,function,f.profile,counter=self.counter)
        before=f.facts()
        for change in ('model','counts','schema','input','manifest','system'):
            candidate=context;evidence=context.counting_evidence
            if change=='model':evidence['count_attempts'][0]['measurement']['model']='other'
            elif change=='counts':evidence['count_attempts'][0]['measurement']['counts'][0]=True
            elif change=='schema':evidence['schema']['derived_schema_sha256']='0'*64
            elif change=='input':candidate=replace(context,input_json=context.input_json+' ')
            elif change=='manifest':candidate=replace(context,manifest_json='{}')
            elif change=='system':candidate=replace(context,system=context.system+' ')
            if change in ('model','counts','schema'):candidate=replace(context,counting_json=json.dumps(evidence))
            with self.subTest(change=change),self.assertRaises((ConfigInvalid,Rejected)):
                with f.database.transaction(write=True) as connection:AuditRepository(connection).prepare(f.run,function,f.profile,candidate,'2026-10-04T08:00:10.000Z',catalog=f.catalog)
            self.assertEqual(f.facts(),before)
        with f.database.transaction(write=True) as connection:prepared=dict(AuditRepository(connection).prepare(f.run,function,f.profile,context,'2026-10-04T08:00:10.000Z',catalog=f.catalog))
        from backend.app.guide.orchestrator import _transport,_parse
        self.h.queue();wire=await self.h.gateway.send(f.profile,context)
        _transport(f.database,prepared['id'],wire,f.profile,self.h.clock);_parse(f.database,prepared['id'],self.h.clock)
        row=f.row('llm_uses',prepared['id']);snapshot=json.loads(row['request_snapshot_json'])
        self.assertNotIn('response',snapshot['counting']['count_attempts'][0]['measurement'])
        for change in ('missing','wrong_hash','null','unknown'):
            damaged=deepcopy(snapshot)
            if change=='missing':damaged.pop('counting')
            elif change=='wrong_hash':damaged['counting']['count_attempts'][0]['measurement']['request_sha256']='0'*64
            elif change=='null':damaged['counting']=None
            else:damaged['counting']['unexpected']=True
            with f.database.transaction(write=True) as connection:connection.execute('UPDATE llm_uses SET request_snapshot_json=? WHERE id=?',(json.dumps(damaged),prepared['id']))
            with self.subTest(change=change),self.assertRaises((Rejected,ConfigInvalid)):produce_trusted_output(f.database,prepared['id'],process_lock=f.lock,profile=f.profile,catalog=f.catalog,clock=self.h.clock)
            self.assertIsNone(f.row('llm_uses',prepared['id'])['trusted_output_json'])
        with f.database.transaction(write=True) as connection:connection.execute('UPDATE llm_uses SET request_snapshot_json=? WHERE id=?',(row['request_snapshot_json'],prepared['id']))
        self.assertIsNotNone(produce_trusted_output(f.database,prepared['id'],process_lock=f.lock,profile=f.profile,catalog=f.catalog,clock=self.h.clock))
