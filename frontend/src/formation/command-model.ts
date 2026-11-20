/** Strict record-5 branch in the shared ledger; exact request bytes are immutable. */
import { exact, object, positiveInteger, snapshotObject, stableJson } from '../api/client.ts';
import type { FrozenRequest } from '../api/client.ts';
import { COMMAND_BODY_BYTES, commandOrigin, commandSha256 } from '../api/code-command-snapshot.ts';
import { COMMAND_METADATA_BYTES, digest, uuid } from '../code-tasks/command-recovery-model.ts';

export type FormationIdentity = Readonly<{
  owner_module: 'FORMATION';
  origin: string;
  key: string;
  method: 'POST' | 'PATCH';
  path: string;
  identity_sha256: string;
  body_sha256: string;
  intent_key: string;
  requirement_id: number;
  document_id: number;
}>;
export type FormationPending = FormationIdentity &
  Readonly<{
    schema_version: 5;
    body_text: string;
    status: 'PREPARED' | 'DISPATCHING' | 'UNKNOWN';
    created_at: string;
    updated_at: string;
    submitted_at: string | null;
    dispatch_count: number;
    dispatch_owner_id: string | null;
    record_revision: number;
    recovery_mode: 'REPLAY_ORIGINAL';
  }>;
export type FormationReceipt = FormationIdentity &
  Readonly<{
    schema_version: 5;
    final_state: 'CONFIRMED' | 'KNOWN_REJECTED' | 'CANCELLED_UNSENT';
    http_status: number | null;
    result_code: string | null;
    guide_run_id: number | null;
    user_message_id: number | null;
    event_ids: readonly number[];
    resolved_at: string;
  }>;
