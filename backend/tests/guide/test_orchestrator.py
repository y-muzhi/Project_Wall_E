"""Native ORCH + SQLite + actual loopback HTTP; no paid/effect/compatibility claim.

The compiler explicitly expands diagnostic budgets and the offline compatibility
check accepts only this controlled server. Production dependencies stay closed.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import json
from threading import Thread
import unittest
from unittest.mock import patch as fault

from backend.app.guide import commands
from backend.app.guide.context_builder import build_context
from backend.app.guide.orchestrator import execute_guide_run
from backend.app.infrastructure.database import CommitOutcomeUnknown, Database
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.messages.queries import list_messages
from backend.tests.guide import test_result_persistence as persistence
from backend.tests.guide import test_acceptance as acceptance
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.infrastructure import test_model_gateway as wire


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.helper=persistence.ResultPersistenceTests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.fixture=self.helper.fixture
        self.server=wire.ControlledServer();self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True)
        self.thread.start();self.observed=[];self.transports=[];self.delays=[]
        self.clock=lambda:creation.INSTANT+timedelta(seconds=10)
        def factory():
            transport=wire.ForwardTransport(self.server.server_port,self.observed)
            self.transports.append(transport);return transport
        self.gateway=ModelGateway(transport_factory=factory)

    async def asyncTearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
        self.assertFalse(self.thread.is_alive());self.assertEqual(self.server.errors,[])
        self.assertTrue(all(item.closed for item in self.transports))

    def compile(self,actual,function):
        policy=function.context_policy;policy['budget'].update(prompt_tokens=100000,input_tokens=100000,total_tokens=120000)
        return build_context(actual,replace(function,context_json=json.dumps(policy)))

    async def sleep(self,seconds):self.delays.append(seconds);await asyncio.sleep(0)

    def queue(self,value=None,status=200,behavior=None,raw=None):
        if value is None:value={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'实际TCP程序诊断结果','confirmed_fact_patches':[]}
        response=wire.envelope(choices=[{'message':{'role':'assistant','content':json.dumps(value,ensure_ascii=False)},'finish_reason':'stop'}]) if status==200 else value
        body=json.dumps(response,ensure_ascii=False).encode() if raw is None else raw
        self.server.responses.append((status,body,{},behavior))

    async def advance(self,**changes):
        f=self.fixture
        options={'process_lock':f.lock,'catalog':f.catalog,'profile':f.profile,'gateway':self.gateway,
            'context_compiler':self.compile,'compatibility_check':lambda *args:True,'clock':self.clock,'sleep':self.sleep,**changes}
        return await execute_guide_run(f.database,{'guide_run_id':f.run},**options)

    def attempts(self):
        with self.fixture.database.transaction() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=? ORDER BY call_no,attempt_no',(self.fixture.run,))]

    def cancel(self):
        f=self.fixture
        value=commands.cancel_guide_run(f.executor,{'guide_run_id':f.run,'idempotency_key':creation.OTHER},clock=self.clock)
        self.assertEqual(value['code'],'GUIDE_CANCELLED',value)

    async def test_real_tcp_audit_commit_before_send_and_actual_c07_completion_no_open_sql(self):
        f=self.fixture;current=f.row('requirement_documents',f.created['current_document_id'])
        def inspect():
            with f.database.transaction(write=True) as connection:
                rows=connection.execute('SELECT call_status,attempt_no FROM llm_uses').fetchall()
                self.assertEqual([(x['call_status'],x['attempt_no']) for x in rows],[('RUNNING',1)])
                self.assertEqual(connection.execute('SELECT current_step FROM guide_runs WHERE id=?',(f.run,)).fetchone()[0],'CALLING_MODEL')
        self.server.inspect_request=inspect;self.queue()
        result=await self.advance();self.assertEqual(result,{'code':'AI_FINISHED','data':{'guide_run_id':f.run,'status':'COMPLETED','current_step':'FINISHED','last_call_no':1},'details':None})
        row=self.attempts()[0];self.assertEqual((row['call_status'],row['parse_status'],row['validation_status']),('SUCCEEDED','SUCCEEDED','SUCCEEDED'))
        self.assertEqual(json.loads(row['request_snapshot_json'])['request'],json.loads(self.server.receipts[0]['body']))
        self.assertEqual((row['input_tokens'],row['output_tokens'],row['cost']),(123,10,None))
        self.assertEqual(f.row('requirement_documents',current['id']),current)
        self.assertEqual(f.row('requirements',f.req)['document_work_state'],'IDLE')
        before=f.facts();self.assertEqual((await self.advance())['code'],'AI_STOPPED');self.assertEqual(f.facts(),before)
        self.assertEqual(len(self.server.receipts),1)

    async def test_retry_rate_limit_then_unknown_output_field_then_success_same_call_exact_three_requests(self):
        self.queue({'error':{'code':'ServerOverloaded','message':'diagnostic'}},status=429)
        invalid={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'不可修复候选','confirmed_fact_patches':[],'reasoning':'unknown schema field'}
        self.queue(invalid);self.queue()
        result=await self.advance();self.assertEqual(result['code'],'AI_FINISHED',result)
        rows=self.attempts();self.assertEqual([(x['call_no'],x['attempt_no']) for x in rows],[(1,1),(1,2),(1,3)])
        self.assertEqual((rows[0]['call_status'],rows[1]['validation_status'],rows[2]['validation_status']),('FAILED','FAILED','SUCCEEDED'))
        self.assertIsNone(rows[1]['trusted_output_json']);self.assertEqual(self.delays,[2,5]);self.assertEqual(len(self.observed),3)
        self.assertNotIn('reasoning',json.loads(rows[1]['parsed_output_json']))
        self.assertIn('reasoning',json.loads(json.loads(rows[1]['raw_response_json'])['choices'][0]['message']['content']))

    async def test_all_three_fail_last_failure_run_error_no_fourth_send_or_business(self):
        self.queue(behavior='disconnect')
        self.queue(raw=json.dumps(wire.envelope(choices=[{'message':{'role':'assistant','content':'```json\n{}\n```'},'finish_reason':'stop'}])).encode())
        self.queue({'error':{'code':'RateLimitExceeded.EndpointRPMExceeded','message':'diagnostic'}},status=429)
        result=await self.advance();self.assertEqual(result['code'],'AI_FAILED',result)
        self.assertEqual(result['details'],{'guide_run_id':self.fixture.run,'error_code':'MODEL_ERROR'})
        rows=self.attempts();self.assertEqual(len(rows),3);self.assertEqual(rows[1]['parse_status'],'FAILED')
        self.assertTrue(all(x['trusted_output_json'] is None for x in rows));self.assertEqual(self.delays,[2,5])
        self.assertEqual(len(self.observed),3);self.assertEqual(self.fixture.row('requirements',self.fixture.req)['document_work_state'],'IDLE')
        with self.fixture.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0],0)

    async def test_authentication_is_one_attempt_without_retry_or_provider_details_leak(self):
        self.queue({'error':{'code':'AuthenticationError','message':'sensitive '+self.fixture.profile.api_key}},status=401)
        result=await self.advance();self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(len(self.observed),1);self.assertEqual(self.delays,[])
        self.assertNotIn('sensitive',str(result));self.assertNotIn(self.fixture.profile.api_key,str(self.attempts()))

    async def test_successful_http_content_filter_is_not_retried_or_adopted(self):
        value=wire.envelope(choices=[{'message':{'role':'assistant','content':'{}','refusal':'policy'},'finish_reason':'content_filter'}])
        self.queue(raw=json.dumps(value).encode());result=await self.advance()
        self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(result['details']['error_code'],'OUTPUT_INVALID')
        self.assertEqual(len(self.observed),1);self.assertEqual(self.delays,[]);self.assertEqual(self.attempts()[0]['parse_status'],'FAILED')

    async def test_all_output_parse_failures_preserve_three_attempts_and_final_output_invalid(self):
        for _ in range(3):self.queue(raw=json.dumps(wire.envelope(choices=[{'message':{'role':'assistant','content':'[]'},'finish_reason':'stop'}])).encode())
        result=await self.advance();self.assertEqual(result['details']['error_code'],'OUTPUT_INVALID')
        self.assertEqual([x['parse_status'] for x in self.attempts()],['FAILED']*3);self.assertEqual(len(self.observed),3)

    async def test_production_budget_failure_records_real_run_no_attempt_or_external_request(self):
        result=await self.advance(context_compiler=build_context)
        self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(result['details']['error_code'],'CONTEXT_LIMIT_EXCEEDED')
        self.assertEqual(self.attempts(),[]);self.assertEqual(self.observed,[])

    async def test_missing_credentials_records_config_failure_no_attempt(self):
        with fault.dict('os.environ',{},clear=True):result=await self.advance(profile=None)
        self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(self.attempts(),[]);self.assertEqual(self.observed,[])

    async def test_missing_or_false_compatibility_proof_never_authorizes_send(self):
        result=await self.advance(compatibility_check=None)
        self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(result['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(self.attempts(),[]);self.assertEqual(self.observed,[])

    async def test_cancellation_committed_during_backoff_prevents_second_send(self):
        self.queue({'error':{'code':'ServerOverloaded'}},status=429)
        async def cancel_sleep(seconds):self.delays.append(seconds);await asyncio.to_thread(self.cancel)
        result=await self.advance(sleep=cancel_sleep)
        self.assertEqual(result['code'],'AI_STOPPED');self.assertEqual(result['data']['status'],'CANCELLED')
        self.assertEqual(len(self.observed),1);self.assertEqual(len(self.attempts()),1)

    async def test_version_change_during_backoff_rechecked_without_second_request(self):
        self.queue({'error':{'code':'ServerOverloaded'}},status=429)
        async def change(seconds):
            self.delays.append(seconds)
            # Explicit hostile stored-state diagnostic, not a normal manual
            # edit accepted during GUIDE_ACTIVE ownership.
            with self.fixture.database.transaction(write=True) as connection:
                connection.execute("UPDATE requirement_documents SET content_version=2 WHERE id=?",(self.fixture.created['current_document_id'],))
        result=await self.advance(sleep=change)
        self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(result['details']['error_code'],'CONTENT_VERSION_CONFLICT')
        self.assertEqual(len(self.observed),1)

    async def test_actual_cancel_then_task_cancel_closes_real_waiting_tcp_and_never_c07(self):
        self.queue(behavior='hold');task=asyncio.create_task(self.advance())
        self.assertTrue(await asyncio.to_thread(self.server.entered.wait,3))
        await asyncio.to_thread(self.cancel);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(await asyncio.to_thread(self.server.peer_closed.wait,3))
        self.assertEqual(self.fixture.row('guide_runs',self.fixture.run)['status'],'CANCELLED')
        self.assertEqual(self.attempts()[0]['call_status'],'CANCELLED');self.assertIsNone(self.attempts()[0]['trusted_output_json'])

    async def test_late_actual_http_after_logical_cancel_only_adds_measurements(self):
        self.server.inspect_request=self.cancel;self.queue()
        result=await self.advance();self.assertEqual(result['code'],'AI_STOPPED')
        row=self.attempts()[0];self.assertEqual(row['call_status'],'CANCELLED');self.assertEqual(row['input_tokens'],123)
        self.assertEqual(row['parse_status'],'NOT_STARTED');self.assertIsNone(row['trusted_output_json'])

    async def test_real_prepare_commit_lost_ack_does_not_resend_or_erase_request(self):
        original=self.fixture.database;armed=[True]
        class LostPrepare(Database):
            @contextmanager
            def transaction(self,*,write=False):
                with super().transaction(write=write) as connection:
                    yield connection
                    lose=write and armed[0] and connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0]>0
                if lose:armed[0]=False;raise CommitOutcomeUnknown('actual commit lost ACK')
        self.fixture.database=LostPrepare(original.path)
        result=await self.advance();self.assertEqual(result['code'],'AI_FAILED');self.assertEqual(result['details']['error_code'],'STORAGE_UNAVAILABLE')
        self.assertEqual(len(self.attempts()),1);self.assertEqual(self.attempts()[0]['call_status'],'FAILED');self.assertEqual(self.observed,[])

    async def test_real_c07_commit_lost_ack_terminal_is_preserved_without_second_send(self):
        original=self.fixture.database;armed=[True];identity=self.fixture.run
        class LostC07(Database):
            @contextmanager
            def transaction(self,*,write=False):
                with super().transaction(write=write) as connection:
                    yield connection
                    lose=write and armed[0] and connection.execute('SELECT status FROM guide_runs WHERE id=?',(identity,)).fetchone()[0]=='COMPLETED'
                if lose:armed[0]=False;raise CommitOutcomeUnknown('actual commit lost ACK')
        self.fixture.database=LostC07(original.path);self.queue()
        result=await self.advance();self.assertEqual(result['code'],'AI_STOPPED');self.assertEqual(result['data']['status'],'COMPLETED')
        self.assertEqual(len(self.observed),1);self.assertIsNotNone(self.attempts()[0]['trusted_output_json'])
        with self.fixture.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0],1)

    async def test_waiting_c07_then_real_continue_uses_same_protocol_new_call_and_resets_attempts(self):
        self.helper.accept('ASK')
        self.queue({'schema_version':1,'response_type':'CLARIFY_TEXT','message':'请补充真实范围'})
        first=await self.advance();self.assertEqual(first['code'],'AI_WAITING_USER');self.assertEqual(first['data']['last_call_no'],1)
        f=self.fixture;run=f.row('guide_runs',f.run)
        result=commands.continue_guide_run(f.executor,{'guide_run_id':f.run,'instruction':'实际补充范围','idempotency_key':acceptance.KEY},catalog=f.catalog,clock=self.clock)
        self.assertEqual(result['code'],'GUIDE_CONTINUED',result)
        self.queue({'error':{'code':'ServerOverloaded'}},status=429)
        self.queue({'schema_version':1,'response_type':'ANSWER','message':'实际本机结果'})
        second=await self.advance();self.assertEqual(second['code'],'AI_FINISHED');self.assertEqual(second['data']['last_call_no'],2)
        self.assertEqual([(x['call_no'],x['attempt_no']) for x in self.attempts()],[(1,1),(2,1),(2,2)])
        self.assertEqual(f.row('guide_runs',f.run)['prompt_version'],run['prompt_version'])
        messages=list_messages(f.database,{'requirement_id':f.req},catalog=f.catalog)['data']['items']
        self.assertEqual([x['content'] for x in messages if x['role']=='ASSISTANT'],['请补充真实范围','实际本机结果'])

    async def test_false_counting_proof_does_not_authorize_a_request(self):
        outcome=await self.advance(compatibility_check=lambda *args:False)
        self.assertEqual(outcome['details']['error_code'],'CONFIG_INVALID')
        self.assertEqual(self.attempts(),[]);self.assertEqual(self.observed,[])

    async def test_strict_internal_input_and_unknown_run_preserve_real_facts(self):
        f=self.fixture;before=f.facts()
        for payload in ({},{'guide_run_id':True},{'guide_run_id':f.run,'gateway':'untrusted'}):
            outcome=await execute_guide_run(f.database,payload,process_lock=f.lock)
            self.assertEqual(outcome['code'],'INVALID_INPUT')
        outcome=await execute_guide_run(f.database,{'guide_run_id':99999},process_lock=f.lock)
        self.assertEqual(outcome['code'],'NOT_FOUND');self.assertEqual(f.facts(),before)

    async def test_duplicate_dispatch_preserves_original_inflight_owner_and_one_request(self):
        self.queue(behavior='hold');original=asyncio.create_task(self.advance())
        self.assertTrue(await asyncio.to_thread(self.server.entered.wait,3))
        duplicate=await self.advance();self.assertEqual(duplicate['code'],'STATE_CONFLICT',duplicate)
        self.assertEqual(self.fixture.row('guide_runs',self.fixture.run)['status'],'RUNNING')
        self.assertEqual(len(self.attempts()),1);self.assertEqual(len(self.observed),1)
        await asyncio.to_thread(self.cancel);original.cancel()
        with self.assertRaises(asyncio.CancelledError):await original

    async def test_sql_request_preparation_failure_cannot_send_an_unrecorded_request(self):
        with self.fixture.database.transaction(write=True) as connection:
            connection.execute("CREATE TRIGGER orch_prepare_fault BEFORE INSERT ON llm_uses BEGIN SELECT RAISE(ABORT,'controlled'); END")
        outcome=await self.advance();self.assertEqual(outcome['details']['error_code'],'STORAGE_UNAVAILABLE',outcome)
        self.assertEqual(self.attempts(),[]);self.assertEqual(self.observed,[])

    async def test_c07_sql_failure_keeps_trusted_audit_and_never_regenerates_business(self):
        with self.fixture.database.transaction(write=True) as connection:
            connection.execute("CREATE TRIGGER orch_result_fault BEFORE INSERT ON conversation_messages WHEN NEW.role='ASSISTANT' BEGIN SELECT RAISE(ABORT,'controlled'); END")
        self.queue();outcome=await self.advance()
        self.assertEqual(outcome['details']['error_code'],'STORAGE_UNAVAILABLE',outcome)
        self.assertEqual(len(self.observed),1);self.assertEqual(self.delays,[])
        self.assertEqual(self.attempts()[0]['validation_status'],'SUCCEEDED')
        self.assertEqual(self.fixture.row('requirements',self.fixture.req)['document_work_state'],'IDLE')
        with self.fixture.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0],0)
