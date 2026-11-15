import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import {
  checkSetContent,
  checkSetVersion,
  CHECK_SET_VERSION_BINDING,
} from '../src/api/code-check-sets.ts';
import { registeredCommand } from '../src/api/code-command-registry.ts';
import { restoreCodeCommand } from '../src/api/code-command-snapshot.ts';
const KEY = '00000000-0000-4000-8000-00000000000a';
const REQUEST = '00000000-0000-4000-8000-00000000000b';
const ORIGIN = 'http://localhost:5173';
const PATH = '/api/v1/code-check-sets/7/versions';
const BODY = { protocol_version: 'CHECK20-CONTROL-1', items: [], coverage_plan: [] };
const version = (extra = {}) => ({
  id: 1,
  check_set_id: 7,
  version: 1,
  owner_module: 'CODING',
  ...BODY,
  created_at: '2026-11-05T00:00:00.000Z',
  ready: false,
  unresolved_capability_codes: ['Q20-CHECKS'],
  ...extra,
});
const success = (data, status = 200, pagination) =>
  new Response(
    JSON.stringify({
      success: true,
      data,
      error: null,
      meta: { request_id: REQUEST, ...(pagination === undefined ? {} : { pagination }) },
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  );
function integrity(extra = {}) {
  return {
    check_id: 'integrity',
    name: '原输入完整性',
    stages: ['BACKEND'],
    required: true,
    check_kind: 'CONTROLLED_ASSERTION',
    command_id: null,
    runner_ref: 'runner',
    case_pack_ref: null,
    expected_exit_codes: null,
    environment_refs: [],
    protected_input_refs: [],
    target: null,
    timeout_seconds: 20,
    evidence_rule: { kind: 'CONTENT_INTEGRITY' },
    ...extra,
  };
}

test('native C08 binding uses the original parent path and exact created version result', () => {
  const original = registeredCommand('POST', PATH, KEY);
  CHECK_SET_VERSION_BINDING.validate_input(BODY, original);
  assert.deepEqual(
    CHECK_SET_VERSION_BINDING.decode(
      { resource_kind: 'CHECK_SET_VERSION', resource_id: 9 },
      original,
      BODY,
    ),
    { resource_kind: 'CHECK_SET_VERSION', resource_id: 9 },
  );
  for (const value of [
    { resource_kind: 'CHECK_SET', resource_id: 9 },
    { resource_kind: 'CHECK_SET_VERSION', resource_id: true },
    { resource_kind: 'CHECK_SET_VERSION', resource_id: 9, ready: true },
  ])
    assert.throws(() => CHECK_SET_VERSION_BINDING.decode(value, original, BODY), TypeError);
  assert.throws(() =>
    CHECK_SET_VERSION_BINDING.validate_input(
      BODY,
      registeredCommand('POST', '/api/v1/code-check-sets', KEY),
    ),
  );
});

test('input and version decoders reject forged owner, project success markers and readiness', () => {
  for (const extra of [{ owner_module: 'TESTING' }, { ready: true }, { version: 1 }])
    assert.throws(() => checkSetContent({ ...BODY, ...extra }));
  for (const item of [
    integrity({ stages: ['ACCEPTANCE'] }),
    integrity({ timeout_seconds: true }),
    integrity({ required: 1 }),
    integrity({ runner_ref: 'x\0y' }),
    integrity({ evidence_rule: { kind: 'EXIT_CODE_AND_MARKERS' } }),
    integrity({
      check_kind: 'PROJECT_COMMAND',
      command_id: 'test',
      expected_exit_codes: [false],
      evidence_rule: { kind: 'PROCESS_EXIT' },
    }),
  ])
    assert.throws(() => checkSetContent({ ...BODY, items: [item] }));
  for (const extra of [
    { ready: true },
    { unresolved_capability_codes: [] },
    { owner_module: 'OTHER' },
    { private_extra: 'secret' },
  ])
    assert.throws(() => checkSetVersion(version(extra)));
  assert.equal(checkSetVersion(version()).ready, false);
  assert.equal(
    checkSetVersion(
      version({ owner_module: 'TESTING', items: [integrity({ stages: ['ACCEPTANCE'] })] }),
    ).owner_module,
    'TESTING',
  );
});

test('decoded nested values are immutable and auto coverage cannot use project or integrity result', () => {
  const row = checkSetContent({ ...BODY, items: [integrity()] });
  assert.ok(Object.isFrozen(row.items[0].stages));
  assert.throws(() => row.items[0].stages.push('FRONTEND'));
  const coverage = {
    coverage_id: 'c',
    basis_refs: [{ document_id: 1, revision_id: 2, quote: 'text' }],
    stages: ['BACKEND'],
    mode: 'AUTO',
    check_ids: ['integrity'],
    explanation: '',
  };
  assert.throws(() =>
    checkSetContent({ ...BODY, items: [integrity()], coverage_plan: [coverage] }),
  );
});

test('WalleApi freezes original bytes and restores same C08 without a replacement key', async () => {
  const calls = [];
  const client = new ApiClient(
    async (path, options) => {
      calls.push([path, options.headers['Idempotency-Key'], options.body]);
      return success({ resource_kind: 'CHECK_SET_VERSION', resource_id: 9 }, 201);
    },
    () => KEY,
  );
  const api = new WalleApi(client, {});
  const body = checkSetContent(BODY);
  const action = await api.preparePublishCodeCheckSetVersion(7, body, ORIGIN);
  assert.equal(calls.length, 0);
  assert.equal(action.frozen.decoder_kind, 'APP-CODE-CMD-C08');
  await action.submit();
  const cold = new ApiClient(
    async (path, options) => {
      calls.push([path, options.headers['Idempotency-Key'], options.body]);
      return success({ resource_kind: 'CHECK_SET_VERSION', resource_id: 9 }, 201);
    },
    () => {
      throw Error('No new key');
    },
  );
  const restored = await restoreCodeCommand(cold, action.frozen, CHECK_SET_VERSION_BINDING, ORIGIN);
  await restored.submit();
  assert.deepEqual(calls[0], calls[1]);
});

test('typed detail and paginated reads preserve original identity, page and descending version order', async () => {
  const api = new WalleApi(
    new ApiClient(async (path) => {
      if (path.includes('code-check-set-versions')) return success(version());
      return success({ items: [version({ id: 2, version: 2 }), version()] }, 200, {
        page: 1,
        page_size: 20,
        total: 2,
        total_pages: 1,
      });
    }),
    {},
  );
  assert.equal((await api.codeCheckSetVersion(1)).data.id, 1);
  assert.deepEqual(
    (await api.codeCheckSetVersions(7)).data.items.map((v) => v.version),
    [2, 1],
  );
  const wrong = new WalleApi(new ApiClient(async () => success(version({ id: 2 }))), {});
  await assert.rejects(wrong.codeCheckSetVersion(1), ApiUnknown);
  const crossed = new WalleApi(
    new ApiClient(async () =>
      success({ items: [version({ check_set_id: 9 })] }, 200, {
        page: 1,
        page_size: 20,
        total: 1,
        total_pages: 1,
      }),
    ),
    {},
  );
  await assert.rejects(crossed.codeCheckSetVersions(7), ApiUnknown);
});

test('202 is not a created version and never replaces an original synchronous result', async () => {
  const api = new WalleApi(
    new ApiClient(
      async () => success({ resource_kind: 'CHECK_SET_VERSION', resource_id: 1 }, 202),
      () => KEY,
    ),
    {},
  );
  const action = await api.preparePublishCodeCheckSetVersion(7, checkSetContent(BODY), ORIGIN);
  await assert.rejects(action.submit(), (error) => error instanceof ApiUnknown && error.mutation);
});
