import { exact, positiveInteger } from './client.ts';
import { array, checked, choices, nonempty, nullable, require, shape, time } from './decoding.ts';

const steps = ['QUIESCE', 'REVOKE', 'CHECK', 'CREATE_SESSION', 'SEND_HANDOFF'] as const;
const statuses = ['PENDING', 'RUNNING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED'] as const;
const nil = (value: unknown) => {
  require(value === null);
  return null;
};
const input = shape({
  source_session_id: positiveInteger,
  candidate_id: positiveInteger,
  verification_id: positiveInteger,
  target_role: choices(['FRONTEND', 'INTEGRATION']),
  expected_state_version: positiveInteger,
});
const resultFields = [
  ['quiesce_observation_id'],
  ['session_id', 'control_generation'],
  ['verification_id'],
  ['session_id'],
  ['session_id'],
] as const;

export const decodeRoleHandoffOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['HANDOFF_ROLE']),
    idempotency_key: nonempty,
    expected_state_version: positiveInteger,
    fixed_input: input,
    control_generation: positiveInteger,
    status: choices(statuses),
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
        status: choices(statuses),
        external_identity: nil,
        fixed_input: input,
        result_ref: (value: unknown) => value,
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      steps.length,
      steps.length,
    ),
  }),
  (row) => {
    require(
      row.resource_id === row.task_id &&
        row.fixed_input.source_session_id === row.session_id &&
        row.fixed_input.expected_state_version === row.expected_state_version &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
          row.idempotency_key,
        ),
    );
    let previous = true;
    let target: number | null = null;
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === steps[index] &&
          JSON.stringify(step.fixed_input) === JSON.stringify(row.fixed_input) &&
          (previous || step.status === 'PENDING' || step.status === 'CANCELLED'),
      );
      previous = step.status === 'SUCCEEDED';
      if (!previous) {
        require(step.result_ref === null);
        continue;
      }
      const fields = resultFields[index]!;
      const result = exact(step.result_ref, fields);
      for (const field of fields) positiveInteger(result[field]);
      if (step.step_type === 'REVOKE')
        require(
          result.session_id === row.session_id &&
            result.control_generation === row.control_generation + 1,
        );
      if (step.step_type === 'CHECK')
        require(result.verification_id === row.fixed_input.verification_id);
      if (step.step_type === 'CREATE_SESSION') {
        target = positiveInteger(result.session_id);
        require(target !== row.session_id);
      }
      if (step.step_type === 'SEND_HANDOFF') require(result.session_id === target);
    }
    if (row.status === 'SUCCEEDED') require(previous);
  },
);
