import { object } from './client.ts';
import type { ApiClient } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { money } from './code-values.ts';
import {
  checked,
  choices,
  count,
  id,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';
import { testingTaskPath } from './testing-tasks.ts';

const policy = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'PERMISSION_NOT_GRANTED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
const parseStatus = choices(['PENDING', 'SUCCEEDED', 'FAILED']);
const fields = {
  id,
  testing_task_id: id,
  operation_id: id,
  call_no: id,
  attempt_no: choices([1]),
  function_type: choices(['TEST_PLAN_DRAFT']),
  model_name: nonempty,
  call_status: choices(['RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED']),
  parse_status: parseStatus,
  validation_status: parseStatus,
  started_at: time,
  ended_at: nullable(time),
  input_tokens: nullable(count),
  output_tokens: nullable(count),
  usage_status: choices(['NOT_REPORTED', 'PARTIAL', 'FINAL', 'DISPUTED']),
  provider_request_id: nullable(checked(nonempty, (value) => require([...value].length <= 1024))),
};
const base = shape(fields);
export type TestingCallSummary = ReturnType<typeof base>;
function checkSummary(row: TestingCallSummary) {
  require(row.ended_at === null || row.ended_at >= row.started_at);
  if (row.usage_status === 'NOT_REPORTED')
    require(row.input_tokens === null && row.output_tokens === null);
  if (row.usage_status === 'FINAL')
    require(row.input_tokens !== null && row.output_tokens !== null);
}
const summary = checked(base, checkSummary);
const detail = checked(
  shape({
    ...fields,
    request_snapshot: nullable(object),
    response_snapshot: nullable(object),
    parsed_output: nullable(object),
    trusted_output: nullable(object),
    reservation_id: id,
    reserved_cny: money,
    settled_cny: nullable(money),
    settlement_basis: nullable(choices(['VERIFIED_USAGE', 'PROVIDER_BILL'])),
  }),
  (row) => {
    checkSummary(row);
    require((row.settled_cny === null) === (row.settlement_basis === null));
    require((row.parsed_output !== null) === (row.parse_status === 'SUCCEEDED'));
    require((row.trusted_output !== null) === (row.validation_status === 'SUCCEEDED'));
    if (row.trusted_output !== null) {
      const keys = Object.keys(row.trusted_output).sort();
      require(
        row.parsed_output !== null && keys.join(',') === 'behaviors,cases,unresolved_questions',
      );
      require(keys.every((key) => Array.isArray(row.trusted_output?.[key])));
    }
  },
);
const path = (task: number) => testingTaskPath(task) + '/model-calls';
export function readTestingCalls(
  client: ApiClient,
  task: number,
  page: number,
  signal?: AbortSignal,
) {
  return readPage(
    client,
    path(task),
    checked(summary, (row) => require(row.testing_task_id === task)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
}
export function readTestingCall(
  client: ApiClient,
  task: number,
  identity: number,
  signal?: AbortSignal,
) {
  return client.read(
    path(task) + '/' + id(identity),
    checked(detail, (row) => require(row.testing_task_id === task && row.id === identity)),
    [],
    signal,
    policy,
  );
}
