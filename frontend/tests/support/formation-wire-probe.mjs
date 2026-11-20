/** Offline contract probe: consume real isolated ASGI envelopes over stdin, never persist them. */
import assert from 'node:assert/strict';
import { ApiClient, ApiRejected } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
import { FormationReadOwner } from '../../src/formation/read-owner.ts';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const fixture = JSON.parse(input);
const normalize = (value) => {
  const url = new URL(value, 'http://localhost');
  url.searchParams.sort();
  return url.pathname + url.search;
};
const responses = new Map(fixture.responses.map((row) => [normalize(row.url), row]));
const used = new Set();
const api = new WalleApi(
  new ApiClient(async (url, options) => {
    assert.ok(options.method === undefined || options.method === 'GET');
    assert.equal(new Headers(options.headers).has('Idempotency-Key'), false);
    const key = normalize(url);
    const response = responses.get(key);
    assert.ok(response, 'Unexpected contract request: ' + key);
    used.add(key);
    return new Response(JSON.stringify(response.body), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }),
  {},
);
const doc = fixture.document_id;
const summary = await api.getFormationSummary(1, doc);
assert.equal(summary.data.exists, fixture.exists);
if (!fixture.exists) {
  await assert.rejects(
    api.getFormationSteps(1, doc),
    (error) =>
      error instanceof ApiRejected && error.details?.reason === 'FORMATION_NOT_INITIALIZED',
  );
} else {
  const steps = await api.getFormationSteps(1, doc);
  assert.equal(steps.data.total, 1);
  const step = await api.getFormationStep(1, doc, 's1');
  assert.equal(step.data.step_ref, 's1');
  for (const method of ['getFormationBranches', 'getFormationIssues']) {
    const response = await api[method](1, doc);
    assert.equal(response.data.total, 0);
  }
  const artifacts = await api.getFormationArtifacts(1, doc);
  assert.equal(artifacts.data.total, 1);
  const artifact = await api.getFormationArtifact(1, doc, 'a1');
  assert.equal(artifact.data.freshness, fixture.freshness);
  for (const kind of ['DEPENDENCY', 'REPLACES', 'TOPIC', 'ISSUE', 'BRANCH', 'ARTIFACT']) {
    const relation = await api.getFormationRelations(1, doc, 's1', { relation_kind: kind });
    assert.equal(relation.data.total, kind === 'ARTIFACT' ? 1 : 0);
  }
  for (const role of ['ORIGIN', 'CURRENT']) {
    const first = await api.getFormationRanges(1, doc, 'a1', role, { limit: 1 });
    assert.equal(first.data.total, 2);
    assert.equal(first.meta.pagination.has_more, true);
    const second = await api.getFormationRanges(1, doc, 'a1', role, {
      limit: 1,
      cursor: first.meta.pagination.next_cursor,
    });
    assert.equal(second.data.total, 2);
    assert.equal(second.data.items[0].ordinal, 2);
    assert.equal(second.meta.pagination.has_more, false);
  }
  const events = await api.getFormationEvents(1, doc);
  assert.ok(events.data.total > 0);
  for (const event of events.data.items) {
    const changes = await api.getFormationChanges(1, doc, event.event_id);
    assert.equal(changes.data.total, event.change_count);
    for (const change of changes.data.items) {
      const members = await api.getFormationMembers(1, doc, event.event_id, change.ordinal);
      assert.equal(members.data.total, change.member_changes.count);
      assert.equal(members.data.digest, change.member_changes.digest);
    }
  }
  if (fixture.closure_event_id !== null) {
    const eventId = fixture.closure_event_id;
    for (const kind of ['RESULT', 'ISSUE', 'BRANCH']) {
      const closed = await api.getFormationClosure(1, doc, eventId, kind);
      assert.equal(closed.data.total, kind === 'RESULT' ? 1 : 0);
    }
    const evidence = await api.getFormationClosureEvidence(1, doc, eventId, 'RESULT', 's1.o1');
    assert.ok(evidence.data.items.some((row) => row.kind === 'RANGE'));
    const original = evidence.data.items.find((row) => row.kind === 'ARTIFACT');
    assert.equal(original.freshness, 'CURRENT');
  }
  const lineage = await api.getFormationLineage(1, doc, 'a1');
  assert.equal(lineage.data.total, 1);
  assert.equal(lineage.data.items[0].freshness, fixture.freshness);
}
// The actual read owner must consume these same envelopes without a second mutation path.
const owner = new FormationReadOwner(1, doc, api);
assert.equal(await owner.refresh(), true);
if (fixture.exists) {
  assert.equal(await owner.selectStep('s1'), true);
  assert.equal(owner.getSnapshot().detail.data.step_ref, 's1');
}
owner.dispose();
assert.equal(used.size, responses.size);
console.log(
  'ASGI -> ApiClient -> WalleApi -> FormationReadOwner contract passed: ' + fixture.stage,
);
