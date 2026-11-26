import assert from 'node:assert/strict';
import test from 'node:test';
import { loadDraft, saveLocal } from '../src/testing/plan-editor/draft.ts';

import { ApiClient, ApiNotSent, ApiRejected, ApiUnknown } from '../src/api/client.ts';
import { EnvironmentConnection } from '../src/api/environment-connection.ts';
import { allowsOrdinaryRequest } from '../src/api/environment-actions.ts';
import { loadBoundEnvironment, parseEnvironmentJson } from '../src/api/environment-binding.ts';
import {
  EnvironmentStorageInvalid,
  ScopedStoragePort,
  readScopedHistory,
  scopedHistoryState,
} from '../src/api/environment-storage.ts';

const environment = '673bc7cb-5050-4ce8-a9bc-b7733dde9180';
const generation = '2a55d008-b25c-4c8b-86df-9e4f252afe8a';
const run = 'ef9bd422-44a3-4d0c-a2d5-f830ed815a4d';
const nextRun = '68dd33a1-1de7-4f5c-b44e-5f87efc009de';
const other = '0f9bc28b-39ef-456c-8c38-18b8d623a35d';
const requestId = '52468f0f-8985-485e-b634-115df2b8a901';
const origin = 'https://e-' + environment + '.walle-dev.test:9443';
const now = '2026-11-20T09:00:00.000Z';
const configuration = {
  format_version: 1,
  binding_protocol: 1,
  environment_id: environment,
  data_generation: generation,
  purpose: 'DEVELOPMENT',
  display_name: '开发环境',
  configuration_sha256: 'd'.repeat(64),
  public_origin: origin,
  api_base: '/api/v1',
  management_url: null,
};
const handshake = {
  environment_id: environment,
  data_generation: generation,
  purpose: 'DEVELOPMENT',
  binding_protocol: 1,
  run_id: run,
  phase: 'READY',
  observed_at: now,
  configuration_sha256: configuration.configuration_sha256,
  access: { client_kind: 'WEB', permission: 'DEVELOP' },
  capabilities: [
    'DOCUMENT_READ',
    'DOCUMENT_WRITE',
    'DOCUMENT_AI',
    'TEST_PLAN_AI',
    'INTERNAL_EXECUTION',
    'INDEPENDENT_CHECK',
  ].map((code, index) => ({
    code,
    state: index < 2 ? 'READY' : 'DISABLED',
    reason_code: index < 2 ? null : 'CONFIG_DISABLED',
  })),
  maintenance: {
    contract_version: 1,
    admission: 'OPEN',
    maintenance_id: null,
    stage: null,
    control_revision: 3,
    reason_code: null,
    allowed_drain_actions: [],
    recovery_read: {
      status: 'NOT_APPLICABLE',
      observed_at: now,
      deployment_id: other,
      data_generation: generation,
      control_revision: 3,
      verification_ref: null,
      verified_scopes: [],
      blockers: [],
    },
  },
};

function success(data) {
  return { success: true, data, error: null, meta: { request_id: requestId } };
}

function response(value, { status = 200, environmentId = environment, runId = run } = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      'X-WALL-E-Environment-ID': environmentId,
      'X-WALL-E-Data-Generation': generation,
      'X-WALL-E-Run-ID': runId,
    },
  });
}

function setupFetch(onRequest = () => undefined, handshakeData = handshake) {
  return async (path, options) => {
    onRequest(path, options);
    return path.startsWith('/.well-known')
      ? response(configuration)
      : response(success(handshakeData));
  };
}

test('read fixed entry before handshake with same-origin credentials', async () => {
  const requests = [];
  const stages = [];
  const bound = await loadBoundEnvironment(
    origin,
    undefined,
    setupFetch((path, options) => {
      requests.push(path);
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.redirect, 'error');
      assert.equal(options.headers['X-WALL-E-Client'], 'web-v1');
    }),
    (stage) => stages.push(stage),
  );
  assert.deepEqual(stages, ['CONFIG_LOADING', 'HANDSHAKING']);
  assert.deepEqual(requests, ['/.well-known/walle-environment.json', '/api/v1/environment']);
  assert.equal(bound.scope.data_generation, generation);
  assert.equal(bound.runId, run);
  assert(Object.isFrozen(bound.scope));
});

