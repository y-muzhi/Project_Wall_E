import { exact } from './client.ts';
import type { ApiClient } from './client.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import {
  array,
  bool,
  checked,
  choices,
  distinct,
  id,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';
import { testingTaskSummary } from './testing-tasks.ts';

export const testingPackListPath = (versionId: number) =>
  '/api/v1/test-plan-versions/' + id(versionId) + '/packs';
export const testingPackPath = (packId: number) => '/api/v1/test-pack-versions/' + id(packId);
export const testingPackSealPath = (packId: number) => testingPackPath(packId) + '/seal';
const readErrors = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
  'PERMISSION_NOT_GRANTED',
] as const;
const policy = codeErrorPolicy(readErrors);
const hash = checked(text, (value) => require(/^[0-9a-f]{64}$/.test(value)));
const reasons = choices([
  'PACK_NOT_SEALED',
  'PACK_NOT_PUBLISHED',
  'TEST_ASSET_REVOKED',
  'REFERENCE_SET_NOT_REGISTERED',
  'Q20-CHECKS',
] as const);
export const testingPack = checked(
  shape({
    id,
    plan_version_id: id,
    version: id,
    check_set_version_id: nullable(id),
    sha256: nullable(hash),
    status: choices(['DRAFT', 'SEALED', 'PUBLISHED', 'REVOKED'] as const),
    validation_id: nullable(id),
    state_version: id,
    created_at: time,
    published_at: nullable(time),
    revoked_at: nullable(time),
    revocation_reason: nullable(text),
    ready: bool,
    reason_codes: checked(array(reasons, 8), distinct),
  }),
  (value) => {
    require((value.sha256 === null) === (value.check_set_version_id === null));
    require((value.status === 'REVOKED') === (value.revoked_at !== null));
    require((value.revoked_at === null) === (value.revocation_reason === null));
    require((value.published_at === null) === (value.validation_id === null));
    require(value.ready === (value.reason_codes.length === 0));
    if (value.status === 'PUBLISHED') require(value.published_at !== null && value.sha256 !== null);
    if (value.status === 'DRAFT') require(value.sha256 === null && value.published_at === null);
    if (value.status === 'SEALED') require(value.sha256 !== null && value.published_at === null);
    if (value.published_at)
      require(value.published_at >= value.created_at && value.sha256 !== null);
    if (value.revoked_at) require(value.revoked_at >= (value.published_at ?? value.created_at));
    if (value.ready) require(value.status === 'PUBLISHED');
  },
);
export type TestPack = ReturnType<typeof testingPack>;
const created = shape({ test_pack_version_id: id });
export const CREATE_TESTING_PACK: CodeCommandBinding<ReturnType<typeof created>> = {
  decoder_kind: 'APP-TEST-CMD-C15',
  success_status: [201],
  errors: [
    ...readErrors,
    'COMMAND_CLOSED',
    'OPERATION_CONFLICT',
    'INVALID_STATE',
    'BASIS_REF_INVALID',
    'TEST_ASSET_REVOKED',
  ],
  validate_input(input) {
    exact(input, []);
  },
  decode(value, original) {
    require(
      original.owner_module === 'TESTING' &&
        original.path === testingPackListPath(id(original.parameters.plan_version_id)),
    );
    return created(value);
  },
};

const accepted = shape({
  operation_id: id,
  test_pack_version_id: id,
  validation_id: (value: unknown): null => {
    require(value === null);
    return null;
  },
});
export type TestingSealReceipt = ReturnType<typeof accepted>;
export const SEAL_TESTING_PACK: CodeCommandBinding<TestingSealReceipt> = {
  decoder_kind: 'APP-TEST-CMD-C18',
  success_status: [202],
  errors: [
    ...readErrors,
    'COMMAND_CLOSED',
    'OPERATION_CONFLICT',
    'OPERATION_IN_PROGRESS',
    'VERSION_CONFLICT',
    'INVALID_STATE',
    'CONFIG_NOT_READY',
    'CHECK_CONFIGURATION_INVALID',
    'CONTENT_NOT_READY',
    'TEST_ASSET_REVOKED',
  ],
  validate_input(input) {
    shape({ expected_state_version: id })(input);
  },
  decode(value, original) {
    const result = accepted(value);
    require(
      original.owner_module === 'TESTING' &&
        original.path === testingPackSealPath(result.test_pack_version_id),
    );
    return result;
  },
};

