/** Strict, task-scoped reads of immutable candidate content identities. */
import { ApiUnknown, positiveInteger } from './client.ts';
import type { ApiClient } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { gitObjectId } from './code-repository-observations.ts';
import { comparePaths, relativePath } from './code-snapshots.ts';
import {
  bool,
  checked,
  choices,
  count,
  nonempty,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';

const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);

const candidate = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    base_snapshot_id: positiveInteger,
    capture_operation_id: positiveInteger,
    content_tree_oid: gitObjectId,
    parent_candidate_id: nullable(positiveInteger),
    role: choices(['BACKEND', 'FRONTEND', 'INTEGRATION'] as const),
    control_generation: positiveInteger,
    content_policy_version: choices(['CONTENT20-STORE-1'] as const),
    manifest_sha256: nonempty,
    captured_at: time,
    published_for_testing_at: nullable(time),
    publication_operation_id: nullable(positiveInteger),
    file_count: count,
    byte_count: count,
    created_at: time,
  }),
  (row) => {
    require(/^[0-9a-f]{64}$/.test(row.manifest_sha256));
    require(row.parent_candidate_id !== row.id && row.captured_at <= row.created_at);
    require((row.published_for_testing_at === null) === (row.publication_operation_id === null));
    require(
      row.published_for_testing_at === null || row.published_for_testing_at >= row.created_at,
    );
  },
);

export type CodeCandidate = ReturnType<typeof candidate>;

function path(taskId: number) {
  return '/api/v1/code-tasks/' + positiveInteger(taskId) + '/candidates';
}

export function readCodeCandidates(
  client: ApiClient,
  taskId: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    path(taskId),
    checked(candidate, (row) => require(row.task_id === taskId)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    errors,
  );
}

export async function readCodeCandidate(
  client: ApiClient,
  taskId: number,
  candidateId: number,
  signal?: AbortSignal,
) {
  const response = await client.read(
    path(taskId) + '/' + positiveInteger(candidateId),
    checked(candidate, (row) => require(row.task_id === taskId && row.id === candidateId)),
    [],
    signal,
    errors,
  );
  if (response.meta.pagination !== undefined) throw new ApiUnknown(false);
  return response;
}

const mode = choices(['100644', '100755']);
export const decodeCandidateDiff = checked(
  shape({
    path: relativePath,
    change: choices(['ADD', 'MODIFY', 'DELETE', 'MODE']),
    before_size: nullable(count),
    after_size: nullable(count),
    before_mode: nullable(mode),
    after_mode: nullable(mode),
    binary: bool,
  }),
  (row) => {
    require(
      (row.before_size === null) === (row.change === 'ADD') &&
        (row.after_size === null) === (row.change === 'DELETE') &&
        (row.before_size === null) === (row.before_mode === null) &&
        (row.after_size === null) === (row.after_mode === null),
    );
    if (row.change === 'MODE')
      require(row.before_mode !== row.after_mode && row.before_size === row.after_size);
  },
);
export type CodeCandidateDiff = ReturnType<typeof decodeCandidateDiff>;
const side = choices(['BEFORE', 'AFTER']);
export type CandidateComparisonSide = ReturnType<typeof side>;
const maxChunk = 65536;
const nullValue = (value: unknown) => {
  require(value === null);
  return null;
};
const chunkFields = {
  candidate_id: positiveInteger,
  path: relativePath,
  offset: count,
  length: count,
  total_bytes: count,
  content_base64: text,
  next_offset: nullable(count),
};
const fileChunk = shape(chunkFields);
const comparisonFields = {
  ...chunkFields,
  side,
  exists: bool,
  total_bytes: nullable(count),
  content_base64: nullable(text),
};
const comparisonChunk = shape({ ...comparisonFields, delivery_plan_id: nullValue });
const planChunk = shape({ ...comparisonFields, delivery_plan_id: positiveInteger });
export type CandidateComparisonChunk = ReturnType<typeof comparisonChunk>;

function candidatePath(taskId: number, candidateId: number) {
  return path(taskId) + '/' + positiveInteger(candidateId);
}

