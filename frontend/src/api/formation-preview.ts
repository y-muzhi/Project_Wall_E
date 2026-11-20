/** Strict read-only preview projection. Temporary labels are never resolved identities. */
import contract from '../../../backend/resources/v27/schemas/collaboration-contract.v15.json' with { type: 'json' };
import { object, snapshotObject } from './client.ts';
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
} from './decoding.ts';
import type { Decoder } from './decoding.ts';
import {
  artifactRef,
  boundedText,
  branchRef,
  branchStatuses,
  digest,
  issueRef,
  resultRef,
  stepRef,
  stepStatuses,
} from './formation-values.ts';
import { validateDefinition } from './resource-schema.ts';
const pathStep = (value: unknown) => {
  validateDefinition('PathStepRef', value, contract.$defs);
  return boundedText(36)(value);
};
const pathResult = (value: unknown) => {
  validateDefinition('PathResultRef', value, contract.$defs);
  return boundedText(36)(value);
};
const unlimited = Number.MAX_SAFE_INTEGER;
const changes = [
  'SET_GOAL',
  'ADD_STEP',
  'RENAME_STEP',
  'MOVE_STEP',
  'SET_DEPENDENCIES',
  'UPDATE_RESULT',
  'ADD_RESULT',
  'CANCEL_STEP',
  'LINK_CONTENT',
  'MOVE_ISSUE',
  'SET_BRANCH_RETURN',
  'DISPOSE_ISSUE',
  'DISPOSE_BRANCH',
  'RESUME_ISSUE',
] as const;
const result = shape({
  result_ref: pathResult,
  description: boundedText(1000),
  kind: choices(['CONTENT', 'ANALYSIS']),
});
const entities = {
  STEP: shape({
    kind: choices(['STEP']),
    step_ref: pathStep,
    title: boundedText(120),
    status: choices(stepStatuses),
    position: id,
    expected_results: array(result, 20, 1),
  }),
  GOAL: shape({ kind: choices(['GOAL']), text: boundedText(1000) }),
  RESULT: shape({
    kind: choices(['RESULT']),
    result_ref: pathResult,
    description: boundedText(1000),
    result_kind: choices(['CONTENT', 'ANALYSIS']),
  }),
  ISSUE: shape({
    kind: choices(['ISSUE']),
    issue_ref: issueRef,
    step_ref: pathStep,
    disposition: choices(branchStatuses),
  }),
  BRANCH: shape({
    kind: choices(['BRANCH']),
    branch_ref: branchRef,
    origin_step_ref: stepRef,
    return_step_ref: pathStep,
    status: choices(branchStatuses),
  }),
  ARTIFACT: shape({
    kind: choices(['ARTIFACT']),
    artifact_ref: artifactRef,
    step_ref: stepRef,
    result_refs: array(resultRef, 20),
    freshness: choices(['CURRENT', 'NEEDS_REVIEW', 'REMOVED']),
  }),
  DEPENDENCIES: shape({
    kind: choices(['DEPENDENCIES']),
    step_ref: pathStep,
    dependencies: array(pathStep, unlimited),
  }),
  ARTIFACT_LINK: shape({
    kind: choices(['ARTIFACT_LINK']),
    step_ref: pathStep,
    result_refs: array(pathResult, 20),
    revision_id: id,
    block_ids: array(id, 100, 1),
  }),
};
export function previewEntity(value: unknown) {
  const kind = choices(Object.keys(entities) as (keyof typeof entities)[])(object(value).kind);
  return entities[kind](value);
}
function slice<T extends { ordinal: number }>(decode: Decoder<T>) {
  return checked(
    shape({
      items: array(decode, 100),
      total: count,
      has_more: bool,
      next_cursor: nullable(boundedText(4096)),
    }),
    (row) => {
      require(row.has_more === (row.next_cursor !== null));
      distinct(row.items.map((item) => item.ordinal));
      require(row.items.length <= row.total);
      for (let i = 1; i < row.items.length; i++)
        require(row.items[i]!.ordinal > row.items[i - 1]!.ordinal);
      const last = row.items.at(-1)?.ordinal ?? 0;
      require(last <= row.total);
      if (row.has_more) require(row.items.length > 0 && last < row.total);
    },
  );
}
const affected = checked(
  shape({
    ordinal: id,
    change_type: choices(changes),
    entity_ref: boundedText(160),
    before: nullable(previewEntity),
    after: nullable(previewEntity),
  }),
  (row) => require(row.before !== null || row.after !== null),
);
const warning = shape({
  ordinal: id,
  code: choices([
    'OUTSTANDING_CONTENT',
    'UNRESOLVED_ISSUE',
    'OPEN_BRANCH',
    'PROPOSAL_AFFECTED',
    'ASSESSMENT_STALE',
    'FOCUS_CLEARED',
  ]),
  step_ref: nullable(pathStep),
  related_ref: nullable(boundedText(160)),
  message: boundedText(1000),
});
const resultRoute = (value: unknown) => {
  validateDefinition('FormationResultRoute', value, contract.$defs);
  return snapshotObject(value);
};
const temp = (value: unknown) => {
  const ref = boundedText(36)(value);
  require(/^new_(step|result|issue|branch)_[1-9][0-9]*$/.test(ref));
  return ref;
};
export const pathPreview = checked(
  shape({
    document_id: id,
    discussion_version: id,
    formation_version: id,
    content_version: id,
    changes_digest: digest,
    affected_items: slice(affected),
    warnings: slice(warning),
    result_routes: array(resultRoute, unlimited),
    reference_map: array(shape({ temp_ref: temp, preview_label: boundedText(120) }), 420),
  }),
  (row) => distinct(row.reference_map.map((item) => item.temp_ref)),
);
export type FormationPathPreview = ReturnType<typeof pathPreview>;
export type PreviewOptions = Readonly<{
  section?: 'AFFECTED' | 'WARNINGS';
  limit?: number;
  cursor?: string;
}>;
