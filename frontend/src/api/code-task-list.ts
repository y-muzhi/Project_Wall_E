/** Read task summaries for the document task list. */
import type { ApiClient } from './client.ts';
import { ApiUnknown, positiveInteger } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { decodeTaskView } from './code-task-creation.ts';
import { checked, choices, interval, nullable, require, shape, time } from './decoding.ts';
import { readPage } from './pagination.ts';

const taskStatus = choices([
  'PENDING',
  'RUNNING',
  'WAITING',
  'VERIFYING',
  'AWAITING_TESTING',
  'AWAITING_ACCEPTANCE',
  'STOPPING',
  'COMPLETED',
  'TERMINATED',
]);
const taskPhase = choices([
  'PREPARING',
  'BACKEND',
  'FRONTEND',
  'INTEGRATION',
  'TESTING',
  'ACCEPTANCE',
  'DELIVERY',
  'FINISHED',
]);
export type CodeTaskStatus = ReturnType<typeof taskStatus>;
export type CodeTaskFilters = Readonly<{
  statuses?: readonly CodeTaskStatus[];
  designRevisionId?: number;
}>;

const taskSummary = checked(
  shape({
    id: positiveInteger,
    document_id: positiveInteger,
    status: taskStatus,
    phase: taskPhase,
    state_version: positiveInteger,
    created_at: time,
    updated_at: time,
    current_candidate_id: nullable(positiveInteger),
  }),
  interval,
);
export type CodeTaskSummary = ReturnType<typeof taskSummary>;

const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);

export async function readCodeTask(client: ApiClient, taskId: number, signal?: AbortSignal) {
  positiveInteger(taskId);
  const result = await client.read(
    '/api/v1/code-tasks/' + taskId,
    checked(decodeTaskView, (task) => require(task.id === taskId)),
    [],
    signal,
    errors,
  );
  if (result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}

export async function readDocumentCodeTasks(
  client: ApiClient,
  documentId: number,
  page: number,
  filters: CodeTaskFilters,
  signal?: AbortSignal,
) {
  positiveInteger(documentId);
  const query: [string, string][] = [['page', String(page)]];
  const statuses = new Set(filters.statuses?.map(taskStatus));
  for (const status of statuses) query.push(['status', status]);
  if (filters.designRevisionId !== undefined)
    query.push(['design_revision_id', String(positiveInteger(filters.designRevisionId))]);
  const result = await readPage(
    client,
    '/api/v1/documents/' + documentId + '/code-tasks',
    checked(taskSummary, (row) => {
      require(row.document_id === documentId);
      require(statuses.size === 0 || statuses.has(row.status));
    }),
    (row) => row.id,
    query,
    page,
    signal,
    errors,
  );
  const rows = result.data.items;
  if (
    rows.some((row, index) => {
      const previous = rows[index - 1];
      return (
        previous !== undefined &&
        (row.created_at > previous.created_at ||
          (row.created_at === previous.created_at && row.id >= previous.id))
      );
    })
  )
    throw new ApiUnknown(false);
  return result;
}
