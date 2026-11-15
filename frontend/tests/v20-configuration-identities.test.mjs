import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown, ApiRejected } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import {
  configurationCollection,
  configurationIdentityBinding,
  configurationIdentityRow,
  CONFIGURATION_IDENTITY_BINDINGS,
} from '../src/api/code-configuration-identities.ts';
import { restoreCodeCommand } from '../src/api/code-command-snapshot.ts';
import { registeredCommand } from '../src/api/code-command-registry.ts';
import { ERROR_MESSAGES } from '../src/api/code-errors.ts';

const ORIGIN = 'http://localhost:5173';
const KEY = '00000000-0000-4000-8000-00000000000a';
const REQUEST = '00000000-0000-4000-8000-00000000000b';
const kinds = ['EXECUTION_PROFILE', 'CHECK_SET'];
function success(data, status = 200, pagination) {
  return new Response(
    JSON.stringify({
      success: true,
      data,
      error: null,
      meta: { request_id: REQUEST, ...(pagination === undefined ? {} : { pagination }) },
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  );
}
function error(code, status, details) {
  return new Response(
    JSON.stringify({
      success: false,
      data: null,
      error: { code, message: ERROR_MESSAGES[code], details },
      meta: { request_id: REQUEST },
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  );
}

test('only two native input/result bindings register real synchronous identity routes', () => {
  assert.equal(CONFIGURATION_IDENTITY_BINDINGS.length, 2);
  for (const kind of kinds) {
    const collection = configurationCollection(kind);
    const binding = configurationIdentityBinding(kind);
    const original = registeredCommand('POST', collection.path, KEY);
    binding.validate_input({ name: ' 原名称 ' }, original);
    assert.deepEqual(binding.success_status, [201]);
    assert.deepEqual(
      binding.decode({ resource_kind: kind, resource_id: 7 }, original, { name: '原名称' }),
      { resource_kind: kind, resource_id: 7 },
    );
    assert.throws(() =>
      binding.decode(
        { resource_kind: kind === 'CHECK_SET' ? 'EXECUTION_PROFILE' : 'CHECK_SET', resource_id: 7 },
        original,
        { name: 'x' },
      ),
    );
    for (const value of [
      { name: '' },
      { name: '\u0085\u3000' },
      { name: null },
      { name: 'x', id: 7 },
      { name: '\0' },
    ])
      assert.throws(() => binding.validate_input(value, original), TypeError);
    for (const value of [
      { resource_kind: kind, resource_id: 0 },
      { resource_kind: kind, resource_id: 7, ready: true },
    ])
      assert.throws(() => binding.decode(value, original, { name: 'x' }), TypeError);
    // Backend White_Space deliberately excludes BOM.
    binding.validate_input({ name: '\ufeff' }, original);
  }
  assert.throws(() => configurationCollection('TASK'));
});

test('configuration list rows require exact nullable latest identity and preserve text facts', () => {
  assert.deepEqual(configurationIdentityRow({ id: 1, name: '配置', latest_version_id: null }), {
    id: 1,
    name: '配置',
    latest_version_id: null,
  });
  for (const row of [
    { id: 1, name: 'x' },
    { id: 1, name: '', latest_version_id: null },
    { id: 1, name: ' x ', latest_version_id: null },
    { id: 1, name: '\ud800', latest_version_id: null },
    { id: 1, name: 'x', latest_version_id: 0 },
    { id: 1, name: 'x', latest_version_id: null, ready: true },
  ])
    assert.throws(() => configurationIdentityRow(row), TypeError);
});

test('WalleApi creates through the original client and restores bytes without a new key', async () => {
  for (const kind of kinds) {
    const calls = [];
    let keys = 0;
    const client = new ApiClient(
      async (path, options) => {
        calls.push([path, options.headers['Idempotency-Key'], options.body]);
        return success({ resource_kind: kind, resource_id: 9 }, 201);
      },
      () => {
        keys++;
        return KEY;
      },
    );
    const api = new WalleApi(client, {});
    const action =
      kind === 'EXECUTION_PROFILE'
        ? await api.prepareCreateCodeExecutionProfile('配置', ORIGIN)
        : await api.prepareCreateCodeCheckSet('配置', ORIGIN);
    assert.equal(calls.length, 0);
    assert.equal(keys, 1);
    assert.equal(action.frozen.body_json, '{"name":"配置"}');
    assert.deepEqual((await action.submit()).data, { resource_kind: kind, resource_id: 9 });
    const cold = new ApiClient(
      async (path, options) => {
        calls.push([path, options.headers['Idempotency-Key'], options.body]);
        return success({ resource_kind: kind, resource_id: 9 }, 201);
      },
      () => {
        throw Error('No replacement key');
      },
    );
    const restored = await restoreCodeCommand(
      cold,
      action.frozen,
      configurationIdentityBinding(kind),
      ORIGIN,
    );
    await restored.submit();
    assert.deepEqual(calls[0], calls[1]);
  }
});

test('a 202 or a wrong resource result is unknown rather than an invented created identity', async () => {
  for (const [status, data] of [
    [202, { resource_kind: 'EXECUTION_PROFILE', resource_id: 1 }],
    [201, { resource_kind: 'CHECK_SET', resource_id: 1 }],
  ]) {
    const api = new WalleApi(
      new ApiClient(
        async () => success(data, status),
        () => KEY,
      ),
      {},
    );
    const action = await api.prepareCreateCodeExecutionProfile('配置', ORIGIN);
    await assert.rejects(action.submit(), (fault) => fault instanceof ApiUnknown && fault.mutation);
  }
});

test('typed list methods retain original page and decode V2 errors through the shared page path', async () => {
  const calls = [];
  const api = new WalleApi(
    new ApiClient(async (path, options) => {
      calls.push([path, options.method, options.headers['Idempotency-Key']]);
      return success({ items: [] }, 200, { page: 3, page_size: 20, total: 2, total_pages: 1 });
    }),
    {},
  );
  const result = await api.codeExecutionProfiles(3);
  assert.deepEqual(result.data, { items: [] });
  assert.equal(result.meta.pagination.page, 3);
  assert.deepEqual(calls, [['/api/v1/code-execution-profiles?page=3', 'GET', undefined]]);
  const unavailable = new WalleApi(
    new ApiClient(async () =>
      error('STORAGE_UNAVAILABLE', 503, { capability_codes: ['DATABASE'] }),
    ),
    {},
  );
  await assert.rejects(
    unavailable.codeCheckSets(),
    (fault) => fault instanceof ApiRejected && fault.code === 'STORAGE_UNAVAILABLE',
  );
});

test('typed identity lists reject inconsistent counts, duplicate IDs and malformed version references', async () => {
  for (const [items, pagination] of [
    [
      [{ id: 1, name: 'x', latest_version_id: null }],
      { page: 1, page_size: 20, total: 0, total_pages: 0 },
    ],
    [
      [
        { id: 1, name: 'x', latest_version_id: null },
        { id: 1, name: 'x', latest_version_id: null },
      ],
      { page: 1, page_size: 20, total: 2, total_pages: 1 },
    ],
    [
      [{ id: 1, name: 'x', latest_version_id: '7' }],
      { page: 1, page_size: 20, total: 1, total_pages: 1 },
    ],
  ]) {
    const api = new WalleApi(new ApiClient(async () => success({ items }, 200, pagination)), {});
    await assert.rejects(api.codeCheckSets(), ApiUnknown);
  }
});

test('WalleApi recovery registers actual identity DTOs and cannot send without committed storage', async () => {
  let calls = 0;
  const api = new WalleApi(
    new ApiClient(
      async () => {
        calls++;
        throw Error('No HTTP');
      },
      () => KEY,
    ),
    {},
  );
  const store = {
    origin: ORIGIN,
    list: async () => [],
    reserve: async () => {
      throw Error('Owned storage unavailable');
    },
    close() {},
  };
  const owner = api.configurationRecovery(store, async () => {
    throw Error('No async identity operation');
  });
  await assert.rejects(
    owner.stage('/api/v1/code-execution-profiles', { name: '配置' }),
    /Owned storage unavailable/,
  );
  await assert.rejects(
    owner.stage('/api/v1/code-tasks/1/start', { expected_state_version: 1 }),
    /Owned storage unavailable/,
  );
  assert.equal(calls, 0);
  owner.dispose();
});
