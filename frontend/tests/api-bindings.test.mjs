import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ApiClient, ApiRejected, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';

const KEY = '00000000-0000-4000-8000-000000000001', REQUEST = '00000000-0000-4000-8000-000000000002';
const at = '2026-10-05T09:00:00.000Z';
const root = () => ({ id: 1, requirement_no: 'REQ000001', requirement_type: 'NEW', initialization_mode: 'IDEATION', title: '标题😀',
  template_key: 'new-requirement', template_version: 'v1', status: 'INITIALIZING', document_work_state: 'GUIDE_ACTIVE',
  active_operation_type: 'GUIDE_RUN', active_operation_id: 2, created_at: at, updated_at: at, completed_at: null, state_started_at: at });
const create = () => ({ title: '标题😀', requirement_type: 'NEW', template_key: 'new-requirement', template_version: 'v1', initial_idea: '原始想法', initialization_mode: 'IDEATION' });
const emptyState = { schema_version: 1, next_block_id: 1, blocks: [] };
const guide = { expected_version: 7, action_type: 'ASK', instruction: '提问', scope_type: 'DOCUMENT', source_type: 'USER_INSTRUCTION' };
const answer = { schema_version: 1, responses: [{ card_key: 'c', selected_option_keys: ['yes'], custom_answer: null, skipped: false }] };
const comment = { expected_content_version: 7, content: '评论', anchor_type: 'BLOCK', block_id: 3 };
const json = (data, status = 200, pagination) => new Response(JSON.stringify({ success: true, data, error: null,
  meta: { request_id: REQUEST, ...(pagination === undefined ? {} : { pagination }) } }), { status, headers: { 'Content-Type': 'application/json' } });
const rejected = () => new Response(JSON.stringify({ success: false, data: null,
  error: { code: 'VALIDATION_FAILED', message: '请求参数不合法', details: { field_errors: [{ field: 'body', reason: 'REQUIRED', message: '必须提供' }] } },
  meta: { request_id: REQUEST } }), { status: 422, headers: { 'Content-Type': 'application/json' } });
const api = (send, uuid = () => KEY) => new WalleApi(new ApiClient(send, uuid), undefined);

