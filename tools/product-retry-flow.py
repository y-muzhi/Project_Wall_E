"""TC-E2E-08 public acceptance/continuation, ORCH and actual local TCP.

Private diagnostic backoff records 2/5 decisions without wall-clock waiting;
only TIMEOUT shortens the transport's local read bound to 50ms while retaining
the original observed 180-second request extension. No paid requests/proof.
"""
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from threading import Event
from uuid import uuid4
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import ENDPOINT
from backend.tests.infrastructure import test_model_gateway as wire


ANSWER = {'schema_version': 1, 'response_type': 'ANSWER', 'message': '实际重试后正常完成。'}
NO_CHANGE = {'schema_version': 1, 'response_type': 'NO_CHANGE', 'message': '此次没有正文修改建议。'}
NON_RETRY = {
    'AUTHENTICATION': (401, 'AuthenticationError'),
    'PERMISSION': (403, 'AccessDenied'),
    'BALANCE': (402, 'AccountOverdueError'),
    'QUOTA': (429, 'QuotaExceeded'),
    'PARAMETER': (400, 'InvalidParameter'),
    'MODEL': (404, 'ModelNotOpen'),
    'CONTENT_FILTER': (400, 'InputTextSensitiveContentDetected.PolicyViolation'),
    'CONTEXT_LIMIT': (413, 'OutofContextError'),
    'UNKNOWN': (429, 'Unknown.ProviderCode'),
    'HTTP404': (404, None),
}


