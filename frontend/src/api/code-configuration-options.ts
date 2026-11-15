/** Exact DTOs for the immutable Git, Profile, content policy and managed scope catalogue.
 * Other registered kinds have no items until their real preparation is implemented.
 */
import { ApiUnknown } from './client.ts';
import type { ApiClient } from './client.ts';
import { array, checked, choices, nonempty, require, shape } from './decoding.ts';
import { configurationIdentityReadErrors } from './code-configuration-identities.ts';
import { readPage } from './pagination.ts';

export const CONFIGURATION_OPTION_KINDS = Object.freeze([
  'EXECUTOR',
  'MODEL',
  'RUNTIME',
  'COMMAND',
  'RUNNER',
  'SCOPE',
  'PRICE',
  'SECRET_REF',
  'CAPABILITY',
  'CONTENT_POLICY',
  'GIT',
  'CASE_PACK',
] as const);
export type ConfigurationOptionKind = (typeof CONFIGURATION_OPTION_KINDS)[number];
const kind = choices(CONFIGURATION_OPTION_KINDS);
const capability = choices([
  'Q20-GIT',
  'Q20-WINDOWS',
  'Q20-MODEL',
  'Q20-CONTENT',
  'Q20-CONFIG',
] as const);
const fields = {
  option_id: nonempty,
  kind,
  label: nonempty,
  unresolved_capability_codes: array(capability, 3, 1),
};
// Boolean values are decoded explicitly; choices() intentionally accepts enums only.
const notReady = (value: unknown): false => {
  require(value === false);
  return false;
};
const profiles = choices(['doubao-v1', 'deepseek-v2', 'deepseek-long-v3'] as const);
const model = checked(
  shape({
    ...fields,
    ready: notReady,
    value: shape({ model_profile_ref: profiles }),
  }),
  (row) => {
    require(row.kind === 'MODEL' && row.option_id === 'model:' + row.value.model_profile_ref);
    require(
      row.unresolved_capability_codes.length === 1 &&
        row.unresolved_capability_codes[0] === 'Q20-MODEL',
    );
  },
);
const git = checked(
  shape({
    ...fields,
    ready: notReady,
    value: shape({
      version: choices(['2.56.0.windows.4'] as const),
      source_commit: choices(['581291682ad5a238c08c93d1f5bd4518382a3230'] as const),
      protocol_version: choices(['GIT20-LOCAL-1'] as const),
      binary_ref(value: unknown) {
        const ref = nonempty(value);
        require(/^git-binary:sha256:[0-9a-f]{64}$/.test(ref));
        return ref;
      },
      runtime_bundle_ref: choices([
        'git-bundle:sha256:4e888e998f1f08e8b78559c212d30c51aaa3cc30e85b9cdafcf7b44249a4e215',
      ] as const),
    }),
  }),
  (row) => {
    require(row.kind === 'GIT' && row.option_id === 'git:mingit-' + row.value.version);
    require(
      row.unresolved_capability_codes.length === 2 &&
        row.unresolved_capability_codes[0] === 'Q20-GIT' &&
        row.unresolved_capability_codes[1] === 'Q20-WINDOWS',
    );
  },
);
const contentPolicy = checked(
  shape({
    ...fields,
    ready: notReady,
    value: shape({
      content_policy_version: choices(['CONTENT20-STORE-1'] as const),
      secret_policy_ref: choices(['CONTENT20-SECRETS-1'] as const),
    }),
  }),
  (row) => {
    require(
      row.kind === 'CONTENT_POLICY' &&
        row.option_id === 'content-policy:' + row.value.secret_policy_ref,
    );
    require(
      row.unresolved_capability_codes.length === 3 &&
        row.unresolved_capability_codes[0] === 'Q20-CONTENT' &&
        row.unresolved_capability_codes[1] === 'Q20-GIT' &&
        row.unresolved_capability_codes[2] === 'Q20-WINDOWS',
    );
  },
);
const managedScope = checked(
  shape({
    ...fields,
    ready: notReady,
    value: shape({
      scope_kind: choices(['READ_ROOT'] as const),
      scope_ref: choices(['READ20-WORKSPACE-1', 'READ20-BASIS-1'] as const),
    }),
  }),
  (row) => {
    require(row.kind === 'SCOPE' && row.option_id === 'scope:' + row.value.scope_ref);
    require(
      row.unresolved_capability_codes.length === 2 &&
        row.unresolved_capability_codes[0] === 'Q20-CONFIG' &&
        row.unresolved_capability_codes[1] === 'Q20-WINDOWS',
    );
  },
);
export function configurationOption(value: unknown) {
  if (typeof value === 'object' && value !== null && 'kind' in value) {
    if (value.kind === 'MODEL') return model(value);
    if (value.kind === 'GIT') return git(value);
    if (value.kind === 'CONTENT_POLICY') return contentPolicy(value);
    if (value.kind === 'SCOPE') return managedScope(value);
  }
  throw new TypeError('Catalogue item kind has no prepared decoder in this resource release');
}
export type ConfigurationOption = ReturnType<typeof configurationOption>;
export async function readConfigurationOptions(
  client: ApiClient,
  requestedKind: ConfigurationOptionKind,
  page = 1,
  signal?: AbortSignal,
) {
  kind(requestedKind);
  const response = await readPage(
    client,
    '/api/v1/code-configuration-options',
    checked(configurationOption, (row) => require(row.kind === requestedKind)),
    (row) => row.option_id,
    [
      ['kind', requestedKind],
      ['page', String(page)],
    ],
    page,
    signal,
    configurationIdentityReadErrors,
  );
  const ids = response.data.items.map((row) => row.option_id);
  // All identities registered by the initial release are ASCII.
  if (!ids.every((value, index) => index === 0 || ids[index - 1]! < value)) {
    throw new ApiUnknown(false);
  }
  return response;
}
