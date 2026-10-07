"""TC-E2E-07 actual lifespan, C09 and native file recovery.

Only explicit legacy occupancy fixtures and a post-commit orphan acceptance
are inserted. Actual HTTP, recovery, locking, audits and business producers run
unchanged. Synthetic local count/Chat do not prove paid Provider compatibility.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import socket
from threading import Event
from time import monotonic
from unittest.mock import patch
from uuid import uuid4

import httpx
import uvicorn
from backend.app.service import create_app
from backend.app.guide import worker as worker_module
from backend.app.guide.commands import recover_runs
from backend.app.guide.worker import GuideWorker, WorkerStartupFailed, MONITOR_SECONDS, SHUTDOWN_GRACE_SECONDS
from backend.app.infrastructure.idempotency import Idempotency, Scope
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.message_repository import MessageRepository
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.requirements.commands import create_requirement
from backend.app.shared.time import utc_milliseconds
from backend.tests.messages.test_queries import cards_fixture


def helper(name):
    path = Path(__file__).with_name('product-' + name + '-flow.py')
    spec = importlib.util.spec_from_file_location('recovery_' + name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def row(database, table, identity):
    with database.transaction() as connection:
        return dict(connection.execute('SELECT * FROM ' + table + ' WHERE id=?', (identity,)).fetchone())


@asynccontextmanager
async def restarted(checker, database, previous, *, pause=False):
    """Use another actual create_app and uvicorn on the same isolated file."""
    catalog = previous.catalog
    def factory(db, resources):
        return GuideWorker(db, catalog=resources, orchestrator_options=previous._options)
    application = create_app(database=database, catalog=catalog, worker_factory=factory)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(); listener.setblocking(False)
    server = uvicorn.Server(uvicorn.Config(application, log_level='error', access_log=False, lifespan='on'))
    entered, release = Event(), Event()
    original = worker_module.recover_runs
    def forward(*args, **kwargs):
        if args[1]['recovery_reason'] == 'STARTUP':
            entered.set()
            if not release.wait(10): raise AssertionError('Startup recovery barrier timed out')
        return original(*args, **kwargs)
    try:
        with patch.object(worker_module, 'recover_runs', new=forward) if pause else patch.object(worker_module, 'recover_runs', new=original):
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            if pause:
                checker.check('Actual startup reaches C09 before HTTP admission', await asyncio.to_thread(entered.wait, 5)
                              and not server.started and getattr(application.state, 'walle_runtime', None) is None)
                # Independent contender must be denied by the real OS lock.
                from backend.app.infrastructure.process_lock import ProcessAlreadyRunning
                refused = False
                try: ProcessLock.for_database(database.path).acquire()
                except ProcessAlreadyRunning: refused = True
                checker.check('Concurrent process cannot acquire lock while startup recovery is paused', refused)
                release.set()
            due = monotonic() + 10
            while not server.started and not serving.done() and monotonic() < due: await asyncio.sleep(0.01)
            checker.check('Restarted actual lifespan admits only after successful recovery', server.started and not serving.done())
            async with httpx.AsyncClient(base_url='http://127.0.0.1:' + str(listener.getsockname()[1]),
                                         trust_env=False, timeout=10) as client:
                yield application, client
    finally:
        release.set(); server.should_exit = True
        if 'serving' in locals(): await asyncio.wait_for(serving, 15)
        listener.close()


async def stop_owner(checker, app):
    worker = app.state.walle_worker
    await helper('gates').settle(worker)
    await asyncio.to_thread(app.state.walle_http_lease.retire)
    result = await worker.close()
    checker.check('Old lifecycle closes HTTP lease and releases native owner', not worker.started and not worker.accepting)
    return worker, result


async def timeout_flow(checker, client, database, req, current, chat, counter, app):
    worker = app.state.walle_worker
    await helper('gates').settle(worker)
    chat.entered.clear(); chat.peer_closed.clear(); chat.hold_timeout = 15
    checker.queue_output(chat, {'schema_version': 1, 'response_type': 'ANSWER', 'message': '迟到答案不得采用。'})
    status, body, headers, unused = chat.responses[-1]
    chat.responses[-1] = (status, body, headers, 'hold')
    accepted = (await checker.request(client, 'POST', f'/requirements/{req}/guide-runs', status=202,
        body={'expected_version': current['content_version'], 'action_type': 'ASK',
              'instruction': '验证真实监测边界。', 'scope_type': 'DOCUMENT', 'source_type': 'USER_INSTRUCTION'}, key=str(uuid4())))['data']
    identity = accepted['guide_run']['id']
    checker.check('Real Chat is in flight with native RUNNING audit', await asyncio.to_thread(chat.entered.wait, 5)
                  and identity in worker.live_run_ids)
    progress = row(database, 'guide_runs', identity)['updated_at']
    t0 = datetime.fromisoformat(progress[:-1] + '+00:00')
    before = checker.database_facts(database); network = (len(chat.receipts), len(counter.server.receipts))
    live_recovery = await asyncio.to_thread(recover_runs, database,
        {'recovery_reason': 'STARTUP', 'live_run_ids': set(worker.live_run_ids), 'operation_time': utc_milliseconds(t0 + timedelta(hours=2))},
        process_lock=worker.process_lock)
    checker.check('Valid live ownership prevents STARTUP interruption even after two hours',
                  live_recovery['code'] == 'RECOVERY_NO_CHANGE' and before == checker.database_facts(database))
    worker.clock = lambda: t0 + timedelta(seconds=899)
    first = await worker.check_no_progress()
    checker.check('14:59 preserves every actual stored row and in-flight task', first['code'] == 'RECOVERY_NO_CHANGE'
                  and before == checker.database_facts(database) and identity in worker.live_run_ids)
    await worker._scan_lock.acquire()
    try:
        checker.check('Overlapping actual monitor scan coalesces without another transaction', await worker.check_no_progress() is None
                      and before == checker.database_facts(database))
    finally: worker._scan_lock.release()
    worker.clock = lambda: t0 + timedelta(seconds=900)
    second = await worker.check_no_progress(scheduled_at=monotonic() - 2)
    checker.check('15:00 recovers exactly the owned live run', second['code'] == 'RECOVERED'
                  and second['data']['recovered_run_ids'] == [identity] and second['data']['repaired_requirement_ids'] == [req])
    await helper('gates').settle(worker)
    checker.check('Committed timeout closes the real in-flight socket', await asyncio.to_thread(chat.peer_closed.wait, 3))
    actual = (await checker.request(client, 'GET', f'/guide-runs/{identity}'))['data']
    root = (await checker.request(client, 'GET', f'/requirements/{req}'))['data']
    with database.transaction() as connection:
        audits = [dict(r) for r in connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=?', (identity,))]
        assistants = connection.execute("SELECT count(*) FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT'", (identity,)).fetchone()[0]
    checker.check('Timeout terminal/audit/error and occupancy commit together without late adoption',
                  actual['status'] == 'FAILED' and row(database, 'guide_runs', identity)['error_code'] == 'EXECUTION_TIMEOUT'
                  and root['document_work_state'] == 'IDLE' and root['active_operation_id'] is None and assistants == 0
                  and len(audits) == 1 and audits[0]['call_status'] == 'FAILED' and audits[0]['input_tokens'] is None
                  and audits[0]['trusted_output_json'] is None)
    checker.check('No recovery resend and entire CURRENT unchanged', network == (len(chat.receipts), len(counter.server.receipts))
                  and (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data'] == current)
    terminal = checker.database_facts(database)
    repeat = await worker.check_no_progress()
    checker.check('Repeated timeout scan preserves ended_at and all terminal facts', repeat['code'] == 'RECOVERY_NO_CHANGE'
                  and terminal == checker.database_facts(database))
    scans = [event for event in worker.events if event['event'] == 'SCAN_RETURNED']
    checker.check('Monitor reports actual delay and does not claim a maximum 15-minute completion bound',
                  scans[-2]['delay_seconds'] >= 2 and (MONITOR_SECONDS, SHUTDOWN_GRACE_SECONDS) == (30, 10))
    checker.record['timeout_progress_t0'] = progress; checker.record['monitor_events'] = list(worker.events)
    checker.record['timeout_audits'] = audits


async def keep_and_orphan(checker, client, database, req, current, chat, counter, app):
    query = helper('query')
    from backend.app.guide.output_evidence import card_text
    cards = cards_fixture(); cards['cards'][0]['related_spec_context'] = []
    waiting = await query.guide(checker, client, chat, req, current['content_version'], 'ASK',
        {'schema_version': 1, 'response_type': 'CLARIFY_CARDS', 'message': card_text(cards), 'cards': cards})
    manual_req = await query.create(checker, client, chat, title='重启保留人工草稿')
    await checker.request(client, 'POST', f'/requirements/{manual_req}/manual-draft', status=201,
                          body={'expected_version': 1}, key=str(uuid4()))
    batch_req = await query.create(checker, client, chat, title='重启保留待审批次')
    await query.guide(checker, client, chat, batch_req, 1, 'MODIFY',
        {'schema_version': 1, 'response_type': 'SUGGESTIONS', 'message': '重启后仍待决定',
         'title': '待审', 'summary': '两个真实候选', 'suggestions': query.patches()})
    protected = checker.database_facts(database); network = (len(chat.receipts), len(counter.server.receipts))
    previous, closed = await stop_owner(checker, app)
    checker.check('Graceful close preserves waiting/cards/draft/pending batch and whole database', protected == checker.database_facts(database))
    # Simulate previous-process disappearance after C01 accepted a request and
    # claimed a second transaction, before dispatch. These are actual native
    # production commands/claim on the same file, not hand-made resource rows.
    key = str(uuid4())
    payload = {'title': '上个进程已接受但未调度', 'requirement_type': 'NEW', 'template_key': 'new-requirement',
               'template_version': 'v1', 'initialization_mode': 'IDEATION', 'initial_idea': '启动恢复不得重发。', 'idempotency_key': key}
    with ProcessLock.for_database(database.path) as owner:
        executor = Idempotency(database, owner)
        accepted = create_requirement(executor, payload, catalog=previous.catalog)
        checker.check('Orphan fixture is a real committed C01 acceptance', accepted['code'] == 'CREATED')
        executor.claim(Scope('APP-REQ-CMD-C02', 'Requirement:' + str(req), str(uuid4())), {'explicit_abandoned_claim': True})
    orphan = accepted['data']['guide_run_id']; orphan_req = accepted['data']['requirement']['id']
    after_orphan_sequences = [line for line in checker.database_facts(database) if line.startswith('INSERT INTO "sequences"')]
    checker.record['orphan_fixture'] = 'Actual C01 acceptance and persisted PROCESSING claim while exclusive previous owner is acquired; owner exits before dispatch'
    async with restarted(checker, database, previous, pause=True) as (new_app, new_client):
        recovery = list(new_app.state.walle_worker.events)[0]
        checker.check('Startup clears only abandoned claim and interrupts orphan before accepting HTTP',
                      recovery['event'] == 'STARTED' and recovery['cleared_claims'] == 1
                      and recovery['recovery']['data']['recovered_run_ids'] == [orphan])
        run = (await checker.request(new_client, 'GET', f'/guide-runs/{orphan}'))['data']
        root = (await checker.request(new_client, 'GET', f'/requirements/{orphan_req}'))['data']
        checker.check('Recovered orphan FAILED/INTERRUPTED and releases root', run['status'] == 'FAILED'
                      and row(database, 'guide_runs', orphan)['error_code'] == 'INTERRUPTED' and root['document_work_state'] == 'IDLE')
        with database.transaction() as connection:
            checker.check('No orphan audit created and no PROCESSING claims remain',
                          connection.execute('SELECT count(*) FROM llm_uses WHERE guide_run_id=?', (orphan,)).fetchone()[0] == 0
                          and connection.execute("SELECT count(*) FROM idempotency_records WHERE status='PROCESSING'").fetchone()[0] == 0)
        after_recovery = checker.database_facts(database)
        checker.check('Waiting/cards/manual/batch and every pre-existing SQL fact survives startup',
                      all(line in after_recovery for line in protected if not line.startswith('INSERT INTO "sequences"')))
        checker.check('Only preceding real orphan acceptance allocates IDs; startup does not allocate any',
                      after_orphan_sequences == [line for line in after_recovery if line.startswith('INSERT INTO "sequences"')])
        checker.check('Waiting run remains WAITING_USER and original cards available',
                      (await checker.request(new_client, 'GET', f'/guide-runs/{waiting["id"]}'))['data'] == waiting
                      and (await checker.request(new_client, 'GET', f'/requirements/{req}/messages'))['data']['items'][-1]['card_state'] == 'AVAILABLE')
        public_payload = {k: v for k, v in payload.items() if k != 'idempotency_key'}
        replay = await checker.request(new_client, 'POST', '/requirements', status=201, body=public_payload, key=key)
        await helper('gates').settle(new_app.state.walle_worker)
        checker.check('Persistent success receipt replays original acceptance after process-owner epoch changes',
                      replay['data'] == accepted['data'] and after_recovery == checker.database_facts(database))
        checker.check('Restart, queries and original-key replay do not resend any model call', network == (len(chat.receipts), len(counter.server.receipts)))
        checker.record['startup_events'] = list(new_app.state.walle_worker.events)


async def occupancy(checker, client, database, req, current, chat, counter, app, branch):
    query = helper('query')
    terminal = await query.guide(checker, client, chat, req, current['content_version'], 'MODIFY',
        {'schema_version': 1, 'response_type': 'SUGGESTIONS', 'message': '真实唯一批次', 'title': '恢复批次',
         'summary': '真实C07两个候选', 'suggestions': query.patches('审批人为部门经理😀。\n')})
    root = (await checker.request(client, 'GET', f'/requirements/{req}'))['data']; batch = root['active_operation_id']
    other = None
    if branch == 'CROSS':
        other_req = await query.create(checker, client, chat, title='跨需求引用应拒绝')
        with database.transaction() as connection:
            other = connection.execute('SELECT id FROM guide_runs WHERE requirement_id=?', (other_req,)).fetchone()[0]
    previous, closed = await stop_owner(checker, app)
    with database.transaction(write=True) as connection:
        if branch == 'MULTIPLE':
            # Each batch must own a distinct parent: retain the actual UNIQUE
            # guide_run_id guarantee. The second complete parent/message/batch
            # is an explicit historical fixture derived from actual C07 rows,
            # not a claim that a second signed model result was accepted.
            parent = dict(connection.execute('SELECT * FROM guide_runs WHERE id=?', (terminal['id'],)).fetchone())
            parent['id'] = entity_id(connection, EntityKind.GUIDE_RUN)
            parent['trigger_message_id'] = entity_id(connection, EntityKind.MESSAGE)
            parent['idempotency_key'] = str(uuid4())
            manifest = json.loads(parent['read_scope_manifest_json'])
            manifest['message_ids'] = [parent['trigger_message_id']]
            parent['read_scope_manifest_json'] = json.dumps(manifest, ensure_ascii=False)
            MessageRepository(connection).create_user_text(parent['trigger_message_id'], req, parent['id'],
                parent['instruction_summary'], parent['idempotency_key'], parent['created_at'])
            connection.execute('INSERT INTO guide_runs(' + ','.join(parent) + ') VALUES (' + ','.join('?' for _ in parent) + ')', tuple(parent.values()))
            copy = dict(connection.execute('SELECT * FROM suggestion_batches WHERE id=?', (batch,)).fetchone())
            copy['id'] = entity_id(connection, EntityKind.BATCH)
            copy['guide_run_id'] = parent['id']
            connection.execute('INSERT INTO suggestion_batches(' + ','.join(copy) + ') VALUES (' + ','.join('?' for _ in copy) + ')', tuple(copy.values()))
            for actual in connection.execute('SELECT * FROM suggestions WHERE batch_id=? ORDER BY id', (batch,)).fetchall():
                suggestion = dict(actual); suggestion['id'] = entity_id(connection, EntityKind.SUGGESTION); suggestion['batch_id'] = copy['id']
                connection.execute('INSERT INTO suggestions(' + ','.join(suggestion) + ') VALUES (' + ','.join('?' for _ in suggestion) + ')', tuple(suggestion.values()))
        identity = 999999 if branch == 'MISSING' else other if branch == 'CROSS' else terminal['id']
        connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=? WHERE id=?", (identity, req))
    checker.record['legacy_occupancy_fixture'] = branch + ': explicit post-close native occupancy corruption; producer and immutable original batch/suggestions remain actual C07'
    before = checker.database_facts(database); network = (len(chat.receipts), len(counter.server.receipts))
    if branch == 'TRUSTED':
        async with restarted(checker, database, previous) as (new_app, new_client):
            repaired = (await checker.request(new_client, 'GET', f'/requirements/{req}'))['data']
            checker.check('Startup switches stale terminal guide pointer to unique actual trusted PENDING batch',
                          repaired['document_work_state'] == 'SUGGESTION_REVIEWING' and repaired['active_operation_type'] == 'SUGGESTION_BATCH'
                          and repaired['active_operation_id'] == batch)
            recovered = checker.database_facts(database)
            # Only this root occupancy/time may change; every other whole SQL
            # fact, including original signed output, must remain exact.
            exclude = 'INSERT INTO "requirements" VALUES(' + str(req) + ','
            checker.check('Recovery changes only occupied root row and preserves all batch/result/document/audit facts',
                          [line for line in before if not line.startswith(exclude)] == [line for line in recovered if not line.startswith(exclude)])
            event = list(new_app.state.walle_worker.events)[0]['recovery']
            checker.check('Startup reports exact repaired root without recovering terminal run',
                          event['data']['recovered_run_ids'] == [] and event['data']['repaired_requirement_ids'] == [req])
    else:
        # Exercise the real C09 command under the real owner before the actual
        # startup entry. No failed uvicorn log is suppressed to fake a pass.
        with ProcessLock.for_database(database.path) as owner:
            result = recover_runs(database, {'recovery_reason': 'NO_PROGRESS', 'live_run_ids': set(),
                                  'operation_time': utc_milliseconds(datetime.now(timezone.utc))}, process_lock=owner)
        checker.check('Inconsistent scan refuses guessing and rolls back whole native DB',
                      result['code'] == 'WORK_STATE_INCONSISTENT' and before == checker.database_facts(database))
        created_workers = []
        def factory(db, resources):
            worker = GuideWorker(db, catalog=resources, orchestrator_options=previous._options)
            created_workers.append(worker); return worker
        denied_app = create_app(database=database, catalog=previous.catalog, worker_factory=factory)
        denied = None
        try:
            async with denied_app.router.lifespan_context(denied_app):
                raise AssertionError('Inconsistent startup must not admit HTTP')
        except WorkerStartupFailed as error: denied = error.code
        checker.check('Actual startup entry refuses inconsistent state and releases exclusive lock',
                      denied == 'WORK_STATE_INCONSISTENT' and not created_workers[0].accepting and not created_workers[0].started
                      and before == checker.database_facts(database))
        with ProcessLock.for_database(database.path): checker.check('Failed startup leaves process lock reacquirable', True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=denied_app), base_url='http://denied') as denied_client:
            await checker.request(denied_client, 'GET', '/requirements', status=503)
        checker.check('Rejected startup HTTP admission does not change any persisted fact', before == checker.database_facts(database))
    checker.check('Recovery never creates an external model resend', network == (len(chat.receipts), len(counter.server.receipts)))


async def run(checker, client, database, req, current, chat, counter, app, branch):
    if branch == 'TIMEOUT': await timeout_flow(checker, client, database, req, current, chat, counter, app)
    elif branch == 'RESTART_KEEP': await keep_and_orphan(checker, client, database, req, current, chat, counter, app)
    else: await occupancy(checker, client, database, req, current, chat, counter, app, branch)
    checker.record['recovery_branch'] = branch
    checker.record['actual_local_count_requests'] = len(counter.server.receipts)
    checker.record['actual_local_chat_requests'] = len(chat.receipts)
