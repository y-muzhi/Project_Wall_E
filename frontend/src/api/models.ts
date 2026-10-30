/** Public read models only. Private prompts/audit/business source proof stay in
 * the backend. Documents/revisions use the actual registered Markdown parser.
 */
import type { Ctx } from '@milkdown/kit/ctx';
import { validateBlockState, validateDocumentReadModel } from '../documents/contracts.ts';
import { exact, snapshotObject } from './client.ts';
import type { JsonObject } from './client.ts';
import type { DocumentReadModel } from '../documents/contracts.ts';
import collaboration from '../../../backend/resources/v9/schemas/collaboration-contract.v1.json' with { type: 'json' };
import {
  id,
  count,
  bool,
  text,
  nonempty,
  time,
  nullable,
  choices,
  array,
  shape,
  checked,
  require,
  interval,
  distinct,
} from './decoding.ts';
import type { Model } from './decoding.ts';
import { validateDefinition } from './resource-schema.ts';

export const requirementStatuses = [
  'PLANNING',
  'READY',
  'IMPLEMENTING',
  'COMPLETED',
  'CLOSED',
] as const;
export const requirementTypes = ['NEW', 'CHANGE'] as const;
export const runStatuses = ['RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'] as const;
export const runActions = ['ASK', 'GENERATE', 'REVIEW', 'MODIFY'] as const;
export const runSteps = [
  'PREPARING',
  'CALLING_MODEL',
  'VALIDATING',
  'PERSISTING',
  'FINISHED',
] as const;
const taskErrors = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'MANUAL_DRAFT_NOT_FOUND',
  'STATE_CONFLICT',
  'WORK_STATE_CONFLICT',
  'WORK_STATE_INCONSISTENT',
  'CONTENT_VERSION_CONFLICT',
  'TEMPLATE_INVALID',
  'DOCUMENT_INVALID',
  'ANCHOR_INVALID',
  'SCOPE_INVALID',
  'SOURCE_INVALID',
  'PATCH_INVALID',
  'TARGET_STALE',
  'BATCH_PENDING',
  'COMMENT_ORPHANED',
  'CARD_ALREADY_ANSWERED',
  'CARD_EXPIRED',
  'CONFIG_INVALID',
  'STORAGE_UNAVAILABLE',
  'CAPACITY_EXHAUSTED',
  'IDEMPOTENCY_CONFLICT',
  'REQUEST_IN_PROGRESS',
  'INTERNAL_ERROR',
  'MODEL_ERROR',
  'OUTPUT_INVALID',
  'CONTEXT_LIMIT_EXCEEDED',
  'INTERRUPTED',
  'EXECUTION_TIMEOUT',
] as const;
const title = checked(nonempty, (value) =>
  require([...value].length <= 20 && !/[\r\n]/.test(value)),
);
const number = checked(text, (value) => require(/^REQ[0-9]{6}$/.test(value)));
export const requirementSummary = shape({
  id,
  requirement_no: number,
  title,
  requirement_type: choices(requirementTypes),
  // Workbench time is display-only. Preserve the original text and server
  // order; SHR-TIME renders an unparseable cell as -- rather than dropping
  // the whole page. Full business objects retain the strict time decoder.
  status: choices(requirementStatuses),
  updated_at: text,
});
export const requirement = checked(
  shape({
    id,
    requirement_no: number,
    title,
    requirement_type: choices(requirementTypes),
    metadata_version: id,
    initial_message_id: id,
    discussion_version: id,
    status: choices(requirementStatuses),
    document_work_state: choices([
      'IDLE',
      'MANUAL_EDITING',
      'GUIDE_ACTIVE',
      'SUGGESTION_REVIEWING',
    ]),
    active_operation_type: nullable(choices(['MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH'])),
    active_operation_id: nullable(id),
    created_at: time,
    updated_at: time,
    completed_at: nullable(time),
    closed_at: nullable(time),
    state_started_at: nullable(time),
  }),
  (row) => {
    require((row.status === 'COMPLETED') === (row.completed_at !== null));
    require((row.status === 'CLOSED') === (row.closed_at !== null));
    interval(row, [row.completed_at, row.closed_at, row.state_started_at]);
    const owner = {
      IDLE: null,
      MANUAL_EDITING: 'MANUAL_DRAFT',
      GUIDE_ACTIVE: 'GUIDE_RUN',
      SUGGESTION_REVIEWING: 'SUGGESTION_BATCH',
    };
    require(owner[row.document_work_state] === row.active_operation_type);
    require((row.document_work_state === 'IDLE') === (row.active_operation_id === null));
    require((row.document_work_state === 'IDLE') === (row.state_started_at === null));
  },
);
export type Requirement = Model<typeof requirement>;
export type RequirementSummary = Model<typeof requirementSummary>;
export const nullableId = nullable(id);

