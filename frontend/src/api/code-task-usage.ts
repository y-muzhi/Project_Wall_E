/** Original Coding call summaries and selected request/response audit. */
import { ApiUnknown, object, positiveInteger } from './client.ts';
import type { ApiClient } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { money } from './code-values.ts';
import {
  array,
  bool,
  checked,
  choices,
  count,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';

const readErrors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
const capture = choices(['FULL', 'REDACTED', 'INCOMPLETE']);
const fields = {
  id: positiveInteger,
  execution_session_id: positiveInteger,
  operation_id: positiveInteger,
  call_no: positiveInteger,
  attempt_no: choices([1]),
  model_name: nonempty,
  protocol_version: choices(['OC20-MODEL-1']),
  call_purpose: choices(['CODE', 'COMPACTION']),
  call_status: choices(['RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED']),
  transport_status: choices(['NOT_SENT', 'SENDING', 'SENT', 'COMPLETE', 'INTERRUPTED', 'UNKNOWN']),
  capture_status: capture,
  started_at: time,
  ended_at: nullable(time),
  input_tokens: nullable(count),
  output_tokens: nullable(count),
  cached_tokens: nullable(count),
  duration_ms: nullable(count),
  usage_status: choices(['NOT_REPORTED', 'PARTIAL', 'FINAL', 'DISPUTED']),
};

const summaryShape = shape(fields);
export type CodeCallSummary = ReturnType<typeof summaryShape>;
function validateSummary(call: CodeCallSummary) {
  require(call.ended_at === null || call.started_at <= call.ended_at);
  require(
    call.cached_tokens === null ||
      (call.input_tokens !== null && call.cached_tokens <= call.input_tokens),
  );
}
const summary = checked(summaryShape, validateSummary);

const responseSnapshot = checked(
  shape({
    frames: array(
      shape({
        seq: positiveInteger,
        received_at: time,
        frame_json: object,
        capture_status: capture,
      }),
      (16 * 1024 * 1024) / 2,
    ),
    frame_count: count,
    captured_bytes: count,
    complete: bool,
  }),
  (value) => {
    require(value.frames.length === value.frame_count && value.captured_bytes <= 16 * 1024 * 1024);
    let previous = 0;
    for (const frame of value.frames) {
      require(frame.seq > previous && (!value.complete || frame.seq === previous + 1));
      previous = frame.seq;
    }
    if (value.complete) require(value.frames.at(-1)?.frame_json.kind === 'DONE');
  },
);

const detail = checked(
  shape({
    ...fields,
    task_id: positiveInteger,
    retry_of_llm_use_id: nullable(positiveInteger),
    request_snapshot: shape({
      native_request: object,
      supplier_request: object,
      model: object,
      window: shape({
        task_id: positiveInteger,
        execution_session_id: positiveInteger,
        operation_id: positiveInteger,
        control_generation: positiveInteger,
        instance_id: positiveInteger,
      }),
    }),
    response_snapshot: nullable(responseSnapshot),
    finish_reason: nullable(nonempty),
    provider_request_id: nullable(nonempty),
    error_code: nullable(nonempty),
    reservation_id: positiveInteger,
    reservation_status: choices(['RESERVED', 'SETTLED', 'RELEASED_UNSENT', 'UNKNOWN', 'DISPUTED']),
    reserved_cny: money,
    settled_cny: nullable(money),
    settlement_basis: nullable(choices(['VERIFIED_USAGE', 'PROVIDER_BILL'])),
  }),
  (call) => {
    validateSummary(call);
    require(call.provider_request_id === null || [...call.provider_request_id].length <= 1024);
    const scope = call.request_snapshot.window;
    require(
      scope.task_id === call.task_id &&
        scope.execution_session_id === call.execution_session_id &&
        scope.operation_id === call.operation_id,
    );
    const settled = call.reservation_status === 'SETTLED';
    require(
      settled === (call.settled_cny !== null) && settled === (call.settlement_basis !== null),
    );
    require(call.capture_status !== 'INCOMPLETE' || call.response_snapshot?.complete !== true);
  },
);
export type CodeCallDetail = ReturnType<typeof detail>;

function path(taskId: number) {
  return '/api/v1/code-tasks/' + positiveInteger(taskId) + '/model-calls';
}

export async function readCodeModelCalls(
  client: ApiClient,
  taskId: number,
  page = 1,
  signal?: AbortSignal,
) {
  const response = await readPage(
    client,
    path(taskId),
    summary,
    (call) => call.id,
    [['page', String(page)]],
    page,
    signal,
    readErrors,
  );
  let previous: CodeCallSummary | null = null;
  for (const call of response.data.items) {
    if (
      previous !== null &&
      (previous.started_at < call.started_at ||
        (previous.started_at === call.started_at && previous.id <= call.id))
    )
      throw new ApiUnknown(false);
    previous = call;
  }
  return response;
}

export async function readCodeModelCall(
  client: ApiClient,
  taskId: number,
  useId: number,
  signal?: AbortSignal,
) {
  const response = await client.read(
    path(taskId) + '/' + positiveInteger(useId),
    detail,
    [],
    signal,
    readErrors,
  );
  if (
    response.data.task_id !== taskId ||
    response.data.id !== useId ||
    response.meta.pagination !== undefined
  )
    throw new ApiUnknown(false);
  return response;
}