test('a configured validation domain is still bound to its exact environment and browser origin', async () => {
  const customOrigin = 'https://e-' + environment + '.validation.example.test';
  for (const expected of [customOrigin, customOrigin + ':9443']) {
    const calls = [];
    const bound = await loadBoundEnvironment(expected, undefined, async (path) => {
      calls.push(path);
      return path.startsWith('/.well-known')
        ? response({ ...configuration, public_origin: expected })
        : response(success(handshake));
    });
    assert.equal(bound.scope.origin, expected);
    assert.deepEqual(calls, ['/.well-known/walle-environment.json', '/api/v1/environment']);
  }
  for (const [current, advertised] of [
    [customOrigin, origin],
    [customOrigin.replace(environment, other), customOrigin.replace(environment, other)],
    [customOrigin + ':443', customOrigin + ':443'],
    [customOrigin + '/page', customOrigin + '/page'],
    [customOrigin.replace('validation.', '*.'), customOrigin.replace('validation.', '*.')],
    ['https://e-' + environment + '.127.0.0.1', 'https://e-' + environment + '.127.0.0.1'],
  ]) {
    const calls = [];
    await assert.rejects(
      loadBoundEnvironment(current, undefined, async (path) => {
        calls.push(path);
        return response({ ...configuration, public_origin: advertised });
      }),
      { code: 'SCOPE_CHANGED' },
    );
    assert.deepEqual(calls, ['/.well-known/walle-environment.json']);
  }
});

test('a candidate starts only when the fixed entry and live handshake agree on its purpose', async () => {
  const candidate = { ...configuration, purpose: 'CANDIDATE', display_name: '候选验证环境' };
  const fetchEntry = (purpose) => async (path) =>
    path.startsWith('/.well-known')
      ? response(candidate)
      : response(success({ ...handshake, purpose }));
  const bound = await loadBoundEnvironment(origin, undefined, fetchEntry('CANDIDATE'));
  assert.equal(bound.purpose, 'CANDIDATE');
  assert.equal(bound.displayName, '候选验证环境');
  assert.equal(bound.scope.data_generation, generation);
  await assert.rejects(
    loadBoundEnvironment(origin, undefined, fetchEntry('INTEGRATION')),
    { code: 'SCOPE_CHANGED' },
  );
});

test('startup stops before a handshake when entry authentication, permission or protocol fails', async () => {
  for (const [status, failure] of [[401, 'ACCESS'], [403, 'PERMISSION'], [503, 'NOT_READY'], [200, 'PROTOCOL']]) {
    const paths = [];
    const phases = [];
    await assert.rejects(
      loadBoundEnvironment(origin, undefined, async (path) => {
        paths.push(path);
        return response({ ...configuration, binding_protocol: 2 }, { status });
      }, (phase) => phases.push(phase)),
      { code: failure },
    );
    assert.deepEqual(paths, ['/.well-known/walle-environment.json']);
    assert.deepEqual(phases, ['CONFIG_LOADING']);
  }
});

test('reject duplicate decoded keys, wrong handshake identity and oversized configuration', async () => {
  assert.throws(() => parseEnvironmentJson('{"ignored":[{"a":1,"\\u0061":2}]}'));
  await assert.rejects(
    loadBoundEnvironment(origin, undefined, setupFetch(undefined, { ...handshake, environment_id: other })),
    { code: 'SCOPE_CHANGED' },
  );
  await assert.rejects(
    loadBoundEnvironment(
      origin,
      undefined,
      async () => response({ ...configuration, display_name: '字'.repeat(6000) }),
    ),
    { code: 'UNREACHABLE' },
  );
});

test('ordinary environment admits actual manual routes and preserves saved reads', () => {
  const admitted = [
    ['GET', '/api/v1/requirements?page=2'],
    ['GET', '/api/v1/requirements/3/comment-index?document_id=5'],
    ['GET', '/api/v1/requirements/3/messages?document_id=5'],
    ['GET', '/api/v1/conversation-messages/3'],
    ['GET', '/api/v1/testing-command-receipts?operation_id=5'],
    ['POST', '/api/v1/requirements'],
    ['POST', '/api/v1/requirements/3/documents'],
    ['POST', '/api/v1/requirements/3/manual-draft'],
    ['PUT', '/api/v1/requirements/3/manual-draft'],
    ['POST', '/api/v1/requirements/3/manual-draft/complete'],
    ['DELETE', '/api/v1/requirements/3/manual-draft'],
  ];
  const refused = [
    ['GET', '/api/v1/requirements/3/guide-runs'],
    ['GET', '/api/v1/code-tasks/3'],
    ['GET', '/api/v1/model-calls/5'],
    ['PATCH', '/api/v1/requirements/3'],
    ['PATCH', '/api/v1/documents/5'],
    ['POST', '/api/v1/requirements/3/revisions'],
    ['POST', '/api/v1/requirements/3/comments'],
    ['POST', '/api/v1/conversation-messages/3/responses'],
    ['POST', '/api/v1/requirements/3/manual-draft/complete-extra'],
  ];
  for (const [method, path] of admitted) assert.equal(allowsOrdinaryRequest(method, path), true, path);
  for (const [method, path] of refused) assert.equal(allowsOrdinaryRequest(method, path), false, path);
});