export const collaborationValue =
  (name: string) =>
  (value: unknown): Readonly<JsonObject> => {
    validateDefinition(name, value, collaboration.$defs);
    return snapshotObject(value);
  };
export const sourceRef = collaborationValue('SourceRef');
export const phaseKinds = ['DISCOVERY', 'SOLUTION', 'SPECIFICATION', 'REVIEW'] as const;
const topicState = shape({
  topic_ref: nonempty,
  phase_ref: nonempty,
  mainline_ref: nonempty,
  title: nonempty,
  purpose: nonempty,
  expected_outcomes: array(
    shape({ outcome_ref: nonempty, text: nonempty, criterion: nonempty }),
    20,
    1,
  ),
  assessment: choices(['NOT_STARTED', 'DISCUSSING', 'SUPPORTED', 'REVIEW_REQUIRED']),
  evidence_refs: array(nonempty, 1000),
  dependencies: array(nonempty, 200),
  unresolved_impacts: array(nonempty, 1000),
  updated_by_message_id: id,
});
export const discussionState = (value: unknown) => {
  collaborationValue('Discussion')(value);
  return shape({
    schema_version: choices([1]),
    phase: shape({
      phase_ref: nonempty,
      kind: choices(phaseKinds),
      guide_ref: collaborationValue('ResourceRef'),
      closure: nullable(
        shape({ message_id: id, summary: nonempty, unresolved_refs: array(nonempty, 1000) }),
      ),
    }),
    focus_topic_ref: nullable(nonempty),
    topics: array(topicState, 200),
    evidence: array(
      shape({
        evidence_ref: nonempty,
        assertion: nonempty,
        origin: choices(['USER_STATEMENT', 'USER_DECISION', 'AI_PROPOSAL']),
        nature: choices(['FACT', 'CONSTRAINT', 'PROPOSAL']),
        applies_to: (item: unknown) =>
          item === 'GLOBAL' ? ('GLOBAL' as const) : array(nonempty, 200, 1)(item),
        source_refs: array(sourceRef, 1000, 1),
        state: choices(['ACTIVE', 'SUPERSEDED', 'DISPUTED']),
        supersedes: array(nonempty, 1000),
        topic_refs: array(nonempty, 200),
      }),
      1000,
    ),
    pending_user_message_ids: array(id, 100000),
    binding: shape({
      target_document_id: nullable(id),
      source_refs: array(sourceRef, 1000),
      scope: nullable(collaborationValue('legacy_scope')),
      document_kind: nullable(choices(['brief', 'design', 'specification'])),
    }),
    dispositions: array(
      shape({
        kind: choices(['DEFER', 'NOT_APPLICABLE', 'REJECT_DRAFT', 'REDIRECT']),
        scope_refs: array(nonempty, 1000),
        message_id: id,
        summary: nonempty,
      }),
      100000,
    ),
    last_step: nullable(shape({ message_id: id, value: collaborationValue('NextStep') })),
    counters: shape({ phase: id, topic: id, evidence: id }),
  })(value);
};
export type DiscussionState = ReturnType<typeof discussionState>;
export const resourceRef = shape({
  key: nonempty,
  version: nonempty,
  digest: checked(text, (value) => require(/^[0-9a-f]{64}$/.test(value))),
});
export const documentKinds = ['REQUIREMENT_BRIEF', 'DESIGN', 'SPECIFICATION'] as const;
export const documentSummaryFields = {
  id,
  requirement_id: id,
  name: checked(nonempty, (value) => require([...value].length <= 80)),
  document_kind: choices(documentKinds),
  document_type: choices(['CURRENT']),
  metadata_version: id,
  content_version: id,
  current_revision_id: id,
  confirmed_revision_id: nullable(id),
  archived_at: nullable(time),
  updated_at: time,
  source_status: choices(['UNCHANGED', 'UPDATED', 'UNAVAILABLE']),
};
export const documentSummary = shape(documentSummaryFields);
export type DocumentSummary = Model<typeof documentSummary>;
export type DocumentView = DocumentReadModel &
  DocumentSummary &
  Readonly<{ template_ref: Model<typeof resourceRef> | null }>;
export type ManualDraft = DocumentReadModel &
  Readonly<{
    target_document_id: number;
    base_content_version: number;
    template_ref: Model<typeof resourceRef> | null;
  }>;
