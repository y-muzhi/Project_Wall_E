import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as models from '../src/api/models.ts';
import { validateDefinition } from '../src/api/resource-schema.ts';
import { snapshotObject } from '../src/api/client.ts';

const at = '2026-10-05T09:00:00.000Z';
const root = () => ({ id: 1, requirement_no: 'REQ000001', title: '需求😀', requirement_type: 'NEW', initialization_mode: 'IDEATION',
  template_key: 'new-requirement', template_version: 'v1', status: 'INITIALIZING', document_work_state: 'IDLE',
  active_operation_type: null, active_operation_id: null, created_at: at, updated_at: at, completed_at: null, state_started_at: null });
const run = () => ({ id: 2, requirement_id: 1, action_type: 'ASK', function_type: 'ANSWER_REQUIREMENT', source_type: 'USER_INSTRUCTION', source_id: null,
  scope: { scope_type: 'DOCUMENT', scope_ref: null }, status: 'RUNNING', current_step: 'PREPARING', final_result: null,
  suggestion_batch_id: null, latest_assistant_message_id: null, error_code: null, error_message: null, cancel_reason: null, retry_of_guide_run_id: null,
  created_at: at, started_at: at, waiting_user_at: null, ended_at: null, updated_at: at });
const option = (key) => ({ option_key: key, label: key, description: '', impact: '', risks: '' });
const cards = () => ({ schema_version: 1, intro: '请确认', cards: [{ card_key: 'confirm', card_type: 'CONFIRM', question: '完整候选', context: '', required: true,
  options: [option('yes'), option('later')], selection_rule: { min: 1, max: 1 }, custom_answer: { enabled: false, max_length: 0 },
  recommendation: null, related_spec_context: [{ block_id: 1, content_snapshot: '原文😀' }] }] });
const comment = () => ({ id: 4, requirement_id: 1, content: '评论', anchor_type: 'SELECTION', block_id: 3,
  anchor_ref: { selected_text: '甲😀', prefix_text: '', suffix_text: '' }, anchor_status: 'ATTACHED', status: 'OPEN',
  resolved_at: null, deleted_at: null, created_at: at, updated_at: at });
const location = () => ({ status: 'ATTACHED', block_id: 3, start_offset: 2, end_offset: 4 });

test('SHR-TEXT exactly accepts1000 revision codepoints and100 selection context, refusing1001/101 without truncation', () => {
  const revision = { id: 3, requirement_id: 1, version_no: 2, revision_type: 'MANUAL', description: '😀'.repeat(1000), source_content_version: 2, created_at: at };
  assert.equal(models.revisionSummary(revision).description, revision.description);
  assert.throws(() => models.revisionSummary({ ...revision, description: revision.description + 'x' }));
  const reference = { block_id: 3, selected_text: '选😀', prefix_text: '😀'.repeat(100), suffix_text: '后'.repeat(100) };
  const scoped = { scope_type: 'SELECTION', scope_ref: reference };
  assert.deepEqual(models.scope(scoped), scoped);
  for (const field of ['prefix_text','suffix_text']) {
    assert.throws(() => models.scope({ ...scoped, scope_ref: { ...reference, [field]: reference[field] + 'x' } }));
    const anchored = { ...comment(), anchor_ref: { selected_text: reference.selected_text, prefix_text: reference.prefix_text, suffix_text: reference.suffix_text } };
    assert.deepEqual(models.comment(anchored).anchor_ref, anchored.anchor_ref);
    assert.throws(() => models.comment({ ...anchored, anchor_ref: { ...anchored.anchor_ref, [field]: reference[field] + 'x' } }));
  }
});
const batch = () => ({ id: 8, requirement_id: 1, guide_run_id: 2, source_type: 'USER_INSTRUCTION', source_id: null, title: '修改', summary: '说明',
  status: 'PENDING', completion_result: null, error_message: null, base_content_version: 7, applied_content_version: null,
  created_at: at, completed_at: null, updated_at: at, counts: { total: 1, pending: 1, accepted: 0, rejected: 0, edited: 0 },
  suggestions: [{ id: 9, batch_id: 8, order_no: 1, title: '修改', explanation: '原因', impact: null, patch_operation: 'REPLACE_BLOCK',
    target_ref: { block_id: 3 }, selector: null, original_content: '原文', proposed_markdown: '新文', proposed_data: null, user_edited_content: null,
    status: 'PENDING', validation_status: 'VALID', validation_error: null, created_at: at, decided_at: null, updated_at: at }] });
function rejectsMutants(decode, make, mutators) {
  for (const mutate of mutators) { const value = make(); mutate(value); assert.throws(() => decode(value), TypeError); }
}

