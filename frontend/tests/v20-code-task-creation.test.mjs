import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeTaskView } from '../src/api/code-task-creation.ts';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import { readCommandReceipt } from '../src/api/code-command-receipts.ts';
import { registeredCommand } from '../src/api/code-command-registry.ts';
import { START_CODE_TASK_BINDING, readTaskStartOperation } from '../src/api/code-task-start.ts';

const path = '/api/v1/documents/3/code-tasks';
const origin = 'http://localhost:5173';
const at = '2026-11-08T03:00:00.000Z';
const requestId = '00000000-0000-4000-8000-00000000000b';
const input = {
  design_revision_id: 7,
  material_refs: [{ document_id: 4, revision_id: 8 }],
  repository_id: 1,
  base_snapshot_id: 2,
  execution_profile_version_id: 5,
  authorization_id: 9,
  target_branch: 'refs/heads/main',
  budget_limit_cny: '0.1',
};
const summary = {
  id: 15, document_id: 3, status: 'PENDING', phase: 'PREPARING',
  state_version: 1, created_at: at, updated_at: at, current_candidate_id: null,
};
const actions = [
  'START', 'RESUME', 'ANSWER_QUESTION', 'DECIDE_PERMISSION', 'APPLY_CONFIGURATION',
  'INCREASE_BUDGET', 'PREPARE_HANDOFF', 'LINK_HANDOFF', 'REGISTER_DEFECT', 'VERIFY_CANDIDATE',
  'CAPTURE_AND_CHECK', 'REPAIR', 'HANDOFF_ROLE', 'PREPARE_DELIVERY', 'ACCEPT',
  'SUBMIT_FOR_TESTING', 'LINK_TEST_REPORT', 'TERMINATE', 'RECONCILE',
];
const enabled = ['APPLY_CONFIGURATION', 'INCREASE_BUDGET', 'TERMINATE', 'RECONCILE'];
const { budget_limit_cny, ...fixed } = input;
const task = {
  ...summary, ...fixed, requirement_id: 1, control_generation: 1,
  workspace_id: null, active_session_id: null, resume_phase: null, started_at: null,
  ended_at: null, stop_requested_at: null, stopped_at: null, last_observed_at: null,
  current_refs: { verification_id: null, test_report_id: null, delivery_plan_id: null, delivery_id: null },
  configuration_application: null,
  runtime: {
    isolation_mode: 'WINDOWS_LPAC', environment_status: 'NOT_PREPARED',
    activity_status: 'NOT_STARTED', stop_status: 'NONE', cleanup_status: 'NOT_STARTED',
    reason_codes: [], active_process_count: null, observed_at: null,
  },
  waiting_items: [], active_operations: [],
  budget: {
    limit_cny: '0.100000', settled_cny: '0.000000', reserved_cny: '0.000000',
    available_cny: '0.100000', unresolved_call_count: 0,
  },
  current_basis_difference: [{ document_id: 3, fixed_revision_id: 7, current_revision_id: 10 }],
  available_actions: actions.map((action) => ({
    action, related_id: null, enabled: enabled.includes(action),
    reason_code: enabled.includes(action) ? null
      : action === 'START' ? 'CONFIG_NOT_READY'
      : action === 'LINK_HANDOFF' ? 'PRECONDITION_FAILED' : 'INVALID_STATE',
  })),
  termination_operation_id: null,
  verification_purposes: ['CAPTURE_AND_CHECK', 'VERIFY_CANDIDATE'].map((action) => ({
    action, purpose: 'HANDOFF', enabled: false, reason_code: 'TASK_STATE',
  })),
};

function success(data, status = 200, pagination) {
  return new Response(JSON.stringify({
    success: true, data, error: null,
    meta: { request_id: requestId, ...(pagination ? { pagination } : {}) },
  }), { status, headers: { 'Content-Type': 'application/json' } });
}

