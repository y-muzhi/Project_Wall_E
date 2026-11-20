import { proposalView } from './formation-workflow.ts';
import { proposalStatuses } from './formation-values.ts';
/** Registered V2.1 current reads. Cursor bytes are opaque and never become authority. */
import { ApiUnknown, object } from './client.ts';
import type { ApiClient, ApiSuccess, FormationCursorPagination } from './client.ts';
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
  artifactView,
  boundedText,
  branchRef,
  branchStatuses,
  branchView,
  digest,
  issueView,
  lineageFields,
  stepDetail,
  stepRef,
  stepStatuses,
  stepView,
} from './formation-values.ts';

export function freezeFormationQuery<T extends object>(query: T): T {
  object(query);
  return Object.freeze({ ...query });
}

export type PageQuery = Readonly<{ limit?: number; cursor?: string; known_f?: number }>;
export type StepQuery = PageQuery &
  Readonly<{ state?: (typeof stepStatuses)[number]; include_cancelled?: boolean }>;
export type BranchQuery = PageQuery &
  Readonly<{ state?: (typeof branchStatuses)[number]; step_ref?: string }>;
export type IssueQuery = BranchQuery & Readonly<{ branch_ref?: string }>;
export type ArtifactQuery = PageQuery &
  Readonly<{
    state?: 'CURRENT' | 'NEEDS_REVIEW' | 'REMOVED';
    step_ref?: string;
    include_superseded?: boolean;
  }>;
export type ProposalQuery = PageQuery & Readonly<{ state?: (typeof proposalStatuses)[number] }>;
export type FormationPage<T> = Readonly<{
  document_id: number;
  formation_version: number;
  kind: string;
  items: readonly T[];
  total: number;
}>;
export type FormationPageResult<T> = ApiSuccess<FormationPage<T>, FormationCursorPagination> &
  Readonly<{ meta: { request_id: string; pagination: FormationCursorPagination } }>;

function location(requirementId: number, documentId: number) {
  return (
    '/api/v1/requirements/' + id(requirementId) + '/documents/' + id(documentId) + '/formation'
  );
}
function queryParameters(
  query: PageQuery,
  extras: Readonly<Record<string, Decoder<unknown>>> = {},
) {
  const item = object(query);
  const parsers: Readonly<Record<string, Decoder<unknown>>> = {
    limit: checked(id, (value) => require(value <= 100)),
    cursor: boundedText(4096),
    known_f: id,
    ...extras,
  };
  const output: [string, string][] = [];
  for (const [name, value] of Object.entries(item)) {
    const decode = parsers[name];
    require(decode !== undefined);
    output.push([name, String(decode(value))]);
  }
  return output;
}
const boolean = (value: unknown) => {
  require(typeof value === 'boolean');
  return value;
};
const artifactStates = ['CURRENT', 'NEEDS_REVIEW', 'REMOVED'] as const;