export const discussionSummary = checked(
  shape({
    discussion_version: id,
    phase_ref: nonempty,
    phase_kind: choices(['DISCOVERY', 'SOLUTION', 'SPECIFICATION', 'REVIEW']),
    focus_topic_ref: nullable(nonempty),
    focus_title: nullable(nonempty),
    next_step: nullable(collaborationValue('NextStep')),
    pending_count: count,
  }),
  (value) => {
    require((value.focus_topic_ref === null) === (value.focus_title === null));
  },
);
export const requirementDetail = checked(
  shape({
    requirement,
    documents: array(documentSummary, Number.MAX_SAFE_INTEGER),
    discussion_summary: discussionSummary,
    discussion: nullable(collaborationValue('Discussion')),
    active_operation: nullable(
      shape({
        type: choices(['MANUAL_DRAFT', 'GUIDE_RUN', 'SUGGESTION_BATCH']),
        id,
        summary: nonempty,
        target_document_id: nullable(id),
      }),
    ),
  }),
  (value) => {
    distinct(value.documents.map((document) => document.id));
    require(value.documents.every((document) => document.requirement_id === value.requirement.id));
    require(value.discussion_summary.discussion_version === value.requirement.discussion_version);
    require((value.active_operation === null) === (value.requirement.active_operation_id === null));
    if (value.active_operation !== null)
      require(
        value.active_operation.id === value.requirement.active_operation_id &&
          value.active_operation.type === value.requirement.active_operation_type,
      );
    if (value.active_operation?.target_document_id != null)
      require(
        value.documents.some(
          (document) => document.id === value.active_operation!.target_document_id,
        ),
      );
    if (value.active_operation !== null && value.active_operation.type !== 'GUIDE_RUN')
      require(value.active_operation.target_document_id !== null);
  },
);
export type RequirementDetail = Model<typeof requirementDetail>;

export const revisionSummaryFields = {
  id,
  requirement_id: id,
  document_id: id,
  version_no: id,
  source_content_version: id,
  created_at: time,
  change_summary: nullable(text),
  source_refs: array(sourceRef, Number.MAX_SAFE_INTEGER),
  markers: array(
    shape({
      event_id: id,
      description: nullable(checked(nonempty, (value) => require([...value].length <= 1000))),
      created_at: time,
    }),
    Number.MAX_SAFE_INTEGER,
  ),
};
export const revisionSummary = checked(shape(revisionSummaryFields), (row) => {
  require(row.version_no === row.source_content_version);
  distinct(row.markers.map((marker) => marker.event_id));
  require(
    row.markers.every(
      (marker, index) =>
        marker.created_at >= row.created_at &&
        (index === 0 ||
          marker.created_at > row.markers[index - 1]!.created_at ||
          (marker.created_at === row.markers[index - 1]!.created_at &&
            marker.event_id > row.markers[index - 1]!.event_id)),
    ),
  );
});
export type RevisionSummary = Model<typeof revisionSummary>;
export const versionMarker = shape({
  revision_id: id,
  event_id: id,
  marked: checked(bool, (value) => require(value)),
});
export type VersionMarker = Model<typeof versionMarker>;
export const documentEffect = checked(
  shape({
    document_id: id,
    before_content_version: nullable(id),
    after_content_version: id,
    revision_id: id,
    result: choices(['CREATED', 'UPDATED', 'NO_CHANGE']),
  }),
  (value) => {
    if (value.result === 'CREATED')
      require(value.before_content_version === null && value.after_content_version === 1);
    else
      require(
        value.before_content_version !== null &&
          value.after_content_version ===
            value.before_content_version + (value.result === 'UPDATED' ? 1 : 0),
      );
  },
);
export type DocumentEffect = Model<typeof documentEffect>;
export function documentBodyDecoder(ctx: Ctx, kind: 'CURRENT' | 'MANUAL_DRAFT') {
  return (value: unknown) => {
    const { document } = validateDocumentReadModel(ctx, value);
    require(document.document_type === kind);
    return document;
  };
}
export function documentDecoder(ctx: Ctx, kind: 'CURRENT'): (value: unknown) => DocumentView;
export function documentDecoder(ctx: Ctx, kind: 'MANUAL_DRAFT'): (value: unknown) => ManualDraft;
export function documentDecoder(ctx: Ctx, kind: 'CURRENT' | 'MANUAL_DRAFT') {
  return (value: unknown) => {
    const core = [
      'id',
      'requirement_id',
      'document_type',
      'markdown_content',
      'block_state_json',
      'content_version',
      'created_at',
      'updated_at',
    ];
    const extra =
      kind === 'CURRENT'
        ? Object.keys(documentSummaryFields).filter((key) => !core.includes(key))
        : ['target_document_id', 'base_content_version'];
    const row = exact(value, [...core, ...extra, 'template_ref']);
    const { document } = validateDocumentReadModel(
      ctx,
      Object.fromEntries(core.map((key) => [key, row[key]])),
    );
    require(document.document_type === kind);
    const template_ref = nullable(resourceRef)(row.template_ref);
    if (kind === 'CURRENT')
      return Object.freeze({
        ...document,
        ...documentSummary(
          Object.fromEntries(Object.keys(documentSummaryFields).map((key) => [key, row[key]])),
        ),
        template_ref,
      });
    return Object.freeze({
      ...document,
      target_document_id: id(row.target_document_id),
      base_content_version: id(row.base_content_version),
      template_ref,
    });
  };
}
export function revisionDecoder(ctx: Ctx) {
  return (value: unknown) => {
    const row = exact(value, [
      ...Object.keys(revisionSummaryFields),
      'markdown_content',
      'block_state_json',
    ]);
    const summary = revisionSummary(
      Object.fromEntries(Object.keys(revisionSummaryFields).map((key) => [key, row[key]])),
    );
    const pair = validateBlockState(ctx, row.markdown_content, row.block_state_json);
    return Object.freeze({
      ...summary,
      markdown_content: pair.source.markdown,
      block_state_json: pair.state,
    });
  };
}

