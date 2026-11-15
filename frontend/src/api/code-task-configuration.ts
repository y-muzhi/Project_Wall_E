/** Original C39 selection and operation evidence; acceptance does not prove effect. */
import type { ExecutionProfileContent } from './code-execution-profiles.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { registeredCommand } from './code-command-registry.ts';
import {
  array,
  checked,
  choices,
  id,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';

const fixedContentLimits = [
  'max_file_bytes',
  'max_snapshot_bytes',
  'max_snapshot_files',
  'max_capture_entries',
  'max_capture_seconds',
  'max_manifest_bytes',
  'max_git_seconds',
  'max_git_output_bytes',
] as const;

export function fixedContentChanged(
  before: ExecutionProfileContent,
  after: ExecutionProfileContent,
) {
  return (
    JSON.stringify(before.capture_rules) !== JSON.stringify(after.capture_rules) ||
    fixedContentLimits.some((field) => before.limits[field] !== after.limits[field])
  );
}

const reason = checked(nonempty, (value) => require(value.trim().length > 0));
const body = {
  expected_state_version: id,
  execution_profile_version_id: id,
  authorization_id: id,
  reason,
};
export const configurationInput = shape(body);
const fixedInput = shape({ task_id: id, ...body });
const receipt = shape({
  task_id: id,
  operation_id: id,
  operation_status: choices(['RUNNING']),
  task_status: choices(['PENDING', 'WAITING']),
  state_version: id,
});
export const configurationPath = (task: number) =>
  '/api/v1/code-tasks/' + id(task) + '/configuration';
export const APPLY_CONFIGURATION: CodeCommandBinding<ReturnType<typeof receipt>> = {
  decoder_kind: 'APP-CODE-CMD-C39',
  success_status: [202],
  errors: [
    'INVALID_INPUT',
    'NOT_FOUND',
    'INVALID_STATE',
    'TASK_ENDED',
    'VERSION_CONFLICT',
    'OPERATION_CONFLICT',
    'AUTHORIZATION_NOT_APPLICABLE',
    'CONFIG_NOT_READY',
    'PRECONDITION_FAILED',
    'STORAGE_UNAVAILABLE',
    'INTERNAL_ERROR',
    'COMMAND_CLOSED',
  ],
  validate_input: configurationInput,
  decode(value, original, fixed) {
    const row = receipt(value);
    require(
      row.task_id === original.parameters.task_id &&
        row.state_version === configurationInput(fixed).expected_state_version + 1,
    );
    return row;
  },
};
const nil = (value: unknown) => {
  require(value === null);
  return null;
};
const steps = ['BLOCK_NEW', 'QUIESCE_IF_REQUIRED', 'APPLY_PAIR', 'VERIFY_EFFECTIVE'] as const;
const statuses = ['RUNNING', 'UNKNOWN', 'CANCELLED', 'SUCCEEDED'] as const;
const pendingStates = ['PENDING', 'RUNNING', 'UNKNOWN', 'CANCELLED', 'SUCCEEDED'] as const;
const prepared = shape({ configuration_application_id: id });
const effective = shape({ configuration_application_id: id, start_operation_id: id });
const configurationOperation = shape({
  id,
  task_id: id,
  testing_task_id: nil,
  resource_kind: choices(['TASK']),
  resource_id: id,
  session_id: nullable(id),
  operation_type: choices(['APPLY_CONFIGURATION']),
  idempotency_key: nonempty,
  expected_state_version: id,
  fixed_input: fixedInput,
  control_generation: id,
  status: choices(statuses),
  created_at: time,
  started_at: time,
  ended_at: nullable(time),
  failure_code: nullable(choices(['EXTERNAL_RESULT_UNKNOWN', 'TASK_ENDED'])),
  content_capture: nil,
  steps: array(
    shape({
      operation_id: id,
      step_no: id,
      step_type: choices(steps),
      status: choices(pendingStates),
      external_identity: nil,
      fixed_input: fixedInput,
      result_ref: (value) => value,
      started_at: nullable(time),
      ended_at: nullable(time),
      last_observed_at: nullable(time),
    }),
    steps.length,
    steps.length,
  ),
});

function validateLiveStepOrder(row: ReturnType<typeof configurationOperation>) {
  const states = row.steps.slice(1).map((step) => step.status);
  if (row.status === 'SUCCEEDED') {
    require(states.every((status) => status === 'SUCCEEDED'));
    return;
  }
  const completed = states.findIndex((status) => status !== 'SUCCEEDED');
  require(completed >= 0);
  const current = states[completed];
  const allowed =
    row.status === 'RUNNING'
      ? current === 'PENDING' || current === 'RUNNING'
      : row.status === 'UNKNOWN'
        ? current === 'UNKNOWN'
        : current === 'CANCELLED';
  const following = row.status === 'CANCELLED' ? 'CANCELLED' : 'PENDING';
  require(allowed && states.slice(completed + 1).every((status) => status === following));
}

function validateLiveSteps(row: ReturnType<typeof configurationOperation>) {
  validateLiveStepOrder(row);
  let previousEnded = row.created_at;
  for (const [index, step] of row.steps.entries()) {
    require(
      step.operation_id === row.id &&
        step.step_no === index + 1 &&
        step.step_type === steps[index] &&
        JSON.stringify(step.fixed_input) === JSON.stringify(row.fixed_input),
    );
    if (index === 0) {
      require(
        step.status === 'SUCCEEDED' &&
          shape({ state_version: id })(step.result_ref).state_version ===
            row.expected_state_version + 1 &&
          step.started_at === row.created_at &&
          step.ended_at === row.created_at &&
          step.last_observed_at === row.created_at,
      );
      continue;
    }
    const expected = step.status;
    if (expected === 'PENDING') {
      require(
        step.started_at === null &&
          step.ended_at === null &&
          step.last_observed_at === null &&
          step.result_ref === null,
      );
      continue;
    }
    require(
      step.started_at !== null &&
        step.last_observed_at !== null &&
        step.started_at >= previousEnded &&
        step.last_observed_at >= step.started_at,
    );
    if (expected === 'RUNNING' || expected === 'UNKNOWN') {
      require(step.ended_at === null);
    } else {
      require(
        step.ended_at !== null &&
          step.ended_at >= step.started_at &&
          step.last_observed_at === step.ended_at &&
          (row.ended_at === null || step.ended_at <= row.ended_at) &&
          ((expected !== 'CANCELLED' && index !== 3) || step.ended_at === row.ended_at),
      );
      previousEnded = step.ended_at;
    }
    if (expected !== 'SUCCEEDED') {
      require(step.result_ref === null);
      continue;
    }
    if (index === 1) shape({ scope: choices(['CURRENT_SESSION']) })(step.result_ref);
    else if (index === 2) prepared(step.result_ref);
    else {
      require(
        effective(step.result_ref).configuration_application_id ===
          prepared(row.steps[2]?.result_ref).configuration_application_id,
      );
    }
  }
}

export const decodeConfigurationOperation = checked(configurationOperation, (row) => {
  registeredCommand('POST', configurationPath(row.task_id), row.idempotency_key);
  const terminal = row.status === 'SUCCEEDED' || row.status === 'CANCELLED';
  const failure =
    row.status === 'UNKNOWN'
      ? 'EXTERNAL_RESULT_UNKNOWN'
      : row.status === 'CANCELLED'
        ? 'TASK_ENDED'
        : null;
  require(
    row.task_id === row.resource_id &&
      row.fixed_input.task_id === row.task_id &&
      row.fixed_input.expected_state_version === row.expected_state_version &&
      row.started_at === row.created_at &&
      row.failure_code === failure &&
      (row.ended_at !== null) === terminal &&
      (row.ended_at === null || row.ended_at >= row.created_at),
  );
  if (row.session_id !== null) {
    validateLiveSteps(row);
    return;
  }
  const application = prepared(row.steps[2]!.result_ref);
  for (const [index, step] of row.steps.entries()) {
    require(
      step.operation_id === row.id &&
        step.step_no === index + 1 &&
        step.step_type === steps[index] &&
        JSON.stringify(step.fixed_input) === JSON.stringify(row.fixed_input),
    );
    if (index < 3) {
      require(
        step.status === 'SUCCEEDED' &&
          step.started_at === row.created_at &&
          step.ended_at === row.created_at &&
          step.last_observed_at === row.created_at,
      );
      continue;
    }
    require(
      step.status === (row.status === 'RUNNING' ? 'PENDING' : row.status) &&
        step.ended_at === row.ended_at,
    );
    if (row.status === 'RUNNING')
      require(step.started_at === null && step.last_observed_at === null);
    else
      require(
        step.started_at !== null &&
          step.last_observed_at !== null &&
          step.started_at >= row.created_at &&
          step.last_observed_at >= step.started_at &&
          (!terminal || step.last_observed_at === row.ended_at),
      );
    if (row.status === 'SUCCEEDED') {
      require(
        effective(step.result_ref).configuration_application_id ===
          application.configuration_application_id,
      );
    } else require(step.result_ref === null);
  }
  const blocked = shape({ state_version: id })(row.steps[0]!.result_ref);
  const scope = shape({ scope: choices(['NO_INSTANCE']) })(row.steps[1]!.result_ref);
  require(
    blocked.state_version === row.expected_state_version + 1 && scope.scope === 'NO_INSTANCE',
  );
});
