/** Saved repository navigation and explicit settings details. */
import { ApiUnknown, positiveInteger } from './client.ts';
import type { ApiClient } from './client.ts';
import { checked, choices, nonempty, nullable, require, shape, time } from './decoding.ts';
import { normalizeOrdinary } from '../shared/text.ts';
import { configurationIdentityReadErrors } from './code-configuration-identities.ts';
import {
  canonicalRepositoryPath,
  repositoryObservationStatus,
} from './code-repository-observations.ts';
import { readPage } from './pagination.ts';

const path = '/api/v1/code-repositories';
const observation = shape({
  id: positiveInteger,
  status: repositoryObservationStatus,
  observed_at: time,
});
const fields = {
  id: positiveInteger,
  name(value: unknown) {
    const name = nonempty(value);
    require(!name.includes('\0') && normalizeOrdinary(name) === name);
    return name;
  },
  object_format: choices(['sha1', 'sha256'] as const),
  created_at: time,
  latest_observation: nullable(observation),
};
const repositoryListItem = shape({
  ...fields,
  root_path(value: unknown): null {
    require(value === null);
    return null;
  },
});
const repositoryDetail = shape({ ...fields, root_path: canonicalRepositoryPath });
export type RepositoryListItem = ReturnType<typeof repositoryListItem>;
export type RepositoryDetail = ReturnType<typeof repositoryDetail>;

export async function readRepositories(client: ApiClient, page = 1, signal?: AbortSignal) {
  const result = await readPage(
    client,
    path,
    repositoryListItem,
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    configurationIdentityReadErrors,
  );
  const rows = result.data.items;
  for (let index = 1; index < rows.length; index++) {
    const previous = rows[index - 1]!,
      current = rows[index]!;
    if (
      previous.created_at < current.created_at ||
      (previous.created_at === current.created_at && previous.id < current.id)
    )
      throw new ApiUnknown(false);
  }
  return result;
}

export async function readRepository(client: ApiClient, id: number, signal?: AbortSignal) {
  positiveInteger(id);
  const result = await client.read(
    path + '/' + id,
    checked(repositoryDetail, (row) => require(row.id === id)),
    [],
    signal,
    configurationIdentityReadErrors,
  );
  if (result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