test('creation freezes original input and binds the 201 and recovery receipt to one task', async () => {
  const editable = structuredClone(input);
  let posts = 0;
  const client = new ApiClient(async (url, request) => {
    assert.equal(url, path);
    assert.equal(request.method, 'POST');
    assert.equal(request.body, prepared.frozen.body_json);
    assert.equal(new Headers(request.headers).get('Idempotency-Key'), prepared.frozen.key);
    assert.deepEqual(JSON.parse(request.body), input);
    posts += 1;
    return success(task, 201);
  });
  const prepared = await new WalleApi(client, {}).prepareCreateCodeTask(3, editable, origin);
  editable.material_refs[0].revision_id = 99;
  const result = await prepared.submit();
  assert.deepEqual(result.data, task);
  assert.ok(Object.isFrozen(result.data.budget));
  assert.ok(Object.isFrozen(result.data.material_refs[0]));
  assert.equal(posts, 1);

  const original = registeredCommand('POST', path, prepared.frozen.key);
  const stored = {
    lookup_status: 'FOUND', record_status: 'SUCCEEDED', original_http_status: 201,
    task_id: task.id, testing_task_id: null, operation_id: null,
    original_outcome: { success: true, data: task, error: null },
  };
  const receipt = await readCommandReceipt(
    new ApiClient(async () => success(stored)), original, prepared.result_policy,
  );
  assert.deepEqual(receipt.data.original_outcome.data, task);
  await assert.rejects(
    readCommandReceipt(
      new ApiClient(async () => success({ ...stored, task_id: task.id + 1 })),
      original, prepared.result_policy,
    ),
    ApiUnknown,
  );
});

test('create rejects a response with a substituted fixed source or fabricated runtime', async () => {
  for (const wrong of [
    { ...task, document_id: 4 },
    { ...task, base_snapshot_id: 3 },
    { ...task, runtime: { ...task.runtime, active_process_count: 0 } },
  ]) {
    const api = new WalleApi(new ApiClient(async () => success(wrong, 201)), {});
    const prepared = await api.prepareCreateCodeTask(3, input, origin);
    await assert.rejects(prepared.submit(), ApiUnknown);
  }
});

test('task summaries bind the selected document, filters and pagination', async () => {
  const api = new WalleApi(new ApiClient(async (url) => {
    assert.equal(url, path + '?page=2&status=PENDING&status=RUNNING&design_revision_id=7');
    return success({ items: [] }, 200, { page: 2, page_size: 20, total: 1, total_pages: 1 });
  }), {});
  const response = await api.documentCodeTasks(3, 2, {
    statuses: ['PENDING', 'PENDING', 'RUNNING'], designRevisionId: 7,
  });
  assert.deepEqual(response.data.items, []);
  assert.equal(response.meta.pagination.total, 1);
  const invalid = new WalleApi(new ApiClient(async () => success(
    { items: [{ ...summary, document_id: 9 }] }, 200, { page: 1, page_size: 20, total: 1, total_pages: 1 },
  )), {});
  await assert.rejects(invalid.documentCodeTasks(3), ApiUnknown);
});

test('current task detail binds its task ID without relying on the original creation result', async () => {
  const current = {
    ...task,
    current_basis_difference: [{ document_id: 3, fixed_revision_id: 7, current_revision_id: 11 }],
  };
  const api = new WalleApi(new ApiClient(async (url, options) => {
    assert.equal(url, '/api/v1/code-tasks/15');
    assert.equal(options.method, 'GET');
    return success(current);
  }), {});
  assert.deepEqual((await api.codeTask(15)).data, current);
  await assert.rejects(api.codeTask(16), ApiUnknown);
});

test('confirmed empty stop supports fenced start and budget versions', () => {
  const stopped = {
    ...task, status: 'TERMINATED', phase: 'FINISHED', state_version: 4, control_generation: 2,
    stop_requested_at: at, ended_at: at, stopped_at: at, last_observed_at: at,
    termination_operation_id: 39,
    runtime: { ...task.runtime, stop_status: 'VERIFIED', cleanup_status: 'VERIFIED', active_process_count: 0, observed_at: at },
    available_actions: actions.map((action) => ({
      action, enabled: action === 'RECONCILE', reason_code: action === 'RECONCILE' ? null : 'TASK_ENDED',
      related_id: action === 'TERMINATE' ? 39 : null,
    })),
  };
  assert.equal(decodeTaskView(stopped).state_version, 4);
  assert.equal(decodeTaskView({ ...stopped, state_version: 7 }).state_version, 7);
  assert.throws(() => decodeTaskView({ ...stopped, state_version: 2 }));
});


