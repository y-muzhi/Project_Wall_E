import type { ApiClient } from './client.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import {
  array,
  checked,
  choices,
  distinct,
  id,
  nonempty,
  nullable,
  require,
  shape,
  time,
} from './decoding.ts';
import { readPage } from './pagination.ts';

const states = ['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED'] as const;
const stages = ['RESTORE_SOURCE', 'SEND_REPAIR', 'OBSERVE', 'CAPTURE_RESULT'] as const;
const nil = (value: unknown) => {
  require(value === null);
  return null;
};
const defectIds = checked(array(id, 65536, 1), distinct);
const input = shape({ expected_state_version: id, candidate_id: id, defect_ids: defectIds });
export const repairPath = (task: number) => '/api/v1/code-tasks/' + id(task) + '/repairs';
const receipt = shape({
  task_id: id,
  operation_id: id,
  operation_status: choices(['PENDING']),
  task_status: choices(['WAITING']),
  state_version: id,
});
const errors = [
  'INVALID_INPUT',
  'NOT_FOUND',
  'CONFIG_NOT_READY',
  'CONTENT_NOT_READY',
  'STORAGE_UNAVAILABLE',
  'INTERNAL_ERROR',
] as const;
export const REQUEST_CODE_REPAIR: CodeCommandBinding<ReturnType<typeof receipt>> = {
  decoder_kind: 'APP-CODE-CMD-C59',
  success_status: [202],
  errors: [
    ...errors,
    'TASK_ENDED',
    'VERSION_CONFLICT',
    'INVALID_STATE',
    'CANDIDATE_NOT_CURRENT',
    'DEFECT_SOURCE_MISMATCH',
    'OPERATION_CONFLICT',
    'EXTERNAL_RESULT_UNKNOWN',
    'EXECUTION_NOT_STOPPED',
    'COMMAND_CLOSED',
  ],
  validate_input: input,
  decode(value, original, fixed) {
    const row = receipt(value);
    require(
      row.task_id === original.parameters.task_id &&
        row.state_version === input(fixed).expected_state_version + 1,
    );
    return row;
  },
};
const repair = checked(
  shape({
    id,
    task_id: id,
    defect_ids: defectIds,
    source_candidate_id: id,
    operation_id: id,
    status: choices(states),
    created_at: time,
    result_candidate_id: nullable(id),
    ended_at: nullable(time),
    failure_code: nullable(nonempty),
  }),
  (row) => {
    require((row.status === 'SUCCEEDED') === (row.result_candidate_id !== null));
    require(row.result_candidate_id !== row.source_candidate_id);
    require(
      (['SUCCEEDED', 'FAILED', 'CANCELLED'] as const).some((s) => s === row.status) ===
        (row.ended_at !== null),
    );
    if (row.ended_at !== null) require(row.ended_at >= row.created_at);
  },
);
export function readRepairs(client: ApiClient, task: number, page: number, signal?: AbortSignal) {
  return readPage(
    client,
    repairPath(task),
    checked(repair, (row) => require(row.task_id === task)),
    (row) => row.id,
    [['page', String(page)]],
    page,
    signal,
    codeErrorPolicy(errors),
  );
}
export function readRepair(
  client: ApiClient,
  task: number,
  identity: number,
  signal?: AbortSignal,
) {
  return client.read(
    repairPath(task) + '/' + id(identity),
    checked(repair, (row) => require(row.task_id === task && row.id === identity)),
    [],
    signal,
    codeErrorPolicy(errors),
  );
}
export const decodeRepairOperation = checked(
  shape({
    id,
    task_id: id,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: id,
    session_id: id,
    operation_type: choices(['REPAIR']),
    idempotency_key: nonempty,
    expected_state_version: id,
    fixed_input: input,
    control_generation: id,
    status: choices(states),
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(nonempty),
    content_capture: nil,
    steps: array(
      shape({
        operation_id: id,
        step_no: id,
        step_type: choices(stages),
        status: choices(states),
        external_identity: nil,
        fixed_input: input,
        result_ref: nil,
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      4,
      4,
    ),
  }),
  (row) => {
    registeredCommand('POST', repairPath(row.task_id), row.idempotency_key);
    require(
      row.resource_id === row.task_id &&
        row.fixed_input.expected_state_version === row.expected_state_version,
    );
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === stages[index],
      );
      require(JSON.stringify(step.fixed_input) === JSON.stringify(row.fixed_input));
    }
  },
);
