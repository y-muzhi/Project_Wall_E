/** Coding stop command and the public original operation facts. */
import type { ApiClient, JsonObject } from './client.ts';
import { ApiUnknown, exact, object, positiveInteger } from './client.ts';
import type { CommandIdentity } from './code-command-registry.ts';
import { registeredCommand } from './code-command-registry.ts';
import type { CodeCommandBinding } from './code-command-snapshot.ts';
import { codeErrorPolicy } from './code-errors.ts';
import { decodeTaskView } from './code-task-creation.ts';
import {
  array,
  checked,
  choices,
  distinct,
  nullable,
  require,
  shape,
  text,
  time,
} from './decoding.ts';

export const taskStopPath = (taskId: number) => '/api/v1/code-tasks/' + taskId + '/terminate';
const receipt = shape({
  task_id: positiveInteger,
  operation_id: positiveInteger,
  operation_status: choices(['PENDING']),
  task_status: choices(['STOPPING']),
  state_version: positiveInteger,
});

function validateInput(value: JsonObject, original: CommandIdentity) {
  require(original.owner_module === 'CODING' && original.decoder_kind === 'APP-CODE-CMD-C37');
  const id = positiveInteger(original.parameters.task_id);
  const hasReason = Object.hasOwn(value, 'reason');
  const fields = exact(
    value,
    hasReason ? ['expected_state_version', 'reason'] : ['expected_state_version'],
  );
  positiveInteger(fields.expected_state_version);
  if (hasReason) require(text(fields.reason).trim().length > 0);
  return id;
}

function decodeStopResult(value: unknown, original: CommandIdentity, input: JsonObject) {
  const id = validateInput(input, original);
  if (Object.hasOwn(object(value), 'operation_id')) {
    const accepted = receipt(value);
    require(accepted.task_id === id);
    return accepted;
  }
  const task = decodeTaskView(value);
  require(task.id === id && task.status === 'TERMINATED');
  return task;
}

const errors = [
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
  'PRECONDITION_FAILED',
] as const;

export const STOP_CODE_TASK_BINDING: CodeCommandBinding<ReturnType<typeof decodeStopResult>> =
  Object.freeze({
    decoder_kind: 'APP-CODE-CMD-C37',
    success_status: Object.freeze([200, 202] as const),
    errors: Object.freeze(errors),
    validate_input: validateInput,
    decode: decodeStopResult,
  });

const steps = [
  'BLOCK_NEW',
  'REVOKE_GATEWAY',
  'ABORT_IF_APPLICABLE',
  'STOP_OWNED_ACTIVITY',
  'RECONCILE_WRITES',
  'CLEANUP',
] as const;
const fixed = shape({ task_id: positiveInteger, expected_state_version: positiveInteger });
function nil(value: unknown): null {
  require(value === null);
  return null;
}
const observations = shape({
  stop_observation_id: positiveInteger,
  cleanup_observation_id: positiveInteger,
});
export const decodeTaskStopOperation = checked(
  shape({
    id: positiveInteger,
    task_id: positiveInteger,
    testing_task_id: nil,
    resource_kind: choices(['TASK']),
    resource_id: positiveInteger,
    session_id: nullable(positiveInteger),
    operation_type: choices(['TERMINATE']),
    idempotency_key: text,
    expected_state_version: positiveInteger,
    fixed_input: fixed,
    control_generation: positiveInteger,
    status: choices(['PENDING', 'RUNNING', 'SUCCEEDED', 'UNKNOWN']),
    created_at: time,
    started_at: nullable(time),
    ended_at: nullable(time),
    failure_code: nullable(choices(['EXECUTION_NOT_STOPPED'])),
    steps: array(
      shape({
        operation_id: positiveInteger,
        step_no: positiveInteger,
        step_type: choices(steps),
        status: choices(['PENDING', 'RUNNING', 'SUCCEEDED', 'UNKNOWN']),
        external_identity: nil,
        fixed_input: fixed,
        result_ref: nullable(observations),
        started_at: nullable(time),
        ended_at: nullable(time),
        last_observed_at: nullable(time),
      }),
      steps.length,
      steps.length,
    ),
    content_capture: nil,
  }),
  (row) => {
    registeredCommand('POST', taskStopPath(row.task_id), row.idempotency_key);
    require(
      row.task_id === row.resource_id &&
        row.fixed_input.task_id === row.task_id &&
        row.fixed_input.expected_state_version === row.expected_state_version,
    );
    require((row.failure_code !== null) === (row.status === 'UNKNOWN'));
    const finished = row.status === 'SUCCEEDED';
    const { started_at: started, ended_at: ended } = row;
    require(
      finished === (ended !== null) &&
        (started === null || started >= row.created_at) &&
        (ended === null || (started !== null && started <= ended)) &&
        (row.status !== 'RUNNING' || started !== null) &&
        (row.status !== 'PENDING' || started === null),
    );
    distinct(row.steps.map((step) => step.step_no));
    let previousEnd = started;
    for (const [index, step] of row.steps.entries()) {
      require(
        step.operation_id === row.id &&
          step.step_no === index + 1 &&
          step.step_type === steps[index] &&
          step.fixed_input.task_id === row.task_id &&
          step.fixed_input.expected_state_version === row.expected_state_version &&
          (!finished || step.status === 'SUCCEEDED'),
      );
      const { started_at: stepStart, ended_at: stepEnd, last_observed_at: observed } = step;
      if (step.status === 'PENDING') {
        require(stepStart === null && stepEnd === null && observed === null);
      } else {
        require(
          previousEnd !== null &&
            stepStart !== null &&
            observed !== null &&
            previousEnd <= stepStart &&
            stepStart <= observed,
        );
        if (step.status === 'SUCCEEDED')
          require(
            stepEnd !== null &&
              stepStart <= stepEnd &&
              stepEnd <= observed &&
              (ended === null || observed <= ended),
          );
        else require(stepEnd === null);
      }
      previousEnd = stepEnd;
      if (finished && step.step_type === 'STOP_OWNED_ACTIVITY')
        require(
          step.result_ref !== null &&
            step.result_ref.stop_observation_id !== step.result_ref.cleanup_observation_id,
        );
      else require(step.result_ref === null);
    }
  },
);
export type TaskStopOperation = ReturnType<typeof decodeTaskStopOperation>;

export async function readTaskStopOperation(
  client: ApiClient,
  id: number,
  taskId: number,
  signal?: AbortSignal,
) {
  positiveInteger(id);
  positiveInteger(taskId);
  const result = await client.read(
    '/api/v1/code-operations/' + id,
    checked(decodeTaskStopOperation, (row) => require(row.id === id && row.task_id === taskId)),
    [],
    signal,
    codeErrorPolicy([
      'INVALID_INPUT',
      'NOT_FOUND',
      'CONFIG_NOT_READY',
      'STORAGE_UNAVAILABLE',
      'INTERNAL_ERROR',
    ]),
  );
  if (result.meta.pagination !== undefined) throw new ApiUnknown(false);
  return result;
}
