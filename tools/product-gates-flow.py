"""TC-E2E-06 native SQL gate/barrier competition through actual HTTP.

Barriers only pause and forward actual production functions; no results, SQL,
trusted output, audit or business effects are replaced. No paid Provider calls.
"""
import asyncio
import sys
from threading import Event
from time import monotonic
from unittest.mock import patch
from uuid import uuid4
from backend.app.guide import orchestrator, result_persistence, commands
from backend.app.infrastructure.model_profile import ModelProfile
from backend.tests.infrastructure.test_model_gateway import KEY


def suggestions(current):
    return {'schema_version': 1, 'response_type': 'SUGGESTIONS', 'message': '请处理两项修改。',
            'title': '取消竞争', 'summary': '隔离场景', 'suggestions': [
                {'title': '修改段落', 'explanation': '待采用', 'impact': None, 'target_ref': {'block_id': identity},
                 'patch_operation': 'REPLACE_BLOCK', 'original_content': original,
                 'selector_json': None, 'proposed_markdown': proposed, 'proposed_data_json': None}
                for identity, original, proposed in ((3, '审批人为部门经理😀。\n', '审批人为项目负责人。\n'),
                                                     (5, '待确认。\n', '时限待确认。\n'))]}


async def settle(worker):
    due = monotonic() + 10
    while worker.live_run_ids and monotonic() < due:
        await asyncio.sleep(0.01)
    if worker.live_run_ids:
        raise AssertionError('Actual worker did not settle')


