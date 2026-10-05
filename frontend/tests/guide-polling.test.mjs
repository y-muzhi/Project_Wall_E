import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GuideRunPolling } from '../src/guide/polling.ts';
import { guideRun } from '../src/api/models.ts';

const at = '2026-10-05T10:00:00.000Z';
function run(status = 'RUNNING', changes = {}) {
  return guideRun({ id: 2, requirement_id: 1, action_type: 'ASK', function_type: 'ANSWER_REQUIREMENT', source_type: 'USER_INSTRUCTION', source_id: null,
    scope: { scope_type: 'DOCUMENT', scope_ref: null }, status, current_step: status === 'RUNNING' ? 'PREPARING' : status === 'WAITING_USER' ? 'WAITING_USER' : 'FINISHED',
    final_result: status === 'COMPLETED' ? { summary: '完成', assistant_message_id: 1, current_document_version: null, suggestion_batch_id: null } : null,
    suggestion_batch_id: null, latest_assistant_message_id: null, error_code: status === 'FAILED' ? 'CONFIG_INVALID' : null,
    error_message: status === 'FAILED' ? '配置缺失' : null, cancel_reason: status === 'CANCELLED' ? 'USER_REQUESTED' : null,
    retry_of_guide_run_id: null, created_at: at, started_at: at, waiting_user_at: status === 'WAITING_USER' ? at : null,
    ended_at: ['COMPLETED', 'FAILED', 'CANCELLED'].includes(status) ? at : null, updated_at: at, ...changes });
}
function timing() {
  const queue = [], delays = [];
  return { delays, queue, schedule(callback, delay) { const entry = { callback, delay, cancelled: false }; queue.push(entry); delays.push(delay); return () => { entry.cancelled = true; }; },
    next() { const entry = queue.find(value => !value.cancelled); assert(entry, 'Expected scheduled poll'); entry.cancelled = true; entry.callback(); } };
}
const flush = async () => { for (let index = 0; index < 12; index++) await Promise.resolve(); };
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { resolve, reject, promise }; }

test('hiding or disposing before the start microtask prevents even an owned read from starting', async () => {
  for (const operation of ['hide', 'dispose']) {
    let calls = 0; const clock = timing();
    const poll = new GuideRunPolling(2, async () => { calls++; return run(); }, clock);
    poll.setVisible(true); operation === 'hide' ? poll.setVisible(false) : poll.dispose(); await flush();
    assert.equal(calls, 0); assert.equal(poll.state.querying, false); assert.equal(clock.queue.length, 0);
    poll.dispose();
  }
});

test('RUNNING polls every one second after confirmed reads; repeated refresh coalesces behind one pending read', async () => {
  const clock = timing(), first = deferred(); let calls = 0, active = 0, peak = 0;
  const poll = new GuideRunPolling(2, async () => { active++; peak = Math.max(peak, active); calls++; const value = calls === 1 ? await first.promise : run(); active--; return value; }, clock);
  poll.setVisible(true); await flush(); assert.equal(calls, 1); assert.equal(poll.state.querying, true);
  poll.refresh(); poll.refresh(); poll.refresh(); await flush(); assert.equal(calls, 1);
  first.resolve(run()); await flush(); assert.equal(calls, 2); assert.equal(peak, 1); assert.deepEqual(clock.delays, [1000]);
  clock.next(); await flush(); assert.equal(calls, 3); assert.deepEqual(clock.delays, [1000, 1000]); poll.dispose();
});
test('failure backoff is 2/5/10/30 seconds then capped30, retaining last confirmed RUNNING; success resets cadence', async () => {
  const clock = timing(); let calls = 0;
  const poll = new GuideRunPolling(2, async () => { calls++; if (calls > 1 && calls < 7) throw new Error('network fixture'); return run(); }, clock);
  poll.setVisible(true); await flush(); const confirmed = poll.state.confirmed;
  for (let index = 0; index < 5; index++) { clock.next(); await flush(); assert.equal(poll.state.confirmed, confirmed); assert.equal(poll.state.connection_error, true); }
  assert.deepEqual(clock.delays, [1000, 2000, 5000, 10000, 30000, 30000]);
  clock.next(); await flush(); assert.equal(poll.state.connection_error, false); assert.equal(clock.delays.at(-1), 1000); poll.dispose();
});
test('WAITING_USER and every terminal state stop; explicit accepted continuation refresh reads the same run again', async () => {
  for (const status of ['WAITING_USER', 'COMPLETED', 'FAILED', 'CANCELLED']) {
    const clock = timing(); let calls = 0;
    const poll = new GuideRunPolling(2, async () => ++calls === 1 ? run(status) : run(), clock);
    poll.setVisible(true); await flush(); assert.equal(poll.state.polling, false); assert.equal(clock.queue.length, 0);
    poll.refresh(); await flush(); assert.equal(poll.state.confirmed.status, 'RUNNING'); assert.deepEqual(clock.delays, [1000]); poll.dispose();
  }
});
test('hidden page aborts only its owned read; late response ignored and resume waits/coalesces before fresh query', async () => {
  const clock = timing(), old = deferred(); let calls = 0, signal;
  const poll = new GuideRunPolling(2, async (_, owned) => { calls++; signal = owned; return calls === 1 ? old.promise : run(); }, clock);
  poll.setVisible(true); await flush(); const original = signal;
  poll.setVisible(false); assert.equal(original.aborted, true); assert.equal(poll.state.polling, false);
  poll.setVisible(true); await flush(); assert.equal(calls, 1);
  old.resolve(run('FAILED')); await flush(); assert.equal(calls, 2); assert.equal(poll.state.confirmed.status, 'RUNNING'); assert.equal(signal.aborted, false); poll.dispose();
});
test('dispose cancels timer/read and ignores late failures without changing another controller or business state', async () => {
  const clock = timing(), old = deferred(); let calls = 0, signal;
  const poll = new GuideRunPolling(2, async (_, owned) => { signal = owned; calls++; return old.promise; }, clock);
  poll.setVisible(true); await flush(); poll.dispose(); old.reject(new Error('late')); await flush();
  assert.equal(signal.aborted, true); assert.equal(calls, 1); assert.equal(poll.state.confirmed, null); assert.equal(poll.state.connection_error, false); assert.equal(clock.queue.length, 0);
  poll.refresh(); poll.setVisible(true); await flush(); assert.equal(calls, 1);
});
test('wrong run identity is a query failure; a subscribed refresh cannot start a simultaneous read', async () => {
  const clock = timing(); let calls = 0, refresh = true;
  const poll = new GuideRunPolling(2, async () => { calls++; return calls === 1 ? run('RUNNING', { id: 3 }) : run('WAITING_USER'); }, clock);
  poll.subscribe(state => { if (state.querying && refresh) { refresh = false; poll.refresh(); } });
  poll.setVisible(true); await flush(); assert.equal(calls, 2); assert.equal(poll.state.confirmed.status, 'WAITING_USER'); assert.equal(poll.state.connection_error, false); poll.dispose();
});
