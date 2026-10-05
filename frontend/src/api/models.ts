/** Public read models only. Private prompts/audit/business source proof stay in
 * the backend. Documents/revisions use the actual registered Markdown parser.
 */
import type { Ctx } from '@milkdown/kit/ctx';
import { validateBlockState, validateDocumentReadModel } from '../documents/contracts.ts';
import { exact } from './client.ts';
import { id, count, bool, text, nonempty, time, nullable, choices, array, shape, checked, require, interval, distinct } from './decoding.ts';
import type { Model } from './decoding.ts';
import { validateDefinition } from './resource-schema.ts';

export const requirementStatuses = ['INITIALIZING', 'ACTIVE', 'COMPLETED'] as const;
export const requirementTypes = ['NEW', 'CHANGE'] as const;
export const runStatuses = ['RUNNING', 'WAITING_USER', 'COMPLETED', 'FAILED', 'CANCELLED'] as const;
export const runActions = ['INITIALIZE', 'ASK', 'REVIEW', 'MODIFY'] as const;
export const runSteps = ['PREPARING', 'CALLING_MODEL', 'VALIDATING', 'PERSISTING', 'WAITING_USER', 'FINISHED'] as const;
const taskErrors = ['INVALID_INPUT', 'NOT_FOUND', 'MANUAL_DRAFT_NOT_FOUND', 'STATE_CONFLICT', 'WORK_STATE_CONFLICT',
  'WORK_STATE_INCONSISTENT', 'CONTENT_VERSION_CONFLICT', 'TEMPLATE_INVALID', 'DOCUMENT_INVALID', 'ANCHOR_INVALID', 'SCOPE_INVALID',
  'SOURCE_INVALID', 'PATCH_INVALID', 'TARGET_STALE', 'BATCH_PENDING', 'COMMENT_ORPHANED', 'CARD_ALREADY_ANSWERED', 'CARD_EXPIRED',
  'CONFIG_INVALID', 'STORAGE_UNAVAILABLE', 'CAPACITY_EXHAUSTED', 'IDEMPOTENCY_CONFLICT', 'REQUEST_IN_PROGRESS', 'INTERNAL_ERROR',
  'MODEL_ERROR', 'OUTPUT_INVALID', 'CONTEXT_LIMIT_EXCEEDED', 'INTERRUPTED', 'EXECUTION_TIMEOUT'] as const;
const title = checked(nonempty, value => require([...value].length <= 20 && !/[\r\n]/.test(value)));
const number = checked(text, value => require(/^REQ[0-9]{6}$/.test(value)));
export const requirementSummary = shape({ id, requirement_no: number, title, requirement_type: choices(requirementTypes),
  status: choices(requirementStatuses), updated_at: time });
export const requirement = checked(shape({ id, requirement_no: number, title, requirement_type: choices(requirementTypes),
  initialization_mode: choices(['IDEATION', 'DESIGN']), template_key: nonempty, template_version: nonempty,
  status: choices(requirementStatuses), document_work_state: choices(['IDLE', 'MANUAL_EDITING', 'GUIDE_ACTIVE', 'SUGGESTION_REVIEWING']),
  active_operation_type: nullable(choices(['MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'])), active_operation_id: nullable(id),
  created_at: time, updated_at: time, completed_at: nullable(time), state_started_at: nullable(time) }), row => {
  require((row.status === 'COMPLETED') === (row.completed_at !== null));
  const owner = { IDLE: null, MANUAL_EDITING: 'MANUAL_DRAFT', GUIDE_ACTIVE: 'GUIDE_RUN', SUGGESTION_REVIEWING: 'SUGGESTION_BATCH' };
  require(owner[row.document_work_state] === row.active_operation_type);
  require((row.document_work_state === 'IDLE') === (row.active_operation_id === null));
  require((row.document_work_state === 'IDLE') === (row.state_started_at === null));
});
export type Requirement = Model<typeof requirement>;
export type RequirementSummary = Model<typeof requirementSummary>;

