import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FormationReadOwner } from '../src/formation/read-owner.ts';
import { ApiRejected, ApiUnknown } from '../src/api/client.ts';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
const envelope = (data) => ({
  data,
  status: 200,
  meta: { request_id: '00000000-0000-4000-8000-000000000001' },
});
const summary = (f = 1, documentId = 7) => ({
  document_id: documentId,
  view_schema: 'formation_read_v21_1',
  exists: f !== null,
  formation_version: f,
  goal: f === null ? null : { version: 1, text: '完成设计', source_refs: [] },
  current_step_ref: null,
  active_branch_ref: null,
  counts: {
    steps: { PLANNED: f === null ? 0 : 1, IN_PROGRESS: 0, PAUSED: 0, COMPLETED: 0, CANCELLED: 0 },
    branches: { OPEN: 0, RESOLVED: 0, DEFERRED: 0, DROPPED: 0 },
    issues: { OPEN: 0, RESOLVED: 0, DEFERRED: 0, DROPPED: 0 },
    proposals: { PENDING: 0, DEFERRED: 0, APPLIED: 0, SUPERSEDED: 0 },
    pending_review_artifacts: 0,
  },
  availability: [],
});
const page = (f = 1, refs = ['s1'], documentId = 7) =>
  envelope({
    document_id: documentId,
    formation_version: f,
    kind: 'steps',
    items: refs.map((ref) => ({ step_ref: ref })),
    total: refs.length,
  });
const detail = (ref = 's1') => envelope({ step_ref: ref });
const stale = () =>
  new ApiRejected(
    'STATE_CONFLICT',
    '路线已变化',
    { reason: 'PATH_CHANGED' },
    '00000000-0000-4000-8000-000000000001',
    409,
  );
const tick = () => new Promise((resolve) => setImmediate(resolve));
function setup(overrides = {}, documentId = 7) {
  const calls = [];
  const api = {
    async getFormationSummary(...args) {
      calls.push(['summary', ...args]);
      return envelope(summary(1, documentId));
    },
    async getFormationSteps(...args) {
      calls.push(['page', ...args]);
      return page(1, ['s1'], documentId);
    },
    async getFormationStep(...args) {
      calls.push(['detail', ...args]);
      return detail(args[2]);
    },
    ...overrides,
  };
  return { owner: new FormationReadOwner(1, documentId, api), calls };
}

test('uninitialized summary makes no formation page/detail calls or invented selection', async () => {
  const { owner, calls } = setup({
    async getFormationSummary() {
      calls.push(['summary']);
      return envelope(summary(null));
    },
  });
  assert.equal(calls.length, 0);
  assert.equal(await owner.refresh(), true);
  assert.equal(owner.getSnapshot().summary.data.exists, false);
  assert.equal(owner.getSnapshot().page.phase, 'IDLE');
  assert.equal(await owner.selectStep('s9'), false);
  assert.equal(owner.getSnapshot().selected_step_ref, 's9');
  assert.equal(owner.getSnapshot().detail.phase, 'ERROR');
  assert.deepEqual(
    calls.map((call) => call[0]),
    ['summary'],
  );
});

test('late page cannot overwrite a newer cancelled filter or reset selection', async () => {
  const first = deferred(),
    second = deferred();
  let count = 0;
  const { owner } = setup({
    getFormationSteps() {
      return ++count === 1 ? first.promise : second.promise;
    },
  });
  const refresh = owner.refresh();
  await tick();
  const filter = owner.setShowCancelled(true);
  second.resolve(page(1, ['s2']));
  assert.equal(await filter, true);
  first.resolve(page(1, ['s1']));
  assert.equal(await refresh, false);
  assert.equal(owner.getSnapshot().show_cancelled, true);
  assert.deepEqual(owner.getSnapshot().page.data.data.items, [{ step_ref: 's2' }]);
  assert.equal(owner.getSnapshot().selected_step_ref, null);
});

test('late selected detail cannot replace another selection, including steps outside the page', async () => {
  const first = deferred(),
    second = deferred();
  const { owner, calls } = setup({
    getFormationStep(...args) {
      calls.push(['detail', ...args]);
      return args[2] === 's8' ? first.promise : second.promise;
    },
  });
  await owner.refresh();
  const a = owner.selectStep('s8'),
    b = owner.selectStep('s9');
  second.resolve(detail('s9'));
  assert.equal(await b, true);
  first.resolve(detail('s8'));
  assert.equal(await a, false);
  assert.equal(owner.getSnapshot().detail.data.step_ref, 's9');
  assert.equal(owner.getSnapshot().selected_step_ref, 's9');
  assert.equal(calls.filter((call) => call[0] === 'detail').length, 2);
});

test('refresh errors preserve last successful page/detail and leave no loading state', async () => {
  let rejectSummary = false;
  const oldDetail = deferred();
  const { owner } = setup({
    async getFormationSummary() {
      if (rejectSummary) throw new ApiUnknown(false);
      return envelope(summary());
    },
    getFormationStep(_r, _d, ref) {
      return ref === 's2' ? oldDetail.promise : Promise.resolve(detail(ref));
    },
  });
  await owner.refresh();
  await owner.selectStep('s1');
  const lastPage = owner.getSnapshot().page.data;
  const lastDetail = owner.getSnapshot().detail.data;
  const pending = owner.selectStep('s2');
  rejectSummary = true;
  assert.equal(await owner.refresh(), false);
  assert.equal(owner.getSnapshot().page.data, lastPage);
  assert.equal(owner.getSnapshot().page.phase, 'ERROR');
  assert.equal(owner.getSnapshot().detail.phase, 'ERROR');
  assert.equal(owner.getSnapshot().detail.data, null);
  oldDetail.resolve(detail('s2'));
  assert.equal(await pending, false);
  assert.equal(lastDetail.step_ref, 's1');
});