test('ordinary environment blocks a frozen card action before transport without inventing receipts', async () => {
  const original = await loadBoundEnvironment(origin, undefined, setupFetch());
  const connection = new EnvironmentConnection(original);
  const calls = [];
  const send = async (route) => {
    calls.push(route);
    return response(success({ id: 1 }));
  };
  const api = new ApiClient(send, () => requestId, original, connection);
  const target = '/api/v1/conversation-messages/3/responses';
  const action = api.prepare('POST', target, {}, { idempotent: true, success_status: 200 });
  const actual = api.exportPrepared(action);
  await assert.rejects(api.commit(action, value => value), (error) =>
    error instanceof ApiNotSent && error.code === 'ENVIRONMENT_CAPABILITY_DISABLED' &&
    error.request_id === null && error.status === null);
  assert.deepEqual(api.exportPrepared(action), actual);
  assert.deepEqual(calls, []);
  await api.read('/api/v1/conversation-messages/3', value => value);
  assert.deepEqual(calls, ['/api/v1/conversation-messages/3']);
  await new ApiClient(send).read('/api/v1/requirements/3/guide-runs', value => value);
  assert.deepEqual(calls, ['/api/v1/conversation-messages/3', '/api/v1/requirements/3/guide-runs']);
  connection.dispose();
});

function closedHandshake() {
  const actual = structuredClone(handshake);
  actual.access.permission = 'READ_ONLY';
  actual.capabilities[1] = {
    code: 'DOCUMENT_WRITE',
    state: 'DISABLED',
    reason_code: 'RECOVERY_READ_ONLY',
  };
  const revision = 9;
  const reason = 'RECOVERY_RECONCILIATION_REQUIRED';
  Object.assign(actual.maintenance, {
    admission: 'CLOSED',
    maintenance_id: requestId,
    stage: 'BLOCKED',
    control_revision: revision,
    reason_code: reason,
  });
  Object.assign(actual.maintenance.recovery_read, {
    status: 'AVAILABLE',
    control_revision: revision,
    verification_ref: 'a'.repeat(64),
    verified_scopes: ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
    blockers: [reason],
  });
  return actual;
}

test('closed maintenance entry requires a matching current verification and read-only access', async () => {
  const actual = closedHandshake();
  const bound = await loadBoundEnvironment(origin, undefined, setupFetch(undefined, actual));
  assert.deepEqual(bound.recovery, {
    controlRevision: 9,
    maintenanceId: requestId,
    deploymentId: other,
    verificationRef: 'a'.repeat(64),
    observedAt: now,
  });
  assert.equal(bound.userPermission, 'READ_ONLY');
  for (const damage of [
    (data) => { data.maintenance.recovery_read.data_generation = other; },
    (data) => { data.maintenance.recovery_read.control_revision--; },
    (data) => { data.maintenance.recovery_read.verification_ref = null; },
    (data) => { data.maintenance.recovery_read.verified_scopes.pop(); },
    (data) => { data.maintenance.recovery_read.status = 'BLOCKED'; },
    (data) => { data.maintenance.admission = 'OPEN'; },
    (data) => { data.capabilities[1] = handshake.capabilities[1]; },
    (data) => { data.access.permission = 'DEVELOP'; },
  ]) {
    const invalid = closedHandshake();
    damage(invalid);
    await assert.rejects(loadBoundEnvironment(origin, undefined, setupFetch(undefined, invalid)));
  }
});

