import { test } from 'node:test';
import assert from 'node:assert/strict';
import { changeRemaining, remainingProblem } from '../src/formation/completion-state.ts';
import { nativeFormationCommand } from '../src/api/formation-commands.ts';
import { entityChange } from '../src/api/formation-history.ts';
import { historicalDescription } from '../src/formation/history-presentation.ts';
const complete = (issues) => ({
  type: 'FORMATION',
  action: 'COMPLETE_STEP',
  step_ref: 's1',
  expected_definition_version: 1,
  expected_goal_version: 1,
  expected_content_version: 1,
  result_dispositions: [],
  issue_dispositions: Object.values(issues),
  branch_dispositions: [],
  next_step_ref: null,
});
test('default completion keeps all unselected matters open; explicit choices survive other pages and have a bounded payload', () => {
  let values = {};
  assert.deepEqual(nativeFormationCommand(complete(values)).issue_dispositions, []);
  for (let n = 1; n <= 20; n++)
    values = {
      ...changeRemaining(values, 'i' + n, 'DEFERRED'),
      ['i' + n]: { ref: 'i' + n, disposition: 'DEFERRED', to_step_ref: null, reason: '明确暂缓' },
    };
  assert.equal(remainingProblem(values), null);
  assert.equal(nativeFormationCommand(complete(values)).issue_dispositions.length, 20);
  const over = changeRemaining(values, 'i21', 'DEFERRED');
  assert.notEqual(remainingProblem(over), null);
  values = changeRemaining(values, 'i1', 'KEEP_OPEN');
  assert.equal(values.i1, undefined);
  assert.equal(values.i20.reason, '明确暂缓');
  assert.equal(nativeFormationCommand(complete(values)).issue_dispositions.length, 19);
});
test('transfer requires a real target; changing disposition clears incompatible target/reason, Unicode reasons use codepoints', () => {
  let values = changeRemaining({}, 'i1', 'TRANSFER');
  assert.notEqual(remainingProblem(values), null);
  values = { ...values, i1: { ...values.i1, to_step_ref: 's2' } };
  assert.equal(remainingProblem(values), null);
  assert.deepEqual(nativeFormationCommand(complete(values)).issue_dispositions[0], values.i1);
  values = changeRemaining(values, 'i1', 'DEFERRED');
  assert.equal(values.i1.to_step_ref, null);
  assert.notEqual(remainingProblem(values), null);
  values = { ...values, i1: { ...values.i1, reason: '😀'.repeat(1000) } };
  assert.equal(remainingProblem(values), null);
  assert.doesNotThrow(() => nativeFormationCommand(complete(values)));
});
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