export const revisionSummaryFields = { id, requirement_id: id, version_no: id, revision_type: choices(['BASELINE', 'MANUAL']),
  description: nullable(checked(nonempty, value => require([...value].length <= 1000))), source_content_version: id, created_at: time };
export const revisionSummary = checked(shape(revisionSummaryFields), row => require(row.revision_type === 'BASELINE' ? row.version_no === 1 : row.version_no > 1));
export type RevisionSummary = Model<typeof revisionSummary>;
export function documentDecoder(ctx: Ctx, kind: 'CURRENT' | 'MANUAL_DRAFT') {
  return (value: unknown) => { const { document } = validateDocumentReadModel(ctx, value); require(document.document_type === kind); return document; };
}
export function revisionDecoder(ctx: Ctx) {
  return (value: unknown) => {
    const row = exact(value, [...Object.keys(revisionSummaryFields), 'markdown_content', 'block_state_json']);
    const summary = revisionSummary(Object.fromEntries(Object.keys(revisionSummaryFields).map(key => [key, row[key]])));
    const pair = validateBlockState(ctx, row.markdown_content, row.block_state_json);
    return Object.freeze({ ...summary, markdown_content: pair.source.markdown, block_state_json: pair.state });
  };
}

const selection = shape({ selected_text: checked(nonempty, value => require([...value].length <= 2000)),
  prefix_text: checked(text, value => require([...value].length <= 100)), suffix_text: checked(text, value => require([...value].length <= 100)) });
export const scope = (value: unknown) => {
  const row = exact(value, ['scope_type', 'scope_ref']);
  const kind = choices(['DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION'])(row.scope_type);
  if (kind === 'DOCUMENT') { require(row.scope_ref === null); return Object.freeze({ scope_type: kind, scope_ref: null }); }
  if (kind === 'SELECTION') return Object.freeze({ scope_type: kind, scope_ref: shape({ block_id: id,
    selected_text: selectionText('selected_text'), prefix_text: selectionText('prefix_text'), suffix_text: selectionText('suffix_text') })(row.scope_ref) });
  return Object.freeze({ scope_type: kind, scope_ref: shape({ block_id: id })(row.scope_ref) });
};
function selectionText(key: 'selected_text' | 'prefix_text' | 'suffix_text') {
  return (value: unknown) => { const result = text(value), size = [...result].length; require(size <= (key === 'selected_text' ? 2000 : 100) && (key !== 'selected_text' || size > 0)); return result; };
}
const runFields = { id, requirement_id: id, action_type: choices(runActions),
  function_type: choices(['INITIALIZE_REQUIREMENT', 'ANSWER_REQUIREMENT', 'REVIEW_REQUIREMENT', 'MODIFY_REQUIREMENT', 'MODIFY_FROM_REVIEW', 'MODIFY_FROM_COMMENT']),
  source_type: choices(['USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT']), source_id: nullable(id), scope,
  status: choices(runStatuses), current_step: choices(runSteps), suggestion_batch_id: nullable(id), latest_assistant_message_id: nullable(id),
  error_code: nullable(choices(taskErrors)), error_message: nullable(nonempty), cancel_reason: nullable(nonempty), retry_of_guide_run_id: nullable(id),
  created_at: time, started_at: nullable(time), waiting_user_at: nullable(time), ended_at: nullable(time), updated_at: time };
