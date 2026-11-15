import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiRejected, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import { repositoryOperation } from '../src/api/code-repository-operations.ts';
import {
  REGISTER_CODE_BASELINE_BINDING,
  REGISTER_REPOSITORY_BINDING,
  REFRESH_REPOSITORY_BINDING,
} from '../src/api/code-repository-commands.ts';
import { registeredCommand } from '../src/api/code-command-registry.ts';
import { restoreCodeCommand } from '../src/api/code-command-snapshot.ts';
import { commandReceipt } from '../src/api/code-command-receipts.ts';
import { ERROR_MESSAGES } from '../src/api/code-errors.ts';

const KEY = '00000000-0000-4000-8000-00000000000a';
const REQUEST = '00000000-0000-4000-8000-00000000000b';
const ORIGIN = 'http://localhost:5173';
const PATH = '/api/v1/code-repositories';
const BODY = { name: 'fixture', root_path: 'C:\\fixture' };
const accepted = (extra = {}) => ({
  resource_kind: 'REPOSITORY',
  resource_id: 3,
  operation_id: 17,
  operation_status: 'PENDING',
  ...extra,
});
const moment = '2026-11-06T00:00:00.000Z';
const operation = (extra = {}) => ({
  id: 17,
  task_id: null,
  testing_task_id: null,
  resource_kind: 'REPOSITORY',
  resource_id: 3,
  session_id: null,
  operation_type: 'REGISTER_REPOSITORY',
  idempotency_key: KEY,
  expected_state_version: null,
  fixed_input: { name: 'fixture' },
  control_generation: null,
  status: 'PENDING',
  created_at: moment,
  started_at: null,
  ended_at: null,
  failure_code: null,
  steps: ['VALIDATE', 'SAVE_FACT'].map((step_type, index) => ({
    operation_id: 17,
    step_no: index + 1,
    step_type,
    status: 'PENDING',
    external_identity: null,
    fixed_input: { name: 'fixture' },
    result_ref: null,
    started_at: null,
    ended_at: null,
    last_observed_at: null,
  })),
  content_capture: null,
  ...extra,
});
const response = (data, status = 200, pagination) =>
  new Response(
    JSON.stringify({
      success: true,
      data,
      error: null,
      meta: { request_id: REQUEST, ...(pagination === undefined ? {} : { pagination }) },
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  );
function api(fetcher, key = () => KEY) {
  return new WalleApi(new ApiClient(fetcher, key));
}

test('C01/C02 have exactly immutable 202 acceptance and bind the original refresh resource', () => {
  assert.deepEqual(REGISTER_REPOSITORY_BINDING.success_status, [202]);
  const original = registeredCommand('POST', PATH, KEY);
  REGISTER_REPOSITORY_BINDING.validate_input(BODY, original);
  assert.deepEqual(REGISTER_REPOSITORY_BINDING.decode(accepted(), original, BODY), accepted());
  const refresh = registeredCommand('POST', PATH + '/3/refresh', KEY);
  REFRESH_REPOSITORY_BINDING.validate_input({}, refresh);
  assert.deepEqual(REFRESH_REPOSITORY_BINDING.decode(accepted(), refresh, {}), accepted());
  assert.throws(() => REFRESH_REPOSITORY_BINDING.decode(accepted({ resource_id: 4 }), refresh, {}));
  for (const extra of [
    { resource_id: true },
    { operation_id: 0 },
    { operation_status: 'SUCCEEDED' },
    { task_id: 1 },
    { resource_kind: 'TASK' },
  ])
    assert.throws(() => REGISTER_REPOSITORY_BINDING.decode(accepted(extra), original, BODY));
});

test('registration rejects unknown input and relative paths; refresh keeps empty object', () => {
  const original = registeredCommand('POST', PATH, KEY);
  for (const body of [
    { ...BODY, task_id: 1 },
    { ...BODY, name: ' ' },
    { ...BODY, root_path: 'relative' },
    { ...BODY, root_path: null },
  ])
    assert.throws(() => REGISTER_REPOSITORY_BINDING.validate_input(body, original));
  assert.throws(() =>
    REFRESH_REPOSITORY_BINDING.validate_input(
      { repository_id: 3 },
      registeredCommand('POST', PATH + '/3/refresh', KEY),
    ),
  );
});

test('WalleApi freezes original bytes and restores C01 without a new key', async () => {
  let keys = 0;
  const calls = [];
  const client = new ApiClient(
    async (path, options) => {
      calls.push([path, options.headers['Idempotency-Key'], options.body]);
      return response(accepted(), 202);
    },
    () => {
      keys++;
      return KEY;
    },
  );
  const app = new WalleApi(client);
  const input = { ...BODY };
  const action = await app.prepareRegisterRepository(input, ORIGIN);
  input.name = 'changed';
  await action.submit();
  const restored = await restoreCodeCommand(
    client,
    action.frozen,
    REGISTER_REPOSITORY_BINDING,
    ORIGIN,
  );
  await restored.submit();
  assert.equal(keys, 1);
  assert.equal(action.recovery_mode, 'REPLAY_SAME_KEY');
  assert.deepEqual(calls, [
    [PATH, KEY, JSON.stringify(BODY)],
    [PATH, KEY, JSON.stringify(BODY)],
  ]);
  assert.deepEqual(restored.result_policy.success_status, [202]);
});

test('only the exact C01 readiness failure is known before original acceptance', async () => {
  const exactError = (code, details) =>
    new Response(
      JSON.stringify({
        success: false,
        data: null,
        error: { code, message: ERROR_MESSAGES[code], details },
        meta: { request_id: REQUEST },
      }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    );
  const unavailable = api(async () =>
    exactError('CONFIG_NOT_READY', { capability_codes: ['Q20-WINDOWS', 'Q20-GIT'] }),
  );
  const registration = await unavailable.prepareRegisterRepository(BODY, ORIGIN);
  await assert.rejects(
    () => registration.submit(),
    (error) => error instanceof ApiRejected && error.code === 'CONFIG_NOT_READY',
  );
  const refresh = await unavailable.prepareRefreshRepository(3, ORIGIN);
  await assert.rejects(() => refresh.submit(), ApiUnknown);
  const unknown = api(async () =>
    exactError('STORAGE_UNAVAILABLE', { capability_codes: ['DATABASE'] }),
  );
  const command = await unknown.prepareRegisterRepository(BODY, ORIGIN);
  await assert.rejects(() => command.submit(), ApiUnknown);
});

test('201 is never accepted as repository registration; operation receipt links stay exact', async () => {
  const app = api(async () => response({ resource_kind: 'REPOSITORY', resource_id: 3 }, 201));
  const action = await app.prepareRegisterRepository(BODY, ORIGIN);
  await assert.rejects(() => action.submit(), ApiUnknown);
  const original = registeredCommand('POST', PATH, KEY);
  const receipt = {
    lookup_status: 'FOUND',
    record_status: 'SUCCEEDED',
    original_http_status: 202,
    original_outcome: { success: true, data: accepted(), error: null },
    task_id: null,
    testing_task_id: null,
    operation_id: 17,
  };
  const policy = {
    decoder_kind: original.decoder_kind,
    success_status: [202],
    errors: [],
    decode: (value) => REGISTER_REPOSITORY_BINDING.decode(value, original, BODY),
  };
  assert.equal(commandReceipt(receipt, original, policy).operation_id, 17);
  assert.throws(() => commandReceipt({ ...receipt, operation_id: 18 }, original, policy));
  assert.throws(() => commandReceipt({ ...receipt, task_id: 1 }, original, policy));
  assert.throws(() => commandReceipt({ ...receipt, original_http_status: 201 }, original, policy));
});

test('original OperationView is deeply immutable and does not invent a source path', () => {
  const value = repositoryOperation(operation());
  assert.equal(value.fixed_input.name, 'fixture');
  assert.ok(Object.isFrozen(value.steps[0].fixed_input));
  assert.throws(() => {
    value.steps[0].fixed_input.name = 'changed';
  });
  assert.equal(Object.hasOwn(value.fixed_input, 'root_path'), false);
  const completed = operation({
    status: 'SUCCEEDED',
    steps: operation().steps.map((row, i) => ({
      ...row,
      status: 'SUCCEEDED',
      result_ref: i === 1 ? { repository_id: 3 } : null,
    })),
  });
  assert.equal(repositoryOperation(completed).status, 'SUCCEEDED');
});

test('OperationView rejects private paths/identities, crossed owners and invented success', () => {
  for (const extra of [
    { id: true },
    { task_id: 1 },
    { resource_kind: 'TASK' },
    { control_generation: 1 },
    { fixed_input: { ...BODY } },
    { failure_code: 'raw error at C:\\private' },
    { status: 'SUCCEEDED' },
    { steps: [] },
    { content_capture: { state: 'READY' } },
    {
      steps: operation().steps.map((row, i) =>
        i === 0 ? { ...row, external_identity: { guard_run_ref: 'secret' } } : row,
      ),
    },
    {
      steps: operation().steps.map((row, i) =>
        i === 1 ? { ...row, status: 'SUCCEEDED', result_ref: { repository_id: 99 } } : row,
      ),
    },
  ])
    assert.throws(() => repositoryOperation(operation(extra)));
});

test('WalleApi GET uses original operation ID and never prepares or refreshes', async () => {
  const calls = [];
  const app = api(
    async (path, options) => {
      calls.push([path, options.method]);
      return response(operation());
    },
    () => {
      throw Error('GET creates no key');
    },
  );
  assert.equal((await app.repositoryOperation(17)).data.status, 'PENDING');
  assert.deepEqual(calls, [['/api/v1/code-operations/17', 'GET']]);
});

test('operation read refuses another ID or unexpected pagination', async () => {
  for (const [data, pagination] of [
    [operation({ id: 18 }), undefined],
    [operation(), { page: 1, page_size: 20, total: 1, total_pages: 1 }],
  ]) {
    const app = api(async () => response(data, 200, pagination));
    await assert.rejects(() => app.repositoryOperation(17), ApiUnknown);
  }
});

test('failed original operation remains an explicit readable fact', () => {
  const data = repositoryOperation(operation({ status: 'FAILED', failure_code: 'SOURCE_BUSY' }));
  assert.equal(data.failure_code, 'SOURCE_BUSY');
  assert.equal(data.status, 'FAILED');
});

test('baseline progress accepts four original steps and only the final saved snapshot', () => {
  const fixed_input = {
    repository_id: 3,
    commit_oid: 'a'.repeat(40),
    execution_profile_version_id: 2,
  };
  const steps = ['VALIDATE_COMMIT', 'PIN_COMMIT', 'VERIFY_PINNED_OBJECTS', 'SAVE_BASELINE'].map(
    (step_type, index) => ({
      ...operation().steps[0],
      step_type,
      step_no: index + 1,
      status: index === 0 ? 'SUCCEEDED' : 'PENDING',
      fixed_input,
    }),
  );
  const original = operation({
    operation_type: 'REGISTER_BASE',
    fixed_input,
    steps,
    status: 'RUNNING',
  });
  assert.equal(repositoryOperation(original).steps[0].status, 'SUCCEEDED');
  assert.throws(() => repositoryOperation({ ...original, steps: steps.slice(0, 2) }));
  assert.throws(() =>
    repositoryOperation({
      ...original,
      steps: steps.map((row, index) =>
        index === 0 ? { ...row, result_ref: { closure_sha256: 'b'.repeat(64) } } : row,
      ),
    }),
  );
  const finished = {
    ...original,
    status: 'SUCCEEDED',
    steps: steps.map((row, index) => ({
      ...row,
      status: 'SUCCEEDED',
      result_ref: index === 3 ? { snapshot_id: 8 } : null,
    })),
  };
  assert.deepEqual(repositoryOperation(finished).steps[3].result_ref, { snapshot_id: 8 });
});

test('baseline registration uses its original repository, commit, profile and key on replay', async () => {
  const input = { commit_oid: 'a'.repeat(64), execution_profile_version_id: 7 };
  const calls = [];
  const app = api(async (url, options) => {
    calls.push([
      new URL(url, ORIGIN).pathname,
      new Headers(options.headers).get('Idempotency-Key'),
      options.body,
    ]);
    return response(accepted(), 202);
  });
  const command = await app.prepareRegisterCodeBaseline(3, input, ORIGIN);
  const restored = await restoreCodeCommand(
    app.client,
    command.frozen,
    REGISTER_CODE_BASELINE_BINDING,
    ORIGIN,
  );
  await command.submit();
  await restored.submit();
  assert.deepEqual(
    calls,
    Array.from({ length: 2 }, () => [PATH + '/3/snapshots', KEY, JSON.stringify(input)]),
  );
  assert.throws(() =>
    REGISTER_CODE_BASELINE_BINDING.decode(
      accepted({ resource_id: 4 }),
      registeredCommand('POST', PATH + '/3/snapshots', KEY),
      input,
    ),
  );
  await assert.rejects(() =>
    app.prepareRegisterCodeBaseline(3, { ...input, commit_oid: 'HEAD' }, ORIGIN),
  );
  assert.equal(calls.length, 2);
});
