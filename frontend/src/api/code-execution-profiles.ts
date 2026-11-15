/** Execution configuration DTOs and original C07 commands; never execution permission. */
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
  text,
} from './decoding.ts';
import { codeErrorDetails } from './code-errors.ts';
import { prepareCodeCommand } from './code-command-snapshot.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import {
  configurationCreateErrors,
  configurationIdentityReadErrors,
} from './code-configuration-identities.ts';
import { readPage } from './pagination.ts';

const MAX = 8 * 1024 * 1024;
function reference(value: unknown) {
  const result = nonempty(value);
  require(result.trim().length > 0 && !/[\u0000-\u001f\u007f]/u.test(result));
  return result;
}
const references = checked(array(reference, MAX), distinct);
const profile = choices(['doubao-v1', 'deepseek-v2', 'deepseek-long-v3'] as const);
const profiles = checked(array(profile, 3), distinct);
const executor = shape({
  version: choices(['1.19.5'] as const),
  binary_ref: reference,
  adapter_contract_version: reference,
  runtime_bundle_ref: reference,
  configuration_policy_version: choices(['OC20-CONFIG-1'] as const),
  runtime_policy_version: choices(['WIN20-ISOLATION-1'] as const),
});
const git = shape({
  version: choices(['2.56.0.windows.4'] as const),
  binary_ref: reference,
  runtime_bundle_ref: reference,
  source_commit: choices(['581291682ad5a238c08c93d1f5bd4518382a3230'] as const),
  protocol_version: choices(['GIT20-LOCAL-1'] as const),
});
const binding = checked(
  shape({
    native_model_id: choices(['walle-code', 'walle-compaction'] as const),
    purpose: choices(['CODE', 'COMPACTION'] as const),
    model_profile_ref: profile,
    model_snapshot_ref: reference,
    price_version_id: positiveInteger,
    input_cap_tokens: positiveInteger,
    context_cap_tokens: positiveInteger,
    output_cap_tokens: positiveInteger,
    admission_ref: reference,
  }),
  (row) => require(row.purpose === (row.native_model_id === 'walle-code' ? 'CODE' : 'COMPACTION')),
);
const models = checked(
  shape({
    primary_profile_ref: profile,
    auxiliary_profile_refs: profiles,
    protocol_version: choices(['OC20-MODEL-1'] as const),
    bindings: array(binding, 2, 2),
  }),
  (row) => {
    require(!row.auxiliary_profile_refs.includes(row.primary_profile_ref));
    distinct(row.bindings.map((item) => item.native_model_id));
    for (const item of row.bindings) {
      require(
        item.model_profile_ref === row.primary_profile_ref ||
          row.auxiliary_profile_refs.includes(item.model_profile_ref),
      );
      if (item.native_model_id === 'walle-code')
        require(item.model_profile_ref === row.primary_profile_ref);
    }
  },
);
function managedPath(value: unknown) {
  const result = reference(value);
  require(!result.includes('\\') && !result.startsWith('/') && !result.includes(':'));
  require(
    result
      .split('/')
      .every(
        (part) => part !== '' && part !== '.' && part !== '..' && part.toLowerCase() !== '.git',
      ),
  );
  return result;
}
export const commandDefinition = shape({
  command_id: reference,
  executable_ref: reference,
  argument_template(value: unknown) {
    require(value !== null && typeof value === 'object');
    return snapshotObject({ value }).value;
  },
  working_directory(value: unknown) {
    return value === '.' ? '.' : managedPath(value);
  },
  purpose: choices(['EXECUTION', 'CHECK', 'SERVICE'] as const),
  timeout_seconds: positiveInteger,
  network_scope_ref: nullable(reference),
});
function selectionPath(value: unknown) {
  if (value === '.') return '.';
  const result = reference(value);
  managedPath(result.endsWith('/') ? result.slice(0, -1) : result);
  return result;
}
const capture = shape({
  content_policy_version: choices(['CONTENT20-STORE-1'] as const),
  product_include_paths: checked(array(selectionPath, MAX), distinct),
  nonproduct_exclude_paths: checked(array(managedExclusion, MAX), distinct),
  new_file_mode: choices(['100644', '100755'] as const),
  secret_policy_ref: reference,
});
function managedExclusion(value: unknown) {
  require(value !== '.');
  return selectionPath(value);
}
function identity(value: unknown) {
  const result = reference(value);
  require(!/[<>\u0080-\u009f]/u.test(result));
  return result;
}
function messageTemplate(value: unknown) {
  const result = text(value);
  require(!result.includes('\0') && !/^[ \t]*WALL-E-Delivery[ \t]*:/im.test(result));
  let i = 0;
  while (i < result.length) {
    const char = result[i];
    if (char === '{' || char === '}') {
      if (result[i + 1] === char) {
        i += 2;
        continue;
      }
      const match = /^\{(?:task_id|candidate_id)(?::)?\}/.exec(result.slice(i));
      require(char === '{' && match !== null);
      i += match[0].length;
    } else i++;
  }
  return result;
}
const delivery = shape({
  author_name: identity,
  author_email: identity,
  committer_name: identity,
  committer_email: identity,
  message_template: messageTemplate,
});
export const executionLimits = shape({
  max_model_requests: positiveInteger,
  max_output_tokens: positiveInteger,
  max_consecutive_failures: positiveInteger,
  max_active_seconds: positiveInteger,
  max_file_bytes: positiveInteger,
  max_snapshot_bytes: positiveInteger,
  max_snapshot_files: positiveInteger,
  max_capture_entries: positiveInteger,
  max_capture_seconds: positiveInteger,
  max_manifest_bytes: positiveInteger,
  max_git_seconds: positiveInteger,
  max_git_output_bytes: positiveInteger,
  max_delivery_window_seconds: checked(positiveInteger, (value) => require(value <= 300)),
  max_check_output_bytes: positiveInteger,
  max_check_cases: positiveInteger,
  max_case_steps: positiveInteger,
  max_case_payload_bytes: positiveInteger,
  query_timeout_seconds: positiveInteger,
  send_timeout_seconds: positiveInteger,
  queue_wait_seconds: positiveInteger,
  graceful_stop_seconds: positiveInteger,
  force_stop_wait_seconds: positiveInteger,
});
const contentFields = {
  executor,
  git,
  models,
  environment: shape({
    python_ref: nullable(reference),
    node_ref: nullable(reference),
    package_manager_refs: references,
    secret_refs: references,
  }),
  commands: array(commandDefinition, MAX),
  capture_rules: capture,
  delivery: nullable(delivery),
  check_set_version_id: positiveInteger,
  limits: executionLimits,
  capability_evidence_refs: references,
};
const contentShape = shape(contentFields);
function contentRules(value: ReturnType<typeof contentShape>) {
  require(
    new TextEncoder().encode(
      JSON.stringify(
        Object.fromEntries(
          Object.entries(value).filter(([key]) => Object.hasOwn(contentFields, key)),
        ),
      ),
    ).byteLength <= MAX,
  );
  distinct(value.commands.map((item) => item.command_id));
  for (const item of value.models.bindings)
    require(item.output_cap_tokens <= value.limits.max_output_tokens);
}
export const executionProfileContent = checked(contentShape, contentRules);
export type ExecutionProfileContent = ReturnType<typeof executionProfileContent>;
export const executionProfileVersion = checked(
  shape({
    id: positiveInteger,
    profile_id: positiveInteger,
    version: positiveInteger,
    ...contentFields,
    created_at: time,
    ready: bool,
    unresolved_capability_codes(value: unknown) {
      const codes = array(reference, 16)(value);
      distinct(codes);
      if (codes.length) codeErrorDetails('CONFIG_NOT_READY', { capability_codes: [...codes] });
      return codes;
    },
  }),
  (row) => {
    contentRules(row);
    require(row.ready === (row.unresolved_capability_codes.length === 0));
    require(row.delivery === null || !row.delivery.message_template.includes('\r'));
  },
);
export type ExecutionProfileVersion = ReturnType<typeof executionProfileVersion>;

