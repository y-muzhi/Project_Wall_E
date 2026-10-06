"""TC-E2E-01/02/03/04/05/06/10: independent actual HTTP and native SQLite scenarios.

No paid Provider calls. Private diagnostic compatibility callbacks and synthetic
token counts do not prove tokenizer/framing accuracy. No normal DB or secrets.
Expected document text is calculated without calling the Patch implementation.
"""
import asyncio
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import sys
from threading import Barrier, Event, Thread
from time import monotonic
import traceback
from uuid import uuid4
from unittest.mock import patch as diagnostic_patch

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.service import create_app
from backend.app.guide.worker import GuideWorker
from backend.app.guide import commands as guide_commands
from backend.app.guide.output_evidence import card_text
from backend.app.infrastructure.database import Database
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.tests.infrastructure import test_tokenization as count_tcp
from backend.tests.infrastructure import test_model_gateway as chat_tcp
from backend.tests.messages.test_queries import cards_fixture


def hashes():
    files = sorted(p for p in (ROOT / 'backend').rglob('*')
                   if p.is_file() and p.suffix in ('.py', '.sql', '.json', '.md', '.lock'))
    files.append(Path(__file__).resolve())
    files.append(ROOT / 'tools/product-suggestions-flow.py')
    files.append(ROOT / 'tools/product-comments-flow.py')
    files.append(ROOT / 'tools/product-query-flow.py')
    files.append(ROOT / 'tools/product-gates-flow.py')
    return {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files}


