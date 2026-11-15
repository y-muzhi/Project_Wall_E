import { ApiUnknown, stableJson } from './client.ts';
import type { ApiClient } from './client.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { normalizedName } from './code-configuration-identities.ts';
import {
  array,
  checked,
  choices,
  count,
  distinct,
  id,
  nonempty,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';

export const testingPlansPath = '/api/v1/test-plans';
const versionPath = '/api/v1/test-plan-versions/';
const readErrors = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
  'PERMISSION_NOT_GRANTED',
] as const;
const policy = codeErrorPolicy(readErrors);
const planName = checked(normalizedName, (name) => require([...name].length <= 200));
const plan = shape({
  id,
  name: checked(planName, (name) => require(name.length > 0)),
  created_at: time,
  versions_count: count,
});
const source = shape({ document_id: id, revision_id: id });
const basis = shape({ document_id: id, revision_id: id, quote: nonempty });
const identityArray = checked(array(nonempty, 4096), distinct);
const behavior = shape({
  behavior_id: nonempty,
  name: nonempty,
  basis_refs: array(basis, 256, 1),
  stages: checked(
    array(choices(['BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE'] as const), 4, 1),
    distinct,
  ),
  importance: choices(['BLOCKER', 'CRITICAL', 'NORMAL'] as const),
  mode: choices(['AUTO', 'MANUAL', 'NOT_APPLICABLE', 'UNCOVERED'] as const),
  case_ids: identityArray,
  explanation: text,
});
const testDriver = choices(['CLI', 'HTTP', 'BROWSER'] as const);
function locator(value: unknown) {
  const row = objectField(value);
  return row.kind === 'TEST_ID'
    ? shape({ kind: choices(['TEST_ID']), value: nonempty })(value)
    : shape({ kind: choices(['ROLE']), value: nonempty, name: nullable(text) })(value);
}
function objectField(value: unknown) {
  require(typeof value === 'object' && value !== null && !Array.isArray(value));
  return value as Record<string, unknown>;
}
export function testPlanStep(value: unknown) {
  const row = objectField(value);
  const fields = { step_id: nonempty };
  switch (row.op) {
    case 'RUN':
      return shape({
        ...fields,
        op: choices(['RUN']),
        command_id: nonempty,
        stdin: text,
      })(row);
    case 'REQUEST':
      return shape({
        ...fields,
        op: choices(['REQUEST']),
        endpoint_ref: nonempty,
        path: nonempty,
        method: nonempty,
        headers: objectField,
        body: text,
      })(row);
    case 'NAVIGATE':
      return shape({
        ...fields,
        op: choices(['NAVIGATE']),
        endpoint_ref: nonempty,
        path: nonempty,
      })(row);
    case 'CLICK':
      return shape({ ...fields, op: choices(['CLICK']), locator })(row);
    case 'FILL':
    case 'SELECT':
    case 'PRESS':
      return shape({
        ...fields,
        op: choices(['FILL', 'SELECT', 'PRESS'] as const),
        locator,
        value: text,
      })(row);
    default:
      throw new TypeError('Unsupported stored test step');
  }
}
export function testPlanAssertion(value: unknown) {
  const row = objectField(value);
  const fields = { assertion_id: nonempty, expected: (item: unknown) => item };
  switch (row.op) {
    case 'EXIT_CODE':
    case 'STDOUT_BYTES':
      return shape({ ...fields, op: choices(['EXIT_CODE', 'STDOUT_BYTES'] as const) })(row);
    case 'STATUS':
    case 'BODY_BYTES':
      return shape({
        ...fields,
        op: choices(['STATUS', 'BODY_BYTES'] as const),
        step_id: nonempty,
      })(row);
    case 'HEADER':
      return shape({ ...fields, op: choices(['HEADER']), step_id: nonempty, header: nonempty })(
        row,
      );
    case 'JSON_POINTER':
      return shape({ ...fields, op: choices(['JSON_POINTER']), step_id: nonempty, pointer: text })(
        row,
      );
    case 'VISIBLE':
    case 'TEXT':
    case 'COUNT':
      return shape({ ...fields, op: choices(['VISIBLE', 'TEXT', 'COUNT'] as const), locator })(row);
    default:
      throw new TypeError('Unsupported stored test assertion');
  }
}
const testCase = checked(
  shape({
    case_id: nonempty,
    name: nonempty,
    behavior_ids: checked(array(nonempty, 4096, 1), distinct),
    visibility: choices(['PUBLIC', 'HELD_OUT'] as const),
    driver_kind: testDriver,
    steps: array(testPlanStep, 256),
    assertions: array(testPlanAssertion, 256),
    timeout_seconds: id,
  }),
  (row) => {
    distinct(row.steps.map((item) => item.step_id));
    distinct(row.assertions.map((item) => item.assertion_id));
    require(row.timeout_seconds <= 3600);
  },
);

