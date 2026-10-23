"""Owned temporary worker startup and native lease retirement; no user service."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from backend.tests.requirements.test_v15_foundation import tmp_path, setup, create
from backend.tests.documents.test_v15_documents import workspace
from backend.tests.guide.test_v15_recovery import prepare
from backend.tests.guide.test_v15_execution import PROFILE
from backend.app.guide.worker import GuideWorker
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.execution_lease import ExecutionLease, ExecutionRetired, LeasedDatabase
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog


def test_temporary_worker_start_recovers_durable_response_without_auto_dispatch_and_close_releases_os_lock(tmp_path, monkeypatch):
    database = Database(tmp_path/'worker.sqlite');database.initialize();catalog = ResourceCatalog()
    with ProcessLock.for_database(database.path) as lock:
        executor = Idempotency(database, lock);assert create(executor)['code'] == 'CREATED'
        at = prepare((database, executor, catalog), monkeypatch)
    def forbidden(*args, **kwargs): raise AssertionError('Startup/close must not dispatch provider work')
    async def scenario():
        worker = GuideWorker(database, catalog=catalog, clock=lambda: at+timedelta(seconds=10), orchestrator_options={
            'profile': PROFILE, 'gateway': forbidden, 'counting_counter': forbidden})
        try:
            result = await worker.start()
            assert result['code'] == 'RECOVERED' and result['data']['recovered_run_ids'] == [1]
            assert worker.started and worker.accepting and not worker.live_run_ids
        finally:
            await worker.close()
        assert not worker.started and not worker.accepting
    asyncio.run(scenario())
    with ProcessLock.for_database(database.path):
        with database.transaction() as connection:
            assert connection.execute('SELECT status FROM guide_runs').fetchone()[0] == 'COMPLETED'
            assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 1
            assert connection.execute('SELECT count(*) FROM revisions').fetchone()[0] == 1


def test_lease_retirement_wins_against_uncommitted_native_write_and_rolls_back_actual_transaction(workspace):
    lease = ExecutionLease();database = LeasedDatabase(workspace[0], lease);entered = Event();continue_stage = Event()
    with workspace[0].transaction() as connection: title = connection.execute('SELECT title FROM requirements').fetchone()[0]
    def late_stage():
        with database.transaction(write=True) as connection:
            connection.execute("UPDATE requirements SET title='late retired update' WHERE id=1")
            entered.set();assert continue_stage.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(late_stage)
        try:
            assert entered.wait(5);lease.retire()
        finally:
            continue_stage.set()
        with pytest.raises(ExecutionRetired): future.result(timeout=5)
    with workspace[0].transaction() as connection: assert connection.execute('SELECT title FROM requirements').fetchone()[0] == title


def test_committed_native_write_remains_a_fact_but_retired_lease_cannot_start_a_following_stage(workspace):
    lease = ExecutionLease();database = LeasedDatabase(workspace[0], lease)
    with database.transaction(write=True) as connection:
        connection.execute("UPDATE requirements SET title='committed stage' WHERE id=1")
    lease.retire()
    with pytest.raises(ExecutionRetired):
        with database.transaction(write=True): pass
    with workspace[0].transaction() as connection:
        assert connection.execute('SELECT title FROM requirements').fetchone()[0] == 'committed stage'
