/** Original receipt decoding and reads through the existing ApiClient only. */
import { exact, positiveInteger, object } from './client.ts';
import type { ApiClient, ApiSuccess, JsonObject } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { codeErrorPolicy } from './code-errors.ts';
import type { CodeErrorCode } from './code-errors.ts';

export type OriginalResultPolicy<T> = Readonly<{
  decoder_kind: string;
  success_status: readonly (200 | 201 | 202)[];
  decode: (value: unknown, original: CommandIdentity) => T;
  errors: readonly CodeErrorCode[];
}>;
export type OriginalOutcome<T> =
  | Readonly<{ success: true; data: T; error: null }>
  | Readonly<{
      success: false;
      data: null;
      error: Readonly<{ code: string; message: string; details: JsonObject | null }>;
    }>;
export type CommandReceipt<T> = Readonly<{
  lookup_status: 'FOUND' | 'IN_PROGRESS' | 'NOT_FOUND' | 'UNKNOWN';
  record_status: 'PROCESSING' | 'SUCCEEDED' | 'REJECTED' | 'CLOSED' | null;
  original_http_status: number | null;
  original_outcome: OriginalOutcome<T> | null;
  task_id: number | null;
  testing_task_id: number | null;
  operation_id: number | null;
}>;
const nullableId = (value: unknown) => (value === null ? null : positiveInteger(value));

function verifiedOriginal(original: CommandIdentity): CommandIdentity {
  const checked = registeredCommand(original.method, original.path, original.key);
  if (
    checked.owner_module !== original.owner_module ||
    checked.decoder_kind !== original.decoder_kind
  )
    throw new TypeError('Original receipt owner differs');
  return checked;
}

