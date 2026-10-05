import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ManualDraftAutosave } from '../src/documents/autosave.ts';
import { ApiUnknown, ApiRejected } from '../src/api/client.ts';

// Controller-only diagnostic ports. Real Milkdown/SQLite receipt adoption is
// covered independently in the browser; these do not model provenance.
const at = '2026-10-05T10:40:00.000Z';
const pair = text => ({ markdown_content: text, block_state_json: { schema_version: 1, next_block_id: 1, blocks: [] } });
const draft = (text = 'initial', version = 1) => ({ id: 2, requirement_id: 1, document_type: 'MANUAL_DRAFT', content_version: version, created_at: at, updated_at: at, ...pair(text) });
function ledger(document) {
  const port = { currentSnapshot: pair(document.markdown_content), savedVersion: document.content_version, active: null, proofs: new Set(),
    beginSave() { assert.equal(this.active, null); const ticket = Object.freeze({ requirement_id: 1, expected_version: this.savedVersion, ...this.currentSnapshot }); this.active = ticket; this.proofs.add(ticket); return ticket; },
    suspendSave(ticket) { assert.equal(this.active, ticket); this.active = null; },
    rejectSave(ticket) { assert(this.proofs.delete(ticket)); if (this.active === ticket) this.active = null; },
    acknowledgeSave(ticket, value) { assert(this.proofs.has(ticket)); assert.equal(value.content_version, ticket.expected_version + 1); assert.equal(value.markdown_content, ticket.markdown_content); this.savedVersion = value.content_version; this.active = null; this.proofs.clear(); return this.currentSnapshot; } };
  return port;
}
function clock() {
  const timers = [];
  return { timers, schedule(callback, delay) { const timer = { callback, delay, cancelled: false }; timers.push(timer); return () => { timer.cancelled = true; }; },
    fire(delay) { const timer = timers.find(item => !item.cancelled && item.delay === delay); assert(timer, `missing ${delay} timer`); timer.cancelled = true; timer.callback(); },
    live() { return timers.filter(timer => !timer.cancelled).map(timer => timer.delay); } };
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const settle = async () => { for (let count = 0; count < 25; count++) await Promise.resolve(); };
function setup(api) {
  const initial = draft(), session = ledger(initial), timing = clock(), writes = [], clears = [];
  const cache = { async put(...args) { writes.push(args); return true; }, async clearIfRevision(...args) { clears.push(args); return true; } };
  const controller = new ManualDraftAutosave(initial, session, api, cache, timing);
  const edit = text => { session.currentSnapshot = pair(text); controller.changed(); };
  return { controller, session, timing, writes, clears, edit };
}

test('idle2sec and maximum10sec send a complete pair, continuous edits keep the original maximum deadline', async () => {
  const sent = [], rig = setup({ async save(ticket) { sent.push(ticket); return draft(ticket.markdown_content, ticket.expected_version + 1); }, async read() { return draft(); } });
  rig.edit('first'); rig.edit('second'); assert.deepEqual(rig.timing.live(), [10000, 2000]);
  rig.timing.fire(10000); await settle(); assert.equal(sent.length, 1); assert.equal(sent[0].markdown_content, 'second');
  assert.equal(rig.controller.state.status, 'SAVED'); assert.equal(rig.controller.state.confirmed_version, 2); assert.deepEqual(rig.timing.live(), []);
  rig.edit('third'); rig.timing.fire(2000); await settle(); assert.equal(sent[1].expected_version, 2); rig.controller.dispose();
});
test('one in-flight write, many edits coalesce to newest and old success never overwrites current local content', async () => {
  const first = deferred(), sent = []; let active = 0, peak = 0;
  const rig = setup({ async save(ticket) { sent.push(ticket); active++; peak = Math.max(peak, active); const value = sent.length === 1 ? await first.promise : draft(ticket.markdown_content, ticket.expected_version + 1); active--; return value; }, async read() { return draft(); } });
  rig.edit('first'); const saving = rig.controller.flush(); await settle(); rig.edit('intermediate'); rig.edit('newest');
  assert.equal(sent.length, 1); first.resolve(draft('first', 2)); await saving;
  assert.equal(sent.length, 2); assert.equal(sent[1].markdown_content, 'newest'); assert.equal(sent[1].expected_version, 2); assert.equal(peak, 1);
  assert.equal(rig.controller.localSnapshot.markdown_content, 'newest'); assert.equal(rig.controller.state.status, 'SAVED'); assert.equal(rig.controller.state.confirmed_version, 3);
  assert.equal(rig.clears.length, 1); assert.equal(rig.clears[0][2], 3); rig.controller.dispose();
});
test('lost response is read back against actual submitted snapshot before marking saved; no second write', async () => {
  let persisted = draft(), calls = 0;
  const rig = setup({ async save(ticket) { calls++; persisted = draft(ticket.markdown_content, 2); throw new ApiUnknown(true); }, async read() { return persisted; } });
  rig.edit('committed'); await rig.controller.flush(); assert.equal(calls, 1); assert.equal(rig.controller.state.status, 'SAVED'); assert.equal(rig.controller.state.confirmed_version, 2);
  assert.deepEqual(rig.timing.live(), []); rig.controller.dispose();
});
test('old GET retains earlier proof and retries newest at unchanged version; old write winning is acknowledged then latest sent', async () => {
  let persisted = draft(), calls = 0; const sent = [];
  const rig = setup({ async save(ticket) { sent.push(ticket); calls++; if (calls === 1) throw new ApiUnknown(true); persisted = draft(ticket.markdown_content, ticket.expected_version + 1); return persisted; }, async read() { return persisted; } });
  rig.edit('first'); await rig.controller.flush(); assert.equal(rig.controller.state.status, 'RETRYING'); assert.equal(rig.controller.state.confirmed_version, 1);
  rig.edit('newest'); assert.deepEqual(rig.timing.live(), [2000]);
  // Old native request commits after the old GET, before the next reconciliation.
  persisted = draft('first', 2); rig.timing.fire(2000); await settle();
  assert.equal(sent.length, 2); assert.equal(sent[1].markdown_content, 'newest'); assert.equal(sent[1].expected_version, 2);
  assert.equal(rig.controller.state.confirmed_version, 3); assert.equal(rig.controller.state.status, 'SAVED'); rig.controller.dispose();
});
test('old GET with newest retry racing old native commit: conflict read can adopt earlier real ticket, never an invented version', async () => {
  let persisted = draft(), calls = 0; const sent = [];
  const rig = setup({ async save(ticket) { sent.push(ticket); calls++; if (calls === 1) throw new ApiUnknown(true);
    if (calls === 2) { persisted = draft('first', 2); throw new ApiRejected('CONTENT_VERSION_CONFLICT', 'conflict', null, 'diagnostic', 409); }
    persisted = draft(ticket.markdown_content, ticket.expected_version + 1); return persisted; }, async read() { return persisted; } });
  rig.edit('first'); await rig.controller.flush(); rig.edit('newest'); rig.timing.fire(2000); await settle();
  assert.deepEqual(sent.map(value => value.expected_version), [1, 1, 2]); assert.deepEqual(sent.map(value => value.markdown_content), ['first', 'newest', 'newest']);
  assert.equal(rig.controller.state.status, 'SAVED'); assert.equal(rig.controller.state.confirmed_version, 3); rig.controller.dispose();
});
test('repeated unknown writes/read failure back off2/5/10/30 capped, keep confirmed version and latest local pair', async () => {
  let reads = 0; const rig = setup({ async save() { throw new ApiUnknown(true); }, async read() { reads++; if (reads > 1) throw new ApiUnknown(false); return draft(); } });
  rig.edit('unsynced'); await rig.controller.flush();
  for (const delay of [2000, 5000, 10000, 30000]) { assert.deepEqual(rig.timing.live(), [delay]); rig.timing.fire(delay); await settle(); }
  assert.deepEqual(rig.timing.live(), [30000]); assert.equal(rig.controller.state.status, 'UNKNOWN'); assert.equal(rig.controller.state.confirmed_version, 1); assert.equal(rig.controller.localSnapshot.markdown_content, 'unsynced'); rig.controller.dispose();
});
test('validation refusal stops retries until corrected; unrelated external version stops overwrite and retains local content', async () => {
  let calls = 0; const rig = setup({ async save(ticket) { if (++calls === 1) throw new ApiRejected('DOCUMENT_INVALID', 'invalid', null, 'diagnostic', 422); return draft(ticket.markdown_content, 2); }, async read() { return draft('external', 3); } });
  rig.edit('bad'); await rig.controller.flush(); assert.equal(rig.controller.state.status, 'VALIDATION_ERROR'); assert.deepEqual(rig.timing.live(), []);
  await rig.controller.flush(); assert.equal(calls, 1); rig.edit('corrected'); rig.timing.fire(2000); await settle(); assert.equal(rig.controller.state.status, 'SAVED'); rig.controller.dispose();
  const conflict = setup({ async save() { throw new ApiUnknown(true); }, async read() { return draft('external', 3); } });
  conflict.edit('local'); await conflict.controller.flush(); assert.equal(conflict.controller.state.status, 'CONFLICT'); assert.equal(conflict.controller.state.server_conflict.markdown_content, 'external');
  conflict.edit('newer local'); await conflict.controller.flush(); assert.equal(conflict.controller.localSnapshot.markdown_content, 'newer local'); assert.equal(conflict.controller.state.confirmed_version, 1); assert.deepEqual(conflict.timing.live(), []); conflict.controller.dispose();
});
test('freeze drains newest before completion, discard pauses and waits, disposal ignores late receipt without deleting cache', async () => {
  const first = deferred(), sent = []; const rig = setup({ async save(ticket) { sent.push(ticket); return sent.length === 1 ? first.promise : draft(ticket.markdown_content, 3); }, async read() { return draft(); } });
  rig.edit('one'); void rig.controller.flush(); await settle(); rig.edit('two'); const drain = rig.controller.freezeAndFlush();
  assert.throws(() => rig.edit('three'), /frozen/); first.resolve(draft('one', 2)); assert.equal(await drain, true); assert.equal(sent.length, 2); rig.controller.dispose();
  const held = deferred(); let calls = 0;
  const paused = setup({ async save() { calls++; return held.promise; }, async read() { return draft(); } });
  paused.edit('one'); void paused.controller.flush(); await settle(); paused.edit('two'); const wait = paused.controller.pauseAndWait(); held.resolve(draft('one', 2)); await wait;
  await paused.controller.flush(); assert.equal(calls, 1); assert.equal(paused.controller.state.accepting_input, false); paused.controller.dispose();
  const late = deferred(), disposed = setup({ async save() { return late.promise; }, async read() { return draft(); } });
  disposed.edit('retain'); const pending = disposed.controller.flush(); await settle(); disposed.controller.dispose(); late.resolve(draft('retain', 2)); await pending;
  assert.equal(disposed.controller.state.status, 'CLOSED'); assert.equal(disposed.controller.state.confirmed_version, 1); assert.equal(disposed.clears.length, 0);
});