export const testingBasisFields = {
  requirement_id: id,
  document_id: id,
  design_revision_id: id,
  material_refs: array(source, 256),
};
const planContentFields = {
  ...testingBasisFields,
  behaviors: array(behavior, 4096),
  cases: array(testCase, 4096),
  unresolved_questions: array(nonempty, 256),
};
export const testPlanContent = shape(planContentFields);
export type TestPlanContent = ReturnType<typeof testPlanContent>;
export type TestPlanStep = ReturnType<typeof testPlanStep>;
export type TestPlanAssertion = ReturnType<typeof testPlanAssertion>;

export function planContentOf(value: TestPlanVersion): TestPlanContent {
  return testPlanContent(
    Object.fromEntries(
      Object.keys(planContentFields).map((key) => [key, value[key as keyof TestPlanContent]]),
    ),
  );
}

const version = checked(
  shape({
    id,
    plan_id: id,
    version: id,
    ...planContentFields,
    status: choices(['DRAFT', 'PUBLISHED', 'REVOKED'] as const),
    state_version: id,
    created_at: time,
    published_at: nullable(time),
    revoked_at: nullable(time),
    revocation_reason: nullable(nonempty),
  }),
  (row) => {
    distinct(row.material_refs.map((item) => item.document_id));
    distinct(row.behaviors.map((item) => item.behavior_id));
    distinct(row.cases.map((item) => item.case_id));
    require((row.status === 'DRAFT') === (row.published_at === null));
    require((row.status === 'REVOKED') === (row.revoked_at !== null));
    require((row.revoked_at === null) === (row.revocation_reason === null));
    if (row.published_at !== null) require(row.created_at <= row.published_at);
    if (row.revoked_at !== null)
      require(row.published_at !== null && row.published_at <= row.revoked_at);
  },
);
export type TestPlan = ReturnType<typeof plan>;
export type TestPlanVersion = ReturnType<typeof version>;

const created = shape({ plan_id: id });
export const CREATE_TEST_PLAN: CodeCommandBinding<ReturnType<typeof created>> = {
  decoder_kind: 'APP-TEST-CMD-C06',
  success_status: [201],
  errors: [...readErrors, 'COMMAND_CLOSED', 'OPERATION_CONFLICT'],
  validate_input(value) {
    shape({ name: planName })(value);
  },
  decode(value, original) {
    require(original.owner_module === 'TESTING' && original.path === testingPlansPath);
    return created(value);
  },
};

const controlInput = shape({ expected_state_version: id });
const reasonField = checked(normalizedName, (value) => require([...value].length <= 2000));
const revokeInput = shape({ expected_state_version: id, reason: reasonField });
export function testingPlanControlPath(versionId: number, action: 'publish' | 'revoke') {
  return versionPath + id(versionId) + '/' + action;
}

