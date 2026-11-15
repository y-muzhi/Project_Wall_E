import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';

const path = '/api/v1/documents/3/code-design-revisions';
const row = {
  revision_id: 7,
  requirement_id: 1,
  document_id: 3,
  version_no: 2,
  is_current: false,
  confirmation_event_id: 6,
  confirmed_at: '2026-11-08T01:00:00.000Z',
  eligible: true,
  reason_code: null,
};
const response = (items, page = 1) =>
  new Response(
    JSON.stringify({
      success: true,
      data: { items },
      error: null,
      meta: {
        request_id: '00000000-0000-4000-8000-00000000000b',
        pagination: { page, page_size: 20, total: 1, total_pages: 1 },
      },
    }),
    { headers: { 'Content-Type': 'application/json' } },
  );
const api = (fetcher) => new WalleApi(new ApiClient(fetcher), {});

test('fixed revision choices preserve historical eligibility and original document scope', async () => {
  const app = api(async (url, request) => {
    assert.equal(request.method, 'GET');
    assert.equal(url, path + '?usage=MATERIAL&page=1');
    return response([row]);
  });
  assert.deepEqual((await app.codeDesignRevisions(3, 'MATERIAL')).data.items, [row]);
  for (const value of [
    { ...row, document_id: 4 },
    { ...row, confirmation_event_id: null },
    { ...row, eligible: false },
  ]) {
    const invalid = api(async () => response([value]));
    await assert.rejects(() => invalid.codeDesignRevisions(3), ApiUnknown);
  }
  const beyond = api(async () => response([], 2));
  const result = await beyond.codeDesignRevisions(3, 'MAIN', 2);
  assert.equal(result.meta.pagination.total, 1);
  assert.deepEqual(result.data.items, []);
});