function checkRun(row: Model<ReturnType<typeof shape<typeof runFields>>>) {
  const functions = { INITIALIZE: 'INITIALIZE_REQUIREMENT', ASK: 'ANSWER_REQUIREMENT', REVIEW: 'REVIEW_REQUIREMENT', MODIFY: 'MODIFY_REQUIREMENT' };
  require(row.function_type === (row.source_type === 'USER_INSTRUCTION' ? functions[row.action_type] : row.source_type === 'COMMENT' ? 'MODIFY_FROM_COMMENT' : 'MODIFY_FROM_REVIEW'));
  require(row.source_type === 'USER_INSTRUCTION' || row.action_type === 'MODIFY');
  require((row.source_type === 'USER_INSTRUCTION') === (row.source_id === null));
  require(['COMPLETED', 'FAILED', 'CANCELLED'].includes(row.status) === (row.ended_at !== null));
  require((row.status === 'FAILED') === (row.error_code !== null) && (row.status === 'FAILED') === (row.error_message !== null));
  require((row.status === 'CANCELLED') === (row.cancel_reason !== null));
  require(row.retry_of_guide_run_id !== row.id); interval(row, [row.started_at, row.waiting_user_at, row.ended_at]);
}
export const guideSummary = checked(shape(runFields), checkRun);
const finalResult = shape({ summary: nonempty, assistant_message_id: nullable(id), current_document_version: nullable(id), suggestion_batch_id: nullable(id) });
export const guideRun = checked(shape({ ...runFields, final_result: nullable(finalResult) }), row => {
  checkRun(row); require((row.status === 'COMPLETED') === (row.final_result !== null));
  if (row.final_result !== null) require(row.final_result.suggestion_batch_id === row.suggestion_batch_id);
});
export const guideAccepted = shape({ id, requirement_id: id, status: choices(runStatuses), current_step: choices(runSteps) });
export type GuideRun = Model<typeof guideRun>;
export type GuideSummary = Model<typeof guideSummary>;

const option = shape({ option_key: nonempty, label: nonempty, description: text, impact: text, risks: text });
const card = shape({ card_key: nonempty, card_type: choices(['SINGLE_SELECT', 'MULTI_SELECT', 'CONFIRM']), question: nonempty, context: text,
  required: bool, options: array(option, 8, 2), selection_rule: shape({ min: count, max: count }),
  custom_answer: shape({ enabled: bool, max_length: count }), recommendation: nullable(shape({ option_keys: array(nonempty, 8), reason: text })),
  related_spec_context: array(shape({ block_id: id, content_snapshot: text }), 20) });
export const cards = checked(shape({ schema_version: choices([1]), intro: text, cards: array(card, 5, 1) }), row => {
  validateDefinition('cards', row); distinct(row.cards.map(item => item.card_key));
  for (const item of row.cards) {
    const keys = item.options.map(entry => entry.option_key); distinct(keys);
    require(item.selection_rule.min <= item.selection_rule.max && item.selection_rule.max <= keys.length + Number(item.custom_answer.enabled));
    if (item.recommendation !== null) require(item.recommendation.option_keys.every(key => keys.includes(key)));
  }
});
export const responses = checked(shape({ schema_version: choices([1]), responses: array(shape({ card_key: nonempty,
  selected_option_keys: array(nonempty, 8), custom_answer: nullable(nonempty), skipped: bool }), 5, 1) }), row => {
  validateDefinition('responses', row); distinct(row.responses.map(item => item.card_key));
  for (const answer of row.responses) { distinct(answer.selected_option_keys); if (answer.skipped) require(answer.selected_option_keys.length === 0 && answer.custom_answer === null); }
});
export type Cards = Model<typeof cards>;
export type Responses = Model<typeof responses>;
export const message = (value: unknown) => {
  const row = exact(value, ['id', 'requirement_id', 'guide_run_id', 'sequence_no', 'role', 'content', 'message_type', 'structured_content', 'reply_to_message_id', 'created_at', 'card_state']);
  const base = shape({ id, requirement_id: id, guide_run_id: nullable(id), sequence_no: id, role: choices(['USER', 'ASSISTANT']),
    content: text, message_type: choices(['TEXT', 'INTERACTION_CARDS', 'CARD_RESPONSE']), reply_to_message_id: nullable(id), created_at: time,
    card_state: nullable(choices(['AVAILABLE', 'ANSWERED', 'EXPIRED'])) })(Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'structured_content')));
  const structured = row.structured_content === null ? null : base.message_type === 'INTERACTION_CARDS' ? cards(row.structured_content) : responses(row.structured_content);
  if (base.message_type === 'TEXT') require(structured === null && base.reply_to_message_id === null && base.card_state === null);
  if (base.message_type === 'INTERACTION_CARDS') require(base.role === 'ASSISTANT' && base.reply_to_message_id === null && (structured !== null) === (base.card_state !== null));
  if (base.message_type === 'CARD_RESPONSE') require(base.role === 'USER' && base.reply_to_message_id !== null && base.card_state === null);
  return Object.freeze({ ...base, structured_content: structured });
};
export type Message = Model<typeof message>;

