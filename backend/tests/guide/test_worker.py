"""Actual startup/task/monitor/drain with native C01/ORCH/TCP and file DB."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
from threading import Thread, Event
from time import monotonic
import unittest
from unittest.mock import patch

from fastapi import FastAPI
import httpx

from backend.app.guide.worker import GuideWorker, WorkerStartupFailed, MONITOR_SECONDS, SHUTDOWN_GRACE_SECONDS
from backend.app.guide import commands
from backend.app.guide.context_builder import build_context
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.process_lock import ProcessLock, ProcessAlreadyRunning
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.commands import create_requirement
from backend.app.requirements.commands import complete_initialization
from backend.app.documents.commands import start_manual_draft
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.requirements.api import req_router
from backend.app.requirements.http_models import CreateRequirementResponse
from backend.app.shared.http_boundary import HttpRuntime
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.infrastructure import test_model_gateway as wire
from backend.tests.documents.test_patch_validation import patch as suggestion_patch


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='walle-worker-real-');self.addCleanup(self.directory.cleanup)
        self.database=Database(Path(self.directory.name)/'actual.sqlite');self.database.initialize()
        self.catalog=ResourceCatalog();self.now=creation.INSTANT;self.workers=[]
        self.server=wire.ControlledServer();self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True)
        self.thread.start();self.observed=[];self.transports=[]
        def factory():
            transport=wire.ForwardTransport(self.server.server_port,self.observed);self.transports.append(transport);return transport
        self.gateway=ModelGateway(transport_factory=factory)

    async def asyncTearDown(self):
        for worker in self.workers:
            if worker.started:await worker.close()
        self.server.shutdown();self.server.server_close();self.thread.join(2)
        self.assertFalse(self.thread.is_alive());self.assertEqual(self.server.errors,[])
        self.assertTrue(all(x.closed for x in self.transports))

    def clock(self):return self.now

    def compile(self,actual,function):
        policy=function.context_policy;policy['budget'].update(prompt_tokens=100000,input_tokens=100000,total_tokens=120000)
        return build_context(actual,replace(function,context_json=json.dumps(policy)))

    async def no_wait(self,seconds):await asyncio.sleep(0)

    def worker(self,*,diagnostic=True):
        options={'profile':ModelProfile(wire.KEY),'gateway':self.gateway,'context_compiler':self.compile,
            'compatibility_check':lambda *args:True,'sleep':self.no_wait} if diagnostic else None
        worker=GuideWorker(self.database,catalog=self.catalog,clock=self.clock,orchestrator_options=options)
        self.workers.append(worker);return worker

    def create(self,executor,key=creation.KEY):
        return create_requirement(executor,creation.CreateRequirementTests().payload(idempotency_key=key),catalog=self.catalog,clock=self.clock)

    def row(self,table,identity):
        with self.database.transaction() as connection:return dict(connection.execute('SELECT * FROM '+table+' WHERE id=?',(identity,)).fetchone())

    def queue(self,*,behavior=None):
        value={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'真实后台任务结果','confirmed_fact_patches':[]}
        self.queue_output(value,behavior=behavior)

    def queue_output(self,value,*,behavior=None):
        envelope=wire.envelope(choices=[{'message':{'role':'assistant','content':json.dumps(value,ensure_ascii=False)},'finish_reason':'stop'}])
        self.server.responses.append((200,json.dumps(envelope,ensure_ascii=False).encode(),{},behavior))

    def activate(self,worker,created):
        identity=created['data']['guide_run_id'];requirement=created['data']['requirement']['id']
        result=commands.cancel_guide_run(worker.executor,{'guide_run_id':identity,'idempotency_key':creation.OTHER},clock=self.clock)
        self.assertEqual(result['code'],'GUIDE_CANCELLED')
        result=complete_initialization(worker.executor,{'requirement_id':requirement,'expected_content_version':1,'idempotency_key':creation.OTHER},catalog=self.catalog,clock=self.clock)
        self.assertEqual(result['code'],'INITIALIZATION_COMPLETED')
        return requirement

    def accept(self,worker,requirement,action):
        result=commands.create_guide_run(worker.executor,{'requirement_id':requirement,'expected_content_version':1,
            'action_type':action,'instruction':'实际后台操作','scope_type':'DOCUMENT','source_type':'USER_INSTRUCTION',
            'idempotency_key':creation.OTHER},catalog=self.catalog,clock=self.clock)
        self.assertEqual(result['code'],'GUIDE_ACCEPTED',result);return result

    async def settle(self,worker):
        due=monotonic()+10
        while worker.live_run_ids and monotonic()<due:await asyncio.sleep(0.01)
        self.assertEqual(worker.live_run_ids,frozenset())
        await asyncio.sleep(0)

    async def test_startup_recovers_committed_orphan_run_and_old_claim_before_accepting_without_resend(self):
        with ProcessLock.for_database(self.database.path) as lock:
            executor=Idempotency(self.database,lock,clock=self.clock);created=self.create(executor)
            executor.claim(Scope('APP-REQ-CMD-C02','Requirement:1',creation.OTHER),{'diagnostic':True})
        worker=self.worker();self.assertFalse(worker.accepting)
        recovered=await worker.start();identity=created['data']['guide_run_id']
        self.assertEqual(recovered['data']['recovered_run_ids'],[identity]);self.assertTrue(worker.accepting)
        self.assertEqual(self.row('guide_runs',identity)['error_code'],'INTERRUPTED')
        self.assertEqual(self.row('requirements',1)['document_work_state'],'IDLE')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM idempotency_records WHERE status='PROCESSING'").fetchone()[0],0)
            self.assertEqual(connection.execute("SELECT count(*) FROM idempotency_records WHERE status='SUCCEEDED'").fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],0)
        self.assertEqual(self.observed,[]);self.assertEqual(list(worker.events)[0]['cleared_claims'],1)

    async def test_second_real_process_lock_owner_refused_preserves_first_worker(self):
        first=self.worker();await first.start();second=self.worker()
        with self.assertRaises(ProcessAlreadyRunning):await second.start()
        first.process_lock.assert_owned();self.assertTrue(first.accepting);self.assertFalse(second.accepting)

    async def test_inconsistent_startup_refuses_acceptance_and_releases_actual_lock_without_repair_guess(self):
        with ProcessLock.for_database(self.database.path) as lock:
            created=self.create(Idempotency(self.database,lock,clock=self.clock))
        with self.database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET active_operation_id=99999 WHERE id=?",(created['data']['requirement']['id'],))
        worker=self.worker()
        with self.assertRaises(WorkerStartupFailed) as error:await worker.start()
        self.assertEqual(error.exception.code,'WORK_STATE_INCONSISTENT');self.assertFalse(worker.accepting)
        self.assertEqual(self.row('guide_runs',created['data']['guide_run_id'])['status'],'RUNNING')
        with ProcessLock.for_database(self.database.path):pass
        self.assertEqual(self.observed,[])

    async def test_serial_monitor_missed_scan_runs_once_immediately_then_plans_from_actual_start(self):
        worker=self.worker();worker.accepting=True;time=[0.0];scans=[];waits=[]
        async def sleep(seconds):waits.append(seconds);time[0]+=seconds
        async def scan(*,scheduled_at):
            scans.append((time[0],scheduled_at))
            if len(scans)==1:time[0]+=45
            else:worker.accepting=False
        with patch('backend.app.guide.worker.monotonic',side_effect=lambda:time[0]),patch('backend.app.guide.worker.asyncio.sleep',new=sleep),patch.object(worker,'check_no_progress',new=scan):
            await worker._monitor_loop()
        self.assertEqual(scans,[(30,30),(75,60)]);self.assertEqual(waits,[30,0])

    async def test_actual_acceptance_dispatch_is_deduplicated_and_completes_via_orch_c07_once(self):
        worker=self.worker();await worker.start();created=self.create(worker.executor);identity=created['data']['guide_run_id']
        self.assertEqual(self.observed,[]);self.queue()
        self.assertTrue(worker.dispatch(identity));self.assertFalse(worker.dispatch(identity))
        await self.settle(worker)
        self.assertEqual(self.row('guide_runs',identity)['status'],'COMPLETED');self.assertEqual(len(self.observed),1)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],1)
            self.assertEqual(connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0],1)
        self.assertTrue(any(x.get('code')=='AI_FINISHED' for x in worker.events))

    async def test_real_http_dispatch_occurs_before_response_projection_failure_and_original_key_replays(self):
        worker=self.worker();worker.clock=lambda:datetime.now(timezone.utc)
        await worker.start();self.queue()
        app=FastAPI();app.include_router(req_router);app.state.walle_runtime=HttpRuntime(self.database,self.catalog,worker.executor,worker)
        payload=creation.CreateRequirementTests().payload();payload.pop('idempotency_key')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            with patch.object(CreateRequirementResponse,'project',side_effect=ValueError('controlled projection')):
                failed=await client.post('/api/v1/requirements',json=payload,headers={'Idempotency-Key':creation.KEY})
            self.assertEqual(failed.status_code,500)
            await self.settle(worker)
            repeated=await client.post('/api/v1/requirements',json=payload,headers={'Idempotency-Key':creation.KEY})
            self.assertEqual(repeated.status_code,201,repeated.text)
            await self.settle(worker)
        self.assertEqual(len(self.observed),1)
        self.assertEqual(self.row('guide_runs',1)['status'],'COMPLETED')

    async def test_dispatch_failure_keeps_original_committed_http_acceptance_for_recovery(self):
        worker=self.worker();await worker.start()
        created=self.create(worker.executor)
        with patch.object(worker,'dispatch',side_effect=RuntimeError('unsafe diagnostic exception')):await worker.after_commit(created)
        identity=created['data']['guide_run_id'];self.assertEqual(self.row('guide_runs',identity)['status'],'RUNNING')
        self.assertEqual(self.observed,[]);self.assertEqual(list(worker.events)[-1],{'event':'DISPATCH_EXCEPTION'})
        self.now+=timedelta(minutes=15);recovered=await worker.check_no_progress()
        self.assertEqual(recovered['data']['recovered_run_ids'],[identity]);self.assertEqual(self.row('guide_runs',identity)['error_code'],'EXECUTION_TIMEOUT')

    async def test_monitor_prunes_only_expired_actual_raw_audit_preserving_long_term_request_and_trust(self):
        worker=self.worker();await worker.start();created=self.create(worker.executor)
        self.queue();await worker.after_commit(created);await self.settle(worker)
        with self.database.transaction() as connection:before=dict(connection.execute('SELECT * FROM llm_uses').fetchone())
        self.assertIsNotNone(before['raw_response_json']);self.assertIsNotNone(before['trusted_output_json'])
        self.now+=timedelta(days=30);await worker.check_no_progress()
        self.assertIsNotNone(self.row('llm_uses',before['id'])['raw_response_json'])
        self.now+=timedelta(milliseconds=1);await worker.check_no_progress()
        after=self.row('llm_uses',before['id'])
        self.assertIsNone(after['raw_response_json']);self.assertIsNone(after['parsed_output_json'])
        for key,value in before.items():
            if key not in ('raw_response_json','parsed_output_json'):self.assertEqual(after[key],value)
        self.assertEqual(list(worker.events)[-1],{'event':'AUDIT_PRUNED','count':1})

    async def test_close_preserves_native_waiting_run_manual_draft_and_pending_batch_and_no_resend(self):
        worker=self.worker();await worker.start()
        first=self.create(worker.executor);req=self.activate(worker,first);ask=self.accept(worker,req,'ASK')
        self.queue_output({'schema_version':1,'response_type':'CLARIFY_TEXT','message':'请实际补充'})
        await worker.after_commit(ask);await self.settle(worker)
        waiting_id=ask['data']['guide_run']['id'];waiting=self.row('guide_runs',waiting_id)
        self.assertEqual(waiting['status'],'WAITING_USER')
        second=self.create(worker.executor,'00000000-0000-4000-8000-00000000003a')
        second_id=second['data']['requirement']['id'];self.activate(worker,second)
        draft=start_manual_draft(worker.executor,{'requirement_id':second_id,'expected_content_version':1,'idempotency_key':creation.KEY},catalog=self.catalog,clock=self.clock)
        self.assertEqual(draft['code'],'DRAFT_STARTED',draft)
        third=self.create(worker.executor,'00000000-0000-4000-8000-00000000003b')
        third_id=self.activate(worker,third);modify=self.accept(worker,third_id,'MODIFY')
        current=self.row('requirement_documents',third['data']['current_document_id'])
        with self.database.transaction() as connection:
            snapshot=validate_snapshot(current['markdown_content'],json.loads(current['block_state_json']),DocumentSources(connection,third_id,self.catalog))
        self.queue_output({'schema_version':1,'response_type':'SUGGESTIONS','message':'实际建议','title':'修改','summary':'摘要','suggestions':[suggestion_patch(snapshot,3)]})
        await worker.after_commit(modify);await self.settle(worker)
        batch_id=self.row('requirements',third_id)['active_operation_id'];batch=self.row('suggestion_batches',batch_id)
        self.assertEqual(batch['status'],'PENDING')
        before={table:[] for table in ('requirements','requirement_documents','suggestion_batches','suggestions')}
        with self.database.transaction() as connection:
            for table in before:before[table]=[dict(row) for row in connection.execute('SELECT * FROM '+table+' ORDER BY id')]
        await worker.close()
        self.assertEqual(self.row('guide_runs',waiting_id),waiting)
        with self.database.transaction() as connection:
            for table,value in before.items():self.assertEqual([dict(row) for row in connection.execute('SELECT * FROM '+table+' ORDER BY id')],value)
        restarted=self.worker();await restarted.start();self.assertEqual(self.row('guide_runs',waiting_id),waiting)
        self.assertEqual(self.row('suggestion_batches',batch_id),batch);self.assertEqual(len(self.observed),2)

    async def test_real_no_progress_threshold_does_not_overlap_and_closes_live_tcp_after_timeout(self):
        worker=self.worker();await worker.start();created=self.create(worker.executor);identity=created['data']['guide_run_id']
        self.queue(behavior='hold');worker.dispatch(identity)
        self.assertTrue(await asyncio.to_thread(self.server.entered.wait,3))
        self.now+=timedelta(minutes=14,seconds=59)
        check=await worker.check_no_progress();self.assertEqual(check['data']['recovered_run_ids'],[])
        await worker._scan_lock.acquire()
        try:self.assertIsNone(await worker.check_no_progress())
        finally:worker._scan_lock.release()
        self.now+=timedelta(seconds=1);check=await worker.check_no_progress(scheduled_at=monotonic()-2)
        self.assertEqual(check['data']['recovered_run_ids'],[identity]);await self.settle(worker)
        self.assertTrue(await asyncio.to_thread(self.server.peer_closed.wait,3))
        self.assertEqual(self.row('guide_runs',identity)['error_code'],'EXECUTION_TIMEOUT')
        scans=[x for x in worker.events if x['event']=='SCAN_RETURNED'];self.assertGreaterEqual(scans[-1]['delay_seconds'],2)
        self.assertEqual((MONITOR_SECONDS,SHUTDOWN_GRACE_SECONDS),(30,10))

    async def test_real_shutdown_grace_waits_at_most_ten_seconds_then_interrupts_running_request(self):
        worker=self.worker();await worker.start();created=self.create(worker.executor);identity=created['data']['guide_run_id']
        self.server.hold_timeout=30
        self.queue(behavior='hold');worker.dispatch(identity)
        self.assertTrue(await asyncio.to_thread(self.server.entered.wait,3))
        result=await worker.close();await asyncio.sleep(0)
        self.assertFalse(worker.accepting);self.assertFalse(worker.started)
        self.assertIn(result['code'],('RECOVERED','RECOVERY_NO_CHANGE'))
        self.assertEqual(self.row('guide_runs',identity)['status'],'FAILED')
        self.assertEqual(self.row('guide_runs',identity)['error_code'],'INTERRUPTED')
        drained=[x for x in worker.events if x['event']=='DRAINED'][-1]
        self.assertLess(drained['wait_seconds'],10.6)
        self.assertGreaterEqual(drained['wait_seconds'],9.9)
        self.assertEqual(drained['remaining'],1)
        self.assertTrue(await asyncio.to_thread(self.server.peer_closed.wait,3))
        await self.settle(worker)
        with ProcessLock.for_database(self.database.path):pass

    async def test_shutdown_fences_actual_c07_inflight_sql_then_startup_recovers_without_late_commit(self):
        from backend.app.guide import result_persistence
        worker=self.worker();await worker.start();created=self.create(worker.executor)
        identity=created['data']['guide_run_id'];entered=Event();resume=Event()
        original=result_persistence.validate_business_output
        def slow(*args,**kwargs):
            entered.set()
            if not resume.wait(25):raise ValueError('controlled native stage was not resumed')
            return original(*args,**kwargs)
        self.queue()
        with patch.object(result_persistence,'validate_business_output',side_effect=slow):
            await worker.after_commit(created)
            self.assertTrue(await asyncio.to_thread(entered.wait,3))
            try:
                closed=await worker.close()
                # The actual C07 writer still holds BEGIN IMMEDIATE. Recovery
                # cannot prove a write and must leave it for the next startup.
                self.assertEqual(closed['code'],'STORAGE_UNAVAILABLE',closed)
                with ProcessLock.for_database(self.database.path):pass
            finally:resume.set()
            await self.settle(worker)
        self.assertEqual(self.row('guide_runs',identity)['status'],'RUNNING')
        self.assertNotEqual(self.row('guide_runs',identity)['current_step'],'PERSISTING')
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM conversation_messages WHERE role='ASSISTANT'").fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT validation_status FROM llm_uses').fetchone()[0],'SUCCEEDED')
        self.assertEqual(len(self.observed),1)
        restarted=self.worker();recovery=await restarted.start()
        self.assertEqual(recovery['data']['recovered_run_ids'],[identity])
        self.assertEqual(self.row('guide_runs',identity)['error_code'],'INTERRUPTED')
        self.assertEqual(len(self.observed),1)


if __name__=='__main__':unittest.main()
