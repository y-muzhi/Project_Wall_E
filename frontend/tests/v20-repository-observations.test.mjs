import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
import { repositoryObservation } from '../src/api/code-repository-observations.ts';

const OID = 'a'.repeat(40),
  REQUEST = '00000000-0000-4000-8000-00000000000b';
function observation(extra = {}) {
  return {
    id: 2,
    repository_id: 1,
    operation_id: 3,
    head_commit: OID,
    local_branches: [{ full_ref: 'refs/heads/main', commit_oid: OID }],
    worktrees: [{ canonical_path: 'C:\\fixture', head_commit: OID, branch_ref: 'refs/heads/main' }],
    observed_at: '2026-11-06T00:00:00.000Z',
    status: 'READABLE',
    ...extra,
  };
}
function success(data, pagination) {
  return new Response(
    JSON.stringify({
      success: true,
      data,
      error: null,
      meta: { request_id: REQUEST, ...(pagination === undefined ? {} : { pagination }) },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}
test('preserves original observation, nullable failed state and immutable fields', () => {
  const value = observation(),
    row = repositoryObservation(value);
  value.local_branches[0].commit_oid = 'b'.repeat(40);
  assert.equal(row.local_branches[0].commit_oid, OID);
  assert.ok(Object.isFrozen(row.worktrees[0]));
  for (const status of ['UNKNOWN', 'UNAVAILABLE'])
    assert.equal(
      repositoryObservation(
        observation({ status, head_commit: null, local_branches: [], worktrees: [] }),
      ).status,
      status,
    );
  const long = 'b'.repeat(64);
  assert.equal(
    repositoryObservation(
      observation({
        head_commit: long,
        local_branches: [],
        worktrees: [{ canonical_path: 'C:\\detached', head_commit: long, branch_ref: null }],
      }),
    ).head_commit,
    long,
  );
});
test('malformed or combined observations are rejected without normalizing', () => {
  for (const extra of [
    { head_commit: 'HEAD' },
    { head_commit: '0'.repeat(40) },
    { id: true },
    { status: 'latest' },
    { observed_at: '2026-02-30T00:00:00.000Z' },
    { files: [] },
    { local_branches: [{ full_ref: 'main', commit_oid: OID }] },
    { local_branches: [{ full_ref: 'refs/heads/main', commit_oid: 'a'.repeat(64) }] },
    { local_branches: [] },
    {
      worktrees: [
        {
          canonical_path: 'C:\\fixture',
          head_commit: 'b'.repeat(40),
          branch_ref: 'refs/heads/main',
        },
      ],
    },
    { worktrees: [{ canonical_path: '\\\\server\\share', head_commit: OID, branch_ref: null }] },
    {
      worktrees: [{ canonical_path: 'C:\\fixture\\..\\other', head_commit: OID, branch_ref: null }],
    },
    { local_branches: [...observation().local_branches, ...observation().local_branches] },
    { worktrees: [...observation().worktrees, ...observation().worktrees] },
  ])
    assert.throws(() => repositoryObservation(observation(extra)));
});
test('WalleApi GET pins both original IDs, forwards abort and never sends body or command', async () => {
  const abort = new AbortController();
  const requests = [];
  const client = new ApiClient(async (url, options) => {
    requests.push({ url: String(url), options });
    return success(observation());
  });
  const result = await new WalleApi(client, {}).repositoryObservation(1, 2, abort.signal);
  assert.equal(result.data.operation_id, 3);
  assert.equal(requests.length, 1);
  assert.equal(
    new URL(requests[0].url, 'http://localhost').pathname,
    '/api/v1/code-repositories/1/observations/2',
  );
  assert.equal(requests[0].options.method, 'GET');
  assert.equal(requests[0].options.body, undefined);
});
test('wrong original IDs or pagination produce an unknown read, never fallback to latest', async () => {
  for (const [data, pagination] of [
    [observation({ repository_id: 9 }), undefined],
    [observation({ id: 9 }), undefined],
    [observation(), { page: 1, page_size: 20, total: 1, total_pages: 1 }],
  ]) {
    let count = 0;
    const client = new ApiClient(async () => {
      count++;
      return success(data, pagination);
    });
    await assert.rejects(new WalleApi(client, {}).repositoryObservation(1, 2), ApiUnknown);
    assert.equal(count, 1);
  }
});

test('canonical drive root is preserved and reserved path names are refused', () => {
  assert.equal(
    repositoryObservation(
      observation({
        head_commit: null,
        local_branches: [],
        worktrees: [{ canonical_path: 'C:\\', head_commit: null, branch_ref: null }],
      }),
    ).worktrees[0].canonical_path,
    'C:\\',
  );
  assert.throws(() =>
    repositoryObservation(
      observation({
        worktrees: [
          { canonical_path: 'C:\\NUL.txt', head_commit: OID, branch_ref: 'refs/heads/main' },
        ],
      }),
    ),
  );
});
