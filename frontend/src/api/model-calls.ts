import {
  array,
  bool,
  checked,
  choices,
  count,
  id,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';
import { collaborationValue, operations } from './models.ts';

const callStates = ['RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'] as const;
const checkStates = ['NOT_STARTED', 'SUCCEEDED', 'FAILED'] as const;
export const modelCall = shape({
  id,
  guide_run_id: id,
  call_no: id,
  attempt_no: id,
  model_name: text,
  call_status: choices(callStates),
  parse_status: choices(checkStates),
  validation_status: choices(checkStates),
  started_at: time,
  ended_at: nullable(time),
  user_message_id: nullable(id),
  document_version: nullable(id),
  input_tokens: nullable(count),
  output_tokens: nullable(count),
  total_tokens: nullable(count),
  cached_tokens: nullable(count),
  duration_ms: nullable(count),
});
export const modelCalls = checked(
  shape({
    id,
    requirement_id: id,
    operation: choices(operations),
    action_type: choices(['INITIALIZE', 'ASK', 'REVIEW', 'MODIFY', 'GENERATE'] as const),
    status: choices(['RUNNING', 'WAITING_USER', 'COMPLETED', 'FAILED', 'CANCELLED'] as const),
    current_step: choices([
      'PREPARING',
      'CALLING_MODEL',
      'VALIDATING',
      'PERSISTING',
      'WAITING_USER',
      'FINISHED',
    ] as const),
    trigger_message_id: nullable(id),
    program_processed: bool,
    items: array(modelCall, Number.MAX_SAFE_INTEGER),
  }),
  (value) => {
    require(
      value.items.every((call) => call.guide_run_id === value.id) &&
        new Set(value.items.map((call) => call.id)).size === value.items.length,
    );
    require(!value.program_processed || value.items.length === 0);
  },
);
const budget = shape({
  total_tokens: count,
  input_tokens: count,
  output_tokens: count,
  prompt_tokens: count,
  current_user_tokens: count,
  source_tokens: count,
  history_tokens: count,
  template_tokens: count,
  counting: text,
});
const selectionFields = {
  read_blocks: nullable(count),
  history_messages: nullable(count),
  soft_input_target: nullable(count),
  count_attempts: nullable(count),
  soft_target_exceeded: nullable(bool),
};
const detailFields = {
  call: modelCall,
  requirement_id: id,
  operation: choices(operations),
  action_type: choices(['INITIALIZE', 'ASK', 'REVIEW', 'MODIFY', 'GENERATE'] as const),
  prompt_reference: nullable(text),
  context_reference: nullable(text),
  sections: array(
    shape({
      key: text,
      title: text,
      content: text,
      characters: count,
      item_count: nullable(count),
    }),
    Number.MAX_SAFE_INTEGER,
  ),
  context_strategy: nullable(text),
  selection_summary: nullable(shape(selectionFields)),
  included_history_ids: array(id, Number.MAX_SAFE_INTEGER),
  budget_removed_history_ids: array(id, Number.MAX_SAFE_INTEGER),
  raw_request_json: nullable(text),
  preflight: shape({
    input_tokens: nullable(count),
    budget: nullable(budget),
    counts: array(nullable(count), 6, 6),
  }),
};
const detailShape = shape(detailFields);
const collaborationDetail = checked(
  shape({
    ...detailFields,
    context_strategy: choices(['collaboration_context_v1']),
    selection_summary: nullable(
      shape({
        ...selectionFields,
        selected_materials: array(collaborationValue('ManifestItem'), 100000),
        omitted_materials: array(collaborationValue('Omitted'), 100000),
        resource_refs: array(collaborationValue('ResourceRef'), 100),
      }),
    ),
    preflight: shape({
      input_tokens: nullable(count),
      budget: nullable(
        shape({
          total_tokens: count,
          input_tokens: count,
          output_tokens: count,
          framing_reserve: count,
          soft_input_target: count,
          counting: text,
        }),
      ),
      counts: array(nullable(count), 8, 8),
    }),
  }),
  (detail) => {
    require(detail.sections.every((section) => [...section.content].length === section.characters));
    require(new Set(detail.sections.map((section) => section.key)).size === detail.sections.length);
  },
);
export const modelCallDetail = (value: unknown) => {
  require(value !== null && typeof value === 'object' && !Array.isArray(value));
  // Older servers and historical fixtures have no phase A diagnostics.
  if ('context_strategy' in value && value.context_strategy === 'collaboration_context_v1')
    return collaborationDetail(value);
  return detailShape({ context_strategy: null, selection_summary: null, ...value });
};
export type ModelCall = ReturnType<typeof modelCall>;
export type ModelCalls = ReturnType<typeof modelCalls>;
export type ModelCallDetail = ReturnType<typeof modelCallDetail>;