async def run(checker, client, database, req, current, chat, counter, app, branch):
    entered, release, cancel_entered = Event(), Event(), Event()
    receipts = []; gate_states = []; late_errors = []
    cancel_committed = Event()
    original_handle_error = chat.handle_error
    original_persist = orchestrator.persist_ai_result
    original_validate = result_persistence.validate_business_output
    original_cancel = commands.cancel_guide_run
    def before_persist(*args, **kwargs):
        if kwargs['catalog'].freeze('MODIFY', 'USER_INSTRUCTION').function_type == args[1]['trusted_output'].function_type:
            receipts.append(args[1]); entered.set()
            if not release.wait(10):
                raise AssertionError('Before-C07 barrier timed out')
        return original_persist(*args, **kwargs)
    def after_gate(connection, **kwargs):
        step = connection.execute('SELECT current_step FROM guide_runs WHERE id=?', (kwargs['actual']['run']['id'],)).fetchone()[0]
        if step == 'PERSISTING':
            gate_states.append(step); entered.set()
            if not release.wait(10):
                raise AssertionError('PERSISTING native transaction barrier timed out')
        return original_validate(connection, **kwargs)
    def concurrent_cancel(*args, **kwargs):
        cancel_entered.set()
        return original_cancel(*args, **kwargs)
    # For late network response the fully valid candidate bytes are withheld on
    # the actual TCP server until logical cancellation commits and closes socket.
    late = branch == 'LATE_TCP'
    if late:
        chat.entered.clear()
        chat.inspect_request = lambda: (entered.set(), release.wait(10))
        def classify_expected_peer_close(request, address):
            error = sys.exception()
            if cancel_committed.is_set() and isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
                late_errors.append(type(error).__name__)
                chat.entered.set()
            else:
                original_handle_error(request, address)
        chat.handle_error = classify_expected_peer_close
    checker.queue_output(chat, suggestions(current))
    target = 'backend.app.guide.orchestrator.persist_ai_result' if branch == 'CANCEL_FIRST' else 'backend.app.guide.result_persistence.validate_business_output'
    forwarded = before_persist if branch == 'CANCEL_FIRST' else after_gate
    try:
        with patch(target, new=forwarded) if not late else patch('backend.app.guide.result_persistence.validate_business_output', new=original_validate):
            accepted = (await checker.request(client, 'POST', f'/requirements/{req}/guide-runs', status=202,
                                body={'expected_version': current['content_version'], 'action_type': 'MODIFY',
                                      'instruction': '提出两条审批修改建议。', 'scope_type': 'DOCUMENT',
                                      'source_type': 'USER_INSTRUCTION'}, key=str(uuid4())))['data']
            identity = accepted['guide_run']['id']
            checker.check('Actual selected transport/SQL stage reached deterministic native barrier',
                          await asyncio.to_thread(entered.wait, 5))
            cancel_path = f'/guide-runs/{identity}/cancel'
            if branch == 'PERSIST_FIRST':
                with patch('backend.app.guide.commands.cancel_guide_run', new=concurrent_cancel):
                    cancellation = asyncio.create_task(checker.request(client, 'POST', cancel_path, status=409, key=str(uuid4())))
                    checker.check('Real HTTP cancellation entered native C03 while C07 transaction holds PERSISTING',
                                  await asyncio.to_thread(cancel_entered.wait, 5) and gate_states == ['PERSISTING'] and not cancellation.done())
                    release.set()
                    rejected = await cancellation
                checker.check('PERSISTING wins and cancellation returns safe conflict', rejected['error']['code'] == 'STATE_CONFLICT')
                await checker.wait_run(client, identity, 'COMPLETED')
            else:
                cancellation = await checker.request(client, 'POST', cancel_path, key=str(uuid4()))
                checker.check('Cancellation commits first with no final result', cancellation['data']['status'] == 'CANCELLED')
                cancel_committed.set()
                release.set()
                if late:
                    checker.check('Actual late TCP reply attempt completed after committed cancellation', await asyncio.to_thread(chat.entered.wait, 2))
            await settle(app.state.walle_worker)
            root = (await checker.request(client, 'GET', f'/requirements/{req}'))['data']
            run = (await checker.request(client, 'GET', f'/guide-runs/{identity}'))['data']
            actual = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
            with database.transaction() as connection:
                stored_run = dict(connection.execute('SELECT * FROM guide_runs WHERE id=?', (identity,)).fetchone())
                audits = [dict(r) for r in connection.execute('SELECT * FROM llm_uses WHERE guide_run_id=?', (identity,))]
                assistants = [dict(r) for r in connection.execute("SELECT * FROM conversation_messages WHERE guide_run_id=? AND role='ASSISTANT'", (identity,))]
                batches = [dict(r) for r in connection.execute('SELECT * FROM suggestion_batches WHERE guide_run_id=?', (identity,))]
            checker.check('Competing terminal paths never write CURRENT', actual == current)
            checker.check('Actual attempted Chat audit retained, no retry', len(audits) == 1
                          and len(chat.receipts) == len(counter.server.receipts) == 2)
            if branch == 'PERSIST_FIRST':
                checker.check('Only actual C07 result wins with one batch/assistant and matching occupancy',
                              run['status'] == 'COMPLETED' and stored_run['final_result_json'] is not None
                              and len(assistants) == len(batches) == 1 and batches[0]['status'] == 'PENDING'
                              and root['document_work_state'] == 'SUGGESTION_REVIEWING'
                              and root['active_operation_id'] == batches[0]['id'])
            else:
                checker.check('Cancel wins with no late final result/message/batch and releases occupancy',
                              run['status'] == 'CANCELLED' and stored_run['final_result_json'] is None
                              and assistants == batches == [] and root['document_work_state'] == 'IDLE'
                              and root['active_operation_id'] is None)
                if branch == 'CANCEL_FIRST':
                    checker.check('Already incurred successful full validation/usage preserved after cancellation',
                                  audits[0]['call_status'] == audits[0]['parse_status'] == audits[0]['validation_status'] == 'SUCCEEDED'
                                  and audits[0]['input_tokens'] == 123 and audits[0]['output_tokens'] == 10 and len(receipts) == 1)
                    before = checker.database_facts(database)
                    late_result = await asyncio.to_thread(original_persist, database, receipts[0],
                                        process_lock=app.state.walle_worker.process_lock,
                                        profile=ModelProfile(KEY), catalog=app.state.walle_runtime.catalog)
                    checker.check('Late already signed receipt rejected without any stored effect',
                                  late_result['code'] == 'STATE_CONFLICT' and before == checker.database_facts(database))
                else:
                    checker.check('Late withheld TCP result cannot be validated/adopted; usage remains unknown',
                                  audits[0]['call_status'] == 'CANCELLED' and audits[0]['input_tokens'] is None
                                  and audits[0]['output_tokens'] is None and audits[0]['trusted_output_json'] is None)
                before = checker.database_facts(database)
                repeated = await checker.request(client, 'POST', cancel_path, key=str(uuid4()))
                after = checker.database_facts(database)
                new_rows = [row for row in after if row not in before]
                checker.check('New-key cancellation adds only its successful receipt, preserves all terminal business facts/times',
                              repeated['data'] == cancellation['data'] and len(new_rows) == 1
                              and new_rows[0].startswith('INSERT INTO "idempotency_records"')
                              and [row for row in after if row not in new_rows] == before)

            checker.record['late_provider_peer_closed_errors'] = list(late_errors)
            checker.record['unexpected_controlled_server_errors'] = list(chat.errors)
            checker.check('Expected late socket close remains explicit and all unexpected server errors rejected',
                          all(e in ('ConnectionResetError', 'BrokenPipeError', 'ConnectionAbortedError') for e in late_errors) and len(late_errors) <= 1 and chat.errors == [])
            checker.record['late_provider_peer_closed_errors'] = late_errors
            checker.record['gate_branch'] = branch
            checker.record['gate_states_inside_native_transaction'] = gate_states
            checker.record['actual_local_count_requests'] = len(counter.server.receipts)
            checker.record['actual_local_chat_requests'] = len(chat.receipts)
    finally:
        release.set()
