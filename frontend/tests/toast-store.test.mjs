import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ToastStore } from '../src/shared/toast-store.ts';
function clock() {
  let now = 0; const timers = [];
  return { now: () => now, schedule(callback, delay) { const timer = { at: now + delay, callback, cancelled: false }; timers.push(timer); return () => { timer.cancelled = true; }; },
    advance(milliseconds) { const target = now + milliseconds; for (;;) { const next = timers.filter(timer => !timer.cancelled && timer.at <= target).sort((a,b) => a.at-b.at)[0]; if (!next) break; now = next.at; next.cancelled = true; next.callback(); } now = target; },
    live: () => timers.filter(timer => !timer.cancelled) };
}
test('success/info expire3sec, failure5sec; closing has no business event', () => {
  const time = clock(), store = new ToastStore(time); store.push('success', '保存确认'); store.push('info', '提示'); store.push('error', '失败确认');
  time.advance(2999); assert.equal(store.getSnapshot().length, 3); time.advance(1); assert.deepEqual(store.getSnapshot().map(value => value.message), ['失败确认']);
  time.advance(2000); assert.equal(store.getSnapshot().length, 0); store.dispose();
});
test('hover and focus pause independently; departure resumes remaining duration rather than restarting', () => {
  const time = clock(), store = new ToastStore(time), id = store.push('success', '保存确认'); time.advance(1000); store.pause(id, 'hover'); store.pause(id, 'focus');
  time.advance(10000); assert.equal(store.getSnapshot().length, 1); store.resume(id, 'hover'); assert.equal(time.live().length, 0);
  time.advance(1000); store.resume(id, 'focus'); time.advance(1999); assert.equal(store.getSnapshot().length, 1); time.advance(1); assert.equal(store.getSnapshot().length, 0); store.dispose();
});
test('same type/text merges and resets while visible or paused; differing type stays distinct', () => {
  const time = clock(), store = new ToastStore(time), first = store.push('info', '同文'); time.advance(2000);
  assert.equal(store.push('info', '同文'), first); assert.equal(store.getSnapshot().length, 1); time.advance(2000); assert.equal(store.getSnapshot().length, 1);
  store.pause(first, 'hover'); store.push('info', '同文'); time.advance(10000); store.resume(first, 'hover'); time.advance(2999); assert.equal(store.getSnapshot().length, 1);
  store.push('error', '同文'); assert.equal(store.getSnapshot().length, 2); time.advance(1); assert.equal(store.getSnapshot()[0].type, 'error'); store.dispose();
});
test('fourth new toast evicts only oldest display; obsolete timer/manual close/dispose cannot remove newer toast', () => {
  const time = clock(), store = new ToastStore(time), ids = [];
  for (const text of ['one','two','three','four']) ids.push(store.push('info', text));
  assert.deepEqual(store.getSnapshot().map(value => value.message), ['four','three','two']); assert.equal(time.live().length, 3);
  store.dismiss(ids[0]); assert.equal(store.getSnapshot().length, 3); store.dismiss(ids[2]); assert.deepEqual(store.getSnapshot().map(value => value.message), ['four','two']);
  store.dispose(); time.advance(10000); assert.deepEqual(store.getSnapshot(), []); assert.equal(time.live().length, 0); assert.throws(() => store.push('info','late'));
});