test('start requires the original task and exactly one state-version increment', () => {
  const original = registeredCommand('POST', '/api/v1/code-tasks/15/start', requestId);
  const request = { expected_state_version: 8 };
  const received = {
    task_id: 15, operation_id: 22, operation_status: 'PENDING', task_status: 'PENDING',
    state_version: 9,
  };
  const { decode, success_status } = START_CODE_TASK_BINDING;
  assert.deepEqual(success_status, [202]);
  assert.deepEqual(decode(received, original, request), received);
  assert.throws(() => decode({ ...received, task_id: 16 }, original, request), TypeError);
  assert.throws(() => decode({ ...received, state_version: 8 }, original, request), TypeError);
  assert.throws(() => decode({ ...received, task_status: 'RUNNING' }, original, request), TypeError);
});


test('original instance readiness exposes only its safe id and keeps START running', async () => {
  const fixed = { task_id: 15, expected_state_version: 8 };
  const stages = ['RESTORE_WORKSPACE', 'PREPARE_BASIS', 'CHECK_CONDITIONS', 'START_INSTANCE', 'CREATE_SESSION', 'SEND_INITIAL'];
  const results = [
    { workspace_id: 2 }, { document_count: 1 },
    { fixed_content_verified: true, capability_codes: [], system_config_clear: true },
    { instance_id: 9 }, null, null,
  ];
  const operation = {
    id: 22, task_id: 15, testing_task_id: null, resource_kind: 'TASK', resource_id: 15,
    session_id: null, operation_type: 'START', idempotency_key: requestId,
    expected_state_version: 8, fixed_input: fixed, control_generation: 1,
    status: 'RUNNING', created_at: at, started_at: at, ended_at: null, failure_code: null,
    content_capture: null,
    steps: stages.map((step_type, index) => ({
      operation_id: 22, step_no: index + 1, step_type,
      status: index < 4 ? 'SUCCEEDED' : 'PENDING', fixed_input: fixed, result_ref: results[index],
      external_identity: index < 4 && index !== 2 ? {} : null,
      started_at: index < 4 ? at : null, ended_at: index < 4 ? at : null,
      last_observed_at: index < 4 ? at : null,
    })),
  };
  const client = {
    async read(route, decode) {
      assert.equal(route, '/api/v1/code-operations/22');
      return { data: decode(operation), meta: {} };
    },
  };
  assert.deepEqual((await readTaskStartOperation(client, 22, 15)).data, {
    id: 22, task_id: 15, status: 'RUNNING',
  });
  operation.steps[3].result_ref = { instance_id: 9, pid: 10 };
  await assert.rejects(readTaskStartOperation(client, 22, 15));
  operation.steps[3].result_ref = { instance_id: 9 };
  operation.steps[2].status = 'PENDING';
  operation.steps[2].result_ref = null;
  await assert.rejects(readTaskStartOperation(client, 22, 15));
});


test('active transitions disable configuration without reading incomplete sources', () => {
  const current = {
    ...task, status: 'VERIFYING', phase: 'BACKEND', state_version: 4,
    workspace_id: 20, active_session_id: null, current_candidate_id: 30,
    current_refs: { ...task.current_refs, verification_id: 40 },
    started_at: at, last_observed_at: at,
    runtime: {
      ...task.runtime, environment_status: 'VERIFIED', activity_status: 'UNKNOWN', observed_at: at,
    },
    active_operations: [{ id: 50, operation_type: 'HANDOFF_ROLE', status: 'RUNNING' }],
    available_actions: actions.map(action => ({
      action, related_id: null,
      enabled: action === 'INCREASE_BUDGET' || action === 'TERMINATE',
      reason_code: action === 'INCREASE_BUDGET' || action === 'TERMINATE' ? null
        : action === 'APPLY_CONFIGURATION' ? 'OPERATION_IN_PROGRESS' : 'INVALID_STATE',
    })),
  };
  assert.equal(decodeTaskView(current).active_operations[0].id, 50);
  const checking = {
    ...current, active_session_id: 60,
    runtime: { ...current.runtime, activity_status: 'QUIESCENT', active_process_count: 1 },
    active_operations: [{ id: 51, operation_type: 'VERIFY_CANDIDATE', status: 'PENDING' }],
  };
  assert.equal(decodeTaskView(checking).active_operations[0].id, 51);
  assert.throws(() => decodeTaskView({ ...checking, active_operations: [] }));
});