// Independent endpoint matrix from the public I01-I37 contracts. Transport
// responses here are explicit fixtures; this is not backend/page acceptance.
const cases = [
  ['I01', 'listRequirements', [{}], 'GET', '/requirements', null, false],
  ['I02', 'prepareCreateRequirement', [create()], 'POST', '/requirements', create(), true],
  ['I03', 'getRequirement', [1], 'GET', '/requirements/1', null, false],
  ['I04', 'prepareUpdateRequirement', [1, { title: '新标题' }], 'PATCH', '/requirements/1', { title: '新标题' }, false],
  ['I05', 'prepareCompleteInitialization', [1, 7], 'POST', '/requirements/1/complete-initialization', { expected_content_version: 7 }, true],
  ['I06', 'prepareCompleteRequirement', [1, 7], 'POST', '/requirements/1/complete', { expected_version: 7 }, true],
  ['I07', 'prepareReactivateRequirement', [1], 'POST', '/requirements/1/reactivate', null, true],
  ['I08', 'getCurrentDocument', [1], 'GET', '/requirements/1/current-document', null, false],
  ['I09', 'prepareStartManualDraft', [1, 7], 'POST', '/requirements/1/manual-draft', { expected_version: 7 }, true],
  ['I10', 'getManualDraft', [1], 'GET', '/requirements/1/manual-draft', null, false],
  ['I11', 'prepareSaveManualDraft', [1, { expected_version: 4, markdown_content: '', block_state_json: emptyState }], 'PUT', '/requirements/1/manual-draft', { expected_version: 4, markdown_content: '', block_state_json: emptyState }, false],
  ['I13', 'prepareCancelManualDraft', [1, 4], 'DELETE', '/requirements/1/manual-draft', { expected_version: 4 }, true],
  ['I12', 'prepareCompleteManualDraft', [1, 4], 'POST', '/requirements/1/manual-draft/complete', { expected_version: 4 }, true],
  ['I14', 'prepareCreateGuide', [1, guide], 'POST', '/requirements/1/guide-runs', guide, true],
  ['I15', 'prepareContinueGuide', [2, '补充'], 'POST', '/guide-runs/2/continue', { instruction: '补充' }, true],
  ['I16', 'getGuideRun', [2], 'GET', '/guide-runs/2', null, false],
  ['I17', 'prepareCancelGuide', [2], 'POST', '/guide-runs/2/cancel', null, true],
  ['I18', 'prepareRetryGuide', [2], 'POST', '/guide-runs/2/retry', null, true],
  ['I19', 'listGuideRuns', [1, {}], 'GET', '/requirements/1/guide-runs', null, false],
  ['I20', 'getBatch', [8], 'GET', '/suggestion-batches/8', null, false],
  ['I21', 'prepareDecideSuggestion', [9, { decision: 'ACCEPTED' }], 'PUT', '/suggestions/9/decision', { decision: 'ACCEPTED' }, true],
  ['I22', 'prepareCompleteBatch', [8, 7], 'POST', '/suggestion-batches/8/complete', { expected_content_version: 7 }, true],
  ['I23', 'prepareDiscardBatch', [8], 'POST', '/suggestion-batches/8/discard', null, true],
  ['I24', 'listRevisions', [1], 'GET', '/requirements/1/revisions', null, false],
  ['I25', 'getRevision', [4], 'GET', '/revisions/4', null, false],
  ['I26', 'prepareCreateRevision', [1, { expected_version: 7 }], 'POST', '/requirements/1/revisions', { expected_version: 7 }, true],
  ['I27', 'listComments', [1], 'GET', '/requirements/1/comments', null, false],
  ['I28', 'getComment', [4], 'GET', '/comments/4', null, false],
  ['I29', 'prepareCreateComment', [1, comment], 'POST', '/requirements/1/comments', comment, true],
  ['I30', 'prepareEditComment', [4, '编辑'], 'PATCH', '/comments/4', { content: '编辑' }, true],
  ['I31', 'prepareResolveComment', [4], 'POST', '/comments/4/resolve', null, true],
  ['I32', 'prepareReopenComment', [4], 'POST', '/comments/4/reopen', null, true],
  ['I33', 'prepareDeleteComment', [4], 'DELETE', '/comments/4', null, true],
  ['I34', 'prepareModifyFromComment', [4, 7], 'POST', '/comments/4/guide-runs', { expected_content_version: 7 }, true],
  ['I35', 'listMessages', [1], 'GET', '/requirements/1/messages', null, false],
  ['I36', 'prepareCardResponses', [5, answer], 'POST', '/conversation-messages/5/responses', answer, true],
  ['I37', 'getCommentIndex', [1], 'GET', '/requirements/1/comment-index', null, false],
];