test('PATH_CHANGED recovers once, drops obsolete cursor and preserves explicit off-page selection', async () => {
  let summaryCalls = 0,
    pageCalls = 0;
  const requests = [];
  const { owner } = setup({
    async getFormationSummary() {
      return envelope(summary(++summaryCalls === 1 ? 1 : 2));
    },
    async getFormationSteps(_r, _d, query) {
      requests.push(query);
      if (++pageCalls === 2) throw stale();
      return page(query.known_f);
    },
  });
  await owner.refresh();
  await owner.selectStep('s19');
  assert.equal(await owner.loadPage('opaque-current-page'), true);
  assert.equal(summaryCalls, 2);
  assert.equal(pageCalls, 3);
  assert.equal(requests[2].cursor, undefined);
  assert.equal(requests[2].known_f, 2);
  assert.equal(owner.getSnapshot().page_cursor, null);
  assert.equal(owner.getSnapshot().selected_step_ref, 's19');
  assert.equal(owner.getSnapshot().detail.data.step_ref, 's19');
});

test('repeated stale reads stop after one recovery with explicit error and retained data', async () => {
  let summaries = 0,
    fail = false,
    pages = 0;
  const { owner } = setup({
    async getFormationSummary() {
      summaries++;
      return envelope(summary(summaries));
    },
    async getFormationSteps(_r, _d, query) {
      pages++;
      if (fail) throw stale();
      return page(query.known_f);
    },
  });
  await owner.refresh();
  const previous = owner.getSnapshot().page.data;
  fail = true;
  assert.equal(await owner.loadPage('next-page'), false);
  assert.equal(summaries, 2);
  assert.equal(pages, 3);
  assert.equal(owner.getSnapshot().page.phase, 'ERROR');
  assert.equal(owner.getSnapshot().page.data, previous);
});

test('disposal aborts its reads and ignores late responses without touching another document owner', async () => {
  const pending = deferred();
  let signal;
  const first = setup({
    getFormationSummary(_r, _d, value) {
      signal = value;
      return pending.promise;
    },
  });
  const other = setup({}, 8);
  const read = first.owner.refresh();
  let notifications = 0;
  first.owner.subscribe(() => notifications++);
  first.owner.dispose();
  assert.equal(signal.aborted, true);
  await other.owner.refresh();
  pending.resolve(envelope(summary()));
  assert.equal(await read, false);
  assert.equal(notifications, 0);
  assert.equal(other.owner.getSnapshot().summary.data.document_id, 8);
  assert.equal(await first.owner.refresh(), false);
  assert.equal(await first.owner.selectStep('s1'), false);
});

test('detail failure is reported by refresh while successful page data stays available', async () => {
  let fail = false;
  const { owner } = setup({
    async getFormationStep(_r, _d, ref) {
      if (fail) throw new ApiUnknown(false);
      return detail(ref);
    },
  });
  await owner.refresh();
  await owner.selectStep('s1');
  const previous = owner.getSnapshot().detail.data;
  fail = true;
  assert.equal(await owner.refresh(), false);
  assert.equal(owner.getSnapshot().page.phase, 'READY');
  assert.equal(owner.getSnapshot().detail.phase, 'ERROR');
  assert.equal(owner.getSnapshot().detail.data, previous);
});

test('wrong-document summary is a read error, never an empty formation', async () => {
  const { owner, calls } = setup({
    async getFormationSummary() {
      return envelope(summary(null, 8));
    },
  });
  assert.equal(await owner.refresh(), false);
  assert.equal(owner.getSnapshot().summary.phase, 'ERROR');
  assert.equal(owner.getSnapshot().summary.data, null);
  assert.equal(calls.length, 0);
});

test('revealing a step follows result cursors and keeps the viewing selection and focus separate', async () => {
  const cursors = [];
  const { owner } = setup({
    async getFormationSteps(_req, _doc, query) {
      cursors.push(query.cursor ?? null);
      const current = query.cursor === 'next' ? 's9' : 's1';
      return {
        ...page(1, [current]),
        meta: { pagination: { next_cursor: current === 's1' ? 'next' : null } },
      };
    },
  });
  assert(await owner.refresh());
  assert(await owner.selectStep('s1'));
  assert(await owner.revealStep('s9'));
  const located = owner.getSnapshot();
  assert.deepEqual(cursors, [null, null, 'next']);
  assert.equal(located.page_cursor, 'next');
  assert.equal(located.page.data.data.items[0].step_ref, 's9');
  assert.equal(located.selected_step_ref, 's1');
  assert.equal(located.summary.data.current_step_ref, null);

  assert.equal(await owner.revealStep('s20'), false);
  const missing = owner.getSnapshot();
  assert.equal(missing.page_cursor, 'next');
  assert.equal(missing.page.data, located.page.data);
  assert.equal(missing.page.phase, 'ERROR');
  assert.match(missing.page.error, /未找到/);
  owner.dispose();
});