test('configuration waiting keeps the original operation and application together', () => {
  const current = {
    ...task, status: 'WAITING', phase: 'BACKEND', resume_phase: 'BACKEND',
    state_version: 5, workspace_id: 20, active_session_id: 60, current_candidate_id: 30,
    current_refs: { ...task.current_refs, verification_id: 40 },
    started_at: at, last_observed_at: at,
    runtime: {
      ...task.runtime, environment_status: 'VERIFIED', activity_status: 'UNKNOWN', observed_at: at,
    },
    active_operations: [{ id: 52, operation_type: 'APPLY_CONFIGURATION', status: 'RUNNING' }],
    configuration_application: {
      id: 70, status: 'PENDING', new_profile_version_id: 6, authorization_id: 10,
      evidence_result: null, difference_kinds: [], observed_at: null,
    },
    waiting_items: [{
      id: 71, task_id: task.id, testing_task_id: null, kind: 'CONFIGURATION',
      source_kind: 'OPERATION', source_id: 52, resume_phase: 'BACKEND', status: 'OPEN',
      created_at: at, resolved_at: null, resolution_ref: null,
    }],
    available_actions: actions.map(action => ({
      action, related_id: action === 'APPLY_CONFIGURATION' ? 52 : null,
      enabled: action === 'INCREASE_BUDGET' || action === 'TERMINATE',
      reason_code: action === 'INCREASE_BUDGET' || action === 'TERMINATE' ? null
        : action === 'APPLY_CONFIGURATION' ? 'OPERATION_IN_PROGRESS' : 'INVALID_STATE',
    })),
  };
  assert.equal(decodeTaskView(current).configuration_application.id, 70);
  const lost = {
    ...current, active_operations: [],
    available_actions: current.available_actions.map(item => item.action === 'APPLY_CONFIGURATION'
      ? { ...item, related_id: null, reason_code: 'INVALID_STATE' } : item),
  };
  assert.throws(() => decodeTaskView(lost));
});


test('published configuration preserves valid testing and acceptance views', () => {
  for (const linked of [false, true]) {
    const published = {
      ...task, status: linked ? 'AWAITING_ACCEPTANCE' : 'AWAITING_TESTING',
      phase: linked ? 'ACCEPTANCE' : 'TESTING',
      state_version: 12, workspace_id: 20, active_session_id: 60, current_candidate_id: 30,
      current_refs: {
        verification_id: 40, test_report_id: linked ? 41 : null,
        delivery_plan_id: linked ? 42 : null, delivery_id: null,
      },
      started_at: at, last_observed_at: at,
      runtime: {
        ...task.runtime, environment_status: 'VERIFIED', activity_status: 'UNKNOWN',
        observed_at: null,
      },
      available_actions: actions.map(action => ({
        action, related_id: null,
        enabled: ['APPLY_CONFIGURATION', 'INCREASE_BUDGET', 'TERMINATE'].includes(action),
        reason_code: ['APPLY_CONFIGURATION', 'INCREASE_BUDGET', 'TERMINATE'].includes(action)
          ? null : 'INVALID_STATE',
      })),
    };
    assert.equal(decodeTaskView(published).status, published.status);
    const busy = {
      ...published,
      available_actions: published.available_actions.map(item =>
        item.action === 'APPLY_CONFIGURATION'
          ? { ...item, enabled: false, reason_code: 'CONFIG_NOT_READY' } : item),
    };
    assert.equal(decodeTaskView(busy).status, published.status);
    assert.throws(() => decodeTaskView({
      ...published,
      available_actions: published.available_actions.map(item =>
        item.action === 'APPLY_CONFIGURATION'
          ? { ...item, related_id: 99 } : item),
    }));
    assert.throws(() => decodeTaskView({
      ...published,
      available_actions: published.available_actions.map(item =>
        item.action === 'APPLY_CONFIGURATION'
          ? { ...item, enabled: false, reason_code: 'UNREGISTERED' } : item),
    }));
  }
});
