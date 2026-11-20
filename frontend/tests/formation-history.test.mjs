import { entityChange, memberDelta } from '../src/api/formation-history.ts';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../src/api/client.ts';
import { WalleApi } from '../src/api/walle.ts';
const hash = 'a'.repeat(64);
const basis = {
  discussion_version: 1,
  formation_version: 1,
  goal_version: 1,
  document_revision_id: 3,
  content_version: 1,
};
const closure = {
  event_id: 9,
  step_ref: 's1',
  definition_version: 1,
  goal_version: 1,
  revision_id: 3,
  command_message_id: 2,
  next_step_ref: null,
  result_count: 1,
  issue_count: 0,
  branch_count: 0,
  items_digest: hash,
};
const event = () => ({
  event_id: 9,
  action: 'STEP_COMPLETED',
  actor: 'USER',
  reason: '结束步骤',
  created_at: '2026-11-16T07:00:00.000Z',
  schema: 'formation_event_v1',
  document_id: 7,
  batch_ref: 9,
  ordinal: 1,
  batch_size: 1,
  version_before: basis,
  version_after: { ...basis, discussion_version: 2, formation_version: 2 },
  change_count: 1,
  closure,
});
const eventPage = () => ({ document_id: 7, upper_event_id: 9, total: 1, items: [event()] });
const result = () => ({
  kind: 'RESULT',
  ordinal: 1,
  result_ref: 's1.o1',
  description: '成果',
  result_kind: 'CONTENT',
  status: 'LANDED',
  artifact_count: 1,
  range_count: 1,
  source_count: 0,
  evidence_count: 2,
  evidence_digest: hash,
});
const closurePage = () => ({
  document_id: 7,
  event_id: 9,
  closure,
  kind: 'RESULT',
  total: 1,
  items: [result()],
});
const evidence = () => ({
  document_id: 7,
  event_id: 9,
  owner_kind: 'RESULT',
  item_ref: 's1.o1',
  total: 1,
  digest: hash,
  items: [
    {
      kind: 'RANGE',
      ordinal: 1,
      artifact_ref: 'a1',
      role: 'ORIGIN',
      revision_id: 3,
      block_id: 4,
      block_digest: hash,
    },
  ],
});
function setup(value, pagination = { page_size: 20, next_cursor: null, has_more: false }) {
  const requests = [];
  const api = new WalleApi(
    new ApiClient(async (url, options) => {
      requests.push({ url, options });
      return new Response(
        JSON.stringify({
          success: true,
          data: value,
          error: null,
          meta: { request_id: '00000000-0000-4000-8000-000000000001', pagination },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }),
    {},
  );
  return { api, requests };
}
test('event history retains immutable versions, actual high water mark and no mutation key', async () => {
  const { api, requests } = setup(eventPage());
  const response = await api.getFormationEvents(1, 7);
  assert.equal(response.data.items[0].version_before.formation_version, 1);
  assert.equal(response.data.upper_event_id, 9);
  assert.equal(new Headers(requests[0].options.headers).has('Idempotency-Key'), false);
  assert.equal(requests[0].options.method, 'GET');
});
test('event history rejects private fields, wrong document, high water and batch metadata', async () => {
  for (const change of [
    (value) => {
      value.items[0].private_basis = {};
    },
    (value) => {
      value.items[0].document_id = 8;
    },
    (value) => {
      value.upper_event_id = 8;
    },
    (value) => {
      value.items[0].ordinal = 2;
    },
    (value) => {
      value.items[0].closure.event_id = 10;
    },
    (value) => {
      value.items[0].schema = 'other';
    },
  ]) {
    const value = structuredClone(eventPage());
    change(value);
    await assert.rejects(
      setup(value).api.getFormationEvents(1, 7),
      (error) => error instanceof ApiUnknown && !error.mutation,
    );
  }
});
test('history rejects current F, unsupported filters and coerced page limits before requesting', async () => {
  for (const query of [
    { known_f: 99 },
    { state: 'OPEN' },
    { limit: '20' },
    { limit: true },
    { step_ref: 'new_step_1' },
  ]) {
    const { api, requests } = setup(eventPage());
    await assert.rejects(async () => api.getFormationEvents(1, 7, query), TypeError);
    assert.equal(requests.length, 0);
  }
});
test('closure loads original result facts and verifies kind/head/count/owner', async () => {
  const { api } = setup(closurePage());
  assert.equal((await api.getFormationClosure(1, 7, 9, 'RESULT')).data.items[0].status, 'LANDED');
  for (const change of [
    (value) => {
      value.event_id = 10;
    },
    (value) => {
      value.closure.event_id = 10;
    },
    (value) => {
      value.total = 2;
    },
    (value) => {
      value.items[0].result_ref = 's2.o1';
    },
    (value) => {
      value.items[0].evidence_count = 1;
    },
    (value) => {
      value.kind = 'ISSUE';
    },
  ]) {
    const value = structuredClone(closurePage());
    change(value);
    await assert.rejects(setup(value).api.getFormationClosure(1, 7, 9, 'RESULT'), ApiUnknown);
  }
});
test('closure issue and branch pages decode only their own item union', async () => {
  for (const kind of ['ISSUE', 'BRANCH']) {
    const value = {
      document_id: 7,
      event_id: 9,
      closure: { ...closure, result_count: 0, [kind.toLowerCase() + '_count']: 1 },
      kind,
      total: 1,
      items: [
        {
          kind,
          ordinal: 1,
          ref: kind === 'ISSUE' ? 'i1' : 'b1',
          description: '遗留',
          state_at_close: 'OPEN',
          disposition: 'KEEP_OPEN',
          to_step_ref: null,
          reason: null,
          source_count: 0,
          evidence_count: 0,
          evidence_digest: hash,
        },
      ],
    };
    assert.equal(
      (await setup(value).api.getFormationClosure(1, 7, 9, kind)).data.items[0].disposition,
      'KEEP_OPEN',
    );
  }
});
test('evidence preserves original revision and rejects wrong owner, private fields and unregistered kind', async () => {
  assert.equal(
    (await setup(evidence()).api.getFormationClosureEvidence(1, 7, 9, 'RESULT', 's1.o1')).data
      .items[0].revision_id,
    3,
  );
  for (const change of [
    (value) => {
      value.item_ref = 's1.o2';
    },
    (value) => {
      value.event_id = 10;
    },
    (value) => {
      value.items[0].private_binding = {};
    },
    (value) => {
      value.items[0].kind = 'CURRENT';
    },
    (value) => {
      value.items[0].block_digest = 'invalid';
    },
  ]) {
    const value = structuredClone(evidence());
    change(value);
    await assert.rejects(
      setup(value).api.getFormationClosureEvidence(1, 7, 9, 'RESULT', 's1.o1'),
      ApiUnknown,
    );
  }
});
test('historical cursor bytes are forwarded unchanged and input owner types are checked before fetch', async () => {
  const { api, requests } = setup(eventPage());
  const cursor = 'opaque/+==';
  await api.getFormationEvents(1, 7, { cursor, step_ref: 's1' });
  assert.equal(new URL(requests[0].url, 'http://localhost').searchParams.get('cursor'), cursor);
  const bad = setup(evidence());
  await assert.rejects(
    async () => bad.api.getFormationClosureEvidence(1, 7, 9, 'ISSUE', 's1.o1'),
    TypeError,
  );
  assert.equal(bad.requests.length, 0);
});
test('historical page completeness and descending event identities are enforced', async () => {
  const value = eventPage();
  value.total = 2;
  await assert.rejects(setup(value).api.getFormationEvents(1, 7), ApiUnknown);
  const reversed = eventPage();
  reversed.items = [{ ...event(), event_id: 8, closure: null }, event()];
  reversed.total = 2;
  await assert.rejects(setup(reversed).api.getFormationEvents(1, 7), ApiUnknown);
});

test('all thirteen scalar change variants keep exact typed snapshots, including append-only proofs', () => {
  const proposal = { message_id: 2, card_key: 'write' };
  const snapshots = {
    STEP: {
      step_ref: 's1',
      definition_version: 1,
      title: '步骤',
      status: 'PLANNED',
      position: 1,
      next_result_no: 2,
      closure_event_ref: null,
    },
    GOAL: { version: 1, text: '目标' },
    RESULT: { result_ref: 's1.o1', description: '成果', kind: 'CONTENT' },
    ISSUE: {
      issue_ref: 'i1',
      step_ref: 's1',
      branch_ref: null,
      description: '问题',
      blocking: true,
      disposition: 'OPEN',
      disposition_reason: null,
      disposition_event_ref: null,
    },
    BRANCH: {
      branch_ref: 'b1',
      origin_step_ref: 's1',
      origin_event_ref: 2,
      return_step_ref: 's1',
      question: '问题',
      relevance: '相关',
      status: 'OPEN',
      state_event_ref: 2,
      result_summary: null,
      disposition_event_ref: null,
    },
    ARTIFACT: {
      artifact_ref: 'a1',
      step_ref: 's1',
      source_event_ref: 2,
      origin_revision_id: 3,
      origin_content_digest: hash,
      summary: '成果',
      checked_against_revision_id: 3,
      freshness: 'CURRENT',
      review_reason: null,
    },
    ORDER: { step_ref: 's1', position: 1 },
    RESULT_ROUTE: {
      from_result_ref: 's1.o1',
      disposition: 'REPLACED',
      target_result_refs: ['s2.o1'],
      reason: '承接',
    },
    ASSESSMENT: {
      verdict: 'UNCERTAIN',
      reason: '需核实',
      goal_version: 1,
      evaluated_step_version: 1,
      evaluated_revision_id: 3,
      coverage_block_ids: [],
      source_refs: [],
      assistant_message_id: 2,
    },
    RECOMMENDATION: {
      action: 'DISCUSS',
      step_ref: 's1',
      reason: '继续讨论',
      source_refs: [],
      assistant_message_id: 2,
      basis: {
        schema: 'formation_recommendation_basis_v21_1',
        goal_version: 1,
        owner_step_ref: 's1',
        owner_definition_version: 1,
        owner_status: 'PLANNED',
        evaluated_revision_id: 3,
        coverage: [],
        target_step: null,
        entity_basis: [],
        relation_sets: [],
        source_heads: [],
      },
    },
    PROPOSAL: { proposal, disposition: 'PENDING', needs_revision: false, binding_digest: hash },
    PROPOSAL_CHECK: {
      proposal,
      publication_binding_digest: hash,
      expected_semantic_digest: hash,
      observed_semantic_digest: hash,
      checked_versions: basis,
      check_kind: 'WITHDRAW_ADJUSTMENT',
      result: 'MATCHED',
      command_message_id: 2,
    },
    ARTIFACT_REVIEW: {
      reviewed_artifact_ref: 'a1',
      replacement_artifact_ref: null,
      result: 'MATCHED',
      checked_against_revision_id: 3,
      assistant_message_id: 2,
      source_refs: [],
    },
  };
  for (const [kind, value] of Object.entries(snapshots)) {
    const row = {
      ordinal: 1,
      entity_kind: kind,
      entity_ref: 'original-reference',
      before: null,
      after: value,
      member_changes: { count: 0, digest: hash },
    };
    assert.equal(entityChange(row).entity_kind, kind);
    assert.throws(
      () => entityChange({ ...row, after: { ...value, private_binding: {} } }),
      TypeError,
    );
    assert.throws(() => entityChange({ ...row, before: null, after: null }), TypeError);
    if (kind === 'PROPOSAL_CHECK' || kind === 'ARTIFACT_REVIEW')
      assert.throws(() => entityChange({ ...row, before: value }), TypeError);
  }
  assert.throws(() => entityChange({ entity_kind: 'UNKNOWN' }), TypeError);
});
test('all eleven member collections select exact source, range or identity values', () => {
  const collections = [
    'DEPENDENCY',
    'REPLACES',
    'TOPIC',
    'GOAL_SOURCE',
    'ISSUE_SOURCE',
    'ISSUE_RESOLUTION_SOURCE',
    'BRANCH_TOPIC',
    'BRANCH_RESULT_SOURCE',
    'ARTIFACT_RESULT',
    'ORIGIN_RANGE',
    'CURRENT_RANGE',
  ];
  for (const collection of collections) {
    const after = collection.endsWith('_SOURCE')
      ? { kind: 'SOURCE', source_ref: { kind: 'MESSAGE', message_id: 1 } }
      : collection.endsWith('_RANGE')
        ? { kind: 'RANGE', revision_id: 3, block_id: 4, block_digest: hash }
        : {
            kind: 'REF',
            ref:
              collection === 'ARTIFACT_RESULT'
                ? 's1.o1'
                : collection.includes('TOPIC')
                  ? 't1'
                  : 's1',
          };
    const row = { ordinal: 1, collection, member_key: 'original-key', before: null, after };
    assert.equal(memberDelta(row).collection, collection);
    assert.throws(() => memberDelta({ ...row, after: { ...after, extra: true } }), TypeError);
    assert.throws(() => memberDelta({ ...row, after: null }), TypeError);
  }
  assert.throws(() => memberDelta({ collection: 'OTHER' }), TypeError);
});
test('changes and members require actual original owner/event/ordinal and complete totals', async () => {
  const row = {
    ordinal: 1,
    entity_kind: 'ORDER',
    entity_ref: 's1',
    before: { step_ref: 's1', position: 2 },
    after: { step_ref: 's1', position: 1 },
    member_changes: { count: 0, digest: hash },
  };
  const changes = { document_id: 7, event_id: 9, total: 1, items: [row] };
  assert.equal(
    (await setup(changes).api.getFormationChanges(1, 7, 9)).data.items[0].before.position,
    2,
  );
  await assert.rejects(
    setup({ ...changes, event_id: 10 }).api.getFormationChanges(1, 7, 9),
    ApiUnknown,
  );
  const members = {
    document_id: 7,
    event_id: 9,
    change_ordinal: 1,
    total: 0,
    digest: hash,
    items: [],
  };
  assert.equal((await setup(members).api.getFormationMembers(1, 7, 9, 1)).data.total, 0);
  await assert.rejects(
    setup({ ...members, change_ordinal: 2 }).api.getFormationMembers(1, 7, 9, 1),
    ApiUnknown,
  );
  await assert.rejects(
    setup({ ...members, private_binding: {} }).api.getFormationMembers(1, 7, 9, 1),
    ApiUnknown,
  );
});
test('issue and branch closure evidence cannot borrow artifact ranges', async () => {
  const value = evidence();
  value.owner_kind = 'ISSUE';
  value.item_ref = 'i1';
  await assert.rejects(
    setup(value).api.getFormationClosureEvidence(1, 7, 9, 'ISSUE', 'i1'),
    ApiUnknown,
  );
});

test('detail read barrier preserves original historical filters and validates its original response limit', async () => {
  const value = eventPage(),
    requests = [];
  const api = new WalleApi(
    new ApiClient(async (url) => {
      requests.push(url);
      return new Response(
        JSON.stringify({
          success: true,
          data: value,
          error: null,
          meta: {
            request_id: '00000000-0000-4000-8000-000000000001',
            pagination: { page_size: 20, next_cursor: null, has_more: false },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }),
    {},
  ).forDetailReads();
  const query = { limit: 20, step_ref: 's1' };
  const pending = api.getFormationEvents(1, 7, query);
  query.limit = 100;
  query.step_ref = 's9';
  const response = await pending;
  assert.equal(response.data.total, 1);
  const sent = new URL(requests[0], 'http://localhost').searchParams;
  assert.equal(sent.get('limit'), '20');
  assert.equal(sent.get('step_ref'), 's1');
  api.disposeDetailReads();
});
