/** Exact stored repository observation; reads never refresh Git. */
import { ApiUnknown, positiveInteger } from './client.ts';
import type { ApiClient } from './client.ts';
import {
  array,
  checked,
  choices,
  distinct,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { codeErrorPolicy } from './code-errors.ts';

export function gitObjectId(value: unknown): string {
  const result = nonempty(value);
  require(/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(result) && !/^0+$/.test(result));
  return result;
}
export function localBranchRef(value: unknown): string {
  const result = nonempty(value);
  require(
    result.startsWith('refs/heads/') &&
      !result.endsWith('/') &&
      !result.endsWith('.') &&
      !result.includes('//') &&
      !result.includes('..') &&
      !result.includes('@{') &&
      ![...result].some(
        (char) =>
          char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127 || '~^:?*[\\'.includes(char),
      ) &&
      !result.split('/').some((part) => part.startsWith('.') || part.endsWith('.lock')),
  );
  return result;
}
function worktreeComponent(part: string): boolean {
  const basename = part.split('.')[0];
  return (
    part.length > 0 &&
    part !== '.' &&
    part !== '..' &&
    !/[. ]$/.test(part) &&
    basename !== undefined &&
    !/^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$/iu.test(
      basename.replace(/ +$/u, ''),
    )
  );
}
export function canonicalRepositoryPath(value: unknown): string {
  const result = nonempty(value);
  require(/^[A-Za-z]:\\/.test(result) && !/[\/\u0000-\u001f:*?"<>|]/.test(result.slice(3)));
  if (result.length === 3) return result;
  const components = result.slice(3).split('\\');
  require(components.every(worktreeComponent));
  return result;
}
const branch = shape({ full_ref: localBranchRef, commit_oid: gitObjectId });
const worktree = shape({
  canonical_path: canonicalRepositoryPath,
  head_commit: nullable(gitObjectId),
  branch_ref: nullable(localBranchRef),
});
export const repositoryObservationStatus = choices(['READABLE', 'UNAVAILABLE', 'UNKNOWN'] as const);
export const repositoryObservation = checked(
  shape({
    id: positiveInteger,
    repository_id: positiveInteger,
    operation_id: positiveInteger,
    head_commit: nullable(gitObjectId),
    local_branches: array(branch, 8 * 1024 * 1024),
    worktrees: array(worktree, 8 * 1024 * 1024),
    observed_at: time,
    status: repositoryObservationStatus,
  }),
  (row) => {
    distinct(row.local_branches.map((item) => item.full_ref));
    distinct(row.worktrees.map((item) => item.canonical_path));
    const lengths = new Set<number>();
    if (row.head_commit !== null) lengths.add(row.head_commit.length);
    for (const item of row.local_branches) lengths.add(item.commit_oid.length);
    const branches = new Map(row.local_branches.map((item) => [item.full_ref, item.commit_oid]));
    for (const item of row.worktrees) {
      if (item.head_commit !== null) lengths.add(item.head_commit.length);
      if (row.status === 'READABLE' && item.branch_ref !== null)
        require(
          branches.has(item.branch_ref) && branches.get(item.branch_ref) === item.head_commit,
        );
    }
    require(lengths.size <= 1);
  },
);
export type RepositoryObservation = ReturnType<typeof repositoryObservation>;
const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
export async function readRepositoryObservation(
  client: ApiClient,
  repositoryId: number,
  observationId: number,
  signal?: AbortSignal,
) {
  positiveInteger(repositoryId);
  positiveInteger(observationId);
  const result = await client.read(
    '/api/v1/code-repositories/' + repositoryId + '/observations/' + observationId,
    repositoryObservation,
    [],
    signal,
    errors,
  );
  if (
    result.data.repository_id !== repositoryId ||
    result.data.id !== observationId ||
    result.meta.pagination !== undefined
  )
    throw new ApiUnknown(false);
  return result;
}
