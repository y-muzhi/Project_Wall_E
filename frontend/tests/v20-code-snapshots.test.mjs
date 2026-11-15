import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { codeBaselineFile, codeSnapshot } from '../src/api/code-snapshots.ts';
import { WalleApi } from '../src/api/walle.ts';

const ORIGIN = 'http://localhost:5173';
const TIME = '2026-11-08T01:00:00.000Z';
const REQUEST = '00000000-0000-4000-8000-00000000000b';
const snapshot = {
  id: 5,
  repository_id: 2,
  registration_operation_id: 3,
  content_profile_version_id: 4,
  commit_oid: 'a'.repeat(40),
  content_tree_oid: 'b'.repeat(40),
  content_policy_version: 'GIT20-BASELINE-1',
  registered_at: TIME,
  created_at: TIME,
  ready: true,
  reason_codes: [],
};
const entry = { path: 'src/main.py', mode: '100644', blob_oid: 'c'.repeat(40), byte_count: 0 };
const response = (data, pagination) =>
  new Response(
    JSON.stringify({
      success: true,
      data,
      error: null,
      meta: { request_id: REQUEST, ...(pagination === undefined ? {} : { pagination }) },
    }),
    { headers: { 'Content-Type': 'application/json' } },
  );
const api = (fetcher) => new WalleApi(new ApiClient(fetcher), {});

test('fixed snapshot detail requires matching identity and exposes only public readiness', async () => {
  const calls = [];
  const app = api(async (url, options) => {
    calls.push([new URL(url, ORIGIN).pathname, options.method]);
    return response(snapshot);
  });
  assert.deepEqual((await app.codeSnapshot(5)).data, snapshot);
  assert.deepEqual(calls, [['/api/v1/code-snapshots/5', 'GET']]);
  await assert.rejects(() => app.codeSnapshot(6), ApiUnknown);
  assert.equal(
    codeSnapshot({ ...snapshot, ready: false, reason_codes: ['CONTENT_NOT_READY'] }).ready,
    false,
  );
  assert.throws(() => codeSnapshot({ ...snapshot, retention_ref: 'refs/walle/baselines/5' }));
  assert.throws(() => codeSnapshot({ ...snapshot, ready: false }));
});

test('fixed file pages preserve actual totals and require UTF-8 ordering and safe paths', async () => {
  const actual = [
    { ...entry, path: '\uE000.py' },
    { ...entry, path: '\u{1F600}.py' },
  ];
  const calls = [];
  const app = api(async (url) => {
    const parsed = new URL(url, ORIGIN);
    calls.push(parsed.pathname + parsed.search);
    const page = Number(parsed.searchParams.get('page'));
    return response(
      { items: page === 1 ? actual : [] },
      { page, page_size: 20, total: 2, total_pages: 1 },
    );
  });
  assert.deepEqual((await app.codeBaselineFiles(5)).data.items, actual);
  const beyond = await app.codeBaselineFiles(5, 2);
  assert.deepEqual(beyond.data.items, []);
  assert.equal(beyond.meta.pagination.total, 2);
  assert.deepEqual(calls, [
    '/api/v1/code-snapshots/5/files?page=1',
    '/api/v1/code-snapshots/5/files?page=2',
  ]);
  const reversed = api(async () =>
    response(
      { items: [...actual].reverse() },
      { page: 1, page_size: 20, total: 2, total_pages: 1 },
    ),
  );
  await assert.rejects(() => reversed.codeBaselineFiles(5), ApiUnknown);
  assert.throws(() => codeBaselineFile({ ...entry, path: '../main.py' }));
  assert.throws(() => codeBaselineFile({ ...entry, sha256: 'private' }));
});