test('requirement occupancy/completion is exact and read never repairs malformed facts', () => {
  const input = root(), output = models.requirement(input); assert.deepEqual(output, input); assert(Object.isFrozen(output)); input.title = '外部改动'; assert.equal(output.title, '需求😀');
  rejectsMutants(models.requirement, root, [r => delete r.completed_at, r => r.secret = 'private', r => r.id = 0, r => r.id = 2 ** 53,
    r => r.requirement_no = '1', r => r.title = 'a\nb', r => r.updated_at = '2026-02-30T00:00:00.000Z',
    r => r.document_work_state = 'GUIDE_ACTIVE', r => r.active_operation_id = 2, r => r.completed_at = at, r => r.status = 'COMPLETED']);
});
test('guide functions, safe errors, independent final-result version and exact history are validated', () => {
  assert.deepEqual(models.guideRun(run()), run());
  const completed = run(); Object.assign(completed, { status: 'COMPLETED', current_step: 'FINISHED', ended_at: at,
    final_result: { summary: '完成', assistant_message_id: 10, current_document_version: 7, suggestion_batch_id: null } });
  assert.equal(models.guideRun(completed).final_result.current_document_version, 7);
  const history = run(); delete history.final_result; assert.deepEqual(models.guideSummary(history), history);
  rejectsMutants(models.guideRun, run, [r => r.source_id = 2, r => r.function_type = 'MODIFY_FROM_COMMENT', r => r.scope.scope_ref = {},
    r => r.status = 'FAILED', r => r.ended_at = at, r => r.error_code = 'PRIVATE_STACK', r => r.retry_of_guide_run_id = r.id,
    r => r.final_result = completed.final_result, r => r.started_at = '2026-10-04T09:00:00.000Z']);
  const failed = run(); Object.assign(failed, { status: 'FAILED', current_step: 'FINISHED', ended_at: at, error_code: 'CONTEXT_LIMIT_EXCEEDED', error_message: '真实拒绝' });
  assert.equal(models.guideRun(failed).error_code, 'CONTEXT_LIMIT_EXCEEDED'); failed.error_code = 'unregistered'; assert.throws(() => models.guideRun(failed));
});
test('frozen card schema preserves complete text, rejects semantic and conditional-field violations', () => {
  const original = cards(), value = models.cards(original); assert.deepEqual(value, original); assert(Object.isFrozen(value.cards[0].options));
  original.cards[0].options[0].label = 'changed'; assert.equal(value.cards[0].options[0].label, 'yes');
  rejectsMutants(models.cards, cards, [r => r.cards[0].options[1].option_key = 'yes', r => r.cards.push(structuredClone(r.cards[0])),
    r => r.cards[0].selection_rule.max = 2, r => r.cards[0].custom_answer = { enabled: true, max_length: 1 },
    r => r.cards[0].recommendation = { option_keys: ['absent'], reason: '' }, r => r.cards[0].related_spec_context[0].content_snapshot = null,
    r => r.cards[0].options[0].label = 'a'.repeat(1001), r => r.cards[0].context = '\ud800', r => r.cards[0].private = 'x']);
  const input = cards(); input.cards[0].options[0].label = '😀'.repeat(1000); assert.equal(models.cards(input).cards[0].options[0].label, input.cards[0].options[0].label);
});
test('formal responses retain explicit skip/custom null and reject duplicate keys/partial schemas', () => {
  const make = () => ({ schema_version: 1, responses: [{ card_key: 'c', selected_option_keys: [], custom_answer: null, skipped: true }] });
  assert.deepEqual(models.responses(make()), make());
  rejectsMutants(models.responses, make, [r => delete r.responses[0].custom_answer, r => r.responses[0].selected_option_keys = ['x'],
    r => r.responses.push(structuredClone(r.responses[0])), r => r.responses[0].custom_answer = '', r => r.schema_version = 2]);
});
test('messages keep damaged structured-content fallback and server card-state; text cannot carry formal answers', () => {
  const message = { id: 1, requirement_id: 1, guide_run_id: 2, sequence_no: 5, role: 'ASSISTANT', content: '回退正文', message_type: 'INTERACTION_CARDS',
    structured_content: null, reply_to_message_id: null, created_at: at, card_state: null };
  assert.deepEqual(models.message(message), message);
  assert.equal(models.message({ ...message, structured_content: cards(), card_state: 'EXPIRED' }).card_state, 'EXPIRED');
  for (const bad of [{ ...message, card_state: 'AVAILABLE' }, { ...message, role: 'USER' }, { ...message, message_type: 'TEXT', structured_content: cards() },
    { ...message, message_type: 'CARD_RESPONSE', role: 'USER' }]) assert.throws(() => models.message(bad), TypeError);
});
test('comment original anchor and current location remain separate and offsets count Unicode code points', () => {
  const make = () => ({ ...comment(), location: location() }); assert.deepEqual(models.commentItem(make()), make());
  rejectsMutants(models.commentItem, make, [r => r.location.end_offset = 5, r => r.location.block_id = 9, r => r.deleted_at = at,
    r => r.location.end_offset = null, r => r.anchor_ref.range = [2, 4], r => r.status = 'RESOLVED']);
  const orphan = make(); orphan.anchor_status = 'ORPHANED'; orphan.location = { status: 'ORPHANED', block_id: null, start_offset: null, end_offset: null };
  assert.equal(models.commentItem(orphan).block_id, 3);
});
test('complete comment index derives markers from all live comments and refuses contradictory counts', () => {
  const make = () => ({ requirement_id: 1, document_id: 2, content_version: 7, total_count: 2, open_count: 1,
    blocks: [{ block_id: 3, open_count: 1, comment_ids: [4] }], comments: [{ id: 4, status: 'OPEN', anchor_status: 'ATTACHED', location: location() },
      { id: 5, status: 'RESOLVED', anchor_status: 'ATTACHED', location: location() }] });
  assert.deepEqual(models.commentIndex(make()), make());
  rejectsMutants(models.commentIndex, make, [r => r.open_count = 2, r => r.blocks[0].comment_ids = [5], r => r.blocks.push(structuredClone(r.blocks[0])),
    r => r.comments[1].id = 4, r => r.total_count = 1]);
});
test('suggestion batch includes all five actual patch shapes and complete same-snapshot counts', () => {
  assert.deepEqual(models.batch(batch()), batch());
  for (const operation of ['REPLACE_BLOCK', 'INSERT_BEFORE', 'INSERT_AFTER', 'DELETE_BLOCK', 'REPLACE_TABLE_ROW']) {
    const row = batch().suggestions[0]; row.patch_operation = operation;
    if (operation === 'DELETE_BLOCK' || operation === 'REPLACE_TABLE_ROW') row.proposed_markdown = null;
    if (operation === 'REPLACE_TABLE_ROW') { row.selector = { key_column_index: 0, key_value: '一' }; row.proposed_data = { cells: ['一', '二'] }; }
    assert.equal(models.suggestion(row).patch_operation, operation);
  }
  rejectsMutants(models.batch, batch, [r => r.counts.total = 2, r => r.counts.pending = 0, r => r.suggestions[0].batch_id = 99,
    r => r.suggestions[0].selector = { key_column_index: 0, key_value: 'x' }, r => r.suggestions[0].validation_status = 'INVALID',
    r => r.suggestions[0].status = 'EDITED', r => r.suggestions.push(structuredClone(r.suggestions[0])), r => r.applied_content_version = 8]);
});
test('batch completion changes CURRENT once; no-change and discard have no adopted version', () => {
  const make = () => { const result = batch(); delete result.counts; delete result.suggestions; return result; };
  for (const completion of ['CHANGES_APPLIED', 'NO_CHANGE']) {
    const row = make(); Object.assign(row, { status: 'COMPLETED', completed_at: at, completion_result: completion, applied_content_version: completion === 'CHANGES_APPLIED' ? 8 : null });
    assert.equal(models.batchMetadata(row).completion_result, completion);
    row.applied_content_version = 9; assert.throws(() => models.batchMetadata(row));
  }
  const discarded = make(); Object.assign(discarded, { status: 'DISCARDED', completed_at: at }); assert.equal(models.batchMetadata(discarded).applied_content_version, null);
});
test('revision summaries keep historical source version and fixed BASELINE/manual numbering', () => {
  const make = () => ({ id: 1, requirement_id: 1, version_no: 1, revision_type: 'BASELINE', description: null, source_content_version: 7, created_at: at });
  assert.equal(models.revisionSummary(make()).source_content_version, 7);
  rejectsMutants(models.revisionSummary, make, [r => r.version_no = 2, r => r.revision_type = 'MANUAL', r => r.description = '', r => r.markdown_content = 'extra']);
});
test('frozen definition names are explicit and business captures getters once with immutable nested data', () => {
  assert.throws(() => validateDefinition('invented', {}));
  let reads = 0; const values = ['original']; const copied = snapshotObject({ get title() { reads++; return 'same'; }, nested: { values } });
  values.push('later'); assert.equal(reads, 1); assert.deepEqual(copied.nested.values, ['original']); assert(Object.isFrozen(copied.nested.values));
  assert.throws(() => snapshotObject({ value: undefined }));
});