test('recheck to recovery allows only verified reads and preserves the same frozen command', async () => {
  const normal = await loadBoundEnvironment(origin, undefined, setupFetch());
  const held = await loadBoundEnvironment(origin, undefined, setupFetch(undefined, closedHandshake()));
  let observation = held;
  const connection = new EnvironmentConnection(normal, async () => observation);
  const sent = [];
  const transport = async (path, options) => {
    sent.push([path, options.method]);
    return response(success({ id: 1 }), { status: options.method === 'GET' ? 200 : 201 });
  };
  const api = new ApiClient(transport, () => requestId, normal, connection);
  const original = api.prepare('POST', '/api/v1/requirements', { title: 'existing' }, {
    idempotent: true, success_status: 201,
  });
  const frozen = api.exportPrepared(original);
  await connection.recheck();
  assert.equal(connection.getSnapshot().environment.recovery, held.recovery);
  await api.read('/api/v1/requirements/1/comment-index', (data) => data, [['document_id', '1']]);
  await assert.rejects(
    api.read('/api/v1/code-command-receipts', (data) => data),
    (error) => error instanceof ApiNotSent && error.code === 'RECOVERY_READ_ONLY',
  );
  await assert.rejects(api.commit(original, (data) => data), ApiNotSent);
  assert.deepEqual(sent, [['/api/v1/requirements/1/comment-index?document_id=1', 'GET']]);
  assert.deepEqual(api.exportPrepared(original), frozen);
  observation = normal;
  await connection.recheck();
  assert.equal(connection.getSnapshot().environment.recovery, undefined);
  assert.equal(sent.length, 1);
  await api.commit(original, (data) => data);
  assert.equal(sent.length, 2);
  connection.dispose();
});

test('bound client attaches four headers and refuses body from another environment', async () => {
  const bound = await loadBoundEnvironment(origin, undefined, setupFetch());
  const api = new ApiClient(async (_path, options) => {
    assert.equal(options.headers['X-WALL-E-Environment-ID'], environment);
    assert.equal(options.headers['X-WALL-E-Data-Generation'], generation);
    assert.equal(options.headers['X-WALL-E-Binding-Protocol'], '1');
    assert.equal(options.headers['X-WALL-E-Client'], 'web-v1');
    return response(success({ body: 'outside' }), { environmentId: other });
  }, undefined, bound);
  let decoded = false;
  await assert.rejects(
    api.read('/api/v1/requirements', () => {
      decoded = true;
    }),
    ApiUnknown,
  );
  assert.equal(decoded, false);
});

test('allow an exact wrong-scope rejection while preserving unknown mutations for other mismatched bodies', async () => {
  const bound = await loadBoundEnvironment(origin, undefined, setupFetch());
  const body = {
    success: false,
    data: null,
    error: { code: 'ENVIRONMENT_MISMATCH', message: '当前入口与请求所属环境不一致', details: null },
    meta: { request_id: requestId },
  };
  const api = new ApiClient(async () => response(body, { status: 409, environmentId: other }), undefined, bound);
  await assert.rejects(api.read('/api/v1/requirements', (value) => value), (error) => {
    assert(error instanceof ApiRejected);
    assert.equal(error.code, 'ENVIRONMENT_MISMATCH');
    return true;
  });
  body.error.message = 'unregistered message';
  const command = api.prepare('POST', '/api/v1/requirements', { title: 'existing key' }, {
    idempotent: true,
    success_status: 201,
  });
  await assert.rejects(api.commit(command, (value) => value), { code: 'RESULT_UNKNOWN', mutation: true });
});

test('keep scope on frozen actions and observe a new run without replacing the scope', async () => {
  const environmentEntry = await loadBoundEnvironment(origin, undefined, setupFetch());
  const seen = [];
  const bound = { ...environmentEntry, onRunChanged: (observed) => seen.push(observed) };
  const runs = [nextRun, run, nextRun];
  const api = new ApiClient(async () => response(success({ id: 1 }), { status: 201, runId: runs.shift() }), undefined, bound);
  const input = { title: 'existing' };
  const options = { idempotent: true, success_status: 201 };
  const frozen = api.exportPrepared(api.prepare('POST', '/api/v1/requirements', input, options));
  assert.deepEqual(frozen.binding_scope, bound.scope);
  const { binding_scope: _, ...legacy } = frozen;
  assert.throws(() => api.restorePrepared(legacy, options));
  assert.throws(() =>
    api.restorePrepared({ ...frozen, binding_scope: { ...bound.scope, data_generation: other } }, options),
  );
  for (let index = 0; index < 3; index += 1)
    await api.commit(api.restorePrepared(frozen, options), (value) => value);
  assert.deepEqual(seen, [nextRun]);
});