export async function readCandidateDiff(
  client: ApiClient,
  taskId: number,
  candidateId: number,
  page: number,
  signal?: AbortSignal,
) {
  const result = await readPage(
    client,
    candidatePath(taskId, candidateId) + '/diff',
    decodeCandidateDiff,
    (row) => row.path,
    [['page', String(page)]],
    page,
    signal,
    errors,
  );
  const encoder = new TextEncoder();
  const paths = result.data.items.map((row) => encoder.encode(row.path));
  if (paths.some((value, index) => index > 0 && comparePaths(paths[index - 1]!, value) >= 0))
    throw new ApiUnknown(false);
  return result;
}

export function decodeCandidateBytes(value: string): Uint8Array {
  require(value.length <= Math.ceil(maxChunk / 3) * 4);
  const raw = atob(value);
  require(btoa(raw) === value);
  return Uint8Array.from(raw, (byte) => byte.charCodeAt(0));
}

function checkChunk(
  row: ReturnType<typeof fileChunk> | Omit<CandidateComparisonChunk, 'delivery_plan_id'>,
  candidateId: number,
  file: string,
  offset: number,
  length: number,
) {
  require(row.candidate_id === candidateId && row.path === file && row.offset === offset);
  if ('exists' in row && !row.exists) {
    require(
      row.length === 0 &&
        row.total_bytes === null &&
        row.content_base64 === null &&
        row.next_offset === null,
    );
    return;
  }
  require(row.total_bytes !== null && row.content_base64 !== null);
  const actualLength = Math.min(Math.max(0, row.total_bytes - offset), length);
  const following = offset + actualLength;
  require(
    row.length === actualLength &&
      decodeCandidateBytes(row.content_base64).length === actualLength &&
      row.next_offset === (following < row.total_bytes ? following : null),
  );
}

function chunkQuery(file: string, offset: number, length: number) {
  require(positiveInteger(length) <= maxChunk);
  return [
    ['path', relativePath(file)],
    ['offset', String(count(offset))],
    ['length', String(length)],
  ] as const;
}

export async function readCandidateFile(
  client: ApiClient,
  taskId: number,
  candidateId: number,
  file: string,
  offset: number,
  length: number,
  signal?: AbortSignal,
) {
  const response = await client.read(
    candidatePath(taskId, candidateId) + '/file',
    checked(fileChunk, (row) => checkChunk(row, candidateId, file, offset, length)),
    chunkQuery(file, offset, length),
    signal,
    errors,
  );
  if (response.meta.pagination !== undefined) throw new ApiUnknown(false);
  return response;
}

export async function readCandidateComparison(
  client: ApiClient,
  taskId: number,
  candidateId: number,
  file: string,
  comparisonSide: CandidateComparisonSide,
  offset: number,
  length: number,
  signal?: AbortSignal,
) {
  const response = await client.read(
    candidatePath(taskId, candidateId) + '/diff/file',
    checked(comparisonChunk, (row) => {
      require(row.side === comparisonSide);
      checkChunk(row, candidateId, file, offset, length);
    }),
    [...chunkQuery(file, offset, length), ['side', side(comparisonSide)]],
    signal,
    errors,
  );
  if (response.meta.pagination !== undefined) throw new ApiUnknown(false);
  return response;
}

export async function readPlanComparison(
  client: ApiClient,
  task: number,
  plan: number,
  candidate: number,
  file: string,
  comparisonSide: CandidateComparisonSide,
  offset: number,
  length: number,
  signal?: AbortSignal,
) {
  const response = await client.read(
    '/api/v1/code-tasks/' +
      positiveInteger(task) +
      '/delivery-plans/' +
      positiveInteger(plan) +
      '/file',
    checked(planChunk, (row) => {
      require(row.side === comparisonSide && row.delivery_plan_id === plan);
      checkChunk(row, candidate, file, offset, length);
    }),
    [...chunkQuery(file, offset, length), ['side', side(comparisonSide)]],
    signal,
    errors,
  );
  if (response.meta.pagination !== undefined) throw new ApiUnknown(false);
  return response;
}