def gates():
    spec = importlib.util.spec_from_file_location('retry_gates', Path(__file__).with_name('product-gates-flow.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def error(chat, status, code=None, *, behavior=None):
    value = {} if code is None else {'error': {'code': code, 'message': '隔离供应方错误'}}
    chat.responses.append((status, json.dumps(value).encode(), {}, behavior))


def invalid(checker, chat, branch):
    if branch == 'NETWORK': error(chat, 200, behavior='disconnect')
    elif branch == 'TIMEOUT':
        checker.queue_output(chat, ANSWER)
        status, body, headers, unused = chat.responses[-1]
        chat.responses[-1] = (status, body, headers, 'hold')
    elif branch == 'RATE_LIMIT': error(chat, 429, 'RateLimitExceeded.EndpointRPMExceeded')
    elif branch == 'TEMPORARY': error(chat, 503)
    elif branch == 'JSON':
        value = wire.envelope(); value['choices'][0]['message']['content'] = '{bad output'
        chat.responses.append((200, json.dumps(value).encode(), {}, None))
    elif branch == 'SCHEMA': checker.queue_output(chat, ANSWER | {'unknown_field': 'never silently repaired'})
    elif branch == 'AUTHORITY':
        checker.queue_output(chat, {'schema_version': 1, 'response_type': 'SUGGESTIONS', 'message': '越权结果必须拒绝',
            'title': '隔离非法目标', 'summary': '区块3权限不能修改区块5', 'suggestions': [
                {'title': '越权修改', 'explanation': '非法范围', 'impact': None, 'patch_operation': 'REPLACE_BLOCK',
                 'target_ref': {'block_id': 5}, 'selector_json': None, 'original_content': '待确认。\n',
                 'proposed_markdown': '不得采用。\n', 'proposed_data_json': None}]})
    else: raise AssertionError(branch)


async def run(checker, client, database, req, current, chat, counter, app, branch):
    worker = app.state.walle_worker
    await gates().settle(worker)
    network_before = (len(chat.receipts), len(counter.server.receipts))
    waits = []; entered = Event(); release = Event()
    async def backoff(seconds):
        waits.append(seconds)
        if branch == 'CANCEL_FIRST':
            entered.set()
            while not release.is_set(): await asyncio.sleep(0.01)
        else: await asyncio.sleep(0)
    worker._options['sleep'] = backoff
    original_gateway = worker._options['gateway']; diagnostic_observed = []; diagnostic_transports = []
    if branch == 'TIMEOUT':
        def factory():
            transport = wire.ForwardTransport(chat.server_port, diagnostic_observed, short_read=True)
            diagnostic_transports.append(transport); return transport
        worker._options['gateway'] = ModelGateway(transport_factory=factory)
        chat.peer_closed.clear(); chat.hold_timeout = 10
    action = 'MODIFY' if branch == 'AUTHORITY' else 'ASK'
    if branch == 'EXHAUST':
        invalid(checker, chat, 'JSON'); invalid(checker, chat, 'SCHEMA'); invalid(checker, chat, 'TEMPORARY')
        expected_attempts, expected_waits, expected_state = 3, [2, 5], 'FAILED'
    elif branch == 'CANCEL_FIRST':
        invalid(checker, chat, 'RATE_LIMIT')
        expected_attempts, expected_waits, expected_state = 1, [2], 'CANCELLED'
    elif branch.startswith('NO_RETRY-'):
        status, code = NON_RETRY[branch.removeprefix('NO_RETRY-')]
        error(chat, status, code)
        expected_attempts, expected_waits, expected_state = 1, [], 'FAILED'
    elif branch == 'WAITING_CONTINUE':
        invalid(checker, chat, 'RATE_LIMIT')
        checker.queue_output(chat, {'schema_version': 1, 'response_type': 'CLARIFY_TEXT', 'message': '请补充后继续。'})
        expected_attempts, expected_waits, expected_state = 2, [2], 'WAITING_USER'
    else:
        invalid(checker, chat, branch); checker.queue_output(chat, NO_CHANGE if action == 'MODIFY' else ANSWER)
        expected_attempts, expected_waits, expected_state = 2, [2], 'COMPLETED'
    body = {'expected_version': current['content_version'], 'action_type': action, 'instruction': '验证单次调用和有限重试。',
            'scope_type': 'BLOCK' if action == 'MODIFY' else 'DOCUMENT', 'source_type': 'USER_INSTRUCTION'}
    if action == 'MODIFY': body['scope_ref'] = {'block_id': 3}
    try:
        accepted = (await checker.request(client, 'POST', f'/requirements/{req}/guide-runs', status=202,
                                          body=body, key=str(uuid4())))['data']
        identity = accepted['guide_run']['id']
        if branch == 'CANCEL_FIRST':
            checker.check('Actual ORCH reaches first backoff after one failed request/audit', await asyncio.to_thread(entered.wait, 5)
                          and len(chat.receipts) == network_before[0] + 1)
            cancelled = (await checker.request(client, 'POST', f'/guide-runs/{identity}/cancel', key=str(uuid4())))['data']
            checker.check('Public cancel commits before any second retry', cancelled['status'] == 'CANCELLED')
            release.set()
        else: await checker.wait_run(client, identity, expected_state)
        await gates().settle(worker)
        def native_attempts():
            with database.transaction() as connection:
                return [dict(r) for r in connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=? ORDER BY id', (identity,))]
        audits = native_attempts()
        checker.check('Every physical request owns exactly one audit and fresh count, without nested retries',
                      len(audits) == expected_attempts and len(chat.receipts) - network_before[0] == expected_attempts
                      and len(counter.server.receipts) - network_before[1] == expected_attempts)
        checker.check('Retries retain call_no 1 with bounded consecutive attempt numbers',
                      [(a['call_no'], a['attempt_no']) for a in audits] == [(1, i) for i in range(1, expected_attempts + 1)]
                      and waits == expected_waits)
        for offset, receipt in enumerate(chat.receipts[network_before[0]:]):
            counted = json.loads(counter.server.receipts[network_before[1] + offset]['body'])
            sent = json.loads(receipt['body'])
            checker.check('Each attempt sends the exact System/User texts counted for it ' + str(offset + 1),
                          counted['text'][:2] == [m['content'] for m in sent['messages']])
        if branch == 'TIMEOUT':
            checker.check('Real local read timeout closes connection; configured request timeout stays frozen',
                          await asyncio.to_thread(chat.peer_closed.wait, 3) and len(diagnostic_observed) == 2
                          and all(o['url'] == ENDPOINT and o['extensions']['timeout'] == {'connect': 10, 'read': 180, 'write': 10, 'pool': 10} for o in diagnostic_observed)
                          and all(t.closed for t in diagnostic_transports))
        if branch in ('JSON', 'SCHEMA', 'AUTHORITY', 'EXHAUST'):
            first = audits[0]
            checker.check('Failed output retains actual incurred token usage and safe failure without trusted adoption',
                          first['call_status'] == 'SUCCEEDED' and first['input_tokens'] == 123 and first['output_tokens'] == 10
                          and first['trusted_output_json'] is None
                          and first['parse_status' if branch in ('JSON', 'EXHAUST') else 'validation_status'] == 'FAILED')
        if branch == 'EXHAUST':
            with database.transaction() as connection:
                failed = dict(connection.execute('SELECT * FROM guide_runs WHERE id=?', (identity,)).fetchone())
            checker.check('Exhaustion takes final transport failure, preserving both earlier output failures and usage',
                          failed['error_code'] == 'MODEL_ERROR' and audits[0]['error_code'] == audits[1]['error_code'] == 'OUTPUT_INVALID'
                          and audits[1]['validation_status'] == 'FAILED' and audits[1]['input_tokens'] == 123
                          and audits[2]['call_status'] == 'FAILED' and audits[2]['error_code'] == 'MODEL_ERROR'
                          and audits[2]['input_tokens'] is None)
        elif branch == 'WAITING_CONTINUE':
            historical = deepcopy(audits)
            invalid(checker, chat, 'TEMPORARY'); checker.queue_output(chat, ANSWER)
            continued = (await checker.request(client, 'POST', f'/guide-runs/{identity}/continue', status=202,
                         body={'instruction': '真实用户补充后继续。'}, key=str(uuid4())))['data']
            checker.check('User continuation accepts original run rather than a replacement', continued['id'] == identity)
            await checker.wait_run(client, identity, 'COMPLETED'); await gates().settle(worker)
            audits = native_attempts()
            checker.check('New input creates call_no 2; each call independently starts attempt_no 1',
                          [(a['call_no'], a['attempt_no']) for a in audits] == [(1, 1), (1, 2), (2, 1), (2, 2)]
                          and audits[:2] == historical and waits == [2, 2]
                          and len(chat.receipts) - network_before[0] == len(counter.server.receipts) - network_before[1] == 4)
        actual = (await checker.request(client, 'GET', f'/guide-runs/{identity}'))['data']
        root = (await checker.request(client, 'GET', f'/requirements/{req}'))['data']
        checker.check('Finished/failed/cancelled operation releases occupancy, preserves entire CURRENT',
                      actual['status'] == ('COMPLETED' if branch == 'WAITING_CONTINUE' else expected_state)
                      and root['document_work_state'] == 'IDLE' and root['active_operation_id'] is None
                      and (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data'] == current)
        with database.transaction() as connection:
            messages = [dict(r) for r in connection.execute("SELECT * FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT' ORDER BY id", (identity,))]
            batches = connection.execute('SELECT count(*) FROM suggestion_batches WHERE guide_run_id=?', (identity,)).fetchone()[0]
        checker.check('Only actual successful results create assistant messages and no invalid batch is adopted',
                      len(messages) == (2 if branch == 'WAITING_CONTINUE' else 1 if expected_state == 'COMPLETED' else 0) and batches == 0)
        checker.record['retry_attempts'] = audits; checker.record['backoff_decisions_seconds'] = waits
        checker.record['diagnostic_backoff'] = 'Record actual ORCH 2/5 decisions, yield without wall-clock wait; does not test elapsed duration'
        checker.record['diagnostic_timeout'] = 'Local TIMEOUT read bound only is 50ms; original observed request timeout remains 180s' if branch == 'TIMEOUT' else None
        checker.record['actual_local_count_requests'] = len(counter.server.receipts)
        checker.record['actual_local_chat_requests'] = len(chat.receipts)
        checker.record['retry_branch'] = branch
    finally:
        release.set(); worker._options['gateway'] = original_gateway
