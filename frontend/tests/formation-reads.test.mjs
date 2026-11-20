import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown, ApiRejected, exact, positiveInteger } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import { discussionState } from '../src/api/models.ts';
import { formationSummary, resultRef, stepView } from '../src/api/formation-values.ts';
import { FORMATION_READ_ERRORS, FORMATION_PREVIEW_ERRORS } from '../src/api/formation-errors.ts';

const key = '00000000-0000-4000-8000-000000000001';
const at = '2026-11-16T06:00:00.000Z';
const base = '/api/v1/requirements/1/documents/7/formation';
const response = (data, pagination) =>
  new Response(
    JSON.stringify({
      success: true,
      data,
      error: null,
      meta: { request_id: key, ...(pagination === undefined ? {} : { pagination }) },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
const failure = (code, details, status = 409) =>
  new Response(
    JSON.stringify({
      success: false,
      data: null,
      error: { code, message: '当前状态不允许此操作', details },
      meta: { request_id: key },
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  );
const summary = (exists = false) => ({
  document_id: 7,
  view_schema: 'formation_read_v21_1',
  exists,
  formation_version: exists ? 1 : null,
  goal: exists ? { version: 1, text: '完成设计', source_refs: [] } : null,
  current_step_ref: null,
  active_branch_ref: null,
  counts: {
    steps: { PLANNED: exists ? 1 : 0, IN_PROGRESS: 0, PAUSED: 0, COMPLETED: 0, CANCELLED: 0 },
    branches: { OPEN: 0, RESOLVED: 0, DEFERRED: 0, DROPPED: 0 },
    issues: { OPEN: 0, RESOLVED: 0, DEFERRED: 0, DROPPED: 0 },
    proposals: { PENDING: 0, DEFERRED: 0, APPLIED: 0, SUPERSEDED: 0 },
    pending_review_artifacts: 0,
  },
  availability: [],
});
const discussion = () => ({
  schema_version: 2,
  focus_topic_ref: null,
  topics: [],
  evidence: [],
  pending_user_message_ids: [],
  binding: { target_document_id: null, source_refs: [], scope: null, document_kind: null },
  dispositions: [],
  last_step: null,
  counters: { topic: 1, evidence: 1 },
});
const root = () => ({
  id: 1,
  requirement_no: 'REQ000001',
  title: '需求',
  requirement_type: 'NEW',
  status: 'PLANNING',
  metadata_version: 1,
  initial_message_id: 1,
  discussion_version: 1,
  document_work_state: 'IDLE',
  active_operation_type: null,
  active_operation_id: null,
  created_at: at,
  updated_at: at,
  completed_at: null,
  closed_at: null,
  state_started_at: null,
});
const detail = (formation = summary()) => ({
  requirement: root(),
  documents: [
    {
      id: 7,
      requirement_id: 1,
      name: '设计',
      document_kind: 'DESIGN',
      document_type: 'CURRENT',
      metadata_version: 1,
      content_version: 1,
      current_revision_id: 3,
      confirmed_revision_id: null,
      archived_at: null,
      updated_at: at,
      source_status: 'UNCHANGED',
    },
  ],
  discussion_summary: {
    discussion_version: 1,
    focus_topic_ref: null,
    focus_title: null,
    next_step: null,
    pending_count: 0,
  },
  discussion: {
    ...discussion(),
    ...(formation === undefined ? {} : { formation_summary: formation }),
  },
  active_operation: null,
});
const step = (ref = 's1') => ({
  step_ref: ref,
  definition_version: 1,
  title: '明确范围',
  status: 'PLANNED',
  position: 1,
  expected_results: [{ result_ref: ref + '.o1', description: '设计成果', kind: 'CONTENT' }],
  relation_counts: {
    dependencies: 0,
    replaces: 0,
    topics: 0,
    issues: 0,
    branches: 0,
    artifacts: 0,
  },
  last_event: null,
  assessment: null,
  recommendation: null,
  availability: [{ action: 'START_STEP', available: true, reason: null }],
});
const page = (items = [step()]) => ({
  document_id: 7,
  formation_version: 1,
  kind: 'steps',
  items,
  total: items.length,
});
const pagination = (size = 20, next = null) => ({
  page_size: size,
  next_cursor: next,
  has_more: next !== null,
});
const readUnknown = (promise) =>
  assert.rejects(promise, (error) => error instanceof ApiUnknown && !error.mutation);

test('summary has one exact key set, zero facts for absent formation and no manufactured target', () => {
  const one = summary(),
    two = summary(true);
  assert.deepEqual(Object.keys(formationSummary(one)), Object.keys(formationSummary(two)));
  assert.equal(formationSummary(one).counts.steps.CANCELLED, 0);
  assert.equal(
    discussionState({ ...discussion(), formation_summary: one }).formation_summary.exists,
    false,
  );
  assert.equal(Object.hasOwn(discussionState(discussion()), 'formation_summary'), false);
  for (const mutate of [
    (row) => (row.target = {}),
    (row) => (row.formation_version = 1),
    (row) => (row.counts.issues.DROPPED = true),
    (row) => delete row.counts.proposals.SUPERSEDED,
    (row) => (row.counts.steps.PLANNED = 1),
  ]) {
    const bad = structuredClone(one);
    mutate(bad);
    assert.throws(() => formationSummary(bad));
  }
});

test('shared detail decoder accepts the new summary only for its explicitly requested document', async () => {
  const sent = [];
  let value = detail();
  const api = new WalleApi(
    new ApiClient(async (url, options) => {
      sent.push([url, options]);
      return response(value);
    }),
    {},
  );
  assert.equal((await api.getFormationSummary(1, 7)).data.exists, false);
  const url = new URL(sent[0][0], 'http://local.invalid');
  assert.equal(url.pathname, '/api/v1/requirements/1');
  assert.equal(url.searchParams.get('document_id'), '7');
  assert.equal(url.searchParams.get('expand'), 'discussion');
  assert.equal(sent[0][1].method, 'GET');
  value = detail({ ...summary(), document_id: 8 });
  await readUnknown(api.getFormationSummary(1, 7));
  value = detail();
  delete value.discussion.formation_summary;
  await readUnknown(api.getFormationSummary(1, 7)); // Older server is not "empty formation".
});

test('opaque cursor and variable page size have an explicit new transport without loosening legacy reads', async () => {
  const native = new ApiClient(async () => response({ id: 1 }, pagination(100, 'opaque-token')));
  const decode = (value) => ({ id: positiveInteger(exact(value, ['id']).id) });
  const result = await native.readFormation(base + '/steps', decode);
  assert.deepEqual(result.meta.pagination, pagination(100, 'opaque-token'));
  await readUnknown(native.read(base + '/steps', decode));
  const malformed = [
    { ...pagination(), page_size: 0 },
    { ...pagination(), page_size: 101 },
    { ...pagination(), next_cursor: 3, has_more: true },
    { ...pagination(), has_more: true },
    { ...pagination(), private_count: 2 },
  ];
  for (const meta of malformed)
    await readUnknown(
      new ApiClient(async () => response({ id: 1 }, meta)).readFormation(base + '/steps', decode),
    );
});

test('step pages enforce original document F kind identity and exact complete first page', async () => {
  let value = page(),
    meta = pagination(1);
  const api = new WalleApi(new ApiClient(async () => response(value, meta)), {});
  assert.equal(
    (await api.getFormationSteps(1, 7, { known_f: 1, limit: 1 })).data.items[0].step_ref,
    's1',
  );
  for (const mutate of [
    (row) => (row.document_id = 8),
    (row) => (row.formation_version = 2),
    (row) => (row.kind = 'issues'),
    (row) => (row.items[0].private_basis = {}),
    (row) => (row.total = 2),
  ]) {
    value = page();
    mutate(value);
    await readUnknown(api.getFormationSteps(1, 7, { known_f: 1, limit: 1 }));
  }
  value = page();
  meta = pagination(20);
  await readUnknown(api.getFormationSteps(1, 7, { known_f: 1, limit: 1 }));
});

test('new read filters refuse coercion and unrelated fields before sending any network request', async () => {
  let sent = 0;
  const api = new WalleApi(
    new ApiClient(async () => {
      sent++;
      return response(page(), pagination());
    }),
    {},
  );
  for (const query of [
    { limit: true },
    { limit: 101 },
    { include_cancelled: 'false' },
    { include_superseded: true },
    { state: 'OPEN' },
    { step_ref: 's1' },
    { known_f: 0 },
  ])
    await assert.rejects(async () => api.getFormationSteps(1, 7, query), TypeError);
  assert.equal(sent, 0);
  assert.throws(() => resultRef('s9007199254740992.o1'));
  assert.throws(() =>
    stepView({
      ...step(),
      expected_results: [{ result_ref: 's2.o1', description: '错属', kind: 'CONTENT' }],
    }),
  );
});

test('cursor forwarding preserves opaque bytes and never changes selected filters', async () => {
  let sent;
  const opaque = '服务端/原游标=a+💠';
  const api = new WalleApi(
    new ApiClient(async (url, options) => {
      sent = [url, options];
      return response(page([]), pagination(3));
    }),
    {},
  );
  await api.getFormationSteps(1, 7, {
    cursor: opaque,
    known_f: 1,
    limit: 3,
    include_cancelled: true,
  });
  const query = new URL(sent[0], 'http://local.invalid').searchParams;
  assert.equal(query.get('cursor'), opaque);
  assert.equal(query.get('include_cancelled'), 'true');
  assert.equal(sent[1].body, undefined);
  assert.equal(sent[1].headers['Idempotency-Key'], undefined);
});

test('formation state and limit errors use exact endpoint policies; private details remain unverifiable', async () => {
  const known = { reason: 'PATH_CHANGED', step_ref: null, proposal: null };
  const client = new ApiClient(async () => failure('STATE_CONFLICT', known));
  await assert.rejects(
    client.readFormation(base + '/steps', (x) => x, [], undefined, FORMATION_READ_ERRORS),
    (error) => error instanceof ApiRejected && error.details.reason === 'PATH_CHANGED',
  );
  const invalid = [
    { ...known, binding: {} },
    { ...known, reason: 'PRIVATE' },
    { ...known, step_ref: 's9007199254740992' },
    { ...known, proposal: { message_id: 1, card_key: 'x', payload: {} } },
  ];
  for (const details of invalid)
    await readUnknown(
      new ApiClient(async () => failure('STATE_CONFLICT', details)).readFormation(
        base + '/steps',
        (x) => x,
        [],
        undefined,
        FORMATION_READ_ERRORS,
      ),
    );
  const limited = new ApiClient(async () =>
    failure(
      'FORMATION_LIMIT_EXCEEDED',
      { resource_kind: 'CHANGE_COUNT', limit: 20, actual: 21 },
      422,
    ),
  );
  await assert.rejects(
    limited.previewFormation(
      base + '/path-preview',
      {},
      (x) => x,
      undefined,
      FORMATION_PREVIEW_ERRORS,
    ),
    (error) => error instanceof ApiRejected && error.details.actual === 21,
  );
  await readUnknown(
    limited.readFormation(base + '/steps', (x) => x, [], undefined, FORMATION_READ_ERRORS),
  );
});

test('keyless POST preview is a read, freezes its wire and does not enter mutation recovery', async () => {
  const calls = [];
  const client = new ApiClient(
    async (url, options) => {
      calls.push({ url, ...options });
      throw Error('offline lost read');
    },
    () => {
      throw Error('Preview must not allocate an idempotency key');
    },
  );
  const body = {
    expected_discussion_version: 1,
    discussion_command: { type: 'FORMATION', reason: '保留\r\n空白  ' },
  };
  const pending = client.previewFormation(base + '/path-preview', body, (x) => x);
  body.discussion_command.reason = '后来的草稿';
  await readUnknown(pending);
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].headers['Idempotency-Key'], undefined);
  assert.equal(JSON.parse(calls[0].body).discussion_command.reason, '保留\r\n空白  ');
  await assert.rejects(
    client.previewFormation('/api/v1/requirements/1', {}, (x) => x),
    TypeError,
  );
  await assert.rejects(
    client.readFormation(base + '/path-preview', (x) => x),
    TypeError,
  );
});

test('range lineage and dotted result paths preserve registered identity and reject arbitrary routes', async () => {
  const client = new ApiClient(async () => response({ id: 1 }));
  const decode = (value) => ({ id: positiveInteger(exact(value, ['id']).id) });
  assert.equal(
    (await client.readFormation(base + '/events/9/closure-items/RESULT/s1.o1/evidence', decode))
      .data.id,
    1,
  );
  await assert.rejects(
    client.readFormation(base + '/events/9/closure-items/RESULT/s1xo1/evidence', decode),
    TypeError,
  );
  await assert.rejects(client.readFormation(base + '/steps/../events', decode), TypeError);
  await assert.rejects(
    client.readFormation('https://remote.invalid' + base + '/steps', decode),
    TypeError,
  );
});