export function commandReceipt<T>(
  value: unknown,
  identity: CommandIdentity,
  policy: OriginalResultPolicy<T>,
): CommandReceipt<T> {
  const original = verifiedOriginal(identity);
  if (
    policy.decoder_kind !== original.decoder_kind ||
    !policy.success_status.length ||
    new Set(policy.success_status).size !== policy.success_status.length ||
    policy.success_status.some((status) => ![200, 201, 202].includes(status))
  )
    throw new TypeError('Original decoder registration differs');
  const row = exact(value, [
    'lookup_status',
    'record_status',
    'original_http_status',
    'original_outcome',
    'task_id',
    'testing_task_id',
    'operation_id',
  ]);
  const task_id = nullableId(row.task_id),
    testing_task_id = nullableId(row.testing_task_id),
    operation_id = nullableId(row.operation_id);
  if (
    (original.owner_module === 'CODING' && testing_task_id !== null) ||
    (original.owner_module === 'TESTING' && task_id !== null) ||
    (original.parameters.task_id !== undefined &&
      task_id !== null &&
      original.parameters.task_id !== task_id) ||
    (original.parameters.testing_task_id !== undefined &&
      testing_task_id !== null &&
      original.parameters.testing_task_id !== testing_task_id)
  )
    throw new TypeError('Receipt association crosses original scope');
  if (
    ['APP-CODE-CMD-C01', 'APP-CODE-CMD-C02', 'APP-CODE-CMD-C05'].includes(original.decoder_kind) &&
    (task_id !== null || testing_task_id !== null)
  )
    throw new TypeError('Repository receipt cannot acquire a task owner');
  const common = { task_id, testing_task_id, operation_id };
  if (row.lookup_status !== 'FOUND') {
    if (
      row.original_http_status !== null ||
      row.original_outcome !== null ||
      !['IN_PROGRESS', 'NOT_FOUND', 'UNKNOWN'].includes(row.lookup_status as string) ||
      (row.lookup_status === 'IN_PROGRESS' && row.record_status !== 'PROCESSING') ||
      (row.lookup_status === 'NOT_FOUND' &&
        (row.record_status !== null ||
          task_id !== null ||
          testing_task_id !== null ||
          operation_id !== null)) ||
      (row.lookup_status === 'UNKNOWN' &&
        row.record_status !== null &&
        row.record_status !== 'PROCESSING')
    )
      throw new TypeError('Nonterminal receipt invents a result');
    return Object.freeze({
      ...common,
      lookup_status: row.lookup_status as 'IN_PROGRESS' | 'NOT_FOUND' | 'UNKNOWN',
      record_status: row.record_status as 'PROCESSING' | null,
      original_http_status: null,
      original_outcome: null,
    });
  }
  const outcome = exact(row.original_outcome, ['success', 'data', 'error']);
  const status = row.original_http_status;
  if (typeof status !== 'number' || !Number.isInteger(status))
    throw new TypeError('Invalid original HTTP status');
  let original_outcome: OriginalOutcome<T>;
  if (row.record_status === 'SUCCEEDED') {
    if (
      outcome.success !== true ||
      outcome.error !== null ||
      !policy.success_status.includes(status as 200 | 201 | 202)
    )
      throw new TypeError('Invalid original success');
    const data = object(outcome.data);
    for (const field of ['task_id', 'testing_task_id', 'operation_id'] as const) {
      if (Object.hasOwn(data, field) && nullableId(data[field]) !== common[field])
        throw new TypeError('Original result and receipt association differ');
    }
    if (
      original.decoder_kind === 'APP-CODE-CMD-C32' &&
      (task_id === null || positiveInteger(data.id) !== task_id || operation_id !== null)
    )
      throw new TypeError('Original task creation receipt differs from its task');
    if (
      original.decoder_kind === 'APP-CODE-CMD-C37' &&
      status === 200 &&
      (task_id === null || positiveInteger(data.id) !== task_id || operation_id !== null)
    )
      throw new TypeError('Terminal stop receipt differs from its task');
    if (
      status === 200 &&
      ['APP-TEST-CMD-C27', 'APP-TEST-CMD-C29', 'APP-TEST-CMD-C31'].includes(
        original.decoder_kind,
      ) &&
      (testing_task_id === null ||
        positiveInteger(data.id) !== testing_task_id ||
        operation_id !== null)
    )
      throw new TypeError('Original Testing task control receipt differs from its owner');
    if (
      original.decoder_kind === 'APP-TEST-CMD-C40' &&
      (testing_task_id !== null || operation_id !== null)
    )
      throw new TypeError('Finding review receipt cannot acquire a task or active operation');
    if (status === 202 && operation_id === null)
      throw new TypeError('Accepted receipt has no original operation');
    original_outcome = Object.freeze({
      success: true,
      data: policy.decode(outcome.data, original),
      error: null,
    });
  } else if (row.record_status === 'REJECTED' || row.record_status === 'CLOSED') {
    if (outcome.success !== false || outcome.data !== null || status < 400 || status >= 500)
      throw new TypeError('Invalid original rejection');
    const error = exact(outcome.error, ['code', 'message', 'details']);
    if (
      typeof error.code !== 'string' ||
      typeof error.message !== 'string' ||
      (row.record_status === 'CLOSED') !== (error.code === 'COMMAND_CLOSED')
    )
      throw new TypeError('Rejected and closed receipt differ');
    const errors = codeErrorPolicy([
      ...new Set<CodeErrorCode>([...policy.errors, 'COMMAND_CLOSED']),
    ]);
    const details = errors.decode(error.code, error.message, error.details, status);
    if (
      row.record_status === 'CLOSED' &&
      (details?.path !== original.path || details?.method !== original.method)
    )
      throw new TypeError('Closed receipt differs from original path');
    original_outcome = Object.freeze({
      success: false,
      data: null,
      error: Object.freeze({ code: error.code, message: error.message, details }),
    });
  } else throw new TypeError('Found receipt must be terminal');
  return Object.freeze({
    ...common,
    lookup_status: 'FOUND',
    record_status: row.record_status,
    original_http_status: status,
    original_outcome,
  });
}

const COMMON_READ_ERRORS = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'PERMISSION_NOT_GRANTED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
] as const;
export async function readCommandReceipt<T>(
  client: ApiClient,
  identity: CommandIdentity,
  policy: OriginalResultPolicy<T>,
  signal?: AbortSignal,
): Promise<ApiSuccess<CommandReceipt<T>>> {
  const original = verifiedOriginal(identity);
  const frozenPolicy = Object.freeze({
    decoder_kind: policy.decoder_kind,
    success_status: Object.freeze([...policy.success_status]),
    decode: policy.decode,
    errors: Object.freeze([...policy.errors]),
  });
  const errors = codeErrorPolicy(
    original.owner_module === 'CODING'
      ? [...COMMON_READ_ERRORS, 'CONTENT_NOT_READY', 'CONFIG_NOT_READY']
      : COMMON_READ_ERRORS,
  );
  const path =
    original.owner_module === 'CODING'
      ? '/api/v1/code-command-receipts'
      : '/api/v1/testing-command-receipts';
  return client.read(
    path,
    (value) => commandReceipt(value, original, frozenPolicy),
    [
      ['method', original.method],
      ['path', original.path],
      ['request_key', original.key],
    ],
    signal,
    errors,
  );
}