export async function readTestingPacks(
  client: ApiClient,
  versionId: number,
  page: number,
  signal?: AbortSignal,
) {
  const result = await readPage(
    client,
    testingPackListPath(versionId),
    checked(testingPack, (row) => require(row.plan_version_id === versionId)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
  require(
    result.data.items.every((row, index, items) => index === 0 || items[index - 1]!.id < row.id),
  );
  return result;
}
export function readTestingPack(
  client: ApiClient,
  versionId: number,
  packId: number,
  signal?: AbortSignal,
) {
  return client.read(
    testingPackPath(packId),
    checked(testingPack, (row) => require(row.id === packId && row.plan_version_id === versionId)),
    [],
    signal,
    policy,
  );
}

const referenceName = checked(text, (value) =>
  require(/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/.test(value)),
);
const referenceSet = checked(
  shape({
    reference_set_ref: referenceName,
    basis_fingerprint: hash,
    positive_count: id,
    negative_count: id,
    repeat_count: id,
    ready: bool,
    reason_codes: array(choices(['CONTENT_NOT_READY']), 1),
  }),
  (value) => {
    require(value.positive_count + value.negative_count <= 20);
    require(value.repeat_count >= 2 && value.repeat_count <= 10);
    require(value.ready === (value.reason_codes.length === 0));
  },
);
export type TestingReferenceSet = ReturnType<typeof referenceSet>;

export async function readTestingReferenceSets(
  client: ApiClient,
  page: number,
  signal?: AbortSignal,
) {
  const result = await readPage(
    client,
    '/api/v1/testing-reference-sets',
    referenceSet,
    (row) => row.reference_set_ref,
    [['page', String(page)]],
    page,
    signal,
    policy,
  );
  const rows = result.data.items;
  require(
    rows.every(
      (row, index) => index === 0 || rows[index - 1]!.reference_set_ref < row.reference_set_ref,
    ),
  );
  return result;
}

export const testingPackControlPath = (
  pack: number,
  action: 'validations' | 'publish' | 'revoke',
) => testingPackPath(pack) + '/' + action;
const controlErrors = [
  ...readErrors,
  'COMMAND_CLOSED',
  'OPERATION_CONFLICT',
  'VERSION_CONFLICT',
  'INVALID_STATE',
  'TEST_ASSET_REVOKED',
] as const;
const packValidationInput = shape({
  expected_state_version: id,
  profile_version_id: id,
  reference_set_ref: referenceName,
  authorization_id: id,
});
const validationAccepted = shape({ operation_id: id, test_pack_version_id: id, validation_id: id });
export type TestingValidationReceipt = ReturnType<typeof validationAccepted>;
export const VALIDATE_TESTING_PACK: CodeCommandBinding<TestingValidationReceipt> = {
  decoder_kind: 'APP-TEST-CMD-C19',
  success_status: [202],
  errors: [
    ...controlErrors,
    'CONFIG_NOT_READY',
    'CHECK_CONFIGURATION_INVALID',
    'CONTENT_NOT_READY',
    'AUTHORIZATION_NOT_APPLICABLE',
    'OPERATION_IN_PROGRESS',
  ],
  validate_input: packValidationInput,
  decode(value, original) {
    const result = validationAccepted(value);
    require(
      original.owner_module === 'TESTING' &&
        original.path === testingPackControlPath(result.test_pack_version_id, 'validations'),
    );
    return result;
  },
};
const expected = shape({ expected_state_version: id });
const revocation = shape({
  expected_state_version: id,
  reason: checked(text, (value) =>
    require(value === value.trim() && [...value].length >= 1 && [...value].length <= 2000),
  ),
});
export const PUBLISH_TESTING_PACK: CodeCommandBinding<TestPack> = {
  decoder_kind: 'APP-TEST-CMD-C21',
  success_status: [200],
  errors: [...controlErrors, 'CONFIG_NOT_READY', 'CHECK_CONFIGURATION_INVALID'],
  validate_input: expected,
  decode(value, original, input) {
    const row = testingPack(value);
    require(
      original.owner_module === 'TESTING' &&
        original.path === testingPackControlPath(row.id, 'publish'),
    );
    require(
      row.status === 'PUBLISHED' &&
        row.state_version === expected(input).expected_state_version + 1,
    );
    return row;
  },
};
export const REVOKE_TESTING_PACK: CodeCommandBinding<TestPack> = {
  decoder_kind: 'APP-TEST-CMD-C22',
  success_status: [200],
  errors: controlErrors,
  validate_input: revocation,
  decode(value, original, input) {
    const row = testingPack(value);
    const fixed = revocation(input);
    require(
      original.owner_module === 'TESTING' &&
        original.path === testingPackControlPath(row.id, 'revoke'),
    );
    require(
      row.status === 'REVOKED' &&
        row.state_version === fixed.expected_state_version + 1 &&
        row.revocation_reason === fixed.reason,
    );
    return row;
  },
};
const validation = checked(
  shape({
    id,
    test_pack_version_id: id,
    profile_version_id: id,
    reference_set_ref: referenceName,
    operation_id: id,
    testing_task_ids: array(id, 200, 4),
    result: choices(['PENDING', 'RUNNING', 'PASSED', 'FAILED', 'UNAVAILABLE', 'UNKNOWN']),
    created_at: time,
    ended_at: nullable(time),
    testing_tasks: array(testingTaskSummary, 200, 4),
  }),
  (row) => {
    distinct(row.testing_task_ids);
    require(
      row.testing_task_ids.length === row.testing_tasks.length &&
        row.testing_tasks.every(
          (task, index) =>
            task.id === row.testing_task_ids[index] &&
            task.purpose === 'PACK_VALIDATION' &&
            task.target_kind === 'SNAPSHOT' &&
            (index === 0 || row.testing_task_ids[index - 1]! < task.id) &&
            (row.result !== 'PASSED' || task.status === 'COMPLETED'),
        ),
    );
    if (['PENDING', 'RUNNING'].includes(row.result)) require(row.ended_at === null);
    if (['PASSED', 'FAILED', 'UNAVAILABLE'].includes(row.result)) require(row.ended_at !== null);
    if (row.ended_at !== null) require(row.ended_at >= row.created_at);
  },
);
export type TestPackValidation = ReturnType<typeof validation>;
export function readTestingValidation(
  client: ApiClient,
  packId: number,
  validationId: number,
  signal?: AbortSignal,
) {
  return client.read(
    '/api/v1/test-pack-validations/' + id(validationId),
    checked(validation, (row) =>
      require(row.id === validationId && row.test_pack_version_id === packId),
    ),
    [],
    signal,
    policy,
  );
}