export type FormationFrozen = FormationIdentity & Readonly<{ body_text: string }>;
const identityFields = [
  'owner_module',
  'origin',
  'key',
  'method',
  'path',
  'identity_sha256',
  'body_sha256',
  'intent_key',
  'requirement_id',
  'document_id',
] as const;
const pendingFields = [
  ...identityFields,
  'schema_version',
  'body_text',
  'status',
  'created_at',
  'updated_at',
  'submitted_at',
  'dispatch_count',
  'dispatch_owner_id',
  'record_revision',
  'recovery_mode',
];
const receiptFields = [
  ...identityFields,
  'schema_version',
  'final_state',
  'http_status',
  'result_code',
  'guide_run_id',
  'user_message_id',
  'event_ids',
  'resolved_at',
];
const encoder = new TextEncoder();
function time(value: unknown): asserts value is string {
  if (
    typeof value !== 'string' ||
    !Number.isFinite(Date.parse(value)) ||
    new Date(value).toISOString() !== value
  )
    throw TypeError('Invalid formation record time');
}
function count(value: unknown): asserts value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0)
    throw TypeError('Invalid dispatch count');
}
function identity(row: Record<string, unknown>, origin: string): FormationIdentity {
  if (row.owner_module !== 'FORMATION' || row.origin !== commandOrigin(origin))
    throw TypeError('Formation record owner differs');
  uuid(row.key);
  digest(row.identity_sha256);
  digest(row.body_sha256);
  positiveInteger(row.requirement_id);
  positiveInteger(row.document_id);
  uuid(row.intent_key);
  const requirement = /^\/api\/v1\/requirements\/([1-9][0-9]*)(\/guide-runs)?$/.exec(
    String(row.path),
  );
  const response = /^\/api\/v1\/conversation-messages\/([1-9][0-9]*)\/responses$/.exec(
    String(row.path),
  );
  if (requirement) {
    if (
      Number(requirement[1]) !== row.requirement_id ||
      row.method !== (requirement[2] ? 'POST' : 'PATCH')
    )
      throw TypeError('Formation route differs');
  } else if (!response || row.method !== 'POST' || !Number.isSafeInteger(Number(response[1])))
    throw TypeError('Unregistered formation route');
  return snapshotObject(
    Object.fromEntries(identityFields.map((field) => [field, row[field]])),
  ) as FormationIdentity;
}
export function formationIdentityText(value: FormationIdentity): string {
  return stableJson({
    owner_module: value.owner_module,
    origin: value.origin,
    key: value.key,
    method: value.method,
    path: value.path,
  })!;
}
export async function verifyFormationIdentity(
  value: FormationIdentity,
  origin: string,
): Promise<void> {
  const actual = identity(object(value), origin);
  if ((await commandSha256(formationIdentityText(actual))) !== actual.identity_sha256)
    throw TypeError('Formation identity digest differs');
}
export function formationPending(value: unknown, origin: string): FormationPending {
  const row = exact(value, pendingFields);
  identity(row, origin);
  if (
    row.schema_version !== 5 ||
    row.recovery_mode !== 'REPLAY_ORIGINAL' ||
    !['PREPARED', 'DISPATCHING', 'UNKNOWN'].includes(String(row.status))
  )
    throw TypeError('Invalid formation pending branch');
  time(row.created_at);
  time(row.updated_at);
  count(row.dispatch_count);
  positiveInteger(row.record_revision);
  if (row.submitted_at !== null) time(row.submitted_at);
  if (row.dispatch_owner_id !== null) uuid(row.dispatch_owner_id);
  if (
    row.updated_at < row.created_at ||
    (row.dispatch_count === 0) !== (row.submitted_at === null) ||
    (row.dispatch_count === 0) !== (row.dispatch_owner_id === null) ||
    (row.status === 'PREPARED') !== (row.dispatch_count === 0)
  )
    throw TypeError('Invalid formation dispatch observation');
  formationPendingSize(row);
  return snapshotObject(row) as FormationPending;
}
export function formationPendingSize(value: unknown): number {
  const row = exact(value, pendingFields);
  if (typeof row.body_text !== 'string') throw TypeError('Formation body unavailable');
  const body = encoder.encode(row.body_text).length;
  const meta = encoder.encode(
    JSON.stringify(Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'body_text'))),
  ).length;
  if (body > COMMAND_BODY_BYTES || meta > COMMAND_METADATA_BYTES)
    throw TypeError('Formation record exceeds capacity');
  return body + meta;
}
export function formationReceipt(value: unknown, origin: string): FormationReceipt {
  const row = exact(value, receiptFields);
  if (encoder.encode(JSON.stringify(row)).length > COMMAND_METADATA_BYTES)
    throw TypeError('Formation receipt exceeds metadata capacity');
  identity(row, origin);
  time(row.resolved_at);
  if (
    row.schema_version !== 5 ||
    !['CONFIRMED', 'KNOWN_REJECTED', 'CANCELLED_UNSENT'].includes(String(row.final_state))
  )
    throw TypeError('Invalid formation terminal branch');
  for (const field of ['guide_run_id', 'user_message_id'])
    if (row[field] !== null) positiveInteger(row[field]);
  if (!Array.isArray(row.event_ids)) throw TypeError('Invalid formation event identities');
  row.event_ids.forEach(positiveInteger);
  if (new Set(row.event_ids).size !== row.event_ids.length)
    throw TypeError('Duplicate formation event');
  if (
    row.result_code !== null &&
    (typeof row.result_code !== 'string' || !/^[A-Z][A-Z0-9_]{0,63}$/.test(row.result_code))
  )
    throw TypeError('Invalid formation rejection code');
  if (row.final_state === 'CONFIRMED') {
    if (![200, 202].includes(Number(row.http_status)) || row.result_code !== null)
      throw TypeError('Invalid confirmed formation response');
  } else if (row.final_state === 'KNOWN_REJECTED') {
    if (
      typeof row.http_status !== 'number' ||
      !Number.isInteger(row.http_status) ||
      row.http_status < 400 ||
      row.http_status >= 500 ||
      row.http_status === 408 ||
      typeof row.result_code !== 'string' ||
      row.result_code === 'REQUEST_IN_PROGRESS'
    )
      throw TypeError('Unknown response is not a known rejection');
  } else if (row.http_status !== null || row.result_code !== null)
    throw TypeError('Unsent terminal differs');
  if (
    row.final_state !== 'CONFIRMED' &&
    (row.guide_run_id !== null || row.user_message_id !== null || row.event_ids.length !== 0)
  )
    throw TypeError('Unexpected terminal result identities');
  return snapshotObject(row) as unknown as FormationReceipt;
}
export async function verifyFormationFrozen(value: FormationFrozen, origin: string): Promise<void> {
  const row = exact(value, [...identityFields, 'body_text']);
  await verifyFormationIdentity(value, origin);
  if (
    typeof row.body_text !== 'string' ||
    encoder.encode(row.body_text).length > COMMAND_BODY_BYTES
  )
    throw TypeError('Formation body unavailable');
  const body = snapshotObject(JSON.parse(row.body_text));
  if (
    JSON.stringify(body) !== row.body_text ||
    (await commandSha256(row.body_text)) !== row.body_sha256
  )
    throw TypeError('Formation body damaged');
  if (!value.path.includes('/conversation-messages/') && body.document_id !== value.document_id)
    throw TypeError('Formation document differs');
}
export function frozenFormation(row: FormationPending): FormationFrozen {
  return snapshotObject(
    Object.fromEntries(
      ([...identityFields, 'body_text'] as const).map((field) => [field, row[field]]),
    ),
  ) as FormationFrozen;
}
export async function freezeFormation(
  request: FrozenRequest,
  requirementId: number,
  documentId: number,
  intentKey: string,
  origin: string,
): Promise<FormationFrozen> {
  if (request.key === null || request.body === null)
    throw TypeError('Keyed formation request required');
  const value = {
    owner_module: 'FORMATION' as const,
    origin: commandOrigin(origin),
    key: request.key,
    method: request.method as 'POST' | 'PATCH',
    path: request.path,
    identity_sha256: '',
    body_sha256: await commandSha256(request.body),
    intent_key: uuid(intentKey),
    requirement_id: positiveInteger(requirementId),
    document_id: positiveInteger(documentId),
    body_text: request.body,
  };
  value.identity_sha256 = await commandSha256(formationIdentityText(value));
  await verifyFormationFrozen(value, origin);
  return Object.freeze(value);
}
