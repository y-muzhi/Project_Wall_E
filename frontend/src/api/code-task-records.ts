import type { ApiClient } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { checked, choices, id, nonempty, nullable, require, shape, time } from './decoding.ts';
import { readPage } from './pagination.ts';

const record = checked(
  shape({
    id,
    task_id: id,
    instance_id: id,
    control_generation: id,
    kind: choices(['MESSAGE', 'TOOL', 'COMMAND_OUTPUT', 'CONTROL', 'ERROR']),
    text: nonempty,
    observed_at: time,
    session_id: nullable(id),
    native_event_id: nullable(nonempty),
    source_kind: nullable(choices(['OPERATION', 'COMMAND', 'QUESTION', 'PERMISSION', 'LLM_USE'])),
    source_id: nullable(id),
  }),
  (row) => require((row.source_kind === null) === (row.source_id === null)),
);
export type CodingExecutionRecord = ReturnType<typeof record>;
const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
export async function readCodeTaskRecords(
  client: ApiClient,
  task: number,
  page: number,
  session: number | null,
  signal?: AbortSignal,
) {
  const query: [string, string][] = [['page', String(page)]];
  if (session !== null) query.push(['session_id', String(id(session))]);
  const response = await readPage(
    client,
    '/api/v1/code-tasks/' + id(task) + '/records',
    checked(record, (row) =>
      require(row.task_id === task && (session === null || row.session_id === session)),
    ),
    (row) => row.id,
    query,
    page,
    signal,
    errors,
  );
  require(
    response.data.items.every((row, index, rows) => index === 0 || rows[index - 1]!.id < row.id),
  );
  return response;
}
