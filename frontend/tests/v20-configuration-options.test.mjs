import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ApiClient, ApiUnknown, ApiRejected } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import {
  CONFIGURATION_OPTION_KINDS,
  configurationOption,
} from '../src/api/code-configuration-options.ts';
import { ERROR_MESSAGES } from '../src/api/code-errors.ts';

const entries = JSON.parse(
  readFileSync(
    new URL('../../backend/resources/code/code20-r3/options.json', import.meta.url),
    'utf8',
  ),
).items;
const REQUEST = '00000000-0000-4000-8000-00000000000b';
function success(items, page = 1, total = items.length, override = {}) {
  return new Response(
    JSON.stringify({
      success: true,
      data: { items },
      error: null,
      meta: {
        request_id: REQUEST,
        pagination: { page, page_size: 20, total, total_pages: Math.ceil(total / 20), ...override },
      },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}
function api(fetch) {
  return new WalleApi(new ApiClient(fetch), {});
}

test('actual published nonsecret resource bytes decode exactly and remain immutable', () => {
  for (const entry of entries) {
    const decoded = configurationOption(entry);
    assert.deepEqual(decoded, entry);
    assert.equal(decoded.ready, false);
    assert.ok(Object.isFrozen(decoded) && Object.isFrozen(decoded.value));
    assert.ok(Object.isFrozen(decoded.unresolved_capability_codes));
  }
});
test('typed API20 reads every registered kind with exact GET parameters and no command key', async () => {
  const calls = [];
  const instance = api(async (path, options) => {
    calls.push([path, options.method, options.headers['Idempotency-Key']]);
    const kind = new URL(path, 'http://owned.invalid').searchParams.get('kind');
    return success(entries.filter((e) => e.kind === kind));
  });
  for (const kind of CONFIGURATION_OPTION_KINDS) {
    const response = await instance.codeConfigurationOptions(kind);
    assert.deepEqual(
      response.data.items,
      entries.filter((e) => e.kind === kind),
    );
  }
  assert.equal(calls.length, 12);
  assert.ok(
    calls.every(
      ([path, method, key]) => path.endsWith('&page=1') && method === 'GET' && key === undefined,
    ),
  );
});
test('opaque catalogue identity pages preserve true empty out-of-range pages', async () => {
  const instance = api(async () => success([], 3, 3));
  const response = await instance.codeConfigurationOptions('MODEL', 3);
  assert.deepEqual(response.data.items, []);
  assert.equal(response.meta.pagination.page, 3);
  assert.equal(response.meta.pagination.total, 3);
});
test('input kind/page failures happen before any HTTP request', async () => {
  let count = 0;
  const instance = api(async () => {
    count++;
    throw Error('No HTTP');
  });
  for (const [kind, page] of [
    ['git', 1],
    ['GIT', 0],
    ['GIT', 100001],
    ['GIT', NaN],
    ['GIT', '1'],
  ]) {
    await assert.rejects(instance.codeConfigurationOptions(kind, page));
  }
  assert.equal(count, 0);
});
test('unprepared kinds, secrets, invented readiness and malformed Git/Profile references are rejected', () => {
  const git = entries.find((entry) => entry.kind === 'GIT');
  const model = entries.find((entry) => entry.kind === 'MODEL');
  const policy = entries.find((entry) => entry.kind === 'CONTENT_POLICY');
  for (const bad of [
    { ...git, ready: true },
    { ...git, extra: 'secret' },
    { ...git, kind: 'EXECUTOR' },
    { ...git, value: { ...git.value, host_path: 'C:\\secret' } },
    { ...git, value: { ...git.value, binary_ref: 'C:\\git.exe' } },
    { ...git, value: { ...git.value, version: 'latest' } },
    { ...git, unresolved_capability_codes: [] },
    { ...model, value: { model_profile_ref: 'private-profile' } },
    { ...model, value: { ...model.value, api_key: 'secret' } },
    { ...model, option_id: 'fake' },
    { ...model, label: '' },
    { ...policy, option_id: 'content-policy:invented' },
    { ...policy, value: { ...policy.value, secret_policy_ref: 'local-secret' } },
    { ...policy, value: { ...policy.value, pattern: 'private' } },
    { ...policy, unresolved_capability_codes: [...policy.unresolved_capability_codes].reverse() },
  ])
    assert.throws(() => configurationOption(bad));
});
test('wrong kind/order/count, duplicates or page metadata cannot be accepted as read success', async () => {
  const models = entries.filter((e) => e.kind === 'MODEL');
  for (const [kind, items, page, total, override] of [
    ['MODEL', [entries.find((entry) => entry.kind === 'GIT')], 1, 1, {}],
    ['MODEL', [models[1], models[0]], 1, 2, {}],
    ['MODEL', [models[0], models[0]], 1, 2, {}],
    ['MODEL', [models[0]], 1, 3, {}],
    ['MODEL', models, 2, 3, {}],
    ['MODEL', models, 1, 3, { page_size: 10 }],
    ['MODEL', models, 1, 3, { total_pages: 0 }],
  ]) {
    const instance = api(async () => success(items, page, total, override));
    await assert.rejects(
      instance.codeConfigurationOptions(kind),
      (fault) => fault instanceof ApiUnknown && fault.mutation === false,
    );
  }
});
test('V2 readiness failure is a typed rejection with its original capability details', async () => {
  const instance = api(
    async () =>
      new Response(
        JSON.stringify({
          success: false,
          data: null,
          error: {
            code: 'CONFIG_NOT_READY',
            message: ERROR_MESSAGES.CONFIG_NOT_READY,
            details: { capability_codes: ['Q20-CONFIG'] },
          },
          meta: { request_id: REQUEST },
        }),
        { status: 503, headers: { 'Content-Type': 'application/json' } },
      ),
  );
  await assert.rejects(
    instance.codeConfigurationOptions('GIT'),
    (fault) =>
      fault instanceof ApiRejected &&
      fault.code === 'CONFIG_NOT_READY' &&
      fault.details.capability_codes[0] === 'Q20-CONFIG',
  );
});

test('managed read roots are exact nonsecret references and never runtime admission', () => {
  const scopes = entries.filter((row) => row.kind === 'SCOPE');
  assert.equal(scopes.length, 2);
  for (const row of scopes) {
    const parsed = configurationOption(row);
    assert.equal(parsed.ready, false);
    assert.equal(parsed.value.scope_kind, 'READ_ROOT');
    assert.deepEqual(parsed.unresolved_capability_codes, ['Q20-CONFIG', 'Q20-WINDOWS']);
    for (const malformed of [
      { ...row, ready: true },
      { ...row, option_id: 'scope:other' },
      { ...row, value: { ...row.value, path: 'C:/private' } },
      { ...row, value: { ...row.value, scope_ref: 'arbitrary-host' } },
      { ...row, value: { ...row.value, scope_kind: 'NETWORK_TARGET' } },
      { ...row, unresolved_capability_codes: [] },
      { ...row, unresolved_capability_codes: ['Q20-WINDOWS', 'Q20-CONFIG'] },
    ])
      assert.throws(() => configurationOption(malformed));
  }
});
