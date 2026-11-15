import { exact, positiveInteger } from './client.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { registeredCommand } from './code-command-registry.ts';
import { array, checked, choices, nonempty, require, shape, time } from './decoding.ts';

const nil = (value: unknown) => {
  require(value === null);
  return null;
};
export const publicationPath = (task: number) =>
  '/api/v1/code-tasks/' + positiveInteger(task) + '/testing-publication';

const input = shape({
  candidate_id: positiveInteger,
  verification_id: positiveInteger,
  expected_state_version: positiveInteger,
});
const receipt = shape({
  task_id: positiveInteger,
  candidate_id: positiveInteger,
  test_report_id: nil,
  state_version: positiveInteger,
});
export const PUBLISH_TESTING_CANDIDATE: CodeCommandBinding<ReturnType<typeof receipt>> = {
  decoder_kind: 'APP-CODE-CMD-C68',
  success_status: [200],
  errors: [
    'INVALID_INPUT',
    'NOT_FOUND',
    'INVALID_STATE',
    'VERSION_CONFLICT',
    'OPERATION_CONFLICT',
    'CONFIG_NOT_READY',
    'CONTENT_NOT_READY',
    'BASIS_REF_INVALID',
    'CHECK_CONFIGURATION_INVALID',
    'TEST_REPORT_NOT_ELIGIBLE',
    'TEST_SOURCE_MISMATCH',
    'TEST_ASSET_REVOKED',
    'VERIFICATION_STAGE_NOT_READY',
    'STORAGE_UNAVAILABLE',
    'INTERNAL_ERROR',
    'COMMAND_CLOSED',
    'EXTERNAL_RESULT_UNKNOWN',
  ],
  validate_input(value, original) {
    require(original.decoder_kind === 'APP-CODE-CMD-C68');
    input(value);
  },
  decode(value, original, request) {
    const result = receipt(value);
    const fixed = input(request);
    require(
      original.decoder_kind === 'APP-CODE-CMD-C68' &&
        original.parameters.task_id === result.task_id &&
        result.candidate_id === fixed.candidate_id &&
        result.state_version === fixed.expected_state_version + 1,
    );
    return result;
  },
};

const steps = ['VALIDATE', 'SAVE_FACT'] as const;
export const decodePublicationOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: positiveInteger,
    operation_type: choices(['SUBMIT_FOR_TESTING']),
    idempotency_key: nonempty,
    expected_state_version: positiveInteger,
    fixed_input: input,
    control_generation: positiveInteger,
    status: choices(['SUCCEEDED']),
    created_at: time,
    started_at: time,
    ended_at: time,
    failure_code: nil,
    content_capture: nil,
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(steps),
        status: choices(['SUCCEEDED']),
        external_identity: nil,
        fixed_input: input,
        result_ref: (value: unknown) => value,
        started_at: time,
        ended_at: time,
        last_observed_at: time,
      }),
      2,
      2,
    ),
  }),
  (row) => {
    registeredCommand('POST', publicationPath(row.task_id), row.idempotency_key);
    require(
      row.task_id === row.resource_id &&
        row.expected_state_version === row.fixed_input.expected_state_version &&
        row.created_at === row.started_at &&
        row.started_at === row.ended_at,
    );
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === steps[index] &&
          JSON.stringify(step.fixed_input) === JSON.stringify(row.fixed_input) &&
          step.started_at === row.ended_at &&
          step.ended_at === row.ended_at &&
          step.last_observed_at === row.ended_at,
      );
      const result = exact(
        step.result_ref,
        index === 0
          ? [
              'candidate_id',
              'verification_id',
              'backend_handoff_operation_id',
              'frontend_handoff_operation_id',
            ]
          : ['candidate_id'],
      );
      require(result.candidate_id === row.fixed_input.candidate_id);
      if (index === 0)
        require(
          result.verification_id === row.fixed_input.verification_id &&
            positiveInteger(result.backend_handoff_operation_id) <
              positiveInteger(result.frontend_handoff_operation_id),
        );
    }
  },
);