function originalProfile(original: CommandIdentity) {
  const match = /^\/api\/v1\/code-execution-profiles\/([1-9][0-9]*)\/versions$/.exec(original.path);
  require(
    original.owner_module === 'CODING' &&
      original.method === 'POST' &&
      original.decoder_kind === 'APP-CODE-CMD-C07' &&
      match !== null,
  );
  return positiveInteger(Number(match[1]));
}
type CreatedVersion = Readonly<{ resource_kind: 'EXECUTION_PROFILE_VERSION'; resource_id: number }>;
export const EXECUTION_PROFILE_VERSION_BINDING: CodeCommandBinding<CreatedVersion> = Object.freeze({
  decoder_kind: 'APP-CODE-CMD-C07',
  success_status: Object.freeze([201] as const),
  errors: configurationCreateErrors,
  validate_input(value: JsonObject, original: CommandIdentity) {
    originalProfile(original);
    executionProfileContent(value);
  },
  decode(value: unknown, original: CommandIdentity, input: JsonObject) {
    originalProfile(original);
    executionProfileContent(input);
    const row = exact(value, ['resource_kind', 'resource_id']);
    require(row.resource_kind === 'EXECUTION_PROFILE_VERSION');
    return Object.freeze({
      resource_kind: 'EXECUTION_PROFILE_VERSION' as const,
      resource_id: positiveInteger(row.resource_id),
    });
  },
});
export function prepareExecutionProfileVersion(
  client: ApiClient,
  profileId: number,
  content: ExecutionProfileContent,
  origin: string,
) {
  positiveInteger(profileId);
  executionProfileContent(content);
  return prepareCodeCommand(
    client,
    '/api/v1/code-execution-profiles/' + profileId + '/versions',
    snapshotObject(content),
    EXECUTION_PROFILE_VERSION_BINDING,
    origin,
  );
}
export async function readExecutionProfileVersion(
  client: ApiClient,
  id: number,
  signal?: AbortSignal,
) {
  positiveInteger(id);
  const result = await client.read(
    '/api/v1/code-execution-profile-versions/' + id,
    executionProfileVersion,
    [],
    signal,
    configurationIdentityReadErrors,
  );
  if (result.data.id !== id || result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
export async function readExecutionProfileVersions(
  client: ApiClient,
  profileId: number,
  page = 1,
  signal?: AbortSignal,
) {
  positiveInteger(profileId);
  const result = await readPage(
    client,
    '/api/v1/code-execution-profiles/' + profileId + '/versions',
    executionProfileVersion,
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    configurationIdentityReadErrors,
  );
  let previous = Number.POSITIVE_INFINITY;
  for (const row of result.data.items) {
    if (row.profile_id !== profileId || row.version >= previous) throw new ApiUnknown(false);
    previous = row.version;
  }
  return result;
}