function controlBinding(action: 'publish' | 'revoke'): CodeCommandBinding<TestPlanVersion> {
  const publish = action === 'publish';
  const errors = [
    ...readErrors,
    'COMMAND_CLOSED',
    'OPERATION_CONFLICT',
    'VERSION_CONFLICT',
    'INVALID_STATE',
  ] as const;
  return {
    decoder_kind: publish ? 'APP-TEST-CMD-C13' : 'APP-TEST-CMD-C14',
    success_status: [200],
    errors: publish ? [...errors, 'BASIS_REF_INVALID', 'CHECK_CONFIGURATION_INVALID'] : errors,
    validate_input(value) {
      if (publish) controlInput(value);
      else revokeInput(value);
    },
    decode(value, original, input) {
      const result = version(value);
      const fixed = publish ? controlInput(input) : revokeInput(input);
      require(
        original.owner_module === 'TESTING' &&
          original.path === testingPlanControlPath(result.id, action) &&
          result.state_version === fixed.expected_state_version + 1 &&
          result.status === (publish ? 'PUBLISHED' : 'REVOKED'),
      );
      if ('reason' in fixed) require(result.revocation_reason === fixed.reason);
      return result;
    },
  };
}
export function testingPlanVersionsPath(planId: number) {
  return testingPlansPath + '/' + id(planId) + '/versions';
}

export function testingPlanDraftPath(versionId: number) {
  return versionPath + id(versionId) + '/draft';
}

function draftBinding(create: boolean): CodeCommandBinding<TestPlanVersion> {
  const input = create
    ? shape({ plan_content: testPlanContent })
    : shape({ plan_content: testPlanContent, expected_state_version: id });
  return {
    decoder_kind: create ? 'APP-TEST-CMD-C09' : 'APP-TEST-CMD-C12',
    success_status: create ? [201] : [200],
    errors: [
      ...readErrors,
      'COMMAND_CLOSED',
      'OPERATION_CONFLICT',
      'BASIS_REF_INVALID',
      ...(create ? [] : (['VERSION_CONFLICT', 'INVALID_STATE'] as const)),
    ],
    validate_input(value) {
      input(value);
    },
    decode(value, original, request) {
      const result = version(value);
      const fixed = input(request);
      require(original.owner_module === 'TESTING' && result.status === 'DRAFT');
      if ('expected_state_version' in fixed) {
        require(original.path === testingPlanDraftPath(result.id));
        require(result.state_version === id(fixed.expected_state_version) + 1);
      } else {
        require(original.path === testingPlanVersionsPath(result.plan_id));
        require(result.state_version === 1);
      }
      require(stableJson(planContentOf(result)) === stableJson(fixed.plan_content));
      return result;
    },
  };
}

export const TEST_PLAN_DRAFT_BINDINGS = [draftBinding(true), draftBinding(false)] as const;

export const TEST_PLAN_CONTROL_BINDINGS = [
  controlBinding('publish'),
  controlBinding('revoke'),
] as const;
export const TEST_PLAN_RECOVERY_KINDS = new Set([
  'APP-TEST-CMD-C06',
  'APP-TEST-CMD-C09',
  'APP-TEST-CMD-C12',
  'APP-TEST-CMD-C13',
  'APP-TEST-CMD-C14',
  'APP-TEST-CMD-C15',
  'APP-TEST-CMD-C18',
  'APP-TEST-CMD-C19',
  'APP-TEST-CMD-C21',
  'APP-TEST-CMD-C22',
]);

function ascending(items: readonly { id: number }[]) {
  if (!items.every((row, index) => index === 0 || items[index - 1]!.id < row.id))
    throw new ApiUnknown(false);
}

export async function readTestingPlans(client: ApiClient, page: number, signal?: AbortSignal) {
  const result = await readPage(
    client,
    testingPlansPath,
    plan,
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
  ascending(result.data.items);
  return result;
}
export function readTestingPlan(client: ApiClient, planId: number, signal?: AbortSignal) {
  return client.read(
    testingPlansPath + '/' + id(planId),
    checked(plan, (row) => require(row.id === planId)),
    [],
    signal,
    policy,
  );
}
export async function readTestingPlanVersions(
  client: ApiClient,
  planId: number,
  page: number,
  signal?: AbortSignal,
) {
  const result = await readPage(
    client,
    testingPlanVersionsPath(planId),
    checked(version, (row) => require(row.plan_id === planId)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
  ascending(result.data.items);
  return result;
}
export function readTestingPlanVersion(
  client: ApiClient,
  planId: number,
  versionId: number,
  signal?: AbortSignal,
) {
  return client.read(
    versionPath + id(versionId),
    checked(version, (row) => require(row.id === versionId && row.plan_id === planId)),
    [],
    signal,
    policy,
  );
}
