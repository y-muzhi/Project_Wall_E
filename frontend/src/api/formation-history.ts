import { freezeFormationQuery } from './formation-reads.ts';
import { bool } from './decoding.ts';
import {
  stepStatuses,
  proposalRef,
  proposalStatuses,
  expectedResult,
  assessmentFields,
  recommendationFields,
} from './formation-values.ts';
/** Immutable event/closure reads never use the current formation version as authority. */
import { object } from './client.ts';
import type { ApiClient } from './client.ts';
import {
  array,
  checked,
  choices,
  count,
  distinct,
  id,
  nullable,
  require,
  shape,
} from './decoding.ts';
import type { Decoder } from './decoding.ts';
import { FORMATION_READ_ERRORS } from './formation-errors.ts';
import {
  artifactRef,
  boundedText,
  branchRef,
  branchStatuses,
  closureHead,
  digest,
  eventSummaryFields,
  issueRef,
  resultRef,
  stepRef,
  versionBasis,
} from './formation-values.ts';
import { sourceRef as sharedSourceRef } from './models.ts';
import { formationPagePagination } from './formation-reads.ts';

export type HistoryQuery = Readonly<{ limit?: number; cursor?: string }>;
export type EventQuery = HistoryQuery & Readonly<{ step_ref?: string; branch_ref?: string }>;
const kinds = ['RESULT', 'ISSUE', 'BRANCH'] as const;
export type ClosureKind = (typeof kinds)[number];
function parameters(query: HistoryQuery, extra: Readonly<Record<string, Decoder<unknown>>> = {}) {
  const fields: Readonly<Record<string, Decoder<unknown>>> = {
    limit: checked(id, (value) => require(value <= 100)),
    cursor: boundedText(4096),
    ...extra,
  };
  return Object.entries(object(query)).map(([name, value]) => {
    const decode = fields[name];
    require(decode !== undefined);
    return [name, String(decode(value))] as const;
  });
}
const location = (requirementId: number, documentId: number) =>
  '/api/v1/requirements/' + id(requirementId) + '/documents/' + id(documentId) + '/formation';
