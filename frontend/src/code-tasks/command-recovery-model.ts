/** Browser observations only; never server ownership or permission. */
import { exact, object, positiveInteger, snapshotObject } from '../api/client.ts';
import { time } from '../api/decoding.ts';
import {
  commandOrigin,
  verifiedCommandIdentity,
  commandSha256,
  commandRecoveryMode,
  COMMAND_BODY_BYTES,
} from '../api/code-command-snapshot.ts';
import type {
  FrozenCodeCommand,
  FrozenIdentity,
  RecoveryMode,
} from '../api/code-command-snapshot.ts';
import { registeredCommand } from '../api/code-command-registry.ts';

export const COMMAND_METADATA_BYTES = 64 * 1024;
export const COMMAND_PENDING_LIMIT = 100;
export const COMMAND_PENDING_BYTES = 128 * 1024 * 1024;
export type PendingSummary = FrozenIdentity &
  Readonly<{
    schema_version: 4;
    intent_key: string;
    close_state: 'NONE' | 'REQUESTED' | 'ALREADY_RECEIVED';
    close_requested_at: string | null;
    status: 'PREPARED' | 'DISPATCHING' | 'ACCEPTED' | 'UNKNOWN';
    task_id: number | null;
    testing_task_id: number | null;
    operation_id: number | null;
    created_at: string;
    updated_at: string;
    submitted_at: string | null;
    dispatch_count: number;
    dispatch_owner_id: string | null;
    record_revision: number;
    lookup_status: 'FOUND' | 'IN_PROGRESS' | 'NOT_FOUND' | 'UNKNOWN' | null;
  }>;
export type PendingAction = PendingSummary &
  FrozenCodeCommand &
  Readonly<{
    recovery_mode: RecoveryMode;
  }>;
export type CommandReceiptLocal = FrozenIdentity &
  Readonly<{
    schema_version: 4;
    body_sha256: string | null;
    final_state: 'CONFIRMED' | 'REJECTED' | 'CANCELLED_UNSENT' | 'CLOSED_UNEXECUTED';
    task_id: number | null;
    testing_task_id: number | null;
    operation_id: number | null;
    http_status: number | null;
    result_code: string | null;
    resolved_at: string;
  }>;
