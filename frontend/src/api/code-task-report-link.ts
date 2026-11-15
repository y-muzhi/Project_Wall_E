import { positiveInteger } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { PUBLISH_TESTING_CANDIDATE } from './code-task-publication.ts';
import { array, checked, choices, nonempty, require, shape, time } from './decoding.ts';

const id = positiveInteger;
const absent = (value: unknown) => {
  require(value === null);
  return null;
};
export const reportLinkPath = (task: number) => '/api/v1/code-tasks/' + id(task) + '/test-reports';
const input = shape({ candidate_id: id, test_report_id: id, expected_state_version: id });
const receipt = shape({ task_id: id, candidate_id: id, test_report_id: id, state_version: id });
export const LINK_TESTING_REPORT: CodeCommandBinding<ReturnType<typeof receipt>> = {
  decoder_kind: 'APP-CODE-CMD-C69',
  success_status: [200],
  errors: PUBLISH_TESTING_CANDIDATE.errors,
  validate_input: input,
  decode(value, original, businessInput) {
    const result = receipt(value),
      fixed = input(businessInput);
    require(
      original.owner_module === 'CODING' &&
        result.task_id === original.parameters.task_id &&
        result.candidate_id === fixed.candidate_id &&
        result.test_report_id === fixed.test_report_id &&
        result.state_version === fixed.expected_state_version + 1,
    );
    return result;
  },
};
const kinds = ['VALIDATE', 'SAVE_FACT'] as const;
export const decodeReportLinkOperation = checked(
  shape({
    id,
    task_id: id,
    testing_task_id: absent,
    resource_kind: choices(['TASK']),
    resource_id: id,
    session_id: id,
    operation_type: choices(['LINK_TEST_REPORT']),
    idempotency_key: nonempty,
    expected_state_version: id,
    fixed_input: input,
    control_generation: id,
    status: choices(['SUCCEEDED']),
    created_at: time,
    started_at: time,
    ended_at: time,
    failure_code: absent,
    content_capture: absent,
    steps: array(
      shape({
        operation_id: id,
        step_no: id,
        step_type: choices(kinds),
        status: choices(['SUCCEEDED']),
        external_identity: absent,
        fixed_input: input,
        result_ref: receipt,
        started_at: time,
        ended_at: time,
        last_observed_at: time,
      }),
      2,
      2,
    ),
  }),
  (row) => {
    registeredCommand('POST', reportLinkPath(row.task_id), row.idempotency_key);
    require(
      row.resource_id === row.task_id &&
        row.expected_state_version === row.fixed_input.expected_state_version,
    );
    require(row.created_at <= row.started_at && row.started_at <= row.ended_at);
    let previous = row.started_at;
    row.steps.forEach((step, index) => {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === kinds[index],
      );
      require(JSON.stringify(step.fixed_input) === JSON.stringify(row.fixed_input));
      require(
        step.result_ref.task_id === row.task_id &&
          step.result_ref.candidate_id === row.fixed_input.candidate_id &&
          step.result_ref.test_report_id === row.fixed_input.test_report_id &&
          step.result_ref.state_version === row.expected_state_version + 1,
      );
      require(
        previous <= step.started_at &&
          step.started_at <= step.ended_at &&
          step.ended_at <= step.last_observed_at &&
          step.last_observed_at <= row.ended_at,
      );
      previous = step.ended_at;
    });
  },
);