export const location = checked(shape({ status: choices(['ATTACHED', 'ORPHANED']), block_id: nullable(id), start_offset: nullable(count), end_offset: nullable(count) }), row => {
  if (row.status === 'ORPHANED') require(row.block_id === null && row.start_offset === null && row.end_offset === null);
  else { require(row.block_id !== null && (row.start_offset === null) === (row.end_offset === null)); if (row.start_offset !== null) require(row.end_offset !== null && row.start_offset < row.end_offset); }
});
const commentFields = { id, requirement_id: id, content: checked(nonempty, value => require([...value].length <= 2000)), anchor_type: choices(['BLOCK', 'SELECTION']),
  block_id: id, anchor_status: choices(['ATTACHED', 'ORPHANED']), status: choices(['OPEN', 'RESOLVED']), resolved_at: nullable(time), deleted_at: nullable(time), created_at: time, updated_at: time };
export const comment = (value: unknown) => {
  const row = exact(value, [...Object.keys(commentFields), 'anchor_ref']);
  const base = shape(commentFields)(Object.fromEntries(Object.keys(commentFields).map(key => [key, row[key]])));
  const anchor = base.anchor_type === 'BLOCK' ? shape({ block_markdown_snapshot: text })(row.anchor_ref) : selection(row.anchor_ref);
  interval(base, [base.resolved_at, base.deleted_at]); require((base.status === 'RESOLVED') === (base.resolved_at !== null));
  return Object.freeze({ ...base, anchor_ref: anchor });
};
export const commentItem = (value: unknown) => {
  const row = exact(value, [...Object.keys(commentFields), 'anchor_ref', 'location']);
  const base = comment(Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'location'))), target = location(row.location);
  require(base.deleted_at === null);
  if (target.status === 'ATTACHED') {
    require(target.block_id === base.block_id);
    if (base.anchor_type === 'BLOCK') require(target.start_offset === null);
    else { require('selected_text' in base.anchor_ref && target.start_offset !== null && target.end_offset !== null);
      require(target.end_offset - target.start_offset === [...base.anchor_ref.selected_text].length); }
  }
  return Object.freeze({ ...base, location: target });
};
export type Comment = Model<typeof comment>;
export type CommentItem = Model<typeof commentItem>;
export const commentIndex = checked(shape({ requirement_id: id, document_id: id, content_version: id, total_count: count, open_count: count,
  blocks: array(shape({ block_id: id, open_count: id, comment_ids: array(id, Number.MAX_SAFE_INTEGER, 1) }), 10000),
  comments: array(shape({ id, status: choices(['OPEN', 'RESOLVED']), anchor_status: choices(['ATTACHED', 'ORPHANED']), location }), Number.MAX_SAFE_INTEGER) }), row => {
  distinct(row.comments.map(item => item.id)); distinct(row.blocks.map(item => item.block_id));
  require(row.total_count === row.comments.length && row.open_count === row.comments.filter(item => item.status === 'OPEN').length);
  const expected = new Map<number, number[]>();
  for (const item of row.comments) if (item.status === 'OPEN' && item.location.status === 'ATTACHED') {
    const block = item.location.block_id!; const ids = expected.get(block) ?? []; ids.push(item.id); expected.set(block, ids);
  }
  require(row.blocks.length === expected.size);
  for (const block of row.blocks) require(block.open_count === block.comment_ids.length && JSON.stringify(block.comment_ids) === JSON.stringify(expected.get(block.block_id)));
});