const SUMMARY_FIELDS = [
  'schema_version',
  'owner_module',
  'origin',
  'key',
  'method',
  'path',
  'identity_sha256',
  'decoder_kind',
  'intent_key',
  'close_state',
  'close_requested_at',
  'status',
  'task_id',
  'testing_task_id',
  'operation_id',
  'created_at',
  'updated_at',
  'submitted_at',
  'dispatch_count',
  'dispatch_owner_id',
  'record_revision',
  'lookup_status',
] as const;
export const PENDING_FIELDS = [
  ...SUMMARY_FIELDS,
  'body_json',
  'body_sha256',
  'recovery_mode',
] as const;
export const IMMUTABLE_FIELDS = [
  'schema_version',
  'owner_module',
  'origin',
  'key',
  'method',
  'path',
  'identity_sha256',
  'decoder_kind',
  'intent_key',
  'body_json',
  'body_sha256',
  'recovery_mode',
  'created_at',
] as const;
const SHA = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const encoder = new TextEncoder();
export function uuid(value: unknown): string {
  if (typeof value !== 'string' || !UUID.test(value)) throw new TypeError('Invalid tab identity');
  return value;
}
export function digest(value: unknown): string {
  if (typeof value !== 'string' || !SHA.test(value)) throw new TypeError('Invalid local digest');
  return value;
}
export function pendingSize(value: unknown): number {
  const row = exact(value, PENDING_FIELDS);
  if (typeof row.body_json !== 'string') throw new TypeError('Original body unavailable');
  const body = encoder.encode(row.body_json).length;
  const meta = encoder.encode(
    JSON.stringify(
      snapshotObject(
        Object.fromEntries(Object.entries(row).filter(([name]) => name !== 'body_json')),
      ),
    ),
  ).length;
  if (body > COMMAND_BODY_BYTES || meta > COMMAND_METADATA_BYTES)
    throw new TypeError('Original command exceeds local limits');
  return body + meta;
}
function associations(row: Record<string, unknown>, owner: string, path: string): void {
  const original = registeredCommand('POST', path, row.key);
  for (const field of ['task_id', 'testing_task_id', 'operation_id']) {
    if (row[field] !== null) positiveInteger(row[field]);
  }
  if (
    (owner === 'CODING' && row.testing_task_id !== null) ||
    (owner === 'TESTING' && row.task_id !== null) ||
    (row.task_id !== null &&
      original.parameters.task_id !== undefined &&
      row.task_id !== original.parameters.task_id) ||
    (row.testing_task_id !== null &&
      original.parameters.testing_task_id !== undefined &&
      row.testing_task_id !== original.parameters.testing_task_id)
  )
    throw new TypeError('Stored command crosses original owner');
}
export function pendingSummary(value: unknown, currentOrigin: string): PendingSummary {
  const row = exact(value, PENDING_FIELDS);
  const original = registeredCommand(row.method, row.path, row.key);
  if (
    row.schema_version !== 4 ||
    row.origin !== commandOrigin(currentOrigin) ||
    row.owner_module !== original.owner_module ||
    row.decoder_kind !== original.decoder_kind ||
    row.intent_key !== original.method + ' ' + original.path
  )
    throw new TypeError('Stored original identity differs');
  digest(row.identity_sha256);
  positiveInteger(row.record_revision);
  if (
    typeof row.dispatch_count !== 'number' ||
    !Number.isSafeInteger(row.dispatch_count) ||
    row.dispatch_count < 0 ||
    !['PREPARED', 'DISPATCHING', 'ACCEPTED', 'UNKNOWN'].includes(row.status as string) ||
    !['NONE', 'REQUESTED', 'ALREADY_RECEIVED'].includes(row.close_state as string) ||
    ![null, 'FOUND', 'IN_PROGRESS', 'NOT_FOUND', 'UNKNOWN'].includes(
      row.lookup_status as string | null,
    )
  )
    throw new TypeError('Stored command observation invalid');
  associations(row, original.owner_module, original.path);
  time(row.created_at);
  time(row.updated_at);
  if ((row.updated_at as string) < (row.created_at as string))
    throw new TypeError('Local time order invalid');
  if (row.close_requested_at !== null) time(row.close_requested_at);
  if ((row.close_state === 'NONE') !== (row.close_requested_at === null))
    throw new TypeError('Stored close intent invalid');
  if (row.submitted_at !== null) time(row.submitted_at);
  if (row.dispatch_owner_id !== null) uuid(row.dispatch_owner_id);
  if (
    (row.dispatch_count === 0) !== (row.submitted_at === null) ||
    (row.dispatch_count === 0) !== (row.dispatch_owner_id === null) ||
    (row.status === 'PREPARED' && row.dispatch_count !== 0) ||
    (row.status !== 'PREPARED' && row.dispatch_count === 0) ||
    (row.status === 'ACCEPTED' && row.operation_id === null)
  )
    throw new TypeError('Stored dispatch observation invalid');
  return snapshotObject(
    Object.fromEntries(SUMMARY_FIELDS.map((field) => [field, row[field]])),
  ) as PendingSummary;
}
export async function verifiedSummary(value: unknown, origin: string): Promise<PendingSummary> {
  const summary = pendingSummary(value, origin);
  await verifiedCommandIdentity(summary, origin);
  return summary;
}
export async function verifiedFrozen(
  value: FrozenCodeCommand,
  origin: string,
): Promise<{
  frozen: FrozenCodeCommand;
  recovery_mode: RecoveryMode;
}> {
  const frozen = snapshotObject(
    exact(value, [
      'origin',
      'owner_module',
      'method',
      'path',
      'key',
      'identity_sha256',
      'decoder_kind',
      'body_json',
      'body_sha256',
    ]),
  );
  const original = await verifiedCommandIdentity(frozen, origin);
  if (
    typeof frozen.body_json !== 'string' ||
    encoder.encode(frozen.body_json).length > COMMAND_BODY_BYTES
  )
    throw new TypeError('Original body unavailable');
  const input = snapshotObject(JSON.parse(frozen.body_json));
  if (
    JSON.stringify(input) !== frozen.body_json ||
    frozen.body_sha256 !== (await commandSha256(frozen.body_json))
  )
    throw new TypeError('Original body damaged');
  return {
    frozen: frozen as FrozenCodeCommand,
    recovery_mode: commandRecoveryMode(original, input),
  };
}
export function receiptLocal(value: unknown, currentOrigin: string): CommandReceiptLocal {
  const row = exact(value, [
    'schema_version',
    'owner_module',
    'origin',
    'key',
    'method',
    'path',
    'identity_sha256',
    'body_sha256',
    'final_state',
    'task_id',
    'testing_task_id',
    'operation_id',
    'http_status',
    'result_code',
    'resolved_at',
  ]);
  const original = registeredCommand(row.method, row.path, row.key);
  if (
    row.schema_version !== 4 ||
    row.origin !== commandOrigin(currentOrigin) ||
    row.owner_module !== original.owner_module ||
    !['CONFIRMED', 'REJECTED', 'CANCELLED_UNSENT', 'CLOSED_UNEXECUTED'].includes(
      row.final_state as string,
    )
  )
    throw new TypeError('Invalid local receipt');
  digest(row.identity_sha256);
  if (row.body_sha256 !== null) digest(row.body_sha256);
  if (row.body_sha256 === null && row.final_state !== 'CLOSED_UNEXECUTED')
    throw new TypeError('Local terminal body digest missing');
  associations(row, original.owner_module, original.path);
  time(row.resolved_at);
  if (
    row.http_status !== null &&
    (typeof row.http_status !== 'number' ||
      !Number.isInteger(row.http_status) ||
      row.http_status < 200 ||
      row.http_status > 499)
  )
    throw new TypeError('Invalid terminal HTTP observation');
  if (
    row.result_code !== null &&
    (typeof row.result_code !== 'string' || !/^[A-Z][A-Z0-9_]{0,63}$/.test(row.result_code))
  )
    throw new TypeError('Invalid terminal code');
  if (
    row.final_state === 'CLOSED_UNEXECUTED' &&
    (row.http_status !== 409 || row.result_code !== 'COMMAND_CLOSED')
  )
    throw new TypeError('Local closed terminal differs');
  if (
    row.final_state === 'CANCELLED_UNSENT' &&
    (row.http_status !== null ||
      row.result_code !== null ||
      row.operation_id !== null ||
      row.task_id !== null ||
      row.testing_task_id !== null)
  )
    throw new TypeError('Local unsent cancellation differs');
  // decoder_kind is re-derived, not another persisted receipt field.
  return Object.freeze({ ...row, decoder_kind: original.decoder_kind }) as CommandReceiptLocal;
}
export function persistedReceipt(value: CommandReceiptLocal): Record<string, unknown> {
  const { decoder_kind: _nativeKind, ...row } = value;
  return row;
}
export function originalFrozen(value: unknown): FrozenCodeCommand {
  const row = object(value);
  return snapshotObject(
    Object.fromEntries(
      [
        'origin',
        'owner_module',
        'method',
        'path',
        'key',
        'identity_sha256',
        'decoder_kind',
        'body_json',
        'body_sha256',
      ].map((field) => [field, row[field]]),
    ),
  ) as FrozenCodeCommand;
}
