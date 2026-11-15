/** Native DTOs for the two actual synchronous configuration identity commands. */
import { exact, positiveInteger } from './client.ts';
import type { ApiClient, JsonObject } from './client.ts';
import { nonempty, nullable, require, shape, text } from './decoding.ts';
import { prepareCodeCommand } from './code-command-snapshot.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { codeErrorPolicy } from './code-errors.ts';
import type { CodeErrorCode } from './code-errors.ts';

export type ConfigurationIdentityKind = 'EXECUTION_PROFILE' | 'CHECK_SET';
export type CreatedConfigurationIdentity = Readonly<{
  resource_kind: ConfigurationIdentityKind;
  resource_id: number;
}>;
const EXECUTION = Object.freeze({
  kind: 'EXECUTION_PROFILE' as const,
  path: '/api/v1/code-execution-profiles',
  decoder_kind: 'APP-CODE-CMD-C09',
});
const CHECKS = Object.freeze({
  kind: 'CHECK_SET' as const,
  path: '/api/v1/code-check-sets',
  decoder_kind: 'APP-CODE-CMD-C10',
});
export function configurationCollection(kind: ConfigurationIdentityKind) {
  if (kind === 'EXECUTION_PROFILE') return EXECUTION;
  if (kind === 'CHECK_SET') return CHECKS;
  throw new TypeError('Unknown native configuration identity collection');
}
export const configurationCreateErrors = Object.freeze([
  'INVALID_INPUT',
  'NOT_FOUND',
  'RESOURCE_CONFLICT',
  'SOURCE_CHANGED',
  'SOURCE_BUSY',
  'SOURCE_UNSUPPORTED',
  'REPOSITORY_UNSUPPORTED',
  'CONTENT_NOT_READY',
  'PRECONDITION_FAILED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
  'OPERATION_CONFLICT',
  'OPERATION_IN_PROGRESS',
  'COMMAND_CLOSED',
] satisfies CodeErrorCode[]);
export const configurationIdentityReadErrors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONTENT_NOT_READY',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);

// Match backend normalize_text's explicit Unicode White_Space set, including
// U+0085 and excluding BOM; String.trim() has a different definition.
const WHITESPACE =
  '[\\u0009-\\u000d\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
export function normalizedName(value: unknown): string {
  const name = text(value);
  require(!name.includes('\0'));
  const normalized = name
    .replace(/\r\n?/g, '\n')
    .replace(new RegExp('^' + WHITESPACE + '+|' + WHITESPACE + '+$', 'g'), '');
  require(normalized.length > 0);
  return normalized;
}
export const configurationIdentityRow = shape({
  id: positiveInteger,
  name(value: unknown) {
    const name = nonempty(value);
    require(normalizedName(name) === name);
    return name;
  },
  latest_version_id: nullable(positiveInteger),
});
export type ConfigurationIdentityRow = ReturnType<typeof configurationIdentityRow>;

function originalFor(kind: ConfigurationIdentityKind, original: CommandIdentity) {
  const collection = configurationCollection(kind);
  require(
    original.owner_module === 'CODING' &&
      original.method === 'POST' &&
      original.path === collection.path &&
      original.decoder_kind === collection.decoder_kind,
  );
  return collection;
}
export function configurationIdentityBinding(
  kind: ConfigurationIdentityKind,
): CodeCommandBinding<CreatedConfigurationIdentity> {
  const collection = configurationCollection(kind);
  return Object.freeze({
    decoder_kind: collection.decoder_kind,
    success_status: Object.freeze([201] as const),
    errors: configurationCreateErrors,
    validate_input(value: JsonObject, original: CommandIdentity) {
      originalFor(kind, original);
      normalizedName(exact(value, ['name']).name);
    },
    decode(value: unknown, original: CommandIdentity, input: JsonObject) {
      originalFor(kind, original);
      normalizedName(exact(input, ['name']).name);
      const row = exact(value, ['resource_kind', 'resource_id']);
      require(row.resource_kind === kind);
      return Object.freeze({ resource_kind: kind, resource_id: positiveInteger(row.resource_id) });
    },
  });
}
export const CONFIGURATION_IDENTITY_BINDINGS = Object.freeze([
  configurationIdentityBinding('EXECUTION_PROFILE'),
  configurationIdentityBinding('CHECK_SET'),
]);
export function prepareConfigurationIdentity(
  client: ApiClient,
  kind: ConfigurationIdentityKind,
  name: string,
  currentOrigin: string,
) {
  const collection = configurationCollection(kind);
  return prepareCodeCommand(
    client,
    collection.path,
    { name },
    configurationIdentityBinding(kind),
    currentOrigin,
  );
}