const selection = shape({
  selected_text: checked(nonempty, (value) => require([...value].length <= 2000)),
  prefix_text: checked(text, (value) => require([...value].length <= 100)),
  suffix_text: checked(text, (value) => require([...value].length <= 100)),
});
export const scope = (value: unknown) => {
  const row = exact(value, ['scope_type', 'scope_ref']);
  const kind = choices(['DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION'])(row.scope_type);
  if (kind === 'DOCUMENT') {
    require(row.scope_ref === null);
    return Object.freeze({ scope_type: kind, scope_ref: null });
  }
  if (kind === 'SELECTION')
    return Object.freeze({
      scope_type: kind,
      scope_ref: shape({
        block_id: id,
        selected_text: selectionText('selected_text'),
        prefix_text: selectionText('prefix_text'),
        suffix_text: selectionText('suffix_text'),
      })(row.scope_ref),
    });
  return Object.freeze({ scope_type: kind, scope_ref: shape({ block_id: id })(row.scope_ref) });
};
function selectionText(key: 'selected_text' | 'prefix_text' | 'suffix_text') {
  return (value: unknown) => {
    const result = text(value),
      size = [...result].length;
    require(
      size <= (key === 'selected_text' ? 2000 : 100) && (key !== 'selected_text' || size > 0),
    );
    return result;
  };
}
export const operations = [
  'DISCUSS',
  'GENERATE',
  'REVISE',
  'PROPOSE_CHANGES',
  'COMPARE',
  'REVIEW',
] as const;
export const targetRef = (value: unknown) => {
  collaborationValue('Target')(value);
  const row = snapshotObject(value);
  return row.kind === 'NEW'
    ? shape({
        kind: choices(['NEW']),
        name: nonempty,
        document_kind: choices(['brief', 'design', 'specification']),
        template_ref: nullable(shape({ key: nonempty, version: nonempty })),
      })(row)
    : shape({ kind: choices(['EXISTING']), document_id: id, expected_content_version: id })(row);
};
export const wireScope = (value: unknown) => {
  const row = collaborationValue('legacy_scope')(value);
  if (row.scope_type === 'SECTION') {
    const ref = snapshotObject(row.scope_ref);
    return scope({ scope_type: 'SECTION', scope_ref: { block_id: ref.heading_block_id } });
  }
  return scope(row);
};
export const runReceipt = shape({
  processing: choices(['MODEL']),
  guide_run_id: id,
  user_message_id: id,
});
export type RunReceipt = ReturnType<typeof runReceipt>;
const runFields = {
  id,
  requirement_id: id,
  action_type: choices(runActions),
  function_type: choices(['collaboration_v1']),
  source_type: choices(['USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT']),
  source_id: nullable(id),
  scope: nullable(wireScope),
  status: choices(runStatuses),
  current_step: choices(runSteps),
  suggestion_batch_id: nullable(id),
  latest_assistant_message_id: nullable(id),
  error_code: nullable(choices(taskErrors)),
  error_message: nullable(nonempty),
  cancel_reason: nullable(nonempty),
  retry_of_guide_run_id: nullable(id),
  created_at: time,
  started_at: nullable(time),
  waiting_user_at: nullable(time),
  ended_at: nullable(time),
  updated_at: time,
  operation: choices(operations),
  parent_guide_run_id: nullable(id),
  target: nullable(targetRef),
  discussion_version_snapshot: id,
  material_summary: nullable(
    shape({
      document_count: count,
      block_count: count,
      history_count: count,
      pending_count: count,
      omitted_count: count,
    }),
  ),
  application_result: nullable(choices(['NOT_REQUESTED', 'APPLIED', 'NO_CHANGE', 'NOT_APPLIED'])),
  progress_result: nullable(choices(['NOT_REQUESTED', 'APPLIED', 'NO_CHANGE', 'REJECTED'])),
  progress_error: nullable(nonempty),
  document_effect: nullable(documentEffect),
};
function checkRun(row: Model<ReturnType<typeof shape<typeof runFields>>>) {
  const actions = {
    DISCUSS: 'ASK',
    GENERATE: 'GENERATE',
    REVISE: 'MODIFY',
    PROPOSE_CHANGES: 'MODIFY',
    COMPARE: 'REVIEW',
    REVIEW: 'REVIEW',
  };
  require(row.action_type === actions[row.operation]);
  require((row.source_type === 'USER_INSTRUCTION') === (row.source_id === null));
  const terminal = row.status !== 'RUNNING';
  require(
    terminal === (row.ended_at !== null) &&
      terminal === (row.current_step === 'FINISHED') &&
      row.waiting_user_at === null,
  );
  require(
    (row.status === 'FAILED') === (row.error_code !== null) &&
      (row.status === 'FAILED') === (row.error_message !== null),
  );
  require((row.status === 'CANCELLED') === (row.cancel_reason !== null));
  require(row.retry_of_guide_run_id !== row.id && row.parent_guide_run_id !== row.id);
  require(!terminal || (row.application_result !== null && row.progress_result !== null));
  require((row.progress_result === 'REJECTED') === (row.progress_error !== null));
  require(
    row.application_result !== 'APPLIED' ||
      row.document_effect !== null ||
      row.suggestion_batch_id !== null,
  );
  interval(row, [row.started_at, row.ended_at]);
}
export const guideSummary = checked(shape(runFields), checkRun);
export const analysis = (value: unknown) => {
  collaborationValue('Analysis')(value);
  return shape({
    conclusion: choices(['RESULT', 'NO_CHANGE', 'NEED_EVIDENCE', 'INCOMPLETE']),
    summary: nonempty,
    findings: array(
      shape({
        ref: nonempty,
        severity: choices(['INFO', 'WARNING', 'CONFLICT']),
        message: nonempty,
        source_refs: array(nonempty, 100000),
      }),
      100,
    ),
    covered_refs: array(nonempty, 100000),
    unresolved: array(
      shape({
        ref: nonempty,
        description: nonempty,
        source_refs: array(nonempty, 100000),
        impact: nonempty,
      }),
      100,
    ),
  })(value);
};
const finalResult = shape({
  summary: nonempty,
  assistant_message_id: nullable(id),
  current_document_version: nullable(id),
  suggestion_batch_id: nullable(id),
  analysis: nullable(analysis),
});
const decodeGuideRun = checked(
  shape({
    ...runFields,
    final_result: nullable(finalResult),
    returned_responses: array(
      shape({ llm_use_id: id, call_no: id, attempt_no: id, content: text }),
      Number.MAX_SAFE_INTEGER,
    ),
  }),
  (row) => {
    checkRun(row);
    require((row.status === 'COMPLETED') === (row.final_result !== null));
    if (row.final_result !== null)
      require(row.final_result.suggestion_batch_id === row.suggestion_batch_id);
  },
);
export const guideRun = decodeGuideRun;
export const guideAccepted = shape({
  id,
  requirement_id: id,
  status: choices(runStatuses),
  current_step: choices(runSteps),
});
export type GuideRun = Model<typeof guideRun>;
export type GuideSummary = Model<typeof guideSummary>;

