/** Exact registered snapshot readiness and fixed Git file metadata. */
import { ApiUnknown, positiveInteger } from './client.ts';
import type { ApiClient } from './client.ts';
import {
  array,
  bool,
  checked,
  choices,
  count,
  nonempty,
  require,
  shape,
  time,
} from './decoding.ts';
import { gitObjectId } from './code-repository-observations.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { readPage } from './pagination.ts';

const path = '/api/v1/code-snapshots';
const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
const contentNotReady = choices(['CONTENT_NOT_READY'] as const);
export const codeSnapshot = checked(
  shape({
    id: positiveInteger,
    repository_id: positiveInteger,
    registration_operation_id: positiveInteger,
    content_profile_version_id: positiveInteger,
    commit_oid: gitObjectId,
    content_tree_oid: gitObjectId,
    content_policy_version: choices(['GIT20-BASELINE-1'] as const),
    registered_at: time,
    created_at: time,
    ready: bool,
    reason_codes: array(contentNotReady, 1),
  }),
  (row) => {
    require(row.registered_at <= row.created_at);
    require(row.commit_oid.length === row.content_tree_oid.length);
    require(row.reason_codes.length === (row.ready ? 0 : 1));
  },
);
export function relativePath(value: unknown) {
  const result = nonempty(value);
  require(result.normalize('NFC') === result && !/[\\:*?"<>|\p{Cc}]/u.test(result));
  for (const part of result.split('/')) {
    const stem = part.split('.')[0]!.replace(/ +$/u, '');
    require(
      part.length > 0 &&
        !/[. ]$/u.test(part) &&
        part.toLowerCase() !== '.git' &&
        !/^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$/iu.test(stem),
    );
  }
  return result;
}
export const codeBaselineFile = shape({
  path: relativePath,
  mode: choices(['100644', '100755'] as const),
  blob_oid: gitObjectId,
  byte_count: count,
});
export type CodeSnapshot = ReturnType<typeof codeSnapshot>;
export type CodeBaselineFile = ReturnType<typeof codeBaselineFile>;

const encoder = new TextEncoder();
export function comparePaths(first: Uint8Array, second: Uint8Array) {
  for (let index = 0; index < Math.min(first.length, second.length); index++) {
    const difference = first[index]! - second[index]!;
    if (difference !== 0) return difference;
  }
  return first.length - second.length;
}

export async function readCodeSnapshot(
  client: ApiClient,
  snapshotId: number,
  signal?: AbortSignal,
) {
  positiveInteger(snapshotId);
  const response = await client.read(path + '/' + snapshotId, codeSnapshot, [], signal, errors);
  if (response.data.id !== snapshotId || response.meta.pagination !== undefined)
    throw new ApiUnknown(false);
  return response;
}

export async function readCodeBaselineFiles(
  client: ApiClient,
  snapshotId: number,
  page = 1,
  signal?: AbortSignal,
) {
  positiveInteger(snapshotId);
  const response = await readPage(
    client,
    path + '/' + snapshotId + '/files',
    codeBaselineFile,
    (entry) => entry.path,
    [['page', String(page)]],
    page,
    signal,
    errors,
  );
  const rows = response.data.items;
  const paths = rows.map((row) => encoder.encode(row.path));
  const formatLengths = new Set(rows.map((row) => row.blob_oid.length));
  if (
    formatLengths.size > 1 ||
    paths.some((value, index) => index > 0 && comparePaths(paths[index - 1]!, value) >= 0)
  )
    throw new ApiUnknown(false);
  return response;
}
