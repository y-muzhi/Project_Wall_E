import { exact, positiveInteger } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { array, checked, choices, nonempty, nullable, require, shape, time } from './decoding.ts';

const nil = (value: unknown) => {
  require(value === null);
  return null;
};
export const reconciliationPath = (task: number) =>
  '/api/v1/code-tasks/' + positiveInteger(task) + '/reconcile';
const input = shape({ expected_state_version: positiveInteger, operation_id: positiveInteger });
const receipt = shape({
  task_id: positiveInteger,
  operation_id: positiveInteger,
  operation_status: choices(['PENDING']),
  task_status: choices(['WAITING']),
  state_version: positiveInteger,
});
export const RECONCILE_ROLE_DELIVERY: CodeCommandBinding<ReturnType<typeof receipt>> = {
  decoder_kind: 'APP-CODE-CMD-C38',
  success_status: [202],
  errors: [
    'INVALID_INPUT',
    'NOT_FOUND',
    'INVALID_STATE',
    'TASK_ENDED',
    'VERSION_CONFLICT',
    'OPERATION_CONFLICT',
    'OPERATION_IN_PROGRESS',
    'EXTERNAL_RESULT_UNKNOWN',
    'EXECUTION_NOT_STOPPED',
    'CONFIG_NOT_READY',
    'STORAGE_UNAVAILABLE',
    'INTERNAL_ERROR',
    'COMMAND_CLOSED',
  ],
  validate_input(value, original) {
    require(original.decoder_kind === 'APP-CODE-CMD-C38');
    input(value);
  },
  decode(value, original, request) {
    const result = receipt(value);
    require(
      original.decoder_kind === 'APP-CODE-CMD-C38' &&
        original.parameters.task_id === result.task_id &&
        result.state_version === input(request).expected_state_version + 1,
    );
    return result;
  },
};
const steps = ['QUERY', 'COMPARE', 'RECORD'] as const;
const states = ['PENDING', 'SUCCEEDED', 'CANCELLED'] as const;
const result = shape({
  operation_id: positiveInteger,
  original_status: choices(['SUCCEEDED', 'RUNNING', 'UNKNOWN']),
});
export const decodeReconciliationOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['RECONCILE']),
    idempotency_key: nonempty,
    expected_state_version: positiveInteger,
    fixed_input: input,
    control_generation: positiveInteger,
    status: choices(states),
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(nonempty),
    content_capture: nil,
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(steps),
        status: choices(states),
        external_identity: nil,
        fixed_input: input,
        result_ref: nullable(result),
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      3,
      3,
    ),
  }),
  (row) => {
    registeredCommand('POST', reconciliationPath(row.task_id), row.idempotency_key);
    require(
      row.task_id === row.resource_id &&
        row.expected_state_version === row.fixed_input.expected_state_version,
    );
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === steps[index] &&
          step.status === row.status &&
          step.fixed_input.operation_id === row.fixed_input.operation_id &&
          step.fixed_input.expected_state_version === row.expected_state_version &&
          (step.result_ref !== null) === (row.status === 'SUCCEEDED'),
      );
      if (step.result_ref) {
        const fixed = exact(step.result_ref, ['operation_id', 'original_status']);
        require(fixed.operation_id === row.fixed_input.operation_id);
      }
    }
  },
);
