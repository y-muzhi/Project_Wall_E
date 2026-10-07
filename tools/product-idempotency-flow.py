"""TC-E2E-09 four independently prepared capabilities x two loss modes.

Actual claim/operation/commit, HTTP response loss and startup owner change;
native trigger proves rollback. UNKNOWN_ACK forwards the actual transaction
through its commit then raises CommitOutcomeUnknown for that success only.
No mock repositories, fake success, normal DB or paid model calls.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
from threading import Event
from unittest.mock import patch
from uuid import uuid4
import httpx
from backend.app.guide.output_evidence import card_text
from backend.app.infrastructure.database import Database, CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Idempotency, Claim
from backend.tests.messages.test_queries import cards_fixture


def helper(name):
    spec = importlib.util.spec_from_file_location('idem_' + name, Path(__file__).with_name('product-' + name + '-flow.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class DropResponse(httpx.AsyncBaseTransport):
    def __init__(self, captures, expected):
        self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.captures = captures; self.expected = expected; self.closed = False
    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if response.status_code == self.expected:
            body = await response.aread(); await response.aclose()
            self.captures.append({'status': response.status_code, 'response': json.loads(body)})
            raise httpx.ReadError('Explicit committed HTTP response loss before delivery to caller', request=request)
        return response
    async def aclose(self):
        await self.inner.aclose(); self.closed = True


async def prepare(checker, client, database, req, current, chat, kind):
    if kind == 'CREATE':
        return '/requirements', {'title': '幂等独立创建', 'requirement_type': 'NEW', 'template_key': 'new-requirement',
                'template_version': 'v1', 'initialization_mode': 'IDEATION', 'initial_idea': '保留模板即可。'}, 201, 'APP-REQ-CMD-C01'
    if kind == 'DRAFT':
        absent = await checker.request(client, 'GET', f'/requirements/{req}/manual-draft', status=404)
        checker.check('404 draft absence is not evidence that a future start/complete command succeeded',
                      absent['error']['code'] == 'MANUAL_DRAFT_NOT_FOUND'
                      and (await checker.request(client, 'GET', f'/requirements/{req}'))['data']['document_work_state'] == 'IDLE')
        return f'/requirements/{req}/manual-draft', {'expected_version': current['content_version']}, 201, 'APP-DOC-CMD-C01'
    if kind == 'CARDS':
        cards = cards_fixture(); cards['cards'][0]['related_spec_context'] = []
        await helper('query').guide(checker, client, chat, req, current['content_version'], 'ASK',
            {'schema_version': 1, 'response_type': 'CLARIFY_CARDS', 'message': card_text(cards), 'cards': cards})
        message = (await checker.request(client, 'GET', f'/requirements/{req}/messages'))['data']['items'][-1]
        checker.check('Independent card source is actual native C07 WAITING_USER/AVAILABLE', message['card_state'] == 'AVAILABLE')
        return f'/conversation-messages/{message["id"]}/responses', {'schema_version': 1, 'responses': [
            {'card_key': 'first', 'selected_option_keys': ['a'], 'custom_answer': None, 'skipped': False}]}, 202, 'APP-GUIDE-CMD-C06'
    await helper('query').guide(checker, client, chat, req, current['content_version'], 'MODIFY',
        {'schema_version': 1, 'response_type': 'SUGGESTIONS', 'message': '准备幂等批次', 'title': '完成一次',
         'summary': '真实C07两项', 'suggestions': helper('query').patches('审批人为部门经理😀。\n')})
    batch = (await checker.request(client, 'GET', f'/requirements/{req}'))['data']['active_operation_id']
    suggestions = (await checker.request(client, 'GET', f'/suggestion-batches/{batch}'))['data']['suggestions']
    for item in suggestions:
        await checker.request(client, 'PUT', f'/suggestions/{item["id"]}/decision',
                              body={'decision': 'ACCEPTED'}, key=str(uuid4()))
    return f'/suggestion-batches/{batch}/complete', {'expected_content_version': current['content_version']}, 200, 'APP-BATCH-CMD-C02'


def altered(body, kind):
    changed = deepcopy(body)
    if kind == 'CREATE': changed['title'] += '另一输入'
    elif kind == 'DRAFT': changed['expected_version'] += 1
    elif kind == 'BATCH': changed['expected_content_version'] += 1
    else: changed['responses'][0]['selected_option_keys'] = ['b']
    return changed


def counts(database):
    with database.transaction() as connection:
        return {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                for table in ('requirements', 'requirement_documents', 'guide_runs', 'conversation_messages',
                              'suggestion_batches', 'suggestions', 'revisions', 'llm_uses')}


async def observe(checker, client, database, req, kind, application_data):
    if kind == 'CREATE':
        created = application_data['requirement']['id']
        root = (await checker.request(client, 'GET', f'/requirements/{created}'))['data']
        document = (await checker.request(client, 'GET', f'/requirements/{created}/current-document'))['data']
        checker.check('Actual created resource and CURRENT identities equal durable original acceptance',
                      root['id'] == created and document['id'] == application_data['current_document_id'] and document['content_version'] == 1)
        return application_data['guide_run_id']
    if kind == 'DRAFT':
        draft = (await checker.request(client, 'GET', f'/requirements/{req}/manual-draft'))['data']
        root = (await checker.request(client, 'GET', f'/requirements/{req}'))['data']
        checker.check('Actual exclusive draft and root equal committed acceptance', draft == application_data['manual_draft']
                      and root['active_operation_id'] == draft['id'] and root['document_work_state'] == 'MANUAL_EDITING')
    elif kind == 'CARDS':
        response = application_data['response_message']
        with database.transaction() as connection:
            matches = [dict(r) for r in connection.execute("SELECT * FROM conversation_messages WHERE reply_to_message_id=? AND message_type='CARD_RESPONSE'", (response['reply_to_message_id'],))]
        checker.check('One durable whole-card response equals accepted formal identity', len(matches) == 1 and matches[0]['id'] == response['id'])
        return application_data['guide_run']['id']
    else:
        batch = (await checker.request(client, 'GET', f'/suggestion-batches/{application_data["batch"]["id"]}'))['data']
        document = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        checker.check('Actual completed batch and CURRENT equal single committed application', batch['status'] == 'COMPLETED'
                      and document == application_data['current_document'] and document['content_version'] == application_data['batch']['base_content_version'] + 1)
    return None


async def tombstone(checker, client, req):
    current = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
    comment = (await checker.request(client, 'POST', f'/requirements/{req}/comments', status=201,
        body={'expected_content_version': current['content_version'], 'content': '删除须查看明确墓碑。', 'anchor_type': 'BLOCK', 'block_id': 3}, key=str(uuid4())))['data']
    await checker.request(client, 'DELETE', f'/comments/{comment["id"]}', key=str(uuid4()))
    deleted = (await checker.request(client, 'GET', f'/comments/{comment["id"]}'))['data']
    checker.check('Soft delete completion is proved by actual retained deleted_at tombstone',
                  deleted['id'] == comment['id'] and deleted['deleted_at'] is not None)
    missing = await checker.request(client, 'GET', '/comments/999999', status=404)
    checker.check('A different unknown resource 404 remains NOT_FOUND, not proof of delete completion', missing['error']['code'] == 'NOT_FOUND')


async def run(checker, client, database, req, current, chat, counter, app, branch):
    kind, loss = branch.split('-', 1)
    await helper('gates').settle(app.state.walle_worker)
    path, body, expected_status, capability = await prepare(checker, client, database, req, current, chat, kind)
    await helper('gates').settle(app.state.walle_worker)
    key = str(uuid4()); native_before = counts(database); initial = checker.database_facts(database)
    network = (len(chat.receipts), len(counter.server.receipts))
    entered, release = Event(), Event(); original_claim = Idempotency.claim
    def forward_claim(executor, scope, business_input):
        outcome = original_claim(executor, scope, business_input)
        if scope.key == key and isinstance(outcome, Claim):
            entered.set()
            if not release.wait(10): raise AssertionError('Committed claim barrier timed out')
        return outcome
    with database.transaction(write=True) as connection:
        connection.execute("CREATE TRIGGER product_idempotency_fault BEFORE UPDATE ON idempotency_records WHEN NEW.status='SUCCEEDED' AND NEW.idempotency_key='" + key + "' BEGIN SELECT RAISE(ABORT,'actual pre-commit failure'); END")
    before_fault = checker.database_facts(database)
    try:
        with patch.object(Idempotency, 'claim', new=forward_claim):
            first = asyncio.create_task(checker.request(client, 'POST', path, status=503, body=body, key=key))
            checker.check('First real HTTP request durably claims before its business transaction starts', await asyncio.to_thread(entered.wait, 5))
            processing = checker.database_facts(database)
            extra = [line for line in processing if line not in before_fault]
            checker.check('Processing adds exactly its claim, with no business allocation or effect', len(extra) == 1
                          and extra[0].startswith('INSERT INTO "idempotency_records"') and 'PROCESSING' in extra[0]
                          and [line for line in processing if line not in extra] == before_fault)
            duplicate = await checker.request(client, 'POST', path, status=409, body=body, key=key)
            conflict = await checker.request(client, 'POST', path, status=409, body=altered(body, kind), key=key)
            checker.check('Concurrent same key/input is in progress; changed input conflicts without effects',
                          duplicate['error']['code'] == 'REQUEST_IN_PROGRESS' and conflict['error']['code'] == 'IDEMPOTENCY_CONFLICT'
                          and processing == checker.database_facts(database))
            release.set(); failure = await first
        checker.check('Known native pre-commit ABORT rolls back every business fact and releases only own claim',
                      failure['error']['code'] == 'STORAGE_UNAVAILABLE' and before_fault == checker.database_facts(database)
                      and network == (len(chat.receipts), len(counter.server.receipts)))
    finally:
        release.set()
        with database.transaction(write=True) as connection: connection.execute('DROP TRIGGER product_idempotency_fault')
    checker.check('Fault trigger removal returns exact original native database', initial == checker.database_facts(database))
    if kind in ('CREATE', 'CARDS'):
        checker.queue_output(chat, {'schema_version': 1, 'response_type': 'INITIALIZE_TEXT', 'message': '幂等创建后的正常运行', 'confirmed_fact_patches': []}
                             if kind == 'CREATE' else {'schema_version': 1, 'response_type': 'ANSWER', 'message': '正式卡片只推进一次。'})
    lost = []; unknown_commits = []; failure_reply = None
    if loss == 'UNKNOWN_ACK':
        original_transaction = Database.transaction
        armed = Event(); armed.set()
        @contextmanager
        def forwarded_transaction(actual_database, *, write=False):
            matched = False
            with original_transaction(actual_database, write=write) as connection:
                yield connection
                if write and actual_database.path == database.path and armed.is_set():
                    stored = connection.execute("SELECT success_result_json FROM idempotency_records WHERE idempotency_key=? AND status='SUCCEEDED'", (key,)).fetchone()
                    matched = stored is not None
            if matched and armed.is_set():
                armed.clear(); unknown_commits.append({'key': key, 'actual_commit_completed': True})
                raise CommitOutcomeUnknown('Explicit lost acknowledgment after actual successful native commit')
        with patch.object(Database, 'transaction', new=forwarded_transaction):
            failure_reply = await checker.request(client, 'POST', path, status=503, body=body, key=key)
        checker.check('Unknown acknowledgment reports storage error after one actual success commit, retaining receipt',
                      failure_reply['error']['code'] == 'STORAGE_UNAVAILABLE' and len(unknown_commits) == 1)
    else:
        transport = DropResponse(lost, expected_status)
        async with httpx.AsyncClient(base_url=str(client.base_url), transport=transport, timeout=10) as losing:
            dropped = False
            try: await losing.post('/api/v1' + path, json=body, headers={'Idempotency-Key': key})
            except httpx.ReadError: dropped = True
        checker.check('Actual successful HTTP response is lost before caller delivery, and connection closes',
                      dropped and transport.closed and len(lost) == 1)
    with database.transaction() as connection:
        receipt = dict(connection.execute('SELECT * FROM idempotency_records WHERE idempotency_key=?', (key,)).fetchone())
    checker.check('Actual commit stores exactly the successful original status and full application result',
                  receipt['status'] == 'SUCCEEDED' and receipt['http_status'] == expected_status)
    application_data = json.loads(receipt['success_result_json'])['data']
    identity = await observe(checker, client, database, req, kind, application_data)
    replay = await checker.request(client, 'POST', path, status=expected_status, body=body, key=key)
    if identity is not None: await checker.wait_run(client, identity, 'COMPLETED')
    await helper('gates').settle(app.state.walle_worker)
    if lost:
        checker.check('Lost HTTP success replays original frozen data and issues a new request_id',
                      replay['data'] == lost[0]['response']['data'] and replay['meta']['request_id'] != lost[0]['response']['meta']['request_id'])
    else:
        checker.check('Unknown ack replays exact committed success rather than rerunning the command',
                      replay['data'] == application_data and replay['meta']['request_id'] != failure_reply['meta']['request_id'])
    after = checker.database_facts(database); after_network = (len(chat.receipts), len(counter.server.receipts))
    repeated = await checker.request(client, 'POST', path, status=expected_status, body=body, key=key)
    conflict = await checker.request(client, 'POST', path, status=409, body=altered(body, kind), key=key)
    await helper('gates').settle(app.state.walle_worker)
    checker.check('Repeated original key and conflicting input preserve all native facts and request counts',
                  repeated['data'] == replay['data'] and repeated['meta']['request_id'] != replay['meta']['request_id']
                  and conflict['error']['code'] == 'IDEMPOTENCY_CONFLICT' and after == checker.database_facts(database)
                  and after_network == (len(chat.receipts), len(counter.server.receipts)))
    native_after = counts(database)
    expected_delta = {table: 0 for table in native_before}
    if kind == 'CREATE': expected_delta.update(requirements=1, requirement_documents=1, guide_runs=1, conversation_messages=2, llm_uses=1)
    elif kind == 'DRAFT': expected_delta['requirement_documents'] = 1
    elif kind == 'CARDS': expected_delta.update(conversation_messages=2, llm_uses=1)
    checker.check('Resource cardinalities prove exactly one business effect per original command',
                  {table: native_after[table] - value for table, value in native_before.items()} == expected_delta)
    if kind == 'BATCH':
        expected = current['markdown_content'].replace('审批人为部门经理😀。\n', '查询建议一\n', 1).replace('待确认。\n', '查询建议二\n', 1)
        actual = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        checker.check('Completion applies literal independent expected text once to same CURRENT identity',
                      actual['id'] == current['id'] and actual['content_version'] == current['content_version'] + 1 and actual['markdown_content'] == expected)
    recovery = helper('recovery')
    previous, result = await recovery.stop_owner(checker, app)
    request_file = database.path.parent / 'persistent-replay-request.json'
    process_evidence = database.path.parent / 'persistent-replay-process.json'
    request_file.write_text(json.dumps({'path': path, 'body': body, 'key': key, 'status': expected_status},
                                      ensure_ascii=False) + '\n', encoding='utf-8')
    environment = {name: value for name, value in os.environ.items() if not name.startswith('WALLE_')}
    process = await asyncio.create_subprocess_exec(sys.executable, '-X', 'utf8',
        str(Path(__file__).with_name('product-replay-process.py')), str(database.path), str(request_file), str(process_evidence),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 40)
    except BaseException:
        if process.returncode is None: process.kill()
        await process.communicate()
        raise
    separate = json.loads(process_evidence.read_text(encoding='utf-8'))
    checker.record['persistent_replay_process'] = {'exit_code': process.returncode, 'stdout': stdout.decode('utf-8'),
                                                'stderr': stderr.decode('utf-8'), 'evidence': separate}
    checker.check('A distinct Python process replays durable success through actual HTTP after new owner startup',
                  process.returncode == 0 and separate['passed'] and separate['pid'] != os.getpid()
                  and separate['owner_epoch'] != receipt['owner_epoch'] and separate['http_status'] == expected_status
                  and separate['response']['data'] == replay['data']
                  and separate['response']['meta']['request_id'] != replay['meta']['request_id']
                  and separate['model_send_attempts'] == [] and separate['credential_present'] is False
                  and separate['process_lock_reacquired_after_close'] is True)
    checker.check('Separate process replay leaves every SQL fact unchanged, without another count/Chat',
                  after == checker.database_facts(database) and after_network == (len(chat.receipts), len(counter.server.receipts)))
    async with recovery.restarted(checker, database, previous) as (new_app, new_client):
        restarted_reply = await checker.request(new_client, 'POST', path, status=expected_status, body=body, key=key)
        await helper('gates').settle(new_app.state.walle_worker)
        checker.check('Persisted success survives actual lifespan restart and new process epoch with zero repeat effects',
                      restarted_reply['data'] == replay['data'] and restarted_reply['meta']['request_id'] != replay['meta']['request_id']
                      and after == checker.database_facts(database) and after_network == (len(chat.receipts), len(counter.server.receipts)))
        if kind == 'DRAFT':
            # Comment creation legitimately conflicts while MANUAL_EDITING.
            # Prove the persisted draft first, then explicitly cancel it before
            # the separate tombstone check; never silently release occupancy.
            cancelled = (await checker.request(new_client, 'DELETE', f'/requirements/{req}/manual-draft',
                body={'expected_version': 1}, key=str(uuid4())))['data']
            checker.check('Explicit cancellation acknowledges the original persisted draft identity',
                          cancelled['manual_draft_id'] == replay['data']['manual_draft']['id'] and cancelled['cancelled'] is True)
            await checker.request(new_client, 'GET', f'/requirements/{req}/manual-draft', status=404)
            checker.check('Absence after explicit cancel is corroborated by IDLE root and unchanged CURRENT',
                          (await checker.request(new_client, 'GET', f'/requirements/{req}'))['data']['document_work_state'] == 'IDLE'
                          and (await checker.request(new_client, 'GET', f'/requirements/{req}/current-document'))['data'] == current)
        await tombstone(checker, new_client, req)
    checker.record['idempotency_capability'] = capability; checker.record['loss_mode'] = loss
    checker.record['actual_commits_with_unknown_ack'] = unknown_commits; checker.record['lost_http_successes'] = lost
    checker.record['counts_before_operation'] = native_before; checker.record['counts_after_operation'] = native_after
    checker.record['actual_local_count_requests'] = len(counter.server.receipts)
    checker.record['actual_local_chat_requests'] = len(chat.receipts)
