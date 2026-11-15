/** Frozen V2 command bytes; hashes detect damage, never grant authority. */
import { exact, object, snapshotObject, ApiClient } from './client.ts';
import type { ApiSuccess, JsonObject, PreparedCommand } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { codeErrorPolicy } from './code-errors.ts';
import type { CodeErrorCode } from './code-errors.ts';
import type { OriginalResultPolicy } from './code-command-receipts.ts';

export const COMMAND_BODY_BYTES = 8 * 1024 * 1024;
export type RecoveryMode = 'QUERY_ONLY' | 'REPLAY_SAME_KEY';
export type FrozenIdentity = Readonly<{
  origin: string;
  owner_module: 'CODING' | 'TESTING';
  method: 'POST';
  path: string;
  key: string;
  decoder_kind: string;
  identity_sha256: string;
}>;
export type FrozenCodeCommand = FrozenIdentity &
  Readonly<{
    body_json: string;
    body_sha256: string;
  }>;
export type CodeCommandBinding<T> = Readonly<{
  decoder_kind: string;
  success_status: readonly (200 | 201 | 202)[];
  errors: readonly CodeErrorCode[];
  validate_input: (value: JsonObject, original: CommandIdentity) => void;
  decode: (value: unknown, original: CommandIdentity, input: JsonObject) => T;
}>;
export type FrozenCodeAction<T> = Readonly<{
  frozen: FrozenCodeCommand;
  recovery_mode: RecoveryMode;
  result_policy: OriginalResultPolicy<T>;
  submit: (signal?: AbortSignal) => Promise<ApiSuccess<T>>;
}>;
const encoder = new TextEncoder();
const PROBE_KEY = '00000000-0000-4000-8000-000000000000';