test('session records and history reject another generation and preserve a damaged record', async () => {
  const { scope } = await loadBoundEnvironment(origin, undefined, setupFetch());
  const data = new Map();
  const storage = {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: (key) => data.delete(key),
  };
  const current = new ScopedStoragePort(storage, scope);
  const laterScope = { ...scope, data_generation: other };
  const later = new ScopedStoragePort(storage, laterScope);
  current.setItem('entry', 'current data');
  assert.equal(later.getItem('entry'), null);
  later.setItem('entry', 'after restore');
  current.removeItem('entry');
  assert.equal(later.getItem('entry'), 'after restore');
  const existingKey = [...data.keys()][0];
  data.set(existingKey, '{"scope_version":1,"scope_version":1}');
  assert.throws(() => later.setItem('entry', 'overwrite'), EnvironmentStorageInvalid);
  assert.equal(data.get(existingKey), '{"scope_version":1,"scope_version":1}');
  assert.equal(readScopedHistory(laterScope, scopedHistoryState(scope, { url: '/requirements' })), null);
});

test('the plan editor can keep identical plan IDs and original commands in two data generations', async () => {
  const { scope } = await loadBoundEnvironment(origin, undefined, setupFetch());
  const later = { ...scope, data_generation: other };
  const values = new Map([['walle:v20:testing-plan-draft:3:new', 'preserve unscoped value']]);
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
  });
  try {
    const original = loadDraft(3, null, scope);
    const first = {
      ...original,
      change: 1,
      sent: { key: 'original-plan-command', change: 1 },
      draft: { ...original.draft, unresolved_questions: ['原代次草稿'] },
    };
    assert.equal(saveLocal(3, null, first, scope), true);
    assert.equal(loadDraft(3, null, later).sent, null);
    const second = {
      ...original,
      change: 2,
      draft: { ...original.draft, unresolved_questions: ['新代次草稿'] },
    };
    assert.equal(saveLocal(3, null, second, later), true);
    assert.equal(loadDraft(3, null, scope).sent.key, first.sent.key);
    assert.equal(saveLocal(3, null, null, scope), true);
    assert.deepEqual(loadDraft(3, null, later).draft.unresolved_questions, ['新代次草稿']);
    assert.equal(values.get('walle:v20:testing-plan-draft:3:new'), 'preserve unscoped value');
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'sessionStorage', descriptor);
    else delete globalThis.sessionStorage;
  }
});


test('connection recovery coalesces checks, blocks new work, and discards reads from before the check', async () => {
  const original = await loadBoundEnvironment(origin, undefined, setupFetch());
  let finishHandshake;
  const connection = new EnvironmentConnection(original, () => new Promise(resolve => { finishHandshake = resolve; }));
  let finishRead;
  const seen = [];
  const api = new ApiClient((url, options) => {
    seen.push([url, options.method, options.body, options.headers]);
    if (seen.length === 1) return new Promise(resolve => { finishRead = resolve; });
    return Promise.resolve(response(success({ id: 1 }), { status: 201, runId: nextRun }));
  }, () => requestId, original, connection);
  const frozen = api.prepare('POST', '/api/v1/requirements', { title: 'original' }, { idempotent: true, success_status: 201 });
  const lateRead = api.read('/api/v1/requirements', value => value);
  const recheck = connection.recheck();
  assert.equal(connection.recheck(), recheck);
  assert.equal(connection.getSnapshot().phase, 'CHECKING');
  await assert.rejects(api.commit(frozen, value => value), (error) =>
    error instanceof ApiNotSent && error.request_id === null && error.status === null);
  assert.equal(seen.length, 1);
  finishHandshake({ ...original, runId: nextRun });
  await recheck;
  assert.equal(connection.getSnapshot().phase, 'READY');
  finishRead(response(success({ id: 'stale' })));
  await assert.rejects(lateRead, ApiUnknown);
  assert.equal(connection.getSnapshot().phase, 'READY');
  assert.equal(seen.length, 1);
  await api.commit(frozen, value => value);
  assert.equal(seen[1][3]['Idempotency-Key'], requestId);
  assert.equal(seen[1][3]['X-WALL-E-Data-Generation'], generation);
  connection.dispose();
});

