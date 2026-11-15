/** One strict pager for numeric resource identities and opaque catalogue identities. */
import { ApiUnknown } from './client.ts';
import type { ApiClient, ApiErrorPolicy } from './client.ts';
import { array, distinct, id, require, shape } from './decoding.ts';
import type { Decoder } from './decoding.ts';

export async function readPage<T>(
  client: ApiClient,
  path: string,
  decode: Decoder<T>,
  identity: (row: T) => string | number,
  parameters: readonly (readonly [string, string])[],
  requestedPage: number,
  signal?: AbortSignal,
  errorPolicy?: ApiErrorPolicy,
) {
  id(requestedPage);
  require(requestedPage <= 100000);
  const response = await client.read(
    path,
    shape({ items: array(decode, 20) }),
    parameters,
    signal,
    errorPolicy,
  );
  try {
    const pagination = response.meta.pagination;
    require(pagination !== undefined && 'page' in pagination && pagination.page === requestedPage);
    require(
      response.data.items.length ===
        Math.min(20, Math.max(0, pagination.total - (requestedPage - 1) * 20)),
    );
    distinct(response.data.items.map(identity));
    return { ...response, meta: { ...response.meta, pagination } };
  } catch {
    throw new ApiUnknown(false);
  }
}
