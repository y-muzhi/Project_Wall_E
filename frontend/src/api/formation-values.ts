/** V2.1 public read contracts. Runtime fields remain exact and detached. */
import { positiveInteger } from './client.ts';
import {
  array,
  bool,
  checked,
  choices,
  count,
  distinct,
  id,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';
import { sourceRef as sharedSourceRef } from './models.ts';

// Decode on invocation so the shared SourceRef definition is retained without
// accessing an uninitialized binding during the models/read-model import cycle.
const sourceRef = (value: unknown) => sharedSourceRef(value);
const unlimited = Number.MAX_SAFE_INTEGER;
export const stepStatuses = ['PLANNED', 'IN_PROGRESS', 'PAUSED', 'COMPLETED', 'CANCELLED'] as const;
export const branchStatuses = ['OPEN', 'RESOLVED', 'DEFERRED', 'DROPPED'] as const;
export const proposalStatuses = ['PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED'] as const;
export const nativeActions = [
  'START_STEP',
  'PAUSE_STEP',
  'RESUME_STEP',
  'SWITCH_STEP',
  'REOPEN_STEP',
  'COMPLETE_STEP',
  'ADJUST_PATH',
  'ENTER_BRANCH',
  'RETURN_FROM_BRANCH',
  'DISPOSE_BRANCH',
  'RESUME_BRANCH',
  'RESUME_ISSUE',
  'DEFER_WRITE_PROPOSAL',
  'RESUME_WRITE_PROPOSAL',
  'WITHDRAW_PROPOSAL_ADJUSTMENT',
] as const;
export const stateReasons = [
  'FORMATION_NOT_INITIALIZED',
  'ARTIFACT_SUPERSEDED',
  'PATH_CHANGED',
  'GOAL_CHANGED',
  'STEP_DEFINITION_CHANGED',
  'TARGET_CHANGED',
  'BRANCH_STATE_CHANGED',
  'BRANCH_RETURN_MISMATCH',
  'PROPOSAL_ADJUSTING',
  'PROPOSAL_BASIS_CHANGED',
  'SOURCE_UNAVAILABLE',
  'INVALID_TRANSITION',
] as const;
const availabilityReasons = [
  ...stateReasons,
  'WORK_STATE_CONFLICT',
  'WORK_STATE_INCONSISTENT',
  'CONTENT_CHANGED',
  'DEFINITION_CHANGED',
  'PURPOSE_CHANGED',
  'BASIS_CHANGED',
  'ADJUSTING',
  'ALREADY_ANSWERED',
  'DEFERRED',
  'SUPERSEDED',
] as const;
export function boundedText(maximum: number, minimum = 1) {
  return checked(text, (value) =>
    require([...value].length >= minimum && [...value].length <= maximum),
  );
}
function reference(prefix: 's' | 'b' | 'i' | 'a', value: unknown): string {
  const result = text(value);
  require(result.length <= 17 && new RegExp('^' + prefix + '[1-9][0-9]*$').test(result));
  positiveInteger(Number(result.slice(1)));
  return result;
}
export const stepRef = (value: unknown) => reference('s', value);
export const branchRef = (value: unknown) => reference('b', value);
export const issueRef = (value: unknown) => reference('i', value);
export const artifactRef = (value: unknown) => reference('a', value);
export const resultRef = (value: unknown): string => {
  const result = text(value);
  require(result.length <= 35 && /^s[1-9][0-9]*\.o[1-9][0-9]*$/.test(result));
  const parts = result.split('.o');
  stepRef(parts[0]);
  positiveInteger(Number(parts[1]));
  return result;
};
export const digest = checked(text, (value) => require(/^[0-9a-f]{64}$/.test(value)));
export const proposalRef = shape({ message_id: id, card_key: boundedText(100) });
export const availabilityReason = choices(availabilityReasons);
export const availability = checked(
  shape({
    action: choices([...nativeActions, 'apply', 'adjust', 'preview']),
    available: bool,
    reason: nullable(choices(availabilityReasons)),
  }),
  (value) => require(value.available === (value.reason === null)),
);
export const versionBasis = checked(
  shape({
    discussion_version: id,
    formation_version: nullable(id),
    goal_version: nullable(id),
    document_revision_id: id,
    content_version: id,
  }),
  (value) => require((value.formation_version === null) === (value.goal_version === null)),
);
const statusCounts = {
  steps: shape({
    PLANNED: count,
    IN_PROGRESS: count,
    PAUSED: count,
    COMPLETED: count,
    CANCELLED: count,
  }),
  branches: shape({ OPEN: count, RESOLVED: count, DEFERRED: count, DROPPED: count }),
  issues: shape({ OPEN: count, RESOLVED: count, DEFERRED: count, DROPPED: count }),
  proposals: shape({ PENDING: count, DEFERRED: count, APPLIED: count, SUPERSEDED: count }),
  pending_review_artifacts: count,
};
export const formationSummary = checked(
  shape({
    document_id: id,
    view_schema: choices(['formation_read_v21_1']),
    exists: bool,
    formation_version: nullable(id),
    goal: nullable(
      shape({ version: id, text: boundedText(1000), source_refs: array(sourceRef, unlimited) }),
    ),
    current_step_ref: nullable(stepRef),
    active_branch_ref: nullable(branchRef),
    counts: shape(statusCounts),
    availability: array(availability, 20),
  }),
  (value) => {
    require(value.exists === (value.formation_version !== null && value.goal !== null));
    if (!value.exists) {
      require(
        value.formation_version === null &&
          value.goal === null &&
          value.current_step_ref === null &&
          value.active_branch_ref === null &&
          value.availability.length === 0,
      );
      require(value.counts.pending_review_artifacts === 0);
      for (const counts of [
        value.counts.steps,
        value.counts.branches,
        value.counts.issues,
        value.counts.proposals,
      ])
        require(Object.values(counts).every((total) => total === 0));
    }
    require(value.active_branch_ref === null || value.current_step_ref !== null);
  },
);
export type FormationSummary = ReturnType<typeof formationSummary>;

export const sourceStatus = checked(
  shape({
    source_ref: sourceRef,
    availability: choices(['AVAILABLE', 'MISSING', 'UNSUPPORTED']),
    reason: nullable(choices(['SOURCE_MISSING', 'RESOURCE_UNSUPPORTED'])),
  }),
  (value) =>
    require(
      value.availability === 'AVAILABLE'
        ? value.reason === null
        : value.availability === 'MISSING'
          ? value.reason === 'SOURCE_MISSING'
          : value.reason === 'RESOURCE_UNSUPPORTED',
    ),
);
export const eventActions = [
  'PATH_INITIALIZED',
  'GOAL_CHANGED',
  'STEP_ADDED',
  'STEP_UPDATED',
  'STEP_MOVED',
  'STEP_STARTED',
  'STEP_PAUSED',
  'STEP_RESUMED',
  'STEP_REOPENED',
  'STEP_COMPLETED',
  'STEP_CANCELLED',
  'DISCUSSION_STEP_SELECTED',
  'RESULT_ROUTE',
  'ISSUE_ADDED',
  'ISSUE_UPDATED',
  'ISSUE_RESOLVED',
  'ISSUE_MOVED',
  'ISSUE_DISPOSITION_CHANGED',
  'ISSUE_RESUMED',
  'BRANCH_ADDED',
  'BRANCH_UPDATED',
  'BRANCH_RESULT_RECORDED',
  'BRANCH_ENTERED',
  'BRANCH_RETURNED',
  'BRANCH_RETURN_CHANGED',
  'BRANCH_DISPOSITION_CHANGED',
  'BRANCH_RESUMED',
  'BRANCH_REOPENED',
  'ASSESSMENT_RECORDED',
  'RECOMMENDATION_RECORDED',
  'CONTENT_ASSOCIATED',
  'ARTIFACT_CHECKED',
  'ARTIFACT_REASSOCIATED',
  'PROPOSAL_DEFERRED',
  'PROPOSAL_RESUMED',
  'PROPOSAL_ADJUSTMENT_REQUESTED',
  'PROPOSAL_ADJUSTMENT_WITHDRAWN',
  'PROPOSAL_SUPERSEDED',
  'PROPOSAL_APPLIED',
] as const;
export const eventSummaryFields = {
  event_id: id,
  action: choices(eventActions),
  actor: choices(['USER', 'AI', 'PROGRAM']),
  reason: boundedText(1000),
  created_at: time,
};
export const eventSummary = shape(eventSummaryFields);
export const closureHead = shape({
  event_id: id,
  step_ref: stepRef,
  definition_version: id,
  goal_version: id,
  revision_id: id,
  command_message_id: id,
  next_step_ref: nullable(stepRef),
  result_count: count,
  issue_count: count,
  branch_count: count,
  items_digest: digest,
});
export const assessmentFields = {
  verdict: choices(['SUFFICIENT', 'GAPS_REMAIN', 'UNCERTAIN']),
  reason: boundedText(1000),
  goal_version: id,
  evaluated_step_version: id,
  evaluated_revision_id: id,
  coverage_block_ids: array(id, 100),
  source_refs: array(sourceRef, 100),
  assistant_message_id: id,
};
export const assessment = checked(
  shape({
    ...assessmentFields,
    validity: choices(['CURRENT', 'STALE']),
    stale_reason: nullable(choices(['GOAL_CHANGED', 'DEFINITION_CHANGED', 'COVERAGE_CHANGED'])),
  }),
  (value) => {
    require((value.validity === 'CURRENT') === (value.stale_reason === null));
    distinct(value.coverage_block_ids);
  },
);
const recommendationActions = [
  'DISCUSS',
  'WRITE',
  'RESOLVE_BRANCH',
  'REVIEW_CONTENT',
  'COMPLETE_STEP',
  'SWITCH_STEP',
  'NEED_MATERIAL',
] as const;
const stepBasis = shape({
  step_ref: stepRef,
  definition_version: id,
  status: choices(stepStatuses),
});
const entityBasis = (value: unknown) => {
  const kind = (value as { kind?: unknown })?.kind;
  if (kind === 'BRANCH')
    return shape({ kind: choices(['BRANCH']), ref: branchRef, semantic_digest: digest })(value);
  if (kind === 'ISSUE')
    return shape({ kind: choices(['ISSUE']), ref: issueRef, semantic_digest: digest })(value);
  return shape({ kind: choices(['ARTIFACT']), ref: artifactRef, semantic_digest: digest })(value);
};
export const recommendationBasis = checked(
  shape({
    schema: choices(['formation_recommendation_basis_v21_1']),
    goal_version: id,
    owner_step_ref: stepRef,
    owner_definition_version: id,
    owner_status: choices(stepStatuses),
    evaluated_revision_id: id,
    coverage: array(shape({ block_id: id, block_digest: digest }), 100),
    target_step: nullable(stepBasis),
    entity_basis: array(entityBasis, 100),
    relation_sets: array(
      shape({
        kind: choices(['OPEN_ISSUES', 'OPEN_BRANCHES', 'ACTIVE_ARTIFACTS']),
        step_ref: stepRef,
        digest,
      }),
      6,
    ),
    source_heads: array(shape({ source_ref: sourceRef, head_digest: digest }), 100),
  }),
  (value) => {
    distinct(value.coverage.map((row) => row.block_id));
    distinct(value.entity_basis.map((row) => row.kind + ':' + row.ref));
    distinct(value.relation_sets.map((row) => row.kind + ':' + row.step_ref));
    distinct(value.source_heads.map((row) => JSON.stringify(row.source_ref)));
  },
);
export const recommendationFields = {
  action: choices(recommendationActions),
  step_ref: nullable(stepRef),
  reason: boundedText(1000),
  source_refs: array(sourceRef, 100),
  assistant_message_id: id,
  basis: recommendationBasis,
};
export const recommendation = checked(
  shape({
    ...recommendationFields,
    validity: choices(['CURRENT', 'STALE']),
    stale_reason: nullable(
      choices([
        'GOAL_CHANGED',
        'OWNER_DEFINITION_CHANGED',
        'OWNER_STATE_CHANGED',
        'TARGET_CHANGED',
        'COVERAGE_CHANGED',
        'SOURCE_UNAVAILABLE',
        'RELATED_FACT_CHANGED',
      ]),
    ),
  }),
  (value) => require((value.validity === 'CURRENT') === (value.stale_reason === null)),
);
export const expectedResult = shape({
  result_ref: resultRef,
  description: boundedText(1000),
  kind: choices(['CONTENT', 'ANALYSIS']),
});
export const stepFields = {
  step_ref: stepRef,
  definition_version: id,
  title: boundedText(120),
  status: choices(stepStatuses),
  position: id,
  expected_results: array(expectedResult, 20, 1),
  relation_counts: shape({
    dependencies: count,
    replaces: count,
    topics: count,
    issues: count,
    branches: count,
    artifacts: count,
  }),
  last_event: nullable(eventSummary),
  assessment: nullable(assessment),
  recommendation: nullable(recommendation),
  availability: array(availability, 20),
};
function checkStep(value: {
  step_ref: string;
  expected_results: readonly { result_ref: string }[];
}) {
  distinct(value.expected_results.map((row) => row.result_ref));
  require(value.expected_results.every((row) => row.result_ref.startsWith(value.step_ref + '.o')));
}
export const stepView = checked(shape(stepFields), checkStep);
export const stepDetail = checked(
  shape({
    ...stepFields,
    closure: nullable(closureHead),
    sources: array(sourceStatus, unlimited),
  }),
  (value) => {
    checkStep(value);
    require(
      value.closure === null ||
        (value.status === 'COMPLETED' && value.closure.step_ref === value.step_ref),
    );
  },
);
export const branchView = shape({
  branch_ref: branchRef,
  origin_step_ref: stepRef,
  origin_event_ref: id,
  return_step_ref: stepRef,
  question: boundedText(1000),
  relevance: boundedText(1000),
  status: choices(branchStatuses),
  state_event_ref: id,
  topic_count: count,
  result_summary: nullable(boundedText(1000)),
  result_source_refs: array(sourceRef, unlimited),
  disposition_event_ref: nullable(id),
  availability: array(availability, 20),
});
export const issueView = shape({
  issue_ref: issueRef,
  step_ref: stepRef,
  branch_ref: nullable(branchRef),
  description: boundedText(1000),
  source_refs: array(sourceRef, unlimited),
  blocking: bool,
  disposition: choices(branchStatuses),
  disposition_reason: nullable(boundedText(1000)),
  resolution_source_refs: array(sourceRef, unlimited),
  disposition_event_ref: nullable(id),
  availability: array(availability, 20),
});
export const artifactFields = {
  artifact_ref: artifactRef,
  step_ref: stepRef,
  result_refs: array(resultRef, 20, 1),
  source_event_ref: id,
  origin_revision_id: id,
  origin_content_digest: digest,
  summary: boundedText(240),
  checked_against_revision_id: id,
  freshness: choices(['CURRENT', 'NEEDS_REVIEW', 'REMOVED']),
  review_reason: nullable(choices(['CHANGED', 'UNVERIFIABLE'])),
  origin_block_count: count,
  current_block_count: count,
  sources: array(sourceStatus, unlimited),
};
export const lineageFields = {
  predecessor_ref: nullable(artifactRef),
  predecessor_review_event_id: nullable(id),
  successor_ref: nullable(artifactRef),
  successor_review_event_id: nullable(id),
  is_active: bool,
};
export const artifactView = checked(shape({ ...lineageFields, ...artifactFields }), (value) => {
  require((value.predecessor_ref === null) === (value.predecessor_review_event_id === null));
  require((value.successor_ref === null) === (value.successor_review_event_id === null));
  require(value.is_active === (value.successor_ref === null));
  require((value.freshness === 'NEEDS_REVIEW') === (value.review_reason !== null));
  require(value.result_refs.every((row) => row.startsWith(value.step_ref + '.o')));
  distinct(value.result_refs);
});
export type FormationStep = ReturnType<typeof stepView>;
export type FormationStepDetail = ReturnType<typeof stepDetail>;