class Verification:
    def __init__(self):
        self.record = {'scope': __doc__, 'recorded_at': datetime.now(timezone.utc).isoformat(),
                       'before': hashes(), 'checks': [], 'http': [], 'paid_requests': 0,
                       'normal_database_access': False, 'production_enabled': False,
                       'provider_compatibility_proved': False, 'model_effects_proved': False}

    def check(self, name, condition):
        self.record['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    async def request(self, client, method, path, *, status=200, body=None, key=None):
        headers = {} if key is None else {'Idempotency-Key': key}
        response = await client.request(method, '/api/v1' + path, json=body, headers=headers)
        self.record['http'].append({'method': method, 'path': path, 'expected_status': status,
                                   'status': response.status_code, 'response': response.json()})
        self.check(method + ' ' + path + ' HTTP ' + str(status), response.status_code == status)
        return response.json()

    def database_facts(self, database):
        # The application read authorizer intentionally denies the PRAGMA used
        # by iterdump. An independent read-only native connection captures all
        # actual isolated tables and trigger definitions in one read snapshot.
        with closing(sqlite3.connect(database.path.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('BEGIN')
            return list(connection.iterdump())

    async def edit_and_save(self, client, req, current, text, *, append_table=None):
        started = (await self.request(client, 'POST', f'/requirements/{req}/manual-draft',
                                     status=201, body={'expected_version': current['content_version']}, key=str(uuid4())))['data']
        draft = started['manual_draft']
        self.check('Actual draft starts at version 1 with exclusive occupancy', draft['content_version'] == 1
                   and started['requirement']['document_work_state'] == 'MANUAL_EDITING'
                   and started['requirement']['active_operation_id'] == draft['id'])
        self.check('Draft starts from complete current pair', draft['markdown_content'] == current['markdown_content']
                   and draft['block_state_json'] == current['block_state_json'])
        current_paragraph = current['markdown_content'].split('## 背景与目标\n')[1].split('## 用户与使用场景')[0]
        # A literal paragraph replacement, no production parser/Patch helper.
        # Retain authored boundary bytes; editing the paragraph does not remove
        # the template's leading/trailing blank lines as the first fixture did.
        start = len(current_paragraph) - len(current_paragraph.lstrip('\r\n'))
        end = len(current_paragraph.rstrip('\r\n'))
        expected = current['markdown_content'].replace(current_paragraph,
                    current_paragraph[:start] + text + current_paragraph[end:], 1)
        body = {'expected_version': 1, 'markdown_content': expected,
                'block_state_json': deepcopy(draft['block_state_json'])}
        if append_table is not None:
            state = body['block_state_json']; identity = state['next_block_id']
            state['next_block_id'] += 1
            state['blocks'].append({'block_id': identity, 'block_type': 'table',
                'section_path': list(state['blocks'][-1]['section_path']),
                'created_by_type': 'USER', 'created_source_type': 'MANUAL_EDIT', 'created_source_id': draft['id'],
                'created_at': draft['created_at'], 'last_modified_by_type': 'USER',
                'last_modified_source_type': 'MANUAL_EDIT', 'last_modified_source_id': draft['id'],
                'last_modified_at': draft['created_at']})
            expected += '\n' + append_table
            body['markdown_content'] = expected
        saved = (await self.request(client, 'PUT', f'/requirements/{req}/manual-draft', body=body))['data']
        self.check('Save increments only draft version to 2', saved['id'] == draft['id']
                   and saved['content_version'] == 2 and saved['markdown_content'] == expected)
        actual_current = (await self.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        self.check('Save leaves entire CURRENT unchanged', actual_current == current)
        self.check('Changed block receives server-authoritative manual provenance',
                   saved['block_state_json']['blocks'][2]['last_modified_by_type'] == 'USER'
                   and saved['block_state_json']['blocks'][2]['last_modified_source_type'] == 'MANUAL_EDIT'
                   and saved['block_state_json']['blocks'][2]['last_modified_source_id'] == draft['id'])
        return saved

    async def manual_flow(self, client, database, req, current):
        # Reach the exact CURRENT v3 precondition through real public editing,
        # not an artificial UPDATE that bypasses provenance/version semantics.
        preparation = await self.edit_and_save(client, req, current, '审批人为部门经理。')
        prepared = (await self.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                      body={'expected_version': 2}, key=str(uuid4())))['data']
        self.check('TC-E2E-02 native precondition CURRENT v3', prepared['content_version'] == 3
                   and prepared['id'] == current['id'] and prepared['markdown_content'] == preparation['markdown_content'])
        # Independent saved-draft cancellation starts from the same unchanged
        # v3 F-A pair, before the completion branch's draft is created.
        cancelled_draft = await self.edit_and_save(client, req, prepared, '仅保存于待取消草稿的内容😀。')
        cancelled = await self.request(client, 'DELETE', f'/requirements/{req}/manual-draft',
                                       body={'expected_version': 2}, key=str(uuid4()))
        self.check('Independent cancel closes the actual saved v2 draft from CURRENT v3',
                   cancelled['data']['manual_draft_id'] == cancelled_draft['id'] and cancelled['data']['cancelled'] is True)
        after_cancel = (await self.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        self.check('Cancellation preserves entire original CURRENT v3', after_cancel == prepared)
        revisions_before = (await self.request(client, 'GET', f'/requirements/{req}/revisions'))['data']['items']
        self.check('Cancel creates no extra revision', len(revisions_before) == 1 and revisions_before[0]['revision_type'] == 'BASELINE')
        block_comment = (await self.request(client, 'POST', f'/requirements/{req}/comments', status=201,
                                           key=str(uuid4()), body={'expected_content_version': 3, 'content': '请说明审批人',
                                                                  'anchor_type': 'BLOCK', 'block_id': 3}))['data']
        comment = (await self.request(client, 'POST', f'/requirements/{req}/comments', status=201,
                                     key=str(uuid4()), body={'expected_content_version': 3, 'content': '请说明审批人',
                                     'anchor_type': 'SELECTION', 'block_id': 3,
                                     'selection': {'selected_text': '部门经理', 'prefix_text': '审批人为', 'suffix_text': '。'}}))['data']
        self.check('Actual selection comment attached before edit', comment['anchor_status'] == 'ATTACHED')
        saved = await self.edit_and_save(client, req, prepared, '审批人为财务负责人。时限为2天。')
        self.record['manual_draft_id'] = saved['id']
        complete_key = str(uuid4())
        faults = [
            ('current_write', 'AFTER UPDATE', 'requirement_documents', "WHEN NEW.document_type='CURRENT'"),
            ('anchor_write', 'AFTER UPDATE', 'comments', ''),
            ('draft_deleted', 'AFTER DELETE', 'requirement_documents', "WHEN OLD.document_type='MANUAL_DRAFT'"),
            ('occupancy_released', 'AFTER UPDATE', 'requirements', "WHEN NEW.document_work_state='IDLE'"),
            ('source_closed', 'AFTER UPDATE', 'manual_edit_sessions', ''),
            ('success_receipt', 'BEFORE UPDATE', 'idempotency_records', "WHEN NEW.status='SUCCEEDED'"),
        ]
        self.record['manual_completion_faults'] = []
        for name, event, table, predicate in faults:
            with database.transaction(write=True) as connection:
                connection.execute(f"CREATE TRIGGER actual_flow_fault {event} ON {table} {predicate} BEGIN SELECT RAISE(ABORT,'isolated actual transaction fault'); END")
            try:
                before = self.database_facts(database)
                failed = await self.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                            status=503, body={'expected_version': 2}, key=complete_key)
                after = self.database_facts(database)
                self.check(name + ' returns safe STORAGE_UNAVAILABLE', failed['error']['code'] == 'STORAGE_UNAVAILABLE')
                self.check(name + ' rolls back all native facts including draft/anchors/occupancy/source/idempotency', before == after)
                self.record['manual_completion_faults'].append({'phase': name, 'before_sha256': hashlib.sha256('\n'.join(before).encode('utf-8')).hexdigest(),
                                                               'after_sha256': hashlib.sha256('\n'.join(after).encode('utf-8')).hexdigest(), 'passed': before == after})
            finally:
                with database.transaction(write=True) as connection:
                    connection.execute('DROP TRIGGER actual_flow_fault')
        completed = await self.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                       body={'expected_version': 2}, key=complete_key)
        actual = completed['data']
        self.check('Manual completion writes exact saved pair into same CURRENT once', actual['id'] == prepared['id']
                   and actual['content_version'] == 4 and actual['markdown_content'] == saved['markdown_content']
                   and actual['block_state_json'] == saved['block_state_json'])
        changed_comment = (await self.request(client, 'GET', f'/comments/{comment["id"]}'))['data']
        expected_comment = {**comment, 'anchor_status': 'ORPHANED'}
        self.check('Completion revalidates anchor without editing comment content/status/time', changed_comment == expected_comment)
        actual_block_comment = (await self.request(client, 'GET', f'/comments/{block_comment["id"]}'))['data']
        self.check('Block comment remains attached to same identity with all other facts unchanged', actual_block_comment == block_comment)
        root = (await self.request(client, 'GET', f'/requirements/{req}'))['data']
        self.check('Completion jointly releases manual occupancy', root['document_work_state'] == 'IDLE'
                   and root['active_operation_type'] is None and root['active_operation_id'] is None)
        missing = await self.request(client, 'GET', f'/requirements/{req}/manual-draft', status=404)
        self.check('Completed draft actually removed', missing['error']['code'] == 'MANUAL_DRAFT_NOT_FOUND')
        before = self.database_facts(database)
        replay = await self.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                    body={'expected_version': 2}, key=complete_key)
        self.check('Completion replay has exact original data/new request ID/zero native change', replay['data'] == actual
                   and replay['meta']['request_id'] != completed['meta']['request_id'] and before == self.database_facts(database))
        revisions = (await self.request(client, 'GET', f'/requirements/{req}/revisions'))['data']['items']
        self.check('Manual complete and cancel create no extra revision', len(revisions) == 1 and revisions[0]['revision_type'] == 'BASELINE')
        with database.transaction() as connection:
            remaining = connection.execute("SELECT count(*) FROM requirement_documents WHERE document_type='MANUAL_DRAFT'").fetchone()[0]
            contexts = connection.execute('SELECT count(*) FROM manual_draft_context').fetchone()[0]
            sources = [dict(r) for r in connection.execute('SELECT * FROM manual_edit_sessions ORDER BY draft_id')]
        self.record['manual_sources_after_complete_cancel'] = sources
        self.check('No drafts/contexts remain; minimal source relations retained', remaining == contexts == 0
                   and len(sources) == 3)

    async def wait_run(self, client, identity, expected):
        due = monotonic() + 10
        while monotonic() < due:
            status = (await self.request(client, 'GET', f'/guide-runs/{identity}'))['data']
            if status['status'] == expected:
                return status
            if status['status'] in ('FAILED', 'CANCELLED'):
                break
            await asyncio.sleep(0.02)
        self.check('Run reached ' + expected, False)

    def queue_output(self, chat, output):
        value = chat_tcp.envelope()
        value['choices'][0]['message']['content'] = json.dumps(output, ensure_ascii=False, separators=(',', ':'))
        chat.responses.append((200, json.dumps(value, ensure_ascii=False).encode('utf-8'), {}, None))

    async def card_race(self, client, database, message, answers):
        path = f'/conversation-messages/{message["id"]}/responses'
        variants = [
            {'schema_version': 1, 'responses': answers['responses'][:1]},
            {'schema_version': 1, 'responses': [answers['responses'][0], answers['responses'][0]]},
            {'schema_version': 1, 'responses': [{**answers['responses'][0], 'selected_option_keys': ['foreign']}, answers['responses'][1]]},
            {'schema_version': 1, 'responses': [{**answers['responses'][0], 'selected_option_keys': [], 'skipped': True}, answers['responses'][1]]},
        ]
        for body in variants:
            before = self.database_facts(database)
            await self.request(client, 'POST', path, status=422, body=body, key=str(uuid4()))
            self.check('Invalid whole-card group leaves all actual facts unchanged', self.database_facts(database) == before)
        lost = []
        class DropCommittedResponse(httpx.AsyncBaseTransport):
            def __init__(self):
                self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
                self.closed = False
            async def handle_async_request(self, request):
                response = await self.inner.handle_async_request(request)
                if response.status_code == 202:
                    body = await response.aread()
                    await response.aclose()
                    lost.append({'key': request.headers['Idempotency-Key'], 'response': json.loads(body)})
                    raise httpx.ReadError('Explicit loss after actual server commit, before caller receives body', request=request)
                return response
            async def aclose(self):
                await self.inner.aclose(); self.closed = True
        transport = DropCommittedResponse()
        keys = (str(uuid4()), str(uuid4()))
        barrier = Barrier(2); native_arrivals = []
        submit = guide_commands.submit_card_responses
        def simultaneous_native_entry(executor, payload, **kwargs):
            # Both real HTTP requests must enter the native capability before
            # either can acquire its actual SQLite transaction/claim. The real
            # capability then executes unchanged; no result/storage mock.
            native_arrivals.append(payload['idempotency_key'])
            barrier.wait(5)
            return submit(executor, payload, **kwargs)
        with diagnostic_patch.object(guide_commands, 'submit_card_responses', simultaneous_native_entry):
            async with httpx.AsyncClient(base_url=client.base_url, transport=transport, trust_env=False, timeout=10) as race_client:
                results = await asyncio.gather(*(race_client.post('/api/v1' + path, json=answers,
                                                    headers={'Idempotency-Key': key}) for key in keys), return_exceptions=True)
        self.check('Actual native capability concurrency barrier released both requests',
                   set(native_arrivals) == set(keys) and len(native_arrivals) == 2 and not barrier.broken)
        self.check('Actual concurrent requests: one committed/lost response and one conflict',
                   len(lost) == 1 and sum(isinstance(r, httpx.ReadError) for r in results) == 1
                   and sum(isinstance(r, httpx.Response) and r.status_code == 409 for r in results) == 1)
        other = next(r for r in results if isinstance(r, httpx.Response)).json()
        winner = lost[0]['response']; response = winner['data']['response_message']
        self.check('Conflict supplies safe actual already-answered reference', other['error']['code'] == 'CARD_ALREADY_ANSWERED'
                   and other['error']['details'] == {'response_message_id': response['id']})
        self.record.setdefault('actual_card_races', []).append({'message_id': message['id'],
                    'lost_committed_response': winner, 'conflict': other, 'transport_closed': transport.closed,
                    'native_barrier_arrivals': native_arrivals})
        self.check('Lost-response diagnostic HTTP transport closed', transport.closed)
        with database.transaction() as connection:
            count = connection.execute("SELECT count(*) FROM conversation_messages WHERE reply_to_message_id=? AND message_type='CARD_RESPONSE'", (message['id'],)).fetchone()[0]
        self.check('Concurrency creates exactly one formal CARD_RESPONSE', count == 1)
        return lost[0]['key'], winner

    async def cards_flow(self, client, database, req, current, initial_run, initial_message, chat, counter, cards):
        answers = {'schema_version': 1, 'responses': [
            {'card_key': 'c1', 'selected_option_keys': ['o1'], 'custom_answer': None, 'skipped': False},
            {'card_key': 'c2', 'selected_option_keys': [], 'custom_answer': None, 'skipped': True}]}
        self.queue_output(chat, {'schema_version': 1, 'response_type': 'INITIALIZE_TEXT', 'message': '初始化卡片回答已处理', 'confirmed_fact_patches': []})
        key, accepted = await self.card_race(client, database, initial_message, answers)
        new_run = accepted['data']['guide_run']['id']
        self.check('Completed INITIALIZE cards create a distinct native run', new_run != initial_run)
        await self.wait_run(client, new_run, 'COMPLETED')
        before = self.database_facts(database); before_network = (len(chat.receipts), len(counter.server.receipts))
        replay = await self.request(client, 'POST', f'/conversation-messages/{initial_message["id"]}/responses',
                                    status=202, body=answers, key=key)
        self.check('Lost INITIALIZE acceptance recovers original reply/run with new request ID', replay['data'] == accepted['data']
                   and replay['meta']['request_id'] != accepted['meta']['request_id'])
        self.check('INITIALIZE card replay causes no new native or network effect', before == self.database_facts(database)
                   and before_network == (len(chat.receipts), len(counter.server.receipts)))
        actual_current = (await self.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        self.check('Initialization answer text branch leaves entire CURRENT unchanged', actual_current == current)
        await self.request(client, 'POST', f'/requirements/{req}/complete-initialization',
                           body={'expected_content_version': current['content_version']}, key=str(uuid4()))
        self.queue_output(chat, {'schema_version': 1, 'response_type': 'CLARIFY_CARDS', 'message': card_text(cards), 'cards': cards})
        ask = (await self.request(client, 'POST', f'/requirements/{req}/guide-runs', status=202,
                                  body={'expected_version': current['content_version'], 'action_type': 'ASK',
                                        'instruction': '请核对审批人及补充时限', 'scope_type': 'DOCUMENT', 'source_type': 'USER_INSTRUCTION'}, key=str(uuid4())))['data']
        ask_id = ask['guide_run']['id']
        await self.wait_run(client, ask_id, 'WAITING_USER')
        messages = (await self.request(client, 'GET', f'/requirements/{req}/messages'))['data']['items']
        ask_message = messages[-1]
        self.check('Actual ASK card output is available while WAITING_USER', ask_message['message_type'] == 'INTERACTION_CARDS'
                   and ask_message['guide_run_id'] == ask_id and ask_message['card_state'] == 'AVAILABLE')
        self.queue_output(chat, {'schema_version': 1, 'response_type': 'ANSWER', 'message': '卡片继续已经完成'})
        ask_key, continued = await self.card_race(client, database, ask_message, answers)
        self.check('Non-initialization card response continues original native run', continued['data']['guide_run']['id'] == ask_id)
        await self.wait_run(client, ask_id, 'COMPLETED')
        before = self.database_facts(database); before_network = (len(chat.receipts), len(counter.server.receipts))
        replay = await self.request(client, 'POST', f'/conversation-messages/{ask_message["id"]}/responses',
                                    status=202, body=answers, key=ask_key)
        self.check('Lost same-run card acceptance recovers exact original data without second advancement', replay['data'] == continued['data']
                   and replay['meta']['request_id'] != continued['meta']['request_id']
                   and before == self.database_facts(database) and before_network == (len(chat.receipts), len(counter.server.receipts)))
        final_current = (await self.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        self.check('ASK/card continuation does not change CURRENT', final_current == current)
        with database.transaction() as connection:
            attempts = [dict(r) for r in connection.execute('SELECT guide_run_id,call_no,attempt_no,call_status,validation_status FROM llm_uses ORDER BY id')]
            run_count = connection.execute('SELECT count(*) FROM guide_runs').fetchone()[0]
            replies = connection.execute("SELECT count(*) FROM conversation_messages WHERE message_type='CARD_RESPONSE'").fetchone()[0]
        self.record['card_flow_native_attempts'] = attempts
        self.check('Exactly four actual one-attempt calls with same-run call_no 2',
                   [(a['guide_run_id'], a['call_no'], a['attempt_no']) for a in attempts] ==
                   [(initial_run, 1, 1), (new_run, 1, 1), (ask_id, 1, 1), (ask_id, 2, 1)]
                   and all(a['call_status'] == a['validation_status'] == 'SUCCEEDED' for a in attempts)
                   and run_count == 3 and replies == 2 and len(chat.receipts) == len(counter.server.receipts) == 4)
        self.record['actual_local_count_requests'] = len(counter.server.receipts)
        self.record['actual_local_chat_requests'] = len(chat.receipts)

    async def run(self, scenario):
        self.record['scenario'] = scenario
        self.record['independent_case_preparation'] = 'Fresh isolated database, actual public creation and baseline; no prior case state reused'
        directory = ROOT / 'output/product-flow' / uuid4().hex
        directory.mkdir(parents=True)
        database = Database(directory / 'isolated.sqlite')
        database.initialize()
        catalog = ResourceCatalog()
        counter = count_tcp.TokenizationTests(); counter.setUp()
        count_envelope = count_tcp.envelope()
        count_envelope['data'] = [{**deepcopy(count_envelope['data'][0]), 'index': i} for i in range(6)]
        counter.server.body = json.dumps(count_envelope).encode('utf-8')
        chat = chat_tcp.ControlledServer()
        thread = Thread(target=chat.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        arrived, release = Event(), Event()
        observed, transports = [], []
        def inspect():
            arrived.set()
            if not release.wait(15):
                raise AssertionError('Controlled response barrier timed out')
        chat.inspect_request = inspect
        def transport_factory():
            transport = chat_tcp.ForwardTransport(chat.server_port, observed)
            transports.append(transport)
            return transport
        gateway = ModelGateway(transport_factory=transport_factory)
        # Complete literal USER declaration under the approved D-010 protocol.
        # The expected text is independent of the production patch implementation.
        original, proposed = '待确认。\n', '审批人为部门经理😀。\n'
        declaration = '\n'.join(['确认事实变更', '目标区块：3',
                                  '章节：["需求新增规格","背景与目标"]', '操作：替换区块',
                                  '原文：', original, '确认的新正文：', proposed]).strip()
        patch = {'title': '确认审批人', 'explanation': '完整用户声明', 'impact': None,
                 'target_ref': {'block_id': 3}, 'original_content': original,
                 'patch_operation': 'REPLACE_BLOCK', 'selector_json': None,
                 'proposed_markdown': proposed, 'proposed_data_json': None}
        cards = cards_fixture()
        cards['intro'] = '下一步待确认的问题'
        cards['cards'][0]['related_spec_context'] = []
        if scenario == 'TC-E2E-04':
            prototype = cards['cards'][0]
            prototype.update(card_key='c1', question='审批人是否确定？',
                             custom_answer={'enabled': False, 'max_length': 0}, recommendation=None)
            prototype['options'] = [{**option, 'option_key': key} for key, option in zip(('o1', 'o2'), prototype['options'])]
            second = deepcopy(prototype); second.update(card_key='c2', question='是否补充时限？', required=False)
            cards['cards'].append(second)
        output = {'schema_version': 1, 'response_type': 'INITIALIZE_CARDS', 'message': card_text(cards),
                  'cards': cards, 'confirmed_fact_patches': [
                      {'patch': patch, 'evidence': [{'message_id': 1, 'quoted_text': declaration}]}]}
        envelope = chat_tcp.envelope()
        envelope['choices'][0]['message']['content'] = json.dumps(output, ensure_ascii=False, separators=(',', ':'))
        chat.responses.append((200, json.dumps(envelope, ensure_ascii=False).encode('utf-8'), {}, None))
        def worker_factory(db, resources):
            return GuideWorker(db, catalog=resources, orchestrator_options={
                'profile': ModelProfile(chat_tcp.KEY), 'gateway': gateway,
                'compatibility_check': lambda *args: True,
                'counting_counter': counter.gateway,
                'counting_compatibility_check': lambda *args: True})
        app = create_app(database=database, catalog=catalog, worker_factory=worker_factory)
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(); listener.setblocking(False)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                             log_level='error', access_log=False, lifespan='on'))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        self.record['isolated_database'] = str(database.path)
        self.record['diagnostic_model'] = ModelProfile(chat_tcp.KEY).snapshot
        self.record['compatibility_callbacks'] = 'Explicit private offline fixtures only; not production proof'
        try:
            due = monotonic() + 10
            while not server.started and monotonic() < due and not serving.done():
                await asyncio.sleep(0.01)
            self.check('Actual uvicorn lifespan admitted HTTP', server.started and not serving.done())
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=10) as client:
                empty = await self.request(client, 'GET', '/requirements')
                self.check('Initial collection empty', empty['data']['items'] == [] and empty['meta']['pagination']['total'] == 0)
                create_key, baseline_key = str(uuid4()), str(uuid4())
                payload = {'title': '真实HTTP创建至基线😀', 'requirement_type': 'NEW',
                           'template_key': 'new-requirement', 'template_version': 'v1',
                           'initialization_mode': 'IDEATION', 'initial_idea': declaration}
                accepted = await self.request(client, 'POST', '/requirements', status=201, body=payload, key=create_key)
                data = accepted['data']; req = data['requirement']['id']; run = data['guide_run_id']
                self.check('201 is durable acceptance, not AI completion', data['requirement']['status'] == 'INITIALIZING'
                           and data['requirement']['document_work_state'] == 'GUIDE_ACTIVE')
                self.check('Chat has reached prepared audit barrier', await asyncio.to_thread(arrived.wait, 5))
                before = (await self.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
                pending = (await self.request(client, 'GET', f'/guide-runs/{run}'))['data']
                self.check('Run still RUNNING before controlled response', pending['status'] == 'RUNNING')
                self.check('Original CURRENT identity and version', before['id'] == data['current_document_id'] and before['content_version'] == 1)
                self.check('Block 3 original paragraph and section identity', before['block_state_json']['blocks'][2]['block_id'] == 3
                           and before['block_state_json']['blocks'][2]['section_path'] == ['需求新增规格', '背景与目标'])
                expected_markdown = before['markdown_content'].replace(original, proposed, 1)
                release.set()
                states = []
                due = monotonic() + 10
                while monotonic() < due:
                    final_run = (await self.request(client, 'GET', f'/guide-runs/{run}'))['data']
                    states.append(final_run['status'])
                    if final_run['status'] not in ('RUNNING', 'WAITING_USER'):
                        break
                    await asyncio.sleep(0.02)
                self.check('INITIALIZE completed and never waited for USER', final_run['status'] == 'COMPLETED'
                           and 'WAITING_USER' not in states and final_run['current_step'] == 'FINISHED')
                after = (await self.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
                root = (await self.request(client, 'GET', f'/requirements/{req}'))['data']
                self.check('After initialization root INITIALIZING/IDLE', root['status'] == 'INITIALIZING' and root['document_work_state'] == 'IDLE')
                self.check('Exactly confirmed paragraph adopted once into same CURRENT', after['id'] == before['id']
                           and after['content_version'] == 2 and after['markdown_content'] == expected_markdown
                           and after['created_at'] == before['created_at'])
                old_state, new_state = before['block_state_json'], after['block_state_json']
                self.check('All identities/order/allocation preserved', old_state['next_block_id'] == new_state['next_block_id']
                           and [b['block_id'] for b in old_state['blocks']] == [b['block_id'] for b in new_state['blocks']])
                for old, new in zip(old_state['blocks'], new_state['blocks']):
                    if old['block_id'] != 3:
                        self.check('Untouched block metadata ' + str(old['block_id']), old == new)
                    else:
                        changes = {'last_modified_by_type', 'last_modified_source_type', 'last_modified_source_id', 'last_modified_at'}
                        self.check('Changed block creation/type/section provenance preserved',
                                   {k: v for k, v in old.items() if k not in changes} == {k: v for k, v in new.items() if k not in changes})
                        self.check('Changed block actual AI run provenance', new['last_modified_by_type'] == 'AI'
                                   and new['last_modified_source_type'] == 'GUIDE_RUN' and new['last_modified_source_id'] == run
                                   and new['last_modified_at'] >= old['last_modified_at'])
                messages = (await self.request(client, 'GET', f'/requirements/{req}/messages'))['data']['items']
                self.check('Actual USER and native C07 assistant card message', len(messages) == 2
                           and messages[0]['content'] == declaration and messages[1]['message_type'] == 'INTERACTION_CARDS'
                           and messages[1]['content'] == output['message'] and messages[1]['card_state'] == 'AVAILABLE')
                if scenario == 'TC-E2E-04':
                    await self.cards_flow(client, database, req, after, run, messages[1], chat, counter, cards)
                    self.record['tc_e2e_04_passed'] = True
                    return
                self.check('No revision before completing initialization',
                           (await self.request(client, 'GET', f'/requirements/{req}/revisions'))['data']['items'] == [])
                complete_body = {'expected_content_version': 2}
                completed = await self.request(client, 'POST', f'/requirements/{req}/complete-initialization', body=complete_body, key=baseline_key)
                completed_data = completed['data']; baseline = completed_data['baseline_revision']
                self.check('Complete initialization ACTIVE/IDLE with baseline version 1', completed_data['requirement']['status'] == 'ACTIVE'
                           and completed_data['requirement']['document_work_state'] == 'IDLE'
                           and baseline['revision_type'] == 'BASELINE' and baseline['version_no'] == 1 and baseline['source_content_version'] == 2)
                revisions = await self.request(client, 'GET', f'/requirements/{req}/revisions')
                self.check('Exactly one baseline in actual revision collection', revisions['meta']['pagination']['total'] == 1
                           and [r['id'] for r in revisions['data']['items']] == [baseline['id']])
                historical = (await self.request(client, 'GET', f'/revisions/{baseline["id"]}'))['data']
                self.check('Baseline retains exact CURRENT text and provenance snapshot', historical['markdown_content'] == after['markdown_content']
                           and historical['block_state_json'] == after['block_state_json'])
                final_current = (await self.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
                self.check('Baseline creation does not replace/update CURRENT at all', final_current == after)
                replay = await self.request(client, 'POST', f'/requirements/{req}/complete-initialization', body=complete_body, key=baseline_key)
                self.check('Same-key baseline replay exact data and new request ID', replay['data'] == completed_data
                           and replay['meta']['request_id'] != completed['meta']['request_id'])
                creation_replay = await self.request(client, 'POST', '/requirements', status=201, body=payload, key=create_key)
                self.check('Creation replay returns original accepted snapshot without new run', creation_replay['data'] == accepted['data']
                           and creation_replay['meta']['request_id'] != accepted['meta']['request_id'])
                before_duplicate = self.database_facts(database)
                duplicate = await self.request(client, 'POST', f'/requirements/{req}/complete-initialization', status=409,
                                               body=complete_body, key=str(uuid4()))
                self.check('Different-key repeated baseline rejected without any native change', duplicate['error']['code'] == 'STATE_CONFLICT'
                           and before_duplicate == self.database_facts(database))
                with database.transaction() as connection:
                    counts = {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                              for table in ('requirements', 'requirement_documents', 'revisions',
                                            'guide_runs', 'conversation_messages', 'llm_uses', 'suggestion_batches')}
                    audits = [dict(r) for r in connection.execute('SELECT id,guide_run_id,call_no,attempt_no,call_status,parse_status,validation_status,input_tokens,output_tokens FROM llm_uses')]
                self.record['native_counts'] = counts; self.record['audit_stages'] = audits
                self.check('Exactly one native C07 result and baseline; no replay effects', counts == {
                    'requirements': 1, 'requirement_documents': 1, 'revisions': 1,
                    'guide_runs': 1, 'conversation_messages': 2, 'llm_uses': 1, 'suggestion_batches': 0})
                self.check('Actual one-attempt successful transport/parse/full signed validation', len(audits) == 1
                           and all(audits[0][f] == 'SUCCEEDED' for f in ('call_status', 'parse_status', 'validation_status')))
                self.check('Exactly one local count and Chat, no replay network', len(counter.server.receipts) == len(chat.receipts) == 1)
                counted = json.loads(counter.server.receipts[0]['body'])
                sent = json.loads(chat.receipts[0]['body'])
                self.check('Exact counted System/User transmitted to actual Chat TCP', counted['text'][:2] == [m['content'] for m in sent['messages']])
                self.record['actual_local_count_requests'] = len(counter.server.receipts)
                self.record['actual_local_chat_requests'] = len(chat.receipts)
                self.record['tc_e2e_01_passed'] = True
                if scenario == 'TC-E2E-02':
                    await self.manual_flow(client, database, req, final_current)
                    self.record['tc_e2e_02_passed'] = True
                elif scenario.startswith('TC-E2E-06-'):
                    spec = importlib.util.spec_from_file_location('product_gates_flow', ROOT / 'tools/product-gates-flow.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    await module.run(self, client, database, req, final_current, chat, counter, app, scenario.removeprefix('TC-E2E-06-'))
                elif scenario.startswith('TC-E2E-10-'):
                    spec = importlib.util.spec_from_file_location('product_query_flow', ROOT / 'tools/product-query-flow.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    await module.run(self, client, database, req, final_current, chat, counter, scenario.removeprefix('TC-E2E-10-'))
                elif scenario.startswith('TC-E2E-05-'):
                    spec = importlib.util.spec_from_file_location('product_comments_flow', ROOT / 'tools/product-comments-flow.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    await module.run(self, client, database, req, final_current, chat, counter, scenario.removeprefix('TC-E2E-05-'))
                elif scenario.startswith('TC-E2E-03-'):
                    spec = importlib.util.spec_from_file_location('product_suggestions_flow', ROOT / 'tools/product-suggestions-flow.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    await module.run(self, client, database, req, final_current, chat, counter, scenario.removeprefix('TC-E2E-03-'))
        finally:
            release.set(); server.should_exit = True
            await asyncio.wait_for(serving, 15)
            listener.close()
            chat.shutdown(); chat.server_close(); thread.join(3)
            counter.tearDown()
            self.check('Controlled TCP servers and all client transports closed', not thread.is_alive() and not counter.thread.is_alive()
                       and chat.errors == [] and all(t.closed for t in transports + counter.transports))
            self.check('Worker has no live runs after graceful shutdown', not app.state.walle_worker.live_run_ids)
            with ProcessLock.for_database(database.path):
                self.check('Actual process lock released at shutdown', True)


def main():
    outcomes = []
    scenarios = ('TC-E2E-01', 'TC-E2E-02', 'TC-E2E-04', 'TC-E2E-03-APPLY', 'TC-E2E-03-NOCHANGE',
                     'TC-E2E-03-PENDING', 'TC-E2E-03-VERSIONS', 'TC-E2E-03-STALE', 'TC-E2E-03-TARGET', 'TC-E2E-03-COMBINATION',
                     'TC-E2E-03-TABLE_ROW', 'TC-E2E-03-TABLE_APPEND',
                     'TC-E2E-05-OPEN-ATTACHED', 'TC-E2E-05-OPEN-ORPHANED',
                     'TC-E2E-05-RESOLVED-ATTACHED', 'TC-E2E-05-RESOLVED-ORPHANED',
                     'TC-E2E-10-LIST', 'TC-E2E-10-READS',
                     'TC-E2E-06-CANCEL_FIRST', 'TC-E2E-06-PERSIST_FIRST', 'TC-E2E-06-LATE_TCP')
    if len(sys.argv) > 1:
        if len(sys.argv) < 3 or sys.argv[1] != '--scenarios' or any(s not in scenarios for s in sys.argv[2:]):
            raise SystemExit('Use --scenarios followed by registered local verification scenarios')
        scenarios = tuple(sys.argv[2:])
    for scenario in scenarios:
        verification = Verification()
        try:
            asyncio.run(verification.run(scenario))
        except Exception:
            verification.record['failure_traceback'] = traceback.format_exc()
        verification.record['after'] = hashes()
        verification.record['inputs_unchanged'] = verification.record['before'] == verification.record['after']
        verification.record['passed'] = (not verification.record.get('failure_traceback')
                                         and verification.record['inputs_unchanged']
                                         and all(c['passed'] for c in verification.record['checks']))
        stamp = verification.record['recorded_at'].replace(':', '-').replace('.', '-')
        path = ROOT / 'docs/verification' / ('product-flow-' + stamp + '-' + scenario + '.json')
        path.write_text(json.dumps(verification.record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        outcomes.append({'scenario': scenario, 'passed': verification.record['passed'], 'checks': len(verification.record['checks']),
                         'evidence': str(path)})
        if not verification.record['passed']:
            print(verification.record.get('failure_traceback', 'Inputs changed'), file=sys.stderr)
    print(json.dumps(outcomes, ensure_ascii=False))
    if not all(o['passed'] for o in outcomes):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