export function commandOrigin(value: unknown): string {
  if (typeof value !== 'string') throw new TypeError('Current origin required');
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.origin !== value)
    throw new TypeError('Invalid current origin');
  return value;
}
export async function commandSha256(value: string): Promise<string> {
  const hash = await globalThis.crypto.subtle.digest('SHA-256', encoder.encode(value));
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}
export function identityText(origin: string, original: CommandIdentity): string {
  return JSON.stringify([
    commandOrigin(origin),
    original.owner_module,
    original.method,
    original.path,
    original.key,
  ]);
}
export async function verifiedCommandIdentity(
  value: unknown,
  currentOrigin: string,
): Promise<CommandIdentity> {
  const row = object(value);
  const original = registeredCommand(row.method, row.path, row.key);
  if (
    row.origin !== commandOrigin(currentOrigin) ||
    row.owner_module !== original.owner_module ||
    row.decoder_kind !== original.decoder_kind ||
    row.identity_sha256 !== (await commandSha256(identityText(currentOrigin, original)))
  )
    throw new TypeError('Frozen command identity differs from this origin or route');
  return original;
}
export function commandRecoveryMode(original: CommandIdentity, body: JsonObject): RecoveryMode {
  if (
    original.owner_module === 'CODING' &&
    (original.decoder_kind === 'APP-CODE-CMD-C46' ||
      original.decoder_kind === 'APP-CODE-CMD-C47' ||
      original.path.endsWith('/accept') ||
      (original.path.endsWith('/resume') && Object.hasOwn(body, 'repository_quiescent_confirmed')))
  )
    return 'QUERY_ONLY';
  return 'REPLAY_SAME_KEY';
}
function binding<T>(
  value: CodeCommandBinding<T>,
  original: CommandIdentity,
): CodeCommandBinding<T> {
  if (
    value.decoder_kind !== original.decoder_kind ||
    typeof value.validate_input !== 'function' ||
    typeof value.decode !== 'function' ||
    !value.success_status.length ||
    new Set(value.success_status).size !== value.success_status.length ||
    value.success_status.some((status) => ![200, 201, 202].includes(status))
  )
    throw new TypeError('Native input/result binding differs from original route');
  // Validate errors before any handle is installed; only native functions survive.
  codeErrorPolicy(value.errors);
  return Object.freeze({
    ...value,
    success_status: Object.freeze([...value.success_status]),
    errors: Object.freeze([...value.errors]),
  });
}
function transmissionErrors(errors: readonly CodeErrorCode[], original: CommandIdentity) {
  const base = codeErrorPolicy([...new Set<CodeErrorCode>([...errors, 'COMMAND_CLOSED'])]);
  return Object.freeze({
    mutationUnknown(code: string, status: number) {
      // These readiness rejections roll back acceptance before the queue changes.
      if (
        ['APP-CODE-CMD-C01', 'APP-CODE-CMD-C05'].includes(original.decoder_kind) &&
        code === 'CONFIG_NOT_READY'
      )
        return false;
      return base.mutationUnknown(code, status);
    },
    decode(code: string, message: string, details: unknown, status: number) {
      const parsed = base.decode(code, message, details, status);
      if (
        code === 'COMMAND_CLOSED' &&
        (parsed?.path !== original.path || parsed?.method !== original.method)
      )
        throw new TypeError('Closed response differs from original command');
      return parsed;
    },
  });
}
function boundedBody(value: unknown): JsonObject {
  if (typeof value !== 'string' || encoder.encode(value).length > COMMAND_BODY_BYTES)
    throw new TypeError('Frozen command body unavailable or too large');
  const parsed: unknown = JSON.parse(value);
  const result = snapshotObject(parsed);
  if (JSON.stringify(result) !== value)
    throw new TypeError('Frozen body is not the original serialized object');
  return result;
}
function action<T>(
  client: ApiClient,
  handle: PreparedCommand,
  frozen: FrozenCodeCommand,
  input: JsonObject,
  original: CommandIdentity,
  native: CodeCommandBinding<T>,
  restored = false,
): FrozenCodeAction<T> {
  const decode = (value: unknown) => native.decode(value, original, input);
  const result_policy: OriginalResultPolicy<T> = Object.freeze({
    decoder_kind: native.decoder_kind,
    success_status: native.success_status,
    errors: native.errors,
    decode,
  });
  return Object.freeze({
    frozen,
    recovery_mode: commandRecoveryMode(original, input),
    result_policy,
    submit: (signal?: AbortSignal) => {
      if (restored && commandRecoveryMode(original, input) === 'QUERY_ONLY')
        return Promise.reject(new TypeError('Original cooperation window is query-only'));
      return client.commit(handle, decode, signal);
    },
  });
}
export async function prepareCodeCommand<T>(
  client: ApiClient,
  path: string,
  body: JsonObject,
  nativeBinding: CodeCommandBinding<T>,
  currentOrigin: string,
): Promise<FrozenCodeAction<T>> {
  const origin = commandOrigin(currentOrigin);
  const scope = registeredCommand('POST', path, PROBE_KEY);
  const native = binding(nativeBinding, scope);
  const input = snapshotObject(body);
  native.validate_input(input, scope);
  const text = JSON.stringify(input);
  if (encoder.encode(text).length > COMMAND_BODY_BYTES)
    throw new TypeError('Command body too large');
  const handle = client.prepare('POST', path, input, {
    idempotent: true,
    success_status: native.success_status,
    error_policy: transmissionErrors(native.errors, scope),
  });
  const exported = client.exportPrepared(handle);
  const original = registeredCommand(exported.method, exported.path, exported.key);
  if (exported.body !== text) throw new TypeError('Command byte snapshot differs');
  const frozen = Object.freeze({
    origin,
    owner_module: original.owner_module,
    method: original.method,
    path: original.path,
    key: original.key,
    decoder_kind: original.decoder_kind,
    body_json: text,
    identity_sha256: await commandSha256(identityText(origin, original)),
    body_sha256: await commandSha256(text),
  });
  return action(client, handle, frozen, input, original, native);
}
export async function restoreCodeCommand<T>(
  client: ApiClient,
  value: unknown,
  nativeBinding: CodeCommandBinding<T>,
  currentOrigin: string,
): Promise<FrozenCodeAction<T>> {
  // Snapshot before hashing/await; storage/caller mutations cannot change bytes.
  const row = snapshotObject(
    exact(value, [
      'origin',
      'owner_module',
      'method',
      'path',
      'key',
      'decoder_kind',
      'identity_sha256',
      'body_json',
      'body_sha256',
    ]),
  );
  const candidate = registeredCommand(row.method, row.path, row.key);
  const native = binding(nativeBinding, candidate);
  const original = await verifiedCommandIdentity(row, currentOrigin);
  const input = boundedBody(row.body_json);
  if (row.body_sha256 !== (await commandSha256(row.body_json as string)))
    throw new TypeError('Frozen command body digest differs');
  native.validate_input(input, original);
  const frozen: FrozenCodeCommand = Object.freeze({
    origin: currentOrigin,
    owner_module: original.owner_module,
    method: original.method,
    path: original.path,
    key: original.key,
    decoder_kind: original.decoder_kind,
    identity_sha256: row.identity_sha256 as string,
    body_json: row.body_json as string,
    body_sha256: row.body_sha256 as string,
  });
  const handle = client.restorePrepared(
    { method: original.method, path: original.path, key: original.key, body: frozen.body_json },
    {
      idempotent: true,
      success_status: native.success_status,
      error_policy: transmissionErrors(native.errors, original),
    },
  );
  return action(client, handle, frozen, input, original, native, true);
}