const option = shape({
  option_key: nonempty,
  label: nonempty,
  description: text,
  impact: text,
  risks: text,
});
const card = shape({
  card_key: nonempty,
  card_type: choices(['SINGLE_SELECT', 'MULTI_SELECT', 'CONFIRM']),
  question: nonempty,
  context: text,
  required: bool,
  options: array(option, 8, 2),
  selection_rule: shape({ min: count, max: count }),
  custom_answer: shape({ enabled: bool, max_length: count }),
  recommendation: nullable(shape({ option_keys: array(nonempty, 8), reason: text })),
  related_spec_context: array(
    shape({ document_id: id, content_version: id, block_id: id, content_snapshot: text }),
    20,
  ),
});
export const cards = checked(
  shape({
    schema_version: choices([1]),
    intro: text,
    purpose: choices(['CLARIFICATION', 'DOCUMENT_ACTION', 'PHASE_CHANGE', 'FACT_CONFIRMATION']),
    cards: array(card, 5, 1),
    action_payload: nullable(snapshotObject),
    program_binding: shape({
      discussion_version: id,
      target_content_version: nullable(id),
      source_heads: array(shape({ document_id: id, content_version: id }), 1000),
    }),
  }),
  (row) => {
    collaborationValue('StoredCardGroup')(row);
    distinct(row.cards.map((item) => item.card_key));
    for (const item of row.cards) {
      const keys = item.options.map((entry) => entry.option_key);
      distinct(keys);
      require(
        item.selection_rule.min <= item.selection_rule.max &&
          item.selection_rule.max <= keys.length + Number(item.custom_answer.enabled),
      );
      require(
        item.custom_answer.enabled
          ? item.custom_answer.max_length >= 1 && item.custom_answer.max_length <= 2000
          : item.custom_answer.max_length === 0,
      );
      if (item.recommendation !== null) {
        distinct(item.recommendation.option_keys);
        require(item.recommendation.option_keys.every((key) => keys.includes(key)));
      }
    }
  },
);
export const executionSelection = shape({
  target: targetRef,
  scope: nullable(collaborationValue('legacy_scope')),
  source_refs: array(sourceRef, 1000),
  acknowledge_source_changes: bool,
});
export const responses = checked(
  shape({
    schema_version: choices([1]),
    responses: array(
      shape({
        card_key: nonempty,
        selected_option_keys: array(nonempty, 8),
        custom_answer: nullable(nonempty),
        skipped: bool,
      }),
      5,
      1,
    ),
    execution_selection: nullable(executionSelection),
  }),
  (row) => {
    collaborationValue('StoredResponses')(row);
    distinct(row.responses.map((item) => item.card_key));
    for (const answer of row.responses) {
      distinct(answer.selected_option_keys);
      if (answer.skipped)
        require(answer.selected_option_keys.length === 0 && answer.custom_answer === null);
    }
  },
);
export type Cards = Model<typeof cards>;
export type Responses = Model<typeof responses>;
export const programReceipt = checked(
  shape({
    processing: choices(['PROGRAM']),
    user_message_id: id,
    requirement_id: id,
    discussion_version: id,
    purpose: choices(['DOCUMENT_ACTION', 'PHASE_CHANGE', 'FACT_CONFIRMATION']),
    result: choices(['APPLIED', 'DEFERRED', 'NO_CHANGE']),
    document_effect: nullable(documentEffect),
  }),
  (row) => {
    if (row.purpose === 'DOCUMENT_ACTION') require(row.result === 'DEFERRED');
    if (row.document_effect !== null)
      require(row.purpose === 'FACT_CONFIRMATION' && row.result !== 'DEFERRED');
    if (row.purpose === 'FACT_CONFIRMATION' && row.result !== 'DEFERRED')
      require(row.document_effect !== null);
  },
);
export const message = (value: unknown) => {
  const row = exact(value, [
    'id',
    'requirement_id',
    'guide_run_id',
    'sequence_no',
    'role',
    'content',
    'message_type',
    'structured_content',
    'reply_to_message_id',
    'created_at',
    'card_state',
    'phase_ref',
    'topic_refs',
    'document_ids',
    'program_receipt',
  ]);
  const base = shape({
    id,
    requirement_id: id,
    guide_run_id: nullable(id),
    sequence_no: id,
    role: choices(['USER', 'ASSISTANT']),
    content: text,
    message_type: choices(['TEXT', 'INTERACTION_CARDS', 'CARD_RESPONSE']),
    reply_to_message_id: nullable(id),
    created_at: time,
    card_state: nullable(choices(['AVAILABLE', 'ANSWERED', 'EXPIRED'])),
    phase_ref: nullable(nonempty),
    topic_refs: array(nonempty, 200),
    document_ids: array(id, 1000),
    program_receipt: nullable(programReceipt),
  })(Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'structured_content')));
  distinct(base.topic_refs);
  distinct(base.document_ids);
  const structured =
    row.structured_content === null
      ? null
      : base.message_type === 'INTERACTION_CARDS'
        ? cards(row.structured_content)
        : responses(row.structured_content);
  if (base.message_type === 'TEXT')
    require(structured === null && base.reply_to_message_id === null && base.card_state === null);
  if (base.message_type === 'INTERACTION_CARDS')
    require(
      base.role === 'ASSISTANT' &&
        base.reply_to_message_id === null &&
        (structured !== null) === (base.card_state !== null),
    );
  if (base.message_type === 'CARD_RESPONSE')
    require(base.role === 'USER' && base.reply_to_message_id !== null && base.card_state === null);
  if (base.program_receipt !== null)
    require(
      base.message_type === 'CARD_RESPONSE' &&
        base.guide_run_id === null &&
        base.program_receipt.user_message_id === base.id &&
        base.program_receipt.requirement_id === base.requirement_id,
    );
  return Object.freeze({ ...base, structured_content: structured });
};
export type Message = Model<typeof message>;