export const counts = checked(shape({ total: count, pending: count, accepted: count, rejected: count, edited: count }), row => {
  require(row.total >= 1 && row.total <= 100 && row.total === row.pending + row.accepted + row.rejected + row.edited);
});
const batchFields = { id, requirement_id: id, guide_run_id: id, source_type: choices(['USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT']), source_id: nullable(id),
  title: nonempty, summary: nonempty, status: choices(['PENDING', 'COMPLETED', 'DISCARDED']), completion_result: nullable(choices(['CHANGES_APPLIED', 'NO_CHANGE'])),
  error_message: nullable(nonempty), base_content_version: id, applied_content_version: nullable(id), created_at: time, completed_at: nullable(time), updated_at: time };
export const batchMetadata = checked(shape(batchFields), row => {
  require((row.source_type === 'USER_INSTRUCTION') === (row.source_id === null)); interval(row, [row.completed_at]);
  require((row.status === 'PENDING') === (row.completed_at === null)); require((row.status === 'COMPLETED') === (row.completion_result !== null));
  require(row.completion_result === 'CHANGES_APPLIED' ? row.applied_content_version === row.base_content_version + 1 : row.applied_content_version === null);
});
export const suggestion = checked(shape({ id, batch_id: id, order_no: id, title: nonempty, explanation: nonempty, impact: nullable(text),
  patch_operation: choices(['REPLACE_BLOCK', 'INSERT_BEFORE', 'INSERT_AFTER', 'DELETE_BLOCK', 'REPLACE_TABLE_ROW']), target_ref: shape({ block_id: id }),
  selector: nullable(shape({ key_column_index: count, key_value: text })), original_content: text, proposed_markdown: nullable(nonempty),
  proposed_data: nullable(shape({ cells: array(text, 1000, 1) })), user_edited_content: nullable(nonempty),
  status: choices(['PENDING', 'ACCEPTED', 'REJECTED', 'EDITED']), validation_status: choices(['VALID', 'INVALID']), validation_error: nullable(nonempty),
  created_at: time, decided_at: nullable(time), updated_at: time }), row => {
  validateDefinition('patch', { title: row.title, explanation: row.explanation, impact: row.impact, patch_operation: row.patch_operation,
    target_ref: row.target_ref, selector_json: row.selector, original_content: row.original_content, proposed_markdown: row.proposed_markdown, proposed_data_json: row.proposed_data });
  require((row.validation_status === 'INVALID') === (row.validation_error !== null));
  require((row.status === 'EDITED') === (row.user_edited_content !== null));
  if (row.status === 'EDITED') require(row.patch_operation !== 'DELETE_BLOCK' && [...row.user_edited_content!].length <= 100000);
  require((row.status === 'PENDING') === (row.decided_at === null)); interval(row, [row.decided_at]);
});
export const batch = (value: unknown) => {
  const row = exact(value, [...Object.keys(batchFields), 'suggestions', 'counts']);
  const metadata = batchMetadata(Object.fromEntries(Object.keys(batchFields).map(key => [key, row[key]])));
  const items = array(suggestion, 100, 1)(row.suggestions), totals = counts(row.counts);
  distinct(items.map(item => item.id)); distinct(items.map(item => item.order_no));
  require(items.length === totals.total);
  let order = 0;
  for (const item of items) { require(item.batch_id === metadata.id && item.order_no > order && item.created_at >= metadata.created_at && item.updated_at <= metadata.updated_at); order = item.order_no; }
  for (const state of ['pending', 'accepted', 'rejected', 'edited'] as const) require(totals[state] === items.filter(item => item.status.toLowerCase() === state).length);
  return Object.freeze({ ...metadata, suggestions: items, counts: totals });
};
export type Batch = Model<typeof batch>;
export type Suggestion = Model<typeof suggestion>;
