import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import {
  executionProfileContent,
  executionProfileVersion,
  EXECUTION_PROFILE_VERSION_BINDING,
} from '../src/api/code-execution-profiles.ts';
import { registeredCommand } from '../src/api/code-command-registry.ts';
import { restoreCodeCommand } from '../src/api/code-command-snapshot.ts';

const KEY = '00000000-0000-4000-8000-00000000000a';
const REQUEST = '00000000-0000-4000-8000-00000000000b';
const ORIGIN = 'http://localhost:5173';
const PATH = '/api/v1/code-execution-profiles/7/versions';
function body() {
  const binding = {
    native_model_id: 'walle-code',
    purpose: 'CODE',
    model_profile_ref: 'deepseek-v2',
    model_snapshot_ref: 'test-only-snapshot',
    price_version_id: 1,
    input_cap_tokens: 1000,
    context_cap_tokens: 2000,
    output_cap_tokens: 100,
    admission_ref: 'test-only',
  };
  const names = [
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
  ];
  return {
    executor: {
      version: '1.19.5',
      binary_ref: 'test-only-executor',
      adapter_contract_version: 'test-adapter',
      runtime_bundle_ref: 'test-runtime',
      configuration_policy_version: 'OC20-CONFIG-1',
      runtime_policy_version: 'WIN20-ISOLATION-1',
    },
    git: {
      version: '2.56.0.windows.4',
      binary_ref: 'test-only-git',
      runtime_bundle_ref: 'test-runtime',
      source_commit: '581291682ad5a238c08c93d1f5bd4518382a3230',
      protocol_version: 'GIT20-LOCAL-1',
    },
    models: {
      primary_profile_ref: 'deepseek-v2',
      auxiliary_profile_refs: [],
      protocol_version: 'OC20-MODEL-1',
      bindings: [
        binding,
        { ...binding, native_model_id: 'walle-compaction', purpose: 'COMPACTION' },
      ],
    },
    environment: { python_ref: null, node_ref: null, package_manager_refs: [], secret_refs: [] },
    commands: [],
    capture_rules: {
      content_policy_version: 'CONTENT20-STORE-1',
      product_include_paths: ['.'],
      nonproduct_exclude_paths: [],
      new_file_mode: '100644',
      secret_policy_ref: 'test-policy',
    },
    delivery: null,
    check_set_version_id: 1,
    limits: Object.fromEntries(names.map((name) => [name, 100])),
    capability_evidence_refs: [],
  };
}
function version(extra = {}) {
  return {
    id: 1,
    profile_id: 7,
    version: 1,
    ...body(),
    created_at: '2026-11-05T00:00:00.000Z',
    ready: false,
    unresolved_capability_codes: ['Q20-MODEL'],
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
function delivery(message_template) {
  return {
    author_name: '作者',
    author_email: 'author@example.test',
    committer_name: '提交者',
    committer_email: 'committer@example.test',
    message_template,
  };
}

test('C07 input and result are scoped to the original parent and exact resource type', () => {
  const original = registeredCommand('POST', PATH, KEY);
  EXECUTION_PROFILE_VERSION_BINDING.validate_input(body(), original);
  assert.deepEqual(
    EXECUTION_PROFILE_VERSION_BINDING.decode(
      { resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: 9 },
      original,
      body(),
    ),
    { resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: 9 },
  );
  for (const value of [
    { resource_kind: 'EXECUTION_PROFILE', resource_id: 9 },
    { resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: true },
    { resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: 9, ready: true },
  ])
    assert.throws(
      () => EXECUTION_PROFILE_VERSION_BINDING.decode(value, original, body()),
      TypeError,
    );
  assert.throws(() =>
    EXECUTION_PROFILE_VERSION_BINDING.validate_input(
      body(),
      registeredCommand('POST', '/api/v1/code-execution-profiles', KEY),
    ),
  );
});
test('exact nested configuration rejects forged server metadata and version overrides', () => {
  for (const extra of [
    { ready: true },
    { id: 1 },
    { version: 1 },
    { created_at: 'x' },
    { owner_module: 'TESTING' },
  ])
    assert.throws(() => executionProfileContent({ ...body(), ...extra }));
  for (const field of Object.keys(body())) {
    const value = body();
    delete value[field];
    assert.throws(() => executionProfileContent(value));
  }
  for (const [field, key] of [
    ['executor', 'version'],
    ['git', 'source_commit'],
    ['models', 'protocol_version'],
    ['capture_rules', 'content_policy_version'],
  ]) {
    const value = body();
    value[field][key] = 'latest';
    assert.throws(() => executionProfileContent(value));
  }
});
test('all execution limits reject coercion unsafe values and enlarged delivery window', () => {
  for (const name of Object.keys(body().limits))
    for (const bad of [0, -1, true, '2', 1.5, Number.MAX_SAFE_INTEGER + 1]) {
      const value = body();
      value.limits[name] = bad;
      assert.throws(() => executionProfileContent(value));
    }
  const value = body();
  value.limits.max_delivery_window_seconds = 301;
  assert.throws(() => executionProfileContent(value));
});
test('two explicit aliases cannot silently fall back or increase output caps', () => {
  for (const mutate of [
    (value) => value.models.bindings.pop(),
    (value) => (value.models.bindings[1] = value.models.bindings[0]),
    (value) => (value.models.bindings[0].purpose = 'COMPACTION'),
    (value) => (value.models.bindings[0].output_cap_tokens = 101),
    (value) => (value.models.bindings[1].model_profile_ref = 'doubao-v1'),
    (value) => (value.models.auxiliary_profile_refs = ['deepseek-v2']),
  ]) {
    const value = body();
    mutate(value);
    assert.throws(() => executionProfileContent(value));
  }
  const value = body();
  value.models.auxiliary_profile_refs = ['doubao-v1'];
  value.models.bindings[1].model_profile_ref = 'doubao-v1';
  assert.equal(executionProfileContent(value).models.bindings[1].model_profile_ref, 'doubao-v1');
});
test('command data is detached immutable JSON and free shell or control Git are rejected', () => {
  const value = body();
  value.commands = [
    {
      command_id: 'test',
      executable_ref: 'node',
      argument_template: ['--test'],
      working_directory: '.',
      purpose: 'CHECK',
      timeout_seconds: 30,
      network_scope_ref: null,
    },
  ];
  const parsed = executionProfileContent(value);
  value.commands[0].argument_template.push('changed');
  assert.deepEqual(parsed.commands[0].argument_template, ['--test']);
  assert.ok(Object.isFrozen(parsed.commands[0].argument_template));
  for (const changes of [
    { purpose: 'CONTROL_GIT' },
    { argument_template: 'cmd /c arbitrary' },
    { working_directory: '../outside' },
    { timeout_seconds: true },
  ])
    assert.throws(() =>
      executionProfileContent({ ...value, commands: [{ ...value.commands[0], ...changes }] }),
    );
});
test('delivery permits only literal IDs and escaped braces; read never normalizes CR', () => {
  for (const message of [
    '',
    '{{literal}} {task_id} {candidate_id}',
    '{task_id:}',
    'task\r\n{task_id}',
  ])
    assert.equal(
      executionProfileContent({ ...body(), delivery: delivery(message) }).delivery.message_template,
      message,
    );
  for (const message of [
    '{HOME}',
    '{task_id!r}',
    '{task_id:04}',
    '{task_id.__class__}',
    'WALL-E-Delivery: 9',
    '}',
  ])
    assert.throws(() => executionProfileContent({ ...body(), delivery: delivery(message) }));
  assert.throws(() =>
    executionProfileVersion(version({ delivery: delivery('task\r\n{task_id}') })),
  );
});
test('readiness is a consistent fact, never inferred from fields that happen to exist', () => {
  for (const extra of [
    { ready: true },
    { unresolved_capability_codes: [] },
    { unresolved_capability_codes: ['invented'] },
    { unresolved_capability_codes: ['Q20-MODEL', 'Q20-MODEL'] },
  ])
    assert.throws(() => executionProfileVersion(version(extra)));
  assert.equal(executionProfileVersion(version()).ready, false);
});
test('original C07 frozen bytes survive a cold restore without allocating a new key', async () => {
  const calls = [];
  const client = new ApiClient(
    async (path, options) => {
      calls.push([path, options.headers['Idempotency-Key'], options.body]);
      return success({ resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: 9 }, 201);
    },
    () => KEY,
  );
  const api = new WalleApi(client, {});
  const action = await api.preparePublishCodeExecutionProfileVersion(
    7,
    executionProfileContent(body()),
    ORIGIN,
  );
  assert.equal(calls.length, 0);
  assert.equal(action.frozen.decoder_kind, 'APP-CODE-CMD-C07');
  await action.submit();
  const cold = new ApiClient(
    async (path, options) => {
      calls.push([path, options.headers['Idempotency-Key'], options.body]);
      return success({ resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: 9 }, 201);
    },
    () => {
      throw Error('No new key');
    },
  );
  await (
    await restoreCodeCommand(cold, action.frozen, EXECUTION_PROFILE_VERSION_BINDING, ORIGIN)
  ).submit();
  assert.deepEqual(calls[0], calls[1]);
});
test('typed details and pages preserve parent identity and descending versions', async () => {
  const api = new WalleApi(
    new ApiClient(async (path) =>
      path.includes('code-execution-profile-versions')
        ? success(version())
        : success({ items: [version({ id: 2, version: 2 }), version()] }, 200, {
            page: 1,
            page_size: 20,
            total: 2,
            total_pages: 1,
          }),
    ),
    {},
  );
  assert.equal((await api.codeExecutionProfileVersion(1)).data.id, 1);
  assert.deepEqual(
    (await api.codeExecutionProfileVersions(7)).data.items.map((row) => row.version),
    [2, 1],
  );
  const wrong = new WalleApi(new ApiClient(async () => success(version({ id: 2 }))), {});
  await assert.rejects(wrong.codeExecutionProfileVersion(1), ApiUnknown);
  for (const rows of [[version({ profile_id: 8 })], [version(), version({ id: 2, version: 2 })]])
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
      ).codeExecutionProfileVersions(7),
      ApiUnknown,
    );
});
test('C07 synchronous created result cannot be replaced by an asynchronous response', async () => {
  const api = new WalleApi(
    new ApiClient(
      async () => success({ resource_kind: 'EXECUTION_PROFILE_VERSION', resource_id: 9 }, 202),
      () => KEY,
    ),
    {},
  );
  const action = await api.preparePublishCodeExecutionProfileVersion(
    7,
    executionProfileContent(body()),
    ORIGIN,
  );
  await assert.rejects(action.submit(), (error) => error instanceof ApiUnknown && error.mutation);
});