function ordered(items: readonly { ordinal: number }[]) {
  for (let index = 1; index < items.length; index++)
    require(items[index]!.ordinal > items[index - 1]!.ordinal);
}
export const eventView = checked(
  shape({
    ...eventSummaryFields,
    schema: choices(['formation_event_v1']),
    document_id: id,
    batch_ref: id,
    ordinal: id,
    batch_size: id,
    version_before: versionBasis,
    version_after: versionBasis,
    change_count: count,
    closure: nullable(closureHead),
  }),
  (value) => {
    require(value.ordinal <= value.batch_size);
    require(value.closure === null || value.closure.event_id === value.event_id);
  },
);
export async function readFormationEvents(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  query: EventQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const response = await client.readFormation(
    location(requirementId, documentId) + '/events',
    checked(
      shape({
        document_id: id,
        upper_event_id: nullable(id),
        total: count,
        items: array(eventView, 100),
      }),
      (value) => {
        require(value.document_id === documentId);
        require(value.upper_event_id !== null || (value.total === 0 && value.items.length === 0));
        distinct(value.items.map((row) => row.event_id));
        for (let index = 0; index < value.items.length; index++) {
          const row = value.items[index]!;
          require(
            row.document_id === documentId &&
              value.upper_event_id !== null &&
              row.event_id <= value.upper_event_id,
          );
          if (index) require(value.items[index - 1]!.event_id > row.event_id);
        }
      },
    ),
    parameters(query, { step_ref: stepRef, branch_ref: branchRef }),
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}
const resultItem = checked(
  shape({
    kind: choices(['RESULT']),
    ordinal: id,
    result_ref: resultRef,
    description: boundedText(1000),
    result_kind: choices(['CONTENT', 'ANALYSIS']),
    status: choices(['LANDED', 'ANALYZED', 'OUTSTANDING']),
    artifact_count: count,
    range_count: count,
    source_count: count,
    evidence_count: count,
    evidence_digest: digest,
  }),
  (row) => require(row.evidence_count === row.artifact_count + row.range_count + row.source_count),
);
const dispositionFields = {
  ordinal: id,
  description: boundedText(1000),
  state_at_close: choices(branchStatuses),
  disposition: choices(['KEEP_OPEN', 'TRANSFER', 'DEFERRED', 'DROPPED', 'RESOLVED']),
  to_step_ref: nullable(stepRef),
  reason: nullable(boundedText(1000)),
  source_count: count,
  evidence_count: count,
  evidence_digest: digest,
};
const issueItem = shape({ ...dispositionFields, kind: choices(['ISSUE']), ref: issueRef });
const branchItem = shape({ ...dispositionFields, kind: choices(['BRANCH']), ref: branchRef });
type ClosureItem =
  ReturnType<typeof resultItem> | ReturnType<typeof issueItem> | ReturnType<typeof branchItem>;
function closureItem(kind: ClosureKind): Decoder<ClosureItem> {
  switch (kind) {
    case 'RESULT':
      return resultItem;
    case 'ISSUE':
      return issueItem;
    case 'BRANCH':
      return branchItem;
  }
}
export async function readFormationClosure(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  eventId: number,
  kind: ClosureKind,
  query: HistoryQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  choices(kinds)(kind);
  const response = await client.readFormation(
    location(requirementId, documentId) + '/events/' + id(eventId) + '/closure-items',
    checked(
      shape({
        document_id: id,
        event_id: id,
        closure: closureHead,
        kind: choices([kind]),
        total: count,
        items: array(closureItem(kind), 100),
      }),
      (value) => {
        require(
          value.document_id === documentId &&
            value.event_id === eventId &&
            value.closure.event_id === eventId,
        );
        const total =
          kind === 'RESULT'
            ? value.closure.result_count
            : kind === 'ISSUE'
              ? value.closure.issue_count
              : value.closure.branch_count;
        require(value.total === total);
        ordered(value.items);
        distinct(value.items.map((row) => ('ref' in row ? row.ref : row.result_ref)));
        for (const row of value.items)
          if ('result_ref' in row)
            require(row.result_ref.startsWith(value.closure.step_ref + '.o'));
      },
    ),
    [...parameters(query), ['kind', kind]],
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}
const artifactEvidence = checked(
  shape({
    kind: choices(['ARTIFACT']),
    ordinal: id,
    artifact_ref: artifactRef,
    source_event_ref: id,
    origin_revision_id: id,
    checked_against_revision_id: id,
    freshness: choices(['CURRENT', 'NEEDS_REVIEW', 'REMOVED']),
    review_reason: nullable(choices(['CHANGED', 'UNVERIFIABLE'])),
    range_count: count,
    range_digest: digest,
  }),
  (value) => require((value.freshness === 'NEEDS_REVIEW') === (value.review_reason !== null)),
);
const rangeEvidence = shape({
  kind: choices(['RANGE']),
  ordinal: id,
  artifact_ref: artifactRef,
  role: choices(['ORIGIN', 'CURRENT']),
  revision_id: id,
  block_id: id,
  block_digest: digest,
});
const sourceEvidence = shape({
  kind: choices(['SOURCE']),
  ordinal: id,
  source_ref: sharedSourceRef,
});
const evidenceItem = (value: unknown) => {
  switch (object(value).kind) {
    case 'ARTIFACT':
      return artifactEvidence(value);
    case 'RANGE':
      return rangeEvidence(value);
    case 'SOURCE':
      return sourceEvidence(value);
    default:
      throw new TypeError('Unknown immutable evidence kind');
  }
};
export async function readFormationClosureEvidence(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  eventId: number,
  kind: ClosureKind,
  itemRef: string,
  query: HistoryQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  choices(kinds)(kind);
  (kind === 'RESULT' ? resultRef : kind === 'ISSUE' ? issueRef : branchRef)(itemRef);
  const response = await client.readFormation(
    location(requirementId, documentId) +
      '/events/' +
      id(eventId) +
      '/closure-items/' +
      kind +
      '/' +
      itemRef +
      '/evidence',
    checked(
      shape({
        document_id: id,
        event_id: id,
        owner_kind: choices([kind]),
        item_ref: kind === 'RESULT' ? resultRef : kind === 'ISSUE' ? issueRef : branchRef,
        total: count,
        digest,
        items: array(evidenceItem, 100),
      }),
      (value) => {
        require(
          value.document_id === documentId &&
            value.event_id === eventId &&
            value.item_ref === itemRef,
        );
        ordered(value.items);
        if (kind !== 'RESULT') require(value.items.every((row) => row.kind === 'SOURCE'));
      },
    ),
    parameters(query),
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}

// Scalar snapshots and relation members are decoded from their original event only.
const stepSnapshot = shape({
  step_ref: stepRef,
  definition_version: id,
  title: boundedText(120),
  status: choices(stepStatuses),
  position: id,
  next_result_no: id,
  closure_event_ref: nullable(id),
});
const issueSnapshot = shape({
  issue_ref: issueRef,
  step_ref: stepRef,
  branch_ref: nullable(branchRef),
  description: boundedText(1000),
  blocking: bool,
  disposition: choices(branchStatuses),
  disposition_reason: nullable(boundedText(1000)),
  disposition_event_ref: nullable(id),
});
const branchSnapshot = shape({
  branch_ref: branchRef,
  origin_step_ref: stepRef,
  origin_event_ref: id,
  return_step_ref: stepRef,
  question: boundedText(1000),
  relevance: boundedText(1000),
  status: choices(branchStatuses),
  state_event_ref: id,
  result_summary: nullable(boundedText(1000)),
  disposition_event_ref: nullable(id),
});
const artifactSnapshot = checked(
  shape({
    artifact_ref: artifactRef,
    step_ref: stepRef,
    source_event_ref: id,
    origin_revision_id: id,
    origin_content_digest: digest,
    summary: boundedText(240),
    checked_against_revision_id: id,
    freshness: choices(['CURRENT', 'NEEDS_REVIEW', 'REMOVED']),
    review_reason: nullable(choices(['CHANGED', 'UNVERIFIABLE'])),
  }),
  (row) => require((row.freshness === 'NEEDS_REVIEW') === (row.review_reason !== null)),
);
const withdrawal = shape({
  proposal: proposalRef,
  publication_binding_digest: digest,
  expected_semantic_digest: digest,
  observed_semantic_digest: digest,
  checked_versions: versionBasis,
  check_kind: choices(['WITHDRAW_ADJUSTMENT']),
  result: choices(['MATCHED']),
  command_message_id: id,
});
const artifactReview = shape({
  reviewed_artifact_ref: artifactRef,
  replacement_artifact_ref: nullable(artifactRef),
  result: choices(['MATCHED', 'REASSOCIATED', 'UNVERIFIED', 'REMOVED']),
  checked_against_revision_id: id,
  assistant_message_id: id,
  source_refs: array(sharedSourceRef, 100),
});
function change<const K extends string, T>(kind: K, decode: Decoder<T>, appendOnly = false) {
  return checked(
    shape({
      ordinal: id,
      entity_kind: choices([kind]),
      entity_ref: boundedText(160),
      before: nullable(decode),
      after: nullable(decode),
      member_changes: shape({ count, digest }),
    }),
    (row) => {
      require(row.before !== null || row.after !== null);
      if (appendOnly) require(row.before === null && row.after !== null);
    },
  );
}
const changes = {
  STEP: change('STEP', stepSnapshot),
  GOAL: change('GOAL', shape({ version: id, text: boundedText(1000) })),
  RESULT: change('RESULT', expectedResult),
  ISSUE: change('ISSUE', issueSnapshot),
  BRANCH: change('BRANCH', branchSnapshot),
  ARTIFACT: change('ARTIFACT', artifactSnapshot),
  ORDER: change('ORDER', shape({ step_ref: stepRef, position: id })),
  RESULT_ROUTE: change(
    'RESULT_ROUTE',
    shape({
      from_result_ref: resultRef,
      disposition: choices(['REPLACED', 'NOT_REQUIRED']),
      target_result_refs: array(resultRef, Number.MAX_SAFE_INTEGER),
      reason: boundedText(1000),
    }),
  ),
  ASSESSMENT: change('ASSESSMENT', shape(assessmentFields)),
  RECOMMENDATION: change('RECOMMENDATION', shape(recommendationFields)),
  PROPOSAL: change(
    'PROPOSAL',
    shape({
      proposal: proposalRef,
      disposition: choices(proposalStatuses),
      needs_revision: bool,
      binding_digest: digest,
    }),
  ),
  PROPOSAL_CHECK: change('PROPOSAL_CHECK', withdrawal, true),
  ARTIFACT_REVIEW: change('ARTIFACT_REVIEW', artifactReview, true),
};
const changeKinds = [
  'STEP',
  'GOAL',
  'RESULT',
  'ISSUE',
  'BRANCH',
  'ARTIFACT',
  'ORDER',
  'RESULT_ROUTE',
  'ASSESSMENT',
  'RECOMMENDATION',
  'PROPOSAL',
  'PROPOSAL_CHECK',
  'ARTIFACT_REVIEW',
] as const;
export const entityChange = (value: unknown) =>
  changes[choices(changeKinds)(object(value).entity_kind)](value);
export async function readFormationChanges(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  eventId: number,
  query: HistoryQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const response = await client.readFormation(
    location(requirementId, documentId) + '/events/' + id(eventId) + '/changes',
    checked(
      shape({ document_id: id, event_id: id, total: count, items: array(entityChange, 100) }),
      (value) => {
        require(value.document_id === documentId && value.event_id === eventId);
        ordered(value.items);
        distinct(value.items.map((row) => row.entity_kind + ':' + row.entity_ref));
      },
    ),
    parameters(query),
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}
const sourceCollections = [
  'GOAL_SOURCE',
  'ISSUE_SOURCE',
  'ISSUE_RESOLUTION_SOURCE',
  'BRANCH_RESULT_SOURCE',
] as const;
const rangeCollections = ['ORIGIN_RANGE', 'CURRENT_RANGE'] as const;
const refCollections = [
  'DEPENDENCY',
  'REPLACES',
  'TOPIC',
  'BRANCH_TOPIC',
  'ARTIFACT_RESULT',
] as const;
function member<const K extends readonly string[], T>(collections: K, decode: Decoder<T>) {
  return checked(
    shape({
      ordinal: id,
      collection: choices(collections),
      member_key: boundedText(240),
      before: nullable(decode),
      after: nullable(decode),
    }),
    (row) => require(row.before !== null || row.after !== null),
  );
}
const sourceMember = member(
  sourceCollections,
  shape({ kind: choices(['SOURCE']), source_ref: sharedSourceRef }),
);
const rangeMember = member(
  rangeCollections,
  shape({ kind: choices(['RANGE']), revision_id: id, block_id: id, block_digest: digest }),
);
const stepMember = member(
  ['DEPENDENCY', 'REPLACES'] as const,
  shape({ kind: choices(['REF']), ref: stepRef }),
);
const resultMember = member(
  ['ARTIFACT_RESULT'] as const,
  shape({ kind: choices(['REF']), ref: resultRef }),
);
const topicMember = member(
  ['TOPIC', 'BRANCH_TOPIC'] as const,
  shape({ kind: choices(['REF']), ref: boundedText(200) }),
);
export const memberDelta = (value: unknown) => {
  const collection = choices([...sourceCollections, ...rangeCollections, ...refCollections])(
    object(value).collection,
  );
  switch (collection) {
    case 'GOAL_SOURCE':
    case 'ISSUE_SOURCE':
    case 'ISSUE_RESOLUTION_SOURCE':
    case 'BRANCH_RESULT_SOURCE':
      return sourceMember(value);
    case 'ORIGIN_RANGE':
    case 'CURRENT_RANGE':
      return rangeMember(value);
    case 'DEPENDENCY':
    case 'REPLACES':
      return stepMember(value);
    case 'ARTIFACT_RESULT':
      return resultMember(value);
    case 'TOPIC':
    case 'BRANCH_TOPIC':
      return topicMember(value);
  }
};
export async function readFormationMembers(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  eventId: number,
  changeOrdinal: number,
  query: HistoryQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const response = await client.readFormation(
    location(requirementId, documentId) +
      '/events/' +
      id(eventId) +
      '/changes/' +
      id(changeOrdinal) +
      '/members',
    checked(
      shape({
        document_id: id,
        event_id: id,
        change_ordinal: id,
        total: count,
        digest,
        items: array(memberDelta, 100),
      }),
      (value) => {
        require(
          value.document_id === documentId &&
            value.event_id === eventId &&
            value.change_ordinal === changeOrdinal,
        );
        ordered(value.items);
        distinct(value.items.map((row) => row.collection + ':' + row.member_key));
      },
    ),
    parameters(query),
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}
