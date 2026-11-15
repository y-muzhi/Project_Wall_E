import { ApiUnknown, stableJson } from './client.ts';
import type { ApiClient } from './client.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { normalizedName } from './code-configuration-identities.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { commandDefinition } from './code-execution-profiles.ts';
import { formatCnyBalance, money, moneyMicro } from './code-values.ts';
import {
  array,
  bool,
  checked,
  choices,
  distinct,
  id,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';

export const testingProfilePath = '/api/v1/testing-profile-versions';
export const testingAuthorizationPath = '/api/v1/testing-authorizations';
const readErrors = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
  'PERMISSION_NOT_GRANTED',
] as const;
const readErrorPolicy = codeErrorPolicy(readErrors);
const createErrors = [
  ...readErrors,
  'OPERATION_CONFLICT',
  'COMMAND_CLOSED',
  'CHECK_CONFIGURATION_INVALID',
] as const;

const reasons = checked(array(nonempty, 32), (values) => {
  distinct(values);
  require(values.every((value, index) => index === 0 || values[index - 1]! < value));
});
const readiness = { ready: bool, reason_codes: reasons };
function checkReady(value: { ready: boolean; reason_codes: readonly string[] }) {
  require(value.ready === (value.reason_codes.length === 0));
}
const resourceRef = checked(nonempty, (value) => require([...value].length <= 512));
const refs = checked(array(resourceRef, 256, 1), distinct);
export const testingModelBinding = shape({
  model_profile_ref: resourceRef,
  model_snapshot_ref: resourceRef,
  price_version_id: id,
  input_cap_tokens: id,
  output_cap_tokens: id,
  admission_ref: resourceRef,
});
const limits = shape({
  max_model_requests: id,
  max_active_seconds: id,
  max_check_output_bytes: id,
  max_check_cases: id,
  max_case_steps: id,
  max_case_payload_bytes: id,
  max_input_bytes: checked(id, (value) => require(value <= 8 * 1024 * 1024)),
  query_timeout_seconds: id,
  send_timeout_seconds: id,
  graceful_stop_seconds: id,
  force_stop_wait_seconds: id,
});
const profileFields = {
  name(value: unknown) {
    const name = normalizedName(value);
    require([...name].length <= 200);
    return name;
  },
  runner_refs: refs,
  environment_refs: refs,
  commands: checked(array(commandDefinition, 256), (commands) => {
    distinct(commands.map((command) => command.command_id));
    require(commands.every((command) => command.purpose !== 'EXECUTION'));
  }),
  model_binding: nullable(testingModelBinding),
  limits,
  admission_refs: refs,
};
const profileInput = shape(profileFields);
export const testingProfile = checked(
  shape({ id, version: id, created_at: time, ...profileFields, ...readiness }),
  checkReady,
);
export type TestingProfile = ReturnType<typeof testingProfile>;
export type TestingProfileContent = ReturnType<typeof profileInput>;
export type TestingLimits = TestingProfileContent['limits'];
const scope = choices(['TASK', 'PACK_VALIDATION'] as const);
export type TestingAuthorizationScope = ReturnType<typeof scope>;
const approvalFields = { profile_version_id: id, scope_kind: scope, budget_limit_cny: money };
const approvalInput = shape(approvalFields);
const authorization = checked(
  shape({
    id,
    testing_task_id: nullable(id),
    ...approvalFields,
    validation_id: nullable(id),
    status: choices(['APPROVED_UNBOUND', 'EFFECTIVE', 'RETIRED'] as const),
    actor_ref: nonempty,
    approved_at: time,
    ...readiness,
  }),
  (value) => {
    checkReady(value);
    require(value.budget_limit_cny === formatCnyBalance(moneyMicro(value.budget_limit_cny)));
    if (value.scope_kind === 'PACK_VALIDATION') {
      require(value.testing_task_id === null && moneyMicro(value.budget_limit_cny) === 0n);
    } else {
      require(value.validation_id === null);
    }
    if (value.status === 'APPROVED_UNBOUND')
      require(value.testing_task_id === null && value.validation_id === null);
    if (value.status === 'EFFECTIVE')
      require(value.testing_task_id !== null || value.validation_id !== null);
    if (value.status === 'RETIRED') require(!value.ready);
  },
);
export type TestingAuthorization = ReturnType<typeof authorization>;

const profileBody = shape({ profile_content: profileInput });
const profileBinding: CodeCommandBinding<TestingProfile> = {
  decoder_kind: 'APP-TEST-CMD-C01',
  success_status: [201],
  errors: createErrors,
  validate_input(input) {
    profileBody(input);
  },
  decode(value, original, input) {
    require(original.path === testingProfilePath && original.owner_module === 'TESTING');
    const result = testingProfile(value);
    const fixed = profileBody(input).profile_content;
    require(
      Object.keys(profileFields).every((field) => {
        const key = field as keyof typeof profileFields;
        return stableJson(result[key]) === stableJson(fixed[key]);
      }),
    );
    return result;
  },
};
const authorizationBinding: CodeCommandBinding<TestingAuthorization> = {
  decoder_kind: 'APP-TEST-CMD-C04',
  success_status: [201],
  errors: [...createErrors, 'AUTHORIZATION_NOT_APPLICABLE'],
  validate_input(input) {
    approvalInput(input);
  },
  decode(value, original, input) {
    require(original.path === testingAuthorizationPath && original.owner_module === 'TESTING');
    const result = authorization(value);
    const fixed = approvalInput(input);
    require(
      result.status === 'APPROVED_UNBOUND' &&
        result.profile_version_id === fixed.profile_version_id &&
        result.scope_kind === fixed.scope_kind &&
        moneyMicro(result.budget_limit_cny) === moneyMicro(fixed.budget_limit_cny),
    );
    return result;
  },
};
export const TESTING_POLICY_BINDINGS = [profileBinding, authorizationBinding] as const;

export async function readTestingProfiles(
  client: ApiClient,
  page: number,
  name: string | null,
  signal?: AbortSignal,
) {
  const filter = name === null ? null : normalizedName(name);
  const parameters: [string, string][] = [['page', String(page)]];
  if (filter !== null) parameters.push(['name', filter]);
  const response = await readPage(
    client,
    testingProfilePath,
    testingProfile,
    (item) => item.id,
    parameters,
    page,
    signal,
    readErrorPolicy,
  );
  if (
    !response.data.items.every(
      (row, index, items) =>
        (index === 0 || items[index - 1]!.id < row.id) && (filter === null || row.name === filter),
    )
  )
    throw new ApiUnknown(false);
  return response;
}

export function readTestingProfile(client: ApiClient, profileId: number, signal?: AbortSignal) {
  return client.read(
    testingProfilePath + '/' + id(profileId),
    checked(testingProfile, (row) => require(row.id === profileId)),
    [],
    signal,
    readErrorPolicy,
  );
}

export function readTestingAuthorization(
  client: ApiClient,
  authorizationId: number,
  signal?: AbortSignal,
) {
  return client.read(
    testingAuthorizationPath + '/' + id(authorizationId),
    checked(authorization, (row) => require(row.id === authorizationId)),
    [],
    signal,
    readErrorPolicy,
  );
}
