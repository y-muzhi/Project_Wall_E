/** Authorization records describe approval; only task application can make them effective. */
import { ApiUnknown, exact, positiveInteger, snapshotObject } from './client.ts';
import type { ApiClient, JsonObject } from './client.ts';
import {
  array,
  bool,
  checked,
  choices,
  distinct,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { executionLimits } from './code-execution-profiles.ts';
import {
  configurationCreateErrors,
  configurationIdentityReadErrors,
} from './code-configuration-identities.ts';
import { prepareCodeCommand } from './code-command-snapshot.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { readPage } from './pagination.ts';

export const AUTHORIZATION_STATUSES = Object.freeze([
  'APPROVED_UNBOUND',
  'BOUND_PENDING_APPLY',
  'EFFECTIVE',
  'APPLY_FAILED',
  'APPLY_UNKNOWN',
  'RETIRED',
] as const);
export type AuthorizationStatus = (typeof AUTHORIZATION_STATUSES)[number];
const status = choices(AUTHORIZATION_STATUSES);
function reference(value: unknown) {
  const result = nonempty(value);
  require(result.trim().length > 0 && !/[\u0000-\u001f\u007f]/u.test(result));
  return result;
}
const references = checked(array(reference, 8 * 1024 * 1024), distinct);
export const authorizationScope = shape({
  read_roots: references,
  write_workspace_only: checked(bool, (value) => require(value)),
  allowed_command_ids: references,
  network_targets: references,
  model_profile_refs: references,
  allow_local_delivery: bool,
  limits: executionLimits,
});
export type AuthorizationScope = ReturnType<typeof authorizationScope>;
export const authorizationGrant = checked(
  shape({
    id: positiveInteger,
    task_id: nullable(positiveInteger),
    profile_version_id: positiveInteger,
    scope: authorizationScope,
    status,
    approved_at: time,
    actor_ref: reference,
  }),
  (row) => {
    if (row.status === 'APPROVED_UNBOUND') require(row.task_id === null);
    else if (row.status !== 'RETIRED') require(row.task_id !== null);
  },
);
export type AuthorizationGrant = ReturnType<typeof authorizationGrant>;
const approval = shape({ profile_version_id: positiveInteger, scope: authorizationScope });
function originalApproval(original: CommandIdentity) {
  require(
    original.owner_module === 'CODING' &&
      original.method === 'POST' &&
      original.path === '/api/v1/code-authorizations' &&
      original.decoder_kind === 'APP-CODE-CMD-C15',
  );
}
type Approved = Readonly<{ resource_kind: 'AUTHORIZATION'; resource_id: number }>;
export const AUTHORIZATION_BINDING: CodeCommandBinding<Approved> = Object.freeze({
  decoder_kind: 'APP-CODE-CMD-C15',
  success_status: Object.freeze([201] as const),
  errors: configurationCreateErrors,
  validate_input(value: JsonObject, original: CommandIdentity) {
    originalApproval(original);
    approval(value);
  },
  decode(value: unknown, original: CommandIdentity, input: JsonObject) {
    originalApproval(original);
    approval(input);
    const row = exact(value, ['resource_kind', 'resource_id']);
    require(row.resource_kind === 'AUTHORIZATION');
    return Object.freeze({
      resource_kind: 'AUTHORIZATION' as const,
      resource_id: positiveInteger(row.resource_id),
    });
  },
});
export function prepareAuthorization(
  client: ApiClient,
  profileVersionId: number,
  scope: AuthorizationScope,
  origin: string,
) {
  positiveInteger(profileVersionId);
  authorizationScope(scope);
  return prepareCodeCommand(
    client,
    '/api/v1/code-authorizations',
    snapshotObject({ profile_version_id: profileVersionId, scope }),
    AUTHORIZATION_BINDING,
    origin,
  );
}
export async function readAuthorization(client: ApiClient, id: number, signal?: AbortSignal) {
  positiveInteger(id);
  const result = await client.read(
    '/api/v1/code-authorizations/' + id,
    authorizationGrant,
    [],
    signal,
    configurationIdentityReadErrors,
  );
  if (result.data.id !== id || result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
export type AuthorizationFilters = Readonly<{ task_id?: number; status?: AuthorizationStatus }>;
export async function readAuthorizations(
  client: ApiClient,
  page = 1,
  filters: AuthorizationFilters = {},
  signal?: AbortSignal,
) {
  const query: [string, string][] = [['page', String(page)]];
  if (filters.task_id !== undefined)
    query.push(['task_id', String(positiveInteger(filters.task_id))]);
  if (filters.status !== undefined) query.push(['status', status(filters.status)]);
  const result = await readPage(
    client,
    '/api/v1/code-authorizations',
    authorizationGrant,
    (row) => row.id,
    query,
    page,
    signal,
    configurationIdentityReadErrors,
  );
  let previous: AuthorizationGrant | undefined;
  for (const row of result.data.items) {
    if (filters.task_id !== undefined && row.task_id !== filters.task_id)
      throw new ApiUnknown(false);
    if (filters.status !== undefined && row.status !== filters.status) throw new ApiUnknown(false);
    if (
      previous &&
      (row.approved_at > previous.approved_at ||
        (row.approved_at === previous.approved_at && row.id >= previous.id))
    )
      throw new ApiUnknown(false);
    previous = row;
  }
  return result;
}