export const location = checked(
  shape({
    status: choices(['ATTACHED', 'ORPHANED']),
    block_id: nullable(id),
    start_offset: nullable(count),
    end_offset: nullable(count),
  }),
  (row) => {
    if (row.status === 'ORPHANED')
      require(row.block_id === null && row.start_offset === null && row.end_offset === null);
    else {
      require(row.block_id !== null && (row.start_offset === null) === (row.end_offset === null));
      if (row.start_offset !== null)
        require(row.end_offset !== null && row.start_offset < row.end_offset);
    }
  },
);
const commentFields = {
  id,
  requirement_id: id,
  document_id: id,
  content: checked(nonempty, (value) => require([...value].length <= 2000)),
  anchor_type: choices(['BLOCK', 'SELECTION']),
  block_id: id,
  anchor_status: choices(['ATTACHED', 'ORPHANED']),
  status: choices(['OPEN', 'RESOLVED']),
  resolved_at: nullable(time),
  deleted_at: nullable(time),
  created_at: time,
  updated_at: time,
};
export const comment = (value: unknown) => {
  const row = exact(value, [...Object.keys(commentFields), 'anchor_ref']);
  const base = shape(commentFields)(
    Object.fromEntries(Object.keys(commentFields).map((key) => [key, row[key]])),
  );
  const anchor =
    base.anchor_type === 'BLOCK'
      ? shape({ block_markdown_snapshot: text })(row.anchor_ref)
      : selection(row.anchor_ref);
  interval(base, [base.resolved_at, base.deleted_at]);
  require((base.status === 'RESOLVED') === (base.resolved_at !== null));
  return Object.freeze({ ...base, anchor_ref: anchor });
};
export const commentItem = (value: unknown) => {
  const row = exact(value, [...Object.keys(commentFields), 'anchor_ref', 'location']);
  const base = comment(
      Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'location')),
    ),
    target = location(row.location);
  require(base.deleted_at === null);
  if (target.status === 'ATTACHED') {
    require(target.block_id === base.block_id);
    if (base.anchor_type === 'BLOCK') require(target.start_offset === null);
    else {
      require(
        'selected_text' in base.anchor_ref &&
          target.start_offset !== null &&
          target.end_offset !== null,
      );
      require(
        target.end_offset - target.start_offset === [...base.anchor_ref.selected_text].length,
      );
    }
  }
  return Object.freeze({ ...base, location: target });
};
export type Comment = Model<typeof comment>;
export type CommentItem = Model<typeof commentItem>;
export const commentIndex = checked(
  shape({
    requirement_id: id,
    document_id: id,
    content_version: id,
    total_count: count,
    open_count: count,
    blocks: array(
      shape({ block_id: id, open_count: id, comment_ids: array(id, Number.MAX_SAFE_INTEGER, 1) }),
      10000,
    ),
    comments: array(
      shape({
        id,
        status: choices(['OPEN', 'RESOLVED']),
        anchor_status: choices(['ATTACHED', 'ORPHANED']),
        location,
      }),
      Number.MAX_SAFE_INTEGER,
    ),
  }),
  (row) => {
    distinct(row.comments.map((item) => item.id));
    distinct(row.blocks.map((item) => item.block_id));
    require(
      row.total_count === row.comments.length &&
        row.open_count === row.comments.filter((item) => item.status === 'OPEN').length,
    );
    const expected = new Map<number, number[]>();
    for (const item of row.comments)
      if (item.status === 'OPEN' && item.location.status === 'ATTACHED') {
        const block = item.location.block_id!;
        const ids = expected.get(block) ?? [];
        ids.push(item.id);
        expected.set(block, ids);
      }
    require(row.blocks.length === expected.size);
    for (const block of row.blocks)
      require(
        block.open_count === block.comment_ids.length &&
          JSON.stringify(block.comment_ids) === JSON.stringify(expected.get(block.block_id)),
      );
  },
);

