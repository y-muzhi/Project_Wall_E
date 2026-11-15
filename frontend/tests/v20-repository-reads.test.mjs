import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';

const at = '2026-11-07T00:00:00.000Z';
const path = '/api/v1/code-repositories';
const summary = {
  id: 3, name: '仓库', object_format: 'sha256', created_at: at, root_path: null,
  latest_observation: { id: 9, status: 'UNKNOWN', observed_at: at },
};
const pagination = (page, total) => ({ page, page_size: 20, total, total_pages: Math.ceil(total / 20) });
function success(data, paginationValue) {
  return new Response(JSON.stringify({
    success: true, data, error: null,
    meta: { request_id: '00000000-0000-4000-8000-00000000000a',
      ...(paginationValue ? { pagination: paginationValue } : {}) },
  }), { headers: { 'Content-Type': 'application/json' } });
}

test('saved repository list has exact pagination and no local paths', async () => {
  const api = new WalleApi(new ApiClient(async (url, options) => {
    assert.equal(options.method, 'GET');
    assert.equal(url, path + '?page=1');
    return success({ items: [summary, { ...summary, id: 2, latest_observation: null }] }, pagination(1, 2));
  }), {});
  const result = await api.codeRepositories();
  assert.deepEqual(result.data.items[0], summary);
  assert.equal(result.data.items[1].latest_observation, null);
  assert.ok(Object.isFrozen(result.data.items[0].latest_observation));
});

test('repository list rejects paths, loose summaries and incorrect ordering', async () => {
  for (const items of [
    [{ ...summary, root_path: 'C:\\outside' }],
    [{ ...summary, latest_observation: { ...summary.latest_observation, head_commit: 'extra' } }],
    [{ ...summary, id: 2 }, summary],
  ]) {
    const api = new WalleApi(new ApiClient(async () => success({ items }, pagination(1, items.length))), {});
    await assert.rejects(api.codeRepositories(), ApiUnknown);
  }
});

test('settings detail requires canonical local path and exact selected identity', async () => {
  const selected = { ...summary, root_path: 'C:\\work\\repository' };
  const api = new WalleApi(new ApiClient(async (url) => {
    assert.equal(url, path + '/3');
    return success(selected);
  }), {});
  assert.deepEqual((await api.codeRepository(3)).data, selected);
  for (const row of [
    { ...selected, id: 4 }, { ...selected, root_path: null },
    { ...selected, root_path: '\\\\server\\share' }, { ...selected, root_path: 'C:\\work\\..\\other' },
  ]) {
    const rejected = new WalleApi(new ApiClient(async () => success(row)), {});
    await assert.rejects(rejected.codeRepository(3), ApiUnknown);
  }
});
