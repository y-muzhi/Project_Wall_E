import assert from 'node:assert/strict';
import { ApiClient, ApiUnknown } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
let raw = '';
for await (const chunk of process.stdin) raw += chunk;
const fixture = JSON.parse(raw);
let sends = 0;
const api = (body) =>
  new WalleApi(
    new ApiClient(
      async (path, init) => {
        sends++;
        assert.equal(path, '/api/v1/requirements/1/documents/1/formation/path-preview');
        assert.equal(new Headers(init.headers).get('Idempotency-Key'), null);
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      },
      () => assert.fail('Read preview minted key'),
    ),
    null,
  ).forDocumentAssistant(1);
const first = (await api(fixture.first).previewFormationPath(1, 1, fixture.input)).data;
assert.equal(first.affected_items.total, fixture.first.data.affected_items.total);
assert.ok(first.reference_map.every((row) => !Object.hasOwn(row, 'resolved_ref')));
const cursor = first.affected_items.next_cursor;
assert.ok(cursor);
const next = (
  await api(fixture.next).previewFormationPath(1, 1, fixture.input, {
    section: 'AFFECTED',
    cursor,
    limit: 20,
  })
).data;
assert.ok(next.affected_items.items[0].ordinal > first.affected_items.items.at(-1).ordinal);
for (const change of [
  (value) => {
    value.data.changes_digest = 'a'.repeat(64);
  },
  (value) => {
    value.data.reference_map[0].resolved_ref = 's123';
  },
  (value) => {
    value.data.affected_items.items[0].before = { kind: 'STEP', step_ref: 's999' };
  },
  (value) => {
    value.data.affected_items.total = 0;
  },
  (value) => {
    value.data.warnings.next_cursor = null;
  },
]) {
  const body = structuredClone(fixture.first);
  change(body);
  await assert.rejects(
    api(body).previewFormationPath(1, 1, fixture.input),
    (error) => error instanceof ApiUnknown && !error.mutation,
  );
}
process.stdout.write(JSON.stringify({ passed: true, sends, total: first.affected_items.total }));
