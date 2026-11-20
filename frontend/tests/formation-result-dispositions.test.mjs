import { test } from 'node:test';
import assert from 'node:assert/strict';
import { changeResult, resultProblem } from '../src/formation/result-state.ts';
import { nativeFormationCommand } from '../src/api/formation-commands.ts';

const content = { result_ref: 's1.o1', kind: 'CONTENT', description: '正式文档内容' };
const analysis = { result_ref: 's1.o2', kind: 'ANALYSIS', description: '范围结论' };
const definition = [content, analysis];
const command = (values) => ({
  type: 'FORMATION',
  action: 'COMPLETE_STEP',
  step_ref: 's1',
  expected_definition_version: 1,
  expected_goal_version: 1,
  expected_content_version: 1,
  result_dispositions: Object.values(values),
  issue_dispositions: [],
  branch_dispositions: [],
  next_step_ref: null,
});
test('ordinary ending needs no completed results; withdrawing an incomplete declaration restores the direct default', () => {
  assert.equal(resultProblem({}, definition), null);
  assert.deepEqual(nativeFormationCommand(command({})).result_dispositions, []);
  let values = changeResult({}, analysis, 'ANALYZED');
  assert.match(resultProblem(values, definition), /选择依据/);
  values = changeResult(values, analysis, 'OUTSTANDING');
  assert.equal(resultProblem(values, definition), null);
  assert.deepEqual(nativeFormationCommand(command(values)).result_dispositions, []);
});
test('CONTENT can request LANDED only with a real selected association; analysis sources cannot substitute for content', () => {
  let values = changeResult({}, content, 'LANDED');
  values = {
    ...values,
    's1.o1': { ...values['s1.o1'], source_refs: [{ kind: 'MESSAGE', message_id: 7 }] },
  };
  assert.match(resultProblem(values, definition), /实际关联/);
  values = { ...values, 's1.o1': { ...values['s1.o1'], artifact_refs: ['a1'] } };
  assert.equal(resultProblem(values, definition), null);
  assert.deepEqual(nativeFormationCommand(command(values)).result_dispositions[0].artifact_refs, [
    'a1',
  ]);
  assert.throws(() => changeResult({}, content, 'ANALYZED'));
  assert.throws(() => changeResult({}, analysis, 'LANDED'));
});
test('analysis uses real immutable source identities and remains bounded across multiple pages', () => {
  let values = changeResult({}, analysis, 'ANALYZED');
  const sources = Array.from({ length: 100 }, (_, i) => ({ kind: 'MESSAGE', message_id: i + 1 }));
  values = { ...values, 's1.o2': { ...values['s1.o2'], source_refs: sources } };
  assert.equal(resultProblem(values, definition), null);
  const frozen = nativeFormationCommand(command(values));
  assert.equal(frozen.result_dispositions[0].source_refs.length, 100);
  sources[0].message_id = 999;
  assert.equal(frozen.result_dispositions[0].source_refs[0].message_id, 1);
  values = {
    ...values,
    's1.o2': {
      ...values['s1.o2'],
      source_refs: [...sources, { kind: 'MESSAGE', message_id: 101 }],
    },
  };
  assert.match(resultProblem(values, definition), /100/);
  assert.throws(() => nativeFormationCommand(command(values)));
});
test('explicit results survive unrelated choices but reject deleted or changed definitions and duplicate evidence', () => {
  let values = changeResult({}, content, 'LANDED');
  values = { ...values, 's1.o1': { ...values['s1.o1'], artifact_refs: ['a1'] } };
  const original = structuredClone(values);
  const next = changeResult(values, analysis, 'ANALYZED');
  assert.deepEqual(values, original);
  assert.deepEqual(next['s1.o1'], values['s1.o1']);
  assert.match(resultProblem(values, [analysis]), /定义已变化/);
  assert.match(resultProblem(values, [{ ...content, kind: 'ANALYSIS' }]), /定义已变化/);
  assert.match(
    resultProblem({ 's1.o1': { ...values['s1.o1'], artifact_refs: ['a1', 'a1'] } }, definition),
    /重复/,
  );
  const repeated = {
    's1.o2': {
      result_ref: 's1.o2',
      status: 'ANALYZED',
      artifact_refs: [],
      source_refs: [
        { kind: 'REVISION', document_id: 3, revision_id: 8, block_ids: null },
        { block_ids: null, revision_id: 8, document_id: 3, kind: 'REVISION' },
      ],
    },
  };
  assert.match(resultProblem(repeated, definition), /重复/);
});
