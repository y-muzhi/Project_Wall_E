import { test } from 'node:test';
import assert from 'node:assert/strict';
import { IdentitySettingsOwner } from '../src/code-tasks/settings/identity-owner.ts';
import { commandSha256 } from '../src/api/code-command-snapshot.ts';

const origin = 'http://127.0.0.1:5173';
const profilePath = '/api/v1/code-execution-profiles';
const checkPath = '/api/v1/code-check-sets';
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const page = (items = [], current = 1, total = items.length) => ({
  data: { items }, meta: { pagination: { page: current, page_size: 20, total, total_pages: Math.ceil(total / 20) } },
});
const identity = (id, name = '已保存配置') => ({ id, name, latest_version_id: null });
const flush = () => new Promise((done) => setImmediate(done));
function setup(kind = 'EXECUTION_PROFILE', overrides = {}) {
  const drafts = new Map();
  const storage = { getItem: (key) => drafts.get(key) ?? null, setItem: (key, value) => drafts.set(key, value) };
  const requests = [];
  const api = {
    codeExecutionProfiles: async (p, signal) => { requests.push(['profile', p, signal]); return page([identity(7)], p); },
    codeCheckSets: async (p, signal) => { requests.push(['checks', p, signal]); return page([identity(8)], p); },
    codeExecutionProfileVersions: async (id, p, signal) => { requests.push(['profile-versions', id, p, signal]); return page([], p); },
    codeCheckSetVersions: async (id, p, signal) => { requests.push(['check-versions', id, p, signal]); return page([], p); },
    ...overrides.api,
  };
  const writes = [];
  const record = { key: '00000000-0000-4000-8000-000000000001', record_revision: 1, path: kind === 'EXECUTION_PROFILE' ? profilePath : checkPath };
  const recovery = {
    store: { origin, list: async () => [], ...overrides.store },
    stageIntent: async (path, input) => { writes.push(['stage', path, input]); return { kind: 'PREPARED', record }; },
    send: async (key, revision) => {
      writes.push(['send', key, revision]);
      return { response: { data: { resource_kind: kind, resource_id: 42 } } };
    },
    ...overrides.recovery,
  };
  const owner = new IdentitySettingsOwner(api, recovery, kind, storage);
  return { owner, api, recovery, storage, drafts, requests, writes, record };
}

test('explicit creation uses one normalized original intent and reads its actual identity versions', async () => {
  for (const kind of ['EXECUTION_PROFILE', 'CHECK_SET']) {
    const { owner, writes, requests, drafts, record } = setup(kind);
    owner.resume();
    await flush();
    owner.edit('\u0085 固定配置 \r\n');
    const submit = owner.submit();
    await owner.submit();
    await submit;
    await flush();
    assert.deepEqual(writes, [['stage', record.path, { name: '固定配置' }], ['send', record.key, 1]]);
    assert.equal(owner.getSnapshot().name, '');
    assert.equal(owner.getSnapshot().selectedId, 42);
    assert.deepEqual(owner.getSnapshot().versions.items, []);
    assert.ok(requests.some(([label, id]) => label.endsWith('-versions') && id === 42));
    assert.equal(JSON.parse([...drafts.values()][0]).name, '');
    owner.dispose();
  }
});

test('a same-route existing original or terminal race never dispatches the new form', async () => {
  for (const kind of ['EXISTING', 'RESOLVED']) {
    let staged = 0;
    const original = { key: 'other-tab', record_revision: 3 };
    const { owner, writes } = setup('CHECK_SET', { recovery: {
      stageIntent: async (path, body) => {
        assert.equal(path, checkPath);
        assert.deepEqual(body, { name: '新草稿' });
        staged++;
        return kind === 'EXISTING' ? { kind, record: original } : { kind, receipt: {} };
      },
    } });
    owner.edit('新草稿');
    await owner.submit();
    assert.equal(staged, 1);
    assert.deepEqual(writes, []);
    assert.equal(owner.getSnapshot().name, '新草稿');
    assert.equal(owner.getSnapshot().blockedKey, kind === 'EXISTING' ? original.key : null);
    owner.dispose();
  }
});

test('failed dispatch preserves current draft and requires original lookup before a new intent', async () => {
  let records = [];
  const original = { key: 'old-key', path: profilePath, record_revision: 1 };
  const { owner, writes } = setup('EXECUTION_PROFILE', {
    store: { list: async () => records },
    recovery: { send: async () => { records = [original]; throw Error('response lost'); } },
  });
  owner.edit('保留输入');
  await owner.submit();
  assert.equal(owner.getSnapshot().blockedKey, original.key);
  assert.equal(owner.getSnapshot().name, '保留输入');
  await owner.submit();
  assert.equal(writes.length, 1);
  records = [];
  await owner.syncPending();
  assert.equal(owner.getSnapshot().blockedKey, null);
  owner.dispose();
});