test('a verified new run triggers read-only recheck, and actual permission and generation govern subsequent requests', async () => {
  const original = await loadBoundEnvironment(origin, undefined, setupFetch());
  let checks = 0;
  const connection = new EnvironmentConnection(original, async () => {
    checks++;
    return checks === 1 ? { ...original, runId: nextRun, userPermission: 'READ_ONLY' }
      : { ...original, scope: { ...original.scope, data_generation: other }, runId: nextRun };
  });
  let sent = 0;
  const api = new ApiClient(async () => {
    sent++;
    return response(success({ id: 1 }), { runId: nextRun });
  }, () => requestId, original, connection);
  await api.read('/api/v1/requirements', value => value);
  await connection.recheck();
  assert.equal(checks, 1);
  assert.equal(connection.getSnapshot().environment.userPermission, 'READ_ONLY');
  const frozen = api.prepare('POST', '/api/v1/requirements', {}, { idempotent: true, success_status: 201 });
  await assert.rejects(api.commit(frozen, value => value), ApiNotSent);
  assert.equal(sent, 1);
  await connection.recheck();
  assert.equal(connection.getSnapshot().phase, 'SCOPE_CHANGED');
  assert.equal(connection.getSnapshot().environment.scope.data_generation, generation);
  await assert.rejects(api.read('/api/v1/requirements', value => value), ApiNotSent);
  await connection.recheck();
  assert.equal(checks, 2);
  assert.equal(sent, 1);
  connection.dispose();
});

test('a partial configuration switch keeps the mounted scope and permits a later read-only recheck', async () => {
  const original = await loadBoundEnvironment(origin, undefined, setupFetch());
  const target = { ...configuration, configuration_sha256: 'e'.repeat(64) };
  const seen = [];
  let targetReady = false;
  const connection = new EnvironmentConnection(original, (currentOrigin, signal) =>
    loadBoundEnvironment(currentOrigin, signal, async (path) => {
      seen.push(path);
      if (path.startsWith('/.well-known')) return response(target);
      if (!targetReady) return response(success(handshake));
      return response(
        success({ ...handshake, configuration_sha256: target.configuration_sha256, run_id: nextRun }),
        { runId: nextRun },
      );
    }),
  );
  let writes = 0;
  const api = new ApiClient(async () => {
    writes++;
    return response(success({ id: 1 }), { status: 201, runId: nextRun });
  }, () => requestId, original, connection);
  const prepared = api.prepare('POST', '/api/v1/requirements', { title: '原页面输入' }, {
    idempotent: true,
    success_status: 201,
  });

  await connection.recheck();
  assert.equal(connection.getSnapshot().phase, 'NOT_READY');
  assert.equal(connection.getSnapshot().environment, original);
  await assert.rejects(api.commit(prepared, (value) => value), ApiNotSent);
  assert.equal(writes, 0);

  targetReady = true;
  await connection.recheck();
  const recovered = connection.getSnapshot();
  assert.equal(recovered.phase, 'READY');
  assert.deepEqual(recovered.environment.scope, original.scope);
  assert.equal(recovered.environment.configurationSha256, target.configuration_sha256);
  assert.equal(recovered.environment.runId, nextRun);
  assert.equal(writes, 0);
  assert.deepEqual(seen, [
    '/.well-known/walle-environment.json',
    '/api/v1/environment',
    '/.well-known/walle-environment.json',
    '/api/v1/environment',
  ]);
  await api.commit(prepared, (value) => value);
  assert.equal(writes, 1);
  connection.dispose();
});

test('auth and network failures suspend the mounted scope; lost replies and terminal mismatch do not invent a receipt', async () => {
  const original = await loadBoundEnvironment(origin, undefined, setupFetch());
  let sends = 0;
  const connection = new EnvironmentConnection(original, async () => original);
  const api = new ApiClient(async () => {
    sends++;
    if (sends === 1) throw new TypeError('offline');
    if (sends === 2) return new Response('native authentication required', { status: 401 });
    const mismatch = response({ ...success(null), success: false, error: {
      code: 'DATA_GENERATION_MISMATCH', message: '数据已更换，请先核对原操作和草稿', details: null,
    }}, { status: 409 });
    mismatch.headers.set('X-WALL-E-Data-Generation', other);
    return mismatch;
  }, () => requestId, original, connection);
  const frozen = api.prepare('POST', '/api/v1/requirements', {}, { idempotent: true, success_status: 201 });
  await assert.rejects(api.commit(frozen, value => value), { code: 'RESULT_UNKNOWN', mutation: true });
  assert.equal(connection.getSnapshot().phase, 'UNREACHABLE');
  await connection.recheck();
  await assert.rejects(api.commit(frozen, value => value), ApiUnknown);
  assert.equal(connection.getSnapshot().phase, 'ACCESS');
  await connection.recheck();
  await assert.rejects(api.commit(frozen, value => value), ApiUnknown);
  assert.equal(connection.getSnapshot().phase, 'SCOPE_CHANGED');
  assert.equal(sends, 3);
  connection.dispose();
});