async function page<T>(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  kind: string,
  query: PageQuery,
  parameters: readonly (readonly [string, string])[],
  decode: Decoder<T>,
  identity: (value: T) => string,
  signal?: AbortSignal,
): Promise<FormationPageResult<T>> {
  const response = await client.readFormation(
    location(requirementId, documentId) + '/' + kind,
    checked(
      shape({
        document_id: id,
        formation_version: id,
        kind: choices([kind]),
        items: array(decode, 100),
        total: count,
      }),
      (value) => {
        require(value.document_id === documentId);
        require(query.known_f === undefined || value.formation_version === query.known_f);
        distinct(value.items.map(identity));
      },
    ),
    parameters,
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}
export function readFormationSteps(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  query: StepQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const parameters = queryParameters(query, {
    state: choices(stepStatuses),
    include_cancelled: boolean,
  });
  return page(
    client,
    requirementId,
    documentId,
    'steps',
    query,
    parameters,
    stepView,
    (row) => row.step_ref,
    signal,
  );
}
export function readFormationBranches(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  query: BranchQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const parameters = queryParameters(query, { state: choices(branchStatuses), step_ref: stepRef });
  return page(
    client,
    requirementId,
    documentId,
    'branches',
    query,
    parameters,
    branchView,
    (row) => row.branch_ref,
    signal,
  );
}
export function readFormationIssues(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  query: IssueQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const parameters = queryParameters(query, {
    state: choices(branchStatuses),
    step_ref: stepRef,
    branch_ref: branchRef,
  });
  return page(
    client,
    requirementId,
    documentId,
    'issues',
    query,
    parameters,
    issueView,
    (row) => row.issue_ref,
    signal,
  );
}
export function readFormationArtifacts(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  query: ArtifactQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const parameters = queryParameters(query, {
    state: choices(artifactStates),
    step_ref: stepRef,
    include_superseded: boolean,
  });
  return page(
    client,
    requirementId,
    documentId,
    'artifacts',
    query,
    parameters,
    artifactView,
    (row) => row.artifact_ref,
    signal,
  );
}
export function readFormationProposals(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  query: ProposalQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  const parameters = queryParameters(query, { state: choices(proposalStatuses) });
  const decode = checked(proposalView, (row) =>
    require(query.state === undefined || row.disposition === query.state),
  );
  return page(
    client,
    requirementId,
    documentId,
    'proposals',
    query,
    parameters,
    decode,
    (row) => row.message_id + ':' + row.card_key,
    signal,
  );
}
async function detail<T>(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  path: string,
  decode: Decoder<T>,
  knownF?: number,
  signal?: AbortSignal,
) {
  const result = await client.readFormation(
    location(requirementId, documentId) + path,
    decode,
    knownF === undefined ? [] : [['known_f', String(id(knownF))]],
    signal,
    FORMATION_READ_ERRORS,
  );
  if (result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
export function readFormationStep(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  ref: string,
  knownF?: number,
  signal?: AbortSignal,
) {
  stepRef(ref);
  return detail(
    client,
    requirementId,
    documentId,
    '/steps/' + ref,
    checked(stepDetail, (value) => require(value.step_ref === ref)),
    knownF,
    signal,
  );
}
export function readFormationArtifact(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  ref: string,
  knownF?: number,
  signal?: AbortSignal,
) {
  artifactRef(ref);
  return detail(
    client,
    requirementId,
    documentId,
    '/artifacts/' + ref,
    checked(artifactView, (value) => require(value.artifact_ref === ref)),
    knownF,
    signal,
  );
}
export const relationKinds = [
  'DEPENDENCY',
  'REPLACES',
  'TOPIC',
  'ISSUE',
  'BRANCH',
  'ARTIFACT',
] as const;
export type RelationKind = (typeof relationKinds)[number];
export type RelationQuery = PageQuery &
  Readonly<{
    relation_kind: RelationKind;
    state?: string;
    branch_ref?: string;
    include_superseded?: boolean;
  }>;
function relationDecoder(kind: RelationKind, owner: string) {
  switch (kind) {
    case 'DEPENDENCY':
    case 'REPLACES':
      return checked(
        shape({
          relation_kind: choices([kind]),
          from_step_ref: stepRef,
          to_step_ref: stepRef,
        }),
        (row) => require(row.from_step_ref === owner),
      );
    case 'TOPIC':
      return checked(
        shape({
          relation_kind: choices(['TOPIC']),
          step_ref: stepRef,
          topic_ref: boundedText(200),
        }),
        (row) => require(row.step_ref === owner),
      );
    case 'ISSUE':
      return checked(
        shape({ relation_kind: choices(['ISSUE']), step_ref: stepRef, issue: issueView }),
        (row) => require(row.step_ref === owner && row.issue.step_ref === owner),
      );
    case 'BRANCH':
      return checked(
        shape({ relation_kind: choices(['BRANCH']), step_ref: stepRef, branch: branchView }),
        (row) => require(row.step_ref === owner && row.branch.return_step_ref === owner),
      );
    case 'ARTIFACT':
      return checked(
        shape({ relation_kind: choices(['ARTIFACT']), step_ref: stepRef, artifact: artifactView }),
        (row) => require(row.step_ref === owner && row.artifact.step_ref === owner),
      );
  }
}
type RelationItem = ReturnType<ReturnType<typeof relationDecoder>>;
function relationIdentity(value: RelationItem): string {
  if ('to_step_ref' in value) return value.to_step_ref;
  if ('topic_ref' in value) return value.topic_ref;
  if ('issue' in value) return value.issue.issue_ref;
  if ('branch' in value) return value.branch.branch_ref;
  return value.artifact.artifact_ref;
}
export function readFormationRelations(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  owner: string,
  query: RelationQuery,
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  stepRef(owner);
  const kind = choices(relationKinds)(query.relation_kind);
  const extra: Record<string, Decoder<unknown>> = { relation_kind: choices(relationKinds) };
  if (kind === 'ISSUE' || kind === 'BRANCH') extra.state = choices(branchStatuses);
  if (kind === 'ARTIFACT') {
    extra.state = choices(artifactStates);
    extra.include_superseded = boolean;
  }
  if (kind === 'ISSUE') extra.branch_ref = branchRef;
  const parameters = queryParameters(query, extra);
  const decode: Decoder<RelationItem> = relationDecoder(kind, owner);
  // Relation routing uses an owner path, whereas the page's kind remains 'relations'.
  return relationPage(client, requirementId, documentId, owner, query, parameters, decode, signal);
}
async function relationPage(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  owner: string,
  query: PageQuery,
  parameters: readonly (readonly [string, string])[],
  decode: Decoder<RelationItem>,
  signal?: AbortSignal,
) {
  const response = await client.readFormation(
    location(requirementId, documentId) + '/steps/' + owner + '/relations',
    checked(
      shape({
        document_id: id,
        formation_version: id,
        kind: choices(['relations']),
        items: array(decode, 100),
        total: count,
      }),
      (value) => {
        require(
          value.document_id === documentId &&
            (query.known_f === undefined || value.formation_version === query.known_f),
        );
        distinct(value.items.map(relationIdentity));
      },
    ),
    parameters,
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}

export function formationPagePagination<T extends { items: readonly unknown[]; total: number }>(
  response: ApiSuccess<T, FormationCursorPagination>,
  query: PageQuery,
): FormationCursorPagination {
  try {
    const pagination = response.meta.pagination,
      limit = query.limit ?? 20;
    require(pagination !== undefined && pagination.page_size === limit);
    require(response.data.items.length <= limit);
    require(!pagination.has_more || response.data.items.length === limit);
    require(response.data.items.length <= response.data.total);
    if (query.cursor === undefined) {
      require(response.data.items.length === Math.min(limit, response.data.total));
      require(pagination.has_more === response.data.items.length < response.data.total);
    }
    return pagination;
  } catch {
    throw new ApiUnknown(false);
  }
}
export function readFormationRanges(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  artifact: string,
  role: 'ORIGIN' | 'CURRENT',
  query: PageQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  artifactRef(artifact);
  choices(['ORIGIN', 'CURRENT'])(role);
  return rangesPage(client, requirementId, documentId, artifact, role, query, signal);
}
async function rangesPage(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  artifact: string,
  role: 'ORIGIN' | 'CURRENT',
  query: PageQuery,
  signal?: AbortSignal,
) {
  const parameters = [...queryParameters(query), ['role', role] as const];
  const response = await client.readFormation(
    location(requirementId, documentId) + '/artifacts/' + artifact + '/ranges',
    checked(
      shape({
        document_id: id,
        formation_version: id,
        artifact_ref: artifactRef,
        role: choices(['ORIGIN', 'CURRENT']),
        total: count,
        items: array(
          shape({ ordinal: id, revision_id: id, block_id: id, block_digest: digest }),
          100,
        ),
      }),
      (value) => {
        require(
          value.document_id === documentId &&
            value.artifact_ref === artifact &&
            value.role === role,
        );
        require(query.known_f === undefined || value.formation_version === query.known_f);
        for (let index = 1; index < value.items.length; index++)
          require(value.items[index]!.ordinal > value.items[index - 1]!.ordinal);
      },
    ),
    parameters,
    signal,
    FORMATION_READ_ERRORS,
  );
  return {
    ...response,
    meta: { ...response.meta, pagination: formationPagePagination(response, query) },
  };
}
const lineageItem = checked(
  shape({
    artifact_ref: artifactRef,
    ...lineageFields,
    freshness: choices(artifactStates),
    review_reason: nullable(choices(['CHANGED', 'UNVERIFIABLE'])),
  }),
  (value) => {
    require((value.predecessor_ref === null) === (value.predecessor_review_event_id === null));
    require((value.successor_ref === null) === (value.successor_review_event_id === null));
    require(value.is_active === (value.successor_ref === null));
    require((value.freshness === 'NEEDS_REVIEW') === (value.review_reason !== null));
  },
);
export async function readFormationLineage(
  client: ApiClient,
  requirementId: number,
  documentId: number,
  artifact: string,
  query: PageQuery = {},
  signal?: AbortSignal,
) {
  query = freezeFormationQuery(query);
  artifactRef(artifact);
  const parameters = queryParameters(query);
  const response = await client.readFormation(
    location(requirementId, documentId) + '/artifacts/' + artifact + '/lineage',
    checked(
      shape({
        document_id: id,
        formation_version: id,
        anchor_ref: artifactRef,
        total: count,
        items: array(lineageItem, 100),
      }),
      (value) => {
        require(value.document_id === documentId && value.anchor_ref === artifact);
        require(query.known_f === undefined || value.formation_version === query.known_f);
        distinct(value.items.map((row) => row.artifact_ref));
        for (let index = 1; index < value.items.length; index++) {
          const row = value.items[index]!,
            previous = value.items[index - 1]!;
          require(
            row.predecessor_ref === previous.artifact_ref &&
              previous.successor_ref === row.artifact_ref,
          );
          require(row.predecessor_review_event_id === previous.successor_review_event_id);
        }
      },
    ),
    parameters,
    signal,
    FORMATION_READ_ERRORS,
  );
  const pagination = formationPagePagination(response, query);
  try {
    const items = response.data.items;
    if (items.length && query.cursor === undefined) require(items[0]!.predecessor_ref === null);
    if (items.length) require(pagination.has_more === !items[items.length - 1]!.is_active);
  } catch {
    throw new ApiUnknown(false);
  }
  return { ...response, meta: { ...response.meta, pagination } };
}
