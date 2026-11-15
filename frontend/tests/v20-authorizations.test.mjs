import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import {
  authorizationScope,
  authorizationGrant,
  AUTHORIZATION_BINDING,
} from '../src/api/code-authorizations.ts';
import { registeredCommand } from '../src/api/code-command-registry.ts';
import { restoreCodeCommand } from '../src/api/code-command-snapshot.ts';

const KEY = '00000000-0000-4000-8000-00000000000a',
  REQUEST = '00000000-0000-4000-8000-00000000000b';
const ORIGIN = 'http://localhost:5173',
  PATH = '/api/v1/code-authorizations';
function scope() {
  return {
    read_roots: [],
    write_workspace_only: true,
    allowed_command_ids: [],
    network_targets: [],
    model_profile_refs: ['deepseek-v2'],
    allow_local_delivery: false,
    limits: Object.fromEntries(
      [
        'max_model_requests',
        'max_output_tokens',
        'max_consecutive_failures',
        'max_active_seconds',
        'max_file_bytes',
        'max_snapshot_bytes',
        'max_snapshot_files',
        'max_capture_entries',
        'max_capture_seconds',
        'max_manifest_bytes',
        'max_git_seconds',
        'max_git_output_bytes',
        'max_delivery_window_seconds',
        'max_check_output_bytes',
        'max_check_cases',
        'max_case_steps',
        'max_case_payload_bytes',
        'query_timeout_seconds',
        'send_timeout_seconds',
        'queue_wait_seconds',
        'graceful_stop_seconds',
        'force_stop_wait_seconds',
      ].map((name) => [name, 10]),
    ),
  };
}
function grant(extra = {}) {
  return {
    id: 1,
    task_id: null,
    profile_version_id: 2,
    scope: scope(),
    status: 'APPROVED_UNBOUND',
    approved_at: '2026-11-05T00:00:00.000Z',
    actor_ref: 'test-only-native-source',
    ...extra,
  };
}
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
test('scope requires literal workspace isolation and exact bounded fields', () => {
  const value = scope(),
    parsed = authorizationScope(value);
  value.model_profile_refs.push('changed');
  assert.deepEqual(parsed.model_profile_refs, ['deepseek-v2']);
  assert.ok(Object.isFrozen(parsed.limits));
  for (const extra of [
    { write_workspace_only: false },
    { write_workspace_only: 1 },
    { allow_local_delivery: 'true' },
    { actor_ref: 'browser' },
    { allowed_command_ids: ['same', 'same'] },
    { limits: { ...scope().limits, max_model_requests: 0 } },
  ])
    assert.throws(() => authorizationScope({ ...scope(), ...extra }));
});
test('approval state and task binding remain distinct exact stored facts', () => {
  assert.equal(authorizationGrant(grant()).status, 'APPROVED_UNBOUND');
  for (const extra of [
    { status: 'EFFECTIVE' },
    { task_id: 3 },
    { status: 'invented' },
    { actor_ref: '' },
    { ready: true },
  ])
    assert.throws(() => authorizationGrant(grant(extra)));
  assert.equal(authorizationGrant(grant({ status: 'BOUND_PENDING_APPLY', task_id: 3 })).task_id, 3);
});
test('C15 rejects client actor and task state; exact result is AUTHORIZATION only', () => {
  const original = registeredCommand('POST', PATH, KEY);
  const value = { profile_version_id: 2, scope: scope() };
  AUTHORIZATION_BINDING.validate_input(value, original);
  assert.deepEqual(
    AUTHORIZATION_BINDING.decode(
      { resource_kind: 'AUTHORIZATION', resource_id: 9 },
      original,
      value,
    ),
    { resource_kind: 'AUTHORIZATION', resource_id: 9 },
  );
  for (const extra of [
    { actor_ref: 'browser' },
    { task_id: 1 },
    { approved_at: 'now' },
    { status: 'EFFECTIVE' },
  ])
    assert.throws(() => AUTHORIZATION_BINDING.validate_input({ ...value, ...extra }, original));
  assert.throws(() =>
    AUTHORIZATION_BINDING.decode(
      { resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: 9 },
      original,
      value,
    ),
  );
  assert.throws(() =>
    AUTHORIZATION_BINDING.validate_input(
      value,
      registeredCommand('POST', '/api/v1/code-check-sets', KEY),
    ),
  );
});
test('original approval scope is frozen and cold retry reuses original bytes and key', async () => {
  const calls = [];
  const fetcher = async (path, options) => {
    calls.push([path, options.headers['Idempotency-Key'], options.body]);
    return success({ resource_kind: 'AUTHORIZATION', resource_id: 9 }, 201);
  };
  const api = new WalleApi(new ApiClient(fetcher, () => KEY), {});
  const value = scope();
  const action = await api.prepareApproveCodeAuthorization(2, authorizationScope(value), ORIGIN);
  value.limits.max_output_tokens = 999;
  assert.equal(calls.length, 0);
  assert.equal(action.frozen.decoder_kind, 'APP-CODE-CMD-C15');
  await action.submit();
  const cold = new ApiClient(fetcher, () => {
    throw Error('No new key');
  });
  await (await restoreCodeCommand(cold, action.frozen, AUTHORIZATION_BINDING, ORIGIN)).submit();
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(JSON.parse(calls[0][2]).scope.limits.max_output_tokens, 10);
});
test('typed authorization details verify exact identity without pagination', async () => {
  const api = new WalleApi(new ApiClient(async () => success(grant())), {});
  assert.equal((await api.codeAuthorization(1)).data.actor_ref, 'test-only-native-source');
  await assert.rejects(
    new WalleApi(new ApiClient(async () => success(grant({ id: 2 }))), {}).codeAuthorization(1),
    ApiUnknown,
  );
});
test('history filters are transmitted exactly and returned task status and order are checked', async () => {
  const calls = [];
  const api = new WalleApi(
    new ApiClient(async (path) => {
      calls.push(path);
      return success(
        {
          items: [
            grant({ id: 2, task_id: 7, status: 'EFFECTIVE' }),
            grant({ task_id: 7, status: 'EFFECTIVE' }),
          ],
        },
        200,
        { page: 1, page_size: 20, total: 2, total_pages: 1 },
      );
    }),
    {},
  );
  assert.equal(
    (await api.codeAuthorizations(1, { task_id: 7, status: 'EFFECTIVE' })).data.items.length,
    2,
  );
  assert.equal(calls[0], PATH + '?page=1&task_id=7&status=EFFECTIVE');
  for (const rows of [
    [grant()],
    [
      grant({ id: 1, status: 'EFFECTIVE', task_id: 7 }),
      grant({ id: 2, status: 'EFFECTIVE', task_id: 7 }),
    ],
  ])
    await assert.rejects(
      new WalleApi(
        new ApiClient(async () =>
          success({ items: rows }, 200, {
            page: 1,
            page_size: 20,
            total: rows.length,
            total_pages: 1,
          }),
        ),
        {},
      ).codeAuthorizations(1, { task_id: 7, status: 'EFFECTIVE' }),
      ApiUnknown,
    );
});
test('a created approval cannot be mistaken for an accepted asynchronous application', async () => {
  const api = new WalleApi(
    new ApiClient(
      async () => success({ resource_kind: 'AUTHORIZATION', resource_id: 9 }, 202),
      () => KEY,
    ),
    {},
  );
  const action = await api.prepareApproveCodeAuthorization(2, authorizationScope(scope()), ORIGIN);
  await assert.rejects(action.submit(), (error) => error instanceof ApiUnknown && error.mutation);
});