test('all 37 bindings reach exact public method/path/body/key policy; no empty-body JSON or draft/CURRENT version substitution', async () => {
  for (const [name, method, args, verb, path, body, keyed] of cases) {
    let sent, keys = 0; const service = api(async (url, options) => { sent = { url, ...options }; return rejected(); }, () => { keys++; return KEY; });
    const pending = service[method](...args);
    await assert.rejects(method.startsWith('prepare') ? pending.submit() : pending, ApiRejected, name);
    assert.equal(sent.method, verb, name); assert.equal(new URL(sent.url, 'http://local').pathname, '/api/v1' + path, name);
    assert.equal(sent.headers['Idempotency-Key'], keyed ? KEY : undefined, name); assert.equal(keys, Number(keyed), name);
    assert.deepEqual(sent.body === undefined ? null : JSON.parse(sent.body), body, name);
    assert.equal(sent.headers['Content-Type'], body === null ? undefined : 'application/json', name);
  }
  const registered = [];
  for (const module of ['requirements', 'documents', 'revisions', 'comments', 'suggestions', 'guide', 'messages']) {
    const source = readFileSync(new URL(`../../backend/app/${module}/api.py`, import.meta.url), 'utf8');
    for (const match of source.matchAll(/@\w+\.(get|post|patch|put|delete)\('([^']+)'\)/g)) registered.push(match[1].toUpperCase() + ' ' + match[2].replace(/\{[^}]+\}/g, ':id'));
  }
  const bindings = cases.map(([, , , method, path]) => method + ' ' + path.replace(/\/[0-9]+(?=\/|$)/g, '/:id'));
  assert.equal(registered.length, 37); assert.deepEqual(bindings.sort(), registered.sort());
});
test('one creation captures body and response expectations once; loss/replay retains key while next action gets a new key', async () => {
  const calls = []; let attempt = 0, keys = 0, getters = 0;
  const service = api(async (url, options) => { calls.push({ url, ...options }); if (attempt++ === 0) throw new Error('lost');
    return json({ requirement: root(), current_document_id: 3, guide_run_id: 2 }, 201); }, () => keys++ === 0 ? KEY : REQUEST);
  const source = create(); Object.defineProperty(source, 'template_key', { enumerable: true, get() { getters++; return 'new-requirement'; } });
  const action = service.prepareCreateRequirement(source); source.template_version = 'changed';
  await assert.rejects(action.submit(), error => error instanceof ApiUnknown && error.mutation);
  assert.equal((await action.submit()).data.guide_run_id, 2); assert.equal(getters, 1); assert.equal(keys, 1);
  assert.equal(calls[0].body, calls[1].body); assert.equal(calls[1].headers['Idempotency-Key'], KEY);
  const next = service.prepareCreateRequirement(create()); await next.submit(); assert.equal(keys, 2); assert.equal(calls[2].headers['Idempotency-Key'], REQUEST);
});
test('wrong response ownership or successful command pagination keeps results unknown and original request retained', async () => {
  for (const reply of [json({ requirement: { ...root(), template_version: 'wrong' }, current_document_id: 3, guide_run_id: 2 }, 201),
    json({ requirement: root(), current_document_id: 3, guide_run_id: 2 }, 201, { page: 1, page_size: 20, total: 0, total_pages: 0 })]) {
    const service = api(async () => reply.clone()); const action = service.prepareCreateRequirement(create());
    await assert.rejects(action.submit(), error => error instanceof ApiUnknown && error.mutation);
    await assert.rejects(action.submit(), ApiUnknown);
  }
  for (const reply of [json({ ...root(), id: 2 }), json(root(), 200, { page: 1, page_size: 20, total: 0, total_pages: 0 })])
    await assert.rejects(api(async () => reply).getRequirement(1), error => error instanceof ApiUnknown && !error.mutation);
});
test('requirement page checks actual page/window/count and encodes repeated filters without comma joining', async () => {
  const summary = ({ id, requirement_no, title, requirement_type, status, updated_at }) => ({ id, requirement_no, title, requirement_type, status, updated_at });
  let sent; const service = api(async (url) => { sent = url; return json({ items: [summary(root())] }, 200, { page: 2, page_size: 20, total: 21, total_pages: 2 }); });
  assert.equal((await service.listRequirements({ keyword: '甲&乙😀', status: ['INITIALIZING', 'ACTIVE'], requirement_type: ['NEW'], page: 2 })).data.items.length, 1);
  const params = new URL(sent, 'http://local').searchParams; assert.deepEqual(params.getAll('status'), ['INITIALIZING', 'ACTIVE']); assert.equal(params.get('keyword'), '甲&乙😀');
  for (const reply of [json({ items: [] }), json({ items: [] }, 200, { page: 1, page_size: 20, total: 1, total_pages: 1 }),
    json({ items: [] }, 200, { page: 2, page_size: 20, total: 0, total_pages: 0 })])
    await assert.rejects(api(async () => reply).listRequirements(), ApiUnknown);
});
test('workbench keeps server order and raw display time while invalid business times remain rejected', async () => {
  const summarize = ({ id, requirement_no, title, requirement_type, status, updated_at }) => ({ id, requirement_no, title, requirement_type, status, updated_at });
  const first = { ...summarize(root()), id: 2, requirement_no: 'REQ000002', updated_at: 'invalid-time' };
  const second = summarize(root());
  const response = await api(async () => json({ items: [first, second] }, 200, { page: 1, page_size: 20, total: 2, total_pages: 1 })).listRequirements();
  assert.deepEqual(response.data.items.map(row => row.id), [2, 1]);
  assert.equal(response.data.items[0].updated_at, 'invalid-time');
  const { localTime } = await import('../src/shared/time.ts');
  assert.equal(localTime(response.data.items[0].updated_at), '--');
  await assert.rejects(api(async () => json({ items: [{ ...first, updated_at: null }] }, 200,
    { page: 1, page_size: 20, total: 1, total_pages: 1 })).listRequirements(), ApiUnknown);
  await assert.rejects(api(async () => json({ ...root(), updated_at: 'invalid-time' })).getRequirement(1), ApiUnknown);
});
test('message cursor is exclusive, ascending and independently continued by first sequence', async () => {
  const message = sequence => ({ id: sequence, requirement_id: 1, guide_run_id: null, sequence_no: sequence, role: 'USER', content: '原文',
    message_type: 'TEXT', structured_content: null, reply_to_message_id: null, created_at: at, card_state: null });
  let sent; const service = api(async url => { sent = url; return json({ items: [message(3), message(5)] }, 200, { page_size: 20, next_cursor: 3, has_more: true }); });
  assert.equal((await service.listMessages(1, 6)).meta.pagination.next_cursor, 3); assert.equal(new URL(sent, 'http://local').searchParams.get('before_sequence_no'), '6');
  for (const [items, cursor] of [[[message(5), message(3)], 5], [[message(3), message(3)], 3], [[message(3), message(6)], 3], [[], 3], [[message(3)], 2]])
    await assert.rejects(api(async () => json({ items }, 200, { page_size: 20, next_cursor: cursor, has_more: true })).listMessages(1, 6), ApiUnknown);
});
test('invalid IDs and absent/misspelled request fields fail before allocating or sending an action', () => {
  let calls = 0; const service = api(async () => { calls++; return rejected(); }, () => { calls++; return KEY; });
  for (const id of [0, -1, 2 ** 53, '1', NaN]) assert.throws(() => service.prepareCancelGuide(id), TypeError);
  assert.throws(() => service.prepareUpdateRequirement(1, {}));
  assert.throws(() => service.prepareUpdateRequirement(1, { initialization_mode: 'DESIGN' }));
  assert.throws(() => service.prepareUpdateRequirement(1, { title: '不得部分修改', initialization_mode: 'DESIGN' }));
  assert.throws(() => service.prepareCreateRequirement({ ...create(), extra: 'x' }));
  assert.throws(() => service.prepareCreateRevision(1, { expected_content_version: 7 }));
  assert.throws(() => service.prepareCreateGuide(1, { ...guide, source: 'wrong' }));
  assert.equal(calls, 0);
});
test('I15 original run continues; I17 only acknowledges finished cancellation; I18 requires a new retry identity', async () => {
  assert.equal((await api(async () => json({ id: 2, requirement_id: 1, status: 'RUNNING', current_step: 'PREPARING' }, 202)).prepareContinueGuide(2, '补充').submit()).data.id, 2);
  await assert.rejects(api(async () => json({ id: 3, requirement_id: 1, status: 'RUNNING', current_step: 'PREPARING' }, 202)).prepareContinueGuide(2, '补充').submit(), ApiUnknown);
  assert.equal((await api(async () => json({ id: 2, requirement_id: 1, status: 'CANCELLED', current_step: 'FINISHED' })).prepareCancelGuide(2).submit()).data.status, 'CANCELLED');
  await assert.rejects(api(async () => json({ id: 2, requirement_id: 1, status: 'RUNNING', current_step: 'PREPARING' })).prepareCancelGuide(2).submit(), ApiUnknown);
});
