/** Read fixed design revision eligibility with its original confirmation event. */
import { ApiUnknown, positiveInteger } from './client.ts';
import type { ApiClient } from './client.ts';
import { bool, checked, choices, nullable, require, shape, time } from './decoding.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { readPage } from './pagination.ts';

export type DesignRevisionUsage = 'MAIN' | 'MATERIAL';
const usageValue = choices(['MAIN', 'MATERIAL'] as const);
const reason = choices(['UNCONFIRMED', 'EMPTY_MAIN', 'UNAVAILABLE'] as const);
const designRevision = checked(
  shape({
    revision_id: positiveInteger,
    requirement_id: positiveInteger,
    document_id: positiveInteger,
    version_no: positiveInteger,
    is_current: bool,
    confirmation_event_id: nullable(positiveInteger),
    confirmed_at: nullable(time),
    eligible: bool,
    reason_code: nullable(reason),
  }),
  (row) => {
    require((row.confirmation_event_id === null) === (row.confirmed_at === null));
    require(row.eligible === (row.reason_code === null));
    if (row.eligible || row.reason_code === 'EMPTY_MAIN')
      require(row.confirmation_event_id !== null);
    if (row.reason_code === 'UNCONFIRMED') require(row.confirmation_event_id === null);
  },
);
export type DesignRevisionChoice = ReturnType<typeof designRevision>;
const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);

export async function readDesignRevisions(
  client: ApiClient,
  documentId: number,
  usage: DesignRevisionUsage = 'MAIN',
  page = 1,
  signal?: AbortSignal,
) {
  positiveInteger(documentId);
  usageValue(usage);
  const result = await readPage(
    client,
    '/api/v1/documents/' + documentId + '/code-design-revisions',
    checked(designRevision, (row) => {
      require(row.document_id === documentId);
      require(usage === 'MAIN' || row.reason_code !== 'EMPTY_MAIN');
    }),
    (row) => row.revision_id,
    [
      ['usage', usage],
      ['page', String(page)],
    ],
    page,
    signal,
    errors,
  );
  const rows = result.data.items;
  if (
    new Set(rows.map((row) => row.requirement_id)).size > 1 ||
    rows.filter((row) => row.is_current).length > 1 ||
    rows.some((row, index) => index > 0 && row.version_no >= rows[index - 1]!.version_no)
  )
    throw new ApiUnknown(false);
  return result;
}
