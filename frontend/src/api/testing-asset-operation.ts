import type { ApiClient } from './client.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { array, checked, choices, id, nullable, require, shape, text, time } from './decoding.ts';

const failure = choices([
  'INVALID_STATE',
  'CONFIG_NOT_READY',
  'CHECK_CONFIGURATION_INVALID',
  'CONTENT_NOT_READY',
  'TEST_ASSET_REVOKED',
] as const);
const policy = codeErrorPolicy([
  'INVALID_INPUT',
  'NOT_FOUND',
  'PERMISSION_NOT_GRANTED',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
] as const);
const states = choices(['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED'] as const);
const steps = ['VALIDATE_PLAN', 'COMPILE', 'SEAL', 'SAVE_PACK'] as const;
const absent = (value: unknown): null => {
  require(value === null);
  return null;
};
const fixed = shape({ expected_state_version: id });
const hash = checked(text, (value) => require(/^[0-9a-f]{64}$/.test(value)));
const step = shape({
  operation_id: id,
  step_no: id,
  step_type: choices(steps),
  status: states,
  external_identity: absent,
  fixed_input: fixed,
  result_ref: (value: unknown) => value,
  started_at: nullable(time),
  ended_at: nullable(time),
  last_observed_at: nullable(time),
});
const operation = checked(
  shape({
    id,
    task_id: absent,
    testing_task_id: absent,
    resource_kind: choices(['TEST_PACK_VERSION']),
    resource_id: id,
    session_id: absent,
    operation_type: choices(['SEAL_PACK']),
    idempotency_key: checked(text, (value) =>
      require(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)),
    ),
    expected_state_version: id,
    fixed_input: fixed,
    control_generation: absent,
    status: states,
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(failure),
    steps: array(step, 4, 4),
    content_capture: absent,
  }),
  (row) => {
    const terminal = row.status === 'SUCCEEDED' || row.status === 'FAILED';
    require(row.expected_state_version === row.fixed_input.expected_state_version);
    require((row.status === 'PENDING') === (row.started_at === null));
    require(terminal === (row.ended_at !== null));
    require((row.status === 'FAILED') === (row.failure_code !== null));
    if (row.started_at !== null) require(row.started_at >= row.created_at);
    if (row.ended_at !== null) require(row.started_at !== null && row.ended_at >= row.started_at);
    let previous = row.started_at;
    let active: 'PENDING' | 'RUNNING' | 'FAILED' | null = null;
    row.steps.forEach((entry, index) => {
      require(entry.operation_id === row.id && entry.step_no === index + 1);
      require(entry.step_type === steps[index]);
      require(entry.fixed_input.expected_state_version === row.expected_state_version);
      if (entry.status === 'PENDING') {
        require(
          entry.started_at === null &&
            entry.ended_at === null &&
            entry.last_observed_at === null &&
            entry.result_ref === null,
        );
        active ??= 'PENDING';
        return;
      }
      require(
        active === null &&
          previous !== null &&
          entry.started_at !== null &&
          entry.last_observed_at !== null,
      );
      require(previous <= entry.started_at && entry.started_at <= entry.last_observed_at);
      require(row.ended_at === null || entry.last_observed_at <= row.ended_at);
      if (entry.status === 'RUNNING') {
        require(entry.ended_at === null && entry.result_ref === null);
        active = 'RUNNING';
        return;
      }
      require(
        entry.ended_at !== null &&
          entry.started_at <= entry.ended_at &&
          entry.ended_at <= entry.last_observed_at,
      );
      previous = entry.ended_at;
      if (entry.status === 'FAILED') {
        require(entry.result_ref === null);
        active = 'FAILED';
      } else if (entry.step_type === 'VALIDATE_PLAN') {
        shape({ plan_version_id: id })(entry.result_ref);
      } else if (entry.step_type === 'SAVE_PACK') {
        const result = shape({ test_pack_version_id: id, check_set_version_id: id })(
          entry.result_ref,
        );
        require(result.test_pack_version_id === row.resource_id);
      } else shape({ sha256: hash })(entry.result_ref);
    });
    require(row.status === 'SUCCEEDED' ? active === null : row.status === active);
  },
);

export function readTestingSeal(
  client: ApiClient,
  packId: number,
  operationId: number,
  signal?: AbortSignal,
) {
  return client.read(
    '/api/v1/testing-operations/' + id(operationId),
    checked(operation, (row) => require(row.id === operationId && row.resource_id === packId)),
    [],
    signal,
    policy,
  );
}

const validationStates = choices([
  'PENDING',
  'RUNNING',
  'SUCCEEDED',
  'FAILED',
  'UNKNOWN',
  'CANCELLED',
]);
const validationSteps = [
  'FIX_REFERENCE_SET',
  'CREATE_CHILD_TASKS',
  'OBSERVE_CHILDREN',
  'SAVE_VALIDATION',
] as const;
const validationFixed = shape({
  expected_state_version: id,
  profile_version_id: id,
  authorization_id: id,
  reference_set_ref: checked(text, (value) =>
    require(/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/.test(value)),
  ),
});
const validationOperation = checked(
  shape({
    id,
    task_id: absent,
    testing_task_id: absent,
    session_id: absent,
    control_generation: absent,
    content_capture: absent,
    resource_kind: choices(['TEST_PACK_VERSION']),
    resource_id: id,
    operation_type: choices(['VALIDATE_PACK']),
    idempotency_key: checked(text, (value) =>
      require(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)),
    ),
    expected_state_version: id,
    fixed_input: validationFixed,
    status: validationStates,
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(
      choices([
        'CONFIG_NOT_READY',
        'CONTENT_NOT_READY',
        'EXECUTION_NOT_STOPPED',
        'TEST_ASSET_REVOKED',
        'EXTERNAL_RESULT_UNKNOWN',
      ]),
    ),
    steps: array(
      shape({
        operation_id: id,
        step_no: id,
        step_type: choices(validationSteps),
        status: validationStates,
        external_identity: absent,
        fixed_input: validationFixed,
        result_ref: nullable(
          shape({
            validation_id: id,
            result: choices(['PENDING', 'RUNNING', 'PASSED', 'FAILED', 'UNAVAILABLE', 'UNKNOWN']),
          }),
        ),
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      4,
      4,
    ),
  }),
  (row) => {
    require(row.expected_state_version === row.fixed_input.expected_state_version);
    if (row.started_at !== null) require(row.created_at <= row.started_at);
    if (row.ended_at !== null) require(row.started_at !== null && row.started_at <= row.ended_at);
    row.steps.forEach((item, index) => {
      require(
        item.operation_id === row.id &&
          item.step_type === validationSteps[index] &&
          item.step_no === index + 1,
      );
      require(JSON.stringify(item.fixed_input) === JSON.stringify(row.fixed_input));
      if (item.result_ref !== null)
        require(item.step_type === 'SAVE_VALIDATION' && item.status === 'SUCCEEDED');
    });
  },
);
export function readTestingValidationOperation(
  client: ApiClient,
  pack: number,
  operation: number,
  signal?: AbortSignal,
) {
  return client.read(
    '/api/v1/testing-operations/' + id(operation),
    checked(validationOperation, (row) =>
      require(row.resource_id === pack && row.id === operation),
    ),
    [],
    signal,
    policy,
  );
}
