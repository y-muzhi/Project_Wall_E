/** Original progress for the capture associated with a fixed candidate. */
import { exact, positiveInteger } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import { array, checked, choices, nullable, require, shape, time, nonempty } from './decoding.ts';

const stages = ['QUIESCE', 'CAPTURE', 'PUBLISH', 'CHECK'] as const;
const states = ['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED'] as const;
const progress = [
  'PREPARING',
  'READING',
  'PUBLISHING',
  'VERIFYING',
  'READY',
  'FAILED',
  'UNKNOWN',
] as const;
const resultKeys = ['quiesce_observation_id', null, 'candidate_id', 'verification_id'] as const;
const fixed = shape({ expected_state_version: positiveInteger, purpose: choices(['HANDOFF']) });
function nil(value: unknown): null {
  require(value === null);
  return null;
}

export const decodeCaptureOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['CAPTURE_AND_CHECK']),
    idempotency_key: nonempty,
    expected_state_version: positiveInteger,
    fixed_input: fixed,
    control_generation: positiveInteger,
    status: choices(states),
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(nonempty),
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(stages),
        status: choices(states),
        external_identity: nil,
        fixed_input: fixed,
        result_ref: (value: unknown) => value,
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      4,
      4,
    ),
    content_capture: shape({
      state: choices(progress),
      content_policy_version: choices(['CONTENT20-STORE-1']),
      captured_at: nullable(time),
      issue: nullable(shape({ path: nil, reason_code: choices(['RESULT_UNKNOWN']) })),
    }),
  }),
  (row) => {
    registeredCommand(
      'POST',
      '/api/v1/code-tasks/' + row.task_id + '/candidates',
      row.idempotency_key,
    );
    require(
      row.resource_id === row.task_id &&
        row.expected_state_version === row.fixed_input.expected_state_version,
    );
    let previous = true;
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === stages[index] &&
          step.fixed_input.expected_state_version === row.expected_state_version &&
          (previous || step.status === 'PENDING' || step.status === 'CANCELLED'),
      );
      previous = step.status === 'SUCCEEDED';
      const key = resultKeys[index];
      if (previous && key) positiveInteger(exact(step.result_ref, [key])[key]);
      else require(step.result_ref === null);
    }
    const flags = row.steps.map((step) => step.status);
    const expected =
      row.status === 'UNKNOWN' || flags.includes('UNKNOWN')
        ? 'UNKNOWN'
        : row.status === 'FAILED' || row.status === 'CANCELLED' || flags.includes('FAILED')
          ? 'FAILED'
          : row.status === 'SUCCEEDED' && flags[3] === 'SUCCEEDED'
            ? 'READY'
            : flags[2] === 'SUCCEEDED'
              ? 'VERIFYING'
              : flags[1] === 'SUCCEEDED'
                ? 'PUBLISHING'
                : flags[1] === 'RUNNING'
                  ? 'READING'
                  : 'PREPARING';
    require(
      row.content_capture.state === expected &&
        (row.content_capture.issue !== null) === (expected === 'UNKNOWN') &&
        (row.content_capture.captured_at !== null) === (flags[1] === 'SUCCEEDED'),
    );
  },
);

const restoreStages = ['CHECK_CONDITIONS', 'RESTORE_CHECK_COPY', 'CHECK'] as const;
const verifyInput = shape({
  candidate_id: positiveInteger,
  expected_state_version: positiveInteger,
  purpose: choices(['HANDOFF']),
});
export const decodeVerifyCandidateOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['VERIFY_CANDIDATE']),
    idempotency_key: nonempty,
    expected_state_version: positiveInteger,
    fixed_input: verifyInput,
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
        step_type: choices(restoreStages),
        status: choices(states),
        external_identity: nil,
        fixed_input: verifyInput,
        result_ref: (value: unknown) => value,
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      3,
      3,
    ),
  }),
  (row) => {
    registeredCommand(
      'POST',
      '/api/v1/code-tasks/' +
        row.task_id +
        '/candidates/' +
        row.fixed_input.candidate_id +
        '/verifications',
      row.idempotency_key,
    );
    require(
      row.resource_id === row.task_id &&
        row.fixed_input.expected_state_version === row.expected_state_version,
    );
    let previous = true;
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === restoreStages[index] &&
          step.fixed_input.candidate_id === row.fixed_input.candidate_id &&
          step.fixed_input.expected_state_version === row.expected_state_version &&
          (previous || step.status === 'PENDING' || step.status === 'CANCELLED'),
      );
      previous = step.status === 'SUCCEEDED';
      if (!previous) require(step.result_ref === null);
      else {
        const key = step.step_type === 'CHECK' ? 'verification_id' : 'candidate_id';
        const id = positiveInteger(exact(step.result_ref, [key])[key]);
        if (key === 'candidate_id') require(id === row.fixed_input.candidate_id);
      }
    }
  },
);