export const counts = checked(
  shape({ total: count, pending: count, accepted: count, rejected: count, edited: count }),
  (row) => {
    require(
      row.total >= 1 &&
        row.total <= 100 &&
        row.total === row.pending + row.accepted + row.rejected + row.edited,
    );
  },
);
const batchFields = {
  id,
  requirement_id: id,
  guide_run_id: id,
  source_type: choices(['USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT']),
  source_id: nullable(id),
  title: nonempty,
  summary: nonempty,
  status: choices(['PENDING', 'COMPLETED', 'DISCARDED']),
  completion_result: nullable(choices(['CHANGES_APPLIED', 'NO_CHANGE'])),
  error_message: nullable(nonempty),
  base_content_version: id,
  applied_content_version: nullable(id),
  created_at: time,
  completed_at: nullable(time),
  updated_at: time,
  target_document_id: id,
  source_refs: array(sourceRef, 1000),
};
export const batchMetadata = checked(shape(batchFields), (row) => {
  require((row.source_type === 'USER_INSTRUCTION') === (row.source_id === null));
  interval(row, [row.completed_at]);
  require((row.status === 'PENDING') === (row.completed_at === null));
  require((row.status === 'COMPLETED') === (row.completion_result !== null));
  require(
    row.completion_result === 'CHANGES_APPLIED'
      ? row.applied_content_version === row.base_content_version + 1
      : row.applied_content_version === null,
  );
});
export const suggestion = checked(
  shape({
    id,
    batch_id: id,
    order_no: id,
    title: nonempty,
    explanation: nonempty,
    impact: nullable(text),
    patch_operation: choices([
      'REPLACE_BLOCK',
      'INSERT_BEFORE',
      'INSERT_AFTER',
      'DELETE_BLOCK',
      'REPLACE_TABLE_ROW',
    ]),
    target_ref: shape({ block_id: id }),
    selector: nullable(shape({ key_column_index: count, key_value: text })),
    original_content: text,
    proposed_markdown: nullable(nonempty),
    proposed_data: nullable(shape({ cells: array(text, 1000, 1) })),
    user_edited_content: nullable(nonempty),
    status: choices(['PENDING', 'ACCEPTED', 'REJECTED', 'EDITED']),
    validation_status: choices(['VALID', 'INVALID']),
    validation_error: nullable(nonempty),
    created_at: time,
    decided_at: nullable(time),
    updated_at: time,
  }),
  (row) => {
    validateDefinition('patch', {
      title: row.title,
      explanation: row.explanation,
      impact: row.impact,
      patch_operation: row.patch_operation,
      target_ref: row.target_ref,
      selector_json: row.selector,
      original_content: row.original_content,
      proposed_markdown: row.proposed_markdown,
      proposed_data_json: row.proposed_data,
    });
    require((row.validation_status === 'INVALID') === (row.validation_error !== null));
    require((row.status === 'EDITED') === (row.user_edited_content !== null));
    if (row.status === 'EDITED')
      require(
        row.patch_operation !== 'DELETE_BLOCK' && [...row.user_edited_content!].length <= 100000,
      );
    require((row.status === 'PENDING') === (row.decided_at === null));
    interval(row, [row.decided_at]);
  },
);
export const batch = (value: unknown) => {
  const row = exact(value, [...Object.keys(batchFields), 'suggestions', 'counts']);
  const metadata = batchMetadata(
    Object.fromEntries(Object.keys(batchFields).map((key) => [key, row[key]])),
  );
  const items = array(suggestion, 100, 1)(row.suggestions),
    totals = counts(row.counts);
  distinct(items.map((item) => item.id));
  distinct(items.map((item) => item.order_no));
  require(items.length === totals.total);
  let order = 0;
  for (const item of items) {
    require(
      item.batch_id === metadata.id &&
        item.order_no > order &&
        item.created_at >= metadata.created_at &&
        item.updated_at <= metadata.updated_at,
    );
    order = item.order_no;
  }
  for (const state of ['pending', 'accepted', 'rejected', 'edited'] as const)
    require(totals[state] === items.filter((item) => item.status.toLowerCase() === state).length);
  return Object.freeze({ ...metadata, suggestions: items, counts: totals });
};
export type Batch = Model<typeof batch>;
export type Suggestion = Model<typeof suggestion>;