test('late pre-creation list and version reads cannot overwrite the created identity', async () => {
  const old = deferred();
  let readCount = 0, retired;
  const { owner } = setup('EXECUTION_PROFILE', { api: {
    codeExecutionProfiles: (p, signal) => {
      if (++readCount === 1) { retired = signal; return old.promise; }
      return Promise.resolve(page([identity(42, '新配置')], p));
    },
  } });
  owner.resume();
  owner.edit('新配置');
  await owner.submit();
  await flush();
  assert.ok(retired.aborted);
  old.resolve(page([identity(7)]));
  await flush();
  assert.equal(owner.getSnapshot().identities.items[0].id, 42);
  assert.equal(owner.getSnapshot().selectedId, 42);
  owner.dispose();
});

test('a hidden form keeps its draft and late success without issuing hidden reads', async () => {
  const wire = deferred();
  const { owner, requests } = setup('CHECK_SET', { recovery: { send: () => wire.promise } });
  owner.resume();
  await flush();
  owner.edit('异步配置');
  const sent = owner.submit();
  await flush();
  owner.pause();
  wire.resolve({ response: { data: { resource_kind: 'CHECK_SET', resource_id: 84 } } });
  await sent;
  assert.equal(owner.getSnapshot().selectedId, 84);
  assert.deepEqual(requests.map(([label]) => label), ['checks']);
  owner.resume();
  await flush();
  assert.ok(requests.some(([label, id]) => label === 'check-versions' && id === 84));
  owner.dispose();
});

test('original 201 receipt restores its actual ID and only clears a matching draft', async () => {
  const { owner, record, storage, api, recovery } = setup('EXECUTION_PROFILE', {
    recovery: { send: async () => { throw Error('response lost'); } },
  });
  owner.edit(' 原配置 ');
  await owner.submit();
  owner.dispose();
  const resumed = new IdentitySettingsOwner(api, recovery, 'EXECUTION_PROFILE', storage);
  const result = {
    local: { final_state: 'CONFIRMED', key: record.key, http_status: 201, body_sha256: await commandSha256('{"name":"原配置"}') },
    original_receipt: { original_outcome: { success: true, data: { resource_kind: 'EXECUTION_PROFILE', resource_id: 89 } } },
  };
  const signal = new AbortController().signal;
  await resumed.reconcileCreated(record, result, signal);
  assert.equal(resumed.getSnapshot().selectedId, 89);
  assert.equal(resumed.getSnapshot().name, '');
  resumed.edit(' 原配置 ');
  await resumed.reconcileCreated(record, result, signal);
  assert.equal(resumed.getSnapshot().name, ' 原配置 ');
  resumed.edit('另一份草稿');
  await resumed.reconcileCreated(record, result, signal);
  assert.equal(resumed.getSnapshot().name, '另一份草稿');
  resumed.dispose();
});

test('drafts are origin and kind scoped; invalid or denied storage stays separate from commands', () => {
  const { owner, api, recovery, storage, drafts } = setup();
  owner.edit('执行草稿');
  const checks = new IdentitySettingsOwner(api, recovery, 'CHECK_SET', storage);
  checks.edit('检查草稿');
  const resumed = new IdentitySettingsOwner(api, recovery, 'EXECUTION_PROFILE', storage);
  assert.equal(resumed.getSnapshot().name, '执行草稿');
  assert.equal(drafts.size, 2);
  const corrupt = new IdentitySettingsOwner(api, recovery, 'CHECK_SET', {
    getItem: () => '{"schema_version":1,"name":"错误草稿","updated_at":"2026-11-31T00:00:00.000Z","command_key":null}',
    setItem() { throw Error('denied'); },
  });
  assert.equal(corrupt.getSnapshot().name, '');
  corrupt.edit('仅当前页保留');
  assert.equal(corrupt.getSnapshot().name, '仅当前页保留');
  assert.match(corrupt.getSnapshot().draftWarning, /草稿暂存不可用/);
  for (const current of [owner, checks, resumed, corrupt]) current.dispose();
});

test('failed pagination preserves last data and retries the requested page', async () => {
  let failing = true;
  const { owner } = setup('EXECUTION_PROFILE', { api: {
    codeExecutionProfiles: async (p) => {
      if (p === 2 && failing) throw Error('list unavailable');
      return page(p === 1 ? [identity(7)] : [], p, 21);
    },
  } });
  owner.resume();
  await flush();
  await owner.read(2);
  assert.equal(owner.getSnapshot().requestedPage, 2);
  assert.equal(owner.getSnapshot().identities.items[0].id, 7);
  assert.match(owner.getSnapshot().readError, /暂时无法读取/);
  failing = false;
  await owner.read(owner.getSnapshot().requestedPage);
  assert.equal(owner.getSnapshot().identities.pagination.page, 2);
  assert.equal(owner.getSnapshot().readError, null);
  owner.dispose();
});
