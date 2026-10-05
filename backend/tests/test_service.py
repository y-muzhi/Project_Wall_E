"""Native production factory/lifespan; real DB, no fake application responses."""
import asyncio
from pathlib import Path
import tempfile
from threading import Event
from time import monotonic
import unittest
from unittest.mock import patch

import httpx

from backend.app.service import create_app
from backend.app.infrastructure.database import Database, StorageUnavailable
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock, ProcessAlreadyRunning
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.requirements.commands import create_requirement
from backend.app.requirements import commands
from backend.tests.requirements import test_create_requirement as creation


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='walle-service-real-');self.addCleanup(self.directory.cleanup)
        self.database=Database(Path(self.directory.name)/'actual.sqlite');self.database.initialize()
        self.catalog=ResourceCatalog();self.app=create_app(database=self.database,catalog=self.catalog)

    def payload(self):
        value=creation.CreateRequirementTests().payload();value.pop('idempotency_key');return value

    async def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://actual-service')

    async def test_before_startup_no_acceptance_then_actual_missing_config_run_failure_remains_readable(self):
        async with await self.client() as client:
            initial=await client.get('/api/v1/requirements')
            self.assertEqual(initial.status_code,503);self.assertEqual(initial.json()['error']['code'],'STORAGE_UNAVAILABLE')
            with patch.dict('os.environ',{},clear=True):
                async with self.app.router.lifespan_context(self.app):
                    response=await client.post('/api/v1/requirements',json=self.payload(),headers={'Idempotency-Key':creation.KEY})
                    self.assertEqual(response.status_code,201,response.text);identity=response.json()['data']['guide_run_id']
                    due=monotonic()+5
                    while monotonic()<due:
                        status=await client.get('/api/v1/guide-runs/'+str(identity))
                        self.assertEqual(status.status_code,200,status.text)
                        if status.json()['data']['status']=='FAILED':break
                        await asyncio.sleep(0.01)
                    self.assertEqual(status.json()['data']['status'],'FAILED');self.assertEqual(status.json()['data']['error_code'],'CONFIG_INVALID')
                    for url in ('/api/v1/requirements','/api/v1/requirements/1','/api/v1/requirements/1/current-document',
                        '/api/v1/requirements/1/messages','/api/v1/requirements/1/comment-index'):
                        read=await client.get(url);self.assertEqual(read.status_code,200,(url,read.text))
                    replay=await client.post('/api/v1/requirements',json=self.payload(),headers={'Idempotency-Key':creation.KEY})
                    self.assertEqual(replay.status_code,201);self.assertEqual(replay.json()['data'],response.json()['data'])
                    self.assertNotEqual(replay.json()['meta']['request_id'],response.json()['meta']['request_id'])
            closed=await client.get('/api/v1/requirements');self.assertEqual(closed.status_code,503)
        with ProcessLock.for_database(self.database.path):pass

    async def test_startup_finishes_actual_recovery_before_first_http_and_second_instance_refuses(self):
        with ProcessLock.for_database(self.database.path) as lock:
            created=create_requirement(Idempotency(self.database,lock),creation.CreateRequirementTests().payload(),catalog=self.catalog)
        identity=created['data']['guide_run_id']
        async with self.app.router.lifespan_context(self.app):
            async with await self.client() as client:
                read=await client.get('/api/v1/guide-runs/'+str(identity))
                self.assertEqual(read.status_code,200);self.assertEqual(read.json()['data']['error_code'],'INTERRUPTED')
            second=create_app(database=self.database,catalog=self.catalog)
            with self.assertRaises(ProcessAlreadyRunning):
                async with second.router.lifespan_context(second):pass
            self.app.state.walle_worker.process_lock.assert_owned()

    async def test_missing_database_refuses_startup_without_creating_it(self):
        missing=Database(Path(self.directory.name)/'missing.sqlite')
        app=create_app(database=missing,catalog=self.catalog)
        with self.assertRaises(StorageUnavailable):
            async with app.router.lifespan_context(app):pass
        self.assertFalse(missing.path.exists())

    async def test_shutdown_retires_actual_http_write_thread_before_lock_release_no_late_commit(self):
        entered=Event();resume=Event();request_task=None;context=self.app.router.lifespan_context(self.app)
        await context.__aenter__()
        worker=self.app.state.walle_worker
        try:
            created=create_requirement(worker.executor,creation.CreateRequirementTests().payload(),catalog=self.catalog)
            identity=created['data']['requirement']['id']
            # Actual command infrastructure writes on the HTTP fence; a slow
            # native phase is explicit diagnostic injection, not fake success.
            def slow(database,payload):
                with database.transaction(write=True) as connection:
                    connection.execute("UPDATE requirements SET title='late HTTP title' WHERE id=?",(identity,))
                    entered.set()
                    if not resume.wait(10):raise ValueError('controlled phase not resumed')
                raise AssertionError('retired HTTP transaction must not commit')
            async with await self.client() as client:
                with patch.object(commands,'update_requirement',side_effect=slow):
                    request_task=asyncio.create_task(client.patch('/api/v1/requirements/'+str(identity),json={'title':'late HTTP title'}))
                    self.assertTrue(await asyncio.to_thread(entered.wait,3))
                    closing=asyncio.create_task(context.__aexit__(None,None,None))
                    due=monotonic()+3
                    while not self.app.state.walle_http_lease.retired and monotonic()<due:await asyncio.sleep(0.01)
                    self.assertTrue(self.app.state.walle_http_lease.retired)
                    # Middleware rejects a new request while shutdown is active.
                    self.assertEqual((await client.get('/api/v1/requirements')).status_code,503)
                    resume.set();response=await request_task;await closing
                    self.assertEqual(response.status_code,503,response.text)
            with self.database.transaction() as connection:
                self.assertEqual(connection.execute('SELECT title FROM requirements WHERE id=?',(identity,)).fetchone()[0],'需求😀')
            with ProcessLock.for_database(self.database.path):pass
        finally:
            resume.set()
            if worker.started:await context.__aexit__(None,None,None)


if __name__=='__main__':unittest.main()
