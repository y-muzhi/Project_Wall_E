"""Real worker count cancellation/restart and retention; two loopback providers."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from backend.app.guide import commands
from backend.app.guide.worker import GuideWorker
from backend.app.infrastructure.counting_journal import CountingJournal
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.commands import create_requirement
from backend.tests.requirements import test_create_requirement as creation
from backend.tests.infrastructure import test_model_gateway as chat_tcp
from backend.tests.infrastructure import test_tokenization as count_tcp


class CountedWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='walle-count-worker-');self.addCleanup(self.directory.cleanup)
        self.database=Database(Path(self.directory.name)/'actual.sqlite');self.database.initialize();self.now=creation.INSTANT
        self.count=count_tcp.TokenizationTests();self.count.setUp();self.addCleanup(self.count.tearDown)
        envelope=count_tcp.envelope();envelope['data']=[{**deepcopy(envelope['data'][0]),'index':index} for index in range(6)];self.count.server.body=json.dumps(envelope).encode()
        self.chat=chat_tcp.ControlledServer();self.thread=Thread(target=self.chat.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start()
        self.observed,self.transports,self.workers=[],[],[]
        def factory():
            transport=chat_tcp.ForwardTransport(self.chat.server_port,self.observed);self.transports.append(transport);return transport
        self.gateway=ModelGateway(transport_factory=factory)

    async def asyncTearDown(self):
        for worker in self.workers:
            if worker.started:await worker.close()
        self.chat.shutdown();self.chat.server_close();self.thread.join(3)
        self.assertFalse(self.thread.is_alive());self.assertEqual(self.chat.errors,[])
        self.assertTrue(all(item.closed for item in self.transports));self.assertTrue(all(item.closed for item in self.count.transports))

    async def start(self):
        worker=GuideWorker(self.database,catalog=ResourceCatalog(),clock=lambda:self.now,orchestrator_options={
            'profile':ModelProfile(chat_tcp.KEY),'gateway':self.gateway,'compatibility_check':lambda *args:True,
            'counting_counter':self.count.gateway,'counting_compatibility_check':lambda *args:True})
        self.workers.append(worker);await worker.start();return worker

    async def create(self,worker):
        result=create_requirement(worker.executor,{'title':'计数后台专项','requirement_type':'NEW','template_key':'new-requirement','template_version':'v1',
            'initial_idea':'实际后台计数😀','initialization_mode':'DESIGN','idempotency_key':creation.KEY},catalog=worker.catalog,clock=lambda:self.now)
        self.assertEqual(result['code'],'CREATED',result);await worker.after_commit(result);return result['data']['guide_run_id']

    async def settled(self,worker):
        async def wait():
            while worker.live_run_ids:await asyncio.sleep(0.005)
        await asyncio.wait_for(wait(),5)

    async def test_actual_worker_logical_cancel_closes_count_socket_and_restart_never_replays_prepared_file(self):
        self.count.server.hold=True;worker=await self.start();identity=await self.create(worker)
        self.assertTrue(await asyncio.to_thread(self.count.server.entered.wait,3));self.now+=timedelta(seconds=1)
        cancelled=commands.cancel_guide_run(worker.executor,{'guide_run_id':identity,'idempotency_key':creation.OTHER},clock=lambda:self.now)
        self.assertEqual(cancelled['code'],'GUIDE_CANCELLED',cancelled);await worker.after_commit(cancelled);await self.settled(worker)
        self.assertTrue(await asyncio.to_thread(self.count.server.peer_closed.wait,3))
        journal=CountingJournal(self.database,worker.process_lock)
        self.assertEqual(len(list(journal.root.glob('*.prepared.json'))),1);self.assertEqual(list(journal.root.glob('*.finished.json')),[])
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT status FROM guide_runs WHERE id=?',(identity,)).fetchone()[0],'CANCELLED')
            self.assertEqual(connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0],0)
        await worker.close();restarted=await self.start();self.assertEqual(len(self.count.server.receipts),1);self.assertEqual(self.chat.receipts,[])
        self.assertEqual(restarted.live_run_ids,frozenset());self.assertEqual(list(journal.root.glob('*.finished.json')),[])

    async def test_actual_worker_completion_and_monitor_prune_count_raw_preserve_chat_snapshot_summary(self):
        value={'schema_version':1,'response_type':'INITIALIZE_TEXT','message':'隔离后台完成','confirmed_fact_patches':[]}
        raw=chat_tcp.envelope(choices=[{'message':{'role':'assistant','content':json.dumps(value,ensure_ascii=False)},'finish_reason':'stop'}])
        self.chat.responses.append((200,json.dumps(raw).encode(),{},None))
        worker=await self.start();identity=await self.create(worker);await self.settled(worker)
        with self.database.transaction() as connection:
            self.assertEqual(connection.execute('SELECT status FROM guide_runs WHERE id=?',(identity,)).fetchone()[0],'COMPLETED')
            row=dict(connection.execute('SELECT * FROM llm_uses').fetchone());snapshot=row['request_snapshot_json']
        journal=CountingJournal(self.database,worker.process_lock);files=list(journal.root.glob('*.finished.json'));self.assertEqual(len(files),1)
        original=json.loads(files[0].read_bytes());self.assertIn('response',original['measurement'])
        self.now+=timedelta(days=31);await worker.check_no_progress()
        updated=json.loads(files[0].read_bytes());self.assertNotIn('response',updated['measurement']);self.assertIn('response_sha256',updated['measurement'])
        with self.database.transaction() as connection:
            row=dict(connection.execute('SELECT * FROM llm_uses').fetchone());self.assertEqual(row['request_snapshot_json'],snapshot)
            self.assertIsNone(row['raw_response_json']);self.assertEqual(row['validation_status'],'SUCCEEDED')
        self.assertEqual(len(self.count.server.receipts),1);self.assertEqual(len(self.chat.receipts),1)
        self.assertIn({'event':'COUNT_RAW_PRUNED','count':1},list(worker.events))
