import { test } from 'node:test';
import assert from 'node:assert/strict';
import { entityChange } from '../src/api/formation-history.ts';
import { historicalDescription } from '../src/formation/history-presentation.ts';
test('ORDER presentation retains original and resulting positions without a current ordering lookup', () => {
  const row = entityChange({
    ordinal: 1,
    entity_kind: 'ORDER',
    entity_ref: 's2',
    before: { step_ref: 's2', position: 20 },
    after: { step_ref: 's2', position: 1 },
    member_changes: { count: 0, digest: 'a'.repeat(64) },
  });
  assert.equal(historicalDescription(row, 'before'), 's2：第20步');
  assert.equal(historicalDescription(row, 'after'), 's2：第1步');
});
test('historical review describes the original replacement, triggering response and checked revision, independent of later current lineage', () => {
  const row = entityChange({
    ordinal: 1,
    entity_kind: 'ARTIFACT_REVIEW',
    entity_ref: 'a1',
    before: null,
    after: {
      reviewed_artifact_ref: 'a1',
      replacement_artifact_ref: 'a2',
      result: 'REASSOCIATED',
      checked_against_revision_id: 9,
      assistant_message_id: 7,
      source_refs: [],
    },
    member_changes: { count: 0, digest: 'b'.repeat(64) },
  });
  const original = structuredClone(row),
    laterCurrent = { artifact_ref: 'a3', checked_against_revision_id: 22 };
  assert.match(historicalDescription(row, 'after'), /a1 → a2/);
  assert.match(historicalDescription(row, 'after'), /版本#9/);
  assert.match(historicalDescription(row, 'after'), /回复#7/);
  assert(!historicalDescription(row, 'after').includes(laterCurrent.artifact_ref));
  assert.deepEqual(row, original);
});
