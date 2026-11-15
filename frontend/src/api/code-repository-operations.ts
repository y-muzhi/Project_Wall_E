/** Public original repository operations; reading never starts a Git command. */
import { ApiUnknown, exact, positiveInteger, snapshotObject } from './client.ts';
import type { ApiClient } from './client.ts';
import { array, checked, choices, nonempty, nullable, require, shape, time } from './decoding.ts';
import { codeErrorPolicy, ERROR_HTTP } from './code-errors.ts';
import { registeredCommand } from './code-command-registry.ts';

const state = choices([
  'PENDING',
  'RUNNING',
  'SUCCEEDED',
  'FAILED',
  'UNKNOWN',
  'CANCELLED',
] as const);
function nil(value: unknown): null {
  require(value === null);
  return null;
}
const step = shape({
  operation_id: positiveInteger,
  step_no: positiveInteger,
  step_type: nonempty,
  status: state,
  external_identity: nullable(shape({})),
  fixed_input: snapshotObject,
  result_ref: nullable(snapshotObject),
  started_at: nullable(time),
  ended_at: nullable(time),
  last_observed_at: nullable(time),
});
export const repositoryOperation = checked(
  shape({
    id: positiveInteger,
    task_id: nil,
    testing_task_id: nil,
    resource_kind: choices(['REPOSITORY'] as const),
    resource_id: positiveInteger,
    session_id: nil,
    operation_type: choices([
      'REGISTER_REPOSITORY',
      'REFRESH_REPOSITORY',
      'REGISTER_BASE',
    ] as const),
    idempotency_key: nonempty,
    expected_state_version: nil,
    fixed_input: snapshotObject,
    control_generation: nil,
    status: state,
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable((value: unknown) => {
      const code = nonempty(value);
      require(Object.hasOwn(ERROR_HTTP, code));
      return code;
    }),
    steps: array(step, 4, 2),
    content_capture: nil,
  }),
  (row) => {
    const registration = row.operation_type === 'REGISTER_REPOSITORY';
    const baseline = row.operation_type === 'REGISTER_BASE';
    const path = registration
      ? '/api/v1/code-repositories'
      : '/api/v1/code-repositories/' + row.resource_id + (baseline ? '/snapshots' : '/refresh');
    registeredCommand('POST', path, row.idempotency_key);
    const fields = registration
      ? ['name']
      : baseline
        ? ['repository_id', 'commit_oid', 'execution_profile_version_id']
        : ['repository_id'];
    const input = exact(row.fixed_input, fields);
    if (registration) {
      const name = nonempty(input.name);
      require(name.trim().length > 0 && !name.includes('\0'));
    } else {
      require(positiveInteger(input.repository_id) === row.resource_id);
    }
    if (baseline) {
      const oid = nonempty(input.commit_oid);
      require(/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(oid) && !/^0+$/.test(oid));
      positiveInteger(input.execution_profile_version_id);
    }
    const types = registration
      ? ['VALIDATE', 'SAVE_FACT']
      : baseline
        ? ['VALIDATE_COMMIT', 'PIN_COMMIT', 'VERIFY_PINNED_OBJECTS', 'SAVE_BASELINE']
        : ['READ_REPOSITORY', 'SAVE_OBSERVATION'];
    require(row.steps.length === types.length);
    row.steps.forEach((item, index) => {
      require(
        item.operation_id === row.id &&
          item.step_no === index + 1 &&
          item.step_type === types[index],
      );
      require(JSON.stringify(item.fixed_input) === JSON.stringify(row.fixed_input));
      if (item.result_ref !== null) {
        const field = registration ? 'repository_id' : baseline ? 'snapshot_id' : 'observation_id';
        const result = exact(item.result_ref, [field]);
        const id = positiveInteger(result[field]);
        require(index === types.length - 1 && item.status === 'SUCCEEDED');
        if (registration) require(id === row.resource_id);
      }
    });
    if (row.status === 'SUCCEEDED')
      require(
        row.steps.every((item) => item.status === 'SUCCEEDED') &&
          row.steps[types.length - 1]?.result_ref !== null,
      );
  },
);
export type RepositoryOperation = ReturnType<typeof repositoryOperation>;
const errors = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONFIG_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
]);
export async function readRepositoryOperation(
  client: ApiClient,
  operationId: number,
  signal?: AbortSignal,
) {
  positiveInteger(operationId);
  const result = await client.read(
    '/api/v1/code-operations/' + operationId,
    repositoryOperation,
    [],
    signal,
    errors,
  );
  if (result.data.id !== operationId || result.meta.pagination !== undefined)
    throw new ApiUnknown(false);
  return result;
}
