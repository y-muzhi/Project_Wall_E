/** Immutable repository 202 bindings shared with original-key recovery. */
import { exact, positiveInteger } from './client.ts';
import type { ApiClient, JsonObject } from './client.ts';
import { nonempty, require } from './decoding.ts';
import { configurationCreateErrors } from './code-configuration-identities.ts';
import { prepareCodeCommand } from './code-command-snapshot.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import type { CommandIdentity } from './code-command-registry.ts';

export type RepositoryAccepted = Readonly<{
  resource_kind: 'REPOSITORY';
  resource_id: number;
  operation_id: number;
  operation_status: 'PENDING';
}>;
export type RegisterRepositoryInput = Readonly<{ name: string; root_path: string }>;
export type RegisterCodeBaselineInput = Readonly<{
  commit_oid: string;
  execution_profile_version_id: number;
}>;

const commandKinds = {
  REGISTER: 'APP-CODE-CMD-C01',
  REFRESH: 'APP-CODE-CMD-C02',
  BASELINE: 'APP-CODE-CMD-C05',
} as const;
type RepositoryCommand = keyof typeof commandKinds;

function originalRoute(original: CommandIdentity, command: RepositoryCommand) {
  require(original.owner_module === 'CODING' && original.method === 'POST');
  require(original.decoder_kind === commandKinds[command]);
  if (command === 'REGISTER') {
    require(original.path === '/api/v1/code-repositories');
    return null;
  }
  const match = /^\/api\/v1\/code-repositories\/([1-9][0-9]*)\/(refresh|snapshots)$/.exec(
    original.path,
  );
  require(match !== null && match[2] === (command === 'REFRESH' ? 'refresh' : 'snapshots'));
  return positiveInteger(Number(match[1]));
}
function registrationInput(value: JsonObject) {
  const row = exact(value, ['name', 'root_path']);
  const name = nonempty(row.name),
    path = nonempty(row.root_path);
  require(name.trim().length > 0 && !name.includes('\0'));
  require(/^[A-Za-z]:[\\/]/.test(path) && !path.includes('\0'));
}
function checkInput(value: JsonObject, original: CommandIdentity, command: RepositoryCommand) {
  const repositoryId = originalRoute(original, command);
  if (command === 'REGISTER') {
    registrationInput(value);
  } else if (command === 'BASELINE') {
    const row = exact(value, ['commit_oid', 'execution_profile_version_id']);
    const oid = nonempty(row.commit_oid);
    require(/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(oid) && !/^0+$/.test(oid));
    positiveInteger(row.execution_profile_version_id);
  } else {
    exact(value, []);
  }
  return repositoryId;
}
function nativeBinding(command: RepositoryCommand): CodeCommandBinding<RepositoryAccepted> {
  return Object.freeze({
    decoder_kind: commandKinds[command],
    success_status: Object.freeze([202] as const),
    errors: Object.freeze([...configurationCreateErrors, 'CONFIG_NOT_READY'] as const),
    validate_input(value: JsonObject, original: CommandIdentity) {
      checkInput(value, original, command);
    },
    decode(value: unknown, original: CommandIdentity, input: JsonObject): RepositoryAccepted {
      const repositoryId = checkInput(input, original, command);
      const row = exact(value, [
        'resource_kind',
        'resource_id',
        'operation_id',
        'operation_status',
      ]);
      require(row.resource_kind === 'REPOSITORY' && row.operation_status === 'PENDING');
      const resource_id = positiveInteger(row.resource_id),
        operation_id = positiveInteger(row.operation_id);
      if (repositoryId !== null) require(resource_id === repositoryId);
      return Object.freeze({
        resource_kind: 'REPOSITORY',
        resource_id,
        operation_id,
        operation_status: 'PENDING',
      });
    },
  });
}
export const REGISTER_REPOSITORY_BINDING = nativeBinding('REGISTER');
export const REFRESH_REPOSITORY_BINDING = nativeBinding('REFRESH');
export const REGISTER_CODE_BASELINE_BINDING = nativeBinding('BASELINE');
export const REPOSITORY_COMMAND_BINDINGS = Object.freeze([
  REGISTER_REPOSITORY_BINDING,
  REFRESH_REPOSITORY_BINDING,
  REGISTER_CODE_BASELINE_BINDING,
]);
export function prepareRegisterRepository(
  client: ApiClient,
  input: RegisterRepositoryInput,
  currentOrigin: string,
) {
  return prepareCodeCommand(
    client,
    '/api/v1/code-repositories',
    { ...input },
    REGISTER_REPOSITORY_BINDING,
    currentOrigin,
  );
}
export function prepareRefreshRepository(
  client: ApiClient,
  repositoryId: number,
  currentOrigin: string,
) {
  positiveInteger(repositoryId);
  return prepareCodeCommand(
    client,
    '/api/v1/code-repositories/' + repositoryId + '/refresh',
    {},
    REFRESH_REPOSITORY_BINDING,
    currentOrigin,
  );
}

export function prepareRegisterCodeBaseline(
  client: ApiClient,
  repositoryId: number,
  input: RegisterCodeBaselineInput,
  currentOrigin: string,
) {
  positiveInteger(repositoryId);
  return prepareCodeCommand(
    client,
    '/api/v1/code-repositories/' + repositoryId + '/snapshots',
    { ...input },
    REGISTER_CODE_BASELINE_BINDING,
    currentOrigin,
  );
}
